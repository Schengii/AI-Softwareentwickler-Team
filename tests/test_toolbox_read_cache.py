"""
tests/test_toolbox_read_cache.py – Testet den Lese-Cache in AgentToolbox._tool_read_file()
(Team-Goal 20260913, Aufgabe 3): wiederholte, unveränderte volle read_file-Aufrufe auf
dieselbe Datei sollen nur einen kompakten Cache-Hinweis liefern statt den kompletten Inhalt
erneut in den Nachrichtenverlauf zu blasen - line_start/line_end und force=True bleiben davon
unberührt (liefern immer den echten Inhalt), und eine zwischenzeitliche Änderung (write_file/
edit_file) invalidiert den Cache automatisch (Inhalts-Hash ändert sich).
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from core.agent_toolbox import AgentToolbox


def run(coro):
    return asyncio.run(coro)


class TestToolboxReadCache(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.toolbox = AgentToolbox(project_dir=self.temp_dir, agent_id="backend")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_first_read_returns_full_content(self):
        run(self.toolbox.dispatch("write_file", {"path": "app.py", "content": "x = 1\n"}))
        result = run(self.toolbox.dispatch("read_file", {"path": "app.py"}))
        self.assertEqual(result["content"], "x = 1\n")
        self.assertNotIn("cached", result)

    def test_repeated_unchanged_full_read_returns_cache_notice(self):
        run(self.toolbox.dispatch("write_file", {"path": "app.py", "content": "x = 1\n"}))
        run(self.toolbox.dispatch("read_file", {"path": "app.py"}))  # erster echter read_file-Aufruf

        second = run(self.toolbox.dispatch("read_file", {"path": "app.py"}))
        self.assertTrue(second.get("cached"))
        self.assertNotIn("content", second)
        self.assertIn("bereits unverändert übergeben", second["notice"])

    def test_read_after_edit_returns_full_content_again(self):
        run(self.toolbox.dispatch("write_file", {"path": "app.py", "content": "x = 1\n"}))
        run(self.toolbox.dispatch("read_file", {"path": "app.py"}))
        run(self.toolbox.dispatch("edit_file", {"path": "app.py", "old_text": "x = 1", "new_text": "x = 2"}))

        result = run(self.toolbox.dispatch("read_file", {"path": "app.py"}))
        self.assertNotIn("cached", result)
        self.assertEqual(result["content"], "x = 2\n")

    def test_force_bypasses_cache(self):
        run(self.toolbox.dispatch("write_file", {"path": "app.py", "content": "x = 1\n"}))
        run(self.toolbox.dispatch("read_file", {"path": "app.py"}))

        forced = run(self.toolbox.dispatch("read_file", {"path": "app.py", "force": True}))
        self.assertNotIn("cached", forced)
        self.assertEqual(forced["content"], "x = 1\n")

    def test_line_range_bypasses_cache_and_returns_slice(self):
        content = "line1\nline2\nline3\nline4\n"
        run(self.toolbox.dispatch("write_file", {"path": "app.py", "content": content}))
        run(self.toolbox.dispatch("read_file", {"path": "app.py"}))

        sliced = run(self.toolbox.dispatch("read_file", {"path": "app.py", "line_start": 2, "line_end": 3}))
        self.assertNotIn("cached", sliced)
        self.assertEqual(sliced["content"], "line2\nline3")
        self.assertEqual(sliced["line_start"], 2)
        self.assertEqual(sliced["line_end"], 3)

    def test_cache_expires_after_repeat_window(self):
        run(self.toolbox.dispatch("write_file", {"path": "app.py", "content": "x = 1\n"}))
        run(self.toolbox.dispatch("read_file", {"path": "app.py"}))

        # Simuliert, dass das letzte volle Lesen bereits außerhalb des Wiederholungsfensters lag.
        with patch.object(AgentToolbox, "READ_CACHE_REPEAT_WINDOW_SECONDS", 0.0):
            result = run(self.toolbox.dispatch("read_file", {"path": "app.py"}))
        self.assertNotIn("cached", result)
        self.assertEqual(result["content"], "x = 1\n")


if __name__ == "__main__":
    unittest.main()
