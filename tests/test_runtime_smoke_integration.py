"""
tests/test_runtime_smoke_integration.py – Testet die Runtime-Smoke-Check-Anbindung im
Verifikationslauf (agents/orchestrator.py._run_verification_loop())

Realer Fund (Code-Review): Der `else`-Zweig für einen fehlgeschlagenen Runtime-Smoke-Test
(core/verifier.py.check_runtime_smoke() -> attempted=True, passed=False, d.h. die generierte
App startet nachweislich NICHT) baute bisher nur eine ungenutzte `err`-Variable (von ruff als
F841 markiert) – ohne notify()/summary_lines.append() und ohne verification_ok zurückzusetzen.
Ein fehlgeschlagener Smoke-Test blieb dadurch komplett unsichtbar UND unblockiert, obwohl genau
das der Sinn dieses Checks ist ("Tests grün != App startet"). Dieselbe Integrationsart wie
test_coverage_integration.py/test_lint_integration.py, nur für check_runtime_smoke().
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.verifier import RuntimeSmokeReport, VerificationReport
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


class TestRuntimeSmokeInVerificationLoop(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, smoke_report: RuntimeSmokeReport):
        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            task = AgentTask(task_id="t1", agent_id="backend", description="Etwas bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "smoke_test_proj", [task])
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
            mock_verifier.check_runtime_smoke.return_value = smoke_report
            mock_verifier.check_browser_ui.return_value.attempted = False

            status_logs: list[str] = []
            result = asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return result, status_logs, mock_verifier

        return _inner()

    def test_failed_smoke_test_is_visible_and_flips_verification_ok_to_false(self):
        smoke_report = RuntimeSmokeReport(
            attempted=True, passed=False, entrypoint="main.py", app_type="cli_script",
            output="Traceback (most recent call last): ... ImportError: no module named foo",
        )
        result, logs, mock_verifier = self._run(smoke_report)

        # Ein fehlgeschlagener Smoke-Test löst jetzt eine gezielte Fix-Schleife aus (siehe
        # _run_runtime_check_with_fix in agents/orchestrator/verification.py) - der Mock liefert
        # bei jedem Versuch denselben Fehlschlag zurück, der Check läuft deshalb mehrfach
        # (initialer Lauf + ein erneuter Check je Fixversuch bis MAX_VERIFICATION_ITERATIONS).
        self.assertGreater(mock_verifier.check_runtime_smoke.call_count, 1)
        # Muss im Abschlussbericht sichtbar sein, nicht lautlos verschluckt werden.
        self.assertIn("Runtime-Smoke-Test fehlgeschlagen", result)
        self.assertIn("main.py", result)
        # Muss auch live per notify() gemeldet werden, nicht nur im finalen Bericht.
        self.assertTrue(any("Runtime-Smoke-Test fehlgeschlagen" in line for line in logs))
        # Ein echter Startfehler ist eine Anforderungsverletzung, kein reiner Hinweis -
        # verification_ok muss zurückgesetzt werden (sichtbar am "NICHT verifiziert"-Status).
        self.assertTrue(any("NICHT verifiziert" in line for line in logs))

    def test_passed_smoke_test_keeps_verification_ok(self):
        smoke_report = RuntimeSmokeReport(
            attempted=True, passed=True, entrypoint="main.py", app_type="cli_script",
        )
        result, logs, mock_verifier = self._run(smoke_report)

        mock_verifier.check_runtime_smoke.assert_called_once()
        self.assertIn("Runtime-Smoke-Test", result)
        self.assertIn("startet fehlerfrei", result)
        self.assertTrue(any("Fertig!" in line and "NICHT" not in line for line in logs))


if __name__ == "__main__":
    unittest.main()
