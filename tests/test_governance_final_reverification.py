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
        with patch("agents.orchestrator.governance.MAX_REVIEW_ITERATIONS", 1):
            return asyncio.run(self.orchestrator._run_governance_fix_loop(
                project_dir=self.temp_workspace,
                all_results=[code_reviewer_result],
                file_owners={"backend/db.py": "backend"},
                notify=lambda msg: None,
            ))

    def test_unconfirmed_fix_opens_backlog_ticket(self):
        with patch("agents.orchestrator.governance.upsert_ticket") as mock_ticket:
            results, summary, budget_aborted, cancelled = self._run(CRITICAL_CODE_REVIEWER_REPORT)

        self.assertFalse(budget_aborted)
        self.assertFalse(cancelled)
        self.assertIn("bestätigt der Re-Review WEITERHIN", summary)
        self.assertIn("Backlog-Ticket", summary)
        mock_ticket.assert_called_once()
        self.assertIn("unresolved-governance-critical-", mock_ticket.call_args.kwargs["ticket_id"])

    def test_confirmed_fix_reports_success_without_ticket(self):
        with patch("agents.orchestrator.governance.upsert_ticket") as mock_ticket:
            results, summary, budget_aborted, cancelled = self._run(CLEAN_CODE_REVIEWER_REPORT)

        self.assertIn("Re-Review nach Versuch 1 bestätigt", summary)
        self.assertNotIn("Fix nicht bestätigt", summary)
        mock_ticket.assert_not_called()

    def test_llm_confirms_but_structural_check_still_broken_opens_ticket(self):
        # Team-Optimierung (vollständige Umsetzung einer KI-Team-Retrospektive, echter Fund am
        # event_relay-Lauf 2026-09-06): der LLM-Re-Review hat real einen Fix als erledigt
        # akzeptiert, der einen frischen ImportError einführte (`from app.resilience import
        # resilience`, obwohl die globale Instanz im selben Fix entfernt wurde) - der Bruch fiel
        # erst im NÄCHSTEN, unabhängigen Lauf per echtem pytest auf. check_completeness() muss
        # das jetzt SELBST erkennen und ein Ticket eröffnen, auch wenn der LLM-Reviewer
        # (hier: CLEAN_CODE_REVIEWER_REPORT) "keine kritischen Probleme" meldet.
        app_dir = Path(self.temp_workspace) / "app"
        app_dir.mkdir()
        (app_dir / "resilience.py").write_text("class ResilienceManager:\n    pass\n", encoding="utf-8")
        (app_dir / "main.py").write_text("from app.resilience import resilience\n", encoding="utf-8")

        with patch("agents.orchestrator.governance.upsert_ticket") as mock_ticket:
            results, summary, budget_aborted, cancelled = self._run(CLEAN_CODE_REVIEWER_REPORT)

        self.assertIn("bestätigt der Re-Review WEITERHIN", summary)
        self.assertIn("Backlog-Ticket", summary)
        mock_ticket.assert_called_once()
        self.assertIn("resilience", mock_ticket.call_args.kwargs["detail"])

    def test_still_critical_escalates_to_dept_lead_before_ticket_and_can_resolve(self):
        # Team-Optimierung (Fortsetzung der Analyse 2026-09-06, echter Fund am event_relay-Lauf):
        # der Fixversuch hatte den URSPRÜNGLICHEN Befund zwar verändert, aber eine ANDERE
        # kritische Symptomatik derselben Ursache zurückgelassen ("ResilienceManager nicht
        # verdrahtet" → nach dem Fix: "ImportError, resilience keine globale Instanz mehr") -
        # der Zirkuit-Breaker (_no_progress, exakter Wiederholungs-Vergleich) griff dafür NIE,
        # der verpflichtende Re-Review eröffnete bisher SOFORT ein Ticket, ohne den zuständigen
        # Fachbereichsleiter mit einer geänderten Strategie zu versuchen. Löst dessen Team das
        # Problem, darf KEIN Ticket eröffnet werden.
        class _SequencedLLM:
            def __init__(self, texts: list[str]):
                self._texts = texts
                self._n = 0
                self.model_name = "fake-model"

            async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
                text = self._texts[min(self._n, len(self._texts) - 1)]
                self._n += 1
                return LLMResponse(text=text, model_name=self.model_name,
                                    prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[])

            async def generate_with_usage(self, prompt, system_prompt=None):
                return LLMResponse(text=self._texts[0], model_name=self.model_name,
                                    prompt_tokens=10, completion_tokens=5, total_tokens=15)

        self.orchestrator._agents["code_reviewer"]._llm = _SequencedLLM([
            CRITICAL_CODE_REVIEWER_REPORT,  # verpflichtender Re-Review nach Versuch 1 - weiterhin kritisch
            CLEAN_CODE_REVIEWER_REPORT,     # Recheck NACH der Eskalation an den Fachbereichsleiter
        ])
        code_reviewer_result = AgentResult(
            task_id="t2", agent_id="code_reviewer", agent_name="Code-Reviewer", success=True,
            content=CRITICAL_CODE_REVIEWER_REPORT,
        )
        with patch("agents.orchestrator.governance.upsert_ticket") as mock_ticket, \
             patch("agents.orchestrator.governance.MAX_REVIEW_ITERATIONS", 1):
            results, summary, budget_aborted, cancelled = asyncio.run(self.orchestrator._run_governance_fix_loop(
                project_dir=self.temp_workspace,
                all_results=[code_reviewer_result],
                file_owners={"backend/db.py": "backend"},
                notify=lambda msg: None,
            ))

        self.assertIn("Eskalation an Fachbereichsleiter", summary)
        self.assertIn("behob den Befund", summary)
        mock_ticket.assert_not_called()

    def test_still_critical_after_escalation_still_opens_ticket(self):
        # Gegenprobe: löst auch die Eskalation an den Fachbereichsleiter das Problem NICHT,
        # wird (wie bisher) ein Backlog-Ticket eröffnet - die Eskalation ersetzt die
        # menschliche Prüfung nicht, sie ist nur ein zusätzlicher Versuch davor.
        with patch("agents.orchestrator.governance.upsert_ticket") as mock_ticket:
            results, summary, budget_aborted, cancelled = self._run(CRITICAL_CODE_REVIEWER_REPORT)

        self.assertIn("Eskalation an Fachbereichsleiter behob den Befund NICHT", summary)
        self.assertIn("Backlog-Ticket", summary)
        mock_ticket.assert_called_once()

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
             patch("agents.orchestrator.governance.MAX_TASK_TOKENS", 100), \
             patch("agents.orchestrator.governance.MAX_REVIEW_ITERATIONS", 1):
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
