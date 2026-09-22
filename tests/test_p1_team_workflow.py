"""
tests/test_p1_team_workflow.py – Arbeitsweise wie ein echtes Entwicklerteam (Team-Analyse 2026-09-15, P1):

3.1 Übergabe-Prüfung für Entwickler (core/handoff_check.py, agents/base_agent.py)
3.2 Review NACH der Verifikation inkl. Regressionstest (agents/orchestrator/integration.py)
3.3/3.4 Deterministisches Projektgerüst (core/project_scaffold.py)
3.5 Integrations-Checkpoint nach der Entwicklungsphase
3.6 Test-First: tester arbeitet in der Entwicklungsphase
3.7 Budget-Anteile je Fachbereich
3.8 Backend-verursachte UI-Fehler gehen an backend
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import agents.orchestrator.budget as budget_module
from agents.backend_agent import BackendAgent
from agents.orchestrator import Orchestrator
from agents.orchestrator.verification import _classify_browser_failure_owner
from config import BASE_DIR
from core.handoff_check import check_handoff
from core.llm_factory import LLMResponse, ToolCall
from core.message_bus import AgentResult, AgentTask
from core.project_scaffold import (
    STACK_FASTAPI,
    STACK_PYTHON,
    STACK_UNKNOWN,
    apply_scaffold,
    detect_stack,
    ensure_package_inits,
    is_safe_project_dir,
)
from core.verification_outcome import VerificationOutcome
from core.verifier.models import VerificationReport


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ── 3.3 / 3.4 Projektgerüst ────────────────────────────────────────────────────────────────
class TestProjectScaffold:
    def test_framework_root_and_workspace_are_never_targets(self, tmp_path):
        assert not is_safe_project_dir(BASE_DIR)
        assert not is_safe_project_dir(Path(BASE_DIR) / "workspace")
        assert not is_safe_project_dir(Path(BASE_DIR).parent)
        assert is_safe_project_dir(tmp_path)
        assert apply_scaffold(BASE_DIR, "Baue eine FastAPI").created == []
        assert ensure_package_inits(BASE_DIR) == []

    @pytest.mark.parametrize("request_text,expected", [
        ("Baue eine FastAPI Notizen-API", STACK_FASTAPI),
        ("Webhook-Gateway mit Dashboard", STACK_FASTAPI),
        ("Python CLI zum Umbenennen von Dateien", STACK_PYTHON),
        ("React Dashboard mit TypeScript", STACK_UNKNOWN),
    ])
    def test_detect_stack(self, tmp_path, request_text, expected):
        assert detect_stack(tmp_path, request_text) == expected

    def test_fastapi_scaffold_creates_structure_without_stubs(self, tmp_path):
        _write(tmp_path / "interface_contract.json", json.dumps({"modules": {
            "app/core/config.py": {"Settings": "class"}, "app/db/database.py": {"Base": "class"},
        }}))
        report = apply_scaffold(tmp_path, "FastAPI Aufgaben-API mit Datenbank und JWT Login")
        assert report.stack == STACK_FASTAPI
        for rel in ("app/__init__.py", "app/core/__init__.py", "app/db/__init__.py", "pytest.ini", ".env.example", "tests/conftest.py"):
            assert (tmp_path / rel).is_file(), rel
        conftest = (tmp_path / "tests/conftest.py").read_text(encoding="utf-8")
        assert "async_client" in conftest
        # Realer Fund (pulse_queue, 2026-09-22): conftest muss BEIDE Namen liefern (async_client
        # UND client als Alias), damit eine Umbenennung in eine Richtung die andere nicht bricht.
        assert "def client" in conftest, "client-Alias fehlt in conftest.py"
        assert "auth_headers" in conftest, "auth_headers-Fixture fehlt in conftest.py"
        # Sprint-4 (2026-09-22): poll_until-Helfer gegen async-Race-Conditions im Conftest
        assert "poll_until" in conftest, "poll_until-Helfer fehlt in conftest.py"
        runtime = (tmp_path / "requirements.txt").read_text(encoding="utf-8")
        dev = (tmp_path / "requirements-dev.txt").read_text(encoding="utf-8")
        assert "greenlet" in runtime and "PyJWT" in runtime and "python-multipart" in runtime
        assert "pytest-asyncio" in dev and "pytest" not in runtime
        assert not (tmp_path / "app" / "main.py").exists(), "keine Implementierungs-Stubs"
        assert "pythonpath = ." in (tmp_path / "pytest.ini").read_text(encoding="utf-8")
        assert "Projektgerüst" in report.format_for_agents()

    def test_existing_files_are_never_overwritten(self, tmp_path):
        _write(tmp_path / "requirements.txt", "flask\n")
        _write(tmp_path / "pytest.ini", "[pytest]\n")
        report = apply_scaffold(tmp_path, "FastAPI Service")
        assert (tmp_path / "requirements.txt").read_text(encoding="utf-8") == "flask\n"
        assert "requirements.txt" in report.skipped_existing

    def test_package_inits_only_below_package_roots(self, tmp_path):
        _write(tmp_path / "app" / "services" / "x.py", "")
        _write(tmp_path / "scripts" / "tool.py", "")
        _write(tmp_path / "examples" / "demo" / "run.py", "")
        _write(tmp_path / "tests" / "unit" / "test_a.py", "")
        created = ensure_package_inits(tmp_path)
        assert set(created) == {"app/__init__.py", "app/services/__init__.py"}


# ── 3.1 Übergabe-Prüfung ───────────────────────────────────────────────────────────────────
class TestHandoffCheck:
    def test_syntax_error_and_missing_local_module_are_reported(self, tmp_path):
        _write(tmp_path / "app" / "__init__.py")
        _write(tmp_path / "app" / "main.py", "from app.services.missing import thing\n")
        _write(tmp_path / "app" / "broken.py", "def f(:\n    pass\n")
        report = check_handoff(tmp_path, ["app/main.py", "app/broken.py"])
        text = "\n".join(report.issues)
        assert "Syntaxfehler" in text and "app/broken.py" in text
        assert "app/main.py" in text
        assert "ÜBERGABE-PRÜFUNG" in report.format_for_agent()

    def test_import_of_module_planned_for_teammate_is_not_a_finding(self, tmp_path):
        _write(tmp_path / "interface_contract.json", json.dumps({"modules": {"app/services/stats.py": {"Stats": "class"}}}))
        _write(tmp_path / "app" / "__init__.py")
        _write(tmp_path / "app" / "main.py", "from app.services.stats import Stats\n")
        assert check_handoff(tmp_path, ["app/main.py"]).passed

    def test_missing_init_is_fixed_deterministically(self, tmp_path):
        _write(tmp_path / "app" / "__init__.py")
        _write(tmp_path / "app" / "core" / "config.py", "X = 1\n")
        report = check_handoff(tmp_path, ["app/core/config.py"])
        assert "app/core/__init__.py" in report.auto_fixed and report.passed

    def test_framework_root_is_never_checked_or_modified(self):
        assert check_handoff(BASE_DIR, ["agents/base_agent.py"]).passed

    def test_agent_gets_handoff_feedback_and_fixes_before_finishing(self, tmp_path):
        agent = BackendAgent()
        responses = [
            LLMResponse(text="", model_name="m", prompt_tokens=1, completion_tokens=1, total_tokens=2, tool_calls=[
                ToolCall(id="1", name="write_file", arguments={"path": "app/main.py", "content": "from app.services.missing import helper\n"}),
            ]),
            LLMResponse(text="Fertig.", model_name="m", prompt_tokens=1, completion_tokens=1, total_tokens=2, tool_calls=[]),
            LLMResponse(text="", model_name="m", prompt_tokens=1, completion_tokens=1, total_tokens=2, tool_calls=[
                ToolCall(id="2", name="write_file", arguments={"path": "app/main.py", "content": "def fixed():\n    return 1\n"}),
            ]),
            LLMResponse(text="Korrigiert.", model_name="m", prompt_tokens=1, completion_tokens=1, total_tokens=2, tool_calls=[]),
        ]
        seen_prompts: list[str] = []

        class _LLM:
            model_name = "m"
            calls = 0

            async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
                seen_prompts.append(messages[-1].text or "")
                r = responses[min(self.calls, len(responses) - 1)]
                self.calls += 1
                return r

        agent._llm = _LLM()
        _write(tmp_path / "app" / "__init__.py")
        result = asyncio.run(agent.execute(AgentTask(task_id="t", agent_id="backend", description="API", project_dir=str(tmp_path))))
        assert result.success
        assert result.content == "Korrigiert."
        assert any("ÜBERGABE-PRÜFUNG" in p for p in seen_prompts)
        assert (tmp_path / "app" / "main.py").read_text(encoding="utf-8").startswith("def fixed")


# ── 3.8 UI-Fehler-Routing ──────────────────────────────────────────────────────────────────
class TestBrowserFailureRouting:
    @pytest.mark.parametrize("message", [
        "Failed to load resource: the server responded with a status of 500 (Internal Server Error)",
        "GET http://localhost:8000/api/stats 404 (Not Found)",
        "WebSocket connection failed: Error during WebSocket handshake: 'Connection' header is missing",
    ])
    def test_backend_signals_route_to_backend(self, message):
        assert _classify_browser_failure_owner([message], [], {"frontend", "backend"}) == "backend"

    def test_missing_static_asset_stays_with_frontend(self):
        msg = "Failed to load resource: the server responded with a status of 404 (Not Found) /static/app.js"
        assert _classify_browser_failure_owner([msg], [], {"frontend", "backend"}) == "frontend"


# ── 3.6 Test-First + 3.7 Phasenbudget + 4.5 Teamleiter nur bei Bedarf ───────────────────────
class _FakeLLM:
    model_name = "fake-model"

    def __init__(self, label: str):
        self.label = label

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        return LLMResponse(text=f"[{self.label}]", model_name=self.model_name, prompt_tokens=1, completion_tokens=1, total_tokens=2, tool_calls=[])

    async def generate_with_usage(self, prompt, system_prompt=None):
        return LLMResponse(text=f"[{self.label}]", model_name=self.model_name, prompt_tokens=1, completion_tokens=1, total_tokens=2)


@pytest.fixture
def orchestrator():
    orch = Orchestrator()
    for agent in list(orch._agents.values()) + list(orch._dept_leads.values()):
        agent._llm = _FakeLLM(agent.agent_id)
    return orch


class TestDepartmentWorkflow:
    def test_tester_runs_in_development_phase_right_after_developers(self, orchestrator):
        tasks = [
            AgentTask(task_id="1", agent_id="backend", description="API"),
            AgentTask(task_id="2", agent_id="tester", description="Tests"),
            AgentTask(task_id="3", agent_id="devops", description="Docker"),
        ]
        results, *_ = asyncio.run(orchestrator._run_department_hierarchy(
            user_request="API", task_summary="API", agent_tasks=tasks, project_dir=".", notify=lambda m: None,
        ))
        order = [r.agent_id for r in results]
        assert order.index("tester") < order.index("devops"), order
        assert "tester" not in [t.agent_id for t in tasks if False]
        assert "Test-First" in tasks[1].context

    def test_test_first_disabled_keeps_tester_in_qa_phase(self, orchestrator):
        tasks = [
            AgentTask(task_id="1", agent_id="backend", description="API"),
            AgentTask(task_id="2", agent_id="tester", description="Tests"),
        ]
        with patch("agents.orchestrator.department.ENABLE_TEST_FIRST", False):
            asyncio.run(orchestrator._run_department_hierarchy(
                user_request="API", task_summary="API", agent_tasks=tasks, project_dir=".", notify=lambda m: None,
            ))
        assert "Test-First" not in tasks[1].context

    def test_route_mismatch_preflight_runs_after_test_first_dev_phase(self, orchestrator):
        """P4-4 (ROADMAP_TEMP.md): der statische Routen-Abgleich läuft NUR im Test-First-Modus
        und NUR, wenn tester tatsächlich an der dev_lead-Phase beteiligt war - direkt nach ihr,
        vor QA/Reviews (wie der Einstiegspunkt-Pre-Flight direkt daneben)."""
        tasks = [
            AgentTask(task_id="1", agent_id="backend", description="API"),
            AgentTask(task_id="2", agent_id="tester", description="Tests"),
        ]
        orchestrator._run_test_route_mismatch_preflight = AsyncMock()
        asyncio.run(orchestrator._run_department_hierarchy(
            user_request="API", task_summary="API", agent_tasks=tasks, project_dir=".", notify=lambda m: None,
        ))
        orchestrator._run_test_route_mismatch_preflight.assert_awaited_once()

    def test_route_mismatch_preflight_skipped_without_test_first(self, orchestrator):
        tasks = [
            AgentTask(task_id="1", agent_id="backend", description="API"),
            AgentTask(task_id="2", agent_id="tester", description="Tests"),
        ]
        orchestrator._run_test_route_mismatch_preflight = AsyncMock()
        with patch("agents.orchestrator.department.ENABLE_TEST_FIRST", False):
            asyncio.run(orchestrator._run_department_hierarchy(
                user_request="API", task_summary="API", agent_tasks=tasks, project_dir=".", notify=lambda m: None,
            ))
        orchestrator._run_test_route_mismatch_preflight.assert_not_awaited()

    def test_optional_phase_skipped_when_core_phases_would_starve(self, orchestrator):
        with patch.object(budget_module, "MAX_RUN_TOKENS", 100_000), \
                patch.object(Orchestrator, "_tokens_used_since", return_value=70_000):
            # Generierungsbudget 85.000, verbraucht 70.000 -> Design (6%) + halbe Kernanteile passen nicht mehr.
            assert not orchestrator._phase_budget_allows("design_lead", 0, ["dev_lead", "qa_lead", "governance_lead"])
            assert orchestrator._phase_budget_allows("dev_lead", 0, ["qa_lead"])
        with patch.object(budget_module, "MAX_RUN_TOKENS", 100_000), \
                patch.object(Orchestrator, "_tokens_used_since", return_value=5_000):
            assert orchestrator._phase_budget_allows("design_lead", 0, ["dev_lead", "qa_lead", "governance_lead"])
        with patch.object(budget_module, "MAX_RUN_TOKENS", 0):
            assert orchestrator._phase_budget_allows("content_lead", 0, [])


# ── 3.5 Integrations-Checkpoint ────────────────────────────────────────────────────────────
class TestIntegrationCheckpoint:
    def test_deterministic_fixes_then_single_fix_round(self, orchestrator, tmp_path):
        _write(tmp_path / "requirements.txt", "fastapi\n")
        _write(tmp_path / "app" / "__init__.py")
        _write(tmp_path / "app" / "db" / "session.py", "import jwt\n")
        _write(tmp_path / "app" / "broken.py", "def f(:\n  pass\n")
        dispatched: list[AgentTask] = []

        async def fake_parallel(tasks, notify=None):
            dispatched.extend(tasks)
            _write(tmp_path / "app" / "broken.py", "def f():\n    pass\n")
            return [AgentResult(task_id=t.task_id, agent_id=t.agent_id, agent_name=t.agent_id, success=True, content="ok", files_written=["app/broken.py"]) for t in tasks]

        orchestrator._run_agents_parallel = fake_parallel
        lines = asyncio.run(orchestrator._run_integration_checkpoint(str(tmp_path), [], {"app/broken.py": "database"}, lambda m: None))
        assert (tmp_path / "app" / "db" / "__init__.py").is_file()
        assert "PyJWT" in (tmp_path / "requirements.txt").read_text(encoding="utf-8")
        assert [t.agent_id for t in dispatched] == ["database"]
        assert any("behoben" in line for line in lines)

    def test_checkpoint_never_runs_on_framework_root(self, orchestrator):
        orchestrator._run_agents_parallel = AsyncMock(side_effect=AssertionError("darf nicht laufen"))
        assert asyncio.run(orchestrator._run_integration_checkpoint(str(BASE_DIR), [], {}, lambda m: None)) == []


# ── 3.2 Review nach Verifikation ───────────────────────────────────────────────────────────
class TestReviewAfterVerification:
    def _run(self, orchestrator, tmp_path, regression_passes: bool):
        outcome = VerificationOutcome()
        outcome.record("tests", True)
        orchestrator.last_verification_outcome = outcome
        review_task = AgentTask(task_id="r", agent_id="code_reviewer", description="Review")

        async def fake_hierarchy(**kwargs):
            return [AgentResult(task_id="r", agent_id="code_reviewer", agent_name="cr", success=True, content="ok")], {}, False, False

        async def fake_governance(**kwargs):
            results = kwargs["all_results"] + [AgentResult(task_id="f", agent_id="backend", agent_name="b", success=True, content="fix", files_written=["app/main.py"])]
            return results, "### Governance", False, False

        orchestrator._run_department_hierarchy = fake_hierarchy
        orchestrator._run_governance_fix_loop = fake_governance
        report = VerificationReport(ran=True, passed=regression_passes, exit_code=0 if regression_passes else 1, stdout="", stderr="", duration_seconds=0.1)
        orchestrator._run_tests_logged = AsyncMock(return_value=report)
        with patch("agents.orchestrator.integration.ProjectVerifier", MagicMock()):
            return asyncio.run(orchestrator._run_review_after_verification(
                user_request="x", task_summary="x", review_tasks=[review_task], project_dir=str(tmp_path), results=[],
                file_owners={}, verification_ok=True, verification_summary="### Verifikation\n- ✅ grün",
                run_start_tokens=None, notify=lambda m: None, cancel_requested=None,
            )), review_task

    def test_reviewers_see_real_verification_status_and_green_regression_keeps_ok(self, orchestrator, tmp_path):
        (results, ok, summary, gov, aborted, cancelled), review_task = self._run(orchestrator, tmp_path, True)
        assert ok and "Verifikationsstatus" in review_task.context
        assert "Regressionstest nach Review-Änderungen" in summary and gov == "### Governance"

    def test_regression_from_review_fix_makes_run_unverified(self, orchestrator, tmp_path):
        (results, ok, summary, *_), _ = self._run(orchestrator, tmp_path, False)
        assert not ok
        assert orchestrator.last_verification_outcome.status("tests") is False
        assert "❌ Regressionstest" in summary


class TestMandatoryCodeReview:
    """P4-1 (ROADMAP_TEMP.md): Code-Review war rein optional (code_reviewer lief nur in 6 von
    20 Läufen), weil allein der LLM-Planer entschied, ob code_reviewer überhaupt eingeplant
    wurde. Wurde Code geschrieben, aber kein Review geplant, wird code_reviewer jetzt
    zusätzlich eingeplant (agents/orchestrator/integration.py._run_review_after_verification)."""

    def test_code_reviewer_is_forced_when_code_was_written_but_no_review_was_planned(self, orchestrator, tmp_path):
        outcome = VerificationOutcome()
        outcome.record("tests", True)
        orchestrator.last_verification_outcome = outcome
        hierarchy_calls = []

        async def fake_hierarchy(**kwargs):
            hierarchy_calls.append(kwargs["agent_tasks"])
            return [AgentResult(task_id="r", agent_id="code_reviewer", agent_name="cr", success=True, content="ok")], {}, False, False

        async def fake_governance(**kwargs):
            return kwargs["all_results"], "", False, False

        orchestrator._run_department_hierarchy = fake_hierarchy
        orchestrator._run_governance_fix_loop = fake_governance
        prior_results = [AgentResult(task_id="b", agent_id="backend", agent_name="b", success=True, content="ok", files_written=["app/main.py"])]

        with patch("agents.orchestrator.integration.ProjectVerifier", MagicMock()):
            asyncio.run(orchestrator._run_review_after_verification(
                user_request="x", task_summary="x", review_tasks=[], project_dir=str(tmp_path), results=prior_results,
                file_owners={}, verification_ok=True, verification_summary="### Verifikation\n- ✅ grün",
                run_start_tokens=None, notify=lambda m: None, cancel_requested=None,
            ))

        assert len(hierarchy_calls) == 1
        assert [t.agent_id for t in hierarchy_calls[0]] == ["code_reviewer"]

    def test_no_forced_review_without_any_written_files(self, orchestrator, tmp_path):
        outcome = VerificationOutcome()
        outcome.record("tests", True)
        orchestrator.last_verification_outcome = outcome
        hierarchy_calls = []

        async def fake_hierarchy(**kwargs):
            hierarchy_calls.append(kwargs["agent_tasks"])
            return [], {}, False, False

        async def fake_governance(**kwargs):
            return kwargs["all_results"], "", False, False

        orchestrator._run_department_hierarchy = fake_hierarchy
        orchestrator._run_governance_fix_loop = fake_governance
        # Kein Agent hat Dateien geschrieben (z.B. eine reine Rückfrage-/Analyse-Aufgabe).
        prior_results = [AgentResult(task_id="a", agent_id="architect", agent_name="a", success=True, content="Analyse ohne Codeänderung")]

        with patch("agents.orchestrator.integration.ProjectVerifier", MagicMock()):
            asyncio.run(orchestrator._run_review_after_verification(
                user_request="x", task_summary="x", review_tasks=[], project_dir=str(tmp_path), results=prior_results,
                file_owners={}, verification_ok=True, verification_summary="### Verifikation\n- ✅ grün",
                run_start_tokens=None, notify=lambda m: None, cancel_requested=None,
            ))

        assert hierarchy_calls == []
