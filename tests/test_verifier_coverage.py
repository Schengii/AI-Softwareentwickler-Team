"""
tests/test_verifier_coverage.py – Testet die echte Coverage-Messung (core/verifier.py.check_coverage())

Realer Fund: der tester-Agent nennt "Code-Coverage-Analyse" in seinem eigenen System-Prompt
(agents/tester_agent.py) als Fähigkeit - aber nirgends im echten Code wurde Coverage jemals
tatsächlich ausgeführt oder gemessen, nur behauptet. check_coverage() misst jetzt echt per
`coverage.py` (dieselbe "LLM-Einschätzung statt echter Messung"-Lücke, die bei
Dependency-Vulnerabilities bereits durch pip-audit geschlossen wurde).

`CodeSandbox.run_command` wird gemockt (wie bei den bestehenden Lint-/Dependency-Audit-
Tests) - die reale Coverage-JSON-Struktur (`{"totals": {"percent_covered": ...}}`) entspricht
wortgetreu einem echten `coverage json`-Report.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.code_sandbox import ExecutionResult
from core.verifier import ProjectVerifier

_OK = ExecutionResult(exit_code=0, stdout="", stderr="", duration_seconds=0.1)


class TestCoverageMeasurement(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        (self.project_dir / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _seed_coverage_output(self, percent: float) -> None:
        """Simuliert die Dateien, die ein echter `coverage run` + `coverage json` hinterlässt -
        CodeSandbox.run_command ist gemockt (kein echter Subprozess), also muss der Test die
        realen Nebeneffekte selbst nachbilden, exakt wie bei den Lint-/Audit-Tests."""
        (self.project_dir / ".ai_team_coverage_data").write_text("", encoding="utf-8")
        (self.project_dir / ".ai_team_coverage.json").write_text(
            json.dumps({"totals": {"percent_covered": percent}}), encoding="utf-8",
        )

    @patch("core.verifier.CodeSandbox.run_command")
    def test_reports_real_percentage_above_threshold_as_passed(self, mock_run):
        mock_run.side_effect = lambda *a, **kw: (self._seed_coverage_output(82.5), _OK)[1]
        verifier = ProjectVerifier(self.project_dir)

        report = verifier.check_coverage()

        self.assertTrue(report.attempted)
        self.assertAlmostEqual(report.percent_covered, 82.5)
        self.assertTrue(report.passed)

    @patch("core.verifier.CodeSandbox.run_command")
    def test_reports_percentage_below_threshold_as_not_passed(self, mock_run):
        mock_run.side_effect = lambda *a, **kw: (self._seed_coverage_output(30.0), _OK)[1]
        verifier = ProjectVerifier(self.project_dir)

        report = verifier.check_coverage()

        self.assertTrue(report.attempted)
        self.assertAlmostEqual(report.percent_covered, 30.0)
        self.assertFalse(report.passed)

    @patch("core.verifier.CodeSandbox.run_command")
    def test_cleans_up_coverage_artifact_files_after_measurement(self, mock_run):
        mock_run.side_effect = lambda *a, **kw: (self._seed_coverage_output(50.0), _OK)[1]
        verifier = ProjectVerifier(self.project_dir)

        verifier.check_coverage()

        self.assertFalse((self.project_dir / ".ai_team_coverage_data").exists())
        self.assertFalse((self.project_dir / ".ai_team_coverage.json").exists())

    def test_no_python_test_files_skips_measurement(self):
        empty_dir = Path(tempfile.mkdtemp())
        try:
            verifier = ProjectVerifier(empty_dir)
            report = verifier.check_coverage()
            self.assertFalse(report.attempted)
            self.assertIn("Keine Testdateien", report.reason_skipped)
        finally:
            shutil.rmtree(empty_dir, ignore_errors=True)

    @patch("core.verifier.CodeSandbox.run_command")
    def test_failed_coverage_package_install_skips_measurement(self, mock_run):
        mock_run.return_value = ExecutionResult(exit_code=1, stdout="", stderr="no internet", duration_seconds=0.1)
        verifier = ProjectVerifier(self.project_dir)

        report = verifier.check_coverage()

        self.assertFalse(report.attempted)
        self.assertIn("konnte nicht installiert werden", report.reason_skipped)

    @patch("core.verifier.CodeSandbox.run_command")
    def test_missing_data_file_after_run_is_reported_as_not_attempted(self, mock_run):
        """Realer Fund im Verifikationsloop-Stil: schlägt der Testlauf selbst so hart fehl,
        dass gar keine Coverage-Daten geschrieben werden, ist das KEIN Fehler der Messung
        selbst - nur nicht messbar, NIEMALS fälschlich als '0% Coverage' gemeldet."""
        mock_run.return_value = _OK  # keine Datei wird je erzeugt
        verifier = ProjectVerifier(self.project_dir)

        report = verifier.check_coverage()

        self.assertFalse(report.attempted)
        self.assertTrue(report.passed)  # nicht messbar != fehlgeschlagen
        self.assertEqual(report.percent_covered, 0.0)

    @patch("core.verifier.CodeSandbox.run_command")
    def test_malformed_json_report_is_reported_as_not_attempted(self, mock_run):
        def _side_effect(*args, **kwargs):
            (self.project_dir / ".ai_team_coverage_data").write_text("", encoding="utf-8")
            (self.project_dir / ".ai_team_coverage.json").write_text("not valid json", encoding="utf-8")
            return _OK
        mock_run.side_effect = _side_effect
        verifier = ProjectVerifier(self.project_dir)

        report = verifier.check_coverage()

        self.assertFalse(report.attempted)
        self.assertIn("Coverage-JSON-Report konnte nicht gelesen werden", report.reason_skipped)


if __name__ == "__main__":
    unittest.main()
