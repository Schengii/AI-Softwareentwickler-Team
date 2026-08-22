"""
tests/test_coverage_integration.py – Testet die Coverage-Schwelle im Verifikationslauf

Realer Fund: die Verifikation maß bisher nur Pass/Fail, keine Abdeckung.
agents/orchestrator.py._run_verification_loop() ruft jetzt (opt-in über config.MIN_TEST_COVERAGE)
echte ProjectVerifier.check_coverage() auf und setzt verification_ok explizit zurück, wenn die
konfigurierte Schwelle unterschritten wird - exakt dasselbe Integrationsmuster wie
test_dependency_audit_integration.py/test_lint_integration.py.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.verifier import CoverageReport, VerificationReport
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


class TestCoverageInVerificationLoop(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, coverage_report: CoverageReport, min_coverage: float):
        @patch("agents.orchestrator.MIN_TEST_COVERAGE", min_coverage)
        @patch("agents.orchestrator.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            task = AgentTask(task_id="t1", agent_id="backend", description="Etwas bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "coverage_test_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
            )
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_lint.return_value = []
            mock_verifier.check_coverage.return_value = coverage_report

            status_logs: list[str] = []
            result = asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return result, status_logs, mock_verifier

        return _inner()

    def test_coverage_above_threshold_keeps_verification_ok(self):
        result, logs, mock_verifier = self._run(CoverageReport(attempted=True, percent=85.0), min_coverage=70.0)

        mock_verifier.check_coverage.assert_called_once()
        self.assertIn("85.0%", result)
        self.assertTrue(any("Fertig!" in line and "NICHT" not in line for line in logs))

    def test_coverage_below_threshold_flips_verification_ok_to_false(self):
        result, logs, mock_verifier = self._run(CoverageReport(attempted=True, percent=40.0), min_coverage=70.0)

        self.assertIn("40.0%", result)
        self.assertIn("UNTER", result)
        self.assertTrue(any("NICHT verifiziert" in line for line in logs))

    def test_disabled_threshold_skips_coverage_check_entirely(self):
        result, logs, mock_verifier = self._run(CoverageReport(attempted=True, percent=10.0), min_coverage=0)

        mock_verifier.check_coverage.assert_not_called()
        self.assertTrue(any("Fertig!" in line and "NICHT" not in line for line in logs))


if __name__ == "__main__":
    unittest.main()
