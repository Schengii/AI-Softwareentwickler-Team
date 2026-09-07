"""
tests/test_check_interop_command.py – Testet `/check-interop <aufrufendes_projekt> <ziel_projekt>`
(interface/cli.py._check_cross_project_interop())

KI-Team-Analyse 07.09.2026, Punkt 9 "Fehlende Interoperabilitäts-Tests zwischen generierten
Projekten": statischer Cross-Projekt-Contract-Check zwischen zwei workspace/-Projekten.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.workspace import WorkspaceManager
from interface.cli import CLIInterface


class TestCheckInteropCommand(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.cli = CLIInterface()
        self.cli._workspace = WorkspaceManager(self.temp_workspace)
        self.cli._loaded_project_dir = None

        self.caller_dir = Path(self.temp_workspace) / "event_relay"
        self.caller_dir.mkdir()
        (self.caller_dir / "client.py").write_text(
            'import requests\n\ndef notify():\n    requests.post("/api/events")\n', encoding="utf-8",
        )

        self.provider_dir = Path(self.temp_workspace) / "taskpulse"
        self.provider_dir.mkdir()
        (self.provider_dir / "main.py").write_text(
            'from fastapi import FastAPI\napp = FastAPI()\n\n'
            '@app.get("/api/notes")\ndef list_notes():\n    return []\n',
            encoding="utf-8",
        )

    @patch("interface.cli.console.print")
    def test_missing_args_shows_usage_hint(self, mock_print):
        self.cli._check_cross_project_interop(["event_relay"])
        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        self.assertIn("Nutzung", printed)

    @patch("interface.cli.console.print")
    def test_unknown_caller_project_is_reported(self, mock_print):
        self.cli._check_cross_project_interop(["does_not_exist", "taskpulse"])
        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        self.assertIn("does_not_exist", printed)

    @patch("interface.cli.console.print")
    def test_mismatch_between_real_projects_is_reported(self, mock_print):
        self.cli._check_cross_project_interop(["event_relay", "taskpulse"])
        panel = mock_print.call_args_list[0].args[0]
        rendered = str(panel.renderable)
        self.assertIn("Mismatches gefunden", rendered)
        self.assertIn("/api/events", rendered)
        self.assertEqual(panel.border_style, "red")


if __name__ == "__main__":
    unittest.main()
