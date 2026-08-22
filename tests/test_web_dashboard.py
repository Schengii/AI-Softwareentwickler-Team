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
        # Jobs schreiben jetzt auch ins Backlog (core/backlog_store.py) - gegen ein
        # temporäres Verzeichnis statt der echten memory/backlog.json (dasselbe Prinzip wie
        # tests/test_cost_history_integration.py für COST_HISTORY_FILE).
        cls._backlog_dir = tempfile.mkdtemp()
        cls._backlog_patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(cls._backlog_dir) / "backlog.json")
        cls._backlog_patcher.start()
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
        # mehreren Testdateien mit demselben Muster in derselben `unittest discover`-Suite
        # führte das reproduzierbar zu einem minutenlangen Hänger der vollen Suite.
        cls.server_state.shutdown()
        cls._process_patcher.stop()
        cls._backlog_patcher.stop()

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

        # Das Ticket landet im gemeinsamen Backlog (core/backlog_store.py) mit demselben
        # Endstatus wie der Job - sichtbar über /api/backlog, unabhängig vom job_id-Polling.
        backlog = self._get_json("/api/backlog")
        ticket = next(t for t in backlog["tickets"] if t["id"] == f"dashboard-{job_id}")
        self.assertEqual(ticket["status"], "done")
        self.assertEqual(ticket["source"], "dashboard")

    def test_unknown_job_id_returns_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/status/does-not-exist")
        self.assertEqual(ctx.exception.code, 404)

    def test_failed_job_notifies_externally(self):
        """
        Realer Fund: ein fehlgeschlagener Dashboard-Job war nur sichtbar, wenn jemand aktiv
        ins Dashboard schaute - anders als bei interface/cli.py sieht hier niemand zwangsläufig
        zu, da Jobs als Hintergrund-Worker laufen (core/notifier.py, no-op ohne konfigurierten
        Webhook).
        """
        async def _failing_process(self, prompt, status_callback=None, cancel_requested=None):
            raise RuntimeError("LLM-Aufruf fehlgeschlagen")

        with patch.object(Orchestrator, "process", _failing_process), \
             patch("interface.web_dashboard.notify_external") as mock_notify:
            req = urllib.request.Request(
                f"http://127.0.0.1:{PORT}/api/run",
                data=json.dumps({"prompt": "Kaputte Aufgabe"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req) as r:
                job_id = json.loads(r.read())["job_id"]

            job_status = {}
            for _ in range(30):
                job_status = self._get_json(f"/api/status/{job_id}")
                if job_status["status"] in ("done", "error"):
                    break
                time.sleep(0.1)

            # notify_external() ist der ALLERLETZTE Schritt in _execute_job() (nach dem bereits
            # sichtbaren job_status/Ticket-Update) - eigenes kurzes Polling statt eines festen
            # Sleeps, um diese Race gegen den Hintergrund-Worker-Thread robust abzudecken.
            for _ in range(30):
                if mock_notify.called:
                    break
                time.sleep(0.05)

        self.assertEqual(job_status["status"], "error", msg=job_status)
        backlog = self._get_json("/api/backlog")
        ticket = next(t for t in backlog["tickets"] if t["id"] == f"dashboard-{job_id}")
        self.assertEqual(ticket["status"], "blocked")
        mock_notify.assert_called_once()
        self.assertIn("Dashboard-Job fehlgeschlagen", mock_notify.call_args[0][0])


class TestDashboardServerShutdown(unittest.TestCase):
    """
    Realer Fund: `DashboardServer.__init__` startet einen dauerhaften Hintergrund-Thread mit
    eigenem Asyncio-Event-Loop (`run_forever()`). Mehrere Testdateien (test_web_dashboard.py,
    test_observability_endpoint.py, test_dashboard_deploy.py, test_dashboard_security.py,
    test_dashboard_concurrency.py, test_dashboard_cancel.py) erzeugen je eine
    `DashboardServer()`-Instanz in `setUpClass`, aber `tearDownClass` stoppte davor nur den
    `ThreadingHTTPServer` (`httpd.shutdown()`) - der interne Event-Loop-Thread der
    `DashboardServer`-Instanz selbst lief als daemon-Thread unbegrenzt über das Testende hinaus
    weiter. Mit sechs solchen Testdateien in derselben `unittest discover`-Suite blieben
    entsprechend viele dauerhaft laufende Event-Loops gleichzeitig im Prozess zurück - die
    volle Suite hing sich dabei reproduzierbar minutenlang auf, obwohl jede Datei einzeln
    ausgeführt in unter 2s durchlief.
    """

    def test_shutdown_stops_the_background_event_loop_thread(self):
        server = DashboardServer()
        self.assertTrue(server._thread.is_alive())

        server.shutdown()

        self.assertFalse(server._thread.is_alive())

    def test_shutdown_leaves_no_pending_dispatch_task_behind(self):
        """
        Regression-Test für einen Code-Review-Fund: `shutdown()` rief bisher nur
        `loop.stop()` auf, ohne den dauerhaft laufenden `_dispatch_loop()`-Task vorher zu
        canceln - der Task blieb dabei als "pending" hängen und wurde erst beim späteren
        Garbage-Collect zerstört (`Task was destroyed but it is pending!`/`RuntimeError:
        Event loop is closed`-Rauschen am Ende der Testsuite). `shutdown()` muss den Task
        jetzt sauber fertigstellen, bevor der Thread endet.
        """
        server = DashboardServer()
        dispatch_task = server._dispatch_task
        self.assertIsNotNone(dispatch_task)

        server.shutdown()

        self.assertTrue(dispatch_task.done())
        self.assertTrue(dispatch_task.cancelled())


if __name__ == "__main__":
    unittest.main()
