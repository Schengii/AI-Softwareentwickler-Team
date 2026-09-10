"""
tests/test_git_runtime.py – Nicht-interaktive, zeitbegrenzte Git-Aufrufe

Realer Fund (Framework-Analyse 2026-09-10): git commit/push/stash/checkout/revert liefen ohne
Timeout und ohne GIT_TERMINAL_PROMPT=0 - eine Zugangsdaten-Abfrage blockierte unbeaufsichtigte
Läufe (Issue-Watcher, Backlog-Worker) unbegrenzt.
"""

import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agents.github_agent import GitHubAgent
from core import framework_release, obsidian_sync
from core.git_runtime import (
    GIT_NETWORK_TIMEOUT_SECONDS,
    GIT_NOT_EXECUTABLE_EXIT_CODE,
    GIT_TIMEOUT_EXIT_CODE,
    non_interactive_git_env,
    run_git,
)


class TestNonInteractiveGitEnv(unittest.TestCase):
    def test_disables_all_interactive_prompts_and_keeps_environment(self):
        env = non_interactive_git_env({"PATH": "C:/git/bin", "GIT_TERMINAL_PROMPT": "1"})
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(env["GCM_INTERACTIVE"], "never")
        self.assertEqual(env["PATH"], "C:/git/bin")


class TestRunGit(unittest.TestCase):
    @patch("core.git_runtime.subprocess.run")
    def test_passes_timeout_and_non_interactive_env(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(["git", "status"], 0, "ok", "")
        run_git(["status"], cwd=".", timeout=7)
        kwargs = mock_run.call_args.kwargs
        self.assertEqual(mock_run.call_args.args[0], ["git", "status"])
        self.assertEqual(kwargs["timeout"], 7)
        self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")

    @patch("core.git_runtime.subprocess.run", side_effect=subprocess.TimeoutExpired(["git", "push"], 300))
    def test_timeout_becomes_failed_result_instead_of_hanging_or_raising(self, _mock_run):
        result = run_git(["push", "origin", "main"], cwd=".", timeout=300)
        self.assertEqual(result.returncode, GIT_TIMEOUT_EXIT_CODE)
        self.assertIn("Timeout", result.stderr)

    @patch("core.git_runtime.subprocess.run", side_effect=FileNotFoundError("git"))
    def test_missing_git_becomes_failed_result(self, _mock_run):
        result = run_git(["status"], cwd=".")
        self.assertEqual(result.returncode, GIT_NOT_EXECUTABLE_EXIT_CODE)


class TestCallersUseGitRuntime(unittest.TestCase):
    @patch("core.git_runtime.subprocess.run", side_effect=subprocess.TimeoutExpired(["git", "push"], 300))
    def test_github_agent_push_fails_cleanly_on_timeout(self, mock_run):
        success, output = GitHubAgent().push(branch="feature/x")
        self.assertFalse(success)
        self.assertIn("Timeout", output)
        self.assertEqual(mock_run.call_args.kwargs["timeout"], GIT_NETWORK_TIMEOUT_SECONDS)
        self.assertEqual(mock_run.call_args.kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")

    @patch("core.git_runtime.subprocess.run")
    def test_github_agent_checkout_is_non_interactive(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(["git"], 0, "", "")
        GitHubAgent().checkout("main")
        self.assertEqual(mock_run.call_args.args[0], ["git", "checkout", "main"])
        self.assertIn("timeout", mock_run.call_args.kwargs)
        self.assertEqual(mock_run.call_args.kwargs["env"]["GCM_INTERACTIVE"], "never")

    @patch("core.git_runtime.subprocess.run", side_effect=subprocess.TimeoutExpired(["git", "describe"], 300))
    def test_framework_release_git_timeout_is_a_failure_not_an_exception(self, _mock_run):
        success, output = framework_release._run_git("describe", "--tags", "--abbrev=0")
        self.assertFalse(success)
        self.assertIn("Timeout", output)

    def test_obsidian_git_info_uses_timeout_and_survives_hang(self):
        with patch("core.obsidian_sync.subprocess.check_output", return_value="main\n") as mock_out:
            info = obsidian_sync._get_current_git_info(SimpleNamespace())
        self.assertEqual(info["branch"], "main")
        self.assertEqual(mock_out.call_args.kwargs["timeout"], 10)
        self.assertEqual(mock_out.call_args.kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")

        with patch("core.obsidian_sync.subprocess.check_output", side_effect=subprocess.TimeoutExpired("git", 10)):
            self.assertEqual(obsidian_sync._get_current_git_info(SimpleNamespace())["branch"], "unknown")


if __name__ == "__main__":
    unittest.main()
