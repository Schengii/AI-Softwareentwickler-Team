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
from core.backlog_store import upsert_ticket
from core.team_retro import STALE_TICKET_DAYS, build_team_retro_report


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


if __name__ == "__main__":
    unittest.main()
