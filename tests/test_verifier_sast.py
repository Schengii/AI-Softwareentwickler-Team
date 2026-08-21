"""
tests/test_verifier_sast.py – Testet den echten statischen Sicherheits-Scan
(core/verifier.py.check_sast())

Realer Fund bei einer Bestandsaufnahme des eigenen Teams: check_dependency_vulnerabilities()
prüft nur FREMDE Abhängigkeiten auf bekannte CVEs, aber die selbst geschriebene Code-LOGIK
(hartcodierte Secrets, SQL-String-Concat, eval(), ...) hatte nie einen echten statischen
Sicherheits-Scan - der security-Agent konnte sie nur per LLM-Einschätzung bewerten.

`CodeSandbox.run_command` wird gemockt (wie bei den bestehenden Lint-/Coverage-Tests) - die
JSON-Struktur entspricht wortgetreu einem echten `bandit -f json`-Report.
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


def _bandit_json(project_dir: Path, filename: str = "app.py") -> str:
    return json.dumps({
        "results": [
            {
                "filename": str(project_dir / filename),
                "line_number": 12,
                "issue_text": "Possible SQL injection vector through string-based query construction.",
                "issue_severity": "MEDIUM",
                "test_id": "B608",
            },
        ],
        "errors": [],
    })


_BANDIT_CLEAN = json.dumps({"results": [], "errors": []})


class TestSastScan(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        (self.project_dir / "app.py").write_text("import os\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("core.verifier.CodeSandbox.run_command")
    def test_reports_real_bandit_findings_with_relative_paths(self, mock_run):
        mock_run.side_effect = [
            _OK,  # pip install bandit
            ExecutionResult(exit_code=1, stdout=_bandit_json(self.project_dir.resolve()), stderr="", duration_seconds=0.2),
        ]
        verifier = ProjectVerifier(self.project_dir)

        report = verifier.check_sast()

        self.assertTrue(report.attempted)
        self.assertFalse(report.passed)
        self.assertEqual(len(report.issues), 1)
        self.assertEqual(report.issues[0].file_path, "app.py")
        self.assertEqual(report.issues[0].line_number, 12)
        self.assertEqual(report.issues[0].rule, "B608")
        self.assertEqual(report.issues[0].severity, "MEDIUM")

    @patch("core.verifier.CodeSandbox.run_command")
    def test_clean_scan_is_reported_as_passed(self, mock_run):
        mock_run.side_effect = [_OK, ExecutionResult(exit_code=0, stdout=_BANDIT_CLEAN, stderr="", duration_seconds=0.1)]
        verifier = ProjectVerifier(self.project_dir)

        report = verifier.check_sast()

        self.assertTrue(report.attempted)
        self.assertTrue(report.passed)
        self.assertEqual(report.issues, [])

    def test_no_python_files_skips_scan(self):
        empty_dir = Path(tempfile.mkdtemp())
        try:
            verifier = ProjectVerifier(empty_dir)
            report = verifier.check_sast()
            self.assertFalse(report.attempted)
            self.assertIn("Keine Python-Dateien", report.reason_skipped)
        finally:
            shutil.rmtree(empty_dir, ignore_errors=True)

    @patch("core.verifier.CodeSandbox.run_command")
    def test_failed_bandit_install_skips_scan(self, mock_run):
        mock_run.return_value = ExecutionResult(exit_code=1, stdout="", stderr="no internet", duration_seconds=0.1)
        verifier = ProjectVerifier(self.project_dir)

        report = verifier.check_sast()

        self.assertFalse(report.attempted)
        self.assertIn("konnte nicht installiert werden", report.reason_skipped)

    @patch("core.verifier.CodeSandbox.run_command")
    def test_malformed_bandit_output_is_reported_as_not_attempted(self, mock_run):
        mock_run.side_effect = [_OK, ExecutionResult(exit_code=2, stdout="not valid json", stderr="crash", duration_seconds=0.1)]
        verifier = ProjectVerifier(self.project_dir)

        report = verifier.check_sast()

        self.assertFalse(report.attempted)
        self.assertTrue(report.passed)  # nicht messbar != Fehler
        self.assertIn("kein gültiges Ergebnis", report.reason_skipped)


if __name__ == "__main__":
    unittest.main()
