"""
tests/test_verifier_license.py – Testet den echten Open-Source-Lizenz-Scan
(core/verifier.py.check_licenses())

Realer Fund: der compliance-Agent konnte die Lizenzen fremder Abhängigkeiten bisher nur
"plausibel" einschätzen (LLM-Vermutung in einer Freitext-Tabelle, z. B. "MIT/AGPL 🔴"), ohne
echten Blick auf die tatsächlich installierten Paket-Metadaten. `pip-licenses` wird dabei
ECHT über `shutil.which()`/`CodeSandbox.run_command` gemockt (dasselbe Muster wie beim
Dependency-Audit) – die Fixture-JSON ist wortgetreu am realen `pip-licenses --format=json`-
Ausgabeformat orientiert.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.code_sandbox import ExecutionResult
from core.verifier import ProjectVerifier

_REAL_PIP_LICENSES_WITH_COPYLEFT = json.dumps([
    {"Name": "requests", "Version": "2.31.0", "License": "Apache Software License"},
    {"Name": "gpl-lib", "Version": "1.0.0", "License": "GNU General Public License v3 (GPLv3)"},
])

_REAL_PIP_LICENSES_CLEAN = json.dumps([
    {"Name": "requests", "Version": "2.31.0", "License": "Apache Software License"},
    {"Name": "flask", "Version": "3.0.0", "License": "BSD License"},
])


class TestPipLicensesIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        (self.project_dir / "requirements.txt").write_text("requests==2.31.0\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/pip-licenses")
    def test_reports_copyleft_risk(self, mock_which, mock_run):
        mock_run.return_value = ExecutionResult(exit_code=0, stdout=_REAL_PIP_LICENSES_WITH_COPYLEFT, stderr="", duration_seconds=1.0)
        verifier = ProjectVerifier(self.project_dir)

        reports = verifier.check_licenses()

        self.assertEqual(len(reports), 1)
        report = reports[0]
        self.assertTrue(report.attempted)
        self.assertTrue(report.has_copyleft_risk)
        self.assertEqual(report.tool, "pip-licenses")
        self.assertEqual(len(report.findings), 2)
        gpl_finding = next(f for f in report.findings if f.package == "gpl-lib")
        self.assertTrue(gpl_finding.copyleft)
        requests_finding = next(f for f in report.findings if f.package == "requests")
        self.assertFalse(requests_finding.copyleft)
        mock_run.assert_called_once()
        self.assertEqual(mock_run.call_args[0][0][0], "pip-licenses")

    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/pip-licenses")
    def test_reports_clean_when_no_copyleft(self, mock_which, mock_run):
        mock_run.return_value = ExecutionResult(exit_code=0, stdout=_REAL_PIP_LICENSES_CLEAN, stderr="", duration_seconds=1.0)
        verifier = ProjectVerifier(self.project_dir)

        report = verifier.check_licenses()[0]

        self.assertTrue(report.attempted)
        self.assertFalse(report.has_copyleft_risk)
        self.assertEqual(len(report.findings), 2)

    @patch("core.verifier.shutil.which", return_value=None)
    def test_skipped_gracefully_when_pip_licenses_not_installed(self, mock_which):
        verifier = ProjectVerifier(self.project_dir)
        report = verifier.check_licenses()[0]

        self.assertFalse(report.attempted)
        self.assertFalse(report.has_copyleft_risk)
        self.assertIn("nicht installiert", report.reason_skipped)

    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/pip-licenses")
    def test_technical_failure_is_never_reported_as_clean(self, mock_which, mock_run):
        """Ein kaputtes/leeres Ergebnis darf NIE als 'kein Copyleft-Risiko' gelten."""
        mock_run.return_value = ExecutionResult(exit_code=1, stdout="", stderr="Traceback: crashed", duration_seconds=1.0)
        verifier = ProjectVerifier(self.project_dir)

        report = verifier.check_licenses()[0]

        self.assertFalse(report.attempted)
        self.assertFalse(report.has_copyleft_risk)
        self.assertIn("kein gültiges Ergebnis", report.reason_skipped)

    def test_no_report_without_requirements_file(self):
        empty_project = tempfile.mkdtemp()
        try:
            verifier = ProjectVerifier(empty_project)
            self.assertEqual(verifier.check_licenses(), [])
        finally:
            shutil.rmtree(empty_project, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
