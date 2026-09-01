"""
tests/test_worktree_pruning.py – Testet prune_stale_worktrees() aus core/git_isolation.py

Verwaiste, vom KI-Team angelegte Git-Worktrees (core/git_isolation.py: create_isolated_
worktree) sammelten sich unbemerkt an, weil es bisher keinen automatischen Cleanup gab.
prune_stale_worktrees() räumt gemergte oder lange inaktive Worktrees auf, rührt aber
NIEMALS den aktuell aktiven Worktree oder einen mit ungemergten Änderungen an.

Nutzt ECHTE temporäre Git-Repos/Worktrees (kein Mock) - genau wie test_git_isolation.py.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path

from core.git_isolation import (
    create_isolated_worktree,
    prune_stale_worktrees,
    remove_worktree,
)


def _run(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30)


class TestPruneStaleWorktrees(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.temp_root = self._tmp.name
        self.repo_dir = str(Path(self.temp_root) / "repo")
        Path(self.repo_dir).mkdir()
        _run(["init", "-b", "main"], cwd=self.repo_dir)
        _run(["config", "user.email", "test@example.com"], cwd=self.repo_dir)
        _run(["config", "user.name", "Test"], cwd=self.repo_dir)
        (Path(self.repo_dir) / "main.py").write_text("print('original')\n", encoding="utf-8")
        _run(["add", "-A"], cwd=self.repo_dir)
        _run(["commit", "-m", "initial"], cwd=self.repo_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def _set_last_commit_days_ago(self, cwd: str, days: int) -> None:
        """Setzt Committer- UND Autor-Datum des letzten Commits künstlich in die Vergangenheit
        (als exakter Unix-Timestamp, da relative Datumsangaben wie "N days ago" von
        `git commit --date` auf manchen Git-Builds nicht zuverlässig geparst werden)."""
        import os
        import time

        epoch = int(time.time()) - days * 86400
        git_date = f"@{epoch} +0000"
        subprocess.run(
            ["git", "commit", "--amend", "--no-edit", f"--date={git_date}"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "GIT_COMMITTER_DATE": git_date},
        )

    def test_merged_worktree_is_removed(self):
        """(a) Ein gemergter, alter Worktree wird tatsächlich entfernt."""
        worktree = create_isolated_worktree(self.repo_dir, "Alte erledigte Aufgabe")
        (Path(worktree.path) / "feature.py").write_text("x = 1\n", encoding="utf-8")
        _run(["add", "-A"], cwd=worktree.path)
        _run(["commit", "-m", "feature"], cwd=worktree.path)

        # In main mergen, damit der Branch als "erledigt" gilt.
        _run(["merge", "--no-ff", worktree.branch, "-m", "merge feature"], cwd=self.repo_dir)

        actions = prune_stale_worktrees(self.repo_dir)

        self.assertFalse(Path(worktree.path).exists())
        removed = [a for a in actions if a.action == "removed" and a.branch == worktree.branch]
        self.assertEqual(len(removed), 1)
        self.assertIn("gemergt", removed[0].reason)

    def test_unmerged_recent_worktree_is_untouched(self):
        """(b) Ein NICHT gemergter, frischer Worktree bleibt unangetastet."""
        worktree = create_isolated_worktree(self.repo_dir, "Laufende Aufgabe")
        (Path(worktree.path) / "wip.py").write_text("y = 2\n", encoding="utf-8")
        _run(["add", "-A"], cwd=worktree.path)
        _run(["commit", "-m", "wip"], cwd=worktree.path)

        actions = prune_stale_worktrees(self.repo_dir)

        self.assertTrue(Path(worktree.path).exists())
        skipped = [a for a in actions if a.branch == worktree.branch]
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0].action, "skipped")

        remove_worktree(worktree, force=True)

    def test_unmerged_old_but_dirty_worktree_is_never_force_removed(self):
        """Alt + nicht gemergt + unkommittierte Änderungen -> niemals angefasst."""
        worktree = create_isolated_worktree(self.repo_dir, "Alte laufende Aufgabe")
        (Path(worktree.path) / "wip.py").write_text("y = 2\n", encoding="utf-8")
        _run(["add", "-A"], cwd=worktree.path)
        _run(["commit", "-m", "wip"], cwd=worktree.path)
        self._set_last_commit_days_ago(worktree.path, 30)
        # Zusätzliche unkommittierte Änderung.
        (Path(worktree.path) / "dirty.py").write_text("z = 3\n", encoding="utf-8")

        actions = prune_stale_worktrees(self.repo_dir, stale_days=7)

        self.assertTrue(Path(worktree.path).exists())
        matched = [a for a in actions if a.branch == worktree.branch]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].action, "skipped")
        self.assertIn("unkommittierte", matched[0].reason)

        remove_worktree(worktree, force=True)

    def test_active_worktree_is_never_touched(self):
        """(c) Der aktuell aktive Worktree (base_dir selbst) wird nie angefasst, egal was."""
        actions = prune_stale_worktrees(self.repo_dir)

        # base_dir selbst taucht in git worktree list auf (Branch "main"), darf aber
        # niemals in den Aktionen auftauchen (weder removed noch skipped) - kein
        # ai-team/-Branch UND identisch mit dem aktiven Pfad.
        for action in actions:
            self.assertNotEqual(str(Path(action.path).resolve()), str(Path(self.repo_dir).resolve()))

        self.assertTrue(Path(self.repo_dir).exists())
        self.assertTrue((Path(self.repo_dir) / "main.py").exists())

    def test_non_ai_team_worktree_is_ignored(self):
        """Ein manuell (nicht vom KI-Team) angelegter Worktree mit fremdem Branch-Namen
        bleibt von prune_stale_worktrees vollständig unberührt."""
        manual_dir = str(Path(self.temp_root) / "manual-worktree")
        _run(["worktree", "add", "-b", "manual/some-branch", manual_dir], cwd=self.repo_dir)

        actions = prune_stale_worktrees(self.repo_dir)

        matched = [a for a in actions if "manual" in a.branch]
        self.assertEqual(matched, [])
        self.assertTrue(Path(manual_dir).exists())

    def test_stale_unmerged_clean_worktree_is_removed_but_branch_kept(self):
        """Alt + nicht gemergt + sauber (keine unkommittierten Änderungen) -> Worktree wird
        entfernt (nichts geht verloren, der Branch existiert weiter), Branch bleibt bestehen."""
        worktree = create_isolated_worktree(self.repo_dir, "Alte saubere Aufgabe")
        (Path(worktree.path) / "wip.py").write_text("y = 2\n", encoding="utf-8")
        _run(["add", "-A"], cwd=worktree.path)
        _run(["commit", "-m", "wip"], cwd=worktree.path)
        self._set_last_commit_days_ago(worktree.path, 30)

        actions = prune_stale_worktrees(self.repo_dir, stale_days=7)

        self.assertFalse(Path(worktree.path).exists())
        matched = [a for a in actions if a.branch == worktree.branch]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].action, "removed")

        branch_list = _run(["branch", "--list", worktree.branch], cwd=self.repo_dir)
        self.assertIn(worktree.branch, branch_list.stdout)


if __name__ == "__main__":
    unittest.main()
