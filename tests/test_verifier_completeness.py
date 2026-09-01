"""
tests/test_verifier_completeness.py – Testet den Vollständigkeits-Check
(core/verifier.py.check_completeness()).

Realer Fund (Bestandsaufnahme cloudvault-Projekt, siehe core/verifier/completeness.py): eine
Testsuite bestand vollständig, obwohl ein Endpunkt nur den Kommentar "Hier würde die
AES-256-GCM Verschlüsselung ... erfolgen" statt echter Verschlüsselung enthielt, und obwohl
das README auf eine nie generierte requirements.txt verwies. check_completeness() erkennt
beide Fälle.
"""

import tempfile
import unittest
from pathlib import Path

from core.verifier import ProjectVerifier


class TestCompletenessCheck(unittest.TestCase):
    def test_no_source_files_not_attempted(self):
        with tempfile.TemporaryDirectory() as tmp:
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.attempted)

    def test_clean_project_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app.py").write_text(
                "def encrypt(data: bytes) -> bytes:\n    return real_aes_encrypt(data)\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.attempted)
            self.assertTrue(report.passed)
            self.assertEqual(report.issues, [])

    def test_detects_stub_comment(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app.py").write_text(
                "async def upload_file(file):\n"
                "    # Hier würde die AES-256-GCM Verschlüsselung und S3-Speicherung erfolgen\n"
                "    return {'id': 1}\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.attempted)
            self.assertFalse(report.passed)
            self.assertEqual(len(report.issues), 1)
            self.assertEqual(report.issues[0].file_path, "app.py")
            self.assertEqual(report.issues[0].line_number, 2)

    def test_detects_not_implemented_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "auth.py").write_text(
                "def verify_token(token):\n    raise NotImplementedError\n",
                encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertEqual(len(report.issues), 1)

    def test_detects_missing_readme_referenced_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app.py").write_text("def main():\n    pass\n", encoding="utf-8")
            (project_dir / "README.md").write_text(
                "## Setup\n```bash\npip install -r requirements.txt\n```\n", encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertFalse(report.passed)
            self.assertTrue(any("requirements.txt" in i.message for i in report.issues))

    def test_existing_readme_referenced_file_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app.py").write_text("def main():\n    pass\n", encoding="utf-8")
            (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
            (project_dir / "README.md").write_text(
                "## Setup\n```bash\npip install -r requirements.txt\n```\n", encoding="utf-8",
            )
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)

    def test_ignores_venv_and_node_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app.py").write_text("def main():\n    pass\n", encoding="utf-8")
            venv_dir = project_dir / ".ai_team_venv" / "lib"
            venv_dir.mkdir(parents=True)
            (venv_dir / "dep.py").write_text("# Hier würde das erfolgen\n", encoding="utf-8")
            verifier = ProjectVerifier(tmp)
            report = verifier.check_completeness()
            self.assertTrue(report.passed)


if __name__ == "__main__":
    unittest.main()
