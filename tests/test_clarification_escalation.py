"""
tests/test_clarification_escalation.py – Testet die Mid-Task-Eskalation an einen Menschen
(agents/orchestrator.py, core/agent_toolbox.py.ask_human_for_clarification)

Realer Fund: Rückfragen (core/task_manager.py needs_clarification) passierten bisher NUR VOR
dem Start, wenn die Gesamtaufgabe zu vage war. Sobald Agenten liefen, gab es kein "Moment, das
ist wirklich mehrdeutig" mehr - nur Weiterarbeiten mit einer geratenen Annahme. Dieser Test
prüft den kompletten Weg vom Werkzeug-Aufruf eines einzelnen Agenten bis zur sichtbaren
Kennzeichnung im Gesamtergebnis von Orchestrator.process().
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse, ToolCall
from core.message_bus import AgentTask
from core.verifier import VerificationReport
from core.workspace import WorkspaceManager


class _FakeToolCapableLLM:
    """Meldet beim ERSTEN Werkzeug-Aufruf eine Rückfrage, danach eine normale Abschlussantwort."""

    def __init__(self, ask_clarification: bool = False):
        self._ask_clarification = ask_clarification
        self.model_name = "fake-model"
        self._calls = 0

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        self._calls += 1
        if self._ask_clarification and self._calls == 1:
            return LLMResponse(
                text="", model_name=self.model_name, prompt_tokens=20, completion_tokens=10, total_tokens=30,
                tool_calls=[ToolCall(id="call_1", name="ask_human_for_clarification", arguments={
                    "question": "Welche Zahlungsanbieter sollen unterstützt werden?",
                })],
            )
        return LLMResponse(
            text="Fertig.", model_name=self.model_name, prompt_tokens=10, completion_tokens=5,
            total_tokens=15, tool_calls=[],
        )

    async def generate_with_usage(self, prompt, system_prompt=None):
        return LLMResponse(text="Fertig.", model_name=self.model_name, prompt_tokens=10, completion_tokens=5, total_tokens=15)


class TestClarificationEscalation(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, ask_clarification: bool):
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM(ask_clarification=ask_clarification)

        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            mock_decompose.return_value = (
                "Kurze Aufgabe", "clarify_test_proj",
                [AgentTask(task_id="t1", agent_id="backend", description="Baue Zahlungsabwicklung")],
            )
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
            )
            status_logs: list[str] = []
            result = asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return result, status_logs

        return _inner()

    def test_clarification_request_is_surfaced_in_result_and_status(self):
        result, logs = self._run(ask_clarification=True)

        self.assertTrue(self.orchestrator.last_needs_human_input)
        self.assertEqual(len(self.orchestrator.last_clarification_questions), 1)
        self.assertIn("Zahlungsanbieter", self.orchestrator.last_clarification_questions[0])
        self.assertIn("Offene Rückfragen", result)
        self.assertTrue(any("offener" in line and "Rückfrage" in line for line in logs))

    def test_normal_run_without_clarification_is_unaffected(self):
        result, logs = self._run(ask_clarification=False)

        self.assertFalse(self.orchestrator.last_needs_human_input)
        self.assertEqual(self.orchestrator.last_clarification_questions, [])
        self.assertNotIn("Offene Rückfragen", result)
        self.assertTrue(any("Fertig!" in line and "Rückfrage" not in line for line in logs))


if __name__ == "__main__":
    unittest.main()
