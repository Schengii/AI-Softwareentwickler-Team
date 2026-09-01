"""
tests/test_dashboard_concurrency.py – Testet echte Parallelität mehrerer Dashboard-Jobs

Vorher liefen Jobs SERIELL in einem einzigen Hintergrund-Worker – ein zweiter Job musste
komplett warten, bis der erste fertig war, selbst wenn beide unabhängige Projekte betrafen.
interface/web_dashboard.py.DashboardServer nutzt jetzt einen persistenten asyncio-Event-Loop
mit einem Semaphore auf config.DASHBOARD_MAX_CONCURRENT_JOBS gleichzeitig LAUFENDE Jobs, jeder
mit einer frischen, isolierten Orchestrator-Instanz.

Nutzt einen ECHTEN HTTP-Server (kein Mock des Request/Response-Zyklus). Orchestrator.process()
wird durch eine steuerbare Fake-Funktion ersetzt, die explizit signalisiert, wann sie wirklich
zu laufen begonnen hat, und erst nach einem externen Freigabesignal zurückkehrt – so lässt sich
echte Überlappung deterministisch beweisen, statt sich auf Timing/sleep()-Heuristiken zu verlassen.
"""

import asyncio
import json
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import core.backlog_store as backlog_store
from agents.orchestrator import Orchestrator
from interface.web_dashboard import DashboardServer, make_handler

PORT = 8242  # dediziert, um Konflikte mit den anderen Dashboard-Testdateien zu vermeiden


class TestDashboardConcurrency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.started: dict[str, threading.Event] = {}
        cls.release = threading.Event()

        async def _fake_blocking_process(self, prompt, status_callback=None, cancel_requested=None):
            cls.started.setdefault(prompt, threading.Event()).set()
            while not cls.release.is_set():
                await asyncio.sleep(0.02)  # blockiert den Event-Loop NICHT, andere Jobs laufen weiter
            return f"Ergebnis fuer: {prompt}"

        cls._process_patcher = patch.object(Orchestrator, "process", _fake_blocking_process)
        cls._process_patcher.start()
        cls._backlog_dir = tempfile.mkdtemp()
        cls._backlog_patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(cls._backlog_dir) / "backlog.json")
        cls._backlog_patcher.start()
        cls.server_state = DashboardServer(max_concurrent_jobs=2)
        handler_cls = make_handler(cls.server_state)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", PORT), handler_cls)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.release.set()  # falls noch ein Job hängt - Server sauber beenden können
        cls.httpd.shutdown()
        cls.thread.join(timeout=2)
        # Ohne dies liefe der interne Event-Loop-Thread von DashboardServer (siehe
        # DashboardServer.shutdown()-Docstring) als daemon-Thread unbegrenzt weiter - bei
        # mehreren Testdateien mit demselben Muster in derselben `unittest discover`-Suite
        # führte das reproduzierbar zu einem minutenlangen Hänger der vollen Suite.
        cls.server_state.shutdown()
        cls._process_patcher.stop()
        cls._backlog_patcher.stop()

    def setUp(self):
        self.started.clear()
        self.release.clear()

    def _get_json(self, path: str) -> dict:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}") as r:
            return json.loads(r.read())

    def _enqueue(self, prompt: str) -> str:
        req = urllib.request.Request(
            f"http://127.0.0.1:{PORT}/api/run",
            data=json.dumps({"prompt": prompt}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())["job_id"]

    def _wait_for_status(self, job_id: str, statuses: tuple[str, ...], timeout: float = 5.0) -> dict:
        deadline = time.monotonic() + timeout
        job_status = {}
        while time.monotonic() < deadline:
            job_status = self._get_json(f"/api/status/{job_id}")
            if job_status["status"] in statuses:
                return job_status
            time.sleep(0.02)
        return job_status

    def test_two_jobs_run_truly_concurrently_within_the_limit(self):
        id_a = self._enqueue("Job A")
        id_b = self._enqueue("Job B")

        # Beide müssen innerhalb kurzer Zeit WIRKLICH gestartet sein - bei seriellem Verhalten
        # würde Job B erst starten, nachdem Job A (der auf self.release wartet) fertig ist,
        # und dieser wait() liefe in den Timeout.
        self.assertTrue(self.started.setdefault("Job A", threading.Event()).wait(timeout=3), "Job A nie gestartet")
        self.assertTrue(self.started.setdefault("Job B", threading.Event()).wait(timeout=3), "Job B nie gestartet - liefe seriell statt parallel")

        self.assertEqual(self._get_json(f"/api/status/{id_a}")["status"], "running")
        self.assertEqual(self._get_json(f"/api/status/{id_b}")["status"], "running")

        self.release.set()
        self.assertEqual(self._wait_for_status(id_a, ("done", "error"))["status"], "done")
        self.assertEqual(self._wait_for_status(id_b, ("done", "error"))["status"], "done")

    def test_third_job_waits_while_two_are_already_running(self):
        id_a = self._enqueue("Job C")
        id_b = self._enqueue("Job D")
        self.started.setdefault("Job C", threading.Event()).wait(timeout=3)
        self.started.setdefault("Job D", threading.Event()).wait(timeout=3)

        id_c = self._enqueue("Job E")  # 3. Job bei Limit 2 - muss warten, darf NICHT sofort starten
        time.sleep(0.3)  # kurzes Zeitfenster, in dem ein fälschlich sofort gestarteter Job sich zeigen würde

        self.assertFalse(self.started.get("Job E", threading.Event()).is_set(), "3. Job lief vorzeitig - Limit nicht durchgesetzt")
        self.assertEqual(self._get_json(f"/api/status/{id_c}")["status"], "queued")

        self.release.set()
        for job_id in (id_a, id_b, id_c):
            self.assertEqual(self._wait_for_status(job_id, ("done", "error"))["status"], "done")

    def test_independent_orchestrator_instances_dont_mix_conversation_history(self):
        """Der eigentliche Grund für die frühere Serialisierung war eine geteilte
        ConversationHistory - jeder Job muss jetzt sein eigenes, unvermischtes Gespräch haben."""
        seen_histories: list[int] = []

        async def _capture_history_identity(self, prompt, status_callback=None, cancel_requested=None):
            seen_histories.append(id(self._history))
            return f"Ergebnis fuer: {prompt}"

        with patch.object(Orchestrator, "process", _capture_history_identity):
            id_a = self._enqueue("Isoliert A")
            self._wait_for_status(id_a, ("done", "error"))
            id_b = self._enqueue("Isoliert B")
            self._wait_for_status(id_b, ("done", "error"))

        self.assertEqual(len(seen_histories), 2)
        self.assertNotEqual(seen_histories[0], seen_histories[1])  # zwei verschiedene Objekte


if __name__ == "__main__":
    unittest.main()
