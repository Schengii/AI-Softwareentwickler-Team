"""
tests/test_route_mismatch_preflight.py – Statischer Routen-Abgleich direkt nach der
Test-First-Entwicklungsphase (P4-4, ROADMAP_TEMP.md).

Realer Fund (synapsegate, 2026-09-20): Im Test-First-Modus schreibt `tester` seine Tests
PARALLEL zu `backend`, gegen `interface_contract.json`/die Akzeptanzkriterien statt gegen
echten Code. War der Vertrag unvollständig oder fehlte er (reines Backend-Projekt ohne
Frontend), erfand `tester` zwei nie deklarierte Routen (`POST /api/v1/events/`,
`GET /api/v1/events/dlq`). Der Completeness-Check deckte das auf - aber erst am Laufende,
NACHDEM performance/readme/qa_lead/security/resilience_guard bereits auf dem fehlerhaften
Stand weitergearbeitet hatten. `_run_test_route_mismatch_preflight()`
(agents/orchestrator/department.py) fängt denselben, rein statischen Befund jetzt direkt nach
der Entwicklungsphase ab, BEVOR die teuren Folgephasen starten.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agents.orchestrator import Orchestrator
from core.message_bus import AgentResult, AgentTask
from core.project_scaffold import is_safe_project_dir


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def orchestrator():
    return Orchestrator()


def _seed_synapsegate_style_mismatch(tmp_path: Path) -> None:
    """Reproduziert den realen synapsegate-Befund: ein deklarierter Endpunkt (`POST /`), ein
    Test, der zwei NICHT deklarierte Endpunkte aufruft."""
    _write(tmp_path / "app" / "__init__.py")
    _write(tmp_path / "app" / "api" / "__init__.py")
    _write(
        tmp_path / "app" / "api" / "events.py",
        'from fastapi import APIRouter\n\n'
        'router = APIRouter()\n\n'
        '@router.post("")\n'
        'async def create_event():\n'
        '    return {"ok": True}\n',
    )
    _write(
        tmp_path / "app" / "main.py",
        'from fastapi import FastAPI\n'
        'from app.api.events import router\n\n'
        'app = FastAPI()\n'
        'app.include_router(router, prefix="/api/v1/events")\n',
    )
    _write(
        tmp_path / "tests" / "test_events_api.py",
        'def test_create_event(client):\n'
        '    resp = client.post("/api/v1/events/")\n'
        '    assert resp.status_code == 200\n\n'
        'def test_dlq(client):\n'
        '    resp = client.get("/api/v1/events/dlq")\n'
        '    assert resp.status_code == 200\n',
    )


def _seed_matching_project(tmp_path: Path) -> None:
    """Kein Mismatch: der Test ruft ausschließlich real deklarierte Routen auf."""
    _write(tmp_path / "app" / "__init__.py")
    _write(
        tmp_path / "app" / "main.py",
        'from fastapi import FastAPI\n\n'
        'app = FastAPI()\n\n'
        '@app.get("/health")\n'
        'async def health():\n'
        '    return {"ok": True}\n',
    )
    _write(
        tmp_path / "tests" / "test_health.py",
        'def test_health(client):\n'
        '    resp = client.get("/health")\n'
        '    assert resp.status_code == 200\n',
    )


def _seed_unwired_router_project(tmp_path: Path) -> None:
    """Reproduziert den hyperion_metrics-Fund: ein Router, der nie include_router() bekommt."""
    _write(tmp_path / "app" / "__init__.py")
    _write(
        tmp_path / "app" / "ingestion.py",
        'from fastapi import APIRouter\n\n'
        'router = APIRouter()\n\n'
        '@router.post("/metrics")\n'
        'async def ingest():\n'
        '    return {"ok": True}\n',
    )
    _write(
        tmp_path / "app" / "main.py",
        'from fastapi import FastAPI\n\n'
        'app = FastAPI()\n\n'
        '@app.post("/api/v1/metrics")\n'
        'async def ingest_inline():\n'
        '    return {"ok": True}\n',
    )


class TestRouteMismatchPreflight:
    def test_no_mismatch_dispatches_nothing(self, orchestrator, tmp_path):
        _seed_matching_project(tmp_path)
        orchestrator._run_agents_parallel = AsyncMock(side_effect=AssertionError("darf nicht laufen"))

        asyncio.run(orchestrator._run_test_route_mismatch_preflight(
            str(tmp_path), [], {}, lambda m: None,
        ))
        # AssertionError wäre bei einem Aufruf hochgeschossen - kein Fund bedeutet kein Dispatch.

    def test_invented_test_route_dispatches_tester_fix(self, orchestrator, tmp_path):
        _seed_synapsegate_style_mismatch(tmp_path)
        dispatched: list[AgentTask] = []

        async def fake_parallel(tasks, notify=None):
            dispatched.extend(tasks)
            return [
                AgentResult(task_id=t.task_id, agent_id=t.agent_id, agent_name=t.agent_id, success=True, content="ok")
                for t in tasks
            ]

        orchestrator._run_agents_parallel = fake_parallel
        all_results: list[AgentResult] = []
        asyncio.run(orchestrator._run_test_route_mismatch_preflight(
            str(tmp_path), all_results, {}, lambda m: None,
        ))

        assert len(dispatched) == 1
        assert dispatched[0].agent_id == "tester"
        assert "api/v1/events/" in dispatched[0].description or "events/dlq" in dispatched[0].description
        assert len(all_results) == 1
        assert all_results[0].agent_id == "tester"

    def test_unwired_router_dispatches_to_file_owner(self, orchestrator, tmp_path):
        _seed_unwired_router_project(tmp_path)
        dispatched: list[AgentTask] = []

        async def fake_parallel(tasks, notify=None):
            dispatched.extend(tasks)
            return [
                AgentResult(task_id=t.task_id, agent_id=t.agent_id, agent_name=t.agent_id, success=True, content="ok")
                for t in tasks
            ]

        orchestrator._run_agents_parallel = fake_parallel
        file_owners = {"app/ingestion.py": "database"}
        asyncio.run(orchestrator._run_test_route_mismatch_preflight(
            str(tmp_path), [], file_owners, lambda m: None,
        ))

        assert len(dispatched) == 1
        # Der bekannte Datei-Eigentümer bekommt den Fix, nicht pauschal "backend".
        assert dispatched[0].agent_id == "database"
        assert "include_router" in dispatched[0].description

    def test_unwired_router_falls_back_to_backend_without_known_owner(self, orchestrator, tmp_path):
        _seed_unwired_router_project(tmp_path)
        dispatched: list[AgentTask] = []

        async def fake_parallel(tasks, notify=None):
            dispatched.extend(tasks)
            return [
                AgentResult(task_id=t.task_id, agent_id=t.agent_id, agent_name=t.agent_id, success=True, content="ok")
                for t in tasks
            ]

        orchestrator._run_agents_parallel = fake_parallel
        asyncio.run(orchestrator._run_test_route_mismatch_preflight(
            str(tmp_path), [], {}, lambda m: None,
        ))

        assert len(dispatched) == 1
        assert dispatched[0].agent_id == "backend"

    def test_framework_root_is_never_scanned(self, orchestrator):
        """Wie _run_integration_checkpoint(): project_dir='.' (Framework-Root, in Tests üblich)
        darf niemals gescannt werden - is_safe_project_dir() muss das bereits ausschließen."""
        assert not is_safe_project_dir(".")
        orchestrator._run_agents_parallel = AsyncMock(side_effect=AssertionError("darf nicht laufen"))

        asyncio.run(orchestrator._run_test_route_mismatch_preflight(
            ".", [], {}, lambda m: None,
        ))
        # Kein AssertionError => kein Scan, kein Dispatch, sofortige Rückkehr über den Guard.

    def test_unresolvable_check_completeness_error_does_not_raise(self, orchestrator, tmp_path, monkeypatch):
        """Best-Effort: ein interner Fehler im statischen Check darf den Lauf nicht abbrechen."""
        _seed_synapsegate_style_mismatch(tmp_path)

        def boom(self):
            raise RuntimeError("kaputt")

        monkeypatch.setattr("core.verifier.completeness.CompletenessMixin.check_completeness", boom)
        orchestrator._run_agents_parallel = AsyncMock(side_effect=AssertionError("darf nicht laufen"))

        # Wirft nicht - Best-Effort, wie jeder andere Pre-Flight-Checkpoint im selben Modul.
        asyncio.run(orchestrator._run_test_route_mismatch_preflight(
            str(tmp_path), [], {}, lambda m: None,
        ))


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
