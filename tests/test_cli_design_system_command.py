"""
tests/test_cli_design_system_command.py – Testet /design-system in interface/cli.py

Realer Bedarf: das visuelle Design-System (Farbpalette, Typografie, Spacing-Skala, …) sollte
wie der Tech-Stack per /constitution einmal festgelegt werden können, statt bei jedem Lauf am
selben Projekt neu vom Modell erfunden zu werden (siehe tests/test_design_system.py für die
core/design_system.py-Seite selbst).
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from core.design_system import read_design_system
from core.workspace import WorkspaceManager
from interface.cli import CLIInterface


class TestDesignSystemCommand(unittest.TestCase):
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
        self._handle("/design-system")

    def test_unknown_project_shows_error_not_crash(self):
        self._handle("/design-system does_not_exist")

    @patch("interface.cli.Confirm.ask", return_value=False)
    def test_viewing_without_editing_leaves_file_untouched(self, mock_confirm):
        project_dir = self._make_project("my_app")
        from core.design_system import write_design_system
        write_design_system(project_dir, {"color_palette": "Blau"})

        self._handle("/design-system my_app")

        self.assertEqual(read_design_system(project_dir), {"color_palette": "Blau"})

    @patch("interface.cli.Prompt.ask")
    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_setting_fields_on_a_fresh_project_persists_them(self, mock_confirm, mock_prompt):
        project_dir = self._make_project("my_app")
        # Reihenfolge entspricht core.design_system.FIELDS.
        mock_prompt.side_effect = ["Primär #2563EB", "Inter", "", "", "", ""]

        self._handle("/design-system my_app")

        result = read_design_system(project_dir)
        self.assertEqual(result["color_palette"], "Primär #2563EB")
        self.assertEqual(result["typography"], "Inter")
        self.assertNotIn("spacing_scale", result)

    @patch("interface.cli.Prompt.ask")
    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_dash_clears_an_existing_field(self, mock_confirm, mock_prompt):
        project_dir = self._make_project("my_app")
        from core.design_system import write_design_system
        write_design_system(project_dir, {"color_palette": "Blau", "typography": "Inter"})
        # "-" löscht typography, alle anderen Felder unverändert (Enter -> gibt den default zurück).
        mock_prompt.side_effect = ["Blau", "-", "", "", "", ""]

        self._handle("/design-system my_app")

        result = read_design_system(project_dir)
        self.assertEqual(result["color_palette"], "Blau")
        self.assertNotIn("typography", result)

    @patch("interface.cli.Prompt.ask")
    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_uses_loaded_project_when_no_arg_given(self, mock_confirm, mock_prompt):
        project_dir = self._make_project("loaded_app")
        self.cli._loaded_project_dir = project_dir
        mock_prompt.side_effect = ["Blau", "", "", "", "", ""]

        self._handle("/design-system")

        self.assertEqual(read_design_system(project_dir)["color_palette"], "Blau")


if __name__ == "__main__":
    unittest.main()
