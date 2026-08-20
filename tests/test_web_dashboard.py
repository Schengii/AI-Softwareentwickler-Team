"""
tests/test_web_dashboard.py – Testet das Web-Dashboard (interface/web_dashboard.py)

Vorher war der Server nirgends im Projekt verdrahtet und der "Start"-Button loeste
serverseitig nichts aus. Dieser Test startet den echten HTTP-Server auf einem lokalen
Port und prueft den kompletten realen Request/Response-Zyklus (POST /api/run -> Polling
via GET /api/status/<job_id> -> fertiges Ergebnis) – Orchestrator.process() wird gemockt,
um echte API-Kosten im Test zu vermeiden, aber Threading/Job-Queue/HTTP-Handling laufen echt.

Realer Fund: Jobs bekommen seit der Parallel-Jobs-Umstellung (siehe
tests/test_dashboard_concurrency.py) jeweils eine FRISCHE Orchestrator-Instanz statt der
einen geteilten `server_state.orchestrator` - ein Mock auf DIESER einen Instanz hätte also
keine Wirkung mehr auf echte Jobs. Orchestrator.process() wird deshalb auf KLASSENEBENE
gepatcht (patch.object(Orchestrator, "process", ...)), betrifft dadurch JEDE Instanz.
"""

import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from interface.web_dashboard import DashboardServer, make_handler

PORT = 8199  # dediziert für Tests, um Konflikte mit einer evtl. laufenden echten Instanz zu vermeiden


async def _fake_process(self, prompt, status_callback=None, cancel_requested=None):
    if status_callback:
        status_callback("Phase 1: Starte...")
        status_callback("Phase 2: Fertig.")
    return f"Ergebnis fuer: {prompt}"


class TestWebDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._process_patcher = patch.object(Orchestrator, "process", _fake_process)
        cls._process_patcher.start()
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
        cls._process_patcher.stop()

    def _get_json(self, path: str) -> dict:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}") as r:
            return json.loads(r.read())

    def test_status_endpoint_reflects_real_orchestrator(self):
        status = self._get_json("/api/status")
        self.assertEqual(status["agents_count"], 33)
        self.assertEqual(status["departments_count"], 5)
        self.assertEqual(len(status["departments"]), 5)

    def test_index_page_loads_and_contains_start_button(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/") as r:
            html = r.read().decode("utf-8")
        self.assertIn("Projekt-Entwicklung starten", html)
        self.assertIn("/api/run", html)  # der Button muss wirklich einen echten Endpoint ansprechen

    def test_run_endpoint_rejects_empty_prompt(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{PORT}/api/run",
            data=json.dumps({"prompt": "  "}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)

    def test_full_run_and_poll_cycle_completes(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{PORT}/api/run",
            data=json.dumps({"prompt": "Baue eine Todo-App"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            self.assertEqual(r.status, 202)
            job_id = json.loads(r.read())["job_id"]

        job_status = {}
        for _ in range(30):
            job_status = self._get_json(f"/api/status/{job_id}")
            if job_status["status"] in ("done", "error"):
                break
            time.sleep(0.1)

        self.assertEqual(job_status["status"], "done", msg=job_status)
        self.assertIn("Ergebnis fuer: Baue eine Todo-App", job_status["result"])
        self.assertIn("Phase 1: Starte...", job_status["log"])

    def test_unknown_job_id_returns_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/status/does-not-exist")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
