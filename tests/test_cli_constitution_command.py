"""
tests/test_cli_constitution_command.py – Testet /constitution in interface/cli.py

Realer Bedarf: project_slug/Architektur/Tech-Stack werden pro Lauf frisch vom Modell geraten.
/constitution gibt dem Nutzer die Kontrolle, feste Präferenzen EINMAL festzulegen, statt sie
bei jeder Anfrage neu zu spezifizieren (siehe tests/test_project_constitution.py für die
core/project_constitution.py-Seite selbst).
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from core.project_constitution import read_constitution
from core.workspace import WorkspaceManager
from interface.cli import CLIInterface


class TestConstitutionCommand(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()
        self.temp_workspace = tempfile.mkdtemp()
        self.cli._workspace = WorkspaceManager(self.temp_workspace)

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _handle(self, command: str) -> None:
        with patch("interface.cli.console.print"):
            asyncio.run(self.cli._handle_command(command))

    def _make_project(self, name: str) -> str:
        project_dir = self.cli._workspace.get_project_dir(name)
        return str(project_dir)

    def test_no_project_specified_and_none_loaded_shows_hint_not_crash(self):
        self._handle("/constitution")

    def test_unknown_project_shows_error_not_crash(self):
        self._handle("/constitution does_not_exist")

    @patch("interface.cli.Confirm.ask", return_value=False)
    def test_viewing_without_editing_leaves_file_untouched(self, mock_confirm):
        project_dir = self._make_project("my_app")
        from core.project_constitution import write_constitution
        write_constitution(project_dir, {"language": "Python"})

        self._handle("/constitution my_app")

        self.assertEqual(read_constitution(project_dir), {"language": "Python"})

    @patch("interface.cli.Prompt.ask")
    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_setting_fields_on_a_fresh_project_persists_them(self, mock_confirm, mock_prompt):
        project_dir = self._make_project("my_app")
        # Reihenfolge entspricht core.project_constitution.FIELDS.
        mock_prompt.side_effect = ["Python", "FastAPI", "pytest", "", "", ""]

        self._handle("/constitution my_app")

        result = read_constitution(project_dir)
        self.assertEqual(result["language"], "Python")
        self.assertEqual(result["framework"], "FastAPI")
        self.assertEqual(result["test_framework"], "pytest")
        self.assertNotIn("code_style", result)

    @patch("interface.cli.Prompt.ask")
    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_dash_clears_an_existing_field(self, mock_confirm, mock_prompt):
        project_dir = self._make_project("my_app")
        from core.project_constitution import write_constitution
        write_constitution(project_dir, {"language": "Python", "framework": "FastAPI"})
        # "-" löscht framework, alle anderen Felder unverändert (Enter -> gibt den default zurück).
        mock_prompt.side_effect = ["Python", "-", "", "", "", ""]

        self._handle("/constitution my_app")

        result = read_constitution(project_dir)
        self.assertEqual(result["language"], "Python")
        self.assertNotIn("framework", result)

    @patch("interface.cli.Prompt.ask")
    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_uses_loaded_project_when_no_arg_given(self, mock_confirm, mock_prompt):
        project_dir = self._make_project("loaded_app")
        self.cli._loaded_project_dir = project_dir
        mock_prompt.side_effect = ["Python", "", "", "", "", ""]

        self._handle("/constitution")

        self.assertEqual(read_constitution(project_dir)["language"], "Python")


if __name__ == "__main__":
    unittest.main()
