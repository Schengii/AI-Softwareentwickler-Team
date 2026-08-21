"""
tests/test_ci_failure_creates_backlog_ticket.py – Testet die Folgeaktion bei rotem CI

Realer Fund: interface/cli.py._report_ci_status() wartete zwar echt auf die CI-Pipeline und
zeigte "❌ CI fehlgeschlagen" in der Konsole - aber danach passierte NICHTS. Kein
Backlog-Ticket, kein Hinweis in /backlog, keine Weiterverfolgung. Ein rotes CI blieb
komplett folgenlos, obwohl der Push/PR-Vorgang selbst als "review"/"done" im Backlog stand.
_report_ci_status() gibt jetzt (status, detail) zurück, und _ask_for_git_push() überschreibt
den Ticket-Endstatus mit "blocked", sobald CI wirklich fehlschlägt.
"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import core.backlog_store as backlog_store
from interface.cli import CLIInterface


class TestCiFailureCreatesBacklogTicket(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()
        self._backlog_dir = tempfile.mkdtemp()
        self._backlog_patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(self._backlog_dir) / "backlog.json")
        self._backlog_patcher.start()
        self.addCleanup(self._backlog_patcher.stop)
        self.fake_github = MagicMock()
        self.fake_github.get_status.return_value = "M some_file.py"
        self.fake_github.get_diff.return_value = "some_file.py | 3 +--"
        self.fake_github.commit.return_value = (True, "commit ok")
        self.fake_github.push.return_value = (True, "push ok")
        self.fake_github.get_current_branch.return_value = "main"
        self.fake_github.scan_for_secrets.return_value = []
        self.fake_github.gh_ready.return_value = False  # Direct-Push-Pfad, PR-Workflow nicht Testgegenstand
        self.cli._orchestrator._agents["github"] = self.fake_github
        self.cli._orchestrator.last_verification_ok = True
        self._print_patcher = patch("interface.cli.console.print")
        self._print_patcher.start()
        self.addCleanup(self._print_patcher.stop)

    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_failed_ci_downgrades_ticket_to_blocked_with_reason(self, _mock_confirm):
        self.fake_github.wait_for_ci_status = AsyncMock(
            return_value=("failed", "Tests (Python 3.12): conclusion=failure")
        )

        asyncio.run(self.cli._ask_for_git_push("Testaufgabe"))

        tickets = backlog_store.list_tickets()
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0].status, "blocked")
        self.assertIn("CI fehlgeschlagen", tickets[0].detail)
        self.assertIn("conclusion=failure", tickets[0].detail)

    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_passed_ci_keeps_ticket_done(self, _mock_confirm):
        self.fake_github.wait_for_ci_status = AsyncMock(return_value=("passed", "actions/runs/1"))

        asyncio.run(self.cli._ask_for_git_push("Testaufgabe"))

        tickets = backlog_store.list_tickets()
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0].status, "done")

    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_no_run_ci_status_does_not_block_ticket(self, _mock_confirm):
        """no_run (kein gh verfügbar, kein Remote, ...) ist kein Fehler - darf den sonst
        erfolgreichen Push-Status nicht künstlich auf 'blocked' herabstufen."""
        self.fake_github.wait_for_ci_status = AsyncMock(return_value=("no_run", "kein CI konfiguriert"))

        asyncio.run(self.cli._ask_for_git_push("Testaufgabe"))

        tickets = backlog_store.list_tickets()
        self.assertEqual(tickets[0].status, "done")


if __name__ == "__main__":
    unittest.main()
