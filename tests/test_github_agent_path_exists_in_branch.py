"""
tests/test_github_agent_path_exists_in_branch.py – Testet GitHubAgent.path_exists_in_branch()

Realer Fund (mockforge-Governance-Retry, Team-Bestandsaufnahme 2026-09-03): core/backlog_
worker.py und core/issue_watcher.py wählten als Basis für einen neuen Feature-Branch bisher
blind den ersten konfigurierten Hauptbranch (GIT_PROTECTED_BRANCHES[0], typischerweise
"main"), sobald der aktuell ausgecheckte Branch selbst keiner davon war. Existiert das
bearbeitete Projekt aber NUR auf dem aktuellen, langlebigen Feature-Branch (noch nicht nach
main gemerged), scheiterte `git checkout -b <feature> main` real mit "Your local changes ...
would be overwritten by checkout" - main kennt die soeben geänderten Projektdateien gar
nicht. path_exists_in_branch() erlaubt beiden Aufrufern, das VORHER zu erkennen, ohne
auszuchecken.

Nutzt ein ECHTES lokales Git-Repo (kein Mock) - Branch-Inhalt ist genau die Art von
Git-Interaktion, die ein Mock nicht glaubwürdig simulieren kann.
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


class TestPathExistsInBranch(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp()
        self.work_dir = str(Path(self.temp_root) / "work")
        Path(self.work_dir).mkdir()
        _run(["init", "-b", "main"], cwd=self.work_dir)
        _run(["config", "user.email", "test@example.com"], cwd=self.work_dir)
        _run(["config", "user.name", "Test"], cwd=self.work_dir)
        (Path(self.work_dir) / "README.md").write_text("init\n", encoding="utf-8")
        _run(["add", "-A"], cwd=self.work_dir)
        _run(["commit", "-m", "initial"], cwd=self.work_dir)

        self.agent = GitHubAgent()

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_path_missing_from_target_branch_returns_false(self):
        """Der reale Fund: ein Projektordner existiert nur auf dem Feature-Branch, main kennt
        ihn nicht - genau der Fall, der den Checkout-Konflikt real auslöste."""
        _run(["checkout", "-b", "feature/mockforge"], cwd=self.work_dir)
        (Path(self.work_dir) / "workspace").mkdir()
        (Path(self.work_dir) / "workspace" / "mockforge").mkdir()
        (Path(self.work_dir) / "workspace" / "mockforge" / "app.py").write_text("x = 1\n", encoding="utf-8")
        _run(["add", "-A"], cwd=self.work_dir)
        _run(["commit", "-m", "add mockforge"], cwd=self.work_dir)

        with patch("agents.github_agent.BASE_DIR", self.work_dir):
            self.assertFalse(self.agent.path_exists_in_branch("main", "workspace/mockforge"))
            self.assertTrue(self.agent.path_exists_in_branch("feature/mockforge", "workspace/mockforge"))

    def test_path_present_on_both_branches_returns_true(self):
        (Path(self.work_dir) / "workspace").mkdir()
        (Path(self.work_dir) / "workspace" / "existing_project").mkdir()
        (Path(self.work_dir) / "workspace" / "existing_project" / "app.py").write_text("x = 1\n", encoding="utf-8")
        _run(["add", "-A"], cwd=self.work_dir)
        _run(["commit", "-m", "add existing_project on main"], cwd=self.work_dir)
        _run(["checkout", "-b", "feature/other"], cwd=self.work_dir)

        with patch("agents.github_agent.BASE_DIR", self.work_dir):
            self.assertTrue(self.agent.path_exists_in_branch("main", "workspace/existing_project"))

    def test_nonexistent_path_on_existing_branch_returns_false(self):
        with patch("agents.github_agent.BASE_DIR", self.work_dir):
            self.assertFalse(self.agent.path_exists_in_branch("main", "workspace/never_created"))


if __name__ == "__main__":
    unittest.main()
