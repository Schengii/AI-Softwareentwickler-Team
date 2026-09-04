"""
tests/test_contract_verifier.py – Tests für den API-Contract Lock (Frontend-Backend Abgleich).
"""

import tempfile
import unittest
from pathlib import Path

from core.contract_verifier import (
    extract_backend_endpoints,
    extract_frontend_api_calls,
    normalize_path,
    verify_api_contracts,
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


if __name__ == "__main__":
    unittest.main()
