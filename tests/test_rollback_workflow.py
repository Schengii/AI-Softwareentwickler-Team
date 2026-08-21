"""
tests/test_rollback_workflow.py – Testet den echten Rollback-Workflow (`/rollback <PR-Nummer>`)

Realer Fund bei einer Bestandsaufnahme des eigenen Teams: bricht ein gemergter PR `main`
(z.B. rotes CI erst NACH dem Merge bemerkt), gab es keinerlei Mechanismus, das rückgängig
zu machen - nur der manuelle Weg direkt über GitHub. agents/github_agent.py.get_merged_pr_info()/
revert_commit() und interface/cli.py._rollback_merged_pr() bauen einen echten Revert-Workflow:
neuer Branch, echter `git revert`, echter Push, echter Revert-Pull-Request - KEIN
Direct-Commit auf den Hauptbranch, derselbe PR-Workflow wie jede andere Änderung.
"""

import asyncio
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.github_agent import GitHubAgent
from interface.cli import CLIInterface


def _run(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")


class TestGetMergedPrInfo(unittest.TestCase):
    def setUp(self):
        self.work_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def test_returns_merge_commit_and_title_for_a_merged_pr(self):
        with patch("agents.github_agent.BASE_DIR", self.work_dir), \
             patch("agents.github_agent.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"state": "MERGED", "mergeCommit": {"oid": "abc1234"}, "title": "feat: x"}',
                stderr="",
            )
            agent = GitHubAgent()
            found, sha, title = agent.get_merged_pr_info(7)

        self.assertTrue(found)
        self.assertEqual(sha, "abc1234")
        self.assertEqual(title, "feat: x")

    def test_open_pr_is_rejected_with_clear_reason(self):
        with patch("agents.github_agent.BASE_DIR", self.work_dir), \
             patch("agents.github_agent.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='{"state": "OPEN", "mergeCommit": null, "title": "x"}', stderr="",
            )
            agent = GitHubAgent()
            found, reason, _title = agent.get_merged_pr_info(7)

        self.assertFalse(found)
        self.assertIn("nicht gemerged", reason)

    def test_pr_not_found_is_rejected_without_crashing(self):
        with patch("agents.github_agent.BASE_DIR", self.work_dir), \
             patch("agents.github_agent.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="no pull requests found")
            agent = GitHubAgent()
            found, reason, _title = agent.get_merged_pr_info(999)

        self.assertFalse(found)
        self.assertIn("no pull requests found", reason)


class TestRevertCommit(unittest.TestCase):
    """Echter lokaler Git-Revert gegen ein reales Repo (wie test_pr_workflow.py.
    TestGitHubAgentBranchOperations) - kein gemockter subprocess, da git revert die
    tatsächliche Verzeichnisstruktur/Historie braucht, um sinnvoll geprüft zu werden."""

    def setUp(self):
        self.work_dir = tempfile.mkdtemp()
        _run(["init", "-b", "main"], cwd=self.work_dir)
        _run(["config", "user.email", "test@example.com"], cwd=self.work_dir)
        _run(["config", "user.name", "Test"], cwd=self.work_dir)
        (Path(self.work_dir) / "app.py").write_text("VERSION = 1\n", encoding="utf-8")
        _run(["add", "-A"], cwd=self.work_dir)
        _run(["commit", "-m", "initial"], cwd=self.work_dir)

    def tearDown(self):
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def test_revert_undoes_the_targeted_commit(self):
        (Path(self.work_dir) / "app.py").write_text("VERSION = 2\n", encoding="utf-8")
        _run(["add", "-A"], cwd=self.work_dir)
        _run(["commit", "-m", "bump version"], cwd=self.work_dir)
        bad_sha = _run(["rev-parse", "HEAD"], cwd=self.work_dir).stdout.strip()

        with patch("agents.github_agent.BASE_DIR", self.work_dir):
            agent = GitHubAgent()
            success, output = agent.revert_commit(bad_sha)

        self.assertTrue(success, output)
        self.assertEqual((Path(self.work_dir) / "app.py").read_text(encoding="utf-8"), "VERSION = 1\n")

    def test_revert_conflict_fails_cleanly_without_crashing(self):
        (Path(self.work_dir) / "app.py").write_text("VERSION = 2\n", encoding="utf-8")
        _run(["add", "-A"], cwd=self.work_dir)
        _run(["commit", "-m", "bump version"], cwd=self.work_dir)
        bad_sha = _run(["rev-parse", "HEAD"], cwd=self.work_dir).stdout.strip()
        # Weitere, überlappende Änderung DANACH - macht den Revert konfliktbehaftet.
        (Path(self.work_dir) / "app.py").write_text("VERSION = 3\n", encoding="utf-8")
        _run(["add", "-A"], cwd=self.work_dir)
        _run(["commit", "-m", "bump again"], cwd=self.work_dir)

        with patch("agents.github_agent.BASE_DIR", self.work_dir):
            agent = GitHubAgent()
            success, output = agent.revert_commit(bad_sha)

        self.assertFalse(success)
        self.assertTrue(output)  # echte Konfliktmeldung, keine leere Fehlermeldung


class TestRollbackCliCommand(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()
        self.fake_github = MagicMock()
        self.fake_github.gh_ready.return_value = True
        self.fake_github.get_current_branch.return_value = "revert-source-branch"
        self.cli._orchestrator._agents["github"] = self.fake_github
        self._print_patcher = patch("interface.cli.console.print")
        self._print_patcher.start()
        self.addCleanup(self._print_patcher.stop)

    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_full_rollback_creates_branch_reverts_pushes_and_opens_pr(self, _mock_confirm):
        self.fake_github.get_merged_pr_info.return_value = (True, "abc1234", "feat: kaputte Aenderung")
        self.fake_github.create_branch.return_value = (True, "ok")
        self.fake_github.revert_commit.return_value = (True, "ok")
        self.fake_github.push.return_value = (True, "ok")
        self.fake_github.create_pull_request.return_value = (True, "https://github.com/x/y/pull/99")

        asyncio.run(self.cli._rollback_merged_pr("42"))

        self.fake_github.create_branch.assert_called_once()
        branch_arg = self.fake_github.create_branch.call_args[0][0]
        self.assertTrue(branch_arg.startswith("revert-42-"))
        self.fake_github.revert_commit.assert_called_once_with("abc1234")
        self.fake_github.push.assert_called_once_with(branch=branch_arg)
        self.fake_github.create_pull_request.assert_called_once()
        pr_kwargs = self.fake_github.create_pull_request.call_args.kwargs
        self.assertIn("42", pr_kwargs["title"])

    @patch("interface.cli.Confirm.ask", return_value=False)
    def test_declining_confirmation_makes_no_changes(self, _mock_confirm):
        self.fake_github.get_merged_pr_info.return_value = (True, "abc1234", "feat: x")

        asyncio.run(self.cli._rollback_merged_pr("42"))

        self.fake_github.create_branch.assert_not_called()
        self.fake_github.revert_commit.assert_not_called()

    async def _run_without_confirm_prompt(self):
        await self.cli._rollback_merged_pr("42")

    def test_pr_not_found_or_not_merged_never_reaches_confirmation(self):
        self.fake_github.get_merged_pr_info.return_value = (False, "PR #42 ist nicht gemerged (Status: OPEN).", "")

        with patch("interface.cli.Confirm.ask") as mock_confirm:
            asyncio.run(self._run_without_confirm_prompt())
            mock_confirm.assert_not_called()

        self.fake_github.create_branch.assert_not_called()

    def test_missing_gh_cli_blocks_rollback_before_any_lookup(self):
        self.fake_github.gh_ready.return_value = False

        asyncio.run(self.cli._rollback_merged_pr("42"))

        self.fake_github.get_merged_pr_info.assert_not_called()

    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_revert_conflict_checks_out_original_branch_and_stops(self, _mock_confirm):
        self.fake_github.get_merged_pr_info.return_value = (True, "abc1234", "feat: x")
        self.fake_github.create_branch.return_value = (True, "ok")
        self.fake_github.revert_commit.return_value = (False, "CONFLICT (content): Merge conflict in app.py")

        asyncio.run(self.cli._rollback_merged_pr("42"))

        self.fake_github.checkout.assert_called_once_with("revert-source-branch")
        self.fake_github.push.assert_not_called()
        self.fake_github.create_pull_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
