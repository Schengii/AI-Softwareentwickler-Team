"""
tests/test_workspace_audit.py – Testet core/workspace_audit.py (periodische
Re-Verifikation über ALLE Workspace-Projekte)

WorkspaceManager UND ProjectVerifier sind hier vollständig gemockt (echte pytest-/npm-Läufe
sind bereits an anderer Stelle abgedeckt: tests/test_verifier.py für die Primitiven).
Gegenstand dieser Tests ist die ORCHESTRIERUNG: welches Projekt bekommt welches Ticket, wann
wird benachrichtigt, wann wird ein Ticket wieder freigegeben.
"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import core.backlog_store as backlog_store
from core.verifier import VerificationReport
from core.workspace_audit import run_workspace_audit_cycle


def _passing_report() -> VerificationReport:
    return VerificationReport(ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1)


def _skipped_report() -> VerificationReport:
    return VerificationReport(
        ran=False, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.0,
        reason_skipped="Keine Testdateien (test_*.py), kein npm-Test-Skript und kein Rust/Go-Projekt gefunden – Verifikation übersprungen.",
    )


def _incomplete_project_report() -> VerificationReport:
    return VerificationReport(
        ran=False, passed=False, exit_code=1, stdout="", stderr="", duration_seconds=0.0,
        reason_skipped="Unvollständiges Projekt erkannt: kein erkennbarer Einstiegspunkt.",
    )


def _failing_report() -> VerificationReport:
    return VerificationReport(ran=True, passed=False, exit_code=1, stdout="", stderr="Boom", duration_seconds=0.2)


class TestWorkspaceAuditCycle(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._backlog_patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(self.temp_dir) / "backlog.json")
        self._backlog_patcher.start()
        self.addCleanup(self._backlog_patcher.stop)

        self.fake_workspace = MagicMock()
        self.fake_workspace.list_projects.return_value = ["fastapi_app"]
        self.fake_workspace.get_project_dir.return_value = Path(self.temp_dir) / "fastapi_app"
        self._ws_patcher = patch("core.workspace_audit.WorkspaceManager", return_value=self.fake_workspace)
        self._ws_patcher.start()
        self.addCleanup(self._ws_patcher.stop)

    def _patch_verifier(self, report):
        fake_verifier = MagicMock()
        fake_verifier.run_tests.return_value = report
        return patch("core.workspace_audit.ProjectVerifier", return_value=fake_verifier)

    def test_no_projects_returns_empty_report(self):
        self.fake_workspace.list_projects.return_value = []
        report = asyncio.run(run_workspace_audit_cycle())
        self.assertEqual(report.scanned_projects, 0)
        self.assertEqual(report.results, [])

    def test_passing_project_creates_no_ticket(self):
        with self._patch_verifier(_passing_report()):
            report = asyncio.run(run_workspace_audit_cycle())

        self.assertEqual(report.scanned_projects, 1)
        self.assertTrue(report.results[0].healthy)
        self.assertEqual(backlog_store.list_tickets(), [])

    def test_legitimately_skipped_project_is_not_treated_as_failure(self):
        """"Keine Tests gefunden" (passed=True) bleibt weiterhin ein legitimer Zustand -
        kein Ticket, kein Fehlschlag, nur die harte Regression wird gemeldet."""
        with self._patch_verifier(_skipped_report()):
            report = asyncio.run(run_workspace_audit_cycle())

        self.assertTrue(report.results[0].healthy)
        self.assertEqual(backlog_store.list_tickets(), [])

    @patch("core.workspace_audit.notify_external")
    def test_incomplete_project_creates_blocked_ticket_and_notifies(self, mock_notify):
        with self._patch_verifier(_incomplete_project_report()):
            report = asyncio.run(run_workspace_audit_cycle())

        self.assertFalse(report.results[0].healthy)
        ticket = next(t for t in backlog_store.list_tickets() if t.id == "audit-fastapi_app")
        self.assertEqual(ticket.status, "blocked")
        self.assertIn("Unvollständiges Projekt", ticket.detail)
        mock_notify.assert_called_once()

    def test_failing_tests_create_blocked_ticket(self):
        with self._patch_verifier(_failing_report()):
            report = asyncio.run(run_workspace_audit_cycle())

        self.assertFalse(report.results[0].healthy)
        ticket = next(t for t in backlog_store.list_tickets() if t.id == "audit-fastapi_app")
        self.assertEqual(ticket.status, "blocked")

    def test_previously_blocked_ticket_is_resolved_when_passing_again(self):
        backlog_store.upsert_ticket(
            ticket_id="audit-fastapi_app", title="Verifikation fehlgeschlagen: fastapi_app",
            source="workspace_audit", status="blocked", detail="alter Fehlschlag",
        )
        with self._patch_verifier(_passing_report()):
            asyncio.run(run_workspace_audit_cycle())

        ticket = next(t for t in backlog_store.list_tickets() if t.id == "audit-fastapi_app")
        self.assertEqual(ticket.status, "done")

    def test_multiple_projects_are_all_scanned(self):
        self.fake_workspace.list_projects.return_value = ["proj_a", "proj_b"]
        with self._patch_verifier(_failing_report()):
            report = asyncio.run(run_workspace_audit_cycle())

        self.assertEqual(report.scanned_projects, 2)
        self.assertEqual(len(report.results), 2)
        ticket_ids = {t.id for t in backlog_store.list_tickets()}
        self.assertEqual(ticket_ids, {"audit-proj_a", "audit-proj_b"})


if __name__ == "__main__":
    unittest.main()
