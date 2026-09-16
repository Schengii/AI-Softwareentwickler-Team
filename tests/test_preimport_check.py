"""
tests/test_preimport_check.py – Testet den Vorab-Import-Check in
agents/orchestrator/verification.py._run_verification_loop().

Realer Fund (taskpulse-Projekt, 2026-09-03): `app/main.py` importierte `from . import database,
models, schemas`, aber `app/models.py` existierte nie - der Fund wurde erst nach der kompletten,
teuren Test-/Governance-/Review-Kaskade sichtbar (33 Agenten-Durchläufe, 714k Tokens). Der
Vorab-Import-Check läuft jetzt statisch (core/verifier/completeness.py._missing_local_python_
imports) VOR jedem echten Testlauf und beauftragt den zuständigen Datei-Owner gezielt, BEVOR
die teure Testsuite überhaupt startet - exakt nach dem Integrationsmuster von
tests/test_missing_tests_autofix.py.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.verifier import CompletenessIssue, CompletenessReport, VerificationReport
from core.workspace import WorkspaceManager
from tests.helpers import ScriptedWriteFileLLM as _ScriptedLLM

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




def _completeness_report_with_missing_import() -> CompletenessReport:
    return CompletenessReport(
        attempted=True, passed=False,
        issues=[CompletenessIssue(
            file_path="app/main.py", line_number=10,
            message="Import „from . import models“ verweist auf kein existierendes lokales "
                    "Submodul (`app/models.py`).",
            kind="missing_local_import",
        )],
    )


def _clean_completeness_report() -> CompletenessReport:
    return CompletenessReport(attempted=True, passed=True, issues=[])


def _completeness_report_with_missing_symbol() -> CompletenessReport:
    # Team-Optimierung (vollständige Umsetzung einer KI-Team-Retrospektive, echter Fund am
    # event_relay-Lauf 2026-09-06): core/verifier/completeness.py._check_symbols_in_module_file()
    # formuliert einen fehlenden SYMBOL-Import bewusst OHNE die Zeichenfolge "existierendes
    # lokales" (siehe CompletenessIssue.kind-Docstring) - dieselbe Meldungsform wie beim echten
    # `from app.resilience import resilience`-Fund. Ohne kind="missing_local_import" würde die
    # alte Substring-Suche in _run_verification_loop() diesen Fund NIE finden.
    return CompletenessReport(
        attempted=True, passed=False,
        issues=[CompletenessIssue(
            file_path="app/main.py", line_number=6,
            message="Import „from app.resilience import resilience“ verweist auf kein in "
                    "`app/resilience.py` definiertes/importiertes Symbol.",
            kind="missing_local_import",
        )],
    )


class TestPreimportCheck(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, completeness_side_effect, write_file: str | None = "app/main.py"):
        if write_file:
            self.orchestrator._agents["backend"]._llm = _ScriptedLLM(written_file=write_file)

        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            task = AgentTask(task_id="t1", agent_id="backend", description="app/main.py bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "preimport_test_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = PASSED_REPORT
            mock_verifier.check_completeness.side_effect = completeness_side_effect
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_lint.return_value = []

            status_logs: list[str] = []
            result = asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return result, status_logs, mock_verifier

        return _inner()

    def test_missing_local_import_dispatched_before_test_suite_runs(self):
        # Erster Aufruf (Vorab-Check) findet den Fund, jeder weitere Aufruf (Retry im
        # Vorab-Check + regulärer Check nach der Testsuite) ist bereits sauber.
        result, logs, mock_verifier = self._run([
            _completeness_report_with_missing_import(),
            _clean_completeness_report(),
            _clean_completeness_report(),
        ])

        self.assertTrue(any("Vorab-Import-Check" in line for line in logs))
        self.assertTrue(any("Beauftrage backend" in line and "Vorab-Import-Check" in line for line in logs))
        self.assertIn("Vorab-Import-Check", result)
        self.assertTrue(self.orchestrator.last_verification_ok)

    def test_missing_symbol_import_dispatched_before_test_suite_runs(self):
        # Regressionstest für den event_relay-Fund: ein fehlendes SYMBOL (nicht nur ein
        # fehlendes Modul/Submodul) muss GENAUSO vor der Testsuite zur Korrektur beauftragt
        # werden - siehe _completeness_report_with_missing_symbol()-Docstring.
        result, logs, mock_verifier = self._run([
            _completeness_report_with_missing_symbol(),
            _clean_completeness_report(),
            _clean_completeness_report(),
        ])

        self.assertTrue(any("Beauftrage backend" in line and "Vorab-Import-Check" in line for line in logs))
        self.assertTrue(self.orchestrator.last_verification_ok)

    def test_no_missing_import_skips_dispatch_entirely(self):
        result, logs, mock_verifier = self._run([
            _clean_completeness_report(),
            _clean_completeness_report(),
        ])

        self.assertFalse(any("Vorab-Import-Check:" in line and "Beauftrage" in line for line in logs))
        self.assertTrue(self.orchestrator.last_verification_ok)

    def test_default_magicmock_completeness_does_not_crash(self):
        # Realistischer Fall für ANDERE Tests, die ProjectVerifier komplett mocken, ohne
        # check_completeness() selbst zu konfigurieren (siehe z.B.
        # tests/test_missing_tests_autofix.py) - MagicMock().passed ist truthy, das darf den
        # neuen Vorab-Check nicht zum Absturz bringen (siehe Kommentar in verification.py).
        result, logs, mock_verifier = self._run(None)  # kein side_effect -> default MagicMock

        self.assertTrue(self.orchestrator.last_verification_ok)


if __name__ == "__main__":
    unittest.main()
