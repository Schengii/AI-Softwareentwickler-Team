"""
tests/test_dashboard_diff_viewer.py – Testet den Diff-Viewer-Endpunkt /api/diff/<job_id>
"""

import json
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

from interface.web_dashboard import DashboardServer, make_handler


class TestDashboardDiffViewer(unittest.TestCase):
    def setUp(self):
        self.server = DashboardServer()
        self.handler_cls = make_handler(self.server)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self.handler_cls)
        self.port = self.httpd.server_address[1]
        import threading
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.server.shutdown()

    def test_diff_endpoint_unknown_job(self):
        req = Request(f"http://127.0.0.1:{self.port}/api/diff/unknown_123")
        try:
            urlopen(req)
        except Exception as e:
            self.assertEqual(e.code, 404)

    def test_diff_endpoint_valid_job(self):
        job_id = self.server.enqueue("Test prompt")
        req = Request(f"http://127.0.0.1:{self.port}/api/diff/{job_id}")
        with urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["job_id"], job_id)
            self.assertIn("diff", data)
            self.assertIn("changed_files", data)
