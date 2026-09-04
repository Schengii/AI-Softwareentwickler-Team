"""
tests/test_repeated_failure_reescalation.py – Testet die deterministische architect-
Zwangs-Einplanung nach wiederholtem Scheitern in agents/orchestrator/__init__.py.process()
(Punkt 1 einer Team-Retrospektive).

Realer Hintergrund: has_repeated_failure()/count_consecutive_failed_runs() lösten bisher nur
einen informativen Prompt-Hinweis aus (core/project_status.py.format_context_for_agents()) -
kein harter Garant, dass das Modell ihn tatsächlich befolgt. Ab 2 Fehlschlägen in Folge wird
architect jetzt DETERMINISTISCH (kein LLM-Entscheid) als zusätzliche, erste Teilaufgabe
eingeplant, falls er nicht ohnehin schon Teil des vom Modell erstellten Plans ist.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.verifier import VerificationReport
from core.workspace import WorkspaceManager


class _FakeLLM:
    def __init__(self, text: str = "Fertig."):
        self._text = text
        self.model_name = "fake-model"
        self.call_count = 0

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        self.call_count += 1
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[])

    async def generate_with_usage(self, prompt, system_prompt=None):
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15)


class TestRepeatedFailureReescalation(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, consecutive_failures: int):
        @patch("agents.orchestrator.count_consecutive_failed_runs", return_value=consecutive_failures)
        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls, mock_consecutive):
            tasks = [AgentTask(task_id="t1", agent_id="backend", description="Baue etwas weiter")]
            mock_decompose.return_value = ("Kurze Aufgabe", "repeated_failure_proj", tasks)
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
            )
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_lint.return_value = []

            status_logs: list[str] = []
            result = asyncio.run(self.orchestrator.process("Baue etwas weiter", status_callback=status_logs.append))
            return result, status_logs

        return _inner()

    def test_two_consecutive_failures_force_architect_into_plan(self):
        result, logs = self._run(consecutive_failures=2)

        self.assertTrue(any("architect wird zusätzlich eingeplant" in line for line in logs))
        self.assertGreater(self.orchestrator._agents["architect"]._llm.call_count, 0)

    def test_no_prior_failures_leaves_plan_untouched(self):
        result, logs = self._run(consecutive_failures=0)

        self.assertFalse(any("architect wird zusätzlich eingeplant" in line for line in logs))
        self.assertEqual(self.orchestrator._agents["architect"]._llm.call_count, 0)

    def test_architect_already_in_plan_is_not_duplicated(self):
        @patch("agents.orchestrator.count_consecutive_failed_runs", return_value=2)
        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls, mock_consecutive):
            tasks = [
                AgentTask(task_id="t1", agent_id="architect", description="Architektur klären"),
                AgentTask(task_id="t2", agent_id="backend", description="Baue etwas weiter"),
            ]
            mock_decompose.return_value = ("Kurze Aufgabe", "repeated_failure_proj2", tasks)
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
            )
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_lint.return_value = []

            status_logs: list[str] = []
            asyncio.run(self.orchestrator.process("Baue etwas weiter", status_callback=status_logs.append))
            return status_logs

        logs = _inner()
        self.assertFalse(any("architect wird zusätzlich eingeplant" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
