"""
tests/test_team_lessons_schema.py – Testet P3-4 (ROADMAP_TEMP.md): "team_lessons.jsonl ist
uneinheitlich und teilweise unlesbar"

Analyse 2026-09-21: die 102 realen Einträge in memory/team_lessons.jsonl entsprechen bereits
dem in core/team_memory.py definierten Zwei-Formen-Schema (Lektion: category/detail/
project_slug/signature/timestamp; Ereignis: event/signature/timestamp + event-spezifische
Felder) - read_team_lessons() trennt beide bereits sauber über das `event`-Feld. Was fehlte:
eine explizite, testbare Schema-Prüfung und eine Normalisierung für --clean-telemetry, die
künftige/ältere schema-widrige Zeilen (kaputtes JSON, fehlende Pflichtfelder, unbekannter
Ereignistyp) automatisch entfernt, statt dass CLAUDE.md's "ergiebigste Quelle für echte
Framework-Bugs" stillschweigend unlesbare Zeilen enthält.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class TestCleanTeamLessons(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "team_lessons.jsonl"

    def _write(self, lines: list[str]) -> None:
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_valid_lessons_and_events_are_kept(self):
        from core.telemetry_hygiene import clean_team_lessons

        self._write([
            '{"timestamp": "2026-09-01T00:00:00+00:00", "project_slug": "aegisflow", '
            '"category": "dependency_missing", "detail": "requirements.txt fehlt fastapi", '
            '"signature": "abc123"}',
            '{"timestamp": "2026-09-02T00:00:00+00:00", "event": "lesson_recurrence", '
            '"signature": "abc123", "project_slug": "sentinedge"}',
            '{"timestamp": "2026-09-03T00:00:00+00:00", "event": "lesson_status", '
            '"signature": "abc123", "status": "implemented", "resolution": "Regel ergänzt"}',
        ])

        total, removed = clean_team_lessons(self.path, dry_run=True)
        self.assertEqual((total, removed), (3, 0))
        self.assertEqual(len(self.path.read_text(encoding="utf-8").strip().splitlines()), 3)

    def test_malformed_json_and_missing_fields_are_removed_with_backup(self):
        from core.telemetry_hygiene import clean_team_lessons

        self._write([
            '{"timestamp": "2026-09-01T00:00:00+00:00", "project_slug": "aegisflow", '
            '"category": "dependency_missing", "detail": "requirements.txt fehlt fastapi", '
            '"signature": "abc123"}',
            "{kaputtes json",
            '{"timestamp": "2026-09-02T00:00:00+00:00", "project_slug": "sentinedge", '
            '"category": "", "detail": "leere Kategorie", "signature": "def456"}',
            '{"event": "unbekanntes_ereignis", "signature": "xyz", "timestamp": "2026-09-04"}',
            '{"project_slug": "orphanproj", "signature": "onlysig"}',
            # Lektion ganz ohne "signature" (Alteintrag) - gilt als gültig, da
            # core/team_memory.py._entry_signature() sie bei Bedarf nachberechnet.
            '{"timestamp": "2026-09-05T00:00:00+00:00", "project_slug": "logpulse", '
            '"category": "dependency_compatibility", "detail": "SQLAlchemy async Engine"}',
        ])

        total, removed = clean_team_lessons(self.path, dry_run=True)
        self.assertEqual((total, removed), (6, 4))
        # dry_run: Datei bleibt unverändert.
        self.assertEqual(len(self.path.read_text(encoding="utf-8").strip().splitlines()), 6)

        total, removed = clean_team_lessons(self.path)
        self.assertEqual((total, removed), (6, 4))
        kept = self.path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(kept), 2)
        self.assertIn("aegisflow", kept[0])
        self.assertIn("logpulse", kept[1])
        self.assertTrue(list(self.tmp.glob("team_lessons.jsonl.bak_*")))

    def test_missing_file_is_a_noop(self):
        from core.telemetry_hygiene import clean_team_lessons

        self.assertEqual(clean_team_lessons(self.tmp / "nicht_vorhanden.jsonl"), (0, 0))

    def test_real_team_lessons_file_is_already_schema_clean(self):
        """Regressionsschutz: die echte memory/team_lessons.jsonl soll nach diesem Fix
        vollständig dem Schema entsprechen - jede künftige schema-widrige Zeile (z.B. durch
        einen Bug in record_lesson()/_append_event()) muss auffallen."""
        from core.team_memory import TEAM_MEMORY_FILE
        from core.telemetry_hygiene import clean_team_lessons

        if not TEAM_MEMORY_FILE.exists():
            self.skipTest("memory/team_lessons.jsonl existiert in dieser Umgebung nicht")
        total, removed = clean_team_lessons(TEAM_MEMORY_FILE, dry_run=True)
        self.assertEqual(removed, 0, f"{removed} von {total} Zeilen in der echten Datei sind schema-widrig")


if __name__ == "__main__":
    unittest.main()
