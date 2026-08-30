"""
tests/test_dashboard_token_progress.py – Testet das neue Live-Token-Verbrauchs-SSE-Event

Vorher war der Tokenverbrauch eines laufenden Dashboard-Jobs unterwegs unsichtbar: nur der
Abschlussbericht (nach Jobende) oder ein harter Abbruch bei MAX_RUN_TOKENS zeigten je einen
Stand. interface/web_dashboard.py.DashboardServer._execute_job pusht jetzt ein "tokens"-SSE-
Event (Delta seit Jobstart, dasselbe Prinzip wie Orchestrator._tokens_used_since()) - hier
mindestens einmal garantiert VOR dem finalen "status"-Event, unabhängig vom periodischen
TOKEN_PROGRESS_INTERVAL_SECONDS-Intervall (kein sleep()-Timing im Test nötig).
"""

import json
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.token_guard import token_guard
from interface.web_dashboard import DashboardServer, make_handler

PORT = 8275  # dediziert, um Konflikte mit den anderen Dashboard-Testdateien zu vermeiden (8199/8220/8231/8242/8253/8264 bereits vergeben)


class TestDashboardTokenProgress(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.release = threading.Event()

        async def _fake_process_with_token_usage(self, prompt, status_callback=None, cancel_requested=None):
            # Simuliert echten Tokenverbrauch während des Laufs, wie ihn core/llm_factory.py
            # bei jedem echten Modellaufruf über token_guard.record_usage() meldet.
            token_guard.record_usage("gemini-3.6-flash", prompt_tokens=100, completion_tokens=50)
            # Kurz auf das externe Freigabesignal warten (blockiert den Event-Loop NICHT), damit
            # der Test-Client seinen SSE-Stream sicher VOR Jobende verbinden kann - sonst wäre
            # das finale "tokens"-Event schon verpuppt, bevor überhaupt ein Listener lauscht.
            import asyncio
            while not cls.release.is_set():
                await asyncio.sleep(0.02)
            return f"Ergebnis fuer: {prompt}"

        cls._process_patcher = patch.object(Orchestrator, "process", _fake_process_with_token_usage)
        cls._process_patcher.start()
        cls.server_state = DashboardServer(max_concurrent_jobs=2)
        handler_cls = make_handler(cls.server_state)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", PORT), handler_cls)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.server_state.shutdown()
        cls._process_patcher.stop()

    def test_tokens_event_reaches_client_before_final_status(self):
        body = json.dumps({"prompt": "Live-Token-Test"}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/run", data=body, method="POST",
                                      headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            job_id = json.loads(resp.read())["job_id"]

        events: list[dict] = []
        read_error: list[BaseException] = []

        def _read_stream():
            # Realer Fund (CI-Flake): frühere Version brach still ab, ohne den Fehler dem
            # Haupt-Thread mitzuteilen - ein Timeout/Verbindungsfehler hier hätte NUR einen
            # unvollständigen events-Stand hinterlassen, statt den Test sichtbar fehlschlagen
            # zu lassen (reader.is_alive() wird nach einer Exception ebenfalls False).
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/stream/{job_id}", timeout=5) as stream:
                    evt_type = None
                    for raw_line in stream:
                        line = raw_line.decode("utf-8").strip()
                        if line.startswith("event:"):
                            evt_type = line.split(":", 1)[1].strip()
                        elif line.startswith("data:") and evt_type:
                            events.append({"type": evt_type, **json.loads(line.split(":", 1)[1].strip())})
                            if evt_type == "status" and events[-1]["status"] in ("done", "error", "cancelled"):
                                break
            except BaseException as exc:  # noqa: BLE001 - bewusst breit, siehe Kommentar oben
                read_error.append(exc)

        reader = threading.Thread(target=_read_stream, daemon=True)
        reader.start()
        # Kurz warten, bis der SSE-Handler den Listener registriert hat (siehe init-Event in
        # interface/web_dashboard.py), BEVOR der simulierte Job freigegeben wird - sonst könnte
        # der Job schon fertig sein, bevor überhaupt jemand zuhört.
        time.sleep(0.3)
        self.release.set()
        reader.join(timeout=5)
        self.assertFalse(reader.is_alive(), "SSE-Stream wurde nicht innerhalb des Timeouts abgeschlossen")
        if read_error:
            raise read_error[0]

        token_events = [e for e in events if e["type"] == "tokens"]
        self.assertTrue(token_events, f"kein 'tokens'-Event empfangen: {events}")
        # 100 Prompt- + 50 Completion-Tokens aus dem simulierten Aufruf oben.
        self.assertEqual(token_events[-1]["used"], 150)

        # NUR der finale/terminale status-Event zählt als Referenzpunkt - vorher kann bereits
        # ein status="running"-Event durchgekommen sein (job.status wird direkt bei Jobstart
        # gebroadcastet, siehe DashboardServer._execute_job), das wäre kein gültiger Vergleich.
        terminal_status_indices = [
            i for i, e in enumerate(events)
            if e["type"] == "status" and e.get("status") in ("done", "error", "cancelled")
        ]
        self.assertTrue(terminal_status_indices, f"kein finaler status-Event empfangen: {events}")
        terminal_status_index = terminal_status_indices[-1]
        last_tokens_index = max(i for i, e in enumerate(events) if e["type"] == "tokens")
        self.assertLess(
            last_tokens_index, terminal_status_index,
            "tokens-Event muss vor dem finalen status-Event ankommen",
        )


if __name__ == "__main__":
    unittest.main()
