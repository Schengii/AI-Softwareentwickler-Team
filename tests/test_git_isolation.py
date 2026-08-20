"""
tests/test_git_isolation.py – Testet die Git-Worktree-Isolation für Selbstverbesserungsläufe

Realer Fund: Der backend-Agent überschrieb main.py UND interface/cli.py im Framework-Root
direkt mit kaputtem Inhalt – für die Dauer des Laufs lag das echte Arbeitsverzeichnis des
Nutzers offen. core/git_isolation.py legt für Selbstverbesserungsläufe jetzt einen
komplett separaten Git-Worktree an, statt im echten Arbeitsverzeichnis zu schreiben.

Nutzt einen ECHTEN temporären Git-Repo (kein Mock) - Worktree-Erstellung ist genau die
Art von Dateisystem-/Git-Interaktion, die ein Mock nicht glaubwürdig simulieren kann.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from core.git_isolation import (
    GitIsolationError,
    create_isolated_worktree,
    find_git_root,
    has_uncommitted_changes,
    is_git_repo,
    remove_worktree,
)


def _run(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30)


class TestGitIsolation(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp()
        self.repo_dir = str(Path(self.temp_root) / "repo")
        Path(self.repo_dir).mkdir()
        _run(["init", "-b", "main"], cwd=self.repo_dir)
        _run(["config", "user.email", "test@example.com"], cwd=self.repo_dir)
        _run(["config", "user.name", "Test"], cwd=self.repo_dir)
        (Path(self.repo_dir) / "main.py").write_text("print('original')\n", encoding="utf-8")
        _run(["add", "-A"], cwd=self.repo_dir)
        _run(["commit", "-m", "initial"], cwd=self.repo_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_is_git_repo_detects_real_and_non_repo_dirs(self):
        self.assertTrue(is_git_repo(self.repo_dir))
        non_repo = str(Path(self.temp_root) / "not_a_repo")
        Path(non_repo).mkdir()
        self.assertFalse(is_git_repo(non_repo))

    def test_creates_separate_worktree_with_own_branch(self):
        worktree = create_isolated_worktree(self.repo_dir, "Health-Check-Endpoint implementiert")

        self.assertTrue(Path(worktree.path).exists())
        self.assertNotEqual(str(Path(worktree.path).resolve()), str(Path(self.repo_dir).resolve()))
        self.assertTrue(worktree.branch.startswith("ai-team/"))
        # Der neue Worktree enthält den committeten Stand (main.py existiert dort auch).
        self.assertTrue((Path(worktree.path) / "main.py").exists())

    def test_writing_in_worktree_never_touches_original_working_dir(self):
        """Der eigentliche Sicherheits-Kern: Änderungen im Worktree dürfen das reale
        Arbeitsverzeichnis (self.repo_dir) NIEMALS berühren."""
        worktree = create_isolated_worktree(self.repo_dir, "Test-Aufgabe")

        # Simuliert genau das reale Vorkommnis: main.py im Worktree kaputtschreiben.
        (Path(worktree.path) / "main.py").write_text("KAPUTT \\n\\\"\\n", encoding="utf-8")

        original_content = (Path(self.repo_dir) / "main.py").read_text(encoding="utf-8")
        self.assertEqual(original_content, "print('original')\n")

    def test_two_consecutive_runs_get_distinct_worktrees(self):
        first = create_isolated_worktree(self.repo_dir, "Aufgabe A")
        second = create_isolated_worktree(self.repo_dir, "Aufgabe A")  # gleiche Beschreibung
        self.assertNotEqual(first.path, second.path)
        self.assertNotEqual(first.branch, second.branch)

    def test_raises_clear_error_for_non_git_directory(self):
        non_repo = str(Path(self.temp_root) / "plain_dir")
        Path(non_repo).mkdir()
        with self.assertRaises(GitIsolationError):
            create_isolated_worktree(non_repo, "Test")

    def test_remove_worktree_cleans_up_successfully(self):
        worktree = create_isolated_worktree(self.repo_dir, "Aufraeumen")
        ok, _ = remove_worktree(worktree)
        self.assertTrue(ok)
        self.assertFalse(Path(worktree.path).exists())

    def test_find_git_root_for_subdirectory(self):
        subdir = str(Path(self.repo_dir) / "some" / "nested" / "dir")
        Path(subdir).mkdir(parents=True)
        self.assertEqual(find_git_root(subdir), str(Path(self.repo_dir).resolve()))

    def test_find_git_root_works_for_not_yet_existing_path(self):
        """Ein brandneues Workspace-Projekt existiert zum Zeitpunkt der Prüfung u.U. noch
        nicht - find_git_root muss dann beim naechsten existierenden Elternordner ansetzen."""
        not_yet_created = str(Path(self.repo_dir) / "workspace" / "brand_new_project")
        self.assertEqual(find_git_root(not_yet_created), str(Path(self.repo_dir).resolve()))

    def test_find_git_root_returns_none_outside_any_repo(self):
        non_repo = str(Path(self.temp_root) / "no_repo_here")
        Path(non_repo).mkdir()
        self.assertIsNone(find_git_root(non_repo))

    def test_has_uncommitted_changes_detects_dirty_state(self):
        self.assertFalse(has_uncommitted_changes(self.repo_dir, self.repo_dir))
        (Path(self.repo_dir) / "main.py").write_text("print('modified')\n", encoding="utf-8")
        self.assertTrue(has_uncommitted_changes(self.repo_dir, self.repo_dir))

    def test_has_uncommitted_changes_scoped_to_subpath(self):
        """Unkommittete Aenderungen an EINEM Projekt duerfen ein ANDERES, sauberes
        Projekt im selben Repo nicht faelschlich als 'dirty' markieren."""
        (Path(self.repo_dir) / "workspace_a").mkdir()
        (Path(self.repo_dir) / "workspace_a" / "file.py").write_text("x = 1\n", encoding="utf-8")
        _run(["add", "-A"], cwd=self.repo_dir)
        _run(["commit", "-m", "add workspace_a"], cwd=self.repo_dir)

        (Path(self.repo_dir) / "workspace_b").mkdir()
        (Path(self.repo_dir) / "workspace_b" / "dirty.py").write_text("y = 2\n", encoding="utf-8")

        self.assertFalse(has_uncommitted_changes(self.repo_dir, str(Path(self.repo_dir) / "workspace_a")))
        self.assertTrue(has_uncommitted_changes(self.repo_dir, str(Path(self.repo_dir) / "workspace_b")))


if __name__ == "__main__":
    unittest.main()
