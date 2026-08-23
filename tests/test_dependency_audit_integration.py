"""
tests/test_dependency_audit_integration.py – Testet den Dependency-Audit im Verifikationslauf

Realer Fund: der security-Agent konnte Abhängigkeits-Risiken bisher nur "plausibel"
einschätzen (LLM-Vermutung), ohne echten Abgleich gegen eine CVE-/Advisory-Datenbank.
agents/orchestrator.py._run_verification_loop() ruft jetzt echte
ProjectVerifier.check_dependency_vulnerabilities() auf und macht das Ergebnis sichtbar –
exakt dasselbe Integrationsmuster wie test_docker_build_integration.py für den Docker-Build.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.verifier import DependencyAuditReport, DependencyVulnerability, VerificationReport
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


class TestDependencyAuditInVerificationLoop(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, audit_reports: list[DependencyAuditReport]):
        @patch("agents.orchestrator.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            task = AgentTask(task_id="t1", agent_id="backend", description="Etwas bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "audit_test_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
            )
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = audit_reports

            status_logs: list[str] = []
            result = asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return result, status_logs, mock_verifier

        return _inner()

    def test_found_vulnerabilities_are_reported_in_summary(self):
        report = DependencyAuditReport(
            attempted=True, vulnerable=True, tool="pip-audit",
            vulnerabilities=[
                DependencyVulnerability(package="urllib3", version="1.24.1",
                                         vulnerability_id="PYSEC-2019-133", description="..."),
            ],
        )
        result, logs, mock_verifier = self._run([report])

        mock_verifier.check_dependency_vulnerabilities.assert_called_once()
        self.assertIn("pip-audit", result)
        self.assertIn("urllib3", result)
        self.assertIn("PYSEC-2019-133", result)
        self.assertTrue(any("bekannte Schwachstelle" in line for line in logs))

    def test_clean_scan_is_reported_in_summary(self):
        report = DependencyAuditReport(attempted=True, vulnerable=False, tool="npm audit")
        result, logs, mock_verifier = self._run([report])

        self.assertIn("npm audit", result)
        self.assertIn("keine bekannten Schwachstellen", result)

    def test_skipped_scan_adds_no_noise_to_summary(self):
        report = DependencyAuditReport(
            attempted=False, vulnerable=False, tool="pip-audit",
            reason_skipped="`pip-audit` ist auf diesem System nicht installiert/verfügbar.",
        )
        result, logs, mock_verifier = self._run([report])

        self.assertNotIn("pip-audit", result)
        self.assertNotIn("bekannte Schwachstelle", result)

    def test_multiple_stack_reports_are_all_included(self):
        reports = [
            DependencyAuditReport(attempted=True, vulnerable=False, tool="pip-audit"),
            DependencyAuditReport(
                attempted=True, vulnerable=True, tool="npm audit",
                vulnerabilities=[DependencyVulnerability(
                    package="lodash", version="<=4.17.11",
                    vulnerability_id="GHSA-fvqr-27wr-82fm", description="Prototype Pollution",
                )],
            ),
        ]
        result, logs, mock_verifier = self._run(reports)

        self.assertIn("pip-audit", result)
        self.assertIn("npm audit", result)
        self.assertIn("lodash", result)


if __name__ == "__main__":
    unittest.main()
