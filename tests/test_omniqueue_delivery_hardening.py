"""
tests/test_omniqueue_delivery_hardening.py – Deckt die drei deterministischen Härtungen aus der
OmniQueue-Fehleranalyse (ki_team_fehleranalyse_zusammenfassung.md, 12.09.2026) ab:

- Befund 2: `performance` gehört zu den Code-schreibenden Rollen (agents/base_agent.py), sonst
  liefert der Lasttest-Ingenieur sein Locust-Skript nur als Text (33.403 Tokens, 0 Dateien).
- Befund 3: zwei Agenten schreiben dieselbe `requirements.txt`; der zweite kannte `starlette`
  nicht und löschte es (core/dependency_manifest.py + core/agent_toolbox.py).
- Befund 4: der Text-Fallback erkannte die branchenübliche Konvention "Dateipfad als Kommentar
  in der ersten Fence-Zeile" nicht (core/workspace.py), wodurch eine komplette, im Text
  vorliegende Testsuite verworfen wurde (46.643 Tokens).
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path

from agents.base_agent import CODE_WRITING_AGENT_IDS
from core.agent_toolbox import AgentToolbox
from core.dependency_manifest import merge_preserving_requirements
from core.workspace import _find_file_blocks, text_has_extractable_file_blocks


def run(coro):
    return asyncio.run(coro)


class TestPerformanceIsCodeWriting(unittest.TestCase):
    def test_performance_agent_is_subject_to_the_delivery_gate(self):
        self.assertIn("performance", CODE_WRITING_AGENT_IDS)


class TestFirstLineCommentFallback(unittest.TestCase):
    def test_path_as_first_fence_comment_is_recognized(self):
        text = (
            "Hier die Testsuite:\n\n"
            "```python\n"
            "# tests/test_api.py\n"
            "import pytest\n\n"
            "def test_health():\n"
            "    assert True\n"
            "```\n"
        )
        blocks = _find_file_blocks(text)
        self.assertIn("tests/test_api.py", blocks)
        # Der Pfad-Kommentar bleibt Teil des gespeicherten Inhalts (gültiges Python, dient als
        # Herkunftsnachweis der über den Fallback geretteten Datei).
        self.assertIn("import pytest", blocks["tests/test_api.py"])
        self.assertTrue(text_has_extractable_file_blocks(text))

    def test_negative_example_with_first_line_comment_is_not_saved(self):
        text = (
            "### ❌ VORHER: ungefilterte Eingaben\n"
            "```python\n"
            "# app/api/endpoints.py\n"
            "async def ingest(payload: dict):\n"
            "    return payload\n"
            "```\n"
        )
        self.assertEqual(_find_file_blocks(text), {})

    def test_stub_body_after_path_comment_is_not_saved(self):
        text = "```python\n# app/main.py\n...\n```\n"
        self.assertEqual(_find_file_blocks(text), {})

    def test_ordinary_prose_comment_is_not_mistaken_for_a_path(self):
        text = "```python\n# Diese Funktion prüft den Status\ndef check():\n    return True\n```\n"
        self.assertEqual(_find_file_blocks(text), {})


class TestMergePreservingRequirements(unittest.TestCase):
    def test_package_missing_in_new_content_is_preserved(self):
        current = "fastapi==0.110.0\nstarlette==0.36.3\n"
        new = "fastapi==0.110.0\nsqlalchemy==2.0.29\n"
        merged, preserved = merge_preserving_requirements(current, new)
        self.assertEqual(preserved, ["starlette==0.36.3"])
        self.assertIn("starlette==0.36.3", merged)
        self.assertIn("sqlalchemy==2.0.29", merged)

    def test_new_content_wins_for_packages_it_lists_itself(self):
        # Kein Duplikat, wenn der neue Inhalt dasselbe Paket mit anderer Version pinnt.
        merged, preserved = merge_preserving_requirements("fastapi==0.110.0\n", "fastapi==0.111.0\n")
        self.assertEqual(preserved, [])
        self.assertEqual(merged, "fastapi==0.111.0\n")

    def test_normalized_names_are_treated_as_equal(self):
        # PEP 503: `Pytest_Asyncio` und `pytest-asyncio` sind dasselbe Paket.
        _, preserved = merge_preserving_requirements("Pytest_Asyncio==0.23\n", "pytest-asyncio==0.24\n")
        self.assertEqual(preserved, [])

    def test_comments_and_options_are_not_treated_as_packages(self):
        _, preserved = merge_preserving_requirements("# Basis\n-r base.txt\n", "fastapi\n")
        self.assertEqual(preserved, [])


class TestWriteFilePreservesForeignDependencies(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.toolbox = AgentToolbox(project_dir=self.temp_dir, agent_id="database")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write(self, path: str, content: str) -> dict:
        return run(self.toolbox.dispatch("write_file", {"path": path, "content": content}))

    def test_overwriting_requirements_keeps_foreign_packages(self):
        manifest = Path(self.temp_dir) / "requirements.txt"
        manifest.write_text("fastapi==0.110.0\nstarlette==0.36.3\n", encoding="utf-8")
        # Der Agent muss den aktuellen Stand kennen, sonst greift bereits _reject_if_stale.
        run(self.toolbox.dispatch("read_file", {"path": "requirements.txt"}))

        result = self._write("requirements.txt", "fastapi==0.110.0\nsqlalchemy==2.0.29\n")

        self.assertEqual(result["status"], "ok")
        self.assertIn("starlette", result["warning"])
        self.assertIn("starlette==0.36.3", manifest.read_text(encoding="utf-8"))

    def test_normal_source_file_is_written_verbatim(self):
        result = self._write("app/main.py", "app = 1\n")
        self.assertEqual(result["status"], "ok")
        self.assertNotIn("warning", result)
        self.assertEqual((Path(self.temp_dir) / "app/main.py").read_text(encoding="utf-8"), "app = 1\n")


if __name__ == "__main__":
    unittest.main()
