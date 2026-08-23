"""
tests/test_license_audit_integration.py – Testet den Lizenz-Scan im Verifikationslauf

Realer Fund: der compliance-Agent konnte die Lizenzen fremder Abhängigkeiten bisher nur
"plausibel" einschätzen (LLM-Vermutung), ohne echten Blick auf die installierten Pakete.
agents/orchestrator.py._run_verification_loop() ruft jetzt echte
ProjectVerifier.check_licenses() auf und macht das Ergebnis sichtbar – exakt dasselbe
Integrationsmuster wie test_dependency_audit_integration.py.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.verifier import LicenseAuditReport, LicenseFinding, VerificationReport
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


class TestLicenseAuditInVerificationLoop(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, license_reports: list[LicenseAuditReport]):
        @patch("agents.orchestrator.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            task = AgentTask(task_id="t1", agent_id="backend", description="Etwas bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "license_test_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
            )
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_licenses.return_value = license_reports

            status_logs: list[str] = []
            result = asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return result, status_logs, mock_verifier

        return _inner()

    def test_copyleft_finding_is_reported_in_summary(self):
        report = LicenseAuditReport(
            attempted=True, has_copyleft_risk=True, tool="pip-licenses",
            findings=[
                LicenseFinding(package="gpl-lib", version="1.0.0", license="GPLv3", copyleft=True),
                LicenseFinding(package="requests", version="2.31.0", license="Apache-2.0", copyleft=False),
            ],
        )
        result, logs, mock_verifier = self._run([report])

        mock_verifier.check_licenses.assert_called_once()
        self.assertIn("pip-licenses", result)
        self.assertIn("gpl-lib", result)
        self.assertTrue(any("Copyleft-Lizenz" in line for line in logs))

    def test_clean_scan_is_reported_in_summary(self):
        report = LicenseAuditReport(
            attempted=True, has_copyleft_risk=False, tool="pip-licenses",
            findings=[LicenseFinding(package="requests", version="2.31.0", license="Apache-2.0")],
        )
        result, logs, mock_verifier = self._run([report])

        self.assertIn("pip-licenses", result)
        self.assertIn("keine Copyleft-Lizenzen", result)

    def test_skipped_scan_adds_no_noise_to_summary(self):
        report = LicenseAuditReport(
            attempted=False, has_copyleft_risk=False, tool="pip-licenses",
            reason_skipped="`pip-licenses` ist auf diesem System nicht installiert/verfügbar.",
        )
        result, logs, mock_verifier = self._run([report])

        self.assertNotIn("pip-licenses", result)
        self.assertNotIn("Copyleft-Lizenz", result)


if __name__ == "__main__":
    unittest.main()
