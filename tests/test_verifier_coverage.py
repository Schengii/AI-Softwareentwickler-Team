"""
tests/test_verifier_coverage.py – Testet die echte Testabdeckungs-Messung
(core/verifier.py.check_coverage())

Realer Fund bei einer Bestandsaufnahme des eigenen Teams: die Verifikation misst bisher nur
Pass/Fail, keine Coverage-Zahl - ein Projekt mit 3 bestandenen Tests bei 500 Zeilen ungetestetem
Code galt genauso als "verifiziert" wie eines mit echter Abdeckung. `pytest`/`pytest-cov`
werden hier ECHT über `CodeSandbox.run_command` gemockt (wie bei den bestehenden Docker-Build-/
Dependency-Audit-/Lint-Tests) - das JSON-Fixture entspricht dem tatsächlichen Format von
`coverage.py`s `--cov-report=json`.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.code_sandbox import ExecutionResult
from core.verifier import ProjectVerifier


def _ok(stdout: str = "", stderr: str = "", exit_code: int = 0) -> ExecutionResult:
    return ExecutionResult(exit_code=exit_code, stdout=stdout, stderr=stderr, duration_seconds=0.1)


class TestCheckCoverage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        self.verifier = ProjectVerifier(self.project_dir)

    def _write_test_file(self):
        (self.project_dir / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    def _mock_run_command(self, percent_covered: float, pytest_cov_available: bool = True):
        report_path = self.project_dir / "coverage_report.json"

        def _side_effect(cmd, cwd=None, timeout_seconds=None):
            if "import pytest_cov" in cmd:
                return _ok(exit_code=0 if pytest_cov_available else 1)
            if "pytest" in cmd:
                report_path.write_text(
                    json.dumps({"totals": {"percent_covered": percent_covered}}), encoding="utf-8",
                )
                return _ok(stdout="1 passed")
            raise AssertionError(f"unerwarteter Befehl: {cmd}")

        return _side_effect

    def test_no_test_files_is_not_attempted(self):
        report = self.verifier.check_coverage()
        self.assertFalse(report.attempted)
        self.assertIn("Keine Python-Testdateien", report.reason_skipped)

    @patch("core.verifier.CodeSandbox.run_command")
    def test_pytest_cov_not_installed_is_not_attempted(self, mock_run):
        self._write_test_file()
        mock_run.side_effect = self._mock_run_command(percent_covered=90.0, pytest_cov_available=False)

        report = self.verifier.check_coverage()

        self.assertFalse(report.attempted)
        self.assertIn("pytest-cov", report.reason_skipped)

    @patch("core.verifier.CodeSandbox.run_command")
    def test_coverage_above_reports_percent(self, mock_run):
        self._write_test_file()
        mock_run.side_effect = self._mock_run_command(percent_covered=87.3)

        report = self.verifier.check_coverage()

        self.assertTrue(report.attempted)
        self.assertEqual(report.percent, 87.3)

    @patch("core.verifier.CodeSandbox.run_command")
    def test_report_file_is_cleaned_up_afterwards(self, mock_run):
        self._write_test_file()
        mock_run.side_effect = self._mock_run_command(percent_covered=50.0)

        self.verifier.check_coverage()

        self.assertFalse((self.project_dir / "coverage_report.json").exists())

    @patch("core.verifier.CodeSandbox.run_command")
    def test_missing_report_file_is_not_attempted(self, mock_run):
        self._write_test_file()

        def _side_effect(cmd, cwd=None, timeout_seconds=None):
            if "import pytest_cov" in cmd:
                return _ok(exit_code=0)
            return _ok(stdout="", stderr="irgendein Absturz")  # schreibt KEINE JSON-Datei

        mock_run.side_effect = _side_effect

        report = self.verifier.check_coverage()

        self.assertFalse(report.attempted)
        self.assertIn("kein Ergebnis", report.reason_skipped)


if __name__ == "__main__":
    unittest.main()
