"""
tests/test_load_test_integration.py – Testet die Lastentest-Anbindung im Verifikationslauf
(agents/orchestrator.py._run_verification_loop())

Realer Fund: der performance-Agent schreibt vollständige k6-/Locust-Lastentest-Skripte, die
aber NIE ausgeführt wurden - anders als run_tests() landeten sie ungeprüft im Projekt.
core/verifier.py.check_load_test() führt sie jetzt echt aus und macht das Ergebnis sichtbar –
dieselbe Integrationsart wie test_runtime_smoke_integration.py, nur für den Lasttest.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.verifier import PerfCheckReport, VerificationReport
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


class TestLoadTestInVerificationLoop(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, perf_report: PerfCheckReport):
        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            task = AgentTask(task_id="t1", agent_id="backend", description="Etwas bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "load_test_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
            )
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_lint.return_value = []
            mock_verifier.check_sast.return_value = []
            mock_verifier.check_licenses.return_value = []
            mock_verifier.check_runtime_smoke.return_value.attempted = False
            mock_verifier.check_load_test.return_value = perf_report
            mock_verifier.check_browser_ui.return_value.attempted = False

            status_logs: list[str] = []
            result = asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return result, status_logs, mock_verifier

        return _inner()

    def test_passed_load_test_is_visible_and_keeps_verification_ok(self):
        perf_report = PerfCheckReport(
            attempted=True, passed=True, tool="locust", script="tests/load/locustfile.py",
            total_requests=15, failed_requests=0, p95_ms=20.0,
        )
        result, logs, mock_verifier = self._run(perf_report)

        mock_verifier.check_load_test.assert_called_once()
        self.assertIn("Lastentest (locust) bestanden", result)
        self.assertIn("15 Requests", result)
        self.assertTrue(any("Lastentest" in line and "bestanden" in line for line in logs))
        self.assertTrue(any("Fertig!" in line and "NICHT" not in line for line in logs))

    def test_failed_load_test_is_visible_and_flips_verification_ok_to_false(self):
        perf_report = PerfCheckReport(
            attempted=True, passed=False, tool="k6", script="tests/load/script.js",
            total_requests=15, failed_requests=4, p95_ms=800.0,
        )
        result, logs, mock_verifier = self._run(perf_report)

        self.assertIn("Lastentest (k6) fehlgeschlagen", result)
        self.assertIn("4 fehlgeschlagen", result)
        self.assertTrue(any("Lastentest" in line and "fehlgeschlagen" in line for line in logs))
        self.assertTrue(any("NICHT verifiziert" in line for line in logs))

    def test_skipped_load_test_adds_no_noise_to_summary(self):
        perf_report = PerfCheckReport(
            attempted=False, reason_skipped="Kein Lastentest-Skript unter tests/load/ gefunden.",
        )
        result, logs, mock_verifier = self._run(perf_report)

        self.assertNotIn("Lastentest", result)


if __name__ == "__main__":
    unittest.main()
