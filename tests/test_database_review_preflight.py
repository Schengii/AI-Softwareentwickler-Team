"""
tests/test_database_review_preflight.py – Deterministischer database-Einsatz bei erkanntem ORM
(P2-3, ROADMAP_TEMP.md).

Realer Fund: über 20 ausgewertete Läufe lief der `database`-Agent nur 3×, obwohl SQLAlchemy-
Fehler (konkurrierende `Base`-Definitionen, `TypeError` in Modell-Tests) zu den häufigsten
echten Testfehlern gehören - der Planer wählt die Rolle beim Zerlegen fast nie. Da der
Tech-Stack bei einem neuen Projekt zur Planungszeit oft noch nicht feststeht, greift
`_run_database_review_preflight()` (agents/orchestrator/department.py) stattdessen NACH der
Entwicklungsphase, rein statisch (Textsuche in bereits geschriebenem Code, kein LLM-Aufruf).
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


def _seed_sqlalchemy_project(tmp_path: Path) -> None:
    _write(
        tmp_path / "app" / "models.py",
        "from sqlalchemy.orm import declarative_base\n\n"
        "Base = declarative_base()\n",
    )


def _seed_plain_project(tmp_path: Path) -> None:
    _write(
        tmp_path / "app" / "main.py",
        "from fastapi import FastAPI\n\napp = FastAPI()\n",
    )


class TestDatabaseReviewPreflight:
    def test_no_orm_dispatches_nothing(self, orchestrator, tmp_path):
        _seed_plain_project(tmp_path)
        orchestrator._run_agents_parallel = AsyncMock(side_effect=AssertionError("darf nicht laufen"))

        asyncio.run(orchestrator._run_database_review_preflight(str(tmp_path), [], lambda m: None))
        # AssertionError wäre bei einem Aufruf hochgeschossen - kein ORM bedeutet kein Dispatch.

    def test_orm_detected_dispatches_database_agent(self, orchestrator, tmp_path):
        _seed_sqlalchemy_project(tmp_path)
        dispatched: list[AgentTask] = []

        async def fake_parallel(tasks, notify=None):
            dispatched.extend(tasks)
            return [
                AgentResult(task_id=t.task_id, agent_id=t.agent_id, agent_name=t.agent_id, success=True, content="ok")
                for t in tasks
            ]

        orchestrator._run_agents_parallel = fake_parallel
        all_results: list[AgentResult] = []
        asyncio.run(orchestrator._run_database_review_preflight(str(tmp_path), all_results, lambda m: None))

        assert len(dispatched) == 1
        assert dispatched[0].agent_id == "database"
        assert len(all_results) == 1
        assert all_results[0].agent_id == "database"

    def test_database_already_involved_is_not_dispatched_again(self, orchestrator, tmp_path):
        _seed_sqlalchemy_project(tmp_path)
        orchestrator._run_agents_parallel = AsyncMock(side_effect=AssertionError("darf nicht erneut laufen"))
        prior = [AgentResult(task_id="t1", agent_id="database", agent_name="Database", success=True, content="ok")]

        asyncio.run(orchestrator._run_database_review_preflight(str(tmp_path), prior, lambda m: None))
        # Kein AssertionError => bereits beteiligter database-Agent wird nicht erzwungen.

    def test_database_agent_unavailable_dispatches_nothing(self, orchestrator, tmp_path):
        _seed_sqlalchemy_project(tmp_path)
        del orchestrator._agents["database"]
        orchestrator._run_agents_parallel = AsyncMock(side_effect=AssertionError("darf nicht laufen"))

        asyncio.run(orchestrator._run_database_review_preflight(str(tmp_path), [], lambda m: None))

    def test_framework_root_is_never_scanned(self, orchestrator):
        assert not is_safe_project_dir(".")
        orchestrator._run_agents_parallel = AsyncMock(side_effect=AssertionError("darf nicht laufen"))

        asyncio.run(orchestrator._run_database_review_preflight(".", [], lambda m: None))


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
