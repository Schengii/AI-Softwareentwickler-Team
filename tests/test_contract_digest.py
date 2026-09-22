"""
tests/test_contract_digest.py – core/contract_digest.py: deterministischer Backend-Vertrags-
Auszug (Enum-Werte, Pydantic-Feldnamen, Routen-Präfixe, Response-Modelle) für den tester-Agenten
und Router-Import-Check für den backend-Agenten.

Regressionstest für pulse_queue-Fund (2026-09-22, Problem 2): Tester erfand Enum-Werte/Feldnamen.
Sprint-4-Erweiterungen (2026-09-22):
  - Route-Prefix-Digest: omnimetric_engine-Fund (Tester schrieb GET /stats statt GET /api/v1/stats)
  - Router-Import-Check: ecotrack_ai-Fund (Backend importierte nicht existierende Router)
  - Response-Model-Digest: eventforge-Fund (Tester nahm falsche Response-Struktur an)
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.contract_digest import (
    build_backend_contract_digest,
    build_route_prefix_digest,
    check_router_imports,
)


class TestBuildBackendContractDigest(unittest.TestCase):
    def test_extracts_enum_members_and_model_fields(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            models_dir = root / "app" / "models"
            models_dir.mkdir(parents=True)
            (models_dir / "job.py").write_text(
                "import enum\n"
                "from pydantic import BaseModel\n\n"
                "class JobType(str, enum.Enum):\n"
                "    email_dispatch = \"email_dispatch\"\n"
                "    data_export = \"data_export\"\n\n"
                "class JobCreate(BaseModel):\n"
                "    type: JobType\n"
                "    priority: int = 1\n",
                encoding="utf-8",
            )
            digest = build_backend_contract_digest(root)
            self.assertIn("JobType", digest)
            self.assertIn("data_export", digest)
            self.assertIn("email_dispatch", digest)
            self.assertIn("type: JobType", digest)
            # Nicht die verkürzte SCREAMING_SNAKE-Form, die der Tester real erfunden hatte.
            self.assertNotIn("DATA_EXPORT", digest)

    def test_ignores_test_files(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "tests").mkdir()
            (root / "tests" / "test_models.py").write_text(
                "import enum\n\nclass FakeType(enum.Enum):\n    A = 1\n", encoding="utf-8",
            )
            self.assertEqual(build_backend_contract_digest(root), "")

    def test_empty_project_returns_empty_string(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(build_backend_contract_digest(d), "")

    def test_missing_directory_returns_empty_string(self) -> None:
        self.assertEqual(build_backend_contract_digest("/does/not/exist"), "")


class TestBuildRoutePrefixDigest(unittest.TestCase):
    """Sprint-4: Routen-Präfixe und Response-Modelle per AST extrahieren.

    Realer Fund (omnimetric_engine): Tester schrieb `GET /stats` obwohl der echte Pfad
    `GET /api/v1/stats` ist – APIRouter hatte prefix="/api/v1" deklariert."""

    def _write(self, root: Path, rel: str, content: str) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_extracts_apirouter_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._write(root, "app/routers/stats.py",
                "from fastapi import APIRouter\n"
                "router = APIRouter(prefix='/api/v1/stats', tags=['stats'])\n"
            )
            digest = build_route_prefix_digest(root)
            self.assertIn("/api/v1/stats", digest)
            self.assertIn("APIRouter prefix", digest)

    def test_extracts_include_router_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._write(root, "app/main.py",
                "from fastapi import FastAPI\n"
                "from app.routers import stats\n"
                "app = FastAPI()\n"
                "app.include_router(stats.router, prefix='/api/v1')\n"
            )
            digest = build_route_prefix_digest(root)
            self.assertIn("/api/v1", digest)
            self.assertIn("include_router prefix", digest)

    def test_extracts_response_model(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._write(root, "app/routers/jobs.py",
                "from fastapi import APIRouter\n"
                "from app.schemas import JobResponse\n"
                "router = APIRouter()\n"
                "@router.get('/jobs/{id}', response_model=JobResponse)\n"
                "async def get_job(id: int): ...\n"
            )
            digest = build_route_prefix_digest(root)
            self.assertIn("response_model=`JobResponse`", digest)
            self.assertIn("GET", digest)

    def test_ignores_test_files(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._write(root, "tests/test_routes.py",
                "router = APIRouter(prefix='/fake')\n"
            )
            self.assertEqual(build_route_prefix_digest(root), "")

    def test_empty_project_returns_empty_string(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(build_route_prefix_digest(d), "")

    def test_missing_directory_returns_empty_string(self) -> None:
        self.assertEqual(build_route_prefix_digest("/does/not/exist"), "")


class TestCheckRouterImports(unittest.TestCase):
    """Sprint-4: Fehlende Router-Dateien aus app/main.py ImportFrom-Deklarationen erkennen.

    Realer Fund (ecotrack_ai): Backend importierte `from app.routers import users`
    in app/main.py, aber app/routers/users.py fehlte."""

    def _write(self, root: Path, rel: str, content: str) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_detects_missing_router_module(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._write(root, "app/main.py",
                "from app.routers.users import router as users_router\n"
                "from app.routers.jobs import router as jobs_router\n"
            )
            # Nur users.py anlegen, jobs.py fehlt
            self._write(root, "app/routers/users.py", "from fastapi import APIRouter\nrouter = APIRouter()\n")
            missing = check_router_imports(root)
            self.assertEqual(missing, ["app/routers/jobs.py"])

    def test_no_missing_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._write(root, "app/main.py",
                "from app.routers.users import router\n"
            )
            self._write(root, "app/routers/users.py", "from fastapi import APIRouter\nrouter = APIRouter()\n")
            self.assertEqual(check_router_imports(root), [])

    def test_no_main_py_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(check_router_imports(d), [])

    def test_ignores_non_app_imports(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._write(root, "app/main.py",
                "from fastapi import FastAPI\n"
                "from sqlalchemy import create_engine\n"
                "import uvicorn\n"
            )
            # Externe Imports (nicht app.*) werden nie als fehlend gemeldet
            self.assertEqual(check_router_imports(root), [])

    def test_accepts_package_init_as_existing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._write(root, "app/main.py",
                "from app.routers import users\n"
            )
            # Als Package mit __init__.py
            self._write(root, "app/routers/__init__.py", "")
            self.assertEqual(check_router_imports(root), [])

    def test_missing_directory_returns_empty_list(self) -> None:
        self.assertEqual(check_router_imports("/does/not/exist"), [])


if __name__ == "__main__":
    unittest.main()
