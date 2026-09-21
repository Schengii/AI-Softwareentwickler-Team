"""
tests/test_backlog_store.py – Testet core/backlog_store.py (persistenter Backlog/Kanban-
Zustand über CLI/Dashboard/Issue-Watcher hinweg)
"""

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import core.backlog_store as backlog_store


class TestBacklogStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.file_path = Path(self.temp_dir) / "backlog.json"
        self._patcher = patch.object(backlog_store, "BACKLOG_FILE", self.file_path)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_list_tickets_is_empty_without_a_file(self):
        self.assertEqual(backlog_store.list_tickets(), [])

    def test_upsert_creates_a_new_ticket(self):
        ticket = backlog_store.upsert_ticket("issue-1", "Health-Check bauen", "issue", "in_progress")
        self.assertEqual(ticket.title, "Health-Check bauen")
        self.assertEqual(ticket.created_at, ticket.updated_at)

        tickets = backlog_store.list_tickets()
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0].id, "issue-1")

    def test_upsert_with_same_id_updates_instead_of_duplicating(self):
        backlog_store.upsert_ticket("issue-1", "Health-Check bauen", "issue", "in_progress")
        updated = backlog_store.upsert_ticket(
            "issue-1", "Health-Check bauen", "issue", "review", detail="https://github.com/x/y/pull/1",
        )

        tickets = backlog_store.list_tickets()
        self.assertEqual(len(tickets), 1)  # kein Duplikat
        self.assertEqual(tickets[0].status, "review")
        self.assertEqual(tickets[0].detail, "https://github.com/x/y/pull/1")
        self.assertEqual(updated.created_at, tickets[0].created_at)  # created_at bleibt fix

    def test_list_tickets_filters_by_status(self):
        backlog_store.upsert_ticket("t1", "A", "cli", "done")
        backlog_store.upsert_ticket("t2", "B", "cli", "in_progress")

        in_progress = backlog_store.list_tickets(status="in_progress")
        self.assertEqual([t.id for t in in_progress], ["t2"])

    def test_new_ticket_id_is_prefixed_and_unique(self):
        id_a = backlog_store.new_ticket_id("dashboard")
        id_b = backlog_store.new_ticket_id("dashboard")
        self.assertTrue(id_a.startswith("dashboard-"))
        self.assertNotEqual(id_a, id_b)

    def test_corrupted_file_does_not_crash_list_tickets(self):
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.write_text("not valid json {{{", encoding="utf-8")
        self.assertEqual(backlog_store.list_tickets(), [])

    def test_ticket_count_is_capped_and_keeps_most_recently_updated(self):
        with patch.object(backlog_store, "MAX_TICKETS_KEPT", 2):
            backlog_store.upsert_ticket("t1", "A", "cli", "done")
            backlog_store.upsert_ticket("t2", "B", "cli", "done")
            backlog_store.upsert_ticket("t3", "C", "cli", "done")

        tickets = backlog_store.list_tickets()
        self.assertEqual(len(tickets), 2)
        self.assertNotIn("t1", [t.id for t in tickets])  # ältestes zuerst verdrängt

    def test_new_ticket_defaults_to_medium_priority_and_no_estimate(self):
        ticket = backlog_store.upsert_ticket("t1", "A", "cli", "todo")
        self.assertEqual(ticket.priority, 2)
        self.assertEqual(ticket.estimate, "")

    def test_priority_and_estimate_can_be_set_on_creation(self):
        ticket = backlog_store.upsert_ticket("t1", "A", "cli", "todo", priority=1, estimate="M")
        self.assertEqual(ticket.priority, 1)
        self.assertEqual(ticket.estimate, "M")

    def test_priority_and_estimate_survive_a_status_update_without_being_passed_again(self):
        # Realer struktureller Fund: mehrere Aufrufer (core/issue_watcher.py u.a.) aktualisieren
        # ein Ticket über seinen Lebenszyklus mehrfach, OHNE priority/estimate erneut
        # mitzugeben - ein echter Zahlen-Default hätte eine einmal gesetzte Priorität beim
        # nächsten Update stillschweigend auf "mittel" zurückgesetzt.
        backlog_store.upsert_ticket("t1", "A", "issue", "in_progress", priority=1, estimate="L")
        updated = backlog_store.upsert_ticket("t1", "A", "issue", "review", detail="https://x/y/pull/1")

        self.assertEqual(updated.priority, 1)
        self.assertEqual(updated.estimate, "L")

    def test_priority_and_estimate_can_be_explicitly_changed_on_update(self):
        backlog_store.upsert_ticket("t1", "A", "cli", "todo", priority=1, estimate="L")
        updated = backlog_store.upsert_ticket("t1", "A", "cli", "todo", priority=3, estimate="S")
        self.assertEqual(updated.priority, 3)
        self.assertEqual(updated.estimate, "S")

    def test_project_slug_survives_a_status_update_without_being_passed_again(self):
        # Bugfix (Team-Optimierung, real beobachtet im mockforge-Governance-Retry): anders als
        # priority/estimate/epic/retries hatte project_slug bisher KEINEN Sentinel-Default -
        # core/backlog_worker.py._process_single_ticket() aktualisiert ein Ticket mehrfach über
        # seinen Lebenszyklus (Aufgreifen, Retry-Zähler, finaler Status), der finale
        # Status-Update-Aufruf gab project_slug bisher nicht erneut mit und löschte es dadurch
        # STILLSCHWEIGEND - ein nachfolgender automatischer Retry (core/backlog_worker.py.
        # _governance_retry_pool()) fand dadurch kein project_slug mehr und legte fälschlich
        # ein komplett neues Projekt an, statt das bestehende fortzusetzen.
        backlog_store.upsert_ticket("t1", "A", "orchestrator", "blocked", project_slug="mockforge")
        updated = backlog_store.upsert_ticket("t1", "A", "orchestrator", "blocked", detail="erneut versucht")
        self.assertEqual(updated.project_slug, "mockforge")

    def test_project_slug_can_be_explicitly_cleared_on_update(self):
        backlog_store.upsert_ticket("t1", "A", "orchestrator", "blocked", project_slug="mockforge")
        updated = backlog_store.upsert_ticket("t1", "A", "orchestrator", "blocked", project_slug="")
        self.assertEqual(updated.project_slug, "")

    def test_blocked_reason_set_and_survives_a_detail_only_update(self):
        # P1-3 (ROADMAP_TEMP.md): derselbe None-Sentinel wie priority/estimate/epic/retries -
        # ein Folge-Aufruf, der blocked_reason nicht erneut mitgibt, darf ihn nicht löschen.
        backlog_store.upsert_ticket("t1", "A", "cli", "blocked", blocked_reason="stale")
        updated = backlog_store.upsert_ticket("t1", "A", "cli", "blocked", detail="weiterhin liegengeblieben")
        self.assertEqual(updated.blocked_reason, "stale")

    def test_blocked_reason_is_cleared_when_status_leaves_blocked(self):
        # Kein Sentinel hier: verlässt das Ticket "blocked", ist ein "stale"-Vermerk irreführend
        # und wird IMMER zurückgesetzt, unabhängig vom übergebenen Wert.
        backlog_store.upsert_ticket("t1", "A", "cli", "blocked", blocked_reason="stale")
        updated = backlog_store.upsert_ticket("t1", "A", "cli", "in_progress")
        self.assertEqual(updated.blocked_reason, "")

    def test_new_blocked_ticket_defaults_to_no_blocked_reason(self):
        # Ein bewusst vom Governance-/Verifikations-Loop "blocked" eröffnetes Ticket bekommt
        # KEINEN blocked_reason - core/backlog_worker.py darf es nicht mit einem operationell
        # liegengebliebenen "cli"-Ticket verwechseln (siehe recover_stale_in_progress()).
        ticket = backlog_store.upsert_ticket("t1", "A", "orchestrator", "blocked")
        self.assertEqual(ticket.blocked_reason, "")

    def test_count_by_status(self):
        backlog_store.upsert_ticket("t1", "A", "cli", "in_progress")
        backlog_store.upsert_ticket("t2", "B", "cli", "in_progress")
        backlog_store.upsert_ticket("t3", "C", "cli", "done")

        self.assertEqual(backlog_store.count_by_status("in_progress"), 2)
        self.assertEqual(backlog_store.count_by_status("done"), 1)
        self.assertEqual(backlog_store.count_by_status("blocked"), 0)

    def test_epic_and_depends_on_round_trip(self):
        ticket = backlog_store.upsert_ticket(
            "t1", "Checkout-Button bauen", "cli", "todo", epic="Checkout-Flow", depends_on=["t0"],
        )
        self.assertEqual(ticket.epic, "Checkout-Flow")
        self.assertEqual(ticket.depends_on, ["t0"])

        reloaded = backlog_store.list_tickets()[0]
        self.assertEqual(reloaded.epic, "Checkout-Flow")
        self.assertEqual(reloaded.depends_on, ["t0"])

    def test_epic_and_depends_on_persist_unchanged_across_status_updates(self):
        # Dieselbe "None = unverändert lassen"-Konvention wie priority/estimate (siehe
        # upsert_ticket()-Docstring) - ein reines Status-Update darf Epic/Abhängigkeiten nicht
        # stillschweigend zurücksetzen.
        backlog_store.upsert_ticket("t1", "A", "cli", "todo", epic="Checkout-Flow", depends_on=["t0"])
        updated = backlog_store.upsert_ticket("t1", "A", "cli", "in_progress")
        self.assertEqual(updated.epic, "Checkout-Flow")
        self.assertEqual(updated.depends_on, ["t0"])


