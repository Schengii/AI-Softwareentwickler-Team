"""
tests/test_toxic_dependency_sanitation.py – Regressionstests für toxische Paket-Kollisionen

Realer Fund (logipulse-Lauf 2026-09-10): `requirements.txt` enthielt `pyjwt>=2.8.0` UND `jwt`.
Das veraltete PyPI-Paket `jwt` überschreibt den Namespace von PyJWT -> `AttributeError: module
'jwt' has no attribute 'encode'` in jedem Auth-Test, obwohl pip exit_code=0 meldete. Diese Tests
sichern die deterministische Bereinigung in core/manifest_guard.py und ihre Einbindung in
Completeness-Check, Agenten-Toolbox und pip-Installationspfad ab.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.agent_toolbox import AgentToolbox
from core.manifest_guard import (
    find_toxic_dependencies,
    sanitize_requirements,
    sanitize_requirements_file,
)
from core.verifier import ProjectVerifier

_LOGIPULSE_REQUIREMENTS = (
    "fastapi>=0.100.0\n"
    "pydantic>=2.0\n"
    "pytest>=7.4.0\n"
    "pyjwt>=2.8.0\n"
    "jwt\n"
)


class TestFindToxicDependencies(unittest.TestCase):
    def test_flags_jwt_next_to_pyjwt_for_removal(self):
        findings = find_toxic_dependencies("requirements.txt", _LOGIPULSE_REQUIREMENTS)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].package, "jwt")
        self.assertEqual(findings[0].action, "remove")
        self.assertEqual(findings[0].line_number, 5)

    def test_flags_crypto_next_to_cryptography_for_removal(self):
        findings = find_toxic_dependencies("requirements.txt", "cryptography>=42\ncrypto==1.4.1\n")
        self.assertEqual([(f.package, f.action) for f in findings], [("crypto", "remove")])

    def test_matches_case_and_version_specifiers(self):
        findings = find_toxic_dependencies("requirements.txt", "PyJWT[crypto]>=2.8\nJWT==1.3.1  # alt\n")
        self.assertEqual([(f.package, f.action) for f in findings], [("jwt", "remove")])

    def test_ignores_legitimate_look_alikes_comments_and_pip_options(self):
        content = (
            "# jwt\n"
            "python-jose[cryptography]>=3.3\n"
            "pyjwt[crypto]>=2.8\n"
            "-r base.txt\n"
            "--index-url https://pypi.org/simple\n"
            "cryptography>=42\n"
        )
        self.assertEqual(find_toxic_dependencies("requirements.txt", content), [])

    def test_ignores_non_requirements_files(self):
        self.assertEqual(find_toxic_dependencies("src/main.py", _LOGIPULSE_REQUIREMENTS), [])
        self.assertEqual(find_toxic_dependencies("package.json", "jwt\n"), [])

    def test_applies_to_requirements_variants_in_subpaths(self):
        self.assertEqual(len(find_toxic_dependencies("backend/requirements-dev.txt", "pyjwt\njwt\n")), 1)


class TestSanitizeRequirements(unittest.TestCase):
    def test_removes_jwt_and_keeps_everything_else(self):
        sanitized, findings = sanitize_requirements("requirements.txt", _LOGIPULSE_REQUIREMENTS)
        self.assertEqual(len(findings), 1)
        self.assertEqual(sanitized, "fastapi>=0.100.0\npydantic>=2.0\npytest>=7.4.0\npyjwt>=2.8.0\n")

    def test_replaces_standalone_jwt_with_pyjwt_once(self):
        sanitized, findings = sanitize_requirements("requirements.txt", "fastapi\njwt==1.3.1\njwt\n")
        self.assertEqual([f.action for f in findings], ["replace", "remove"])
        self.assertEqual(sanitized, "fastapi\nPyJWT\n")

    def test_removes_standalone_crypto_without_guessing_a_replacement(self):
        sanitized, findings = sanitize_requirements("requirements.txt", "fastapi\ncrypto\n")
        self.assertEqual(findings[0].action, "remove")
        self.assertEqual(sanitized, "fastapi\n")

    def test_clean_manifest_stays_byte_identical(self):
        content = "fastapi==0.110.2\r\npyjwt>=2.8.0"
        sanitized, findings = sanitize_requirements("requirements.txt", content)
        self.assertEqual(findings, [])
        self.assertIs(sanitized, content)


class TestSanitationIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project = Path(self.temp_dir)
        # Ohne jede Quelldatei überspringt check_completeness() den Lauf (attempted=False).
        (self.project / "src").mkdir()
        (self.project / "src" / "main.py").write_text("import jwt\n\nTOKEN = jwt.encode({}, 'k')\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_completeness_check_sanitizes_manifest_on_disk_before_install(self):
        (self.project / "requirements.txt").write_text(_LOGIPULSE_REQUIREMENTS, encoding="utf-8")

        report = ProjectVerifier(self.temp_dir).check_completeness()

        on_disk = (self.project / "requirements.txt").read_text(encoding="utf-8")
        self.assertNotIn("\njwt\n", on_disk)
        self.assertIn("pyjwt>=2.8.0", on_disk)
        self.assertFalse([i for i in report.issues if i.kind == "corrupted_dependency_manifest"])

    def test_completeness_check_reports_corrupted_manifest_when_sanitation_cannot_be_written(self):
        (self.project / "requirements.txt").write_text(_LOGIPULSE_REQUIREMENTS, encoding="utf-8")

        with patch("pathlib.Path.write_text", side_effect=OSError("schreibgeschützt")):
            report = ProjectVerifier(self.temp_dir).check_completeness()

        issues = [i for i in report.issues if i.kind == "corrupted_dependency_manifest"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].file_path, "requirements.txt")
        self.assertIn("jwt", issues[0].message)
        self.assertFalse(report.passed)

    def test_agent_toolbox_write_file_sanitizes_and_warns_agent(self):
        toolbox = AgentToolbox(project_dir=self.temp_dir, agent_id="refactoring")

        result = asyncio.run(toolbox._tool_write_file("requirements.txt", _LOGIPULSE_REQUIREMENTS))

        self.assertEqual(result.get("status"), "ok")
        self.assertIn("jwt", result.get("warning", ""))
        self.assertNotIn("\njwt\n", (self.project / "requirements.txt").read_text(encoding="utf-8"))

    def test_agent_toolbox_edit_file_sanitizes_newly_added_collision(self):
        (self.project / "requirements.txt").write_text("fastapi\npyjwt>=2.8.0\n", encoding="utf-8")
        toolbox = AgentToolbox(project_dir=self.temp_dir, agent_id="backend")

        result = asyncio.run(toolbox._tool_edit_file("requirements.txt", "fastapi\n", "fastapi\njwt\n"))

        self.assertIn("warning", result)
        self.assertEqual((self.project / "requirements.txt").read_text(encoding="utf-8"), "fastapi\npyjwt>=2.8.0\n")

    def test_sanitize_requirements_file_rewrites_only_when_needed(self):
        req = self.project / "requirements.txt"
        req.write_text("cryptography>=42\ncrypto\n", encoding="utf-8")
        self.assertEqual(len(sanitize_requirements_file(req)), 1)
        self.assertEqual(req.read_text(encoding="utf-8"), "cryptography>=42\n")
        self.assertEqual(sanitize_requirements_file(req), [])


if __name__ == "__main__":
    unittest.main()
