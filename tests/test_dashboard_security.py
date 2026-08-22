"""
tests/test_dashboard_security.py – Testet die Absicherung des Web-Dashboards

Vorher band interface/web_dashboard.py per ThreadingHTTPServer(("", port), ...) auf ALLE
Netzwerk-Interfaces, ohne jede Authentifizierung – jeder im selben Netzwerk konnte über
POST /api/run einen vollen Agentenlauf mit echtem Datei-/Kommandozugriff auslösen. Dieser
Test stellt sicher, dass (1) run_dashboard() den Start auf einer nicht-lokalen Adresse ohne
Token verweigert, und (2) ein gesetztes DASHBOARD_AUTH_TOKEN wirklich von JEDEM Request
verlangt wird (echter HTTP-Request/Response-Zyklus, kein reines Unit-Mocking).
"""

import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import ANY, MagicMock, patch

import interface.web_dashboard as web_dashboard
from interface.web_dashboard import DashboardServer, make_handler, run_dashboard

PORT = 8220  # dediziert für diese Testklasse, um Konflikte mit test_web_dashboard.py (8199) zu vermeiden


class TestDashboardHostGuard(unittest.TestCase):
    """run_dashboard() darf ohne Token nicht auf eine nicht-lokale Adresse binden."""

    def test_refuses_non_loopback_host_without_token(self):
        # Muss VOR jedem echten Socket-Bind abbrechen – kein ThreadingHTTPServer-Aufruf nötig.
        with patch.object(web_dashboard, "DASHBOARD_AUTH_TOKEN", ""):
            with self.assertRaises(SystemExit):
                run_dashboard(port=PORT, host="0.0.0.0")

    def test_allows_non_loopback_host_with_token(self):
        # Nur prüfen, dass die Sicherheitssperre bei gesetztem Token NICHT greift – kein
        # echter Socket-Bind auf "0.0.0.0" (löst unter Windows sonst einen blockierenden
        # Firewall-Dialog aus), daher wird ThreadingHTTPServer selbst komplett gemockt.
        # DashboardServer wird ebenfalls gemockt: run_dashboard() erzeugt es intern (kein
        # Rückgabewert, den der Test greifen könnte), eine ECHTE Instanz würde einen
        # dauerhaften Hintergrund-Event-Loop-Thread starten (siehe
        # DashboardServer.shutdown()-Docstring), den dieser Test nie stoppen könnte.
        fake_httpd = MagicMock()
        fake_httpd.__enter__.return_value = fake_httpd
        fake_httpd.__exit__.return_value = False
        fake_server = MagicMock()
        fake_server.orchestrator._agents = {}
        with patch.object(web_dashboard, "DASHBOARD_AUTH_TOKEN", "geheim123"), \
             patch.object(web_dashboard, "DashboardServer", return_value=fake_server), \
             patch.object(web_dashboard, "ThreadingHTTPServer", return_value=fake_httpd) as mock_server_cls, \
             patch("builtins.print"):  # Start-Print enthält Emojis -> auf cp1252-Konsolen (Windows) sonst UnicodeEncodeError
            run_dashboard(port=PORT, host="0.0.0.0")  # darf NICHT raisen
        mock_server_cls.assert_called_once_with(("0.0.0.0", PORT), ANY)
        fake_httpd.serve_forever.assert_called_once()

    def test_default_host_is_loopback(self):
        self.assertEqual(web_dashboard.DASHBOARD_HOST, "127.0.0.1")


class TestDashboardTokenAuth(unittest.TestCase):
    """Ist ein Token konfiguriert, muss jeder Request ihn mitliefern."""

    TOKEN = "test-token-xyz"

    @classmethod
    def setUpClass(cls):
        cls._auth_patch = patch.object(web_dashboard, "DASHBOARD_AUTH_TOKEN", cls.TOKEN)
        cls._auth_patch.start()

        cls.server_state = DashboardServer()

        async def _fake_process(prompt, status_callback=None):
            return f"Ergebnis fuer: {prompt}"

        cls.server_state.orchestrator.process = _fake_process
        handler_cls = make_handler(cls.server_state)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", PORT + 1), handler_cls)
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
        cls._auth_patch.stop()

    def _base_url(self) -> str:
        return f"http://127.0.0.1:{PORT + 1}"

    def test_request_without_token_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"{self._base_url()}/api/status")
        self.assertEqual(ctx.exception.code, 401)

    def test_request_with_wrong_token_is_rejected(self):
        req = urllib.request.Request(
            f"{self._base_url()}/api/status",
            headers={"Authorization": "Bearer falsches-token"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 401)

    def test_request_with_correct_bearer_token_succeeds(self):
        req = urllib.request.Request(
            f"{self._base_url()}/api/status",
            headers={"Authorization": f"Bearer {self.TOKEN}"},
        )
        with urllib.request.urlopen(req) as r:
            data = json.loads(r.read())
        self.assertEqual(data["agents_count"], 33)

    def test_request_with_correct_query_token_succeeds(self):
        with urllib.request.urlopen(f"{self._base_url()}/api/status?token={self.TOKEN}") as r:
            data = json.loads(r.read())
        self.assertEqual(data["agents_count"], 33)

    def test_post_run_without_token_is_rejected(self):
        req = urllib.request.Request(
            f"{self._base_url()}/api/run",
            data=json.dumps({"prompt": "Baue eine App"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 401)


if __name__ == "__main__":
    unittest.main()
