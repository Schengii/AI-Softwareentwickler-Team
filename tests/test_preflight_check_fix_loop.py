"""
tests/test_preflight_check_fix_loop.py – Testet den Fix-Loop für den deterministischen
Pre-Flight-Check (core/pre_flight_check.py) in agents/orchestrator/verification.py.

Realer Fund (Analyse 2026-09-06): core/pre_flight_check.py wurde eingeführt (ast-basierter
Vorab-Check auf fehlende __init__.py, Syntax-Fehler und fehlende requirements.txt-Einträge),
aber nur für eine reine Notify-Anzeige verdrahtet - jeder Fund blieb bis zum teuren, isolierten
Testlauf liegen statt gezielt an den zuständigen Datei-Owner zur Korrektur zurückgespielt zu
werden, obwohl format_pre_flight_issues_for_fix() genau dafür geschrieben wurde. Dieser Test
stellt sicher, dass ein Pre-Flight-Fund jetzt GENAUSO wie der Vorab-Import-Check (siehe
tests/test_preimport_check.py) vor der Testsuite gezielt beauftragt wird.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.pre_flight_check import PreFlightIssue, PreFlightReport
from core.verifier import CompletenessReport, VerificationReport
from core.workspace import WorkspaceManager
from tests.helpers import ScriptedWriteFileLLM as _ScriptedLLM

PASSED_REPORT = VerificationReport(
    ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
)
CLEAN_COMPLETENESS = CompletenessReport(attempted=True, passed=True, issues=[])


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




def _report_with_missing_dependency() -> PreFlightReport:
    return PreFlightReport(
        project_dir="dummy",
        files_checked=3,
        issues=[PreFlightIssue(
            file="app/main.py", line=3, issue_type="missing_dependency",
            message="Paket `httpx` wird importiert, fehlt aber in requirements.txt.",
            suggestion="Füge `httpx` zu requirements.txt hinzu.",
        )],
    )


def _clean_report() -> PreFlightReport:
    return PreFlightReport(project_dir="dummy", files_checked=3, issues=[])


def _report_with_empty_test_suite() -> PreFlightReport:
    return PreFlightReport(
        project_dir="dummy",
        files_checked=3,
        issues=[PreFlightIssue(
            file="tests/", line=0, issue_type="empty_test_suite",
            message="`tests/` existiert, enthaelt aber keine einzige ausfuehrbare Testfunktion.",
            suggestion="Lege in `tests/` mindestens eine `test_*.py`-Datei mit echten `def test_...`-Funktionen an.",
        )],
    )


class TestPreflightCheckFixLoop(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, pre_flight_side_effect, write_file: str | None = "app/main.py"):
        if write_file:
            self.orchestrator._agents["backend"]._llm = _ScriptedLLM(written_file=write_file)

        @patch("agents.orchestrator.verification.run_pre_flight_check")
        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls, mock_pre_flight):
            task = AgentTask(task_id="t1", agent_id="backend", description="app/main.py bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "preflight_test_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = PASSED_REPORT
            mock_verifier.check_completeness.return_value = CLEAN_COMPLETENESS
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_lint.return_value = []
            mock_pre_flight.side_effect = pre_flight_side_effect

            status_logs: list[str] = []
            result = asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return result, status_logs, mock_verifier

        return _inner()

    def test_missing_dependency_dispatched_before_test_suite_runs(self):
        # Erster Aufruf (Pre-Flight-Check) findet den Fund, jeder weitere Aufruf (Retry im
        # Fix-Loop) ist bereits sauber.
        result, logs, mock_verifier = self._run([
            _report_with_missing_dependency(),
            _clean_report(),
        ])

        self.assertTrue(any("Pre-Flight-Check" in line for line in logs))
        self.assertTrue(any("Beauftrage backend" in line and "Pre-Flight-Check" in line for line in logs))
        self.assertTrue(self.orchestrator.last_verification_ok)

    def test_empty_test_suite_dispatched_to_tester_not_dev_lead(self):
        """KI-Team-Zustandsbericht 2026-09-08: 'empty_test_suite' hat nie einen bekannten
        file_owners-Eintrag (der Fund zeigt auf das Verzeichnis 'tests/', keine konkrete Datei,
        die je von einem Agenten geschrieben wurde) - muss also über den Fallback-Owner
        ausdrücklich an 'tester' gehen, nicht an den generischen 'dev_lead'-Auffangfall."""
        self.orchestrator._agents["tester"]._llm = _ScriptedLLM(written_file="tests/test_main.py")
        result, logs, mock_verifier = self._run([
            _report_with_empty_test_suite(),
            _clean_report(),
        ], write_file=None)

        self.assertTrue(any("Beauftrage tester" in line and "Pre-Flight-Check" in line for line in logs))
        self.assertFalse(any("Beauftrage dev_lead" in line and "Pre-Flight-Check" in line for line in logs))
        self.assertTrue(self.orchestrator.last_verification_ok)

    def test_no_issues_skips_dispatch_entirely(self):
        result, logs, mock_verifier = self._run([_clean_report()])

        self.assertFalse(any("Pre-Flight-Check" in line and "Beauftrage" in line for line in logs))
        self.assertTrue(self.orchestrator.last_verification_ok)

    def test_error_during_check_is_skipped_without_crash(self):
        result, logs, mock_verifier = self._run(
            [PreFlightReport(project_dir="dummy", error="Projektverzeichnis existiert nicht: x")],
        )

        self.assertTrue(any("übersprungen" in line for line in logs))
        self.assertTrue(self.orchestrator.last_verification_ok)

    def test_exception_during_check_is_skipped_without_crash(self):
        result, logs, mock_verifier = self._run(RuntimeError("boom"))

        self.assertTrue(any("übersprungen" in line for line in logs))
        self.assertTrue(self.orchestrator.last_verification_ok)


if __name__ == "__main__":
    unittest.main()
