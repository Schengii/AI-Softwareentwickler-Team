"""
tests/test_dashboard_cancel.py – Testet POST /api/cancel/<job_id> (interface/web_dashboard.py)

Vorher gab es im Dashboard keinen Weg, einen laufenden Job zu stoppen - nur Wegklicken der
Browser-Seite, der Job lief im Hintergrund-Worker unbeeinflusst weiter. DashboardServer.cancel()
setzt Job.cancel_requested, das der Worker als cancel_requested-Callback an
Orchestrator.process() durchreicht (dieselben Prüfpunkte wie das bestehende MAX_RUN_TOKENS-
Budget, siehe tests/test_run_cancellation.py für die Orchestrator-Seite selbst).

Nutzt einen ECHTEN HTTP-Server auf einem dedizierten Port (kein Mock des Request/Response-
Zyklus) - Orchestrator.process() wird durch eine schnelle, cancel_requested-bewusste Fake-
Funktion ersetzt, um echte API-Kosten im Test zu vermeiden. Realer Fund: Jobs bekommen seit
der Parallel-Jobs-Umstellung jeweils eine FRISCHE Orchestrator-Instanz - process() wird
deshalb auf KLASSENEBENE gepatcht (betrifft dadurch JEDE Instanz), nicht auf der einen
`server_state.orchestrator`-Instanz, die für echte Jobs gar nicht mehr verwendet wird.
"""

import asyncio
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

PORT = 8231  # dediziert, um Konflikte mit test_web_dashboard.py (8199) / test_dashboard_security.py (8220) zu vermeiden


async def _fake_cancellable_process(self, prompt, status_callback=None, cancel_requested=None):
    """Simuliert einen Lauf, der kooperativ auf cancel_requested() reagiert - wie der echte
    Orchestrator, der das vor jeder Fachbereichs-Phase abfragt."""
    for _ in range(50):  # max. ~5s, mehr als genug Zeit für einen Cancel-Request im Test
        if cancel_requested and cancel_requested():
            return "### Ergebnis (unvollständig)\n\n⏹️ Manuell abgebrochen: der Lauf wurde gestoppt."
        await asyncio.sleep(0.1)
    return f"Ergebnis fuer: {prompt}"


class TestDashboardCancel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._process_patcher = patch.object(Orchestrator, "process", _fake_cancellable_process)
        cls._process_patcher.start()
        cls._backlog_dir = tempfile.mkdtemp()
        cls._backlog_patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(cls._backlog_dir) / "backlog.json")
        cls._backlog_patcher.start()
        # max_concurrent_jobs=1: test_cancel_queued_job_never_runs verlässt sich darauf, dass
        # ein zweiter enqueue()ter Job garantiert wartet, statt mit dem Standard-Limit (2)
        # gleich mitzulaufen - echte Parallelität wird separat in
        # tests/test_dashboard_concurrency.py geprüft.
        cls.server_state = DashboardServer(max_concurrent_jobs=1)
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
        cls._backlog_patcher.stop()

    def _get_json(self, path: str) -> dict:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}") as r:
            return json.loads(r.read())

    def _post_json(self, path: str, body: dict | None = None) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"http://127.0.0.1:{PORT}{path}",
            data=json.dumps(body or {}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def _enqueue(self, prompt: str) -> str:
        status, data = self._post_json("/api/run", {"prompt": prompt})
        self.assertEqual(status, 202, msg=data)
        return data["job_id"]

    def _wait_for_status(self, job_id: str, statuses: tuple[str, ...], timeout: float = 5.0) -> dict:
        deadline = time.monotonic() + timeout
        job_status = {}
        while time.monotonic() < deadline:
            job_status = self._get_json(f"/api/status/{job_id}")
            if job_status["status"] in statuses:
                return job_status
            time.sleep(0.05)
        return job_status

    def test_cancel_unknown_job_returns_404(self):
        status, data = self._post_json("/api/cancel/does-not-exist")
        self.assertEqual(status, 404)

    def test_cancel_running_job_stops_it_and_marks_cancelled(self):
        job_id = self._enqueue("Baue eine App")
        self._wait_for_status(job_id, ("running",))

        status, data = self._post_json(f"/api/cancel/{job_id}")
        self.assertEqual(status, 200, msg=data)
        self.assertTrue(data["cancel_requested"])

        final = self._wait_for_status(job_id, ("done", "cancelled", "error"))
        self.assertEqual(final["status"], "cancelled", msg=final)
        self.assertIn("Manuell abgebrochen", final["result"])

    def test_cancel_queued_job_never_runs(self):
        # Erster Job hält den einzigen seriellen Worker beschäftigt (echtes Design, siehe
        # Moduldocstring von web_dashboard.py) - der zweite bleibt garantiert "queued".
        blocking_job_id = self._enqueue("Langer Lauf 1")
        self._wait_for_status(blocking_job_id, ("running",))

        queued_job_id = self._enqueue("Wird nie laufen")
        status, data = self._post_json(f"/api/cancel/{queued_job_id}")
        self.assertEqual(status, 200, msg=data)

        queued_status = self._get_json(f"/api/status/{queued_job_id}")
        self.assertEqual(queued_status["status"], "cancelled")

        # Aufräumen: den blockierenden Job selbst auch abbrechen, statt die volle Laufzeit
        # abzuwarten und andere Tests in dieser Klasse zu verlangsamen.
        self._post_json(f"/api/cancel/{blocking_job_id}")
        self._wait_for_status(blocking_job_id, ("done", "cancelled", "error"))

    def test_cancel_already_done_job_returns_404(self):
        job_id = self._enqueue("Kurzer Lauf")
        self._wait_for_status(job_id, ("running",))
        # Sofort abbrechen, damit der Job schnell fertig wird, statt die volle Fake-Laufzeit abzuwarten.
        self._post_json(f"/api/cancel/{job_id}")
        self._wait_for_status(job_id, ("done", "cancelled", "error"))

        status, data = self._post_json(f"/api/cancel/{job_id}")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
