"""
tests/test_github_agent_push.py – Testet, dass push() den TATSÄCHLICH aktiven Branch pusht

Realer Fund: GitHubAgent.push() hatte den Ziel-Branch fest auf "main" verdrahtet (Standard-
Parameterwert) – jeder Aufruf (immer ohne explizites branch=..., siehe interface/cli.py)
pushte damit IMMER den lokalen "main"-Branch zum Remote, unabhängig davon, welcher Branch
tatsächlich ausgecheckt war. Nach der Einführung isolierter Worktree-Branches für
Selbstverbesserungsläufe (core/git_isolation.py) wäre das besonders falsch gewesen.

Nutzt ein ECHTES lokales Bare-Repo als Remote (kein Mock) – Branch-Push-Verhalten ist genau
die Art von Git-Interaktion, die ein Mock nicht glaubwürdig simulieren kann.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.github_agent import GitHubAgent


def _run(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30)


class TestGitHubAgentPushesCurrentBranch(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp()
        self.remote_dir = str(Path(self.temp_root) / "remote.git")
        self.work_dir = str(Path(self.temp_root) / "work")
        Path(self.work_dir).mkdir()

        _run(["init", "--bare", "-b", "main", self.remote_dir], cwd=self.temp_root)
        _run(["init", "-b", "main"], cwd=self.work_dir)
        _run(["config", "user.email", "test@example.com"], cwd=self.work_dir)
        _run(["config", "user.name", "Test"], cwd=self.work_dir)
        (Path(self.work_dir) / "README.md").write_text("init\n", encoding="utf-8")
        _run(["add", "-A"], cwd=self.work_dir)
        _run(["commit", "-m", "initial"], cwd=self.work_dir)
        _run(["remote", "add", "origin", self.remote_dir], cwd=self.work_dir)
        _run(["push", "-u", "origin", "main"], cwd=self.work_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _remote_branches(self) -> list[str]:
        result = _run(["branch"], cwd=self.remote_dir)
        return [line.strip(" *") for line in result.stdout.splitlines() if line.strip()]

    def test_push_uses_currently_checked_out_branch_not_hardcoded_main(self):
        _run(["checkout", "-b", "ai-team/some-feature"], cwd=self.work_dir)
        (Path(self.work_dir) / "new_file.py").write_text("x = 1\n", encoding="utf-8")
        _run(["add", "-A"], cwd=self.work_dir)
        _run(["commit", "-m", "feature work"], cwd=self.work_dir)

        with patch("agents.github_agent.BASE_DIR", self.work_dir):
            agent = GitHubAgent()
            self.assertEqual(agent.get_current_branch(), "ai-team/some-feature")

            success, output = agent.push()

        self.assertTrue(success, output)
        self.assertIn("ai-team/some-feature", self._remote_branches())

    def test_push_on_main_still_works_as_before(self):
        (Path(self.work_dir) / "another_file.py").write_text("y = 2\n", encoding="utf-8")
        _run(["add", "-A"], cwd=self.work_dir)
        _run(["commit", "-m", "more work on main"], cwd=self.work_dir)

        with patch("agents.github_agent.BASE_DIR", self.work_dir):
            agent = GitHubAgent()
            success, output = agent.push()

        self.assertTrue(success, output)


if __name__ == "__main__":
    unittest.main()
