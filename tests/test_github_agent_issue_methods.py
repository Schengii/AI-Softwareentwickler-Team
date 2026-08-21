"""
tests/test_github_agent_issue_methods.py – Testet die neuen GitHubAgent-Primitiven für
autonome, getriggerte Läufe (core/issue_watcher.py)

Die `gh`-CLI ist in der CI-Testumgebung nicht installiert – alle Aufrufe werden über
`agents.github_agent.subprocess.run` gemockt (dasselbe Prinzip wie tests/test_ci_feedback_loop.py
für wait_for_ci_status()).
"""

import subprocess
import unittest
from unittest.mock import MagicMock, patch

from agents.github_agent import GitHubAgent


class TestListActionableIssues(unittest.TestCase):
    def setUp(self):
        self.agent = GitHubAgent()

    @patch("agents.github_agent.subprocess.run")
    def test_excludes_issues_with_any_excluded_label(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="""
        [
          {"number": 1, "title": "A", "body": "", "labels": [{"name": "ai-team"}]},
          {"number": 2, "title": "B", "body": "", "labels": [{"name": "ai-team"}, {"name": "ai-team-in-progress"}]},
          {"number": 3, "title": "C", "body": "", "labels": [{"name": "ai-team"}, {"name": "ai-team-done"}]}
        ]
        """, stderr="")

        issues = self.agent.list_actionable_issues(
            label="ai-team", exclude_labels=["ai-team-in-progress", "ai-team-done", "ai-team-blocked"],
        )

        self.assertEqual([i["number"] for i in issues], [1])

    @patch("agents.github_agent.subprocess.run")
    def test_returns_empty_list_when_gh_command_fails(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not a git repository")
        self.assertEqual(self.agent.list_actionable_issues("ai-team", []), [])

    @patch("agents.github_agent.subprocess.run")
    def test_returns_empty_list_on_malformed_json(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="not json", stderr="")
        self.assertEqual(self.agent.list_actionable_issues("ai-team", []), [])

    @patch("agents.github_agent.subprocess.run", side_effect=subprocess.TimeoutExpired("gh", 20))
    def test_returns_empty_list_on_timeout_without_crashing(self, _mock_run):
        self.assertEqual(self.agent.list_actionable_issues("ai-team", []), [])


class TestIssueLabelAndCommentOperations(unittest.TestCase):
    def setUp(self):
        self.agent = GitHubAgent()

    @patch("agents.github_agent.subprocess.run")
    def test_add_issue_label_builds_correct_gh_command(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        success, _ = self.agent.add_issue_label(42, "ai-team-in-progress")
        self.assertTrue(success)
        self.assertEqual(
            mock_run.call_args[0][0],
            ["gh", "issue", "edit", "42", "--add-label", "ai-team-in-progress"],
        )

    @patch("agents.github_agent.subprocess.run")
    def test_remove_issue_label_builds_correct_gh_command(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        success, _ = self.agent.remove_issue_label(42, "ai-team-in-progress")
        self.assertTrue(success)
        self.assertEqual(
            mock_run.call_args[0][0],
            ["gh", "issue", "edit", "42", "--remove-label", "ai-team-in-progress"],
        )

    @patch("agents.github_agent.subprocess.run")
    def test_comment_on_issue_reports_failure_without_crashing(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="issue not found")
        success, output = self.agent.comment_on_issue(999, "hallo")
        self.assertFalse(success)
        self.assertIn("issue not found", output)

    @patch("agents.github_agent.subprocess.run", side_effect=OSError("gh not found"))
    def test_ensure_label_exists_swallows_every_error(self, _mock_run):
        # Darf NIE werfen - reine Best-effort-Vorbereitung (siehe Docstring in github_agent.py).
        self.agent.ensure_label_exists("ai-team-done")


class TestGetPrStatus(unittest.TestCase):
    def setUp(self):
        self.agent = GitHubAgent()

    @patch("agents.github_agent.subprocess.run")
    def test_returns_merged_for_a_merged_pr(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout='{"state": "MERGED", "mergedAt": "2026-08-21T10:00:00Z"}', stderr="",
        )
        state, detail = self.agent.get_pr_status("https://github.com/x/y/pull/1")
        self.assertEqual(state, "merged")
        self.assertEqual(detail, "2026-08-21T10:00:00Z")

    @patch("agents.github_agent.subprocess.run")
    def test_returns_closed_for_a_closed_unmerged_pr(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout='{"state": "CLOSED", "mergedAt": null}', stderr="")
        state, _detail = self.agent.get_pr_status("https://github.com/x/y/pull/2")
        self.assertEqual(state, "closed")

    @patch("agents.github_agent.subprocess.run")
    def test_returns_open_for_a_still_open_pr(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout='{"state": "OPEN", "mergedAt": null}', stderr="")
        state, _detail = self.agent.get_pr_status("https://github.com/x/y/pull/3")
        self.assertEqual(state, "open")

    @patch("agents.github_agent.subprocess.run")
    def test_returns_unknown_when_pr_not_found(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="no pull requests found")
        state, detail = self.agent.get_pr_status("https://github.com/x/y/pull/999")
        self.assertEqual(state, "unknown")
        self.assertIn("no pull requests found", detail)

    @patch("agents.github_agent.subprocess.run")
    def test_returns_unknown_on_malformed_json(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="not json", stderr="")
        state, _detail = self.agent.get_pr_status("https://github.com/x/y/pull/1")
        self.assertEqual(state, "unknown")

    @patch("agents.github_agent.subprocess.run", side_effect=subprocess.TimeoutExpired("gh", 20))
    def test_returns_unknown_on_timeout_without_crashing(self, _mock_run):
        state, _detail = self.agent.get_pr_status("https://github.com/x/y/pull/1")
        self.assertEqual(state, "unknown")


if __name__ == "__main__":
    unittest.main()
