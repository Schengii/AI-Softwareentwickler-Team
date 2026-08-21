"""
tests/test_adr.py – Testet core/adr.py (Architecture Decision Records)

Realer struktureller Fund: agents/architect_agent.py sprach in seinem eigenen Ausgabeformat
schon immer von "ADRs", schrieb sie aber NIE als echte, persistente Datei - jede Entscheidung
stand nur im Antworttext EINES Laufs und war beim nächsten Lauf bereits wieder vergessen.
core/project_constitution.py hält das WAS fest (Tech-Stack), aber nicht das WARUM.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import core.adr as adr_module
from core.adr import format_adr_summary_for_context, list_adrs, next_adr_number, write_adr


class TestWriteAndListAdrs(unittest.TestCase):
    def setUp(self):
        self.project_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)

    def test_write_adr_creates_numbered_markdown_file_in_nygard_format(self):
        path = write_adr(
            self.project_dir, title="PostgreSQL statt MongoDB",
            context="Nutzerdaten brauchen relationale Integrität.",
            decision="PostgreSQL, da ACID-Transaktionen für Bestellungen nötig sind.",
            consequences="Erfordert ein Schema-Migrationswerkzeug.",
        )
        self.assertTrue(path.exists())
        self.assertEqual(path.name, "0001-postgresql-statt-mongodb.md")

        content = path.read_text(encoding="utf-8")
        self.assertIn("# PostgreSQL statt MongoDB", content)
        self.assertIn("Status: Angenommen", content)
        self.assertIn("## Kontext", content)
        self.assertIn("## Entscheidung", content)
        self.assertIn("## Konsequenzen", content)
        self.assertIn("ACID-Transaktionen", content)

    def test_second_adr_gets_the_next_sequential_number(self):
        write_adr(self.project_dir, "Erste Entscheidung", "K", "E", "K")
        second = write_adr(self.project_dir, "Zweite Entscheidung", "K", "E", "K")
        self.assertTrue(second.name.startswith("0002-"))

    def test_next_adr_number_is_one_for_a_fresh_project(self):
        self.assertEqual(next_adr_number(self.project_dir), 1)

    def test_list_adrs_is_empty_without_a_docs_adr_directory(self):
        self.assertEqual(list_adrs(self.project_dir), [])

    def test_list_adrs_reads_title_and_status_from_file_content(self):
        write_adr(self.project_dir, "REST statt GraphQL", "K", "E", "K", status="Vorgeschlagen")
        records = list_adrs(self.project_dir)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].number, 1)
        self.assertEqual(records[0].title, "REST statt GraphQL")
        self.assertEqual(records[0].status, "Vorgeschlagen")

    def test_list_adrs_ignores_files_not_matching_the_naming_scheme(self):
        adr_dir = self.project_dir / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "README.md").write_text("kein ADR", encoding="utf-8")
        self.assertEqual(list_adrs(self.project_dir), [])

    def test_malformed_adr_file_does_not_crash_listing(self):
        adr_dir = self.project_dir / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0001-kaputt.md").write_text("", encoding="utf-8")
        records = list_adrs(self.project_dir)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].status, "unbekannt")


class TestAdrContextSummary(unittest.TestCase):
    def setUp(self):
        self.project_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)

    def test_empty_project_yields_no_context_noise(self):
        self.assertEqual(format_adr_summary_for_context(self.project_dir), "")

    def test_summary_lists_number_status_and_title(self):
        write_adr(self.project_dir, "PostgreSQL statt MongoDB", "K", "E", "K")
        summary = format_adr_summary_for_context(self.project_dir)
        self.assertIn("ADR-0001", summary)
        self.assertIn("Angenommen", summary)
        self.assertIn("PostgreSQL statt MongoDB", summary)

    def test_summary_caps_at_max_adrs_and_notes_omission(self):
        with patch.object(adr_module, "MAX_ADRS_IN_CONTEXT", 2):
            for i in range(5):
                write_adr(self.project_dir, f"Entscheidung {i}", "K", "E", "K")
            summary = format_adr_summary_for_context(self.project_dir)

        self.assertIn("ADR-0004", summary)  # neueste zwei bleiben drin
        self.assertIn("ADR-0005", summary)
        self.assertNotIn("ADR-0001", summary)  # älteste fällt raus
        self.assertIn("ausgelassen", summary)


if __name__ == "__main__":
    unittest.main()
