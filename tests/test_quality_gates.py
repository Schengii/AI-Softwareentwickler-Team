"""
tests/test_quality_gates.py – Testtiefe, erzwungener Werkzeug-Aufruf, rote Projekte, Watchdog

Analyse 2026-09-15:
- 7 Tests in 2 s galten bei einem Gateway-Projekt als ausreichend (core/test_depth.py)
- frontend lieferte 8.188 Tokens Code als Chat-Text ohne Werkzeug-Aufruf (require_tool_call)
- 8 rote Projekte wurden nie nachgebessert (core/red_project_repair.py)
- Fehlverhalten fiel erst nach der Aufgabe auf (core/agent_watchdog.py)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

import core.backlog_store as backlog_store
from agents.backend_agent import BackendAgent
from core.agent_watchdog import AgentWatchdog
from core.definition_of_done import build_definition_of_done
from core.llm_factory import LLMResponse, ToolCall, openai_tool_choice, require_tool_call, tool_call_required
from core.message_bus import AgentTask
from core.test_depth import analyze_test_depth


def _write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestTestDepth:
    def test_routes_with_prefix_and_params_count_as_tested(self, tmp_path):
        _write(tmp_path / "app" / "api.py", (
            "@router.get('/items/{item_id}')\ndef get_item(item_id: int): ...\n"
            "@router.post('/items')\ndef create(): ...\n"
            "@app.get('/health')\ndef health(): ...\n"
        ))
        _write(tmp_path / "tests" / "test_api.py", (
            "def test_get():\n    client.get('/api/items/42')\n"
            "def test_create():\n    client.post(f'/api/items')\n"
        ))
        report = analyze_test_depth(tmp_path, min_ratio=0.6)
        assert report.applicable and report.test_count == 2
        assert [r.path for r in report.untested_routes] == ["/health"]
        assert report.passed and abs(report.tested_ratio - 2 / 3) < 1e-9

    def test_shallow_suite_fails_and_lists_untested_routes(self, tmp_path):
        _write(tmp_path / "app" / "main.py", "".join(f"@app.get('/api/r{i}')\ndef r{i}(): ...\n" for i in range(5)))
        _write(tmp_path / "tests" / "test_main.py", "def test_one():\n    client.get('/api/r0')\n")
        report = analyze_test_depth(tmp_path)
        assert not report.passed
        assert "1/5 API-Routen" in report.format_summary() and "GET /api/r4" in report.format_summary()

    def test_routes_defined_in_tests_are_ignored_and_no_routes_is_not_applicable(self, tmp_path):
        _write(tmp_path / "tests" / "test_x.py", "@app.get('/fake')\ndef test_fake(): ...\n")
        report = analyze_test_depth(tmp_path)
        assert not report.applicable and report.passed

    def test_dod_blocks_on_shallow_tests(self, tmp_path):
        _write(tmp_path / "main.py", "print('x')\n")
        dod = build_definition_of_done("p", tmp_path, files_written=1, tests_ran=True, tests_passed=True,
                                       verification_ok=True, test_depth_ok=False)
        assert not dod.is_done and "test_depth" in [c.key for c in dod.blocking_criteria]
        dod_ok = build_definition_of_done("p", tmp_path, files_written=1, tests_ran=True, tests_passed=True,
                                          verification_ok=True, test_depth_ok=None)
        assert "test_depth" not in [c.key for c in dod_ok.blocking_criteria]


class TestForcedToolCall:
    def test_context_manager_controls_provider_choice(self):
        assert not tool_call_required() and openai_tool_choice() == "auto"
        with require_tool_call(True):
            assert tool_call_required() and openai_tool_choice() == "required"
            with require_tool_call(False):
                assert openai_tool_choice() == "auto"
        assert openai_tool_choice() == "auto"

    def _run(self, tmp_path, *, read_only=False):
        flags: list[bool] = []
        responses = [
            LLMResponse(text="", model_name="m", prompt_tokens=1, completion_tokens=1, total_tokens=2, tool_calls=[
                ToolCall(id="1", name="write_file", arguments={"path": "app/x.py", "content": "X = 1\n"}),
            ]),
            LLMResponse(text="Fertig.", model_name="m", prompt_tokens=1, completion_tokens=1, total_tokens=2, tool_calls=[]),
        ]

        class _LLM:
            model_name = "m"
            calls = 0

            async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
                flags.append(tool_call_required())
                r = responses[min(self.calls, len(responses) - 1)]
                self.calls += 1
                return r

        agent = BackendAgent()
        agent._llm = _LLM()
        asyncio.run(agent.execute(AgentTask(task_id="t", agent_id="backend", description="x",
                                            project_dir=str(tmp_path), tools_read_only=read_only)))
        return flags

    def test_first_iteration_of_code_role_requires_tool_call_then_auto(self, tmp_path):
        flags = self._run(tmp_path)
        assert flags[0] is True and flags[1] is False

    def test_read_only_task_is_never_forced(self, tmp_path):
        assert not any(self._run(tmp_path, read_only=True))

    def test_gemini_config_uses_mode_any_when_required(self):
        from google.genai import types as genai_types

        from core import llm_factory

        captured = {}
        original = genai_types.GenerateContentConfig

        def capture(**kwargs):
            captured.update(kwargs)
            raise RuntimeError("abbrechen nach Konfiguration")

        client = llm_factory.GeminiClient.__new__(llm_factory.GeminiClient)
        client.model_name = "gemini-3.8-flash"
        client._build_gemini_contents = lambda messages: []
        with patch.object(llm_factory, "_gemini_client", object()), patch.object(genai_types, "GenerateContentConfig", side_effect=capture):
            with require_tool_call(True), pytest.raises(RuntimeError):
                asyncio.run(client.generate_with_tools([], "sys", [{"name": "write_file", "parameters": {"type": "object", "properties": {}}}]))
        assert original is not None
        assert str(captured["tool_config"].function_calling_config.mode).endswith("ANY")


class TestRedProjectRepair:
    @pytest.fixture(autouse=True)
    def _backlog(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backlog_store, "BACKLOG_FILE", tmp_path / "backlog.json")

    def _project(self, root: Path, slug: str, ok: bool, **extra) -> None:
        entry = {"timestamp": "2026-09-15T10:00:00", "task_summary": "x", "verification_ok": ok,
                 "budget_aborted": False, "cancelled": False, "files_written_count": 3,
                 "failure_detail": "- ❌ 2 Testfehler in tests/test_api.py", **extra}
        _write(root / slug / ".ai_team_status.json", json.dumps([entry]))

    def test_red_projects_get_repair_ticket_once_and_green_ones_are_ignored(self, tmp_path):
        from core.red_project_repair import queue_red_projects

        ws = tmp_path / "ws"
        self._project(ws, "red_one", False)
        self._project(ws, "green_one", True)
        self._project(ws, "stopped", False, cancelled=True)
        report = queue_red_projects(ws)
        assert report.queued == ["red_one"]
        ticket = backlog_store.get_ticket("recurring-failure-red_one")
        assert ticket.status == "blocked" and ticket.source == "orchestrator" and "2 Testfehler" in ticket.detail
        assert queue_red_projects(ws).queued == []

    def test_exhausted_retries_and_limit_are_respected(self, tmp_path):
        from core.red_project_repair import queue_red_projects

        ws = tmp_path / "ws"
        for slug in ("a", "b", "c"):
            self._project(ws, slug, False)
        backlog_store.upsert_ticket("recurring-failure-a", "x", "orchestrator", "blocked", project_slug="a", retries=99)
        report = queue_red_projects(ws, max_new=1)
        assert report.queued == ["b"]
        assert "ausgeschöpft" in report.skipped["a"] and "Limit" in report.skipped["c"]

    def test_queued_ticket_is_picked_by_worker_retry_pool(self, tmp_path):
        from core.backlog_worker import _governance_retry_pool
        from core.red_project_repair import queue_red_projects

        ws = tmp_path / "ws"
        self._project(ws, "red_one", False)
        queue_red_projects(ws)
        assert [t.id for t in _governance_retry_pool(backlog_store.list_tickets())] == ["recurring-failure-red_one"]


class TestWatchdog:
    def test_read_without_write_fires_once_for_code_roles(self):
        dog = AgentWatchdog(agent_id="backend", code_writing=True, read_streak_limit=2)
        read = [("read_file", {"path": "a.py"})]
        assert dog.observe(prompt_tokens=10, completion_tokens=1, tool_calls=read, tool_results=[{}], files_written_count=0) == []
        second = dog.observe(prompt_tokens=10, completion_tokens=1, tool_calls=read, tool_results=[{}], files_written_count=0)
        assert [i.kind for i in second] == ["read_without_write"]
        assert dog.observe(prompt_tokens=10, completion_tokens=1, tool_calls=read, tool_results=[{}], files_written_count=0) == []
        reviewer = AgentWatchdog(agent_id="code_reviewer", code_writing=False)
        for _ in range(3):
            assert reviewer.observe(prompt_tokens=10, completion_tokens=1, tool_calls=read, tool_results=[{}], files_written_count=0) == []

    def test_repeated_rewrite_repeated_error_explosion_and_cap(self):
        dog = AgentWatchdog(agent_id="tester", code_writing=True, max_prompt_tokens=1000, task_token_cap=5000)
        write = [("write_file", {"path": "tests/test_a.py"})]
        kinds: list[str] = []
        for _ in range(3):
            kinds += [i.kind for i in dog.observe(prompt_tokens=10, completion_tokens=1, tool_calls=write, tool_results=[{"status": "ok"}], files_written_count=1)]
        assert "repeated_rewrite" in kinds
        err = [("edit_file", {"path": "x"})]
        dog.observe(prompt_tokens=10, completion_tokens=1, tool_calls=err, tool_results=[{"error": "old_text nicht gefunden"}], files_written_count=1)
        again = dog.observe(prompt_tokens=10, completion_tokens=1, tool_calls=err, tool_results=[{"error": "old_text nicht gefunden"}], files_written_count=1)
        assert "repeated_tool_error" in [i.kind for i in again]
        big = dog.observe(prompt_tokens=6000, completion_tokens=1, tool_calls=[], tool_results=[], files_written_count=1)
        assert {i.kind for i in big} == {"prompt_explosion", "task_token_cap"}
        assert any(i.compact for i in big) and any(i.stop for i in big)

    def test_agent_loop_receives_watchdog_hint_and_reports_event(self, tmp_path):
        _write(tmp_path / "app" / "a.py", "A = 1\n")
        seen: list[str] = []
        calls = {"n": 0}

        class _LLM:
            model_name = "m"

            async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
                seen.extend(m.text or "" for m in messages if m.role == "user")
                calls["n"] += 1
                if calls["n"] <= 3:
                    return LLMResponse(text="", model_name="m", prompt_tokens=1, completion_tokens=1, total_tokens=2,
                                       tool_calls=[ToolCall(id=str(calls["n"]), name="read_file", arguments={"path": "app/a.py", "force": True})])
                if calls["n"] == 4:
                    return LLMResponse(text="", model_name="m", prompt_tokens=1, completion_tokens=1, total_tokens=2,
                                       tool_calls=[ToolCall(id="w", name="write_file", arguments={"path": "app/b.py", "content": "B = 2\n"})])
                return LLMResponse(text="Fertig.", model_name="m", prompt_tokens=1, completion_tokens=1, total_tokens=2, tool_calls=[])

        agent = BackendAgent()
        agent._llm = _LLM()
        result = asyncio.run(agent.execute(AgentTask(task_id="t", agent_id="backend", description="x",
                                                     project_dir=str(tmp_path), max_tool_iterations=8)))
        assert result.success and "read_without_write" in result.watchdog_events
        assert any("WATCHDOG (read_without_write)" in text for text in seen)


class TestTestDepthInVerificationLoop:
    """End-to-End über Orchestrator.process() mit Fake-Verifier (Muster wie test_missing_tests_autofix)."""

    def test_green_but_shallow_suite_gets_one_tester_round_then_passes(self, tmp_path):
        import shutil
        import tempfile
        from unittest.mock import patch as mock_patch

        from agents.orchestrator import Orchestrator
        from core.test_depth import RouteRef, TestDepthReport
        from core.verifier import VerificationReport
        from core.workspace import WorkspaceManager
        from tests.test_missing_tests_autofix import _FakeToolCapableLLM

        passed = VerificationReport(ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1)
        shallow = TestDepthReport(routes=[RouteRef("GET", "/api/a", "app/main.py"), RouteRef("GET", "/api/b", "app/main.py")],
                                  untested_routes=[RouteRef("GET", "/api/b", "app/main.py"), RouteRef("GET", "/api/a", "app/main.py")])
        deep = TestDepthReport(routes=list(shallow.routes), untested_routes=[])

        workspace = tempfile.mkdtemp()
        try:
            orchestrator = Orchestrator()
            orchestrator._workspace = WorkspaceManager(workspace)
            for agent in list(orchestrator._agents.values()) + list(orchestrator._dept_leads.values()):
                agent._llm = _FakeToolCapableLLM()
            dispatched: list[str] = []
            original_parallel = orchestrator._run_agents_parallel

            async def spy(tasks, notify=None):
                dispatched.extend(t.task_id for t in tasks)
                return await original_parallel(tasks, notify=notify)

            orchestrator._run_agents_parallel = spy
            with mock_patch("agents.orchestrator.verification.ProjectVerifier") as verifier_cls, \
                 mock_patch("core.task_manager.TaskManager.decompose") as decompose, \
                 mock_patch("core.result_aggregator.ResultAggregator.synthesize") as synthesize, \
                 mock_patch("agents.orchestrator.verification.analyze_test_depth", side_effect=[shallow, deep]):
                decompose.return_value = ("Kurze Aufgabe", "depth_proj", [AgentTask(task_id="t1", agent_id="backend", description="API")])
                synthesize.return_value = ("### Fertig", 5)
                verifier = verifier_cls.return_value
                verifier.ensure_environment.return_value = ""
                verifier.run_tests.side_effect = [passed, passed, passed, passed]
                verifier.check_docker_build.return_value.attempted = False
                verifier.check_load_test.return_value.attempted = False
                verifier.check_dependency_vulnerabilities.return_value = []
                logs: list[str] = []
                asyncio.run(orchestrator.process("Baue eine API", status_callback=logs.append))
            assert any(task_id.startswith("test_depth_fix_") for task_id in dispatched)
            assert any("zu flach" in line for line in logs)
            assert orchestrator.last_verification_outcome.status("test_depth") is True
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


class TestFrontendBackendContractReview:
    """Analyse 2026-09-15: contract_verifier lief nie; das nexus-Dashboard rief GET /metrics ohne Backend-Route auf."""

    def test_mismatch_dispatches_one_backend_fix_round(self, tmp_path):
        from agents.orchestrator import Orchestrator
        from core.message_bus import AgentResult

        _write(tmp_path / "app" / "__init__.py")
        _write(tmp_path / "app" / "main.py", "from fastapi import FastAPI\napp = FastAPI()\n\n@app.get('/health')\ndef health():\n    return {}\n")
        _write(tmp_path / "static" / "index.html", "<script>fetch('/metrics').then(r => r.json())</script>")
        orchestrator = Orchestrator()
        dispatched: list = []

        async def fake_parallel(tasks, notify=None):
            dispatched.extend(tasks)
            _write(tmp_path / "app" / "main.py", "from fastapi import FastAPI\napp = FastAPI()\n\n@app.get('/health')\ndef health():\n    return {}\n\n@app.get('/metrics')\ndef metrics():\n    return {}\n")
            return [AgentResult(task_id=t.task_id, agent_id=t.agent_id, agent_name=t.agent_id, success=True, content="ok", files_written=["app/main.py"]) for t in tasks]

        orchestrator._run_agents_parallel = fake_parallel
        lines = asyncio.run(orchestrator._run_frontend_backend_contract_review(str(tmp_path), [], {}, lambda m: None, None))
        assert [t.agent_id for t in dispatched] == ["backend"] and "/metrics" in dispatched[0].description
        assert lines and "behoben" in lines[0]

    def test_dynamic_paths_and_router_prefixes_are_not_findings(self):
        from agents.orchestrator.integration import _is_contract_false_positive
        from core.contract_verifier import ContractMismatch, Endpoint, FrontendApiCall

        endpoints = [Endpoint(method="GET", path="/items/{item_id}", source_file="app/api.py")]
        dynamic = ContractMismatch("MISSING_ENDPOINT", FrontendApiCall("GET", "${BASE_URL}${url}", "src/api.ts"), "x")
        prefixed = ContractMismatch("MISSING_ENDPOINT", FrontendApiCall("GET", "/api/items/${id}", "src/api.ts"), "x")
        real = ContractMismatch("MISSING_ENDPOINT", FrontendApiCall("GET", "/api/metrics", "static/index.html"), "x")
        assert _is_contract_false_positive(dynamic, endpoints)
        assert _is_contract_false_positive(prefixed, endpoints)
        assert not _is_contract_false_positive(real, endpoints)


class TestPipInstallHintFix:
    """Realer Fund (ping_service, 2026-09-16): Starlette verlangt httpx2 - ohne ModuleNotFoundError."""

    def test_hint_packages_are_added_to_dev_manifest(self, tmp_path):
        from agents.orchestrator import Orchestrator

        _write(tmp_path / "requirements.txt", "fastapi\n")
        _write(tmp_path / "requirements-dev.txt", "pytest\n")
        output = (
            "E   RuntimeError: The starlette.testclient module requires the httpx2 package to be installed.\n"
            "E   You can install this with:\n"
            "E       $ pip install httpx2\n"
        )
        added = Orchestrator._apply_pip_install_hints(str(tmp_path), output)
        assert added == [("httpx2", "requirements-dev.txt")]
        assert "httpx2" in (tmp_path / "requirements-dev.txt").read_text(encoding="utf-8")
        assert Orchestrator._apply_pip_install_hints(str(tmp_path), output) == []

    def test_generic_install_commands_are_ignored(self, tmp_path):
        from agents.orchestrator import Orchestrator

        _write(tmp_path / "requirements.txt", "fastapi\n")
        assert Orchestrator._apply_pip_install_hints(str(tmp_path), "pip install -r requirements.txt") == []
