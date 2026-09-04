"""
tests/test_workspace_project_name_canonicalization.py – Testet core/workspace.py.
WorkspaceManager.get_project_dir()'s Namens-Kanonisierung.

Realer Fund (Team-Retrospektive, webhookshield-Projekt, 2026-09-03): ein Auftrag "WebhookShield
reparieren" legte `workspace/webhookshield/` an, obwohl der eigentliche Code bereits unter
`workspace/webhook_shield/` (aus einem früheren Lauf mit Leerzeichen im Namen) lag - die alte
Normalisierung wandelte zwar Leerzeichen in "_", unterschied aber nicht Groß-/Kleinschreibung
und prüfte nie gegen bereits vorhandene Ordner. Der Agent fand ein leeres Verzeichnis, hielt es
für ein kaputtes Projekt und der Lauf endete fast folgenlos (nur README.md + requirements.txt).
"""

import shutil
import tempfile
import unittest

from core.workspace import WorkspaceManager


class TestProjectNameCanonicalization(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = WorkspaceManager(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_reuses_existing_non_empty_dir_with_different_casing_and_separators(self):
        existing = self.workspace.base_dir / "webhook_shield"
        existing.mkdir()
        (existing / "README.md").write_text("# WebhookShield\n", encoding="utf-8")

        result = self.workspace.get_project_dir("WebhookShield")

        self.assertEqual(result, existing)

    def test_reuses_existing_dir_when_name_has_spaces(self):
        existing = self.workspace.base_dir / "webhookshield"
        existing.mkdir()
        (existing / "app").mkdir()

        result = self.workspace.get_project_dir("Webhook Shield")

        self.assertEqual(result, existing)

    def test_does_not_reuse_empty_existing_dir(self):
        """Ein leerer gleichnamiger Ordner bringt keinen Vorteil - lieber der reguläre,
        vorhersagbare clean_name-Pfad als ein zufällig zuerst gefundener leerer Zwilling."""
        empty_existing = self.workspace.base_dir / "webhook_shield"
        empty_existing.mkdir()

        result = self.workspace.get_project_dir("WebhookShield")

        self.assertNotEqual(result, empty_existing)
        self.assertEqual(result.name, "webhookshield")

    def test_first_time_project_creates_new_dir(self):
        result = self.workspace.get_project_dir("BrandNewProject")
        self.assertTrue(result.exists())
        self.assertEqual(result.name, "brandnewproject")

    def test_unrelated_existing_projects_are_not_reused(self):
        unrelated = self.workspace.base_dir / "totally_different_project"
        unrelated.mkdir()
        (unrelated / "main.py").write_text("print('hi')\n", encoding="utf-8")

        result = self.workspace.get_project_dir("WebhookShield")

        self.assertNotEqual(result, unrelated)
        self.assertEqual(result.name, "webhookshield")

    def test_exact_existing_dir_is_reused_via_normal_path_match(self):
        existing = self.workspace.base_dir / "myproject"
        existing.mkdir()
        result = self.workspace.get_project_dir("MyProject")
        self.assertEqual(result, existing)


if __name__ == "__main__":
    unittest.main()
