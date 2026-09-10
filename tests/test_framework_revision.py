"""
tests/test_framework_revision.py – Testet core/framework_revision.py.

Realer Fund (auditlog_sentinel, 2026-09-10): Commit 66ab8c0 führte um 14:40 Uhr eine
Modell-Mindeststufe ein. Ein Lauf um 15:20 Uhr lief trotzdem komplett auf dem schwächsten
Modell - die seit dem Vormittag laufende CLI führte noch den beim Prozessstart geladenen,
alten Code aus. source_fingerprint() muss eine Codeänderung erkennen, ohne bei unverändertem
Code unnötig oft `git` aufzurufen.
"""

import tempfile
import unittest
from pathlib import Path

from core.framework_revision import current_revision, source_fingerprint


class TestSourceFingerprint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "core").mkdir()
        (self.root / "core" / "example.py").write_text("x = 1\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_stable_for_unchanged_tree(self):
        self.assertEqual(source_fingerprint(self.root), source_fingerprint(self.root))

    def test_changes_when_a_source_file_changes(self):
        before = source_fingerprint(self.root)
        (self.root / "core" / "example.py").write_text("x = 2\n", encoding="utf-8")
        after = source_fingerprint(self.root)
        self.assertNotEqual(before, after)

    def test_changes_when_a_source_file_is_added(self):
        before = source_fingerprint(self.root)
        (self.root / "core" / "new_module.py").write_text("y = 1\n", encoding="utf-8")
        after = source_fingerprint(self.root)
        self.assertNotEqual(before, after)

    def test_ignores_non_source_directories(self):
        (self.root / "agents").mkdir()
        (self.root / "agents" / "__pycache__").mkdir()
        (self.root / "agents" / "__pycache__" / "cached.pyc").write_bytes(b"\x00")
        before = source_fingerprint(self.root)
        (self.root / "agents" / "__pycache__" / "cached.pyc").write_bytes(b"\x01\x02")
        after = source_fingerprint(self.root)
        self.assertEqual(before, after)


class TestCurrentRevision(unittest.TestCase):
    def test_unknown_commit_outside_a_git_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "core").mkdir()
            revision = current_revision(root)
        self.assertEqual(revision.commit, "unbekannt")
        self.assertFalse(revision.dirty)

    def test_label_marks_dirty_state(self):
        from core.framework_revision import FrameworkRevision

        clean = FrameworkRevision(commit="abc123", dirty=False, fingerprint="x")
        dirty = FrameworkRevision(commit="abc123", dirty=True, fingerprint="x")
        self.assertEqual(clean.label(), "abc123")
        self.assertIn("lokale Änderungen", dirty.label())


if __name__ == "__main__":
    unittest.main()
