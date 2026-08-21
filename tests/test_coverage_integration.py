"""
tests/test_coverage_integration.py – Testet die Coverage-Anzeige im Verifikationslauf

Realer Fund: der tester-Agent nennt "Code-Coverage-Analyse" im eigenen System-Prompt als
Fähigkeit, aber nirgends im echten Code wurde sie je tatsächlich ausgeführt oder gemessen.
agents/orchestrator.py._run_verification_loop() ruft jetzt echte
ProjectVerifier.check_coverage() auf und macht das Ergebnis sichtbar - exakt dasselbe
Integrationsmuster wie test_lint_integration.py/test_dependency_audit_integration.py.
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

    def _run(self, coverage_report: CoverageReport):
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
            return result, status_logs

        return _inner()

    def test_coverage_above_threshold_is_reported_as_passed(self):
        report = CoverageReport(attempted=True, passed=True, percent_covered=85.0, threshold=70.0)
        result, logs = self._run(report)

        self.assertIn("85", result)
        self.assertTrue(any("Test-Coverage" in line for line in logs))

    def test_coverage_below_threshold_is_reported_as_warning(self):
        report = CoverageReport(attempted=True, passed=False, percent_covered=22.0, threshold=70.0)
        result, logs = self._run(report)

        self.assertIn("22", result)
        self.assertIn("unter", result)

    def test_unattempted_coverage_adds_no_noise_to_summary(self):
        report = CoverageReport(
            attempted=False, passed=True, percent_covered=0.0, threshold=70.0,
            reason_skipped="Keine Testdateien (test_*.py) im Projekt gefunden – Coverage nicht messbar.",
        )
        result, _logs = self._run(report)

        self.assertNotIn("Test-Coverage", result)

    def test_coverage_result_does_not_affect_verification_ok(self):
        """Coverage ist rein informativ (wie check_lint()) - eine niedrige Coverage darf
        die Push-Bereitschaft NICHT hart blockieren, nur sichtbar machen."""
        report = CoverageReport(attempted=True, passed=False, percent_covered=5.0, threshold=70.0)
        self._run(report)

        self.assertTrue(self.orchestrator.last_verification_ok)


if __name__ == "__main__":
    unittest.main()
