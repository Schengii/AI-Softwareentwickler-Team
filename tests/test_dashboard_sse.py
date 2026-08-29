"""
tests/test_dashboard_sse.py – Tests für Dashboard SSE Streaming und Datei-Inspektor
"""

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock

import pytest

from interface.web_dashboard import DashboardServer, Job, make_handler


@pytest.fixture
def test_dashboard_server(tmp_path):
    server = DashboardServer(max_concurrent_jobs=2)
    # Mock workspace dir
    ws_mock = MagicMock()
    ws_mock.list_projects.return_value = ["test-project"]
    proj_dir = tmp_path / "test-project"
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "main.py").write_text("print('Hello Dashboard')", encoding="utf-8")
    (proj_dir / "README.md").write_text("# Test Project", encoding="utf-8")
    ws_mock.get_project_dir.return_value = proj_dir

    server.orchestrator._workspace = ws_mock

    handler_cls = make_handler(server)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    yield server, port, proj_dir

    httpd.shutdown()
    httpd.server_close()
    server.shutdown()


def test_dashboard_sse_stream_init_and_log(test_dashboard_server):
    server, port, _ = test_dashboard_server
    job_id = "test-job-sse-1"
    server.jobs[job_id] = Job(job_id=job_id, prompt="Test SSE Prompt", status="running", log=["Log 1", "Log 2"])

    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", f"/api/stream/{job_id}")
    resp = conn.getresponse()
    assert resp.status == 200
    assert "text/event-stream" in resp.getheader("Content-Type")

    # Read init event line
    line1 = resp.readline().decode("utf-8")
    line2 = resp.readline().decode("utf-8")
    assert "event: init" in line1
    init_data = json.loads(line2.replace("data: ", ""))
    assert init_data["status"] == "running"
    assert "Log 1" in init_data["log"]

    conn.close()


def test_dashboard_project_files_and_content(test_dashboard_server):
    server, port, proj_dir = test_dashboard_server

    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", "/api/project-files?project=test-project")
    resp = conn.getresponse()
    assert resp.status == 200
    data = json.loads(resp.read().decode("utf-8"))
    assert "files" in data
    paths = [f["path"] for f in data["files"]]
    assert "main.py" in paths
    assert "README.md" in paths

    conn.request("GET", "/api/project-file-content?project=test-project&path=main.py")
    resp_content = conn.getresponse()
    assert resp_content.status == 200
    content_data = json.loads(resp_content.read().decode("utf-8"))
    assert content_data["content"] == "print('Hello Dashboard')"

    conn.request("GET", "/api/project-diff?project=test-project")
    resp_diff = conn.getresponse()
    assert resp_diff.status == 200
    diff_data = json.loads(resp_diff.read().decode("utf-8"))
    assert "diff" in diff_data

    conn.close()
