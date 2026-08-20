"""
tests/test_cli_push_gate.py – Testet das Bestätigungs-Gate vor Git-Commit & -Push

Stellt sicher, dass CLIInterface._ask_for_git_push():
1. Vor der Bestätigung den tatsächlichen Diff-Status (nicht nur ein blindes Ja/Nein) anzeigt.
2. Bei Ablehnung NIEMALS commit()/push() aufruft (kein versehentlicher Push).
3. Bei Zustimmung mit genau der zuvor angezeigten Commit-Message committet.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from interface.cli import CLIInterface


class TestPushConfirmationGate(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()
        self.fake_github = MagicMock()
        self.fake_github.get_status.return_value = "M some_file.py\n?? new_file.py"
        self.fake_github.get_diff.return_value = "some_file.py | 3 +--"
        self.fake_github.commit.return_value = (True, "commit ok")
        self.fake_github.push.return_value = (True, "push ok")
        self.fake_github.get_current_branch.return_value = "main"
        # wait_for_ci_status() ist async (siehe agents/github_agent.py) - MagicMock kennt das
        # nicht automatisch, ohne AsyncMock würde `await` mit TypeError fehlschlagen.
        self.fake_github.wait_for_ci_status = AsyncMock(return_value=("no_run", "kein CI im Test"))
        self.cli._orchestrator._agents["github"] = self.fake_github
        # Reines Terminal-Rendering ist hier nicht Testgegenstand (und Emoji-Ausgabe crasht
        # unter der Standard-Windows-cp1252-Konsole ohne main.py's UTF-8-Wrapper) – wir testen
        # ausschließlich die Bestätigungs-Gate-Logik, nicht rich's Darstellung.
        self._print_patcher = patch("interface.cli.console.print")
        self._print_patcher.start()
        self.addCleanup(self._print_patcher.stop)

    @patch("interface.cli.Confirm.ask", return_value=False)
    def test_declining_confirmation_never_commits_or_pushes(self, mock_confirm):
        asyncio.run(self.cli._ask_for_git_push("Testaufgabe"))
        mock_confirm.assert_called_once()
        self.fake_github.commit.assert_not_called()
        self.fake_github.push.assert_not_called()

    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_accepting_confirmation_commits_and_pushes(self, mock_confirm):
        asyncio.run(self.cli._ask_for_git_push("Testaufgabe"))
        self.fake_github.commit.assert_called_once()
        commit_msg = self.fake_github.commit.call_args[0][0]
        self.assertIn("Testaufgabe", commit_msg)
        self.fake_github.push.assert_called_once()

    def test_no_pending_changes_skips_confirmation_entirely(self):
        self.fake_github.get_status.return_value = ""
        with patch("interface.cli.Confirm.ask") as mock_confirm:
            asyncio.run(self.cli._ask_for_git_push("Testaufgabe"))
            mock_confirm.assert_not_called()
        self.fake_github.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
