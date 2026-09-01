"""
tests/test_verifier_sast.py – Testet den echten Static-Application-Security-Testing-Scan
(core/verifier.py.check_sast())

Realer Fund: der security-Agent konnte Schwachstellen im SELBST GESCHRIEBENEN Code bisher
nur "plausibel" einschätzen (LLM-Vermutung im Freitext, ohne konkrete Datei/Zeile) – ganz
anders als Abhängigkeits-CVEs, die bereits über einen echten pip-audit/npm-audit-Scan
verifiziert werden (siehe test_verifier_dependency_audit.py). `bandit` wird dabei ECHT über
`shutil.which()`/`CodeSandbox.run_command` gemockt (dasselbe Muster wie beim Dependency-Audit)
– die Fixture-JSON ist wortgetreu am realen bandit-JSON-Ausgabeformat orientiert.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.code_sandbox import ExecutionResult
from core.verifier import ProjectVerifier

# Wortgetreue Struktur eines echten `bandit -r . -f json`-Laufs gegen ein absichtlich
# unsicheres Skript (`subprocess.Popen(cmd, shell=True)`).
_REAL_BANDIT_VULNERABLE = json.dumps({
    "errors": [],
    "results": [
        {
            "filename": "example.py",
            "issue_confidence": "HIGH",
            "issue_severity": "HIGH",
            "issue_text": "subprocess call with shell=True identified, security issue.",
            "line_number": 5,
            "line_range": [5],
            "test_id": "B602",
            "test_name": "subprocess_popen_with_shell_equals_true",
        },
        {
            "filename": "example.py",
            "issue_confidence": "MEDIUM",
            "issue_severity": "LOW",
            "issue_text": "Standard pseudo-random generators are not suitable for security/cryptographic purposes.",
            "line_number": 12,
            "line_range": [12],
            "test_id": "B311",
            "test_name": "blacklist",
        },
    ],
})

_REAL_BANDIT_CLEAN = json.dumps({"errors": [], "results": []})


class TestBanditSastIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        (self.project_dir / "example.py").write_text("import subprocess\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/bandit")
    def test_reports_real_bandit_findings(self, mock_which, mock_run):
        mock_run.return_value = ExecutionResult(exit_code=1, stdout=_REAL_BANDIT_VULNERABLE, stderr="", duration_seconds=1.0)
        verifier = ProjectVerifier(self.project_dir)

        reports = verifier.check_sast()

        self.assertEqual(len(reports), 1)
        report = reports[0]
        self.assertTrue(report.attempted)
        self.assertTrue(report.vulnerable)
        self.assertEqual(report.tool, "bandit")
        self.assertEqual(len(report.findings), 2)
        self.assertEqual(report.findings[0].file_path, "example.py")
        self.assertEqual(report.findings[0].line_number, 5)
        self.assertEqual(report.findings[0].rule, "B602")
        self.assertEqual(report.findings[0].severity, "HIGH")
        mock_run.assert_called_once()
        self.assertEqual(mock_run.call_args[0][0][:3], ["bandit", "-r", str(self.project_dir)])

    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/bandit")
    def test_reports_clean_when_no_findings(self, mock_which, mock_run):
        mock_run.return_value = ExecutionResult(exit_code=0, stdout=_REAL_BANDIT_CLEAN, stderr="", duration_seconds=1.0)
        verifier = ProjectVerifier(self.project_dir)

        report = verifier.check_sast()[0]

        self.assertTrue(report.attempted)
        self.assertFalse(report.vulnerable)
        self.assertEqual(report.findings, [])

    @patch("core.verifier.shutil.which", return_value=None)
    def test_skipped_gracefully_when_bandit_not_installed(self, mock_which):
        verifier = ProjectVerifier(self.project_dir)
        report = verifier.check_sast()[0]

        self.assertFalse(report.attempted)
        self.assertFalse(report.vulnerable)
        self.assertIn("nicht installiert", report.reason_skipped)

    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/bandit")
    def test_technical_failure_is_never_reported_as_clean(self, mock_which, mock_run):
        """Ein kaputtes/leeres Ergebnis darf NIE als 'sauber' gelten."""
        mock_run.return_value = ExecutionResult(exit_code=2, stdout="", stderr="Traceback: crashed", duration_seconds=1.0)
        verifier = ProjectVerifier(self.project_dir)

        report = verifier.check_sast()[0]

        self.assertFalse(report.attempted)
        self.assertFalse(report.vulnerable)
        self.assertIn("kein gültiges Ergebnis", report.reason_skipped)

    def test_no_report_without_python_files(self):
        empty_project = tempfile.mkdtemp()
        try:
            verifier = ProjectVerifier(empty_project)
            self.assertEqual(verifier.check_sast(), [])
        finally:
            shutil.rmtree(empty_project, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
