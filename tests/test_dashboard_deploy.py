"""
tests/test_dashboard_deploy.py – Testet die Deployment-Endpunkte des Web-Dashboards
(GET /api/projects, POST /api/deploy, POST /api/deploy-stop, GET /api/deploy-status/<projekt>)

Echtes `docker` ist in der CI-Testumgebung nicht garantiert verfügbar - core/deployment.py's
deploy_project()/stop_deployment() werden gemockt (core/deployment.py selbst ist in
tests/test_deployment.py gegen mockierte Docker-Kommandos getestet). Nutzt einen ECHTEN
HTTP-Server (kein Mock des Request/Response-Zyklus, siehe tests/test_web_dashboard.py für
dasselbe Prinzip) - Gegenstand ist die asynchrone Ausführung im Hintergrund-Event-Loop plus
das Status-Polling.
"""

import json
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import core.backlog_store as backlog_store
from core.deployment import DeploymentResult
from core.workspace import WorkspaceManager
from interface.web_dashboard import DashboardServer, make_handler

PORT = 8253  # dediziert, um Konflikte mit den anderen Dashboard-Testdateien zu vermeiden


class TestDashboardDeployEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_workspace = tempfile.mkdtemp()
        (Path(cls.temp_workspace) / "demo_project").mkdir()
        (Path(cls.temp_workspace) / "demo_project" / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")

        cls._backlog_dir = tempfile.mkdtemp()
        cls._backlog_patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(cls._backlog_dir) / "backlog.json")
        cls._backlog_patcher.start()

        cls.server_state = DashboardServer()
        cls.server_state.orchestrator._workspace = WorkspaceManager(cls.temp_workspace)
        handler_cls = make_handler(cls.server_state)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", PORT), handler_cls)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.thread.join(timeout=2)
        # Ohne dies liefe der interne Event-Loop-Thread von DashboardServer (siehe
        # DashboardServer.shutdown()-Docstring) als daemon-Thread unbegrenzt weiter - bei
        # mehreren Testdateien mit demselben Muster in derselben `unittest discover`-Suite
        # führte das reproduzierbar zu einem minutenlangen Hänger der vollen Suite.
        cls.server_state.shutdown()
        cls._backlog_patcher.stop()
        shutil.rmtree(cls.temp_workspace, ignore_errors=True)
        shutil.rmtree(cls._backlog_dir, ignore_errors=True)

    def _get_json(self, path: str) -> dict:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}") as r:
            return json.loads(r.read())

    def _post_json(self, path: str, body: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"http://127.0.0.1:{PORT}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_projects_endpoint_lists_workspace_projects(self):
        data = self._get_json("/api/projects")
        self.assertIn("demo_project", data["projects"])

    def test_deploy_unknown_project_returns_404(self):
        status, data = self._post_json("/api/deploy", {"project": "does_not_exist"})
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_deploy_status_for_never_deployed_project_is_none(self):
        data = self._get_json("/api/deploy-status/never_touched_project")
        self.assertEqual(data["status"], "none")

    @patch("core.deployment.deploy_project")
    def test_full_deploy_cycle_reaches_done_with_success(self, mock_deploy):
        mock_deploy.return_value = DeploymentResult(
            attempted=True, success=True, method="docker", urls=["http://localhost:8000"],
        )
        status, data = self._post_json("/api/deploy", {"project": "demo_project"})
        self.assertEqual(status, 202)

        final = {}
        for _ in range(30):
            final = self._get_json("/api/deploy-status/demo_project")
            if final["status"] not in ("running",):
                break
            time.sleep(0.1)

        self.assertEqual(final["status"], "done")
        self.assertTrue(final["success"])
        self.assertEqual(final["method"], "docker")
        self.assertEqual(final["urls"], ["http://localhost:8000"])

    @patch("core.deployment.stop_deployment")
    def test_full_stop_cycle_reaches_stopped(self, mock_stop):
        mock_stop.return_value = DeploymentResult(attempted=True, success=True, method="docker")
        status, _data = self._post_json("/api/deploy-stop", {"project": "demo_project"})
        self.assertEqual(status, 202)

        final = {}
        for _ in range(30):
            final = self._get_json("/api/deploy-status/demo_project")
            if final["status"] not in ("stopping",):
                break
            time.sleep(0.1)

        self.assertEqual(final["status"], "stopped")


if __name__ == "__main__":
    unittest.main()
