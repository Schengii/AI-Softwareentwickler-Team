"""
tests/test_manifest_guard.py – Testet core/manifest_guard.py sowie dessen Anbindung an alle
Schreibpfade für Dependency-Manifeste (core/agent_toolbox.py, core/workspace.py,
core/verifier/completeness.py).

Realer Fund (zeiterfassung_app-Projekt, 2026-09-04): `requirements.txt` enthielt wörtlich einen
unverarbeiteten Diff-Hunk ("- fastapi\\n+ fastapi==0.110.2\\n..."), wodurch `pip install -r
requirements.txt` mit exit_code=1 fehlschlug und die anschließende Testsuite gegen eine nicht
aktualisierte Umgebung lief.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path

from core.agent_toolbox import AgentToolbox
from core.manifest_guard import detect_corrupted_manifest
from core.verifier import ProjectVerifier
from core.workspace import WorkspaceManager

_CORRUPTED_REQUIREMENTS = (
    "- fastapi\n"
    "- sqlalchemy\n"
    "+ fastapi==0.110.2\n"
    "+ sqlalchemy==2.0.30\n"
)


class TestDetectCorruptedManifest(unittest.TestCase):
    def test_flags_raw_diff_hunk_in_requirements_txt(self):
        message = detect_corrupted_manifest("requirements.txt", _CORRUPTED_REQUIREMENTS)
        self.assertIsNotNone(message)
        self.assertIn("Diff-Hunk", message)

    def test_accepts_valid_requirements_txt(self):
        content = "fastapi==0.110.2\nsqlalchemy==2.0.30\n"
        self.assertIsNone(detect_corrupted_manifest("requirements.txt", content))

    def test_does_not_flag_legitimate_pip_flags(self):
        # "-e .", "-r base.txt", "--index-url ..." sind gültige pip-Optionen, kein Diff-Rest -
        # der entscheidende Unterschied ist das Leerzeichen direkt nach "+"/"-".
        content = "-e .\n-r base.txt\n--index-url https://pypi.org/simple\nfastapi==0.110.2\n"
        self.assertIsNone(detect_corrupted_manifest("requirements.txt", content))

    def test_flags_invalid_json_in_package_json(self):
        message = detect_corrupted_manifest("package.json", '{"name": "x",')
        self.assertIsNotNone(message)
        self.assertIn("JSON", message)

    def test_accepts_valid_package_json(self):
        self.assertIsNone(detect_corrupted_manifest("package.json", '{"name": "x"}'))

    def test_ignores_unrelated_files(self):
        self.assertIsNone(detect_corrupted_manifest("app/main.py", _CORRUPTED_REQUIREMENTS))


class TestAgentToolboxRejectsCorruptedManifest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.toolbox = AgentToolbox(project_dir=self.temp_dir, agent_id="backend")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_write_file_rejects_corrupted_requirements_txt(self):
        result = asyncio.run(self.toolbox._tool_write_file("requirements.txt", _CORRUPTED_REQUIREMENTS))

        self.assertIn("error", result)
        self.assertFalse((Path(self.temp_dir) / "requirements.txt").exists())

    def test_write_file_accepts_valid_requirements_txt(self):
        result = asyncio.run(self.toolbox._tool_write_file("requirements.txt", "fastapi==0.110.2\n"))

        self.assertEqual(result.get("status"), "ok")
        self.assertTrue((Path(self.temp_dir) / "requirements.txt").exists())

    def test_edit_file_rejects_corrupted_result(self):
        target = Path(self.temp_dir) / "requirements.txt"
        target.write_text("fastapi==0.110.1\n", encoding="utf-8")

        result = asyncio.run(self.toolbox._tool_edit_file(
            "requirements.txt", "fastapi==0.110.1\n", _CORRUPTED_REQUIREMENTS,
        ))

        self.assertIn("error", result)
        self.assertEqual(target.read_text(encoding="utf-8"), "fastapi==0.110.1\n")


class TestWorkspaceParseAndSaveSkipsCorruptedManifest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.manager = WorkspaceManager(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_corrupted_requirements_txt_is_not_saved(self):
        text = f"### `requirements.txt`\n```text\n{_CORRUPTED_REQUIREMENTS}```\n"
        saved = self.manager.parse_and_save_files("demo_proj", text, agent_name="backend")

        self.assertEqual(saved, [])
        self.assertFalse((self.manager.get_project_dir("demo_proj") / "requirements.txt").exists())


class TestCompletenessCheckCatchesExistingCorruption(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_flags_pre_existing_corrupted_requirements_txt(self):
        # Zweite Verteidigungslinie: eine bereits auf der Platte liegende korrupte Datei (z.B.
        # aus einem Lauf vor dieser Prüfung) wird auch beim regulären Vollständigkeits-Check
        # erkannt, nicht nur beim Schreiben selbst.
        (self.project_dir / "requirements.txt").write_text(_CORRUPTED_REQUIREMENTS, encoding="utf-8")
        (self.project_dir / "main.py").write_text("print('hi')\n", encoding="utf-8")

        report = ProjectVerifier(self.project_dir).check_completeness()

        self.assertFalse(report.passed)
        self.assertTrue(any("Diff-Hunk" in issue.message for issue in report.issues))


if __name__ == "__main__":
    unittest.main()
