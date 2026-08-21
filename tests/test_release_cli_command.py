"""
tests/test_release_cli_command.py – Testet den CLI-Befehl `/release`

interface/cli.py._create_release_with_confirmation() ruft core/release_manager.py auf, um
den nächsten SemVer-Bump vorzuschlagen, und erstellt bei Bestätigung einen echten Tag +
GitHub-Release. github_agent hier gemockt (core/release_manager.py selbst ist bereits real
gegen ein Git-Repo getestet, siehe test_release_manager.py) - analog zu
test_rollback_workflow.py.TestRollbackCliCommand für dasselbe Prinzip.
"""

import asyncio
import unittest
from unittest.mock import MagicMock, patch

from interface.cli import CLIInterface


class TestReleaseCliCommand(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()
        self.fake_github = MagicMock()
        self.fake_github.gh_ready.return_value = True
        self.cli._orchestrator._agents["github"] = self.fake_github
        self._print_patcher = patch("interface.cli.console.print")
        self._print_patcher.start()
        self.addCleanup(self._print_patcher.stop)

    @patch("interface.cli.release_manager.create_release")
    @patch("interface.cli.release_manager.get_commits_since")
    @patch("interface.cli.release_manager.get_latest_tag")
    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_creates_release_with_computed_next_version(self, _confirm, mock_latest, mock_commits, mock_create):
        mock_latest.return_value = "v1.0.0"
        mock_commits.return_value = ["feat: neue Sache"]
        mock_create.return_value = (True, "https://github.com/x/y/releases/tag/v1.1.0")

        asyncio.run(self.cli._create_release_with_confirmation())

        mock_create.assert_called_once()
        version_arg = mock_create.call_args[0][0]
        self.assertEqual(version_arg, "v1.1.0")

    @patch("interface.cli.release_manager.get_commits_since")
    @patch("interface.cli.release_manager.get_latest_tag")
    def test_no_commits_since_last_release_skips_confirmation_entirely(self, mock_latest, mock_commits):
        mock_latest.return_value = "v1.0.0"
        mock_commits.return_value = []

        with patch("interface.cli.Confirm.ask") as mock_confirm:
            asyncio.run(self.cli._create_release_with_confirmation())
            mock_confirm.assert_not_called()

    @patch("interface.cli.release_manager.create_release")
    @patch("interface.cli.release_manager.get_commits_since")
    @patch("interface.cli.release_manager.get_latest_tag")
    @patch("interface.cli.Confirm.ask", return_value=False)
    def test_declining_confirmation_never_creates_a_release(self, _confirm, mock_latest, mock_commits, mock_create):
        mock_latest.return_value = "v1.0.0"
        mock_commits.return_value = ["fix: x"]

        asyncio.run(self.cli._create_release_with_confirmation())

        mock_create.assert_not_called()

    def test_missing_gh_cli_blocks_release_before_any_lookup(self):
        self.fake_github.gh_ready.return_value = False

        with patch("interface.cli.release_manager.get_latest_tag") as mock_latest:
            asyncio.run(self.cli._create_release_with_confirmation())
            mock_latest.assert_not_called()

    @patch("interface.cli.release_manager.create_release")
    @patch("interface.cli.release_manager.get_commits_since")
    @patch("interface.cli.release_manager.get_latest_tag")
    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_no_prior_release_uses_v0_0_0_as_baseline(self, _confirm, mock_latest, mock_commits, mock_create):
        """Erstes Release überhaupt (noch kein Tag) - Vorschlag soll trotzdem funktionieren."""
        mock_latest.return_value = None
        mock_commits.return_value = ["feat: erstes Feature"]
        mock_create.return_value = (True, "url")

        asyncio.run(self.cli._create_release_with_confirmation())

        version_arg = mock_create.call_args[0][0]
        self.assertEqual(version_arg, "v0.1.0")


if __name__ == "__main__":
    unittest.main()
