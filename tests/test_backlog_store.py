"""
tests/test_backlog_store.py – Testet core/backlog_store.py (persistenter Backlog/Kanban-
Zustand über CLI/Dashboard/Issue-Watcher hinweg)
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
