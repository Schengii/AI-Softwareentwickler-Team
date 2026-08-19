"""
tests/test_project_cleanup.py – Testet die vorher toten (nirgends aufgerufenen) Aufräum-Pfade

1. agents/project_cleaner_agent.py::clean_orphaned_files() – jetzt automatisch am Ende
   jedes Orchestrator-Laufs aufgerufen (core/orchestrator.py). Nur sicher regenerierbare
   Cache-Verzeichnisse, nie Quellcode.
2. interface/cli.py::_delete_project_with_confirmation() – jetzt als /delete-project
   erreichbar, mit Bestätigungs-Gate analog zum Git-Push-Gate.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.project_cleaner_agent import ProjectCleanerAgent
from interface.cli import CLIInterface


class TestCleanOrphanedFiles(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        self.agent = ProjectCleanerAgent()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_removes_known_safe_cache_dirs_only(self):
        (self.project_dir / "app" / "__pycache__").mkdir(parents=True)
        (self.project_dir / "__pycache__" / "x.pyc").parent.mkdir(parents=True, exist_ok=True)
        (self.project_dir / ".pytest_cache").mkdir()
        (self.project_dir / ".mypy_cache").mkdir()
        (self.project_dir / "app" / "main.py").parent.mkdir(parents=True, exist_ok=True)
        (self.project_dir / "app" / "main.py").write_text("x = 1")

        removed = self.agent.clean_orphaned_files(str(self.project_dir))

        self.assertGreaterEqual(len(removed), 3)
        self.assertFalse((self.project_dir / "app" / "__pycache__").exists())
        self.assertFalse((self.project_dir / ".pytest_cache").exists())
        self.assertFalse((self.project_dir / ".mypy_cache").exists())
        # Quellcode bleibt unangetastet
        self.assertTrue((self.project_dir / "app" / "main.py").exists())

    def test_missing_directory_returns_empty_list_not_crash(self):
        removed = self.agent.clean_orphaned_files(str(self.project_dir / "does_not_exist"))
        self.assertEqual(removed, [])


class TestDeleteProjectConfirmationGate(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()
        self.temp_workspace = tempfile.mkdtemp()
        self.cli._workspace.base_dir = Path(self.temp_workspace)
        (self.cli._workspace.base_dir / "demo_project").mkdir()
        (self.cli._workspace.base_dir / "demo_project" / "main.py").write_text("x = 1")

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    @patch("interface.cli.Confirm.ask", return_value=False)
    @patch("interface.cli.console.print")
    def test_declining_confirmation_keeps_project(self, mock_print, mock_confirm):
        asyncio.run(self.cli._delete_project_with_confirmation("demo_project"))
        self.assertTrue((self.cli._workspace.base_dir / "demo_project").exists())

    @patch("interface.cli.Confirm.ask", return_value=True)
    @patch("interface.cli.console.print")
    def test_accepting_confirmation_deletes_project(self, mock_print, mock_confirm):
        asyncio.run(self.cli._delete_project_with_confirmation("demo_project"))
        self.assertFalse((self.cli._workspace.base_dir / "demo_project").exists())

    @patch("interface.cli.console.print")
    def test_nonexistent_project_skips_confirmation_entirely(self, mock_print):
        with patch("interface.cli.Confirm.ask") as mock_confirm:
            asyncio.run(self.cli._delete_project_with_confirmation("does_not_exist_at_all"))
            mock_confirm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
