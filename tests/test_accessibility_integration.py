"""
tests/test_accessibility_integration.py – Testet die Accessibility-Check-Anbindung im
Verifikationslauf (agents/orchestrator.py._run_verification_loop())

Realer Fund: der accessibility-Agent konnte WCAG-Verstöße bisher nur "plausibel" einschätzen
(LLM-Freitext-Checkliste), ohne echten Scan. core/verifier.py.check_accessibility() (axe-core)
führt jetzt einen echten Scan aus und macht das Ergebnis sichtbar – dieselbe Integrationsart
wie test_load_test_integration.py, nur für Barrierefreiheit.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.browser_verifier import AccessibilityReport, AccessibilityViolation
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.verifier import VerificationReport
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


class TestAccessibilityInVerificationLoop(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, a11y_report: AccessibilityReport):
        @patch("agents.orchestrator.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            task = AgentTask(task_id="t1", agent_id="frontend", description="Etwas bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "a11y_test_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
            )
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_sast.return_value = []
            mock_verifier.check_licenses.return_value = []
            mock_verifier.check_lint.return_value = []
            mock_verifier.check_runtime_smoke.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_browser_ui.return_value.attempted = False
            mock_verifier.check_accessibility.return_value = a11y_report

            status_logs: list[str] = []
            result = asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return result, status_logs, mock_verifier

        return _inner()

    def test_violations_are_visible_and_do_not_flip_verification_ok(self):
        a11y_report = AccessibilityReport(
            attempted=True, passed=False, tested_url="http://127.0.0.1:8123/index.html",
            violations=[
                AccessibilityViolation(rule_id="image-alt", impact="critical", description="...",
                                        help_url="https://dequeuniversity.com/rules/axe/4.x/image-alt",
                                        target="img.logo"),
            ],
        )
        result, logs, mock_verifier = self._run(a11y_report)

        mock_verifier.check_accessibility.assert_called_once()
        self.assertIn("Accessibility-Check", result)
        self.assertIn("image-alt", result)
        self.assertTrue(any("WCAG-Verstoß" in line for line in logs))
        # Rein informativ wie Lint/SAST - beeinflusst den Gesamtstatus nicht.
        self.assertTrue(any("Fertig!" in line and "NICHT" not in line for line in logs))

    def test_clean_scan_is_reported_in_summary(self):
        a11y_report = AccessibilityReport(attempted=True, passed=True, tested_url="http://127.0.0.1:8123/index.html")
        result, logs, mock_verifier = self._run(a11y_report)

        self.assertIn("Accessibility-Check", result)
        self.assertIn("keine WCAG-Verstöße", result)

    def test_skipped_scan_adds_no_noise_to_summary(self):
        a11y_report = AccessibilityReport(attempted=False, reason_skipped="Keine HTML-Dateien im Projekt gefunden.")
        result, logs, mock_verifier = self._run(a11y_report)

        self.assertNotIn("Accessibility-Check", result)


if __name__ == "__main__":
    unittest.main()
