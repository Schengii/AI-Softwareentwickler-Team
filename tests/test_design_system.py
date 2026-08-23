"""
tests/test_design_system.py – Testet core/design_system.py (visuelle Design-Präferenzen)

Realer Fund (Bestandsaufnahme des eigenen Teams): core/project_constitution.py gibt dem
Nutzer bereits Kontrolle über feste Tech-Stack-Präferenzen, die JEDEM künftigen Lauf
mitgegeben werden - das visuelle Design-System (Farbpalette, Typografie, Spacing-Skala, …)
hatte bisher kein Pendant, obwohl design_lead seit der Design-vor-Dev-Aufspaltung als
eigenständige, VOR dev_lead laufende Phase existiert.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from core.design_system import (
    DESIGN_SYSTEM_FILENAME,
    format_design_system_for_agents,
    read_design_system,
    write_design_system,
)


class TestDesignSystem(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_read_returns_empty_dict_when_no_file_exists(self):
        self.assertEqual(read_design_system(self.temp_dir), {})

    def test_write_then_read_roundtrip(self):
        write_design_system(self.temp_dir, {
            "color_palette": "Primär #2563EB, Sekundär #7C3AED",
            "typography": "Inter für Fließtext, Poppins für Headlines",
        })
        result = read_design_system(self.temp_dir)
        self.assertEqual(result["color_palette"], "Primär #2563EB, Sekundär #7C3AED")
        self.assertEqual(result["typography"], "Inter für Fließtext, Poppins für Headlines")

    def test_unknown_fields_are_ignored_on_write(self):
        write_design_system(self.temp_dir, {"color_palette": "Blau", "not_a_real_field": "irrelevant"})
        result = read_design_system(self.temp_dir)
        self.assertIn("color_palette", result)
        self.assertNotIn("not_a_real_field", result)

    def test_empty_or_blank_fields_are_not_written(self):
        write_design_system(self.temp_dir, {"color_palette": "Blau", "typography": "", "notes": "   "})
        result = read_design_system(self.temp_dir)
        self.assertIn("color_palette", result)
        self.assertNotIn("typography", result)
        self.assertNotIn("notes", result)

    def test_rewrite_replaces_previous_values_entirely(self):
        write_design_system(self.temp_dir, {"color_palette": "Blau", "typography": "Inter"})
        write_design_system(self.temp_dir, {"color_palette": "Grün"})  # typography nicht erneut übergeben
        result = read_design_system(self.temp_dir)
        self.assertEqual(result, {"color_palette": "Grün"})

    def test_values_with_quotes_and_backslashes_survive_roundtrip(self):
        tricky = 'Nutze "Poppins" statt C:\\Fonts\\Arial'
        write_design_system(self.temp_dir, {"typography": tricky})
        result = read_design_system(self.temp_dir)
        self.assertEqual(result["typography"], tricky)

    def test_corrupted_file_does_not_crash(self):
        (Path(self.temp_dir) / DESIGN_SYSTEM_FILENAME).write_text("not = valid = toml = [[[", encoding="utf-8")
        self.assertEqual(read_design_system(self.temp_dir), {})

    def test_format_for_agents_is_empty_without_design_system(self):
        self.assertEqual(format_design_system_for_agents(self.temp_dir), "")

    def test_format_for_agents_includes_all_set_fields(self):
        write_design_system(self.temp_dir, {
            "color_palette": "Primär #2563EB", "tone_of_voice": "locker-professionell, Du-Form",
        })
        context = format_design_system_for_agents(self.temp_dir)
        self.assertIn("#2563EB", context)
        self.assertIn("locker-professionell", context)
        self.assertIn("Design-System", context)


if __name__ == "__main__":
    unittest.main()
