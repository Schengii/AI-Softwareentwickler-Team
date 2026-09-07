"""
tests/test_contract_verifier.py – Tests für den API-Contract Lock (Frontend-Backend Abgleich).
"""

import tempfile
import unittest
from pathlib import Path

from core.contract_verifier import (
    extract_backend_endpoints,
    extract_frontend_api_calls,
    extract_python_client_calls,
    normalize_path,
    verify_api_contracts,
    verify_cross_project_contract,
)


class TestContractVerifier(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_normalize_path(self):
        self.assertEqual(normalize_path("/api/notes"), "/api/notes")
        self.assertEqual(normalize_path("/api/notes/"), "/api/notes")
        self.assertEqual(normalize_path("/api/notes/{id}"), "/api/notes/:param")
        self.assertEqual(normalize_path("/api/notes/${noteId}"), "/api/notes/:param")
        self.assertEqual(normalize_path("/api/users/<int:user_id>"), "/api/users/:param")
        self.assertEqual(normalize_path("/search?q=test&limit=10"), "/search")

    def test_extract_fastapi_endpoints(self):
        py_code = """
from fastapi import FastAPI

app = FastAPI()

@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.post("/api/notes")
def create_note():
    pass

@app.delete("/api/notes/{note_id}")
def delete_note(note_id: int):
    pass
"""
        (self.project_dir / "main.py").write_text(py_code, encoding="utf-8")
        endpoints = extract_backend_endpoints(self.project_dir)
        self.assertEqual(len(endpoints), 3)

        methods_paths = {(ep.method, ep.normalized_path) for ep in endpoints}
        self.assertIn(("GET", "/api/health"), methods_paths)
        self.assertIn(("POST", "/api/notes"), methods_paths)
        self.assertIn(("DELETE", "/api/notes/:param"), methods_paths)

    def test_extract_flask_endpoints(self):
        py_code = """
from flask import Flask

app = Flask(__name__)

@app.route("/api/v1/items", methods=["GET", "POST"])
def items():
    pass

@app.route("/api/v1/items/<id>", methods=["DELETE"])
def delete_item(id):
    pass
"""
        (self.project_dir / "app.py").write_text(py_code, encoding="utf-8")
        endpoints = extract_backend_endpoints(self.project_dir)
        self.assertEqual(len(endpoints), 3)

        methods_paths = {(ep.method, ep.normalized_path) for ep in endpoints}
        self.assertIn(("GET", "/api/v1/items"), methods_paths)
        self.assertIn(("POST", "/api/v1/items"), methods_paths)
        self.assertIn(("DELETE", "/api/v1/items/:param"), methods_paths)

    def test_extract_frontend_calls(self):
        js_code = """
async function loadData() {
    const res = await fetch("/api/notes");
    const data = await res.json();
    
    await fetch("/api/notes", {
        method: "POST",
        body: JSON.stringify({ title: "New" })
    });

    const id = 42;
    await fetch(`/api/notes/${id}`, { method: 'DELETE' });

    await axios.get("/api/health");
}
"""
        static_dir = self.project_dir / "static"
        static_dir.mkdir(parents=True, exist_ok=True)
        (static_dir / "app.js").write_text(js_code, encoding="utf-8")

        calls = extract_frontend_api_calls(self.project_dir)
        self.assertEqual(len(calls), 4)

        methods_paths = {(c.method, c.normalized_path) for c in calls}
        self.assertIn(("GET", "/api/notes"), methods_paths)
        self.assertIn(("POST", "/api/notes"), methods_paths)
        self.assertIn(("DELETE", "/api/notes/:param"), methods_paths)
        self.assertIn(("GET", "/api/health"), methods_paths)

    def test_contract_verification_passed(self):
        backend_code = """
@app.get("/api/items")
def get_items(): pass

@app.post("/api/items")
def add_item(): pass
"""
        frontend_code = """
fetch("/api/items");
fetch("/api/items", { method: "POST" });
"""
        (self.project_dir / "main.py").write_text(backend_code, encoding="utf-8")
        (self.project_dir / "index.html").write_text(f"<script>{frontend_code}</script>", encoding="utf-8")

        report = verify_api_contracts(self.project_dir)
        self.assertTrue(report.passed)
        self.assertEqual(len(report.mismatches), 0)

    def test_contract_verification_missing_endpoint(self):
        backend_code = """
@app.get("/api/items")
def get_items(): pass
"""
        frontend_code = """
fetch("/api/wrong_endpoint");
"""
        (self.project_dir / "main.py").write_text(backend_code, encoding="utf-8")
        (self.project_dir / "script.js").write_text(frontend_code, encoding="utf-8")

        report = verify_api_contracts(self.project_dir)
        self.assertFalse(report.passed)
        self.assertEqual(len(report.mismatches), 1)
        self.assertEqual(report.mismatches[0].mismatch_type, "MISSING_ENDPOINT")

    def test_contract_verification_method_mismatch(self):
        backend_code = """
@app.get("/api/items")
def get_items(): pass
"""
        frontend_code = """
fetch("/api/items", { method: "DELETE" });
"""
        (self.project_dir / "main.py").write_text(backend_code, encoding="utf-8")
        (self.project_dir / "script.js").write_text(frontend_code, encoding="utf-8")

        report = verify_api_contracts(self.project_dir)
        self.assertFalse(report.passed)
        self.assertEqual(len(report.mismatches), 1)
        self.assertEqual(report.mismatches[0].mismatch_type, "METHOD_MISMATCH")


# KI-Team-Analyse 07.09.2026, Punkt 9 "Fehlende Interoperabilitäts-Tests zwischen generierten
# Projekten": core/contract_verifier.py.verify_cross_project_contract() gleicht ausgehende
# HTTP-Aufrufe EINES Workspace-Projekts gegen die Endpunkte eines ANDEREN ab.
class TestCrossProjectContract(unittest.TestCase):
    def setUp(self):
        self._caller_tmp = tempfile.TemporaryDirectory()
        self._provider_tmp = tempfile.TemporaryDirectory()
        self.caller_dir = Path(self._caller_tmp.name)
        self.provider_dir = Path(self._provider_tmp.name)

    def tearDown(self):
        self._caller_tmp.cleanup()
        self._provider_tmp.cleanup()

    def test_extract_python_client_calls_finds_literal_and_fstring_paths(self):
        (self.caller_dir / "client.py").write_text(
            'import requests\n'
            'BASE_URL = "http://taskpulse:8000"\n\n'
            'def notify():\n'
            '    requests.post(f"{BASE_URL}/api/events", json={})\n'
            '    requests.get("/api/notes")\n',
            encoding="utf-8",
        )
        calls = extract_python_client_calls(self.caller_dir)
        paths = {(c.method, c.raw_path) for c in calls}
        self.assertIn(("POST", "/api/events"), paths)
        self.assertIn(("GET", "/api/notes"), paths)

    def test_matching_endpoint_across_projects_passes(self):
        (self.caller_dir / "client.py").write_text(
            'import requests\n\ndef fetch():\n    requests.get("/api/notes")\n', encoding="utf-8",
        )
        (self.provider_dir / "main.py").write_text(
            'from fastapi import FastAPI\napp = FastAPI()\n\n'
            '@app.get("/api/notes")\ndef list_notes():\n    return []\n',
            encoding="utf-8",
        )
        report = verify_cross_project_contract(self.caller_dir, self.provider_dir)
        self.assertTrue(report.passed)
        self.assertEqual(report.mismatches, [])

    def test_missing_endpoint_in_provider_is_flagged(self):
        (self.caller_dir / "client.py").write_text(
            'import requests\n\ndef notify():\n    requests.post("/api/events")\n', encoding="utf-8",
        )
        (self.provider_dir / "main.py").write_text(
            'from fastapi import FastAPI\napp = FastAPI()\n\n'
            '@app.get("/api/notes")\ndef list_notes():\n    return []\n',
            encoding="utf-8",
        )
        report = verify_cross_project_contract(self.caller_dir, self.provider_dir)
        self.assertFalse(report.passed)
        self.assertEqual(len(report.mismatches), 1)
        self.assertEqual(report.mismatches[0].mismatch_type, "MISSING_ENDPOINT")

    def test_method_mismatch_across_projects_is_flagged(self):
        (self.caller_dir / "client.py").write_text(
            'import requests\n\ndef remove():\n    requests.delete("/api/notes")\n', encoding="utf-8",
        )
        (self.provider_dir / "main.py").write_text(
            'from fastapi import FastAPI\napp = FastAPI()\n\n'
            '@app.get("/api/notes")\ndef list_notes():\n    return []\n',
            encoding="utf-8",
        )
        report = verify_cross_project_contract(self.caller_dir, self.provider_dir)
        self.assertFalse(report.passed)
        self.assertEqual(report.mismatches[0].mismatch_type, "METHOD_MISMATCH")

    def test_no_client_calls_or_no_endpoints_skips_silently(self):
        report = verify_cross_project_contract(self.caller_dir, self.provider_dir)
        self.assertTrue(report.passed)
        self.assertEqual(report.mismatches, [])


if __name__ == "__main__":
    unittest.main()
