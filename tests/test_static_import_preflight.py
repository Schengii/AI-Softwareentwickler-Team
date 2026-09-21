"""
tests/test_static_import_preflight.py – Testet die statische Import-Konsistenzprüfung
direkt nach der Entwicklungsphase (dev_lead) in agents/orchestrator/department.py.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agents.orchestrator import Orchestrator
from core.message_bus import AgentResult


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def orchestrator():
    return Orchestrator()


@pytest.mark.asyncio
async def test_static_import_preflight_no_issues_skips_dispatch(orchestrator, tmp_path):
    _write(tmp_path / "app" / "__init__.py")
    _write(tmp_path / "app" / "models.py", "class Item:\n    pass\n")
    _write(tmp_path / "app" / "main.py", "from app.models import Item\n")

    notified = []
    all_results = []
    file_owners = {"app/main.py": "backend"}

    orchestrator._run_agents_parallel = AsyncMock(return_value=[])

    await orchestrator._run_static_import_preflight(
        str(tmp_path), all_results, file_owners, notified.append
    )

    orchestrator._run_agents_parallel.assert_not_called()
    assert len(all_results) == 0


@pytest.mark.asyncio
async def test_static_import_preflight_dispatches_task_for_missing_import(orchestrator, tmp_path):
    # main.py importiert models.py, aber models.py existiert nicht
    _write(tmp_path / "app" / "__init__.py")
    _write(tmp_path / "app" / "main.py", "from app.models import Item\n")

    notified = []
    all_results = []
    file_owners = {"app/main.py": "backend"}

    mock_fix_result = AgentResult(
        task_id="dev_lead_missing_import_backend",
        agent_id="backend",
        agent_name="Backend-Entwickler",
        success=True,
        content="models.py angelegt",
        duration_seconds=0.5,
        model_used="fake",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        files_written=["app/models.py"],
    )

    orchestrator._run_agents_parallel = AsyncMock(return_value=[mock_fix_result])

    await orchestrator._run_static_import_preflight(
        str(tmp_path), all_results, file_owners, notified.append
    )

    orchestrator._run_agents_parallel.assert_called_once()
    tasks = orchestrator._run_agents_parallel.call_args[0][0]
    assert len(tasks) == 1
    assert tasks[0].agent_id == "backend"
    assert "Statischer Pre-Flight-Befund" in tasks[0].description
    assert "models.py" in tasks[0].description
    assert len(all_results) == 1
    assert any("Statischer Import-Pre-Flight" in msg for msg in notified)


@pytest.mark.asyncio
async def test_static_import_preflight_unsafe_root_dir_is_ignored(orchestrator):
    orchestrator._run_agents_parallel = AsyncMock(return_value=[])
    notified = []
    await orchestrator._run_static_import_preflight(".", [], {}, notified.append)
    orchestrator._run_agents_parallel.assert_not_called()
