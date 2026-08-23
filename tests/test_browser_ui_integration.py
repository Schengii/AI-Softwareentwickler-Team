"""
tests/test_browser_ui_integration.py – Testet die Anbindung des Frontend/UI-Checks im
Verifikationslauf (agents/orchestrator.py._run_verification_loop())

Realer Fund (Pong-Projekt): ein Fehlschlag des Frontend/UI-Checks (core/browser_verifier.py)
war bisher rein informativ und beeinflusste verification_ok NICHT - ein Frontend, das im
echten Browser mit einem JS-Fehler crasht oder ein <canvas> nie zeichnet, bestand die
Verifikation trotzdem. Außerdem sah ein "static_dom"-Fallback-Pass (kein echter Browser
installiert, kein JS ausgeführt) optisch identisch zu einem echten Playwright-Pass aus. Beide
Lücken sind hier jeweils durch einen eigenen Test abgedeckt - dieselbe Integrationsart wie
test_accessibility_integration.py, nur für den Frontend/UI-Check statt Barrierefreiheit.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.browser_verifier import BrowserVerificationReport
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


class TestBrowserUiInVerificationLoop(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, browser_report: BrowserVerificationReport):
        @patch("agents.orchestrator.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            task = AgentTask(task_id="t1", agent_id="frontend", description="Etwas bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "browser_ui_test_proj", [task])
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
            mock_verifier.check_browser_ui.return_value = browser_report
            mock_verifier.check_accessibility.return_value.attempted = False

            status_logs: list[str] = []
            result = asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return result, status_logs

        return _inner()

    def test_real_console_error_fails_verification(self):
        browser_report = BrowserVerificationReport(
            attempted=True, passed=False, engine="playwright",
            console_errors=["Uncaught SyntaxError: Unexpected token 'export'"],
            tested_url="http://127.0.0.1:8123/index.html",
        )
        result, logs = self._run(browser_report)

        self.assertFalse(self.orchestrator.last_verification_ok)
        self.assertIn("Frontend/UI-Check fehlgeschlagen", result)
        self.assertTrue(any("NICHT verifiziert" in line for line in logs))

    def test_blank_canvas_fails_verification(self):
        browser_report = BrowserVerificationReport(
            attempted=True, passed=False, engine="playwright",
            blank_canvases=["game"], tested_url="http://127.0.0.1:8123/index.html",
        )
        result, logs = self._run(browser_report)

        self.assertFalse(self.orchestrator.last_verification_ok)
        self.assertIn("Canvas nie gezeichnet", result)

    def test_real_playwright_pass_reports_success_without_reservation(self):
        browser_report = BrowserVerificationReport(
            attempted=True, passed=True, engine="playwright",
            tested_url="http://127.0.0.1:8123/index.html",
        )
        result, logs = self._run(browser_report)

        self.assertTrue(self.orchestrator.last_verification_ok)
        self.assertIn("Frontend/UI-Check", result)
        self.assertNotIn("eingeschränkt", result)

    def test_static_dom_pass_is_marked_as_limited_not_a_full_pass(self):
        # Realer Fund: ohne installiertes Playwright degradiert der Check STILL auf eine reine
        # Datei-Existenz-Prüfung (kein JS wird ausgeführt) - das darf im Bericht nicht wie ein
        # vollwertiger, echter Browser-Check aussehen.
        browser_report = BrowserVerificationReport(
            attempted=True, passed=True, engine="static_dom",
            tested_url="file://index.html",
        )
        result, logs = self._run(browser_report)

        # Ein reiner static_dom-Pass ist kein echter Testfehlschlag - verification_ok bleibt
        # unberührt (Python-Testsuite war grün), aber die Einschränkung muss lesbar sein.
        self.assertTrue(self.orchestrator.last_verification_ok)
        self.assertIn("eingeschränkt", result)
        self.assertIn("JavaScript", result)


if __name__ == "__main__":
    unittest.main()
