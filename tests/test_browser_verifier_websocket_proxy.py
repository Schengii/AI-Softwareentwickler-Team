"""
tests/test_browser_verifier_websocket_proxy.py – Regression fuer den WebSocket-Proxy-Luecke im
Browser-Verifier (Fund: entwickle_das_projekt_sentinel, 2026-09-17, drei Laeufe in Folge mit
identischem Fehler "Error during WebSocket handshake: 'Connection' header is missing").

Root Cause: `_make_static_handler()`s `QuietHandler` proxyte jede Anfrage ohne lokale Datei per
gepuffertem `http.client`-Request/Response-Zyklus an das Backend (siehe `_proxy_to_backend`) -
das kann niemals ein "101 Switching Protocols" durchreichen. Jedes Projekt mit echten
WebSockets, dessen Frontend ueber den statischen Playwright-Server (nicht direkt ueber
`backend_port`) ausgeliefert wird, scheiterte deshalb GARANTIERT am Browser-UI-Check - unabhaengig
davon, ob Frontend- und Backend-Code korrekt waren. Zwei fruehere Root-Cause-Tickets
(logstream_sentinel, syncwave) schrieben genau dieses Symptom faelschlich Agenten-Fehlern zu
(fehlendes `websockets`-Paket, falscher Client) und blieben deshalb wirkungslos.
"""

import os
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.browser_verifier import BrowserVerifier


def _fake_ws_backend(host: str = "127.0.0.1") -> tuple[socket.socket, int, threading.Thread]:
    """Minimaler TCP-Server, der jeden Handshake mit Upgrade-Header akzeptiert
    (101 Switching Protocols) und alles andere mit 404 beantwortet - genug, um zu pruefen,
    ob der Proxy die Roh-Bytes des Handshakes unveraendert durchreicht."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind((host, 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def _serve():
        try:
            conn, _ = srv.accept()
        except OSError:
            return
        try:
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                data += chunk
            if b"upgrade: websocket" in data.lower():
                conn.sendall(
                    b"HTTP/1.1 101 Switching Protocols\r\n"
                    b"Upgrade: websocket\r\nConnection: Upgrade\r\n\r\n"
                )
            else:
                conn.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
        finally:
            conn.close()

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    return srv, port, t


class TestWebSocketUpgradeIsProxiedToBackend(unittest.TestCase):
    def test_upgrade_request_reaches_backend_and_gets_101(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "index.html").write_text("<html><title>x</title></html>", encoding="utf-8")

            backend_srv, backend_port, backend_thread = _fake_ws_backend()
            try:
                verifier = BrowserVerifier(base)
                Handler = verifier._make_static_handler(str(base), backend_port)
                import http.server

                httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
                server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                server_thread.start()
                try:
                    proxy_port = httpd.server_address[1]
                    client = socket.create_connection(("127.0.0.1", proxy_port), timeout=5)
                    try:
                        client.sendall(
                            b"GET /ws/live HTTP/1.1\r\n"
                            b"Host: 127.0.0.1\r\n"
                            b"Upgrade: websocket\r\n"
                            b"Connection: Upgrade\r\n"
                            b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                            b"Sec-WebSocket-Version: 13\r\n\r\n"
                        )
                        client.settimeout(5)
                        response = client.recv(4096)
                    finally:
                        client.close()
                finally:
                    httpd.shutdown()
                    server_thread.join(timeout=5)
            finally:
                backend_srv.close()
                backend_thread.join(timeout=5)

            self.assertIn(b"101", response, response)
            self.assertIn(b"Upgrade", response, response)


if __name__ == "__main__":
    unittest.main()
