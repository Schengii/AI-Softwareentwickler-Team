"""
tests/test_missing_tests_autofix.py – Testet den Nachbeauftragungs-Versuch in
agents/orchestrator/verification.py._run_verification_loop(), wenn keine Testdateien gefunden
wurden.

Realer Fund (incidentpilot-Projekt): der Lauf endete mit "Keine Testdateien gefunden ...
Verifikation übersprungen" - reine Sichtbarkeit ohne jeden Versuch, den tester-Agenten gezielt
mit dem Nachliefern einer echten Testsuite zu beauftragen. _run_verification_loop() dispatcht
jetzt GENAU EINMAL einen gezielten Fix-Task an tester, bevor endgültig aufgegeben wird - exakt
nach demselben Integrationsmuster wie tests/test_dependency_audit_integration.py.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.verifier import VerificationReport
from core.workspace import WorkspaceManager

NO_TESTS_REPORT = VerificationReport(
    ran=False, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.0,
    reason_skipped="Keine Testdateien gefunden.",
)
INCOMPLETE_TESTS_REPORT = VerificationReport(
    ran=False, passed=False, exit_code=1, stdout="", stderr="", duration_seconds=0.0,
    reason_skipped=(
        "Unvollständiges Projekt erkannt: Ein tests/-Verzeichnis mit conftest.py existiert, "
        "aber keine einzige echte Testdatei (test_*.py/*_test.py) - sieht nach einer "
        "abgebrochenen Testsuite aus, nicht nach einem Projekt, das bewusst auf Tests verzichtet."
    ),
)
MISSING_ENTRYPOINT_REPORT = VerificationReport(
    ran=False, passed=False, exit_code=1, stdout="", stderr="", duration_seconds=0.0,
    reason_skipped=(
        "Unvollständiges Projekt erkannt: 3 Python-Quelldateien und eine Abhängigkeitsliste "
        "(requirements.txt/pyproject.toml) gefunden, aber kein erkennbarer Einstiegspunkt "
        "(__main__.py/app.py/asgi.py/main.py/manage.py/run.py/wsgi.py) - sieht nach einem "
        "mitten in der Generierung abgebrochenen Backend-Projekt aus, nicht nach einem "
        "fertigen Skript."
    ),
)
PASSED_REPORT = VerificationReport(
    ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
)


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


class TestMissingTestsAutofix(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, run_tests_side_effect):
        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            task = AgentTask(task_id="t1", agent_id="backend", description="Etwas bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "missing_tests_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.side_effect = run_tests_side_effect
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []

            status_logs: list[str] = []
            result = asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return result, status_logs, mock_verifier

        return _inner()

    def test_dispatches_tester_once_then_succeeds_on_retry(self):
        result, logs, mock_verifier = self._run([NO_TESTS_REPORT, PASSED_REPORT])

        self.assertEqual(mock_verifier.run_tests.call_count, 2)
        self.assertTrue(self.orchestrator.last_verification_ok)
        self.assertTrue(any("beauftrage tester" in line for line in logs))

    def test_still_no_tests_after_retry_reports_unverified_without_looping_forever(self):
        result, logs, mock_verifier = self._run([NO_TESTS_REPORT, NO_TESTS_REPORT])

        # Genau EIN Nachbeauftragungs-Versuch, kein zweiter - sonst Endlosschleife bei einem
        # tester, der weiterhin keine echte Testdatei anlegt.
        self.assertEqual(mock_verifier.run_tests.call_count, 2)
        self.assertFalse(self.orchestrator.last_verification_ok)
        self.assertTrue(any("NICHT verifiziert" in line for line in logs))

    def test_incomplete_conftest_only_project_dispatches_tester_then_succeeds(self):
        # Team-Optimierung (Retrospektive, zeiterfassung_app-Lauf): "tests/-Verzeichnis mit
        # conftest.py, aber keine echte Testdatei" wurde bisher zwar korrekt als Fehlschlag
        # (report.ran=False, report.passed=False statt nur "nichts zu testen") erkannt, aber nie
        # ein Fix dafür beauftragt - der Zweig endete direkt in einem `break`. Jetzt bekommt der
        # tester denselben EINEN Nachbeauftragungs-Versuch wie beim "keine Tests gefunden"-Fall.
        result, logs, mock_verifier = self._run([INCOMPLETE_TESTS_REPORT, PASSED_REPORT])

        self.assertEqual(mock_verifier.run_tests.call_count, 2)
        self.assertTrue(self.orchestrator.last_verification_ok)
        self.assertTrue(any("beauftrage tester" in line for line in logs))

    def test_incomplete_conftest_only_project_gives_up_after_one_retry(self):
        result, logs, mock_verifier = self._run([INCOMPLETE_TESTS_REPORT, INCOMPLETE_TESTS_REPORT])

        self.assertEqual(mock_verifier.run_tests.call_count, 2)
        self.assertFalse(self.orchestrator.last_verification_ok)

    def test_missing_entrypoint_is_not_routed_to_tester(self):
        # Ein fehlender Einstiegspunkt (main.py/app.py/...) ist kein Testsuite-Problem - der
        # tester darf hierfür NICHT beauftragt werden (das wäre architect/backend-Aufgabe),
        # die Schleife muss stattdessen direkt aufgeben, ohne einen Fix-Versuch zu verschwenden.
        result, logs, mock_verifier = self._run([MISSING_ENTRYPOINT_REPORT, PASSED_REPORT])

        self.assertEqual(mock_verifier.run_tests.call_count, 1)
        self.assertFalse(self.orchestrator.last_verification_ok)
        self.assertFalse(any("beauftrage tester" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
