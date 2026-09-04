"""
tests/test_github_agent_create_branch_autostash.py – Testet GitHubAgent.create_branch()'s
automatisches Stash/Pop bei dirty Arbeitsverzeichnis.

Realer Fund (mockforge-Governance-Retry, zweimal hintereinander beobachtet,
memory/backlog.json: "unresolved-governance-critical-mockforge", retries=1):
`git checkout -b <feature> <base>` scheiterte hart mit "Your local changes to the following
files would be overwritten by checkout: workspace/mockforge/.ai_team_status.json,
workspace/mockforge/PROJECT_STATE.md" - beides vom Orchestrator selbst automatisch
regenerierte Status-Dateien, keine echten Arbeitsergebnisse. create_branch() stasht ein
dirty Arbeitsverzeichnis jetzt automatisch VOR dem Checkout und spielt es danach auf dem
neuen Branch wieder ein.

Nutzt ein ECHTES lokales Git-Repo (kein Mock) - Stash/Checkout-Konflikte sind genau die Art
von Git-Interaktion, die ein Mock nicht glaubwürdig simulieren kann (siehe
tests/test_github_agent_path_exists_in_branch.py für dasselbe Prinzip).
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


class TestCreateBranchAutoStash(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp()
        self.work_dir = str(Path(self.temp_root) / "work")
        Path(self.work_dir).mkdir()
        _run(["init", "-b", "main"], cwd=self.work_dir)
        _run(["config", "user.email", "test@example.com"], cwd=self.work_dir)
        _run(["config", "user.name", "Test"], cwd=self.work_dir)
        status_file = Path(self.work_dir) / "workspace" / "mockforge" / ".ai_team_status.json"
        status_file.parent.mkdir(parents=True)
        status_file.write_text('{"run": 1}\n', encoding="utf-8")
        _run(["add", "-A"], cwd=self.work_dir)
        _run(["commit", "-m", "initial"], cwd=self.work_dir)

        self.agent = GitHubAgent()

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_dirty_status_file_no_longer_blocks_checkout(self):
        """Der reale mockforge-Fund: ein uncommittetes Update an .ai_team_status.json blockierte
        bisher jeden `git checkout -b <feature> main`."""
        status_file = Path(self.work_dir) / "workspace" / "mockforge" / ".ai_team_status.json"
        status_file.write_text('{"run": 2}\n', encoding="utf-8")

        with patch("agents.github_agent.BASE_DIR", self.work_dir):
            success, output = self.agent.create_branch("feature/mockforge-fix", base="main")

        self.assertTrue(success, output)
        current = _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=self.work_dir).stdout.strip()
        self.assertEqual(current, "feature/mockforge-fix")
        # Die Änderung muss nach dem Branch-Wechsel wieder im Arbeitsverzeichnis liegen, nicht
        # nur im Stash verschwunden sein.
        self.assertEqual(status_file.read_text(encoding="utf-8"), '{"run": 2}\n')

    def test_dirty_untracked_file_is_preserved_across_branch_switch(self):
        untracked = Path(self.work_dir) / "workspace" / "mockforge" / "PROJECT_STATE.md"
        untracked.write_text("# Status\n", encoding="utf-8")

        with patch("agents.github_agent.BASE_DIR", self.work_dir):
            success, output = self.agent.create_branch("feature/mockforge-new-file", base="main")

        self.assertTrue(success, output)
        self.assertEqual(untracked.read_text(encoding="utf-8"), "# Status\n")

    def test_clean_working_tree_does_not_attempt_to_stash(self):
        with patch("agents.github_agent.BASE_DIR", self.work_dir):
            success, output = self.agent.create_branch("feature/clean", base="main")

        self.assertTrue(success, output)
        stash_list = _run(["stash", "list"], cwd=self.work_dir).stdout
        self.assertEqual(stash_list.strip(), "")

    def test_no_base_never_stashes_even_when_dirty(self):
        status_file = Path(self.work_dir) / "workspace" / "mockforge" / ".ai_team_status.json"
        status_file.write_text('{"run": 3}\n', encoding="utf-8")

        with patch("agents.github_agent.BASE_DIR", self.work_dir):
            success, output = self.agent.create_branch("feature/from-head")

        self.assertTrue(success, output)
        stash_list = _run(["stash", "list"], cwd=self.work_dir).stdout
        self.assertEqual(stash_list.strip(), "")
        self.assertEqual(status_file.read_text(encoding="utf-8"), '{"run": 3}\n')


if __name__ == "__main__":
    unittest.main()
