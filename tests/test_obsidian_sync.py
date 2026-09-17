"""
tests/test_obsidian_sync.py – Tests für die Obsidian-Synchronisation und Claude-Gedächtnis-Funktion.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import core.backlog_store as backlog_store_module
from core.backlog_store import get_ticket
from core.obsidian_sync import (
    ObsidianSyncResult,
    _create_markdown_wrapper,
    get_obsidian_destination,
    record_sync_health_ticket,
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

    def test_sync_with_subdirectories_and_learnings(self):
        target_sub = "02 Areas/Lernprojekte/AI-Team"
        target_dest = self.vault_path / Path(target_sub)

        # Unterverzeichnis-Datei anlegen
        (self.project_src / "skills" / "ai-dev-team").mkdir(parents=True, exist_ok=True)
        (self.project_src / "skills" / "ai-dev-team" / "SKILL.md").write_text("# Skill Spec\nContent", encoding="utf-8")

        # Team-Lessons JSONL anlegen
        (self.project_src / "memory").mkdir(parents=True, exist_ok=True)
        (self.project_src / "memory" / "team_lessons.jsonl").write_text(
            '{"timestamp": "2026-09-17T09:00:00", "project_slug": "test_proj", "category": "root_cause_analysis", "detail": "Test Root Cause", "resolution": "Fix applied"}\n',
            encoding="utf-8",
        )

        with patch("core.obsidian_sync.BASE_DIR", str(self.project_src)):
            result = sync_project_to_obsidian(
                vault_path=self.vault_path,
                target_dir=target_sub,
                files_to_sync=["skills/ai-dev-team/SKILL.md", "README.md"],
            )

        self.assertTrue(result.success)
        self.assertTrue((target_dest / "skills" / "ai-dev-team" / "SKILL.md").exists())
        self.assertTrue((target_dest / "01_TEAM_LEARNINGS.md").exists())
        self.assertTrue((target_dest / "00_PROJEKT_GEDAECHTNIS.md").exists())

        learnings_content = (target_dest / "01_TEAM_LEARNINGS.md").read_text(encoding="utf-8")
        self.assertIn("Test Root Cause", learnings_content)
        self.assertIn("Root-Cause-Analysen", learnings_content)

        index_content = (target_dest / "00_PROJEKT_GEDAECHTNIS.md").read_text(encoding="utf-8")
        self.assertIn("[[01_TEAM_LEARNINGS.md]]", index_content)
        self.assertIn("[[skills/ai-dev-team/SKILL.md]]", index_content)


class TestRecordSyncHealthTicket(unittest.TestCase):
    """
    KI-Team-Zustandsbericht 2026-09-08, echter Fund: interface/cli.py verwarf einen Obsidian-
    Sync-Fehlschlag bisher NUR auf der Konsole - unsichtbar für jeden autonomen Lauf und ohne
    jede Spur, sobald die naechste Konsolenzeile den Hinweis verdraengt hat. record_sync_health_
    ticket() macht einen Fehlschlag als Backlog-Ticket sichtbar und schliesst es mechanisch
    wieder, sobald ein spaeterer Sync erfolgreich war.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self._patcher = patch.object(backlog_store_module, "BACKLOG_FILE", Path(self.temp_dir.name) / "backlog.json")
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_failed_result_opens_ticket(self):
        result = ObsidianSyncResult(success=False, target_dir=Path("x"), failed_files={"README.md": "Permission denied"})

        record_sync_health_ticket(result)

        ticket = get_ticket("obsidian-sync-health")
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket.status, "blocked")
        self.assertIn("Permission denied", ticket.detail)

    def test_exception_opens_ticket(self):
        record_sync_health_ticket(None, exception=RuntimeError("Vault-Pfad nicht erreichbar"))

        ticket = get_ticket("obsidian-sync-health")
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket.status, "blocked")
        self.assertIn("Vault-Pfad nicht erreichbar", ticket.detail)

    def test_successful_result_after_failure_closes_ticket(self):
        record_sync_health_ticket(None, exception=RuntimeError("Vault-Pfad nicht erreichbar"))

        record_sync_health_ticket(ObsidianSyncResult(success=True, target_dir=Path("x"), synced_files=["README.md"]))

        ticket = get_ticket("obsidian-sync-health")
        self.assertEqual(ticket.status, "done")

    def test_successful_result_without_prior_failure_opens_no_ticket(self):
        record_sync_health_ticket(ObsidianSyncResult(success=True, target_dir=Path("x"), synced_files=["README.md"]))

        self.assertIsNone(get_ticket("obsidian-sync-health"))

    def test_none_result_without_exception_is_a_noop(self):
        """auto_sync_if_enabled() gibt None zurueck, wenn OBSIDIAN_AUTO_SYNC deaktiviert ist -
        kein Fehlschlag, kein Ticket."""
        record_sync_health_ticket(None)

        self.assertIsNone(get_ticket("obsidian-sync-health"))


if __name__ == "__main__":
    unittest.main()
