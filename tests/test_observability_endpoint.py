"""
tests/test_observability_endpoint.py – Testet GET /api/observability

Realer Fund bei einer Bestandsaufnahme des eigenen Teams: das Web-Dashboard zeigte bisher nur
den aktuellen/letzten Job, keine Trends über die Zeit. /api/observability liefert jetzt
Erfolgsquoten je Agent + jüngste Läufe aus memory/run_history.py - über ALLE Trigger-Quellen
hinweg, nicht nur Dashboard-Jobs. Selbes Testmuster wie test_web_dashboard.py, eigener Port
um Konflikte mit der parallel laufenden Test-Instanz dort zu vermeiden.
"""

import json
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import memory.run_history as run_history_module
from interface.web_dashboard import DashboardServer, make_handler
from memory.run_history import record_run

PORT = 8264  # dediziert für diesen Test, um Portkonflikte mit test_web_dashboard.py zu vermeiden


class TestObservabilityEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._history_dir = tempfile.mkdtemp()
        cls._history_patcher = patch.object(
            run_history_module, "RUN_HISTORY_FILE", Path(cls._history_dir) / "run_history.json",
        )
        cls._history_patcher.start()

        record_run(
            project_slug="obs_test_proj", task_summary="Endpunkt gebaut", verification_ok=True,
            total_tokens=1234, duration_seconds=42.0,
            agent_results=[
                {"agent_id": "backend", "success": True, "total_tokens": 1000},
                {"agent_id": "tester", "success": False, "total_tokens": 234},
            ],
        )

        cls.server_state = DashboardServer()
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
        # mehreren Testdateien mit demselben Muster (siehe auch test_web_dashboard.py) in
        # derselben `unittest discover`-Suite führte das reproduzierbar zu einem
        # minutenlangen Hänger der vollen Suite.
        cls.server_state.shutdown()
        cls._history_patcher.stop()

    def _get_json(self, path: str) -> dict:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}") as r:
            return json.loads(r.read())

    def test_returns_recent_runs_with_real_data(self):
        data = self._get_json("/api/observability")

        self.assertEqual(len(data["recent_runs"]), 1)
        run = data["recent_runs"][0]
        self.assertEqual(run["project_slug"], "obs_test_proj")
        self.assertEqual(run["total_tokens"], 1234)

    def test_returns_agent_success_rates(self):
        data = self._get_json("/api/observability")

        rates = {r["agent_id"]: r for r in data["agent_success_rates"]}
        self.assertEqual(rates["backend"]["success_rate"], 100.0)
        self.assertEqual(rates["tester"]["success_rate"], 0.0)

    def test_dashboard_html_includes_observability_panel(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/") as r:
            html = r.read().decode("utf-8")
        self.assertIn("/api/observability", html)
        self.assertIn("successRatesList", html)


if __name__ == "__main__":
    unittest.main()
