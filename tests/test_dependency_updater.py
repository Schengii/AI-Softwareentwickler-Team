"""
tests/test_dependency_updater.py – Testet core/dependency_updater.py (automatisches Anheben
verwundbarer Python-Abhängigkeiten in requirements.txt, Grundlage für den Dependabot-artigen
Auto-Update-PR aus core/dependency_watch.py).
"""

import tempfile
import unittest
from pathlib import Path

from core.dependency_updater import apply_python_dependency_fixes
from core.verifier import DependencyAuditReport, DependencyVulnerability


def _pip_audit_report(vulns: list[DependencyVulnerability]) -> DependencyAuditReport:
    return DependencyAuditReport(attempted=True, vulnerable=True, tool="pip-audit", vulnerabilities=vulns)


class TestApplyPythonDependencyFixes(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def _write_requirements(self, content: str) -> Path:
        req = self.temp_dir / "requirements.txt"
        req.write_text(content, encoding="utf-8")
        return req

    def test_bumps_vulnerable_package_to_first_fix_version(self):
        self._write_requirements("fastapi==0.100.0\nurllib3==1.24.1\npytest==7.0.0\n")
        report = _pip_audit_report([
            DependencyVulnerability(
                package="urllib3", version="1.24.1", vulnerability_id="PYSEC-2019-133",
                description="...", fix_versions=["1.24.2", "1.25.0"],
            ),
        ])

        changed = apply_python_dependency_fixes(self.temp_dir, [report])

        self.assertEqual(changed, ["urllib3: 1.24.1 -> 1.24.2"])
        new_content = (self.temp_dir / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("urllib3==1.24.2", new_content)
        self.assertIn("fastapi==0.100.0", new_content)  # unbetroffene Zeilen bleiben unverändert
        self.assertIn("pytest==7.0.0", new_content)

    def test_preserves_extras_in_pin(self):
        self._write_requirements("uvicorn[standard]==0.20.0\n")
        report = _pip_audit_report([
            DependencyVulnerability(
                package="uvicorn", version="0.20.0", vulnerability_id="CVE-x",
                description="...", fix_versions=["0.20.1"],
            ),
        ])

        changed = apply_python_dependency_fixes(self.temp_dir, [report])

        self.assertEqual(changed, ["uvicorn: 0.20.0 -> 0.20.1"])
        new_content = (self.temp_dir / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("uvicorn[standard]==0.20.1", new_content)

    def test_no_fix_versions_leaves_file_untouched(self):
        original = "urllib3==1.24.1\n"
        self._write_requirements(original)
        report = _pip_audit_report([
            DependencyVulnerability(
                package="urllib3", version="1.24.1", vulnerability_id="PYSEC-2019-133",
                description="...",  # keine fix_versions -> nichts anhebbar
            ),
        ])

        changed = apply_python_dependency_fixes(self.temp_dir, [report])

        self.assertEqual(changed, [])
        self.assertEqual((self.temp_dir / "requirements.txt").read_text(encoding="utf-8"), original)

    def test_missing_requirements_file_returns_empty(self):
        report = _pip_audit_report([
            DependencyVulnerability(
                package="urllib3", version="1.24.1", vulnerability_id="x",
                description="...", fix_versions=["1.24.2"],
            ),
        ])
        changed = apply_python_dependency_fixes(self.temp_dir, [report])
        self.assertEqual(changed, [])

    def test_non_pip_audit_reports_are_ignored(self):
        self._write_requirements("urllib3==1.24.1\n")
        npm_report = DependencyAuditReport(
            attempted=True, vulnerable=True, tool="npm audit",
            vulnerabilities=[DependencyVulnerability(
                package="urllib3", version="1.24.1", vulnerability_id="x",
                description="...", fix_versions=["1.24.2"],
            )],
        )
        changed = apply_python_dependency_fixes(self.temp_dir, [npm_report])
        self.assertEqual(changed, [])

    def test_package_name_matching_is_case_and_separator_insensitive(self):
        self._write_requirements("My_Package==1.0.0\n")
        report = _pip_audit_report([
            DependencyVulnerability(
                package="my-package", version="1.0.0", vulnerability_id="x",
                description="...", fix_versions=["1.0.1"],
            ),
        ])
        changed = apply_python_dependency_fixes(self.temp_dir, [report])
        self.assertEqual(changed, ["my-package: 1.0.0 -> 1.0.1"])
        new_content = (self.temp_dir / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("My_Package==1.0.1", new_content)

    def test_comments_and_blank_lines_are_preserved(self):
        self._write_requirements("# core deps\n\nurllib3==1.24.1\n")
        report = _pip_audit_report([
            DependencyVulnerability(
                package="urllib3", version="1.24.1", vulnerability_id="x",
                description="...", fix_versions=["1.24.2"],
            ),
        ])
        apply_python_dependency_fixes(self.temp_dir, [report])
        new_content = (self.temp_dir / "requirements.txt").read_text(encoding="utf-8")
        self.assertTrue(new_content.startswith("# core deps\n\n"))


if __name__ == "__main__":
    unittest.main()
