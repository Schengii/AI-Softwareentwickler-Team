"""
tests/test_pr_review_watcher.py – Testet core/pr_review_watcher.py (GitHub PR Review Feedback-Loop)
"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import core.backlog_store as backlog_store
from core.pr_review_watcher import (
    PRReviewComment,
    PRReviewPollResult,
    run_pr_review_cycle,
)


class TestPRReviewWatcher(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._backlog_patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(self.temp_dir) / "backlog.json")
        self._backlog_patcher.start()
        self.addCleanup(self._backlog_patcher.stop)

    @patch("core.pr_review_watcher.is_gh_cli_available", return_value=False)
    def test_gh_unavailable_returns_cleanly(self, mock_gh):
        report = asyncio.run(run_pr_review_cycle())
        self.assertFalse(report.gh_available)
        self.assertEqual(report.scanned_prs, 0)

    @patch("core.pr_review_watcher.is_gh_cli_available", return_value=True)
    @patch("core.pr_review_watcher.get_open_pull_requests")
    @patch("core.pr_review_watcher.get_pr_review_comments")
    @patch("core.pr_review_watcher.notify_external")
    def test_pr_comments_create_backlog_tickets(self, mock_notify, mock_comments, mock_prs, mock_gh):
        mock_prs.return_value = [
            {"number": 42, "title": "Feature User Auth", "headRefName": "feat/user-auth"}
        ]
        mock_comments.return_value = [
            {
                "id": 101,
                "body": "Bitte hier statt Plaintext Passwort Hashing mit bcrypt verwenden.",
                "path": "app/auth.py",
                "line": 25,
                "user": {"login": "senior_dev"},
            }
        ]

        report = asyncio.run(run_pr_review_cycle())

        self.assertTrue(report.gh_available)
        self.assertEqual(report.scanned_prs, 1)
        self.assertEqual(report.new_comments_count, 1)
        self.assertEqual(len(report.created_ticket_ids), 1)

        tickets = backlog_store.list_tickets()
        self.assertEqual(len(tickets), 1)
        ticket = tickets[0]
        self.assertEqual(ticket.id, "pr-review-42-101")
        self.assertIn("Feedback von @senior_dev", ticket.title)
        self.assertIn("bcrypt", ticket.detail)
        self.assertEqual(ticket.status, "todo")
        mock_notify.assert_called_once()

    @patch("core.pr_review_watcher.is_gh_cli_available", return_value=True)
    @patch("core.pr_review_watcher.get_open_pull_requests")
    @patch("core.pr_review_watcher.get_pr_review_comments")
    def test_bot_comments_are_ignored(self, mock_comments, mock_prs, mock_gh):
        mock_prs.return_value = [{"number": 10, "title": "PR", "headRefName": "branch"}]
        mock_comments.return_value = [
            {"id": 202, "body": "Coverage report", "user": {"login": "codecov[bot]"}}
        ]

        report = asyncio.run(run_pr_review_cycle())
        self.assertEqual(report.new_comments_count, 0)
        self.assertEqual(backlog_store.list_tickets(), [])


if __name__ == "__main__":
    unittest.main()
