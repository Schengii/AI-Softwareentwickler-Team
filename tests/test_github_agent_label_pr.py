"""
tests/test_github_agent_label_pr.py – Testet GitHubAgent.label_pr()

Realer Fund: der Verifikationsstatus eines Laufs (verification_ok/budget_aborted/
needs_human_input) steckte bisher nur im PR-Titel-Präfix und im PR-Body
(interface/cli.py._ask_for_git_push()) - in der PR-LISTE auf GitHub, wo ein Reviewer
mehrere offene PRs überfliegt, war davon nichts sichtbar. label_pr() legt die benötigten
Labels idempotent an (`gh label create --force`) und wendet sie dann per
`gh pr edit --add-label` auf den PR an - beide `gh`-Aufrufe werden hier gemockt (kein
echter GitHub-Zugriff in Tests).
"""

import unittest
from unittest.mock import MagicMock, patch

from agents.github_agent import GitHubAgent


class TestGitHubAgentLabelPr(unittest.TestCase):
    def setUp(self):
        self.agent = GitHubAgent()

    def test_rejects_unknown_label_names_without_calling_gh(self):
        with patch("agents.github_agent.subprocess.run") as mock_run:
            success, output = self.agent.label_pr("https://github.com/x/y/pull/1", ["not-a-real-label"])
        self.assertFalse(success)
        self.assertIn("not-a-real-label", output)
        mock_run.assert_not_called()

    def test_empty_label_list_is_a_no_op_success(self):
        with patch("agents.github_agent.subprocess.run") as mock_run:
            success, output = self.agent.label_pr("https://github.com/x/y/pull/1", [])
        self.assertTrue(success)
        mock_run.assert_not_called()

    def test_creates_each_label_then_applies_them_to_the_pr(self):
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("agents.github_agent.subprocess.run", return_value=mock_result) as mock_run:
            success, _ = self.agent.label_pr(
                "https://github.com/x/y/pull/1", ["verification-failed", "budget-aborted"],
            )
        self.assertTrue(success)
        # 2x `gh label create` (eines pro Label) + 1x `gh pr edit --add-label` am Ende.
        self.assertEqual(mock_run.call_count, 3)
        create_calls = [c for c in mock_run.call_args_list if c.args[0][:2] == ["gh", "label"]]
        self.assertEqual(len(create_calls), 2)
        edit_call = mock_run.call_args_list[-1]
        self.assertEqual(edit_call.args[0][:3], ["gh", "pr", "edit"])
        self.assertIn("--add-label", edit_call.args[0])
        self.assertIn("verification-failed", edit_call.args[0])
        self.assertIn("budget-aborted", edit_call.args[0])

    def test_failed_pr_edit_is_reported_but_does_not_raise(self):
        mock_result = MagicMock(returncode=1, stdout="", stderr="permission denied")
        with patch("agents.github_agent.subprocess.run", return_value=mock_result):
            success, output = self.agent.label_pr("1", ["verification-failed"])
        self.assertFalse(success)
        self.assertIn("permission denied", output)


if __name__ == "__main__":
    unittest.main()
