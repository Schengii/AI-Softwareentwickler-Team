"""
tests/test_cli_load_with_task.py – Testet den kombinierten `/load <projekt> [aufgabe]`-Modus
von interface/cli.py._handle_command().

Realer Fund: `/load opspilot Baue das Dashboard` interpretierte bisher den GESAMTEN Rest nach
`/load` (inkl. der Aufgabenbeschreibung "opspilot Baue das Dashboard") als EINEN einzigen Pfad/
Projektnamen. Unter Windows führte das bei längeren Aufgabenbeschreibungen zu einem `WinError 3`
(Path too long / Invalid Path), weil aus Fließtext ein nie existierender Dateisystempfad gebaut
wurde. Jetzt ist NUR das erste Argument der Projektname/-pfad - alles danach wird, sobald das
Projekt geladen ist, sofort als Folgeaufgabe an _process_task() übergeben.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from interface.cli import CLIInterface


class TestCLILoadWithTask(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cli = CLIInterface()
        # _workspace/_orchestrator sind reale Instanzen (siehe __init__) - für diesen Test
        # reicht es, read_existing_project_context() gezielt zu mocken, statt eine echte
        # Projektstruktur auf der Platte anzulegen.
        self.cli._workspace = MagicMock()
        self.cli._workspace.read_existing_project_context.return_value = "# app.py\nprint('hi')"
        self.cli._workspace.get_project_dir.return_value = "workspace/opspilot"
        self.cli._orchestrator._history = MagicMock()

    async def test_load_with_trailing_task_parses_only_first_arg_as_project(self):
        """`/load opspilot Baue das Dashboard` darf NICHT `opspilot Baue das Dashboard` als
        einen einzigen Pfad an read_existing_project_context() übergeben (WinError 3-Ursache)."""
        with patch.object(self.cli, "_process_task", new=AsyncMock()) as mock_process_task:
            await self.cli._handle_command("/load opspilot Baue das Dashboard")

        self.cli._workspace.read_existing_project_context.assert_called_once_with("opspilot")
        mock_process_task.assert_awaited_once_with("Baue das Dashboard")

    async def test_load_without_trailing_task_keeps_old_behavior(self):
        """Ohne Folgeaufgabe (`/load opspilot`) wird weiterhin nur geladen und NICHT
        automatisch eine leere Aufgabe an das Team übergeben."""
        with patch.object(self.cli, "_process_task", new=AsyncMock()) as mock_process_task:
            await self.cli._handle_command("/load opspilot")

        self.cli._workspace.read_existing_project_context.assert_called_once_with("opspilot")
        mock_process_task.assert_not_awaited()

    async def test_load_without_args_still_shows_usage_hint(self):
        with patch.object(self.cli, "_process_task", new=AsyncMock()) as mock_process_task:
            result = await self.cli._handle_command("/load")

        self.assertFalse(result)
        self.cli._workspace.read_existing_project_context.assert_not_called()
        mock_process_task.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
