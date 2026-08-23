"""
tests/test_sast_integration.py – Testet den SAST-Scan im Verifikationslauf

Realer Fund: der security-Agent konnte Schwachstellen im selbst geschriebenen Code bisher
nur "plausibel" einschätzen (LLM-Vermutung), ohne echten statischen Scan.
agents/orchestrator.py._run_verification_loop() ruft jetzt echte
ProjectVerifier.check_sast() auf und macht das Ergebnis sichtbar – exakt dasselbe
Integrationsmuster wie test_dependency_audit_integration.py für den Dependency-Audit.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.verifier import SastFinding, SastReport, VerificationReport
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

    def _run(self, sast_reports: list[SastReport]):
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
            mock_verifier.check_sast.return_value = sast_reports

            status_logs: list[str] = []
            result = asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return result, status_logs, mock_verifier

        return _inner()

    def test_found_findings_are_reported_in_summary(self):
        report = SastReport(
            attempted=True, vulnerable=True, tool="bandit",
            findings=[
                SastFinding(file_path="app.py", line_number=5, message="shell=True",
                            rule="B602", severity="HIGH"),
            ],
        )
        result, logs, mock_verifier = self._run([report])

        mock_verifier.check_sast.assert_called_once()
        self.assertIn("bandit", result)
        self.assertIn("app.py", result)
        self.assertIn("B602", result)
        self.assertTrue(any("Sicherheits-Fund" in line for line in logs))

    def test_clean_scan_is_reported_in_summary(self):
        report = SastReport(attempted=True, vulnerable=False, tool="bandit")
        result, logs, mock_verifier = self._run([report])

        self.assertIn("bandit", result)
        self.assertIn("keine Sicherheits-Funde", result)

    def test_skipped_scan_adds_no_noise_to_summary(self):
        report = SastReport(
            attempted=False, vulnerable=False, tool="bandit",
            reason_skipped="`bandit` ist auf diesem System nicht installiert/verfügbar.",
        )
        result, logs, mock_verifier = self._run([report])

        self.assertNotIn("bandit", result)
        self.assertNotIn("Sicherheits-Fund", result)


if __name__ == "__main__":
    unittest.main()
