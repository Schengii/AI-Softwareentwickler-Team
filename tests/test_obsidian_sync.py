"""
tests/test_obsidian_sync.py – Tests für die Obsidian-Synchronisation und Claude-Gedächtnis-Funktion.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.obsidian_sync import (
    _create_markdown_wrapper,
    get_obsidian_destination,
    sync_project_to_obsidian,
)


class TestObsidianSync(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.vault_path = self.base_path / "ObsidianVault"
        self.project_src = self.base_path / "ProjectRoot"
        self.vault_path.mkdir(parents=True, exist_ok=True)
        self.project_src.mkdir(parents=True, exist_ok=True)

        # Erstelle Test-Quelldateien. Bewusst ".env.example" statt ".env" als generisches
        # Nicht-Markdown-Testfixture: die echte ".env" wird von sync_project_to_obsidian()
        # als Sicherheitssperre hart geblockt (siehe test_env_file_is_never_synced_even_if_
        # explicitly_requested unten), egal was files_to_sync sagt - sie eignet sich damit
        # nicht mehr für Tests des generischen Sync-Mechanismus (Kopie, .md-Wrapper, Diff).
        (self.project_src / ".env.example").write_text("GEMINI_API_KEY=\nDEBUG=true", encoding="utf-8")
        (self.project_src / "README.md").write_text("# Test Project\nDokumentation hier.", encoding="utf-8")
        (self.project_src / ".gitignore").write_text("*.pyc\n__pycache__/", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_get_obsidian_destination(self):
        dest = get_obsidian_destination(
            vault_path=self.vault_path,
            target_dir="02 Areas/Lernprojekte/AI-Team",
        )
        expected = self.vault_path / "02 Areas" / "Lernprojekte" / "AI-Team"
        self.assertEqual(dest, expected)

    def test_create_markdown_wrapper(self):
        content = "FOO=BAR\nBAZ=123"
        wrapper = _create_markdown_wrapper(".env.example", content, "2026-09-03 21:00:00")
        self.assertIn("type: project-backup", wrapper)
        self.assertIn("source_file: .env.example", wrapper)
        self.assertIn("```ini", wrapper)
        self.assertIn("FOO=BAR", wrapper)

    def test_sync_project_to_obsidian_initial_run(self):
        target_sub = "02 Areas/Lernprojekte/AI-Team"
        target_dest = self.vault_path / Path(target_sub)

        with patch("core.obsidian_sync.BASE_DIR", str(self.project_src)):
            result = sync_project_to_obsidian(
                vault_path=self.vault_path,
                target_dir=target_sub,
                files_to_sync=[".env.example", "README.md", ".gitignore"],
            )

        self.assertTrue(result.success)
        self.assertEqual(len(result.synced_files), 3)
        self.assertIn(".env.example", result.synced_files)
        self.assertIn("README.md", result.synced_files)
        self.assertIn(".gitignore", result.synced_files)

        # Prüfe ob Rohdateien existieren
        self.assertTrue((target_dest / ".env.example").exists())
        self.assertTrue((target_dest / "README.md").exists())
        self.assertTrue((target_dest / ".gitignore").exists())

        # Prüfe ob Markdown-Wrapper für Nicht-MD-Dateien existieren
        self.assertTrue((target_dest / ".env.example.md").exists())
        self.assertTrue((target_dest / ".gitignore.md").exists())

        # Prüfe ob Index-Notiz existiert
        index_file = target_dest / "00_PROJEKT_GEDAECHTNIS.md"
        self.assertTrue(index_file.exists())
        index_content = index_file.read_text(encoding="utf-8")
        self.assertIn("[[.env.example.md]]", index_content)
        self.assertIn("[[README.md]]", index_content)
        self.assertIn("Claude-Gedächtnis", index_content)

    def test_sync_skips_unchanged_files(self):
        target_sub = "02 Areas/Lernprojekte/AI-Team"

        with patch("core.obsidian_sync.BASE_DIR", str(self.project_src)):
            # Erster Sync
            res1 = sync_project_to_obsidian(
                vault_path=self.vault_path,
                target_dir=target_sub,
                files_to_sync=[".env.example", "README.md"],
            )
            self.assertEqual(len(res1.synced_files), 2)

            # Zweiter Sync ohne Änderungen
            res2 = sync_project_to_obsidian(
                vault_path=self.vault_path,
                target_dir=target_sub,
                files_to_sync=[".env.example", "README.md"],
            )
            self.assertEqual(len(res2.synced_files), 0)
            self.assertEqual(len(res2.skipped_files), 2)

            # Datei ändern
            (self.project_src / ".env.example").write_text("NEW_KEY=abc", encoding="utf-8")
            res3 = sync_project_to_obsidian(
                vault_path=self.vault_path,
                target_dir=target_sub,
                files_to_sync=[".env.example", "README.md"],
            )
            self.assertEqual(res3.synced_files, [".env.example"])
            self.assertEqual(res3.skipped_files, ["README.md"])

    def test_force_sync_updates_all(self):
        target_sub = "02 Areas/Lernprojekte/AI-Team"

        with patch("core.obsidian_sync.BASE_DIR", str(self.project_src)):
            sync_project_to_obsidian(
                vault_path=self.vault_path,
                target_dir=target_sub,
                files_to_sync=[".env.example", "README.md"],
            )

            res_force = sync_project_to_obsidian(
                vault_path=self.vault_path,
                target_dir=target_sub,
                files_to_sync=[".env.example", "README.md"],
                force=True,
            )
            self.assertEqual(len(res_force.synced_files), 2)

    def test_env_file_is_never_synced_even_if_explicitly_requested(self):
        """
        Realer Fund: OBSIDIAN_SYNC_FILES enthielt ".env" als Standardwert - der Sync kopiert
        Dateien unredigiert, dadurch landeten ECHTE, aktive API-Keys im Vault, außerhalb des
        durch dieses Repo kontrollierten .gitignore-Schutzes (ein Obsidian-Vault wird
        typischerweise über einen eigenen, nicht kontrollierten Dienst verteilt). Dieser Test
        stellt sicher, dass ".env" NIE synchronisiert wird - auch dann nicht, wenn es (z.B.
        durch eine künftige Fehlkonfiguration) explizit in files_to_sync auftaucht.
        """
        (self.project_src / ".env").write_text("GEMINI_API_KEY=echter-geheimer-key", encoding="utf-8")
        target_sub = "02 Areas/Lernprojekte/AI-Team"
        target_dest = self.vault_path / Path(target_sub)

        with patch("core.obsidian_sync.BASE_DIR", str(self.project_src)):
            result = sync_project_to_obsidian(
                vault_path=self.vault_path,
                target_dir=target_sub,
                files_to_sync=[".env", "README.md"],
            )

        self.assertNotIn(".env", result.synced_files)
        self.assertIn(".env", result.failed_files)
        self.assertFalse((target_dest / ".env").exists())
        self.assertFalse((target_dest / ".env.md").exists())
        # README.md (kein Secret) muss trotzdem normal synchronisiert werden.
        self.assertIn("README.md", result.synced_files)


if __name__ == "__main__":
    unittest.main()
