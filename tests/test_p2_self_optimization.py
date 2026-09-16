"""
tests/test_p2_self_optimization.py – Selbstoptimierung, die tatsächlich wirkt (Team-Analyse 2026-09-15, P2):

4.1 Lebenszyklus für Team-Lektionen      4.2 Relevanz statt reiner Aktualität
4.3 Eval-Gate für Framework-Änderungen   4.4 Zentrales Regelwerk + Prüf-Pipeline
4.6 Modell-A/B-Tests                     4.7 Projektlokaler Lauf-Trace
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import core.team_memory as tm
from agents.orchestrator.verification_checks import CheckContext, run_informational_checks
from core.known_pitfalls import (
    HIDDEN_RUNTIME_DEPENDENCIES,
    PITFALL_CATALOG,
    TOXIC_DEPENDENCY_RULES,
    format_pitfalls_for_agents,
    provided_import_names,
)
from core.manifest_guard import TOXIC_DEPENDENCY_RULES as GUARD_RULES
from core.manifest_guard import sanitize_requirements
from core.project_scaffold import ScaffoldReport
from core.run_logger import RunLogger
from core.run_trace import (
    MAX_RUN_ARTIFACTS_KEPT,
    format_trace_summary,
    latest_trace,
    prune_run_artifacts,
    read_run_artifact,
    summarize_trace,
    write_verification_protocol,
)
from core.verification_outcome import VerificationOutcome
from evals.gate import evaluate_gate
from evals.tasks import list_regression_tasks


@pytest.fixture
def lessons_file(tmp_path, monkeypatch):
    path = tmp_path / "lessons.jsonl"
    monkeypatch.setattr(tm, "TEAM_MEMORY_FILE", path)
    return path


# ── 4.1 Lebenszyklus ───────────────────────────────────────────────────────────────────────
class TestLessonLifecycle:
    def test_recurrence_is_counted_once_per_project_per_day(self, lessons_file):
        tm.record_lesson("a", "missing_dependency", "greenlet fehlt bei create_async_engine")
        tm.record_lesson("a", "missing_dependency", "greenlet fehlt bei create_async_engine")
        tm.record_lesson("a", "missing_dependency", "greenlet fehlt bei create_async_engine")
        tm.record_lesson("b", "missing_dependency", "greenlet fehlt bei create_async_engine")
        index = tm.read_lesson_index()
        assert len(index) == 1
        entry = next(iter(index.values()))
        assert entry["occurrences"] == 3 and entry["projects"] == ["a", "b"]
        assert len(tm.read_team_lessons(limit=100)) == 1, "Ereigniszeilen sind keine Lektionen"

    def test_status_update_hides_closed_lessons_from_agents(self, lessons_file):
        tm.record_lesson("a", "architecture_consistency", "Router-Prefix doppelt gesetzt in include_router")
        signature = next(iter(tm.read_lesson_index()))
        assert "Router-Prefix" in tm.format_team_lessons_for_agents()
        assert tm.update_lesson_status(signature, "verified", "Regel aktiv")
        assert tm.format_team_lessons_for_agents() == ""
        assert not tm.update_lesson_status(signature, "erledigt")
        assert not tm.update_lesson_status("unbekannt", "archived")

    def test_recurrence_reopens_implemented_lesson(self, lessons_file):
        tm.record_lesson("a", "dependency_compatibility", "passlib bricht mit bcrypt>=4.1")
        signature = next(iter(tm.read_lesson_index()))
        tm.update_lesson_status(signature, "implemented", "Pin-Regel")
        tm.record_lesson("b", "dependency_compatibility", "passlib bricht mit bcrypt>=4.1")
        entry = tm.read_lesson_index()[signature]
        assert entry["status"] == "open" and "wieder aufgetreten" in entry["resolution"]

    def test_auto_link_uses_explicit_keywords_and_most_specific_rule(self, lessons_file):
        tm.record_lesson("a", "root_cause_analysis", "Voreilige Re-Exporte in __init__.py vor Anlage des Moduls")
        tm.record_lesson("a", "unresolved_governance_critical", "Inkonsistente HTTP-Statuscodes 401 vs 403 im Test")
        linked = {rule: sig for sig, rule in tm.auto_link_lessons_to_rules()}
        assert "reexport-before-module" in linked and "package-init-files" not in linked
        statuses = {e["detail"][:20]: e["status"] for e in tm.read_lesson_index().values()}
        assert statuses["Inkonsistente HTTP-S"] == "open"

    def test_legacy_lines_without_signature_are_indexed(self, lessons_file):
        lessons_file.write_text(json.dumps({"timestamp": "t", "project_slug": "x", "category": "c", "detail": "alt"}) + "\n", encoding="utf-8")
        assert len(tm.read_lesson_index()) == 1
        assert "offen" in tm.format_lesson_board()


# ── 4.2 Relevanz ───────────────────────────────────────────────────────────────────────────
class TestLessonRelevance:
    def test_relevant_lesson_comes_first_for_matching_context(self, lessons_file):
        tm.record_lesson("p1", "missing_dependency", "SQLAlchemy async engine braucht greenlet")
        tm.record_lesson("p2", "architecture_consistency", "Frontend Canvas wird nie gezeichnet")
        text = tm.format_team_lessons_for_agents(limit=1, context="backend SQLAlchemy async greenlet Datenbank")
        assert "greenlet" in text and "Canvas" not in text
        text = tm.format_team_lessons_for_agents(limit=1, context="frontend Canvas Spiel")
        assert "Canvas" in text

    def test_empty_context_keeps_recency(self, lessons_file):
        tm.record_lesson("p1", "missing_dependency", "erste Lektion zu greenlet")
        tm.record_lesson("p2", "missing_dependency", "zweite Lektion zu multipart")
        assert "zweite" in tm.format_team_lessons_for_agents(limit=1).splitlines()[1]


# ── 4.4 Regelwerk & Pipeline ───────────────────────────────────────────────────────────────
class TestKnownPitfallsRegistry:
    def test_manifest_guard_uses_registry(self):
        assert GUARD_RULES is TOXIC_DEPENDENCY_RULES
        cleaned, findings = sanitize_requirements("requirements.txt", "fastapi\njwt\n")
        assert "PyJWT" in cleaned and findings

    def test_catalog_rules_are_complete(self):
        ids = [r.rule_id for r in PITFALL_CATALOG]
        assert len(ids) == len(set(ids))
        for rule in PITFALL_CATALOG:
            assert rule.symptom and rule.fix and rule.enforced_by and rule.match_keywords, rule.rule_id

    def test_pitfalls_prompt_is_stack_specific(self):
        fastapi = format_pitfalls_for_agents("FastAPI Backend mit SQLAlchemy")
        assert "PyJWT" in fastapi and "greenlet" in fastapi
        assert "write_file" in format_pitfalls_for_agents("")

    def test_pitfalls_prompt_surfaces_websocket_hint_despite_limit(self):
        # Regression (Lauf logstream_sentinel, 2026-09-16): Bei einem FastAPI-Auftrag
        # matchen fast alle Python-Regeln auf "python"/"all", sodass die spezifische
        # "websocket-native-client"-Regel bei limit=8 aus der Liste fiel. Der Frontend-
        # Agent nutzte daraufhin erneut einen Socket.IO-Client gegen die native
        # FastAPI-WebSocket-Route ('Connection'-Header fehlt) und der Browser-UI-Check
        # scheiterte - genau das Symptom, vor dem die Regel warnt.
        prompt = format_pitfalls_for_agents(
            "fastapi FastAPI-Dashboard mit WebSocket-Streaming und Live-Ansicht"
        )
        assert "Connection" in prompt and "header is missing" in prompt

    def test_scaffold_report_passes_full_task_text_to_pitfalls(self):
        # Nur das grobe Stack-Label ("fastapi") an format_pitfalls_for_agents zu geben
        # aktiviert die "frontend"-Stichworte (dashboard/websocket/ui) nie, weil diese
        # Wörter im Label selbst nicht vorkommen - der Auftragstext muss mitgegeben werden.
        report = ScaffoldReport(stack="fastapi", user_request="WebSocket-Dashboard für Live-Logs")
        assert "websocket" in report.format_for_agents().lower()

    def test_transitive_provides(self):
        assert {"starlette", "pydantic"} <= provided_import_names({"fastapi"})
        assert provided_import_names({"requests"}).isdisjoint({"starlette"})
        assert HIDDEN_RUNTIME_DEPENDENCIES

    def test_informational_pipeline_records_outcome_and_lint_signature(self):
        verifier = MagicMock()
        verifier.check_dependency_vulnerabilities.return_value = [
            SimpleNamespace(attempted=True, vulnerable=False, vulnerabilities=[], tool="pip-audit"),
            SimpleNamespace(attempted=True, vulnerable=True, tool="npm audit", vulnerabilities=[
                SimpleNamespace(package="lodash", version="1.0", vulnerability_id="CVE-1")]),
        ]
        verifier.check_sast.return_value = [SimpleNamespace(attempted=False)]
        verifier.check_licenses.return_value = []
        verifier.check_lint.return_value = [SimpleNamespace(attempted=True, passed=False, tool="ruff", issues=[
            SimpleNamespace(file_path="app/main.py", line_number=3, rule="F401")])]
        ctx = asyncio.run(run_informational_checks(CheckContext(verifier=verifier, outcome=VerificationOutcome(), notify=lambda m: None)))
        assert ctx.outcome.status("dependency_audit") is False, "späterer Fehlschlag darf nicht überschrieben werden"
        assert ctx.outcome.status("sast") is None and ctx.outcome.status("lint") is False
        assert ctx.lint_signature == ["ruff:app/main.py:F401"] and ctx.lint_attempted
        assert any("npm audit" in line for line in ctx.summary_lines)


# ── 4.3 Eval-Gate ──────────────────────────────────────────────────────────────────────────
def _run(results: dict[str, tuple[bool, int]]) -> dict:
    return {"results": [
        {"slug": slug, "success": ok, "verification_ok": ok, "total_tokens": tokens, "failed_checks": [] if ok else ["tests"]}
        for slug, (ok, tokens) in results.items()
    ]}


class TestEvalGate:
    def test_no_history_passes_with_note(self):
        assert evaluate_gate([]).passed

    def test_stable_run_passes(self):
        history = [_run({"a": (True, 1000), "b": (True, 2000)}) for _ in range(3)] + [_run({"a": (True, 1100), "b": (True, 1900)})]
        assert evaluate_gate(history).passed

    def test_task_regression_and_pass_rate_drop_fail(self):
        history = [_run({"a": (True, 1000), "b": (True, 1000)}) for _ in range(3)] + [_run({"a": (False, 1000), "b": (True, 1000)})]
        gate = evaluate_gate(history)
        assert not gate.passed
        assert any("`a`" in r for r in gate.reasons) and any("Erfolgsquote" in r for r in gate.reasons)

    def test_token_increase_fails(self):
        history = [_run({"a": (True, 1000)}) for _ in range(3)] + [_run({"a": (True, 1400)})]
        gate = evaluate_gate(history)
        assert not gate.passed and "+40%" in gate.format_report()

    def test_regression_tasks_are_derived_from_real_failures(self):
        tasks = list_regression_tasks()
        assert len(tasks) >= 3 and all(t.derived_from for t in tasks)


# ── 4.6 Modell-A/B-Tests ───────────────────────────────────────────────────────────────────
class TestModelABTrials:
    @pytest.fixture
    def files(self, tmp_path, monkeypatch):
        import config

        monkeypatch.setattr(config, "MODEL_AB_TRIALS_FILE", str(tmp_path / "trials.json"))
        monkeypatch.setattr(config, "AUTO_TUNED_MODELS_FILE", str(tmp_path / "tuned.json"))
        monkeypatch.setattr(config, "ENABLE_MODEL_AB_TRIALS", True)
        monkeypatch.setattr(config, "ENABLE_AUTO_MODEL_TUNING", False)
        monkeypatch.delenv(config.get_model_env_key("performance"), raising=False)
        return tmp_path

    def _report(self):
        from core.optimization_advisor import ModelSuggestion, OptimizationReport

        report = OptimizationReport(sample_runs=100)
        report.model_suggestions.append(ModelSuggestion(
            agent_id="performance", current_model="model-big", current_success_rate=70.0, current_calls=10,
            current_avg_tokens=30000, suggested_model="model-lite", suggested_success_rate=100.0,
            suggested_calls=5, suggested_avg_tokens=20000,
        ))
        return report

    def test_trial_start_and_share(self, files):
        from core.model_ab_trials import start_trials_from_report, trial_model_for_agent

        assert start_trials_from_report(self._report()) == ["performance"]
        assert start_trials_from_report(self._report()) == [], "kein doppelter Test"
        assert trial_model_for_agent("performance", rand=lambda: 0.1) == "model-lite"
        assert trial_model_for_agent("performance", rand=lambda: 0.9) is None

    def test_promotion_applies_without_global_flag_then_rollback(self, files):
        import config
        from core.model_ab_trials import evaluate_trials, load_trials, start_trials_from_report

        start_trials_from_report(self._report())
        perf = [
            {"agent_id": "performance", "model": "model-lite", "calls": 15, "success_rate": 95.0, "avg_tokens": 21000},
            {"agent_id": "performance", "model": "model-big", "calls": 20, "success_rate": 72.0, "avg_tokens": 30000},
        ]
        assert evaluate_trials(perf)["promoted"] == ["performance"]
        with patch("core.model_ab_trials.random.random", return_value=0.99):
            assert config.get_model_for_agent("performance") == "model-lite"
        worse = [
            {"agent_id": "performance", "model": "model-lite", "calls": 30, "success_rate": 50.0, "avg_tokens": 21000},
            perf[1],
        ]
        assert evaluate_trials(worse)["rolled_back"] == ["performance"]
        assert load_trials()["performance"]["status"] == "rolled_back"
        assert json.loads(Path(config.AUTO_TUNED_MODELS_FILE).read_text(encoding="utf-8")) == {}

    def test_insufficient_calls_keep_trial_running_and_explicit_env_wins(self, files, monkeypatch):
        import config
        from core.model_ab_trials import evaluate_trials, start_trials_from_report

        start_trials_from_report(self._report())
        few = [{"agent_id": "performance", "model": "model-lite", "calls": 7, "success_rate": 100.0, "avg_tokens": 1}]
        assert evaluate_trials(few) == {"promoted": [], "rejected": [], "rolled_back": []}
        monkeypatch.setenv(config.get_model_env_key("performance"), "explizit")
        monkeypatch.setitem(config.AGENT_MODELS, "performance", "explizit")
        assert config.get_model_for_agent("performance") == "explizit"


# ── 4.7 Lauf-Trace ─────────────────────────────────────────────────────────────────────────
class TestRunTrace:
    def test_run_logger_mirrors_into_project_and_summary(self, tmp_path):
        logger = RunLogger(project_slug="demo", project_dir=tmp_path)
        logger.log_event("phase_started", phase_id="dev_lead", agents=["backend"])
        logger.log_agent_result(SimpleNamespace(
            agent_id="backend", agent_name="Backend", success=False, model_used="m", prompt_tokens=10,
            completion_tokens=5, total_tokens=15, duration_seconds=1.0, tool_calls_count=3,
            files_written=["app/main.py"], failure_class="agent_error", error="Hard Delivery Gate",
        ), requested_model="m")
        logger.log_event("phase_finished", phase_id="dev_lead", tokens=15, successes=0, failures=1)
        logger.close(verification_ok=False)
        trace = latest_trace(tmp_path)
        assert trace is not None and trace.parent.name == ".ai_team_runs"
        summary = summarize_trace(trace)
        assert summary["total_tokens"] == 15 and summary["agents"]["backend"]["files"] == ["app/main.py"]
        text = format_trace_summary(summary)
        assert "Phase dev_lead" in text and "Hard Delivery Gate" in text

    def test_protocol_path_traversal_is_rejected_and_pruning(self, tmp_path):
        rel = write_verification_protocol(tmp_path, "- ok", {"failed": []}, stamp="20260101_000000")
        assert "- ok" in read_run_artifact(tmp_path, rel)
        (tmp_path / "secret.txt").write_text("geheim", encoding="utf-8")
        assert read_run_artifact(tmp_path, "../secret.txt") == ""
        assert read_run_artifact(tmp_path, "secret.txt") == ""
        for i in range(MAX_RUN_ARTIFACTS_KEPT + 5):
            write_verification_protocol(tmp_path, f"- {i}", stamp=f"20260102_{i:06d}")
        prune_run_artifacts(tmp_path)
        assert len(list((tmp_path / ".ai_team_runs").glob("*_verification.md"))) == MAX_RUN_ARTIFACTS_KEPT

    def test_root_cause_evidence_includes_trace_metrics(self, tmp_path):
        from core.root_cause_analyst import gather_evidence

        logger = RunLogger(project_slug="demo", project_dir=tmp_path)
        logger.log_event("phase_finished", phase_id="qa_lead", tokens=99, successes=1, failures=0)
        evidence = gather_evidence(project_slug="demo", user_request="x", project_trace_path=logger.project_trace_path)
        assert "LAUF-KENNZAHLEN" in evidence and "qa_lead" in evidence
