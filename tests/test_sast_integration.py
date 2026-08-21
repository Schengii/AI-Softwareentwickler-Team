"""
tests/test_sast_integration.py – Testet die SAST-Anzeige im Verifikationslauf

Realer Fund bei einer Bestandsaufnahme des eigenen Teams: check_dependency_vulnerabilities()
prüft nur FREMDE Abhängigkeiten, die selbst geschriebene Code-LOGIK hatte nie einen echten
statischen Sicherheits-Scan. agents/orchestrator.py._run_verification_loop() ruft jetzt echte
ProjectVerifier.check_sast() auf - exakt dasselbe Integrationsmuster wie
test_lint_integration.py/test_coverage_integration.py.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.verifier import SastIssue, SastReport, VerificationReport
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


class TestSastInVerificationLoop(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, sast_report: SastReport):
        @patch("agents.orchestrator.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            task = AgentTask(task_id="t1", agent_id="backend", description="Etwas bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "sast_test_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
            )
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_lint.return_value = []
            mock_verifier.check_sast.return_value = sast_report

            status_logs: list[str] = []
            result = asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return result, status_logs

        return _inner()

    def test_found_sast_issues_are_reported_in_summary(self):
        report = SastReport(
            attempted=True, passed=False,
            issues=[SastIssue(file_path="app.py", line_number=12, message="SQLi", severity="MEDIUM", rule="B608")],
        )
        result, logs = self._run(report)

        self.assertIn("bandit", result)
        self.assertIn("app.py", result)
        self.assertIn("B608", result)
        self.assertTrue(any("Sicherheits-Fund" in line for line in logs))

    def test_clean_sast_is_reported_in_summary(self):
        report = SastReport(attempted=True, passed=True)
        result, _logs = self._run(report)

        self.assertIn("bandit", result)
        self.assertIn("keine statischen Sicherheits-Funde", result)

    def test_skipped_sast_adds_no_noise_to_summary(self):
        report = SastReport(attempted=False, passed=True, reason_skipped="bandit nicht installierbar.")
        result, _logs = self._run(report)

        self.assertNotIn("Sicherheits-Fund", result)

    def test_sast_result_does_not_affect_verification_ok(self):
        """SAST ist rein informativ (wie check_lint()) - Funde duerfen die Push-Bereitschaft
        NICHT hart blockieren, nur sichtbar machen."""
        report = SastReport(
            attempted=True, passed=False,
            issues=[SastIssue(file_path="app.py", line_number=1, message="x", severity="HIGH", rule="B105")],
        )
        self._run(report)

        self.assertTrue(self.orchestrator.last_verification_ok)


if __name__ == "__main__":
    unittest.main()