class TestTicketReadiness(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.file_path = Path(self.temp_dir) / "backlog.json"
        self._patcher = patch.object(backlog_store, "BACKLOG_FILE", self.file_path)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_ticket_without_dependencies_is_ready(self):
        ticket = backlog_store.upsert_ticket("t1", "A", "cli", "todo")
        ready, blocking = backlog_store.is_ticket_ready(ticket, [])
        self.assertTrue(ready)
        self.assertEqual(blocking, [])

    def test_ticket_is_blocked_while_dependency_not_done(self):
        dep = backlog_store.upsert_ticket("t0", "Vorher", "cli", "in_progress")
        ticket = backlog_store.upsert_ticket("t1", "A", "cli", "todo", depends_on=["t0"])
        ready, blocking = backlog_store.is_ticket_ready(ticket, [dep, ticket])
        self.assertFalse(ready)
        self.assertEqual(blocking, ["t0"])

    def test_ticket_is_ready_once_dependency_is_done(self):
        dep = backlog_store.upsert_ticket("t0", "Vorher", "cli", "done")
        ticket = backlog_store.upsert_ticket("t1", "A", "cli", "todo", depends_on=["t0"])
        ready, blocking = backlog_store.is_ticket_ready(ticket, [dep, ticket])
        self.assertTrue(ready)
        self.assertEqual(blocking, [])

    def test_unknown_dependency_id_counts_as_blocking_not_ready(self):
        ticket = backlog_store.upsert_ticket("t1", "A", "cli", "todo", depends_on=["does-not-exist"])
        ready, blocking = backlog_store.is_ticket_ready(ticket, [ticket])
        self.assertFalse(ready)
        self.assertEqual(blocking, ["does-not-exist"])

    def test_defaults_to_loading_from_disk_when_all_tickets_not_passed(self):
        backlog_store.upsert_ticket("t0", "Vorher", "cli", "done")
        ticket = backlog_store.upsert_ticket("t1", "A", "cli", "todo", depends_on=["t0"])
        ready, blocking = backlog_store.is_ticket_ready(ticket)
        self.assertTrue(ready)

    def test_concurrent_reads_during_writes_never_see_a_torn_file(self):
        """
        Realer Fund (Testflake in tests/test_web_dashboard.py unter `pytest tests/`):
        _save_raw() schrieb bisher direkt per write_text() auf BACKLOG_FILE - ein
        GLEICHZEITIGER list_tickets()-Aufruf konnte die Datei mitten im Schreibvorgang lesen,
        bekam ungültiges/abgeschnittenes JSON und landete im JSONDecodeError-Fallback von
        _load_raw() (STILLSCHWEIGEND "keine Tickets" statt eines Fehlers) - im echten Betrieb
        sogar mit Datenverlustrisiko, falls genau dann auch ein upsert_ticket() draufschrieb
        (siehe _save_raw()-Docstring). Große `detail`-Nutzlast, damit ein Schreibvorgang lange
        genug dauert, um eine Kollision mit den parallelen Lesern realistisch zu machen.

        BEWUSST nur EIN Writer-Thread: mehrere GLEICHZEITIGE Writer haben ein separates,
        hier NICHT behobenes Problem (klassisches Lost-Update ohne Sperre - Writer B liest
        denselben alten Stand wie Writer A, überschreibt dessen Ergebnis beim Zurückschreiben)
        - das würde diesen Test fälschlich als "Torn-Read"-Regression melden, obwohl die
        Ursache eine andere ist. Dieser Test prüft gezielt NUR die behobene Eigenschaft: jeder
        Lesevorgang sieht während eines laufenden Schreibvorgangs entweder den vollständigen
        alten oder den vollständigen neuen Stand, nie eine kaputte/leere Zwischenversion.
        """
        backlog_store.upsert_ticket("seed", "Initiales Ticket", "cli", "todo")
        stop = threading.Event()
        saw_empty = threading.Event()
        big_detail = "x" * 200_000

        def _writer():
            i = 0
            while not stop.is_set():
                backlog_store.upsert_ticket(f"writer-{i % 5}", "Titel", "cli", "todo", detail=big_detail)
                i += 1

        def _reader():
            while not stop.is_set():
                if backlog_store.list_tickets() == []:
                    saw_empty.set()
                    return

        writer_thread = threading.Thread(target=_writer)
        reader_threads = [threading.Thread(target=_reader) for _ in range(5)]
        for t in [writer_thread, *reader_threads]:
            t.start()
        time.sleep(1.0)
        stop.set()
        for t in [writer_thread, *reader_threads]:
            t.join(timeout=5)

        self.assertFalse(saw_empty.is_set(), "list_tickets() sah während gleichzeitiger Writes eine leere/kaputte Datei")

    def test_get_ticket_returns_matching_ticket(self):
        backlog_store.upsert_ticket("recurring-failure-proj", "X", "orchestrator", "blocked", detail="y")

        ticket = backlog_store.get_ticket("recurring-failure-proj")

        self.assertIsNotNone(ticket)
        self.assertEqual(ticket.id, "recurring-failure-proj")
        self.assertEqual(ticket.detail, "y")

    def test_get_ticket_returns_none_when_missing(self):
        self.assertIsNone(backlog_store.get_ticket("does-not-exist"))


class TestPruneOrphanedTickets(unittest.TestCase):
    """
    Nutzerauftrag: automatisches Pruning für verwaiste Tickets gelöschter Projekte - siehe
    core/backlog_store.py.prune_orphaned_tickets()-Docstring für den vollen Kontext.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.file_path = Path(self.temp_dir) / "backlog.json"
        self._patcher = patch.object(backlog_store, "BACKLOG_FILE", self.file_path)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_removes_ticket_whose_project_no_longer_exists(self):
        backlog_store.upsert_ticket(
            "audit-deleted_project", "Verifikation fehlgeschlagen: deleted_project",
            "workspace_audit", "blocked", project_slug="deleted_project",
        )

        pruned = backlog_store.prune_orphaned_tickets(existing_project_slugs=set())

        self.assertEqual(pruned, ["audit-deleted_project"])
        self.assertEqual(backlog_store.list_tickets(), [])

    def test_keeps_ticket_whose_project_still_exists(self):
        backlog_store.upsert_ticket(
            "audit-alive_project", "Verifikation fehlgeschlagen: alive_project",
            "workspace_audit", "blocked", project_slug="alive_project",
        )

        pruned = backlog_store.prune_orphaned_tickets(existing_project_slugs={"alive_project"})

        self.assertEqual(pruned, [])
        self.assertEqual(len(backlog_store.list_tickets()), 1)

    def test_never_prunes_tickets_without_a_project_slug(self):
        # Teamweite Meta-Tickets (z.B. "unused-agent-<id>", "team-verification-trend") beziehen
        # sich auf keinen einzelnen Workspace-Ordner und dürfen nie als "verwaist" gelten.
        backlog_store.upsert_ticket("unused-agent-ml", "Ungenutzte Agentenrolle: ml", "optimization_advisor", "todo")

        pruned = backlog_store.prune_orphaned_tickets(existing_project_slugs=set())

        self.assertEqual(pruned, [])
        self.assertEqual(len(backlog_store.list_tickets()), 1)

    def test_empty_result_does_not_rewrite_the_file(self):
        backlog_store.upsert_ticket(
            "audit-alive_project", "X", "workspace_audit", "blocked", project_slug="alive_project",
        )
        mtime_before = self.file_path.stat().st_mtime_ns

        backlog_store.prune_orphaned_tickets(existing_project_slugs={"alive_project"})

        self.assertEqual(self.file_path.stat().st_mtime_ns, mtime_before)

    def test_resolves_existing_projects_from_workspace_manager_by_default(self):
        fake_workspace = MagicMock()
        fake_workspace.list_projects.return_value = ["alive_project"]
        backlog_store.upsert_ticket(
            "audit-deleted_project", "X", "workspace_audit", "blocked", project_slug="deleted_project",
        )
        backlog_store.upsert_ticket(
            "audit-alive_project", "Y", "workspace_audit", "blocked", project_slug="alive_project",
        )

        with patch("core.workspace.WorkspaceManager", return_value=fake_workspace):
            pruned = backlog_store.prune_orphaned_tickets()

        self.assertEqual(pruned, ["audit-deleted_project"])


class TestArchiveCompletedTickets(unittest.TestCase):
    """P6-4 (ROADMAP_TEMP.md): memory/backlog.json lag bei 200 Tickets/143 KB, davon 19
    "cancelled" + 96 "done" - archive_completed_tickets() verschiebt sie nach einer Ruhezeit
    nach memory/backlog_archive.json, statt sie im aktiven Board mitzuschleppen."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.file_path = Path(self.temp_dir) / "backlog.json"
        self.archive_path = Path(self.temp_dir) / "backlog_archive.json"
        self._patcher = patch.object(backlog_store, "BACKLOG_FILE", self.file_path)
        self._archive_patcher = patch.object(backlog_store, "BACKLOG_ARCHIVE_FILE", self.archive_path)
        self._patcher.start()
        self._archive_patcher.start()
        self.addCleanup(self._patcher.stop)
        self.addCleanup(self._archive_patcher.stop)

    def _age(self, ticket_id: str, days: float):
        import json
        from datetime import UTC, datetime, timedelta

        raw = json.loads(self.file_path.read_text(encoding="utf-8"))
        for t in raw:
            if t["id"] == ticket_id:
                t["updated_at"] = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        self.file_path.write_text(json.dumps(raw), encoding="utf-8")

    def test_old_completed_tickets_are_archived(self):
        backlog_store.upsert_ticket("cli-1", "Erledigt", "cli", "done")
        self._age("cli-1", 30)

        archived = backlog_store.archive_completed_tickets(older_than_days=14)

        self.assertEqual(archived, ["cli-1"])
        self.assertIsNone(backlog_store.get_ticket("cli-1"))
        self.assertEqual(len(backlog_store._load_archive()), 1)
        self.assertEqual(backlog_store._load_archive()[0]["id"], "cli-1")

    def test_recently_completed_tickets_stay_in_the_active_board(self):
        backlog_store.upsert_ticket("cli-1", "Gerade erledigt", "cli", "done")  # updated_at = jetzt

        archived = backlog_store.archive_completed_tickets(older_than_days=14)

        self.assertEqual(archived, [])
        self.assertIsNotNone(backlog_store.get_ticket("cli-1"))

    def test_open_tickets_are_never_archived_regardless_of_age(self):
        backlog_store.upsert_ticket("cli-1", "Noch offen", "cli", "todo")
        self._age("cli-1", 365)

        archived = backlog_store.archive_completed_tickets(older_than_days=14)

        self.assertEqual(archived, [])
        self.assertIsNotNone(backlog_store.get_ticket("cli-1"))

    def test_archiving_preserves_previously_archived_tickets(self):
        backlog_store.upsert_ticket("cli-1", "Alt", "cli", "done")
        self._age("cli-1", 30)
        backlog_store.archive_completed_tickets(older_than_days=14)

        backlog_store.upsert_ticket("cli-2", "Auch alt", "cli", "cancelled")
        self._age("cli-2", 30)
        backlog_store.archive_completed_tickets(older_than_days=14)

        ids = {t["id"] for t in backlog_store._load_archive()}
        self.assertEqual(ids, {"cli-1", "cli-2"})

    def test_no_op_when_nothing_qualifies_does_not_write_archive_file(self):
        backlog_store.upsert_ticket("cli-1", "Offen", "cli", "todo")

        backlog_store.archive_completed_tickets(older_than_days=14)

        self.assertFalse(self.archive_path.exists())


if __name__ == "__main__":
    unittest.main()
