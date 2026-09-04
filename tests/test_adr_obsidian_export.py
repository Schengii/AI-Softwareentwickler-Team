"""
tests/test_adr_obsidian_export.py – Tests für den automatischen ADR-Export in den Obsidian Zettelkasten.
"""

import tempfile
import unittest
from pathlib import Path

from core.adr import export_adr_to_obsidian, write_adr


class TestAdrObsidianExport(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.temp_dir.name) / "my_project"
        self.project_dir.mkdir()
        self.vault_dir = Path(self.temp_dir.name) / "my_vault"
        self.vault_dir.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_export_adr_to_obsidian_direct(self):
        res = export_adr_to_obsidian(
            project_dir=self.project_dir,
            title="SQLite für Cache",
            context="Wir brauchen schnelle lokale Persistenz.",
            decision="SQLite wird als lokaler Cache genutzt.",
            consequences="Kein externer Server nötig.",
            status="Angenommen",
            vault_path=self.vault_dir,
        )

        self.assertIsNotNone(res)
        self.assertTrue(res.exists())
        self.assertTrue(res.name.startswith("ADR - my_project - SQLite für Cache.md"))

        content = res.read_text(encoding="utf-8")
        self.assertIn("type: permanent-note", content)
        self.assertIn("category: adr", content)
        self.assertIn("SQLite wird als lokaler Cache genutzt.", content)
        self.assertIn("[[my_project]]", content)

    def test_write_adr_triggers_export(self):
        # Rufe write_adr auf
        adr_file = write_adr(
            project_dir=self.project_dir,
            title="REST statt GraphQL",
            context="Einfache CRUD-Operationen reichen aus.",
            decision="REST-API mit FastAPI.",
            consequences="Schnelle Entwicklung, breite Tooling-Unterstützung.",
        )
        self.assertTrue(adr_file.exists())
        self.assertIn("0001-rest-statt-graphql.md", str(adr_file).lower().replace("\\", "/"))


if __name__ == "__main__":
    unittest.main()
