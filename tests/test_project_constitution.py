"""
tests/test_project_constitution.py – Testet core/project_constitution.py (Tech-Stack-Präferenzen)

Realer Fund: project_slug/Architektur/Tech-Stack werden pro Lauf frisch vom Modell geraten -
selbst am selben Projekt kann Lauf 2 eine andere Sprache/Framework wählen als Lauf 1, wenn die
Nutzeranfrage das nicht jedes Mal explizit wiederholt. Dieses Modul gibt dem Nutzer die
Kontrolle über feste Präferenzen, die JEDEM künftigen Lauf als verbindlicher Kontext
mitgegeben werden.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from core.project_constitution import (
    CONSTITUTION_FILENAME,
    format_constitution_for_agents,
    get_max_project_tokens,
    read_constitution,
    write_constitution,
)


class TestProjectConstitution(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_read_returns_empty_dict_when_no_file_exists(self):
        self.assertEqual(read_constitution(self.temp_dir), {})

    def test_write_then_read_roundtrip(self):
        write_constitution(self.temp_dir, {
            "language": "Python", "framework": "FastAPI", "test_framework": "pytest",
        })
        result = read_constitution(self.temp_dir)
        self.assertEqual(result["language"], "Python")
        self.assertEqual(result["framework"], "FastAPI")
        self.assertEqual(result["test_framework"], "pytest")

    def test_unknown_fields_are_ignored_on_write(self):
        write_constitution(self.temp_dir, {"language": "Python", "not_a_real_field": "irrelevant"})
        result = read_constitution(self.temp_dir)
        self.assertIn("language", result)
        self.assertNotIn("not_a_real_field", result)

    def test_empty_or_blank_fields_are_not_written(self):
        write_constitution(self.temp_dir, {"language": "Python", "framework": "", "notes": "   "})
        result = read_constitution(self.temp_dir)
        self.assertIn("language", result)
        self.assertNotIn("framework", result)
        self.assertNotIn("notes", result)

    def test_rewrite_replaces_previous_values_entirely(self):
        write_constitution(self.temp_dir, {"language": "Python", "framework": "FastAPI"})
        write_constitution(self.temp_dir, {"language": "TypeScript"})  # framework nicht erneut übergeben
        result = read_constitution(self.temp_dir)
        self.assertEqual(result, {"language": "TypeScript"})

    def test_values_with_quotes_and_backslashes_survive_roundtrip(self):
        tricky = 'Nutze "PEP 8" und C:\\Pfade\\mit\\Backslash'
        write_constitution(self.temp_dir, {"code_style": tricky})
        result = read_constitution(self.temp_dir)
        self.assertEqual(result["code_style"], tricky)

    def test_corrupted_file_does_not_crash(self):
        (Path(self.temp_dir) / CONSTITUTION_FILENAME).write_text("not = valid = toml = [[[", encoding="utf-8")
        self.assertEqual(read_constitution(self.temp_dir), {})

    def test_format_for_agents_is_empty_without_constitution(self):
        self.assertEqual(format_constitution_for_agents(self.temp_dir), "")

    def test_format_for_agents_includes_all_set_fields(self):
        write_constitution(self.temp_dir, {
            "language": "Python", "deployment_target": "Docker + Hetzner",
        })
        context = format_constitution_for_agents(self.temp_dir)
        self.assertIn("Python", context)
        self.assertIn("Docker + Hetzner", context)
        self.assertIn("Projekt-Konstitution", context)

    def test_max_project_tokens_is_excluded_from_agent_context(self):
        # Operative Kennzahl, keine inhaltliche Vorgabe - würde im Prompt nur unnötigen,
        # wirkungslosen Text erzeugen (siehe _OPERATIONAL_FIELDS in core/project_constitution.py).
        write_constitution(self.temp_dir, {"language": "Python", "max_project_tokens": "50000"})
        context = format_constitution_for_agents(self.temp_dir)
        self.assertIn("Python", context)
        self.assertNotIn("50000", context)

    def test_format_for_agents_is_empty_when_only_max_project_tokens_is_set(self):
        write_constitution(self.temp_dir, {"max_project_tokens": "50000"})
        self.assertEqual(format_constitution_for_agents(self.temp_dir), "")

    def test_get_max_project_tokens_reads_valid_value(self):
        write_constitution(self.temp_dir, {"max_project_tokens": "50000"})
        self.assertEqual(get_max_project_tokens(self.temp_dir), 50000)

    def test_get_max_project_tokens_defaults_to_zero_when_unset(self):
        self.assertEqual(get_max_project_tokens(self.temp_dir), 0)

    def test_get_max_project_tokens_ignores_non_numeric_value_without_crashing(self):
        write_constitution(self.temp_dir, {"max_project_tokens": "viel"})
        self.assertEqual(get_max_project_tokens(self.temp_dir), 0)

    def test_get_max_project_tokens_rejects_negative_value(self):
        write_constitution(self.temp_dir, {"max_project_tokens": "-100"})
        self.assertEqual(get_max_project_tokens(self.temp_dir), 0)


if __name__ == "__main__":
    unittest.main()
