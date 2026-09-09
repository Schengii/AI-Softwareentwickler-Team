"""
tests/test_team_retro.py – Testet core/team_retro.py (periodische Team-Retro über
liegengebliebene, nicht automatisch wieder aufgegriffene Backlog-Tickets).

KI-Team-Zustandsbericht 2026-09-08: core/backlog_worker.py greift bewusst NUR Tickets aus
_AUTONOMOUS_SOURCES bzw. mit einem der _GOVERNANCE_RETRY_PREFIXES automatisch wieder auf -
"unused-agent-<id>"/"team-verification-trend"-Tickets (source="optimization_advisor" bzw.
"workspace_audit" ohne "audit-"-Präfix) blieben dadurch real tagelang unbeachtet liegen.
core/team_retro.py macht genau diese Kategorie periodisch sichtbar.
"""

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import core.backlog_store as backlog_store_module
import memory.cost_history as cost_history_module
import memory.run_history as run_history_module
from core.backlog_store import upsert_ticket
from core.team_retro import STALE_TICKET_DAYS, build_team_retro_report, build_weekly_digest
from memory.cost_history import record_run_usage
from memory.run_history import record_run


def _iso_days_ago(days: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


class TestBuildTeamRetroReport(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._patcher = patch.object(backlog_store_module, "BACKLOG_FILE", Path(self.temp_dir) / "backlog.json")
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _upsert_with_age(self, ticket_id: str, days_old: float, **kwargs):
        upsert_ticket(ticket_id=ticket_id, **kwargs)
        # upsert_ticket() setzt updated_at immer auf "jetzt" - für einen Alters-Test muss der
        # gespeicherte Zeitstempel direkt im Store zurückdatiert werden.
        raw = backlog_store_module._load_raw()
        for entry in raw:
            if entry["id"] == ticket_id:
                entry["updated_at"] = _iso_days_ago(days_old)
        backlog_store_module._save_raw(raw)

    def test_old_unused_agent_ticket_is_flagged_as_stale(self):
        self._upsert_with_age(
            "unused-agent-ml", STALE_TICKET_DAYS + 2,
            title="Ungenutzte Agentenrolle: ml", source="optimization_advisor",
            status="todo", project_slug="_team", detail="nie gewählt",
        )

        report = build_team_retro_report()

        self.assertEqual(report.total_stale_tickets, 1)
        self.assertEqual(report.stale_tickets[0].id, "unused-agent-ml")
        self.assertFalse(report.is_empty)

    def test_recent_unused_agent_ticket_is_not_yet_stale(self):
        self._upsert_with_age(
            "unused-agent-ml", STALE_TICKET_DAYS - 2,
            title="Ungenutzte Agentenrolle: ml", source="optimization_advisor",
            status="todo", project_slug="_team", detail="nie gewählt",
        )

        report = build_team_retro_report()

        self.assertTrue(report.is_empty)
        self.assertEqual(report.total_open_tickets, 1)

    def test_autonomously_retried_ticket_is_never_flagged_even_when_old(self):
        """Ein 'recurring-lint-'-Ticket wird von core/backlog_worker.py ohnehin automatisch
        wieder aufgegriffen - die Team-Retro soll hier NICHT doppelt Alarm schlagen, egal wie
        alt es ist."""
        self._upsert_with_age(
            "recurring-lint-sentinelproxy", STALE_TICKET_DAYS + 30,
            title="Wiederkehrender Lint-Fund: sentinelproxy", source="orchestrator",
            status="blocked", project_slug="sentinelproxy", detail="BLE001",
        )

        report = build_team_retro_report()

        self.assertTrue(report.is_empty)

    def test_cli_source_ticket_is_never_flagged_even_when_old(self):
        """Ein ganz normales 'todo'-Ticket aus der CLI wird von --work-backlog automatisch
        aufgegriffen (source in _AUTONOMOUS_SOURCES) - kein Fall für die Team-Retro."""
        self._upsert_with_age(
            "cli-1", STALE_TICKET_DAYS + 10,
            title="Baue eine Notiz-App", source="cli", status="todo",
        )

        report = build_team_retro_report()

        self.assertTrue(report.is_empty)

    def test_done_ticket_is_never_flagged(self):
        self._upsert_with_age(
            "unused-agent-mobile", STALE_TICKET_DAYS + 10,
            title="Ungenutzte Agentenrolle: mobile", source="optimization_advisor",
            status="done", project_slug="_team",
        )

        report = build_team_retro_report()

        self.assertTrue(report.is_empty)

    def test_stale_tickets_sorted_oldest_first(self):
        self._upsert_with_age(
            "unused-agent-ml", STALE_TICKET_DAYS + 1,
            title="Ungenutzte Agentenrolle: ml", source="optimization_advisor",
            status="todo", project_slug="_team",
        )
        self._upsert_with_age(
            "unused-agent-mobile", STALE_TICKET_DAYS + 20,
            title="Ungenutzte Agentenrolle: mobile", source="optimization_advisor",
            status="todo", project_slug="_team",
        )

        report = build_team_retro_report()

        self.assertEqual([t.id for t in report.stale_tickets], ["unused-agent-mobile", "unused-agent-ml"])

    def test_format_for_humans_lists_stale_ticket_ids(self):
        self._upsert_with_age(
            "unused-agent-ml", STALE_TICKET_DAYS + 2,
            title="Ungenutzte Agentenrolle: ml", source="optimization_advisor",
            status="todo", project_slug="_team", detail="nie gewählt",
        )

        text = build_team_retro_report().format_for_humans()

        self.assertIn("unused-agent-ml", text)
        self.assertIn("nie gewählt", text)

    def test_format_for_humans_with_no_stale_tickets(self):
        text = build_team_retro_report().format_for_humans()

        self.assertIn("✅", text)


class TestBuildWeeklyDigest(unittest.TestCase):
    """
    KI-Team-Zustandsbericht 2026-09-08, "Weekly Digest": build_team_retro_report() zeigt nur
    liegengebliebene Tickets, kein Fortschritts-Blick wie bei einem echten Sprint-Review.
    build_weekly_digest() kombiniert bereits bestehende Datenquellen (Backlog, memory/
    run_history.py, memory/cost_history.py) zu einem Wochenüberblick.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._backlog_patcher = patch.object(backlog_store_module, "BACKLOG_FILE", Path(self.temp_dir) / "backlog.json")
        self._backlog_patcher.start()
        self.addCleanup(self._backlog_patcher.stop)
        self._cost_patcher = patch.object(cost_history_module, "COST_HISTORY_FILE", Path(self.temp_dir) / "cost_history.json")
        self._cost_patcher.start()
        self.addCleanup(self._cost_patcher.stop)
        self._run_patcher = patch.object(run_history_module, "RUN_HISTORY_FILE", Path(self.temp_dir) / "run_history.json")
        self._run_patcher.start()
        self.addCleanup(self._run_patcher.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _upsert_with_age(self, ticket_id: str, days_old: float, **kwargs):
        upsert_ticket(ticket_id=ticket_id, **kwargs)
        raw = backlog_store_module._load_raw()
        for entry in raw:
            if entry["id"] == ticket_id:
                entry["created_at"] = _iso_days_ago(days_old)
                entry["updated_at"] = _iso_days_ago(days_old)
        backlog_store_module._save_raw(raw)

    def test_counts_recently_completed_and_opened_tickets(self):
        self._upsert_with_age("t1", 2, title="Erledigt", source="cli", status="done")
        self._upsert_with_age("t2", 10, title="Vor 10 Tagen erledigt", source="cli", status="done")
        self._upsert_with_age("t3", 1, title="Neu", source="cli", status="todo")

        digest = build_weekly_digest(window_days=7)

        self.assertEqual(digest.tickets_completed, 1)
        self.assertEqual(digest.tickets_opened, 2)  # t1 (done, aber vor 2 Tagen ERÖFFNET) + t3
        self.assertEqual(digest.velocity_delta, -1)

    def test_sums_token_usage_within_window_only(self):
        record_run_usage({"claude-sonnet-5": {"total_tokens": 500}})
        raw = cost_history_module._load()
        raw["daily"]["2000-01-01"] = {"gemini-old": {"total_tokens": 999_999}}
        cost_history_module._save(raw)

        digest = build_weekly_digest(window_days=7)

        self.assertEqual(digest.tokens_spent, 500)  # NICHT 1_000_499 - der alte Eintrag zählt nicht

    def test_verification_rate_within_window_only(self):
        record_run("proj", "Aufgabe", verification_ok=True, total_tokens=10, duration_seconds=1.0, agent_results=[])
        record_run("proj", "Aufgabe", verification_ok=False, total_tokens=10, duration_seconds=1.0, agent_results=[])
        raw = run_history_module._load()
        raw.append({
            "timestamp": _iso_days_ago(30), "project_slug": "proj", "task_summary": "alt",
            "verification_ok": False, "total_tokens": 5, "duration_seconds": 1.0, "agent_results": [],
        })
        run_history_module._save(raw)

        digest = build_weekly_digest(window_days=7)

        self.assertEqual(digest.verification_runs, 2)  # der 30 Tage alte Lauf zählt nicht
        self.assertEqual(digest.verification_passed, 1)
        self.assertEqual(digest.verification_rate, 50.0)

    def test_includes_stale_ticket_retro_section(self):
        self._upsert_with_age(
            "unused-agent-ml", STALE_TICKET_DAYS + 2, title="Ungenutzte Agentenrolle: ml",
            source="optimization_advisor", status="todo", project_slug="_team",
        )

        digest = build_weekly_digest()

        self.assertEqual(digest.stale_retro.total_stale_tickets, 1)
        self.assertIn("unused-agent-ml", digest.format_for_humans())

    def test_empty_state_does_not_crash(self):
        digest = build_weekly_digest()

        self.assertEqual(digest.tickets_completed, 0)
        self.assertEqual(digest.tokens_spent, 0)
        self.assertEqual(digest.verification_runs, 0)
        self.assertIn("keine Läufe", digest.format_for_humans())


if __name__ == "__main__":
    unittest.main()
