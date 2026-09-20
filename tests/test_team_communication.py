"""
tests/test_team_communication.py – Team-Board, Übergaben, ask_teammate, Re-Export-Schutz

Analyse 2026-09-15: Agenten sahen voneinander nur Dateibaum + 3000 Zeichen Ergebnistext. Reale
Folgen: mehrere Rollen überschrieben `app/__init__.py`, der tester änderte `app/main.py`, der
security-Agent re-exportierte aus einem noch nicht existierenden Modul.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from agents.backend_agent import BackendAgent
from agents.orchestrator import Orchestrator
from core import team_board
from core.agent_toolbox import AgentToolbox
from core.handoff_check import check_handoff
from core.llm_factory import LLMResponse, ToolCall
from core.message_bus import AgentResult, AgentTask


def _write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestBoardBasics:
    def test_first_writer_owns_file_and_foreign_change_is_visible_to_owner(self, tmp_path):
        assert team_board.claim_file(tmp_path, "app/main.py", "backend") is None
        assert team_board.claim_file(tmp_path, "./app/main.py", "backend") is None
        assert team_board.claim_file(tmp_path, "app/main.py", "tester") == "backend"

        backend_view = team_board.format_for_agent(tmp_path, "backend")
        assert "app/main.py" in backend_view and "tester" in backend_view
        tester_view = team_board.format_for_agent(tmp_path, "tester")
        assert "app/main.py (backend)" in tester_view

    def test_begin_run_clears_previous_state(self, tmp_path):
        team_board.claim_file(tmp_path, "app/main.py", "backend")
        team_board.record_handoff(tmp_path, team_board.Handoff(agent_id="backend", files=["app/main.py"]))
        team_board.begin_run(tmp_path, "run2")
        state = team_board.load_board(tmp_path)
        assert state.run_id == "run2" and not state.claims and not state.handoffs

    def test_dotfiles_keep_their_name(self, tmp_path):
        team_board.claim_file(tmp_path, ".env.example", "devops")
        assert ".env.example" in team_board.load_board(tmp_path).claims

    def test_corrupt_board_starts_empty(self, tmp_path):
        _write(team_board.board_path(tmp_path), "{kaputt")
        assert team_board.load_board(tmp_path).claims == {}
        assert team_board.claim_file(tmp_path, "a.py", "backend") is None


class TestHandoffNotes:
    def test_key_lines_are_parsed(self):
        text = "Fertig.\n\nprovides: `GET /api/metrics` (app/api.py); `MetricsService`\nrequires: keine\nopen_issues: Rate-Limit fehlt"
        note = team_board.parse_handoff_note(text)
        assert note["provides"] == ["`GET /api/metrics` (app/api.py)", "`MetricsService`"]
        assert note.get("requires", []) == []
        assert note["open_issues"] == ["Rate-Limit fehlt"]

    def test_json_block_is_parsed(self):
        text = 'Bericht\n```json\n{"provides": ["A"], "requires": ["`B`"], "open_issues": []}\n```'
        assert team_board.parse_handoff_note(text) == {"provides": ["A"], "requires": ["`B`"], "open_issues": []}

    def test_derive_provides_lists_symbols_and_routes(self, tmp_path):
        _write(tmp_path / "app" / "api.py", "router = object()\n\n@router.get('/api/metrics')\nasync def metrics():\n    return {}\n\nclass _Hidden: ...\n")
        provides = team_board.derive_provides(tmp_path, ["app/api.py", "static/index.html"])
        assert "app/api.py: metrics, router" in provides
        assert "GET /api/metrics (app/api.py)" in provides

    def test_unmet_requirements_detects_missing_route_and_symbol(self, tmp_path):
        _write(tmp_path / "app" / "api.py", "@router.get('/api/metrics')\nasync def metrics():\n    return {}\n")
        team_board.record_handoff(tmp_path, team_board.Handoff(
            agent_id="frontend",
            requires=["`GET /api/metrics`", "Route /api/alerts für Alarme", "`AlertService` aus app/alerts.py", "gute Laune"],
        ))
        unmet = [req for _, req in team_board.unmet_requirements(tmp_path)]
        assert "Route /api/alerts für Alarme" in unmet
        assert "`AlertService` aus app/alerts.py" in unmet
        assert "`GET /api/metrics`" not in unmet
        assert "gute Laune" not in unmet

    def test_agent_role_name_in_backticks_is_not_treated_as_code_symbol(self, tmp_path):
        """Realer Fund (aegisflow/sentinedge/eventforge_core, 2026-09-19): der security-Agent
        formuliert seine Übergaben als "`backend` muss ...". `_SYMBOL_REF_RE` hielt den
        Rollennamen für ein Code-Symbol, das als `def backend` definiert sein müsste - die
        Anforderung galt dadurch DAUERHAFT als unerfüllt, `security_handoff` blockierte
        `verification_ok`, und kein Fix-Versuch konnte die Bedingung je erfüllen. `aegisflow`
        war fachlich grün und wurde allein dadurch rot."""
        _write(tmp_path / "app" / "main.py", "def setup_security(app):\n    return app\n")
        team_board.record_handoff(tmp_path, team_board.Handoff(
            agent_id="security",
            requires=["`backend` muss `setup_security(app)` in `app/main.py` aufrufen."],
        ))
        assert team_board.unmet_requirements(tmp_path) == []

    def test_annotated_assignment_counts_as_defined_symbol(self, tmp_path):
        """`ALLOWED_HOSTS: list[str] = ["*"]` (idiomatische pydantic-Settings-Form) matchte den
        alten Regex `\\bALLOWED_HOSTS\\s*=` nicht, weil `: list[str]` dazwischensteht -
        eventforge_core meldete drei tatsächlich vorhandene Settings-Felder als fehlend."""
        _write(tmp_path / "app" / "core" / "config.py",
               "class Settings:\n    ALLOWED_HOSTS: list[str] = [\"*\"]\n    CORS_ORIGINS: list[str] = [\"*\"]\n")
        team_board.record_handoff(tmp_path, team_board.Handoff(
            agent_id="security",
            requires=["In `app/core/config.py` `ALLOWED_HOSTS` und `CORS_ORIGINS` auf eine Whitelist umstellen."],
        ))
        assert team_board.unmet_requirements(tmp_path) == []

    def test_used_but_not_defined_symbol_counts_as_referenced(self, tmp_path):
        """`await conn.run_sync(...)` erfüllt die Anforderung "auf `run_sync` umstellen",
        definiert aber nichts - sentinedge meldete sie trotz Umsetzung als offen."""
        _write(tmp_path / "tests" / "conftest.py",
               "async def setup_db(conn):\n    await conn.run_sync(lambda c: None)\n")
        team_board.record_handoff(tmp_path, team_board.Handoff(
            agent_id="backend",
            requires=["`tester` muss `tests/conftest.py` auf `run_sync` umstellen."],
        ))
        assert team_board.unmet_requirements(tmp_path) == []

    def test_genuinely_missing_symbol_and_route_still_block(self, tmp_path):
        """Gegenprobe zu den drei Tests darüber: die Lockerung darf echte Lücken NICHT
        verschlucken. `POST /api/v1/dlq/replay` und `CircuitBreaker` existieren nicht - beides
        sind reale, korrekt erkannte Funde aus dem aegisflow-Lauf."""
        _write(tmp_path / "app" / "main.py", "@app.get('/api/v1/events')\nasync def events():\n    return []\n")
        team_board.record_handoff(tmp_path, team_board.Handoff(
            agent_id="resilience_guard",
            requires=["`backend` muss `CircuitBreaker` einbinden und `POST /api/v1/dlq/replay` registrieren."],
        ))
        unmet = [req for _, req in team_board.unmet_requirements(tmp_path)]
        assert len(unmet) == 1

    def test_contract_status_separates_implemented_and_planned(self, tmp_path):
        _write(tmp_path / "interface_contract.json", json.dumps({"modules": {
            "app/core/config.py": {"Settings": "class"}, "app/core/security.py": {"SecurityManager": "class"},
        }}))
        _write(tmp_path / "app" / "core" / "config.py", "class Settings: ...\n")
        implemented, planned = team_board.contract_status(tmp_path)
        assert implemented == ["app/core/config.py"]
        assert planned and planned[0].startswith("app/core/security.py")
        assert "NICHT importieren" in team_board.format_for_agent(tmp_path, "security")


class TestToolboxIntegration:
    def test_premature_reexport_in_package_init_is_rejected_until_module_exists(self, tmp_path):
        _write(tmp_path / "app" / "__init__.py")
        _write(tmp_path / "app" / "core" / "__init__.py")
        box = AgentToolbox(project_dir=tmp_path, agent_id="security")
        content = "from app.core.security import SecurityManager\n"
        result = asyncio.run(box._tool_write_file("app/core/__init__.py", content))
        assert "error" in result and "app.core.security" in result["error"]

        _write(tmp_path / "app" / "core" / "security.py", "class SecurityManager: ...\n")
        box._remember_content(tmp_path / "app" / "core" / "__init__.py", "")
        result = asyncio.run(box._tool_write_file("app/core/__init__.py", content))
        assert result.get("status") == "ok", result

    def test_relative_reexport_and_third_party_imports(self, tmp_path):
        _write(tmp_path / "app" / "__init__.py")
        box = AgentToolbox(project_dir=tmp_path, agent_id="backend")
        assert box._reject_if_premature_reexport("app/__init__.py", "from fastapi import FastAPI\n") is None
        assert box._reject_if_premature_reexport("app/__init__.py", "from .routes import router\n") is not None
        _write(tmp_path / "app" / "routes.py", "router = 1\n")
        assert box._reject_if_premature_reexport("app/__init__.py", "from .routes import router\n") is None

    def test_writing_a_teammates_file_returns_ownership_warning(self, tmp_path):
        backend = AgentToolbox(project_dir=tmp_path, agent_id="backend")
        assert asyncio.run(backend._tool_write_file("app/main.py", "x = 1\n")).get("status") == "ok"
        tester = AgentToolbox(project_dir=tmp_path, agent_id="tester")
        asyncio.run(tester._tool_read_file("app/main.py"))
        result = asyncio.run(tester._tool_write_file("app/main.py", "x = 2\n"))
        assert result.get("status") == "ok" and "gehört `backend`" in result.get("warning", "")

    def test_ask_teammate_without_team_returns_error(self, tmp_path):
        box = AgentToolbox(project_dir=tmp_path, agent_id="frontend")
        assert "error" in asyncio.run(box._tool_ask_teammate("backend", "Welche Route?"))

    def test_ask_teammate_uses_responder_records_answer_and_enforces_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.TEAMMATE_QUESTIONS_PER_AGENT", 1)
        calls: list[tuple] = []

        async def responder(asker, target, question, project_dir):
            calls.append((asker, target, question))
            return "GET /api/metrics liefert {cpu: float}"

        team_board.register_teammate_responder(tmp_path, responder)
        try:
            box = AgentToolbox(project_dir=tmp_path, agent_id="frontend")
            assert "error" in asyncio.run(box._tool_ask_teammate("frontend", "Selbstgespräch?"))
            result = asyncio.run(box._tool_ask_teammate("backend", "Welche Route liefert Metriken?"))
            assert result["answer"].startswith("GET /api/metrics")
            second = asyncio.run(box._tool_ask_teammate("backend", "Noch eine Frage?"))
            assert "error" in second
        finally:
            team_board.unregister_teammate_responder(tmp_path)
        assert calls == [("frontend", "backend", "Welche Route liefert Metriken?")]
        assert "Welche Route liefert Metriken?" in team_board.format_for_agent(tmp_path, "frontend")

    def test_read_only_toolbox_cannot_ask_teammates(self, tmp_path):
        box = AgentToolbox(project_dir=tmp_path, agent_id="backend", read_only=True)
        assert "ask_teammate" not in {t["name"] for t in box.tool_specs()}
        assert "error" in asyncio.run(box.dispatch("ask_teammate", {"agent_id": "frontend", "question": "x"}))


class TestHandoffCheck:
    def test_package_init_reexport_of_planned_module_is_still_a_finding(self, tmp_path):
        _write(tmp_path / "interface_contract.json", json.dumps({"modules": {"app/core/security.py": {"SecurityManager": "class"}}}))
        _write(tmp_path / "app" / "__init__.py")
        _write(tmp_path / "app" / "core" / "__init__.py", "from app.core.security import SecurityManager\n")
        report = check_handoff(tmp_path, ["app/core/__init__.py"])
        assert not report.passed


class _ScriptedLLM:
    model_name = "m"

    def __init__(self, responses):
        self.responses = responses
        self.calls = 0
        self.first_prompts: list[str] = []

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        if self.calls == 0:
            self.first_prompts.append(messages[0].text or "")
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


class TestAgentLoopIntegration:
    def test_agent_sees_board_and_leaves_handoff_note(self, tmp_path):
        team_board.record_handoff(tmp_path, team_board.Handoff(agent_id="database", files=["app/models.py"], provides=["`Webhook` (app/models.py)"]))
        llm = _ScriptedLLM([
            LLMResponse(text="", model_name="m", prompt_tokens=1, completion_tokens=1, total_tokens=2, tool_calls=[
                ToolCall(id="1", name="write_file", arguments={"path": "app/api.py", "content": "def list_webhooks():\n    return []\n"}),
            ]),
            LLMResponse(text="Fertig.\nprovides: `GET /api/webhooks`\nrequires: `Webhook` aus app/models.py\nopen_issues: keine",
                        model_name="m", prompt_tokens=1, completion_tokens=1, total_tokens=2, tool_calls=[]),
        ])
        agent = BackendAgent()
        agent._llm = llm
        result = asyncio.run(agent.execute(AgentTask(task_id="t", agent_id="backend", description="API", project_dir=str(tmp_path))))
        assert result.success
        assert "TEAM-BOARD" in llm.first_prompts[0] and "`Webhook` (app/models.py)" in llm.first_prompts[0]
        handoff = [h for h in team_board.load_board(tmp_path).handoffs if h.agent_id == "backend"][-1]
        assert handoff.files == ["app/api.py"]
        assert "`GET /api/webhooks`" in handoff.provides and "app/api.py: list_webhooks" in handoff.provides
        assert handoff.requires == ["`Webhook` aus app/models.py"]

    def test_code_writing_prompt_asks_for_handoff_lines(self):
        prompt = BackendAgent()._augment_with_tool_instructions("BASIS", read_only=False)
        assert "ask_teammate" in prompt and "provides:" in prompt


@pytest.fixture
def orchestrator():
    return Orchestrator()


class TestOrchestratorCommunication:
    def test_teammate_answer_runs_target_read_only_with_small_budget(self, orchestrator, tmp_path):
        seen: list[AgentTask] = []

        async def fake_execute(task):
            seen.append(task)
            return AgentResult(task_id=task.task_id, agent_id="backend", agent_name="Backend", success=True, content="Route: GET /api/x")

        orchestrator._agents["backend"].execute = fake_execute
        answer = asyncio.run(orchestrator._answer_teammate_question("frontend", "backend", "Welche Route?", str(tmp_path)))
        assert answer == "Route: GET /api/x"
        assert seen[0].tools_read_only and seen[0].max_tool_iterations <= 3
        assert "frontend" in seen[0].description

    def test_unknown_teammate_lists_available_roles(self, orchestrator, tmp_path):
        answer = asyncio.run(orchestrator._answer_teammate_question("frontend", "nobody", "?", str(tmp_path)))
        assert "Unbekannte Rolle" in answer and "backend" in answer

    def test_start_and_stop_register_responder(self, orchestrator, tmp_path):
        orchestrator._start_team_board(str(tmp_path), "r1")
        assert team_board.get_teammate_responder(tmp_path) is not None
        orchestrator._stop_team_board()
        assert team_board.get_teammate_responder(tmp_path) is None

    def test_integration_checkpoint_reports_unmet_requirements(self, orchestrator, tmp_path):
        _write(tmp_path / "app" / "__init__.py")
        _write(tmp_path / "app" / "main.py", "x = 1\n")
        team_board.record_handoff(tmp_path, team_board.Handoff(agent_id="frontend", requires=["Route /api/alerts"]))
        messages: list[str] = []
        lines = asyncio.run(orchestrator._run_integration_checkpoint(str(tmp_path), [], {}, messages.append))
        assert any("Team-Board" in line and "/api/alerts" in line for line in lines)

    def test_security_handoff_checkpoint_dispatches_fix_and_clears_when_resolved(self, orchestrator, tmp_path):
        """Regressionsschutz für den EventForge-Fund (KI-Team-Analyse 20260916_154524): der
        security-Agent forderte `app/core/security.py`, das NIE angelegt wurde - der bisherige
        Integrations-Checkpoint lief nur nach der Entwicklungsphase, lange bevor security
        überhaupt etwas prüfen konnte, und meldete den offenen Bedarf nur informativ."""
        team_board.record_handoff(
            tmp_path, team_board.Handoff(
                agent_id="security",
                requires=["Einbindung des SSRF-Schutzes `validate_relay_url` in app/core/security.py"],
            ),
        )

        async def fake_fix(task):
            _write(tmp_path / "app" / "core" / "security.py", "def validate_relay_url(url): return True\n")
            return AgentResult(task_id=task.task_id, agent_id="backend", agent_name="Backend", success=True, content="Fix implementiert.")

        orchestrator._agents["backend"].execute = fake_fix
        messages: list[str] = []
        asyncio.run(orchestrator._run_security_requirements_checkpoint(str(tmp_path), [], {}, messages.append))
        assert orchestrator._security_unmet_requirements == []

    def test_security_handoff_checkpoint_keeps_veto_when_unresolved(self, orchestrator, tmp_path):
        team_board.record_handoff(
            tmp_path, team_board.Handoff(
                agent_id="security", requires=["Einbindung von app/core/security.py für SSRF-Schutz"],
            ),
        )

        async def fake_noop_fix(task):
            return AgentResult(task_id=task.task_id, agent_id="backend", agent_name="Backend", success=True, content="Nichts geändert.")

        orchestrator._agents["backend"].execute = fake_noop_fix
        messages: list[str] = []
        asyncio.run(orchestrator._run_security_requirements_checkpoint(str(tmp_path), [], {}, messages.append))
        assert len(orchestrator._security_unmet_requirements) == 1
        assert orchestrator._security_unmet_requirements[0][0] == "security"

    def test_security_handoff_checkpoint_noop_without_open_requirements(self, orchestrator, tmp_path):
        messages: list[str] = []
        asyncio.run(orchestrator._run_security_requirements_checkpoint(str(tmp_path), [], {}, messages.append))
        assert orchestrator._security_unmet_requirements == []
