"""
tests/test_team_memory.py – Testet core/team_memory.py (Punkt 3 einer Team-Retrospektive):
projektübergreifendes Lessons-Learned-Gedächtnis, das Muster aus mehreren, unabhängigen
Projekten in EINER repo-weiten Datei sammelt und in den Kontext künftiger Läufe einspeist.
"""

import unittest
from unittest.mock import patch

from core import team_memory


class TestTeamMemory(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = None

    def _use_temp_file(self, tmp_path):
        return patch.object(team_memory, "TEAM_MEMORY_FILE", tmp_path)

    def test_read_without_any_recorded_lesson_returns_empty(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            fake_file = Path(d) / "does_not_exist.jsonl"
            with self._use_temp_file(fake_file):
                self.assertEqual(team_memory.read_team_lessons(), [])
                self.assertEqual(team_memory.format_team_lessons_for_agents(), "")

    def test_record_then_read_roundtrip_newest_first(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            fake_file = Path(d) / "team_lessons.jsonl"
            with self._use_temp_file(fake_file):
                team_memory.record_lesson("project_a", "recurring_failure", "Erster Fund.")
                team_memory.record_lesson("project_b", "recurring_failure", "Zweiter Fund.")

                lessons = team_memory.read_team_lessons()
                self.assertEqual(len(lessons), 2)
                self.assertEqual(lessons[0]["project_slug"], "project_b")
                self.assertEqual(lessons[1]["project_slug"], "project_a")

    def test_format_for_agents_includes_project_slug_and_detail(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            fake_file = Path(d) / "team_lessons.jsonl"
            with self._use_temp_file(fake_file):
                team_memory.record_lesson("cors_bug_proj", "recurring_failure", "CORS wiederholt vergessen.")
                text = team_memory.format_team_lessons_for_agents()
                self.assertIn("cors_bug_proj", text)
                self.assertIn("CORS wiederholt vergessen.", text)

    def test_record_lesson_dedups_near_identical_entries(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            fake_file = Path(d) / "team_lessons.jsonl"
            with self._use_temp_file(fake_file):
                team_memory.record_lesson("project_a", "recurring_failure", "CORS wiederholt vergessen.")
                team_memory.record_lesson("project_b", "recurring_failure", "cors WIEDERHOLT vergessen!!")
                lessons = team_memory.read_team_lessons()
                self.assertEqual(len(lessons), 1)
                self.assertEqual(lessons[0]["project_slug"], "project_a")

    def test_record_lesson_same_detail_different_category_not_deduped(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            fake_file = Path(d) / "team_lessons.jsonl"
            with self._use_temp_file(fake_file):
                team_memory.record_lesson("project_a", "recurring_failure", "Gleicher Text.")
                team_memory.record_lesson("project_b", "governance_escalation", "Gleicher Text.")
                self.assertEqual(len(team_memory.read_team_lessons()), 2)

    def test_prioritize_slug_puts_matching_project_lesson_first_even_if_older(self):
        # Team-Optimierung (Retrospektive 2026-09-04): real beobachtet an `zeiterfassung_app`
        # - zwei separate Lektionen für dasselbe Projekt sollen NICHT hinter zwischenzeitlich
        # aufgezeichneten Lektionen ANDERER Projekte im "limit"-Fenster verschwinden.
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            fake_file = Path(d) / "team_lessons.jsonl"
            with self._use_temp_file(fake_file):
                team_memory.record_lesson("zeiterfassung_app", "unresolved_governance_critical", "Fehlende Router-Struktur.")
                team_memory.record_lesson("mockforge", "recurring_failure", "Andere Projekte dazwischen 1.")
                team_memory.record_lesson("taskpulse", "recurring_failure", "Andere Projekte dazwischen 2.")
                team_memory.record_lesson("webhook_shield", "recurring_failure", "Andere Projekte dazwischen 3.")

                text = team_memory.format_team_lessons_for_agents(limit=3, prioritize_slug="zeiterfassung_app")

                lines = [line for line in text.splitlines() if line.startswith("- [")]
                self.assertEqual(len(lines), 3)
                self.assertIn("zeiterfassung_app", lines[0])
                self.assertIn("Fehlende Router-Struktur.", lines[0])

    def test_prioritize_slug_empty_keeps_pure_recency_behavior(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            fake_file = Path(d) / "team_lessons.jsonl"
            with self._use_temp_file(fake_file):
                team_memory.record_lesson("project_a", "recurring_failure", "Älterer Fund.")
                team_memory.record_lesson("project_b", "recurring_failure", "Neuerer Fund.")

                text = team_memory.format_team_lessons_for_agents(limit=1, prioritize_slug="")

                self.assertIn("Neuerer Fund.", text)
                self.assertNotIn("Älterer Fund.", text)

    def test_prioritize_slug_with_no_own_lessons_falls_back_to_recency(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            fake_file = Path(d) / "team_lessons.jsonl"
            with self._use_temp_file(fake_file):
                team_memory.record_lesson("project_a", "recurring_failure", "Einziger Fund.")

                text = team_memory.format_team_lessons_for_agents(limit=5, prioritize_slug="brand_new_project")

                self.assertIn("Einziger Fund.", text)

    def test_record_lesson_never_raises_on_unwritable_path(self):
        from pathlib import Path
        # Ein Pfad, dessen Elternverzeichnis nicht angelegt werden kann (ungültiges Laufwerk) -
        # record_lesson() ist best-effort und darf einen laufenden Team-Lauf nie zum Absturz bringen.
        with self._use_temp_file(Path("Z:\\definitiv\\nicht\\vorhanden\\team_lessons.jsonl")):
            try:
                team_memory.record_lesson("x", "y", "z")
            except OSError:
                self.fail("record_lesson() darf niemals eine OSError durchreichen (best-effort).")


if __name__ == "__main__":
    unittest.main()
