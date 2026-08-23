"""
tests/test_production_monitor.py – Testet core/production_monitor.py (Produktions-Monitoring
nach dem Deploy)

_check_url() (echter HTTP-Request) ist hier über den öffentlichen `urllib`-Aufruf gemockt -
dasselbe Prinzip wie core/browser_verifier.py-Tests, die subprocess.run mocken statt einen
echten Server zu starten.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import core.backlog_store as backlog_store
import core.deployment_status as deployment_status
from core.production_monitor import run_deployment_health_check_cycle


class TestProductionMonitor(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_backlog_dir = tempfile.mkdtemp()

        self._backlog_patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(self.temp_backlog_dir) / "backlog.json")
        self._backlog_patcher.start()
        self.addCleanup(self._backlog_patcher.stop)

        self._workspace_patcher = patch("core.production_monitor.WORKSPACE_DIR", self.temp_workspace)
        self._workspace_patcher.start()
        self.addCleanup(self._workspace_patcher.stop)

        self._notify_patcher = patch("core.production_monitor.notify_external")
        self.mock_notify = self._notify_patcher.start()
        self.addCleanup(self._notify_patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_backlog_dir, ignore_errors=True)

    def _seed_deployment(self, slug: str, url: str = "https://x.fly.dev"):
        project_dir = Path(self.temp_workspace) / slug
        project_dir.mkdir(parents=True, exist_ok=True)
        deployment_status.record_deployment(project_dir, provider="fly", url=url)
        return project_dir

    def test_no_deployments_returns_empty_report(self):
        report = asyncio.run(run_deployment_health_check_cycle())
        self.assertEqual(report.checked, [])

    @patch("core.production_monitor._check_url", return_value=(True, "HTTP 200"))
    def test_healthy_deployment_is_reported_and_no_ticket_created(self, _mock_check):
        self._seed_deployment("proj_a")
        report = asyncio.run(run_deployment_health_check_cycle())

        self.assertEqual(len(report.checked), 1)
        self.assertTrue(report.checked[0].healthy)
        self.assertEqual(backlog_store.list_tickets(), [])
        self.mock_notify.assert_not_called()

    @patch("core.production_monitor._check_url", return_value=(False, "Connection refused"))
    def test_unhealthy_deployment_opens_high_priority_ticket_and_notifies(self, _mock_check):
        self._seed_deployment("proj_a", url="https://a.fly.dev")
        report = asyncio.run(run_deployment_health_check_cycle())

        self.assertFalse(report.checked[0].healthy)
        tickets = backlog_store.list_tickets()
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0].id, "monitor-proj_a")
        self.assertEqual(tickets[0].status, "todo")
        self.assertEqual(tickets[0].priority, 1)
        self.assertIn("Connection refused", tickets[0].detail)
        self.mock_notify.assert_called_once()

    @patch("core.production_monitor._check_url")
    def test_recovery_closes_previously_opened_incident_ticket(self, mock_check):
        self._seed_deployment("proj_a")
        mock_check.return_value = (False, "HTTP 503")
        asyncio.run(run_deployment_health_check_cycle())
        self.assertEqual(backlog_store.list_tickets()[0].status, "todo")

        mock_check.return_value = (True, "HTTP 200")
        asyncio.run(run_deployment_health_check_cycle())

        ticket = next(t for t in backlog_store.list_tickets() if t.id == "monitor-proj_a")
        self.assertEqual(ticket.status, "done")
        self.assertIn("Wieder erreichbar", ticket.detail)

    @patch("core.production_monitor._check_url", return_value=(True, "HTTP 200"))
    def test_health_check_result_is_persisted_per_project(self, _mock_check):
        project_dir = self._seed_deployment("proj_a")
        asyncio.run(run_deployment_health_check_cycle())

        data = deployment_status.read_deployment(project_dir)
        self.assertTrue(data["last_check_healthy"])
        self.assertEqual(data["last_check_detail"], "HTTP 200")

    @patch("core.production_monitor._check_url", return_value=(False, "timeout"))
    def test_multiple_deployed_projects_are_all_checked(self, _mock_check):
        self._seed_deployment("proj_a")
        self._seed_deployment("proj_b")
        report = asyncio.run(run_deployment_health_check_cycle())

        self.assertEqual({r.project_slug for r in report.checked}, {"proj_a", "proj_b"})
        self.assertEqual(len(backlog_store.list_tickets()), 2)


class TestCheckUrlAgainstRealServer(unittest.TestCase):
    """Testet _check_url() gegen einen ECHTEN lokalen HTTP-Server statt gemockter urllib-
    Aufrufe - dasselbe Prinzip wie core/browser_verifier.py, das einen echten
    ThreadingHTTPServer für seine Playwright-Checks startet."""

    def test_reachable_server_is_healthy(self):
        import http.server
        import socket
        import threading

        from core.production_monitor import _check_url

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        class OkHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        httpd = http.server.HTTPServer(("127.0.0.1", port), OkHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            healthy, detail = _check_url(f"http://127.0.0.1:{port}/", timeout=5.0)
        finally:
            httpd.shutdown()
            httpd.server_close()

        self.assertTrue(healthy)
        self.assertIn("200", detail)

    def test_refused_connection_is_unhealthy(self):
        import socket

        from core.production_monitor import _check_url

        # Freien Port ermitteln und SOFORT wieder schließen, statt hart einen unbelegten Port
        # zu raten - garantiert "Connection refused" statt eines zufälligen Treffers.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        healthy, detail = _check_url(f"http://127.0.0.1:{port}/", timeout=2.0)
        self.assertFalse(healthy)
        self.assertTrue(detail)


if __name__ == "__main__":
    unittest.main()
