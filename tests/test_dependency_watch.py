"""
tests/test_dependency_watch.py – Testet core/dependency_watch.py (periodischer
Vulnerability-Scan über ALLE Workspace-Projekte)

WorkspaceManager UND ProjectVerifier sind hier vollständig gemockt (echte pip-audit-/
npm-audit-Läufe sind bereits an anderer Stelle abgedeckt: tests/test_verifier_dependency_audit.py
für die Primitiven). Gegenstand dieser Tests ist die ORCHESTRIERUNG: welches Projekt bekommt
welches Ticket, wann wird benachrichtigt, wann wird ein Ticket wieder freigegeben.
"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import core.backlog_store as backlog_store
from core.dependency_watch import run_dependency_watch_cycle
from core.verifier import DependencyAuditReport, DependencyVulnerability


def _clean_report(tool: str = "pip-audit") -> DependencyAuditReport:
    return DependencyAuditReport(attempted=True, vulnerable=False, tool=tool)


def _vulnerable_report(tool: str = "pip-audit") -> DependencyAuditReport:
    return DependencyAuditReport(
        attempted=True, vulnerable=True, tool=tool,
        vulnerabilities=[DependencyVulnerability(
            package="urllib3", version="1.24.1", vulnerability_id="PYSEC-2019-133", description="...",
        )],
    )


class TestDependencyWatchCycle(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._backlog_patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(self.temp_dir) / "backlog.json")
        self._backlog_patcher.start()
        self.addCleanup(self._backlog_patcher.stop)

        self.fake_workspace = MagicMock()
        self.fake_workspace.list_projects.return_value = ["fastapi_app"]
        self.fake_workspace.get_project_dir.return_value = Path(self.temp_dir) / "fastapi_app"
        self._ws_patcher = patch("core.dependency_watch.WorkspaceManager", return_value=self.fake_workspace)
        self._ws_patcher.start()
        self.addCleanup(self._ws_patcher.stop)

    def _patch_verifier(self, audit_reports):
        fake_verifier = MagicMock()
        fake_verifier.check_dependency_vulnerabilities.return_value = audit_reports
        return patch("core.dependency_watch.ProjectVerifier", return_value=fake_verifier)

    def test_no_projects_returns_empty_report(self):
        self.fake_workspace.list_projects.return_value = []
        report = asyncio.run(run_dependency_watch_cycle())
        self.assertEqual(report.scanned_projects, 0)
        self.assertEqual(report.results, [])

    def test_clean_scan_creates_no_ticket(self):
        with self._patch_verifier([_clean_report()]):
            report = asyncio.run(run_dependency_watch_cycle())

        self.assertEqual(report.scanned_projects, 1)
        self.assertEqual(report.results, [])
        self.assertEqual(backlog_store.list_tickets(), [])

    @patch("core.dependency_watch.notify_external")
    def test_vulnerable_scan_creates_blocked_ticket_and_notifies(self, mock_notify):
        with self._patch_verifier([_vulnerable_report()]):
            report = asyncio.run(run_dependency_watch_cycle())

        self.assertEqual(len(report.results), 1)
        self.assertTrue(report.results[0].vulnerable)
        ticket = next(t for t in backlog_store.list_tickets() if t.id == "depwatch-fastapi_app")
        self.assertEqual(ticket.status, "blocked")
        self.assertIn("urllib3", ticket.detail)
        self.assertIn("PYSEC-2019-133", ticket.detail)
        mock_notify.assert_called_once()

    def test_previously_blocked_ticket_is_resolved_when_clean_again(self):
        backlog_store.upsert_ticket(
            ticket_id="depwatch-fastapi_app", title="Dependency-Schwachstellen: fastapi_app",
            source="dependency_watch", status="blocked", detail="alte Schwachstelle",
        )
        with self._patch_verifier([_clean_report()]):
            asyncio.run(run_dependency_watch_cycle())

        ticket = next(t for t in backlog_store.list_tickets() if t.id == "depwatch-fastapi_app")
        self.assertEqual(ticket.status, "done")

    def test_unattempted_scan_is_not_treated_as_vulnerable(self):
        # pip-audit nicht installiert (attempted=False) darf NIE als "sauber" ODER "verwundbar"
        # fehlinterpretiert werden - siehe DependencyAuditReport-Docstring in core/verifier.py.
        skipped = DependencyAuditReport(attempted=False, vulnerable=False, tool="pip-audit", reason_skipped="fehlt")
        with self._patch_verifier([skipped]):
            report = asyncio.run(run_dependency_watch_cycle())

        self.assertEqual(report.results, [])
        self.assertEqual(backlog_store.list_tickets(), [])

    def test_multiple_projects_are_all_scanned(self):
        self.fake_workspace.list_projects.return_value = ["proj_a", "proj_b"]
        with self._patch_verifier([_vulnerable_report()]):
            report = asyncio.run(run_dependency_watch_cycle())

        self.assertEqual(report.scanned_projects, 2)
        self.assertEqual(len(report.results), 2)
        ticket_ids = {t.id for t in backlog_store.list_tickets()}
        self.assertEqual(ticket_ids, {"depwatch-proj_a", "depwatch-proj_b"})


class TestDependencyAutoUpdatePR(unittest.TestCase):
    """
    Testet die Auto-Update-PR-Anbindung (core/dependency_updater.py +
    agents/github_agent.py) – apply_python_dependency_fixes() ist hier gemockt (bereits
    vollständig in tests/test_dependency_updater.py abgedeckt), GitHubAgent ist über
    agents.github_agent.GitHubAgent gemockt, da _open_dependency_update_pr() es lokal
    importiert (kein Modul-Level-Name in core.dependency_watch zum Patchen).
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._backlog_patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(self.temp_dir) / "backlog.json")
        self._backlog_patcher.start()
        self.addCleanup(self._backlog_patcher.stop)

        self.fake_workspace = MagicMock()
        self.fake_workspace.list_projects.return_value = ["fastapi_app"]
        self.fake_workspace.get_project_dir.return_value = Path(self.temp_dir) / "fastapi_app"
        self._ws_patcher = patch("core.dependency_watch.WorkspaceManager", return_value=self.fake_workspace)
        self._ws_patcher.start()
        self.addCleanup(self._ws_patcher.stop)

        fake_verifier = MagicMock()
        fake_verifier.check_dependency_vulnerabilities.return_value = [_vulnerable_report()]
        self._verifier_patcher = patch("core.dependency_watch.ProjectVerifier", return_value=fake_verifier)
        self._verifier_patcher.start()
        self.addCleanup(self._verifier_patcher.stop)

        self._fixes_patcher = patch(
            "core.dependency_watch.apply_python_dependency_fixes",
            return_value=["urllib3: 1.24.1 -> 1.24.2"],
        )
        self._fixes_patcher.start()
        self.addCleanup(self._fixes_patcher.stop)

        self.fake_github = MagicMock()
        self.fake_github.gh_ready.return_value = True
        self.fake_github.get_current_branch.return_value = "main"
        self.fake_github.create_branch.return_value = (True, "")
        self.fake_github.commit.return_value = (True, "")
        self.fake_github.push.return_value = (True, "")
        self.fake_github.create_pull_request.return_value = (True, "https://github.com/x/y/pull/9")
        self._github_patcher = patch("agents.github_agent.GitHubAgent", return_value=self.fake_github)
        self._github_patcher.start()
        self.addCleanup(self._github_patcher.stop)

    def test_successful_auto_update_opens_pr_and_sets_review_status(self):
        with patch("core.dependency_watch.ENABLE_DEPENDENCY_AUTO_UPDATE", True):
            report = asyncio.run(run_dependency_watch_cycle())

        self.assertEqual(report.results[0].pr_url, "https://github.com/x/y/pull/9")
        ticket = next(t for t in backlog_store.list_tickets() if t.id == "depwatch-fastapi_app")
        self.assertEqual(ticket.status, "review")
        self.assertIn("https://github.com/x/y/pull/9", ticket.detail)
        self.fake_github.checkout.assert_called_with("main")

    def test_disabled_flag_skips_auto_update_and_stays_blocked(self):
        with patch("core.dependency_watch.ENABLE_DEPENDENCY_AUTO_UPDATE", False):
            report = asyncio.run(run_dependency_watch_cycle())

        self.assertEqual(report.results[0].pr_url, "")
        ticket = next(t for t in backlog_store.list_tickets() if t.id == "depwatch-fastapi_app")
        self.assertEqual(ticket.status, "blocked")
        self.fake_github.create_branch.assert_not_called()

    def test_gh_not_ready_falls_back_to_blocked(self):
        self.fake_github.gh_ready.return_value = False
        with patch("core.dependency_watch.ENABLE_DEPENDENCY_AUTO_UPDATE", True):
            report = asyncio.run(run_dependency_watch_cycle())

        self.assertEqual(report.results[0].pr_url, "")
        ticket = next(t for t in backlog_store.list_tickets() if t.id == "depwatch-fastapi_app")
        self.assertEqual(ticket.status, "blocked")

    def test_non_main_branch_skips_auto_update(self):
        # Unerwarteter Zustand (z.B. laufender interaktiver Lauf auf einem Feature-Branch) -
        # nicht eingreifen, statt versehentlich vom falschen Branch abzuzweigen.
        self.fake_github.get_current_branch.return_value = "feat/etwas-anderes-abc123"
        with patch("core.dependency_watch.ENABLE_DEPENDENCY_AUTO_UPDATE", True):
            report = asyncio.run(run_dependency_watch_cycle())

        self.assertEqual(report.results[0].pr_url, "")
        self.fake_github.create_branch.assert_not_called()

    def test_failed_push_falls_back_to_blocked_and_restores_branch(self):
        self.fake_github.push.return_value = (False, "network error")
        with patch("core.dependency_watch.ENABLE_DEPENDENCY_AUTO_UPDATE", True):
            report = asyncio.run(run_dependency_watch_cycle())

        self.assertEqual(report.results[0].pr_url, "")
        ticket = next(t for t in backlog_store.list_tickets() if t.id == "depwatch-fastapi_app")
        self.assertEqual(ticket.status, "blocked")
        self.fake_github.checkout.assert_called_with("main")
        self.fake_github.create_pull_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
