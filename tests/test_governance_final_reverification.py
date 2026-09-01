"""
tests/test_governance_final_reverification.py – Testet den verpflichtenden Re-Review NACH dem
letzten erlaubten Fix-Versuch in agents/orchestrator/verification.py._run_governance_fix_loop()
(Punkt 4 einer Team-Retrospektive).

Realer Fund: bisher wurde ein Fix im FINALEN Versuch (attempt == MAX_REVIEW_ITERATIONS) NIE mehr
gegengeprüft - nur Zwischen-Versuche liefen in eine erneute Runde mit Recheck. Ein Fix im
letzten Versuch galt damit unbesehen als erledigt, selbst bei sicherheitskritischen Befunden.
Diese Tests beweisen direkt (kein voller process()-Lauf nötig, exakt nach dem Muster von
tests/test_governance_fix_loop.py), dass jetzt IMMER ein abschließender, günstiger Nur-Lese-
Recheck läuft und bei weiterhin bestehendem kritischem Befund ein Backlog-Ticket eröffnet wird.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core import team_memory
from core.llm_factory import LLMResponse
from core.message_bus import AgentResult
from core.workspace import WorkspaceManager

CRITICAL_CODE_REVIEWER_REPORT = """## Code-Review Report

### 🔴 Kritische Probleme (müssen behoben werden)
SQL-Injection in `backend/db.py`: die Funktion `get_user()` baut die Query per
String-Concatenation statt parametrisiert.
"""

CLEAN_CODE_REVIEWER_REPORT = """## Code-Review Report

### 🔴 Kritische Probleme (müssen behoben werden)
Keine kritischen Probleme gefunden.
"""


class _FakeLLM:
    def __init__(self, text: str = "Fertig."):
        self._text = text
        self.model_name = "fake-model"

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[])

    async def generate_with_usage(self, prompt, system_prompt=None):
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15)


class TestGovernanceFinalReverification(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        self.orchestrator.last_project_slug = "gov_final_recheck_proj"
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeLLM()
        # record_lesson() (core/team_memory.py) schreibt sonst in die ECHTE, repo-weite
        # memory/team_lessons.jsonl - hier auf eine Wegwerfdatei umgeleitet, damit Testläufe
        # nicht versehentlich echte Team-Lektionen mit Fake-Testdaten verunreinigen.
        self._team_memory_patch = patch.object(team_memory, "TEAM_MEMORY_FILE", Path(self.temp_workspace) / "team_lessons.jsonl")
        self._team_memory_patch.start()

    def tearDown(self):
        self._team_memory_patch.stop()
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, code_reviewer_recheck_text: str):
        self.orchestrator._agents["code_reviewer"]._llm = _FakeLLM(text=code_reviewer_recheck_text)
        code_reviewer_result = AgentResult(
            task_id="t2", agent_id="code_reviewer", agent_name="Code-Reviewer", success=True,
            content=CRITICAL_CODE_REVIEWER_REPORT,
        )
        with patch("agents.orchestrator.verification.MAX_REVIEW_ITERATIONS", 1):
            return asyncio.run(self.orchestrator._run_governance_fix_loop(
                project_dir=self.temp_workspace,
                all_results=[code_reviewer_result],
                file_owners={"backend/db.py": "backend"},
                notify=lambda msg: None,
            ))

    def test_unconfirmed_fix_opens_backlog_ticket(self):
        with patch("agents.orchestrator.verification.upsert_ticket") as mock_ticket:
            results, summary, budget_aborted, cancelled = self._run(CRITICAL_CODE_REVIEWER_REPORT)

        self.assertFalse(budget_aborted)
        self.assertFalse(cancelled)
        self.assertIn("bestätigt der Re-Review WEITERHIN", summary)
        self.assertIn("Backlog-Ticket", summary)
        mock_ticket.assert_called_once()
        self.assertIn("unresolved-governance-critical-", mock_ticket.call_args.kwargs["ticket_id"])

    def test_confirmed_fix_reports_success_without_ticket(self):
        with patch("agents.orchestrator.verification.upsert_ticket") as mock_ticket:
            results, summary, budget_aborted, cancelled = self._run(CLEAN_CODE_REVIEWER_REPORT)

        self.assertIn("Re-Review nach Versuch 1 bestätigt", summary)
        self.assertNotIn("Fix nicht bestätigt", summary)
        mock_ticket.assert_not_called()

    def test_oversized_fix_task_stops_loop_before_final_recheck(self):
        # Punkt 2 einer Team-Retrospektive: ein einzelner ausufernder Fix-Task darf nicht
        # unbegrenzt weiter eskalieren (auch nicht bis zum verpflichtenden Re-Review) - das
        # Pro-Task-Budget-Warnsignal stoppt die Schleife VOR dem finalen Recheck.
        code_reviewer_result = AgentResult(
            task_id="t2", agent_id="code_reviewer", agent_name="Code-Reviewer", success=True,
            content=CRITICAL_CODE_REVIEWER_REPORT,
        )

        async def _oversized_run(agent_tasks, notify=None):
            return [AgentResult(
                task_id=agent_tasks[0].task_id, agent_id="backend", agent_name="Backend",
                success=True, content="Fix versucht.", total_tokens=999_999,
            )]

        with patch.object(self.orchestrator, "_run_agents_parallel", side_effect=_oversized_run), \
             patch("agents.orchestrator.verification.MAX_TASK_TOKENS", 100), \
             patch("agents.orchestrator.verification.MAX_REVIEW_ITERATIONS", 1):
            results, summary, budget_aborted, cancelled = asyncio.run(self.orchestrator._run_governance_fix_loop(
                project_dir=self.temp_workspace,
                all_results=[code_reviewer_result],
                file_owners={"backend/db.py": "backend"},
                notify=lambda msg: None,
            ))

        self.assertIn("Pro-Task-Budget", summary)
        self.assertNotIn("Re-Review", summary)


if __name__ == "__main__":
    unittest.main()
