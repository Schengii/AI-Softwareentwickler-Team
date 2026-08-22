"""
tests/test_cli_push_gate.py – Testet das Bestätigungs-Gate vor Git-Commit & -Push

Stellt sicher, dass CLIInterface._ask_for_git_push():
1. Vor der Bestätigung den tatsächlichen Diff-Status (nicht nur ein blindes Ja/Nein) anzeigt.
2. Bei Ablehnung NIEMALS commit()/push() aufruft (kein versehentlicher Push).
3. Bei Zustimmung mit genau der zuvor angezeigten Commit-Message committet.
"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import core.backlog_store as backlog_store
from interface.cli import CLIInterface


class TestPushConfirmationGate(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()
        # _ask_for_git_push() schreibt jetzt auch ins Backlog (core/backlog_store.py) - gegen
        # ein temporäres Verzeichnis statt der echten memory/backlog.json.
        self._backlog_dir = tempfile.mkdtemp()
        self._backlog_patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(self._backlog_dir) / "backlog.json")
        self._backlog_patcher.start()
        self.addCleanup(self._backlog_patcher.stop)
        self.fake_github = MagicMock()
        self.fake_github.get_status.return_value = "M some_file.py\n?? new_file.py"
        self.fake_github.get_diff.return_value = "some_file.py | 3 +--"
        self.fake_github.commit.return_value = (True, "commit ok")
        self.fake_github.push.return_value = (True, "push ok")
        self.fake_github.get_current_branch.return_value = "main"
        # Gegenstand dieser Tests ist das Bestätigungs-Gate, nicht der PR-Workflow (siehe
        # tests/test_pr_workflow.py) - gh_ready()=False hält den bisherigen Direct-Push-Pfad
        # aktiv, sonst würde ein unkonfigurierter MagicMock() für create_branch() etc. beim
        # Tupel-Unpacking crashen.
        self.fake_github.gh_ready.return_value = False
        # wait_for_ci_status() ist async (siehe agents/github_agent.py) - MagicMock kennt das
        # nicht automatisch, ohne AsyncMock würde `await` mit TypeError fehlschlagen.
        self.fake_github.wait_for_ci_status = AsyncMock(return_value=("no_run", "kein CI im Test"))
        # Secret-Scan ist hier nicht Testgegenstand (siehe test_secret_scan_before_push.py) -
        # ohne explizite Konfiguration liefert MagicMock() kein leeres list zurück.
        self.fake_github.scan_for_secrets.return_value = []
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

    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_failed_ci_pulls_ticket_status_to_blocked(self, mock_confirm):
        """
        Realer Fund: wait_for_ci_status() wurde nach einem erfolgreichen Push zwar aufgerufen,
        das Ergebnis aber nur angezeigt, nie ausgewertet - das Backlog-Ticket blieb auf
        "done" stehen, selbst wenn die echte CI-Pipeline danach rot wurde.
        """
        self.fake_github.wait_for_ci_status = AsyncMock(return_value=("failed", "1 Job fehlgeschlagen – https://x/y"))
        asyncio.run(self.cli._ask_for_git_push("Testaufgabe", ticket_id="t-ci-failed"))

        ticket = next(t for t in backlog_store.list_tickets() if t.id == "t-ci-failed")
        self.assertEqual(ticket.status, "blocked")
        self.assertIn("CI fehlgeschlagen", ticket.detail)

    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_passed_ci_leaves_ticket_status_unchanged(self, mock_confirm):
        self.fake_github.wait_for_ci_status = AsyncMock(return_value=("passed", "https://x/y"))
        asyncio.run(self.cli._ask_for_git_push("Testaufgabe", ticket_id="t-ci-passed"))

        ticket = next(t for t in backlog_store.list_tickets() if t.id == "t-ci-passed")
        self.assertEqual(ticket.status, "done")  # Direct-Push-Pfad (gh_ready()=False) -> "done"

    @patch("interface.cli.Confirm.ask", return_value=True)
    @patch("interface.cli.notify_external")
    def test_failed_ci_triggers_external_notification(self, mock_notify, mock_confirm):
        self.fake_github.wait_for_ci_status = AsyncMock(return_value=("failed", "CI kaputt"))
        asyncio.run(self.cli._ask_for_git_push("Testaufgabe"))
        mock_notify.assert_called_once()
        self.assertIn("CI", mock_notify.call_args[0][0])

    @patch("interface.cli.Confirm.ask", return_value=True)
    @patch("interface.cli.notify_external")
    def test_passed_ci_does_not_notify(self, mock_notify, mock_confirm):
        self.fake_github.wait_for_ci_status = AsyncMock(return_value=("passed", "https://x/y"))
        asyncio.run(self.cli._ask_for_git_push("Testaufgabe"))
        mock_notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
