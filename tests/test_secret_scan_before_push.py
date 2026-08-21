"""
tests/test_secret_scan_before_push.py – Testet den Secret-Scan-Gate vor Commit & Push

Realer Fund: agents/github_agent.py.commit()/push() prüften den zu committenden Inhalt nie
– ein Agent, der versehentlich einen echten API-Key/ein Passwort in eine generierte Datei
schreibt, hätte diesen Secret unbemerkt auf GitHub gepusht. Zwei Ebenen:

1. GitHubAgent.scan_for_secrets() – echtes lokales Git-Repo (kein Mock), da Staging/Diff-
   Verhalten genau die Art von Git-Interaktion ist, die ein Mock nicht glaubwürdig
   simulieren kann (siehe test_github_agent_push.py für dasselbe Prinzip).
2. interface/cli.py._ask_for_git_push() – zeigt bei einem Fund eine deutliche Warnung und
   eine andere Bestätigungsfrage, blockiert aber nichts hart (der Mensch kann bewusst
   trotzdem committen/pushen, analog zur bestehenden Verifikations-Warnung).
"""

import asyncio
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import core.backlog_store as backlog_store
from agents.github_agent import GitHubAgent
from interface.cli import CLIInterface


def _run(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30)


class TestGitHubAgentScanForSecrets(unittest.TestCase):
    def setUp(self):
        self.work_dir = tempfile.mkdtemp()
        _run(["init", "-b", "main"], cwd=self.work_dir)
        _run(["config", "user.email", "test@example.com"], cwd=self.work_dir)
        _run(["config", "user.name", "Test"], cwd=self.work_dir)
        (Path(self.work_dir) / "README.md").write_text("init\n", encoding="utf-8")
        _run(["add", "-A"], cwd=self.work_dir)
        _run(["commit", "-m", "initial"], cwd=self.work_dir)

    def tearDown(self):
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def test_detects_newly_added_secret_in_working_tree(self):
        (Path(self.work_dir) / "config.py").write_text(
            'AWS_KEY = "AKIAABCDEFGHIJKLMNOP"\n', encoding="utf-8",
        )
        with patch("agents.github_agent.BASE_DIR", self.work_dir):
            agent = GitHubAgent()
            findings = agent.scan_for_secrets()

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule, "AWS Access Key")
        self.assertIn("config.py", findings[0].file_path)

    def test_clean_changes_produce_no_findings(self):
        (Path(self.work_dir) / "main.py").write_text("print('hello')\n", encoding="utf-8")
        with patch("agents.github_agent.BASE_DIR", self.work_dir):
            agent = GitHubAgent()
            findings = agent.scan_for_secrets()

        self.assertEqual(findings, [])


class TestCLIWarnsOnSecretFund(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()
        # _ask_for_git_push() schreibt jetzt auch ins Backlog (core/backlog_store.py) - gegen
        # ein temporäres Verzeichnis statt der echten memory/backlog.json.
        self._backlog_dir = tempfile.mkdtemp()
        self._backlog_patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(self._backlog_dir) / "backlog.json")
        self._backlog_patcher.start()
        self.addCleanup(self._backlog_patcher.stop)
        self.fake_github = MagicMock()
        self.fake_github.get_status.return_value = "M config.py"
        self.fake_github.get_diff.return_value = "config.py | 1 +"
        self.fake_github.commit.return_value = (True, "commit ok")
        self.fake_github.push.return_value = (True, "push ok")
        self.fake_github.get_current_branch.return_value = "main"
        self.fake_github.wait_for_ci_status = AsyncMock(return_value=("no_run", "kein CI im Test"))
        # PR-Workflow ist hier nicht Testgegenstand (siehe tests/test_pr_workflow.py) - hält
        # den bisherigen Direct-Push-Pfad aktiv.
        self.fake_github.gh_ready.return_value = False
        self.cli._orchestrator._agents["github"] = self.fake_github
        self.cli._orchestrator.last_verification_ok = True
        self._print_patcher = patch("interface.cli.console.print")
        self._print_patcher.start()
        self.addCleanup(self._print_patcher.stop)

    def _fake_finding(self):
        from core.secret_scanner import SecretFinding
        return SecretFinding(
            file_path="config.py", line_number=3, rule="AWS Access Key",
            snippet='AWS_KEY = "***REDACTED***"',
        )

    @patch("interface.cli.Confirm.ask", return_value=False)
    def test_shows_secret_warning_prompt_and_defaults_to_declining(self, mock_confirm):
        self.fake_github.scan_for_secrets.return_value = [self._fake_finding()]
        asyncio.run(self.cli._ask_for_git_push("Testaufgabe"))
        prompt_text = mock_confirm.call_args[0][0]
        self.assertIn("Secret-Funde", prompt_text)
        self.fake_github.commit.assert_not_called()
        self.fake_github.push.assert_not_called()

    @patch("interface.cli.Confirm.ask", return_value=False)
    def test_no_secret_warning_when_scan_is_clean(self, mock_confirm):
        self.fake_github.scan_for_secrets.return_value = []
        asyncio.run(self.cli._ask_for_git_push("Testaufgabe"))
        prompt_text = mock_confirm.call_args[0][0]
        self.assertNotIn("Secret-Funde", prompt_text)

    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_can_still_push_after_explicit_confirmation_despite_secret_fund(self, mock_confirm):
        """Die Warnung blockiert nichts hart - der Mensch kann bewusst trotzdem pushen."""
        self.fake_github.scan_for_secrets.return_value = [self._fake_finding()]
        asyncio.run(self.cli._ask_for_git_push("Testaufgabe"))
        self.fake_github.commit.assert_called_once()
        self.fake_github.push.assert_called_once()


if __name__ == "__main__":
    unittest.main()
