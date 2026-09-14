"""
tests/test_agent_toolbox_component_library.py – Testet das neue search_component_library-
Werkzeug in core/agent_toolbox.py (Gesamtsystem-Analyse 2026-09-14, Punkt 3.2).

Wichtigster Punkt: die Bibliothek liegt unter memory/component_library/, AUSSERHALB von
project_dir - _resolve() (Sicherheitsgrenze für read_file/write_file/edit_file) würde einen
Zugriff darauf normalerweise als Directory-Traversal ablehnen. Das Werkzeug muss den Code deshalb
DIREKT im Ergebnis mitliefern, keinen Pfad, der einen separaten read_file-Aufruf erfordern würde.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import core.component_library as component_library
from core.agent_toolbox import READ_ONLY_TOOL_NAMES, TOOL_SPECS, AgentToolbox


def run(coro):
    return asyncio.run(coro)


class TestSearchComponentLibraryTool(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.toolbox = AgentToolbox(project_dir=self.temp_dir, agent_id="backend")

        self.library_dir = tempfile.mkdtemp()
        self._patcher = patch.object(component_library, "LIBRARY_DIR", Path(self.library_dir) / "component_library")
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        manifest_patcher = patch.object(
            component_library, "MANIFEST_FILE",
            Path(self.library_dir) / "component_library" / "manifest.json",
        )
        manifest_patcher.start()
        self.addCleanup(manifest_patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        shutil.rmtree(self.library_dir, ignore_errors=True)

    def test_tool_is_registered_and_read_only(self):
        names = {spec["name"] for spec in TOOL_SPECS}
        self.assertIn("search_component_library", names)
        self.assertIn("search_component_library", READ_ONLY_TOOL_NAMES)

    def test_read_only_toolbox_can_use_it(self):
        read_only_box = AgentToolbox(project_dir=self.temp_dir, agent_id="planning_lead", read_only=True)
        result = run(read_only_box.dispatch("search_component_library", {"query": "circuit breaker"}))
        self.assertNotIn("error", result)

    def test_empty_library_returns_helpful_note(self):
        result = run(self.toolbox.dispatch("search_component_library", {"query": "circuit breaker"}))
        self.assertEqual(result["results"], [])
        self.assertIn("note", result)

    def test_match_returns_full_code_inline_not_just_a_path(self):
        """Der Kern dieses Werkzeugs: ein Treffer außerhalb von project_dir wäre über read_file
        gar nicht erreichbar (Directory-Traversal-Schutz in _resolve()) - der Code muss deshalb
        direkt im Ergebnis stehen."""
        source_project = tempfile.mkdtemp()
        try:
            (Path(source_project) / "resilience.py").write_text(
                "class CircuitBreaker:\n"
                "    def __init__(self):\n"
                "        self.state = 'CLOSED'\n"
                "        self.failures = 0\n"
                "        self.threshold = 5\n"
                "    def record_failure(self):\n"
                "        self.failures += 1\n"
                "    def allow(self):\n"
                "        return self.failures < self.threshold\n",
                encoding="utf-8",
            )
            component_library.harvest_from_project(source_project, "quellprojekt")
        finally:
            shutil.rmtree(source_project, ignore_errors=True)

        result = run(self.toolbox.dispatch("search_component_library", {"query": "circuit breaker"}))
        self.assertEqual(len(result["results"]), 1)
        match = result["results"][0]
        self.assertNotIn("snippet_file", match)  # kein Pfad, der außerhalb project_dir liegt
        self.assertIn("record_failure", match["code"])
        self.assertEqual(match["source_project"], "quellprojekt")


if __name__ == "__main__":
    unittest.main()
