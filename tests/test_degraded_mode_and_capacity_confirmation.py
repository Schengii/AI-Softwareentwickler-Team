"""
tests/test_degraded_mode_and_capacity_confirmation.py – Testet P5-1 Punkte 1 und 3
(ROADMAP_TEMP.md, "Alle Premium-Modelle liegen auf Cooldown - das Team läuft dauerhaft im
Notbetrieb")

1. Ehrlicher Degraded-Mode: ist HEAVY_MODEL beim Lauf-Start nicht erreichbar, wird das sichtbar
   markiert (Notification, Abschlussbericht, run_history) statt stillschweigend mit schwächeren
   Modellen weiterzumachen.
2. Kapazitäts-Gate schärfen: würden >= 50% der eingeplanten Rollen herabgestuft starten
   müssen, wird zusätzlich aktiv nachgefragt (dasselbe Bestätigungs-Gate wie die reguläre
   Plan-Freigabe), ob der Lauf trotzdem starten soll.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from agents.orchestrator import Orchestrator
from core.capacity_gate import CapacityAssessment
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.workspace import WorkspaceManager


class _FakeToolCapableLLM:
    def __init__(self, text: str = "Fertig."):
        self._text = text
        self.model_name = "fake-model"

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        return LLMResponse(text=self._text, model_name=self.model_name, prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[])

    async def generate_with_usage(self, prompt, system_prompt=None):
        return LLMResponse(text=self._text, model_name=self.model_name, prompt_tokens=10, completion_tokens=5, total_tokens=15)


class TestDegradedModeAndCapacityConfirmation(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, *, heavy_unreachable_reason: str | None, mostly_downgraded: bool, callback=None):
        capacity = CapacityAssessment()
        capacity.downgraded_agent_ids = ["backend"] if mostly_downgraded else []
        capacity.planned_role_count = 1

        @patch("agents.orchestrator.model_unreachable_reason", return_value=heavy_unreachable_reason)
        @patch("agents.orchestrator.assess_run_capacity", return_value=capacity)
        @patch("agents.orchestrator.Orchestrator._run_department_hierarchy", new_callable=AsyncMock)
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        @patch("agents.orchestrator.record_run_history")
        def _inner(mock_record_run, mock_synthesize, mock_decompose, mock_hierarchy, _mock_capacity, _mock_unreachable):
            mock_decompose.return_value = ("Kurze Aufgabe", "degraded_test_proj", [AgentTask(task_id="t1", agent_id="backend", description="x")])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_hierarchy.return_value = ([], {}, False, False)

            result = asyncio.run(self.orchestrator.process(
                "Baue etwas", plan_confirmation_callback=callback,
            ))
            return result, mock_hierarchy, mock_record_run

        return _inner()

    def test_degraded_run_is_marked_in_notification_and_run_history(self):
        result, mock_hierarchy, mock_record_run = self._run(
            heavy_unreachable_reason="Kontingent für 'claude-sonnet-5' erschöpft", mostly_downgraded=False,
        )

        self.assertIn("Degradierter Lauf", result)
        mock_record_run.assert_called_once()
        self.assertTrue(mock_record_run.call_args.kwargs["degraded"])

    def test_non_degraded_run_is_not_marked(self):
        result, mock_hierarchy, mock_record_run = self._run(heavy_unreachable_reason=None, mostly_downgraded=False)

        self.assertNotIn("Degradierter Lauf", result)
        self.assertFalse(mock_record_run.call_args.kwargs["degraded"])

    def test_mostly_downgraded_asks_for_confirmation_and_aborts_on_decline(self):
        callback = AsyncMock(return_value=False)
        result, mock_hierarchy, _mock_record_run = self._run(
            heavy_unreachable_reason=None, mostly_downgraded=True, callback=callback,
        )

        callback.assert_called_once()
        mock_hierarchy.assert_not_called()
        self.assertIn("Abgebrochen", result)

    def test_mostly_downgraded_continues_on_approval(self):
        callback = AsyncMock(return_value=True)
        result, mock_hierarchy, _mock_record_run = self._run(
            heavy_unreachable_reason=None, mostly_downgraded=True, callback=callback,
        )

        callback.assert_called_once()
        mock_hierarchy.assert_called_once()
        self.assertNotIn("Abgebrochen", result)

    def test_mostly_downgraded_without_callback_just_warns_and_continues(self):
        # Unbeaufsichtigte Läufe (z.B. --work-backlog) haben keinen Callback - Warnung genügt.
        result, mock_hierarchy, _mock_record_run = self._run(
            heavy_unreachable_reason=None, mostly_downgraded=True, callback=None,
        )

        mock_hierarchy.assert_called_once()
        self.assertNotIn("Abgebrochen", result)


if __name__ == "__main__":
    unittest.main()
