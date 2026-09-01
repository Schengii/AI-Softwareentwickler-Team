"""
tests/test_dashboard_cloud_deploy.py – Testet den Cloud-Deployment-Endpunkt des Web-Dashboards
(POST /api/deploy-cloud, GET /api/deploy-cloud-status/<projekt>)

Nutzt einen ECHTEN HTTP-Server (kein Mock des Request/Response-Zyklus, siehe
tests/test_dashboard_deploy.py für dasselbe Prinzip). CloudDeploymentManager.deploy() wird NICHT
gemockt fuer den Dry-Run-Fall (dry_run=True generiert nur lokale Manifest-Dateien, startet keine
echten Subprozesse/Netzwerkaufrufe - sicher in Tests). Ein "--real"-Deploy wird hier bewusst
NICHT ausgeloest (keine echten Cloud-Ressourcen aus der Testsuite heraus) - stattdessen wird nur
geprueft, dass er ohne "confirm": true als 400 abgelehnt wird, bevor core/cloud_deployment.py
ueberhaupt aufgerufen wird.
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
from core.workspace import WorkspaceManager
from interface.web_dashboard import DashboardServer, make_handler

PORT = 8254  # dediziert, um Konflikte mit den anderen Dashboard-Testdateien zu vermeiden


class TestDashboardCloudDeployEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_workspace = tempfile.mkdtemp()
        (Path(cls.temp_workspace) / "demo_project").mkdir()
        (Path(cls.temp_workspace) / "demo_project" / "requirements.txt").write_text("", encoding="utf-8")

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

    def test_cloud_deploy_status_for_never_deployed_project_is_none(self):
        data = self._get_json("/api/deploy-cloud-status/never_touched_project")
        self.assertEqual(data["status"], "none")

    def test_cloud_deploy_unknown_provider_returns_400(self):
        status, data = self._post_json(
            "/api/deploy-cloud", {"project": "demo_project", "provider": "heroku"}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_cloud_deploy_unknown_project_returns_404(self):
        status, data = self._post_json(
            "/api/deploy-cloud", {"project": "does_not_exist", "provider": "fly"}
        )
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_cloud_deploy_real_without_confirm_returns_400(self):
        status, data = self._post_json(
            "/api/deploy-cloud", {"project": "demo_project", "provider": "fly", "real": True}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_full_cloud_deploy_dry_run_reaches_done_with_success(self):
        status, data = self._post_json(
            "/api/deploy-cloud", {"project": "demo_project", "provider": "fly"}
        )
        self.assertEqual(status, 202)
        self.assertFalse(data["real"])

        final = {}
        for _ in range(30):
            final = self._get_json("/api/deploy-cloud-status/demo_project")
            if final["status"] not in ("running",):
                break
            time.sleep(0.1)

        self.assertEqual(final["status"], "done")
        self.assertTrue(final["success"])
        self.assertEqual(final["provider"], "fly")
        self.assertTrue(final["preview_url"].startswith("https://"))


if __name__ == "__main__":
    unittest.main()
