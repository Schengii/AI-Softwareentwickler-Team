"""
tests/test_diff_patcher.py – Tests für die Unified-Diff und Search/Replace Patching-Engine.
"""

import tempfile
import unittest
from pathlib import Path

from core.diff_patcher import (
    apply_search_replace_patch,
    apply_unified_diff,
    patch_content,
    patch_file,
)


class TestDiffPatcher(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_search_replace_single_block(self):
        original = "def hello():\n    return 'old'\n"
        patch = """
<<<<<<< SEARCH
def hello():
    return 'old'
=======
def hello():
    return 'new'
>>>>>>> REPLACE
"""
        success, res, msg = apply_search_replace_patch(original, patch)
        self.assertTrue(success)
        self.assertIn("return 'new'", res)
        self.assertNotIn("return 'old'", res)

    def test_search_replace_multi_block(self):
        original = "val1 = 1\nval2 = 2\nval3 = 3\n"
        patch = """
<<<<<<< SEARCH
val1 = 1
=======
val1 = 100
>>>>>>> REPLACE

<<<<<<< SEARCH
val3 = 3
=======
val3 = 300
>>>>>>> REPLACE
"""
        success, res, msg = apply_search_replace_patch(original, patch)
        self.assertTrue(success)
        self.assertIn("val1 = 100", res)
        self.assertIn("val2 = 2", res)
        self.assertIn("val3 = 300", res)

    def test_search_replace_missing_target(self):
        original = "a = 1\nb = 2\n"
        patch = """
<<<<<<< SEARCH
c = 999
=======
c = 1000
>>>>>>> REPLACE
"""
        success, res, msg = apply_search_replace_patch(original, patch)
        self.assertFalse(success)
        self.assertIn("Suchmuster nicht gefunden", msg)

    def test_unified_diff_single_hunk(self):
        original = """line 1
line 2
line 3
line 4
line 5
"""
        diff = """--- a/file.txt
+++ b/file.txt
@@ -2,3 +2,3 @@
 line 2
-line 3
+line 3 MODIFIED
 line 4
"""
        success, res, msg = apply_unified_diff(original, diff)
        self.assertTrue(success)
        self.assertIn("line 3 MODIFIED", res)
        self.assertNotIn("line 3\n", res)

    def test_patch_content_auto_detect(self):
        original = "x = 10\n"
        patch_sr = "<<<<<<< SEARCH\nx = 10\n=======\nx = 20\n>>>>>>> REPLACE\n"
        success, res, msg = patch_content(original, patch_sr)
        self.assertTrue(success)
        self.assertEqual(res.strip(), "x = 20")

    def test_patch_file(self):
        file_path = self.project_dir / "app.py"
        file_path.write_text("status = 'pending'\n", encoding="utf-8")

        patch = """
<<<<<<< SEARCH
status = 'pending'
=======
status = 'completed'
>>>>>>> REPLACE
"""
        success, msg = patch_file(file_path, patch)
        self.assertTrue(success)
        self.assertEqual(file_path.read_text(encoding="utf-8").strip(), "status = 'completed'")


if __name__ == "__main__":
    unittest.main()
