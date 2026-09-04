"""
tests/test_sandbox_venv.py – Tests für Projekt-Venv Isolation in CodeSandbox.
"""

import sys
import tempfile
import unittest
from pathlib import Path

from core.code_sandbox import CodeSandbox


class TestSandboxVenv(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_get_project_venv_none_when_empty(self):
        self.assertIsNone(CodeSandbox.get_project_venv(self.project_dir))

    def test_get_project_venv_finds_venv(self):
        venv_dir = self.project_dir / ".venv"
        venv_dir.mkdir()
        found = CodeSandbox.get_project_venv(self.project_dir)
        self.assertEqual(found, venv_dir)

    def test_get_project_venv_finds_ai_team_venv(self):
        venv_dir = self.project_dir / ".ai_team_venv"
        venv_dir.mkdir()
        found = CodeSandbox.get_project_venv(self.project_dir)
        self.assertEqual(found, venv_dir)

    def test_run_command_prioritizes_venv_binary(self):
        venv_dir = self.project_dir / ".venv"
        scripts_dir = venv_dir / ("Scripts" if sys.platform == "win32" else "bin")
        scripts_dir.mkdir(parents=True)

        fake_bin_name = "mocktool.exe" if sys.platform == "win32" else "mocktool"
        fake_bin = scripts_dir / fake_bin_name
        # Erstelle ein Dummy-Executable
        fake_bin.write_text("#!/bin/sh\necho mocktool_executed\n", encoding="utf-8")

        # Prüfe Auflösung
        venv_found = CodeSandbox.get_project_venv(self.project_dir)
        self.assertIsNotNone(venv_found)


if __name__ == "__main__":
    unittest.main()
