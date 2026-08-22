"""
tests/test_cli_backlog_commands.py – Testet /backlog und /backlog-add (interface/cli.py)

Sprint-/Kapazitäts-Konzept: bisher entstand JEDES Backlog-Ticket erst, wenn eine Aufgabe
bereits lief - es gab keine Möglichkeit, mehrere geplante Aufgaben VORAB zu priorisieren.
/backlog-add legt ein noch nicht begonnenes, priorisiertes "todo"-Ticket an; /backlog zeigt
zusätzlich eine WIP-Limit-Warnung (config.BACKLOG_WIP_LIMIT_IN_PROGRESS).
"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import core.backlog_store as backlog_store
from interface.cli import CLIInterface


class TestBacklogAddCommand(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()
        self.temp_dir = tempfile.mkdtemp()
        self._patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(self.temp_dir) / "backlog.json")
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    @patch("interface.cli.console.print")
    def test_add_without_priority_defaults_to_medium(self, mock_print):
        asyncio.run(self.cli._handle_command("/backlog-add Login-Seite bauen"))

        tickets = backlog_store.list_tickets()
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0].title, "Login-Seite bauen")
        self.assertEqual(tickets[0].status, "todo")
        self.assertEqual(tickets[0].priority, 2)
        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        self.assertIn("angelegt", printed)

    @patch("interface.cli.console.print")
    def test_add_with_leading_priority_word_sets_priority_and_strips_it_from_title(self, mock_print):
        asyncio.run(self.cli._handle_command("/backlog-add hoch Login-Seite bauen"))

        tickets = backlog_store.list_tickets()
        self.assertEqual(tickets[0].title, "Login-Seite bauen")
        self.assertEqual(tickets[0].priority, 1)

    @patch("interface.cli.console.print")
    def test_add_with_numeric_priority(self, mock_print):
        asyncio.run(self.cli._handle_command("/backlog-add 3 Kleines Aufräumen"))

        tickets = backlog_store.list_tickets()
        self.assertEqual(tickets[0].title, "Kleines Aufräumen")
        self.assertEqual(tickets[0].priority, 3)

    @patch("interface.cli.console.print")
    def test_title_that_starts_with_a_priority_word_but_has_no_further_text_is_kept_as_title(self, mock_print):
        # "hoch" allein (kein Titel mehr übrig) wird NICHT als Prioritäts-Flag interpretiert,
        # sondern bleibt der komplette Titel - siehe Kommentar in interface/cli.py.
        asyncio.run(self.cli._handle_command("/backlog-add hoch"))

        tickets = backlog_store.list_tickets()
        self.assertEqual(tickets[0].title, "hoch")
        self.assertEqual(tickets[0].priority, 2)

    @patch("interface.cli.console.print")
    def test_missing_title_shows_usage_hint_without_crashing(self, mock_print):
        asyncio.run(self.cli._handle_command("/backlog-add"))

        self.assertEqual(backlog_store.list_tickets(), [])
        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        self.assertIn("Titel", printed)


class TestBacklogShowsWipLimitWarning(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()
        self.temp_dir = tempfile.mkdtemp()
        self._patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(self.temp_dir) / "backlog.json")
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        backlog_store.upsert_ticket("t1", "A", "cli", "in_progress")
        backlog_store.upsert_ticket("t2", "B", "cli", "in_progress")
        backlog_store.upsert_ticket("t3", "C", "cli", "in_progress")

    @patch("core.merge_watcher.check_merged_tickets")
    @patch("interface.cli.console.print")
    def test_warning_shown_when_limit_exceeded(self, mock_print, _mock_merge):
        with patch("interface.cli.BACKLOG_WIP_LIMIT_IN_PROGRESS", 2):
            asyncio.run(self.cli._show_backlog())

        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        self.assertIn("WIP-Limit", printed)

    @patch("core.merge_watcher.check_merged_tickets")
    @patch("interface.cli.console.print")
    def test_no_warning_when_disabled(self, mock_print, _mock_merge):
        with patch("interface.cli.BACKLOG_WIP_LIMIT_IN_PROGRESS", 0):
            asyncio.run(self.cli._show_backlog())

        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        self.assertNotIn("WIP-Limit", printed)

    @patch("core.merge_watcher.check_merged_tickets")
    @patch("interface.cli.console.print")
    def test_no_warning_when_within_limit(self, mock_print, _mock_merge):
        with patch("interface.cli.BACKLOG_WIP_LIMIT_IN_PROGRESS", 5):
            asyncio.run(self.cli._show_backlog())

        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        self.assertNotIn("WIP-Limit", printed)


if __name__ == "__main__":
    unittest.main()
