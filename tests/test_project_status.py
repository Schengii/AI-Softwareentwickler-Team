"""
tests/test_project_status.py – Testet core/project_status.py (Projekt-Kontinuität)

Realer Fund: memory/conversation_history.py ist sitzungsgebunden - startet der Nutzer eine
neue Sitzung, ist jeglicher Kontext über ein Projekt weg, selbst bei erneutem /load
desselben Projekts. core/project_status.py schreibt eine persistente, projektgebundene
Lauf-Historie direkt im Projektverzeichnis.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import core.backlog_store as backlog_store
import core.project_status as project_status
from core.project_status import (
    FULL_LOG_FILENAME,
    count_consecutive_failed_runs,
    format_context_for_agents,
    generate_project_state_md,
    has_open_blocker_ticket,
    has_repeated_lint_finding,
    read_status,
    record_run,
)


class TestProjectStatus(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_read_status_returns_empty_list_when_no_history_exists(self):
        self.assertEqual(read_status(self.temp_dir), [])

    def test_record_run_then_read_status_roundtrip(self):
        record_run(self.temp_dir, "Health-Check implementiert", verification_ok=True,
                   budget_aborted=False, files_written_count=2)
        history = read_status(self.temp_dir)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["task_summary"], "Health-Check implementiert")
        self.assertTrue(history[0]["verification_ok"])

    def test_newest_run_appears_first(self):
        record_run(self.temp_dir, "Erster Lauf", verification_ok=True, budget_aborted=False, files_written_count=1)
        record_run(self.temp_dir, "Zweiter Lauf", verification_ok=False, budget_aborted=False, files_written_count=1)
        history = read_status(self.temp_dir)
        self.assertEqual(history[0]["task_summary"], "Zweiter Lauf")
        self.assertEqual(history[1]["task_summary"], "Erster Lauf")

    def test_history_is_capped_oldest_evicted(self):
        for i in range(15):
            record_run(self.temp_dir, f"Lauf {i}", verification_ok=True, budget_aborted=False, files_written_count=1)
        history = read_status(self.temp_dir)
        self.assertEqual(len(history), 10)
        self.assertEqual(history[0]["task_summary"], "Lauf 14")  # neuester
        self.assertEqual(history[-1]["task_summary"], "Lauf 5")  # ältester verbliebener

    def test_format_context_is_empty_for_fresh_project(self):
        self.assertEqual(format_context_for_agents(self.temp_dir), "")

    def test_format_context_includes_recent_runs_with_status_icons(self):
        record_run(self.temp_dir, "Erfolgreich verifiziert", verification_ok=True, budget_aborted=False, files_written_count=3)
        record_run(self.temp_dir, "Budget erreicht", verification_ok=False, budget_aborted=True, files_written_count=1)
        record_run(self.temp_dir, "Tests fehlgeschlagen", verification_ok=False, budget_aborted=False, files_written_count=2)

        context = format_context_for_agents(self.temp_dir)

        self.assertIn("Erfolgreich verifiziert", context)
        self.assertIn("Budget erreicht", context)
        self.assertIn("Tests fehlgeschlagen", context)
        self.assertIn("✅", context)
        self.assertIn("🚫", context)
        self.assertIn("⚠️", context)

    def test_format_context_respects_max_entries(self):
        for i in range(5):
            record_run(self.temp_dir, f"Lauf {i}", verification_ok=True, budget_aborted=False, files_written_count=1)
        context = format_context_for_agents(self.temp_dir, max_entries=2)
        self.assertIn("Lauf 4", context)
        self.assertIn("Lauf 3", context)
        self.assertNotIn("Lauf 2", context)

    def test_corrupted_status_file_does_not_crash(self):
        (Path(self.temp_dir) / ".ai_team_status.json").write_text("{not valid json", encoding="utf-8")
        self.assertEqual(read_status(self.temp_dir), [])
        self.assertEqual(format_context_for_agents(self.temp_dir), "")

    def test_cancelled_run_gets_its_own_icon_distinct_from_budget_aborted(self):
        """Ein manuell abgebrochener Lauf darf nicht wie ein Budget-Abbruch aussehen -
        der Mensch hat den Lauf bewusst gestoppt, das ist ein anderer Grund."""
        record_run(self.temp_dir, "Manuell gestoppt", verification_ok=False,
                   budget_aborted=False, cancelled=True, files_written_count=1)
        history = read_status(self.temp_dir)
        self.assertTrue(history[0]["cancelled"])

        context = format_context_for_agents(self.temp_dir)
        self.assertIn("⏹️", context)
        self.assertNotIn("🚫", context)

    def test_cancelled_defaults_to_false_for_existing_callers(self):
        """record_run() ohne explizites cancelled= (bestehende Aufrufer) bleibt unverändert."""
        record_run(self.temp_dir, "Alter Aufrufer", verification_ok=True,
                   budget_aborted=False, files_written_count=1)
        self.assertFalse(read_status(self.temp_dir)[0]["cancelled"])

    def test_count_consecutive_failed_runs_is_zero_for_fresh_project(self):
        self.assertEqual(count_consecutive_failed_runs(self.temp_dir), 0)

    def test_count_consecutive_failed_runs_counts_from_the_newest_backwards(self):
        record_run(self.temp_dir, "Lauf 1", verification_ok=False, budget_aborted=False, files_written_count=1)
        record_run(self.temp_dir, "Lauf 2", verification_ok=False, budget_aborted=True, files_written_count=1)
        record_run(self.temp_dir, "Lauf 3", verification_ok=False, budget_aborted=False, files_written_count=1)
        self.assertEqual(count_consecutive_failed_runs(self.temp_dir), 3)

    def test_count_consecutive_failed_runs_stops_at_the_first_success(self):
        record_run(self.temp_dir, "Alter Erfolg", verification_ok=True, budget_aborted=False, files_written_count=1)
        record_run(self.temp_dir, "Fehlschlag 1", verification_ok=False, budget_aborted=False, files_written_count=1)
        record_run(self.temp_dir, "Fehlschlag 2", verification_ok=False, budget_aborted=False, files_written_count=1)
        self.assertEqual(count_consecutive_failed_runs(self.temp_dir), 2)

    def test_count_consecutive_failed_runs_stops_at_a_manual_cancellation(self):
        """Ein bewusster menschlicher Stopp ist kein Qualitätsurteil über die Aufgabe/das
        Team und darf die Fehlschlags-Zählung nicht fortsetzen."""
        record_run(self.temp_dir, "Manuell gestoppt", verification_ok=False,
                   budget_aborted=False, cancelled=True, files_written_count=1)
        record_run(self.temp_dir, "Fehlschlag danach", verification_ok=False, budget_aborted=False, files_written_count=1)
        self.assertEqual(count_consecutive_failed_runs(self.temp_dir), 1)

    def test_record_run_appends_to_full_log(self):
        record_run(self.temp_dir, "Erster Lauf", verification_ok=False, budget_aborted=False,
                   files_written_count=1, verification_summary="- 🎨 ruff: 1 Lint-Fund")
        log_path = Path(self.temp_dir) / FULL_LOG_FILENAME
        self.assertTrue(log_path.exists())
        content = log_path.read_text(encoding="utf-8")
        self.assertIn("Erster Lauf", content)
        self.assertIn("ruff", content)

    def test_full_log_is_rotated_when_over_threshold_oldest_dropped_newest_kept(self):
        # MAX_FULL_LOG_BYTES klein patchen, damit der Test nicht wirklich MBs schreiben muss.
        original_max = project_status.MAX_FULL_LOG_BYTES
        project_status.MAX_FULL_LOG_BYTES = 500
        try:
            for i in range(30):
                record_run(
                    self.temp_dir, f"Lauf Nr. {i}", verification_ok=False, budget_aborted=False,
                    files_written_count=1,
                    verification_summary=f"- 🎨 ruff: Lint-Fund in Lauf {i} " + ("x" * 20),
                )
            log_path = Path(self.temp_dir) / FULL_LOG_FILENAME
            size = log_path.stat().st_size
            self.assertLessEqual(size, project_status.MAX_FULL_LOG_BYTES)

            content = log_path.read_text(encoding="utf-8")
            # Neueste Einträge müssen erhalten bleiben ...
            self.assertIn("Lauf Nr. 29", content)
            # ... die ältesten dagegen wurden verworfen.
            self.assertNotIn("Lauf Nr. 0\n", content)
        finally:
            project_status.MAX_FULL_LOG_BYTES = original_max

    def test_has_repeated_lint_finding_true_for_identical_signature_across_streak(self):
        # Realer Fund (Team-Retrospektive, omnichat-Projekt): dasselbe ruff-F841 blieb über
        # mehrere volle Läufe unverändert bestehen, ohne dass has_repeated_failure() je
        # griff (Lint beeinflusst verification_ok nicht).
        sig = ["ruff:tests/test_chat_flow.py:F841"]
        record_run(self.temp_dir, "Lauf 1", verification_ok=False, budget_aborted=False,
                   files_written_count=1, lint_signature=sig)
        record_run(self.temp_dir, "Lauf 2", verification_ok=False, budget_aborted=False,
                   files_written_count=1, lint_signature=sig)
        self.assertTrue(has_repeated_lint_finding(self.temp_dir))

    def test_has_repeated_lint_finding_false_when_signature_changes(self):
        record_run(self.temp_dir, "Lauf 1", verification_ok=False, budget_aborted=False,
                   files_written_count=1, lint_signature=["ruff:a.py:F841"])
        record_run(self.temp_dir, "Lauf 2", verification_ok=False, budget_aborted=False,
                   files_written_count=1, lint_signature=["ruff:b.py:UP007"])
        self.assertFalse(has_repeated_lint_finding(self.temp_dir))

    def test_has_repeated_lint_finding_false_when_no_lint_findings(self):
        record_run(self.temp_dir, "Lauf 1", verification_ok=True, budget_aborted=False, files_written_count=1)
        record_run(self.temp_dir, "Lauf 2", verification_ok=True, budget_aborted=False, files_written_count=1)
        self.assertFalse(has_repeated_lint_finding(self.temp_dir))

    def test_record_run_deduplicates_lint_signature_before_truncating(self):
        # Team-Optimierung (Retrospektive 2026-09-04): agents/orchestrator/verification.py
        # liefert einen Eintrag JE FUND-INSTANZ, nicht je distinkter Regel/Datei-Kombination
        # (real beobachtet: 6x "ruff:tests/test_invoices.py:DTZ001" für sechs betroffene
        # Zeilen derselben Regel). Ohne vorherige Deduplizierung konnten solche Duplikate den
        # MAX_LINT_SIGNATURE_ITEMS-Schnitt dominieren und andere, distinkte Funde verdrängen.
        sig = ["ruff:tests/test_invoices.py:DTZ001"] * 6 + ["ruff:app/main.py:B008"]
        record_run(self.temp_dir, "Lauf 1", verification_ok=False, budget_aborted=False,
                   files_written_count=1, lint_signature=sig)
        entries = read_status(self.temp_dir)
        stored = entries[0]["lint_signature"]
        self.assertEqual(len(stored), 2)
        self.assertEqual(set(stored), {"ruff:tests/test_invoices.py:DTZ001", "ruff:app/main.py:B008"})

    def test_has_repeated_lint_finding_ignores_signature_order(self):
        record_run(self.temp_dir, "Lauf 1", verification_ok=False, budget_aborted=False,
                   files_written_count=1, lint_signature=["ruff:a.py:F841", "ruff:b.py:UP007"])
        record_run(self.temp_dir, "Lauf 2", verification_ok=False, budget_aborted=False,
                   files_written_count=1, lint_signature=["ruff:b.py:UP007", "ruff:a.py:F841"])
        self.assertTrue(has_repeated_lint_finding(self.temp_dir))


class TestOpenBlockerTicketOverridesEinsatzbereitStatus(unittest.TestCase):
    """
    Realer Fund (mockforge-Projekt, Team-Bestandsaufnahme 2026-09-03): PROJECT_STATE.md wies
    "✅ Vollständig verifiziert & einsatzbereit" aus, obwohl ein Backlog-Ticket zu einem
    ungelösten kritischen Governance-Befund (ProxyMiddleware-Deadlock-Risiko) für exakt dieses
    Projekt offen ("blocked") war - verification_ok und der offene kritische Befund waren
    komplett entkoppelt. Diese Tests decken die Kopplung ab.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_slug = Path(self.temp_dir).name
        self._backlog_patcher = patch.object(
            backlog_store, "BACKLOG_FILE", Path(self.temp_dir).parent / f"{self.project_slug}-backlog.json",
        )
        self._backlog_patcher.start()
        self.addCleanup(self._backlog_patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_no_open_ticket_means_no_blocker(self):
        self.assertFalse(has_open_blocker_ticket(self.temp_dir))

    def test_open_governance_ticket_is_detected_as_blocker(self):
        backlog_store.upsert_ticket(
            ticket_id=f"unresolved-governance-critical-{self.project_slug}",
            title="Ungelöster kritischer Governance-Befund", source="orchestrator",
            status="blocked", project_slug=self.project_slug, detail="DB-Session pro Request",
        )
        self.assertTrue(has_open_blocker_ticket(self.temp_dir))

    def test_ticket_for_a_different_project_is_not_a_blocker(self):
        backlog_store.upsert_ticket(
            ticket_id="unresolved-governance-critical-other-project",
            title="Anderes Projekt", source="orchestrator",
            status="blocked", project_slug="other-project", detail="...",
        )
        self.assertFalse(has_open_blocker_ticket(self.temp_dir))

    def test_resolved_ticket_no_longer_blocks(self):
        ticket_id = f"unresolved-governance-critical-{self.project_slug}"
        backlog_store.upsert_ticket(
            ticket_id=ticket_id, title="...", source="orchestrator",
            status="blocked", project_slug=self.project_slug, detail="...",
        )
        backlog_store.upsert_ticket(
            ticket_id=ticket_id, title="...", source="orchestrator",
            status="done", project_slug=self.project_slug, detail="behoben",
        )
        self.assertFalse(has_open_blocker_ticket(self.temp_dir))

    def test_state_md_shows_not_einsatzbereit_despite_passing_verification(self):
        backlog_store.upsert_ticket(
            ticket_id=f"unresolved-governance-critical-{self.project_slug}",
            title="Ungelöster kritischer Governance-Befund", source="orchestrator",
            status="blocked", project_slug=self.project_slug, detail="DB-Session pro Request",
        )
        state_md = generate_project_state_md(self.temp_dir, verification_ok=True)
        self.assertIn("NICHT einsatzbereit", state_md)
        self.assertNotIn("Vollständig verifiziert & einsatzbereit", state_md)
        self.assertIn("Offener kritischer Befund", state_md)

    def test_state_md_shows_einsatzbereit_when_no_blocker(self):
        state_md = generate_project_state_md(self.temp_dir, verification_ok=True)
        self.assertIn("Vollständig verifiziert & einsatzbereit", state_md)

    def test_ticket_auto_closes_when_completeness_check_now_passes(self):
        # Team-Optimierung (Retrospektive, zeiterfassung_app-Lauf): das Ticket wurde bisher NUR
        # über einen erneuten Governance-Reviewer-Recheck geschlossen (agents/orchestrator/
        # verification.py._run_governance_fix_loop). Wird das zugrunde liegende Problem
        # stattdessen auf einem anderen Weg behoben (hier simuliert: die fehlende Datei existiert
        # inzwischen), muss der nächste Checkpoint mit bestandener Testsuite das Ticket
        # eigenständig per statischem Vollständigkeits-Check schließen, statt für immer "blocked"
        # zu bleiben.
        ticket_id = f"unresolved-governance-critical-{self.project_slug}"
        backlog_store.upsert_ticket(
            ticket_id=ticket_id, title="Ungelöster kritischer Governance-Befund", source="orchestrator",
            status="blocked", project_slug=self.project_slug, detail="app/models.py fehlt",
        )
        # Jetzt existiert echter, vollständiger Code ohne offene Vollständigkeits-Funde.
        Path(self.temp_dir, "main.py").write_text("print('hallo')\n", encoding="utf-8")

        state_md = generate_project_state_md(self.temp_dir, verification_ok=True)

        self.assertIn("Vollständig verifiziert & einsatzbereit", state_md)
        self.assertFalse(has_open_blocker_ticket(self.temp_dir, verification_ok=True))
        closed = backlog_store.get_ticket(ticket_id)
        self.assertEqual(closed.status, "done")

    def test_ticket_stays_open_when_completeness_check_still_fails(self):
        ticket_id = f"unresolved-governance-critical-{self.project_slug}"
        backlog_store.upsert_ticket(
            ticket_id=ticket_id, title="...", source="orchestrator",
            status="blocked", project_slug=self.project_slug, detail="app/models.py fehlt",
        )
        # Importiert ein lokales Modul, das nach wie vor nicht existiert - derselbe Befund besteht weiter.
        Path(self.temp_dir, "main.py").write_text("from . import models\n", encoding="utf-8")

        state_md = generate_project_state_md(self.temp_dir, verification_ok=True)

        self.assertIn("NICHT einsatzbereit", state_md)
        self.assertTrue(has_open_blocker_ticket(self.temp_dir, verification_ok=True))

    def test_ticket_not_auto_closed_when_verification_did_not_pass(self):
        # Ein bestandener Vollständigkeits-Check allein reicht nicht - solange die eigentliche
        # Testsuite NICHT grün ist (verification_ok=False), bleibt das Ticket offen.
        ticket_id = f"unresolved-governance-critical-{self.project_slug}"
        backlog_store.upsert_ticket(
            ticket_id=ticket_id, title="...", source="orchestrator",
            status="blocked", project_slug=self.project_slug, detail="...",
        )
        Path(self.temp_dir, "main.py").write_text("print('hallo')\n", encoding="utf-8")

        self.assertTrue(has_open_blocker_ticket(self.temp_dir, verification_ok=False))


if __name__ == "__main__":
    unittest.main()
