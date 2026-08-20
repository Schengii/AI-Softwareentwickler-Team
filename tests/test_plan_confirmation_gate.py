"""
tests/test_plan_confirmation_gate.py – Testet das Plan-Freigabe-Gate vor Ausführung

Bisher sah der Nutzer den zerlegten Aufgabenplan (welche Spezialisten, welche Teilaufgabe)
erst im FERTIGEN Ergebnis – kein Weg, vor dem eigentlichen (kostenpflichtigen) Lauf gegen-
zusteuern. agents/orchestrator.py.process() ruft jetzt optional einen
plan_confirmation_callback NACH der Zerlegung, aber VOR jeder Ausführung auf – nur wenn der
Plan mindestens PLAN_CONFIRMATION_MIN_TASKS Teilaufgaben umfasst, damit kleine Aufgaben
weiterhin ohne Rückfrage durchlaufen.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.workspace import WorkspaceManager


class _FakeToolCapableLLM:
    def __init__(self, text: str = "Fertig."):
        self._text = text
        self.model_name = "fake-model"

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[])

    async def generate_with_usage(self, prompt, system_prompt=None):
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15)


def _tasks(n: int) -> list[AgentTask]:
    agent_ids = ["backend", "frontend", "database", "tester", "devops"]
    return [
        AgentTask(task_id=f"t{i}", agent_id=agent_ids[i % len(agent_ids)], description=f"Teilaufgabe {i}")
        for i in range(n)
    ]


class TestPlanConfirmationGate(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, n_tasks: int, callback):
        @patch("agents.orchestrator.Orchestrator._run_department_hierarchy", new_callable=AsyncMock)
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_hierarchy):
            mock_decompose.return_value = ("Kurze Aufgabe", "gate_test_proj", _tasks(n_tasks))
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_hierarchy.return_value = ([], {}, False, False)

            result = asyncio.run(self.orchestrator.process(
                "Baue etwas", plan_confirmation_callback=callback,
            ))
            return result, mock_hierarchy

        return _inner()

    def test_small_plan_skips_confirmation_entirely(self):
        """Unter PLAN_CONFIRMATION_MIN_TASKS (Standard 3): kein Gate, Callback nie aufgerufen."""
        callback = AsyncMock(return_value=False)  # würde ablehnen - darf trotzdem nie gefragt werden
        result, mock_hierarchy = self._run(2, callback)

        callback.assert_not_called()
        mock_hierarchy.assert_called_once()
        self.assertNotIn("Abgebrochen", result)

    def test_large_plan_triggers_confirmation(self):
        callback = AsyncMock(return_value=True)
        self._run(3, callback)

        callback.assert_called_once()

    def test_declining_aborts_before_any_agent_runs(self):
        callback = AsyncMock(return_value=False)
        result, mock_hierarchy = self._run(4, callback)

        mock_hierarchy.assert_not_called()
        self.assertIn("Abgebrochen", result)

    def test_approving_continues_execution_normally(self):
        callback = AsyncMock(return_value=True)
        result, mock_hierarchy = self._run(4, callback)

        mock_hierarchy.assert_called_once()
        self.assertNotIn("Abgebrochen", result)

    def test_callback_receives_the_real_plan(self):
        callback = AsyncMock(return_value=True)
        self._run(3, callback)

        args = callback.call_args[0]
        task_summary, project_slug, agent_tasks = args
        self.assertEqual(task_summary, "Kurze Aufgabe")
        self.assertEqual(project_slug, "gate_test_proj")
        self.assertEqual(len(agent_tasks), 3)

    def test_no_callback_means_no_gate_regardless_of_plan_size(self):
        """None (Standard, z.B. Dashboard/MCP) - unverändertes Verhalten, kein Gate."""
        result, mock_hierarchy = self._run(5, None)

        mock_hierarchy.assert_called_once()
        self.assertNotIn("Abgebrochen", result)


if __name__ == "__main__":
    unittest.main()
