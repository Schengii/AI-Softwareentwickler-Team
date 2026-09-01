"""
tests/test_permission_blocked_clarification_fix.py – Testet
agents/orchestrator/verification.py._run_permission_blocked_clarification_fix()

Realer Fund (omnichat-Projekt, .ai_team_status.json): der security-Agent identifizierte ein
echtes kritisches Problem (Pydantic-v2-Migration, CORS-Härtung), hatte in diesem Aufruf aber
keine Schreibrechte und griff statt zu einem normalen "Kritisch"-Befund (den
_run_governance_fix_loop erkannt hätte) zu `ask_human_for_clarification` mit der Frage "Wie
erhalte ich Schreibrechte...?". Diese Frage blieb bisher unbeantwortet in den open_questions
liegen, statt automatisch an einen schreibberechtigten Agenten weitergeroutet zu werden - genau
das behebt _run_permission_blocked_clarification_fix() und wird hier direkt getestet, exakt
nach dem Muster von tests/test_governance_fix_loop.py.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agents.orchestrator.budget as orch_budget_module
from agents.orchestrator import Orchestrator
from core import team_memory
from core.message_bus import AgentResult
from core.token_guard import TokenGuard
from core.workspace import WorkspaceManager

PERMISSION_BLOCKED_QUESTION = (
    "Wie erhalte ich Schreibrechte, um die identifizierten kritischen Sicherheitslücken "
    "(CORS-Härtung) in `app/main.py` zu beheben? Ich habe keine Schreibrechte."
)

GENUINE_BUSINESS_QUESTION = (
    "Soll die Registrierung eine E-Mail-Verifikation erfordern, wie in den Anforderungen impliziert?"
)


class _FakeToolCapableLLM:
    def __init__(self, text: str = "Fertig."):
        self._text = text
        self.model_name = "fake-model"

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        from core.llm_factory import LLMResponse
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[])

    async def generate_with_usage(self, prompt, system_prompt=None):
        from core.llm_factory import LLMResponse
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15)


class TestPermissionBlockedClarificationFix(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()
        # record_lesson() (core/team_memory.py) schreibt sonst in die ECHTE, repo-weite
        # memory/team_lessons.jsonl - hier auf eine Wegwerfdatei umgeleitet, damit Testläufe
        # nicht versehentlich echte Team-Lektionen mit Fake-Testdaten verunreinigen.
        self._team_memory_patch = patch.object(team_memory, "TEAM_MEMORY_FILE", Path(self.temp_workspace) / "team_lessons.jsonl")
        self._team_memory_patch.start()

    def tearDown(self):
        self._team_memory_patch.stop()
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def test_permission_blocked_question_dispatches_fix_to_file_owner(self):
        security_result = AgentResult(
            task_id="t2", agent_id="security", agent_name="Security", success=True,
            content="Sicherheitsreview durchgeführt.",
            needs_human_input=True, clarification_questions=[PERMISSION_BLOCKED_QUESTION],
        )

        results, summary, budget_aborted, cancelled = asyncio.run(
            self.orchestrator._run_permission_blocked_clarification_fix(
                project_dir=self.temp_workspace,
                all_results=[security_result],
                file_owners={"app/main.py": "backend"},
                notify=lambda msg: None,
            )
        )

        self.assertFalse(budget_aborted)
        self.assertFalse(cancelled)
        self.assertIn("schreibgeschützt blockierte Rückfrage", summary)
        self.assertIn("an backend zurückgespielt", summary)
        # Die behobene Rückfrage darf nicht mehr als unbeantwortet im Ergebnis stehen.
        self.assertEqual(security_result.clarification_questions, [])
        self.assertTrue(any(r.agent_id == "backend" for r in results))

    def test_genuine_business_question_is_left_untouched(self):
        pm_result = AgentResult(
            task_id="t2", agent_id="product_owner", agent_name="Product Owner", success=True,
            content="Anforderungen geprüft.",
            needs_human_input=True, clarification_questions=[GENUINE_BUSINESS_QUESTION],
        )

        results, summary, budget_aborted, cancelled = asyncio.run(
            self.orchestrator._run_permission_blocked_clarification_fix(
                project_dir=self.temp_workspace,
                all_results=[pm_result],
                file_owners={},
                notify=lambda msg: None,
            )
        )

        self.assertEqual(summary, "")
        self.assertEqual(pm_result.clarification_questions, [GENUINE_BUSINESS_QUESTION])

    def test_unroutable_question_is_reported_but_kept(self):
        security_result = AgentResult(
            task_id="t2", agent_id="security", agent_name="Security", success=True,
            content="Sicherheitsreview durchgeführt.",
            needs_human_input=True,
            clarification_questions=["Ich habe keine Schreibrechte, um das Projekt insgesamt zu härten."],
        )

        results, summary, budget_aborted, cancelled = asyncio.run(
            self.orchestrator._run_permission_blocked_clarification_fix(
                project_dir=self.temp_workspace,
                all_results=[security_result],
                file_owners={"app/main.py": "backend"},
                notify=lambda msg: None,
            )
        )

        self.assertIn("ohne eindeutigen Datei-Bezug", summary)
        self.assertEqual(len(security_result.clarification_questions), 1)

    def test_budget_exceeded_skips_dispatch(self):
        fresh_guard = TokenGuard()
        fresh_guard.record_usage("fake-model", 5, 0)
        security_result = AgentResult(
            task_id="t2", agent_id="security", agent_name="Security", success=True,
            content="Sicherheitsreview durchgeführt.",
            needs_human_input=True, clarification_questions=[PERMISSION_BLOCKED_QUESTION],
        )

        with patch.object(orch_budget_module, "token_guard", fresh_guard), \
             patch.object(orch_budget_module, "MAX_RUN_TOKENS", 1):
            results, summary, budget_aborted, cancelled = asyncio.run(
                self.orchestrator._run_permission_blocked_clarification_fix(
                    project_dir=self.temp_workspace,
                    all_results=[security_result],
                    file_owners={"app/main.py": "backend"},
                    notify=lambda msg: None,
                    run_start_tokens=0,
                )
            )

        self.assertTrue(budget_aborted)
        self.assertFalse(cancelled)
        self.assertEqual(summary, "")
        self.assertEqual(security_result.clarification_questions, [PERMISSION_BLOCKED_QUESTION])

    def test_unconfirmed_fix_opens_backlog_ticket(self):
        # Punkt 4 einer Team-Retrospektive: security (der ursprünglich blockierte Agent) prüft
        # den Fix read-only nach - meldet er weiterhin "Kritisch", wird ein Backlog-Ticket eröffnet
        # statt den Fix-Dispatch ungeprüft als erledigt zu behandeln.
        self.orchestrator._agents["security"]._llm = _FakeToolCapableLLM(
            text="### 🔴 Kritische Probleme (müssen behoben werden)\nCORS weiterhin offen."
        )
        security_result = AgentResult(
            task_id="t2", agent_id="security", agent_name="Security", success=True,
            content="Sicherheitsreview durchgeführt.",
            needs_human_input=True, clarification_questions=[PERMISSION_BLOCKED_QUESTION],
        )

        with patch("agents.orchestrator.verification.upsert_ticket") as mock_ticket:
            results, summary, budget_aborted, cancelled = asyncio.run(
                self.orchestrator._run_permission_blocked_clarification_fix(
                    project_dir=self.temp_workspace,
                    all_results=[security_result],
                    file_owners={"app/main.py": "backend"},
                    notify=lambda msg: None,
                )
            )

        self.assertIn("Re-Review bestätigt den Fix NICHT", summary)
        mock_ticket.assert_called_once()
        self.assertIn("unresolved-permission-blocked-", mock_ticket.call_args.kwargs["ticket_id"])

    def test_confirmed_fix_reports_success_without_ticket(self):
        self.orchestrator._agents["security"]._llm = _FakeToolCapableLLM(text="Alles behoben.")
        security_result = AgentResult(
            task_id="t2", agent_id="security", agent_name="Security", success=True,
            content="Sicherheitsreview durchgeführt.",
            needs_human_input=True, clarification_questions=[PERMISSION_BLOCKED_QUESTION],
        )

        with patch("agents.orchestrator.verification.upsert_ticket") as mock_ticket:
            results, summary, budget_aborted, cancelled = asyncio.run(
                self.orchestrator._run_permission_blocked_clarification_fix(
                    project_dir=self.temp_workspace,
                    all_results=[security_result],
                    file_owners={"app/main.py": "backend"},
                    notify=lambda msg: None,
                )
            )

        self.assertIn("Re-Review bestätigt: Fix erfolgreich", summary)
        mock_ticket.assert_not_called()

    def test_oversized_fix_task_warns_and_skips_reverification(self):
        self.orchestrator._agents["backend"]._llm = _FakeToolCapableLLM(text="Fertig.")
        security_result = AgentResult(
            task_id="t2", agent_id="security", agent_name="Security", success=True,
            content="Sicherheitsreview durchgeführt.",
            needs_human_input=True, clarification_questions=[PERMISSION_BLOCKED_QUESTION],
        )

        async def _oversized_run(agent_tasks, notify=None):
            return [AgentResult(
                task_id=agent_tasks[0].task_id, agent_id="backend", agent_name="Backend",
                success=True, content="Fix versucht.", total_tokens=999_999,
            )]

        with patch.object(self.orchestrator, "_run_agents_parallel", side_effect=_oversized_run), \
             patch("agents.orchestrator.verification.MAX_TASK_TOKENS", 100):
            results, summary, budget_aborted, cancelled = asyncio.run(
                self.orchestrator._run_permission_blocked_clarification_fix(
                    project_dir=self.temp_workspace,
                    all_results=[security_result],
                    file_owners={"app/main.py": "backend"},
                    notify=lambda msg: None,
                )
            )

        self.assertIn("Pro-Task-Budget", summary)
        self.assertNotIn("Re-Review", summary)


if __name__ == "__main__":
    unittest.main()
