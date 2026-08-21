"""
tests/test_adr_command.py – Testet /adr (interface/cli.py._show_adrs())
"""

import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rich.console import Console as RichConsole

from core.adr import write_adr
from interface.cli import CLIInterface


def _render(mock_print) -> str:
    """console.print() bekommt bei Erfolg ein rich.table.Table-Objekt, kein Klartext - über
    eine eigene, aufzeichnende Console gerendert prüfen statt gegen rich-Interna zu greifen
    (dasselbe Prinzip wie tests/test_cli_learnings_commands.py)."""
    capture = RichConsole(record=True, width=120, file=io.StringIO())
    for call in mock_print.call_args_list:
        for arg in call.args:
            capture.print(arg)
    return capture.export_text()


class TestShowAdrsCommand(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()
        self.temp_workspace = tempfile.mkdtemp()
        self.cli._workspace.base_dir = Path(self.temp_workspace)
        (self.cli._workspace.base_dir / "demo_project").mkdir()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    @patch("interface.cli.console.print")
    def test_shows_table_with_recorded_decisions(self, mock_print):
        project_dir = self.cli._workspace.base_dir / "demo_project"
        write_adr(project_dir, "PostgreSQL statt MongoDB", "Kontext", "Entscheidung", "Konsequenzen")

        self.cli._show_adrs("demo_project")

        self.assertIn("PostgreSQL statt MongoDB", _render(mock_print))

    @patch("interface.cli.console.print")
    def test_project_without_adrs_shows_empty_hint_not_crash(self, mock_print):
        self.cli._show_adrs("demo_project")
        self.assertIn("Noch keine", _render(mock_print))

    @patch("interface.cli.console.print")
    def test_nonexistent_project_is_reported_without_crashing(self, mock_print):
        self.cli._show_adrs("does_not_exist")
        self.assertIn("existiert nicht", _render(mock_print))

    @patch("interface.cli.console.print")
    def test_no_project_given_and_none_loaded_shows_hint(self, mock_print):
        self.cli._loaded_project_dir = None
        self.cli._show_adrs(None)
        self.assertIn("Kein Projekt angegeben", _render(mock_print))

    @patch("interface.cli.console.print")
    def test_uses_loaded_project_when_no_name_given(self, mock_print):
        project_dir = self.cli._workspace.base_dir / "demo_project"
        write_adr(project_dir, "REST statt GraphQL", "K", "E", "K")
        self.cli._loaded_project_dir = str(project_dir)

        self.cli._show_adrs(None)

        self.assertIn("REST statt GraphQL", _render(mock_print))


if __name__ == "__main__":
    unittest.main()
