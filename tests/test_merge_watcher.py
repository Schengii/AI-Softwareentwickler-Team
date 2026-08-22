"""
tests/test_merge_watcher.py – Testet core/merge_watcher.py (Merge-Erkennung fürs Backlog)

Realer struktureller Fund: Tickets landeten bei einem geöffneten PR auf "review", aber NIE
automatisch weiter auf "done" - selbst wenn der PR längst gemerged wurde. GitHubAgent ist
hier vollständig gemockt (die echte gh-CLI-Interaktion ist bereits in
tests/test_github_agent_issue_methods.py::TestGetPrStatus abgedeckt) - Gegenstand ist die
Backlog-Status-Übersetzung, nicht die gh-Kommandos selbst.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import core.backlog_store as backlog_store
from core.merge_watcher import check_merged_tickets


class TestCheckMergedTickets(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(self.temp_dir) / "backlog.json")
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

        self.fake_github = MagicMock()
        self.fake_github.gh_ready.return_value = True

    def test_merged_pr_moves_ticket_to_done(self):
        backlog_store.upsert_ticket("issue-1", "Health-Check", "issue", "review", detail="https://github.com/x/y/pull/1")
        self.fake_github.get_pr_status.return_value = ("merged", "2026-08-21T10:00:00Z")

        updated = check_merged_tickets(self.fake_github)

        self.assertEqual(updated, ["issue-1"])
        ticket = backlog_store.list_tickets()[0]
        self.assertEqual(ticket.status, "done")
        self.assertEqual(ticket.detail, "https://github.com/x/y/pull/1")  # PR-Link bleibt erhalten

    def test_closed_without_merge_moves_ticket_to_blocked(self):
        backlog_store.upsert_ticket("cli-abc", "Feature X", "cli", "review", detail="https://github.com/x/y/pull/2")
        self.fake_github.get_pr_status.return_value = ("closed", "")

        updated = check_merged_tickets(self.fake_github)

        self.assertEqual(updated, ["cli-abc"])
        ticket = backlog_store.list_tickets()[0]
        self.assertEqual(ticket.status, "blocked")
        self.assertIn("geschlossen ohne Merge", ticket.detail)

    def test_still_open_pr_leaves_ticket_unchanged(self):
        backlog_store.upsert_ticket("issue-3", "Feature Y", "issue", "review", detail="https://github.com/x/y/pull/3")
        self.fake_github.get_pr_status.return_value = ("open", "")

        updated = check_merged_tickets(self.fake_github)

        self.assertEqual(updated, [])
        self.assertEqual(backlog_store.list_tickets()[0].status, "review")

    def test_unknown_status_leaves_ticket_unchanged(self):
        backlog_store.upsert_ticket("issue-4", "Feature Z", "issue", "review", detail="https://github.com/x/y/pull/4")
        self.fake_github.get_pr_status.return_value = ("unknown", "network error")

        updated = check_merged_tickets(self.fake_github)

        self.assertEqual(updated, [])
        self.assertEqual(backlog_store.list_tickets()[0].status, "review")

    def test_ticket_without_pr_link_in_detail_is_skipped(self):
        backlog_store.upsert_ticket("cli-xyz", "Kein PR", "cli", "review", detail="")

        updated = check_merged_tickets(self.fake_github)

        self.assertEqual(updated, [])
        self.fake_github.get_pr_status.assert_not_called()

    def test_only_review_tickets_are_checked(self):
        backlog_store.upsert_ticket("t1", "Todo", "cli", "todo")
        backlog_store.upsert_ticket("t2", "Done", "cli", "done", detail="https://github.com/x/y/pull/5")
        backlog_store.upsert_ticket("t3", "Review", "cli", "review", detail="https://github.com/x/y/pull/6")
        self.fake_github.get_pr_status.return_value = ("merged", "")

        check_merged_tickets(self.fake_github)

        self.fake_github.get_pr_status.assert_called_once_with("https://github.com/x/y/pull/6")

    def test_detects_pr_url_embedded_in_descriptive_detail_text(self):
        # core/dependency_watch.py hängt die PR-URL hinter einen beschreibenden Text statt
        # detail NUR auf die URL zu setzen (siehe Docstring in core/merge_watcher.py) -
        # ein reiner startswith("http")-Check würde das übersehen.
        backlog_store.upsert_ticket(
            "depwatch-app", "Dependency-Schwachstellen: app", "dependency_watch", "review",
            detail="2 bekannte Schwachstelle(n): urllib3 ... — Automatischer Update-PR: https://github.com/x/y/pull/7",
        )
        self.fake_github.get_pr_status.return_value = ("merged", "")

        updated = check_merged_tickets(self.fake_github)

        self.assertEqual(updated, ["depwatch-app"])
        self.fake_github.get_pr_status.assert_called_once_with("https://github.com/x/y/pull/7")
        self.assertEqual(backlog_store.list_tickets()[0].status, "done")

    def test_skips_entirely_when_gh_not_ready(self):
        backlog_store.upsert_ticket("issue-1", "Health-Check", "issue", "review", detail="https://github.com/x/y/pull/1")
        self.fake_github.gh_ready.return_value = False

        updated = check_merged_tickets(self.fake_github)

        self.assertEqual(updated, [])
        self.fake_github.get_pr_status.assert_not_called()
        self.assertEqual(backlog_store.list_tickets()[0].status, "review")  # unverändert


class TestMergedTicketTriggersReleaseTagging(unittest.TestCase):
    """
    core/release_manager.py.tag_release() ist hier gemockt (bereits vollständig in
    tests/test_release_manager.py abgedeckt) - Gegenstand ist NUR, DASS check_merged_tickets()
    es bei einem echten Merge mit gesetztem project_slug tatsächlich aufruft und das Ergebnis
    ins Ticket-detail übernimmt, über DIESELBE github_agent-Instanz wie den Rest des Zyklus.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(self.temp_dir) / "backlog.json")
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

        self.fake_github = MagicMock()
        self.fake_github.gh_ready.return_value = True
        self.fake_github.get_pr_status.return_value = ("merged", "")

    @patch("core.merge_watcher.tag_release")
    def test_merged_ticket_with_project_slug_triggers_release_tagging(self, mock_tag_release):
        mock_tag_release.return_value = (True, "https://github.com/x/y/releases/tag/notizen_api-v0.1.0")
        backlog_store.upsert_ticket(
            "issue-1", "Notiz-Feature", "issue", "review",
            detail="https://github.com/x/y/pull/1", project_slug="notizen_api",
        )

        check_merged_tickets(self.fake_github)

        mock_tag_release.assert_called_once_with(
            "notizen_api", "Notiz-Feature", "https://github.com/x/y/pull/1", github_agent=self.fake_github,
        )
        ticket = backlog_store.list_tickets()[0]
        self.assertEqual(ticket.status, "done")
        self.assertIn("https://github.com/x/y/pull/1", ticket.detail)  # PR-Link bleibt erhalten
        self.assertIn("https://github.com/x/y/releases/tag/notizen_api-v0.1.0", ticket.detail)

    @patch("core.merge_watcher.tag_release")
    def test_ticket_without_project_slug_never_calls_tag_release(self, mock_tag_release):
        backlog_store.upsert_ticket("issue-1", "Health-Check", "issue", "review", detail="https://github.com/x/y/pull/1")

        check_merged_tickets(self.fake_github)

        mock_tag_release.assert_not_called()

    @patch("core.merge_watcher.tag_release")
    def test_failed_release_tagging_leaves_ticket_detail_unchanged(self, mock_tag_release):
        mock_tag_release.return_value = (False, "tag already exists")
        backlog_store.upsert_ticket(
            "issue-1", "Notiz-Feature", "issue", "review",
            detail="https://github.com/x/y/pull/1", project_slug="notizen_api",
        )

        check_merged_tickets(self.fake_github)

        ticket = backlog_store.list_tickets()[0]
        self.assertEqual(ticket.status, "done")  # trotzdem korrekt done - Tagging ist best effort
        self.assertEqual(ticket.detail, "https://github.com/x/y/pull/1")


if __name__ == "__main__":
    unittest.main()
