"""
tests/test_dashboard_session_and_tasks.py – Dashboard: nutzbare Token-Auth & sichere Hintergrund-Tasks

Realer Fund (Framework-Analyse 2026-09-10):
1. Mit DASHBOARD_AUTH_TOKEN sendete das eingebettete JavaScript bei keinem fetch()/EventSource
   einen Token - die Oberfläche scheiterte komplett an 401, und `?token=` blieb in URL/Verlauf.
2. Jobs/Deploys liefen als `loop.create_task()` ohne Referenz - Exceptions verschwanden spurlos.
"""

import asyncio
import http.client
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import interface.web_dashboard as web_dashboard
from interface.web_dashboard import AUTH_COOKIE_NAME, DashboardServer, make_handler

PORT = 8286  # dediziert (8199/8220/8221/8231/8242/8253/8264/8275 bereits von anderen Dashboard-Tests belegt)


class TestDashboardSessionCookie(unittest.TestCase):
    TOKEN = "cookie-token-123"

    @classmethod
    def setUpClass(cls):
        cls._auth_patch = patch.object(web_dashboard, "DASHBOARD_AUTH_TOKEN", cls.TOKEN)
        cls._auth_patch.start()
        cls.server_state = DashboardServer()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", PORT), make_handler(cls.server_state))
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.thread.join(timeout=2)
        cls.server_state.shutdown()
        cls._auth_patch.stop()

    def _get(self, path: str, headers: dict[str, str] | None = None) -> http.client.HTTPResponse:
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
        conn.request("GET", path, headers=headers or {})
        response = conn.getresponse()
        response.read()
        conn.close()
        return response

    def test_query_token_on_page_is_exchanged_for_httponly_cookie_and_removed_from_url(self):
        response = self._get(f"/?token={self.TOKEN}&tab=backlog")
        self.assertEqual(response.status, 303)
        self.assertEqual(response.getheader("Location"), "/?tab=backlog")
        cookie = response.getheader("Set-Cookie")
        self.assertIn(f"{AUTH_COOKIE_NAME}=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)

    def test_api_request_with_session_cookie_succeeds(self):
        response = self._get("/api/status", headers={"Cookie": f"{AUTH_COOKIE_NAME}={self.TOKEN}"})
        self.assertEqual(response.status, 200)

    def test_page_with_session_cookie_is_served_directly(self):
        response = self._get("/", headers={"Cookie": f"{AUTH_COOKIE_NAME}={self.TOKEN}"})
        self.assertEqual(response.status, 200)

    def test_wrong_cookie_is_rejected(self):
        response = self._get("/api/status", headers={"Cookie": f"{AUTH_COOKIE_NAME}=falsch"})
        self.assertEqual(response.status, 401)

    def test_wrong_query_token_does_not_set_cookie(self):
        response = self._get("/?token=falsch")
        self.assertEqual(response.status, 401)
        self.assertIsNone(response.getheader("Set-Cookie"))


class TestDashboardBackgroundTasks(unittest.TestCase):
    def setUp(self):
        self.server_state = DashboardServer()

    def tearDown(self):
        self.server_state.shutdown()

    def test_failing_background_task_is_logged_and_released(self):
        done = threading.Event()

        async def failing_deploy():
            try:
                raise RuntimeError("Deploy kaputt")
            finally:
                done.set()

        with self.assertLogs("interface.web_dashboard", level="ERROR") as logs:
            self.server_state._loop.call_soon_threadsafe(self.server_state._spawn, failing_deploy())
            self.assertTrue(done.wait(timeout=5))
            deadline = time.monotonic() + 5
            while self.server_state._background_tasks and time.monotonic() < deadline:
                time.sleep(0.02)

        self.assertIn("Deploy kaputt", logs.output[0])
        self.assertEqual(self.server_state._background_tasks, set())

    def test_running_task_is_strongly_referenced(self):
        started = threading.Event()
        release = asyncio.Event()

        async def long_running():
            started.set()
            await release.wait()

        self.server_state._loop.call_soon_threadsafe(self.server_state._spawn, long_running())
        self.assertTrue(started.wait(timeout=5))
        self.assertEqual(len(self.server_state._background_tasks), 1)
        self.server_state._loop.call_soon_threadsafe(release.set)


if __name__ == "__main__":
    unittest.main()
