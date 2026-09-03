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
    copy_worktree_changes_to_target,
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


class TestCopyWorktreeChangesToTarget(unittest.TestCase):
    """
    Realer Fund (mockforge-Governance-Retry, Team-Bestandsaufnahme 2026-09-03): core/backlog_
    worker.py und core/issue_watcher.py prüfen nach einem Orchestrator-Lauf per
    `github_agent.get_status()`, ob sich am ECHTEN Arbeitsverzeichnis etwas geändert hat - bei
    einem isolierten Lauf (JEDER Lauf gegen bereits vorhandenen Inhalt, siehe
    _resolve_project_isolation()) landete die Arbeit aber ausschließlich im Worktree, nie im
    echten Verzeichnis. copy_worktree_changes_to_target() schließt genau diese Lücke.
    """

    def setUp(self):
        self.temp_root = tempfile.mkdtemp()
        self.repo_dir = str(Path(self.temp_root) / "repo")
        Path(self.repo_dir).mkdir()
        _run(["init", "-b", "main"], cwd=self.repo_dir)
        _run(["config", "user.email", "test@example.com"], cwd=self.repo_dir)
        _run(["config", "user.name", "Test"], cwd=self.repo_dir)
        (Path(self.repo_dir) / "app").mkdir()
        (Path(self.repo_dir) / "app" / "middleware.py").write_text("old = 1\n", encoding="utf-8")
        (Path(self.repo_dir) / "app" / "to_delete.py").write_text("gone_soon = True\n", encoding="utf-8")
        _run(["add", "-A"], cwd=self.repo_dir)
        _run(["commit", "-m", "initial"], cwd=self.repo_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_modified_file_is_copied_back_uncommitted(self):
        worktree = create_isolated_worktree(self.repo_dir, "Fix Middleware")
        (Path(worktree.path) / "app" / "middleware.py").write_text("fixed = 2\n", encoding="utf-8")

        changed = copy_worktree_changes_to_target(worktree, self.repo_dir)

        self.assertIn("app/middleware.py", changed)
        self.assertEqual(
            (Path(self.repo_dir) / "app" / "middleware.py").read_text(encoding="utf-8"), "fixed = 2\n",
        )
        # Bewusst NICHT committet - das übernimmt der Aufrufer (github_agent.commit()).
        self.assertTrue(has_uncommitted_changes(self.repo_dir, self.repo_dir))

    def test_new_file_is_copied_back(self):
        worktree = create_isolated_worktree(self.repo_dir, "Neue Datei")
        (Path(worktree.path) / "app" / "new_module.py").write_text("x = 1\n", encoding="utf-8")

        changed = copy_worktree_changes_to_target(worktree, self.repo_dir)

        self.assertIn("app/new_module.py", changed)
        self.assertTrue((Path(self.repo_dir) / "app" / "new_module.py").exists())

    def test_deleted_file_is_removed_in_target(self):
        worktree = create_isolated_worktree(self.repo_dir, "Datei löschen")
        (Path(worktree.path) / "app" / "to_delete.py").unlink()

        changed = copy_worktree_changes_to_target(worktree, self.repo_dir)

        self.assertIn("app/to_delete.py", changed)
        self.assertFalse((Path(self.repo_dir) / "app" / "to_delete.py").exists())

    def test_clean_worktree_returns_empty_list_and_touches_nothing(self):
        worktree = create_isolated_worktree(self.repo_dir, "Nichts geändert")
        changed = copy_worktree_changes_to_target(worktree, self.repo_dir)
        self.assertEqual(changed, [])
        self.assertFalse(has_uncommitted_changes(self.repo_dir, self.repo_dir))

    def test_target_working_dir_untouched_until_copy_is_called(self):
        """Bis zum expliziten Aufruf bleibt das Sicherheitsversprechen aus
        test_writing_in_worktree_never_touches_original_working_dir oben unverändert gültig."""
        worktree = create_isolated_worktree(self.repo_dir, "Verzögerter Merge")
        (Path(worktree.path) / "app" / "middleware.py").write_text("fixed = 2\n", encoding="utf-8")
        self.assertEqual(
            (Path(self.repo_dir) / "app" / "middleware.py").read_text(encoding="utf-8"), "old = 1\n",
        )
        copy_worktree_changes_to_target(worktree, self.repo_dir)
        self.assertEqual(
            (Path(self.repo_dir) / "app" / "middleware.py").read_text(encoding="utf-8"), "fixed = 2\n",
        )


if __name__ == "__main__":
    unittest.main()
