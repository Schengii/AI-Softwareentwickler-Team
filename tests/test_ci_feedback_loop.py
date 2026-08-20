"""
tests/test_ci_feedback_loop.py – Testet GitHubAgent.wait_for_ci_status()

Realer Fund: github_agent.push() war bisher "fire and forget" - ob die echte CI-Pipeline
(.github/workflows/ci.yml, läuft bei jedem Push) tatsächlich grün wird, hat das Team nie
erfahren. wait_for_ci_status() pollt den echten `gh run list`-Status nach einem Push.
"""

import asyncio
import json
import subprocess
import unittest
from unittest.mock import patch

from agents.github_agent import GitHubAgent


def _fake_result(returncode: int = 0, stdout: str = "[]", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestCiFeedbackLoop(unittest.TestCase):
    def setUp(self):
        self.agent = GitHubAgent()

    @patch("agents.github_agent.subprocess.run")
    def test_reports_passed_when_ci_succeeds(self, mock_run):
        mock_run.return_value = _fake_result(stdout=json.dumps([
            {"status": "completed", "conclusion": "success", "url": "https://github.com/x/y/actions/runs/1"},
        ]))
        status, detail = asyncio.run(self.agent.wait_for_ci_status("main"))
        self.assertEqual(status, "passed")
        self.assertIn("actions/runs/1", detail)

    @patch("agents.github_agent.subprocess.run")
    def test_reports_failed_when_ci_fails(self, mock_run):
        mock_run.return_value = _fake_result(stdout=json.dumps([
            {"status": "completed", "conclusion": "failure", "url": "https://github.com/x/y/actions/runs/2"},
        ]))
        status, detail = asyncio.run(self.agent.wait_for_ci_status("main"))
        self.assertEqual(status, "failed")
        self.assertIn("failure", detail)

    @patch("agents.github_agent.subprocess.run")
    def test_reports_no_run_when_gh_unavailable(self, mock_run):
        mock_run.return_value = _fake_result(returncode=1, stderr="gh: command not found")
        status, detail = asyncio.run(self.agent.wait_for_ci_status("main"))
        self.assertEqual(status, "no_run")

    @patch("agents.github_agent.subprocess.run")
    def test_reports_no_run_when_no_runs_found(self, mock_run):
        mock_run.return_value = _fake_result(stdout="[]")
        status, detail = asyncio.run(self.agent.wait_for_ci_status("main"))
        self.assertEqual(status, "no_run")

    @patch("agents.github_agent.asyncio.sleep")
    @patch("agents.github_agent.subprocess.run")
    def test_polls_while_in_progress_then_reports_passed(self, mock_run, mock_sleep):
        in_progress = _fake_result(stdout=json.dumps([{"status": "in_progress", "conclusion": None, "url": "u"}]))
        completed = _fake_result(stdout=json.dumps([{"status": "completed", "conclusion": "success", "url": "u"}]))
        mock_run.side_effect = [in_progress, in_progress, completed]

        status, _ = asyncio.run(self.agent.wait_for_ci_status("main", timeout_seconds=90, poll_interval=1))

        self.assertEqual(status, "passed")
        self.assertEqual(mock_run.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("agents.github_agent.asyncio.sleep")
    @patch("agents.github_agent.subprocess.run")
    def test_times_out_if_never_completes(self, mock_run, mock_sleep):
        mock_run.return_value = _fake_result(stdout=json.dumps([{"status": "in_progress", "conclusion": None, "url": "u"}]))
        status, detail = asyncio.run(self.agent.wait_for_ci_status("main", timeout_seconds=2, poll_interval=1))
        self.assertEqual(status, "timeout")


if __name__ == "__main__":
    unittest.main()
