"""
tests/test_verifier_dependency_audit.py – Testet den echten Dependency-Vulnerability-Scan
(core/verifier.py.check_dependency_vulnerabilities())

Realer Fund: der security-Agent konnte Abhängigkeits-Risiken bisher nur "plausibel"
einschätzen (LLM-Vermutung), ohne echten Abgleich gegen eine CVE-/Advisory-Datenbank.
`pip-audit`/`npm audit` werden dabei ECHT über `shutil.which()`/`CodeSandbox.run_command`
gemockt (wie bei den bestehenden Docker-Build-Tests) – die Fixture-JSON-Strings sind dabei
wortgetreu aus einem echten `pip-audit -r requirements.txt -f json` bzw.
`npm audit --json`-Lauf gegen ein absichtlich verwundbares Paket übernommen (kein
geratenes Format), damit der Parser gegen die tatsächliche Tool-Ausgabe geprüft wird, ohne
in der CI von einer echten Netzwerkverbindung zur Advisory-Datenbank abhängig zu sein.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.code_sandbox import ExecutionResult
from core.verifier import ProjectVerifier

# Wortgetreuer Ausschnitt aus einem echten `pip-audit -r requirements.txt -f json`-Lauf
# gegen "urllib3==1.24.1" (bekannte, historische CVEs - bleiben stabil in der DB).
_REAL_PIP_AUDIT_VULNERABLE = json.dumps({
    "dependencies": [
        {
            "name": "urllib3", "version": "1.24.1",
            "vulns": [
                {"id": "PYSEC-2019-133", "fix_versions": ["1.24.2"],
                 "description": "The urllib3 library before 1.24.2 mishandles certain CA certificate cases."},
                {"id": "PYSEC-2019-132", "fix_versions": ["1.24.3"],
                 "description": "CRLF injection is possible if the attacker controls the request parameter."},
            ],
        },
    ],
})

_REAL_PIP_AUDIT_CLEAN = json.dumps({
    "dependencies": [
        {"name": "certifi", "version": "2024.2.2", "vulns": []},
    ],
})

# Wortgetreuer Ausschnitt aus einem echten `npm audit --json`-Lauf gegen "lodash==4.17.4".
_REAL_NPM_AUDIT_VULNERABLE = json.dumps({
    "auditReportVersion": 2,
    "vulnerabilities": {
        "lodash": {
            "name": "lodash", "severity": "critical", "range": "<=4.17.11",
            "via": [
                {"source": 1106900, "name": "lodash", "title": "Prototype Pollution in lodash",
                 "url": "https://github.com/advisories/GHSA-fvqr-27wr-82fm", "severity": "moderate"},
                "some-transitive-dependency-name",
            ],
        },
    },
    "metadata": {"vulnerabilities": {"info": 0, "low": 0, "moderate": 0, "high": 0, "critical": 1, "total": 1}},
})

_REAL_NPM_AUDIT_CLEAN = json.dumps({
    "auditReportVersion": 2, "vulnerabilities": {},
    "metadata": {"vulnerabilities": {"info": 0, "low": 0, "moderate": 0, "high": 0, "critical": 0, "total": 0}},
})

_NPM_AUDIT_ERROR = json.dumps({"error": {"code": "ENOAUDIT", "summary": "Registry returned 500"}})


class TestPipAuditIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        (self.project_dir / "requirements.txt").write_text("urllib3==1.24.1\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/pip-audit")
    def test_reports_real_pip_audit_vulnerabilities(self, mock_which, mock_run):
        mock_run.return_value = ExecutionResult(exit_code=1, stdout=_REAL_PIP_AUDIT_VULNERABLE, stderr="", duration_seconds=1.0)
        verifier = ProjectVerifier(self.project_dir)

        reports = verifier.check_dependency_vulnerabilities()

        self.assertEqual(len(reports), 1)
        report = reports[0]
        self.assertTrue(report.attempted)
        self.assertTrue(report.vulnerable)
        self.assertEqual(report.tool, "pip-audit")
        self.assertEqual(len(report.vulnerabilities), 2)
        self.assertEqual(report.vulnerabilities[0].package, "urllib3")
        self.assertEqual(report.vulnerabilities[0].vulnerability_id, "PYSEC-2019-133")
        mock_run.assert_called_once()
        self.assertEqual(mock_run.call_args[0][0][:2], ["pip-audit", "-r"])

    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/pip-audit")
    def test_reports_clean_when_no_vulnerabilities_found(self, mock_which, mock_run):
        mock_run.return_value = ExecutionResult(exit_code=0, stdout=_REAL_PIP_AUDIT_CLEAN, stderr="", duration_seconds=1.0)
        verifier = ProjectVerifier(self.project_dir)

        report = verifier.check_dependency_vulnerabilities()[0]

        self.assertTrue(report.attempted)
        self.assertFalse(report.vulnerable)
        self.assertEqual(report.vulnerabilities, [])

    @patch("core.verifier.shutil.which", return_value=None)
    def test_skipped_gracefully_when_pip_audit_not_installed(self, mock_which):
        verifier = ProjectVerifier(self.project_dir)
        report = verifier.check_dependency_vulnerabilities()[0]

        self.assertFalse(report.attempted)
        self.assertFalse(report.vulnerable)
        self.assertIn("nicht installiert", report.reason_skipped)

    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/pip-audit")
    def test_technical_failure_is_never_reported_as_clean(self, mock_which, mock_run):
        """Ein kaputtes/leeres Ergebnis (z.B. kein Netzwerk) darf NIE als 'sauber' gelten."""
        mock_run.return_value = ExecutionResult(exit_code=2, stdout="", stderr="ConnectionError: could not reach OSV.dev", duration_seconds=1.0)
        verifier = ProjectVerifier(self.project_dir)

        report = verifier.check_dependency_vulnerabilities()[0]

        self.assertFalse(report.attempted)
        self.assertFalse(report.vulnerable)
        self.assertIn("Netzwerkverbindung", report.reason_skipped)

    def test_no_report_without_requirements_file(self):
        empty_project = tempfile.mkdtemp()
        try:
            verifier = ProjectVerifier(empty_project)
            self.assertEqual(verifier.check_dependency_vulnerabilities(), [])
        finally:
            shutil.rmtree(empty_project, ignore_errors=True)


class TestNpmAuditIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        (self.project_dir / "package.json").write_text(
            json.dumps({"name": "sample", "scripts": {"test": "node test.js"}}), encoding="utf-8",
        )
        (self.project_dir / "test.js").write_text("process.exit(0);\n", encoding="utf-8")
        (self.project_dir / "package-lock.json").write_text("{}", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/npm")
    def test_reports_real_npm_audit_vulnerabilities(self, mock_which, mock_run):
        mock_run.return_value = ExecutionResult(exit_code=1, stdout=_REAL_NPM_AUDIT_VULNERABLE, stderr="", duration_seconds=1.0)
        verifier = ProjectVerifier(self.project_dir)

        reports = verifier.check_dependency_vulnerabilities()

        self.assertEqual(len(reports), 1)
        report = reports[0]
        self.assertTrue(report.attempted)
        self.assertTrue(report.vulnerable)
        self.assertEqual(report.tool, "npm audit")
        # Nur der dict-Eintrag in "via" ist eine eigene Advisory - der String-Eintrag
        # (Verweis auf eine transitive Abhängigkeit) darf NICHT als eigener Fund zählen.
        self.assertEqual(len(report.vulnerabilities), 1)
        self.assertEqual(report.vulnerabilities[0].package, "lodash")
        self.assertEqual(report.vulnerabilities[0].vulnerability_id, "GHSA-fvqr-27wr-82fm")

    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/npm")
    def test_reports_clean_when_no_vulnerabilities_found(self, mock_which, mock_run):
        mock_run.return_value = ExecutionResult(exit_code=0, stdout=_REAL_NPM_AUDIT_CLEAN, stderr="", duration_seconds=1.0)
        verifier = ProjectVerifier(self.project_dir)

        report = verifier.check_dependency_vulnerabilities()[0]

        self.assertTrue(report.attempted)
        self.assertFalse(report.vulnerable)

    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/npm")
    def test_error_response_is_never_reported_as_clean(self, mock_which, mock_run):
        """{"error": {...}} (z.B. Registry down) darf NIE als 'keine Schwachstellen' gelten."""
        mock_run.return_value = ExecutionResult(exit_code=1, stdout=_NPM_AUDIT_ERROR, stderr="", duration_seconds=1.0)
        verifier = ProjectVerifier(self.project_dir)

        report = verifier.check_dependency_vulnerabilities()[0]

        self.assertFalse(report.attempted)
        self.assertFalse(report.vulnerable)
        self.assertIn("Fehler", report.reason_skipped)

    def test_skipped_gracefully_without_lockfile(self):
        (self.project_dir / "package-lock.json").unlink()
        verifier = ProjectVerifier(self.project_dir)

        report = verifier.check_dependency_vulnerabilities()[0]

        self.assertFalse(report.attempted)
        self.assertIn("package-lock.json", report.reason_skipped)

    @patch("core.verifier.shutil.which", return_value=None)
    def test_skipped_gracefully_when_npm_not_installed(self, mock_which):
        verifier = ProjectVerifier(self.project_dir)
        report = verifier.check_dependency_vulnerabilities()[0]

        self.assertFalse(report.attempted)
        self.assertIn("nicht installiert", report.reason_skipped)


if __name__ == "__main__":
    unittest.main()
