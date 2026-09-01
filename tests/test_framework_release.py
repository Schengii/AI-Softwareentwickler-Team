"""
tests/test_framework_release.py – Testet echtes Release-Management (core/framework_release.py)

Realer Fund bei einer Bestandsaufnahme des eigenen Teams: CHANGELOG.md wird bei jedem PR
manuell ergänzt, aber es gibt über die gesamte Projekthistorie keine einzige Versionsnummer,
keinen Git-Tag, keine GitHub-Release – das README zeigt "v4.3" nur als hart einprogrammierte
Zeichenkette. framework_release.py leitet SemVer-Bumps aus der bereits etablierten
Commit-Konvention (feat:/fix:/...) ab und erstellt echte Git-Tags + GitHub-Releases.

Zwei Ebenen wie bei test_pr_workflow.py: reines Python (Versions-/Notizen-Logik) direkt
getestet, echte Git-Operationen (Tag/Log/Push) gegen ein echtes lokales Repo mit Bare-Remote
(kein Mock – zustandsbehaftete Git-Interaktion, die ein MagicMock nicht glaubwürdig
simulieren kann), nur `gh release create` gemockt (in der CI-Umgebung nicht installiert).
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.framework_release import (
    build_release_notes,
    bump_version,
    create_release,
    determine_version_bump,
    get_commits_since,
    get_latest_tag,
)


def _run(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")


class TestDetermineVersionBump(unittest.TestCase):
    def test_no_commits_means_no_release(self):
        self.assertIsNone(determine_version_bump([]))

    def test_feat_commit_triggers_minor_bump(self):
        self.assertEqual(determine_version_bump(["feat: neue Funktion"]), "minor")

    def test_fix_only_triggers_patch_bump(self):
        self.assertEqual(determine_version_bump(["fix: kaputten Endpunkt repariert"]), "patch")

    def test_docs_only_still_triggers_patch_bump(self):
        """Jede Änderung seit dem letzten Release soll referenzierbar sein - auch reine
        Dokumentationsänderungen, keine "leeren" Releases."""
        self.assertEqual(determine_version_bump(["docs: README aktualisiert"]), "patch")

    def test_breaking_bang_triggers_major_bump_even_with_feat_present(self):
        self.assertEqual(
            determine_version_bump(["feat: neue Funktion", "fix!: API-Bruch"]), "major",
        )

    def test_breaking_change_footer_triggers_major_bump(self):
        self.assertEqual(
            determine_version_bump(["feat: x", "refactor: BREAKING CHANGE: altes Format entfernt"]),
            "major",
        )

    def test_mixed_feat_and_fix_prefers_minor(self):
        self.assertEqual(determine_version_bump(["fix: a", "feat: b", "fix: c"]), "minor")


class TestBumpVersion(unittest.TestCase):
    def test_patch_bump(self):
        self.assertEqual(bump_version("v1.2.3", "patch"), "v1.2.4")

    def test_minor_bump_resets_patch(self):
        self.assertEqual(bump_version("v1.2.3", "minor"), "v1.3.0")

    def test_major_bump_resets_minor_and_patch(self):
        self.assertEqual(bump_version("v1.2.3", "major"), "v2.0.0")

    def test_no_prior_tag_starts_at_v0_1_0_for_minor(self):
        self.assertEqual(bump_version("v0.0.0", "minor"), "v0.1.0")

    def test_malformed_current_version_falls_back_to_v0_1_0_patch(self):
        self.assertEqual(bump_version("garbage", "patch"), "v0.1.0")


class TestBuildReleaseNotes(unittest.TestCase):
    def test_categorizes_feat_and_fix_separately(self):
        notes = build_release_notes(["feat: A hinzugefügt", "fix: B repariert", "docs: C"])
        self.assertIn("### ✨ Neue Funktionen", notes)
        self.assertIn("A hinzugefügt", notes)
        self.assertIn("### 🐛 Fehlerbehebungen", notes)
        self.assertIn("B repariert", notes)
        self.assertIn("### 🔧 Weitere Änderungen", notes)

    def test_empty_commit_list_produces_placeholder_text(self):
        self.assertIn("Keine Änderungen", build_release_notes([]))


class TestGitIntegration(unittest.TestCase):
    """Echtes lokales Git-Repo (kein Mock) für Tag-/Log-Operationen - siehe
    test_pr_workflow.py.TestCLIFullPRWorkflowAgainstRealRepo für dasselbe Prinzip."""

    def setUp(self):
        self.temp_root = tempfile.mkdtemp()
        self.remote_dir = str(Path(self.temp_root) / "remote.git")
        self.work_dir = str(Path(self.temp_root) / "work")
        Path(self.work_dir).mkdir()
        _run(["init", "--bare", "-b", "main", self.remote_dir], cwd=self.temp_root)
        _run(["init", "-b", "main"], cwd=self.work_dir)
        _run(["config", "user.email", "test@example.com"], cwd=self.work_dir)
        _run(["config", "user.name", "Test"], cwd=self.work_dir)
        (Path(self.work_dir) / "a.txt").write_text("1\n", encoding="utf-8")
        _run(["add", "-A"], cwd=self.work_dir)
        _run(["commit", "-m", "chore: initial"], cwd=self.work_dir)
        _run(["remote", "add", "origin", self.remote_dir], cwd=self.work_dir)
        _run(["push", "-u", "origin", "main"], cwd=self.work_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_no_tag_yet_returns_none(self):
        with patch("core.framework_release.BASE_DIR", self.work_dir):
            self.assertIsNone(get_latest_tag())

    def test_finds_most_recent_tag(self):
        _run(["tag", "-a", "v1.0.0", "-m", "r1"], cwd=self.work_dir)
        (Path(self.work_dir) / "a.txt").write_text("2\n", encoding="utf-8")
        _run(["add", "-A"], cwd=self.work_dir)
        _run(["commit", "-m", "feat: mehr"], cwd=self.work_dir)
        _run(["tag", "-a", "v1.1.0", "-m", "r2"], cwd=self.work_dir)

        with patch("core.framework_release.BASE_DIR", self.work_dir):
            self.assertEqual(get_latest_tag(), "v1.1.0")

    def test_commits_since_tag_excludes_older_history(self):
        _run(["tag", "-a", "v1.0.0", "-m", "r1"], cwd=self.work_dir)
        (Path(self.work_dir) / "a.txt").write_text("2\n", encoding="utf-8")
        _run(["add", "-A"], cwd=self.work_dir)
        _run(["commit", "-m", "feat: neues Ding"], cwd=self.work_dir)

        with patch("core.framework_release.BASE_DIR", self.work_dir):
            subjects = get_commits_since("v1.0.0")

        self.assertEqual(subjects, ["feat: neues Ding"])

    def test_commits_since_none_returns_full_history(self):
        with patch("core.framework_release.BASE_DIR", self.work_dir):
            subjects = get_commits_since(None)

        self.assertEqual(subjects, ["chore: initial"])


class TestCreateRelease(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp()
        self.remote_dir = str(Path(self.temp_root) / "remote.git")
        self.work_dir = str(Path(self.temp_root) / "work")
        Path(self.work_dir).mkdir()
        _run(["init", "--bare", "-b", "main", self.remote_dir], cwd=self.temp_root)
        _run(["init", "-b", "main"], cwd=self.work_dir)
        _run(["config", "user.email", "test@example.com"], cwd=self.work_dir)
        _run(["config", "user.name", "Test"], cwd=self.work_dir)
        (Path(self.work_dir) / "a.txt").write_text("1\n", encoding="utf-8")
        _run(["add", "-A"], cwd=self.work_dir)
        _run(["commit", "-m", "chore: initial"], cwd=self.work_dir)
        _run(["remote", "add", "origin", self.remote_dir], cwd=self.work_dir)
        _run(["push", "-u", "origin", "main"], cwd=self.work_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_creates_real_tag_pushes_it_and_calls_gh_release_create(self):
        real_run = subprocess.run

        def fake_run(cmd, **kwargs):
            if cmd[0] == "gh":
                return MagicMock(returncode=0, stdout="https://github.com/x/y/releases/tag/v0.1.0", stderr="")
            return real_run(cmd, **kwargs)

        with patch("core.framework_release.BASE_DIR", self.work_dir), \
             patch("core.framework_release.subprocess.run", side_effect=fake_run):
            success, output = create_release("v0.1.0", "### ✨ Neue Funktionen\n- x")

        self.assertTrue(success, output)
        self.assertIn("releases/tag/v0.1.0", output)
        tags = _run(["tag", "-l"], cwd=self.work_dir).stdout
        self.assertIn("v0.1.0", tags)
        remote_tags = _run(["ls-remote", "--tags", "origin"], cwd=self.work_dir).stdout
        self.assertIn("v0.1.0", remote_tags)

    def test_failed_gh_release_still_leaves_the_pushed_tag_in_place(self):
        real_run = subprocess.run

        def fake_run(cmd, **kwargs):
            if cmd[0] == "gh":
                return MagicMock(returncode=1, stdout="", stderr="not authenticated")
            return real_run(cmd, **kwargs)

        with patch("core.framework_release.BASE_DIR", self.work_dir), \
             patch("core.framework_release.subprocess.run", side_effect=fake_run):
            success, output = create_release("v0.1.0", "notes")

        self.assertFalse(success)
        self.assertIn("not authenticated", output)
        remote_tags = _run(["ls-remote", "--tags", "origin"], cwd=self.work_dir).stdout
        self.assertIn("v0.1.0", remote_tags)  # Tag bleibt trotz gh-Fehlschlag bestehen


if __name__ == "__main__":
    unittest.main()
