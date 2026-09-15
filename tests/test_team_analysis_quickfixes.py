"""
tests/test_team_analysis_quickfixes.py – Sofort-Fixes aus der Team-Analyse 2026-09-15 (Teil 2)

1. Test-Rauschen in Lauf-/Benchmark-Historie (core/telemetry_hygiene.py)
2. Agent-Trainer lief wegen Schwelle 4000 Tokens nach jedem Lauf
3. Lead-/Retro-/Trainer-Aufrufe fehlten im Lauf-Log
4. DoD erkannte serverseitig ausgelieferte HTML-Dashboards nicht
5. Unsinnige Dateinamen wie `asyncio.Lock`
6. Backlog-Hygiene (hängend, doppelt, per Commit erledigt)
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import core.backlog_store as backlog_store
from core.message_bus import AgentResult


class TestTelemetryHygiene(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_fake_model_and_zero_duration_are_synthetic(self):
        from core.telemetry_hygiene import is_synthetic_eval, is_synthetic_run

        self.assertTrue(is_synthetic_run({"duration_seconds": 50, "agent_results": [{"model_used": "fake-model"}]}))
        self.assertTrue(is_synthetic_run({"duration_seconds": 0.0, "agent_results": []}))
        self.assertFalse(is_synthetic_run({"duration_seconds": 781.8, "agent_results": [{"model_used": "gemini-3.8-flash"}]}))
        self.assertTrue(is_synthetic_eval({"total_duration_seconds": 0.0}))
        self.assertFalse(is_synthetic_eval({"total_duration_seconds": 120.0}))

    def test_clean_run_history_keeps_real_runs_and_writes_backup(self):
        from core.telemetry_hygiene import clean_run_history

        path = self.tmp / "run_history.json"
        runs = [
            {"project_slug": "test_proj", "duration_seconds": 0.0, "agent_results": [{"model_used": "fake-model"}]},
            {"project_slug": "syncwave", "duration_seconds": 1085.4, "agent_results": [{"model_used": "gemini-pro-latest"}]},
        ]
        path.write_text(json.dumps(runs), encoding="utf-8")

        self.assertEqual(clean_run_history(path, dry_run=True), (2, 1))
        self.assertEqual(len(json.loads(path.read_text(encoding="utf-8"))), 2)

        self.assertEqual(clean_run_history(path), (2, 1))
        kept = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual([r["project_slug"] for r in kept], ["syncwave"])
        self.assertTrue(list(self.tmp.glob("run_history.json.bak_*")))

    def test_record_run_skips_real_file_during_tests(self):
        import memory.run_history as rh

        real = self.tmp / "real_history.json"
        with patch.object(rh, "RUN_HISTORY_FILE", real), patch.object(rh, "_REAL_RUN_HISTORY_FILE", real):
            rh.record_run("p", "x", True, 10, 5.0, [])
        self.assertFalse(real.exists())

        redirected = self.tmp / "redirected.json"
        with patch.object(rh, "RUN_HISTORY_FILE", redirected), patch.object(rh, "_REAL_RUN_HISTORY_FILE", real):
            rh.record_run("p", "x", True, 10, 5.0, [])
        self.assertEqual(len(json.loads(redirected.read_text(encoding="utf-8"))), 1)

    def test_save_benchmark_result_skips_real_file_during_tests(self):
        import evals.runner as runner

        real = self.tmp / "eval_history.json"
        suite = MagicMock()
        with patch.object(runner, "_REAL_EVALS_HISTORY_FILE", real), patch.object(runner, "asdict", return_value={}):
            runner.save_benchmark_result(suite, history_path=real)
        self.assertFalse(real.exists())


class TestTrainerTrigger(unittest.TestCase):
    def setUp(self):
        from agents.orchestrator import Orchestrator
        self.orchestrator = Orchestrator()

    def _run(self, results, **kwargs):
        mock_execute = AsyncMock(return_value=AgentResult(
            task_id="trainer_auto_opt", agent_id="agent_trainer", agent_name="Trainer",
            success=True, content='```json\n{"learnings": []}\n```',
        ))
        with patch.object(self.orchestrator._agents["agent_trainer"], "execute", mock_execute):
            asyncio.run(self.orchestrator._run_agent_trainer_self_optimization(
                user_request="Baue etwas", results=results, retro_content="", **kwargs,
            ))
        return mock_execute

    def test_normal_token_usage_on_green_run_does_not_trigger_trainer(self):
        results = [AgentResult(task_id="t", agent_id="backend", agent_name="Backend", success=True,
                               content="ok", total_tokens=61_000)]
        self._run(results).assert_not_called()

    def test_provider_exhaustion_alone_does_not_trigger_trainer(self):
        results = [AgentResult(task_id="t", agent_id="backend", agent_name="Backend", success=False,
                               content="", error="429", failure_class="provider_exhausted", total_tokens=0)]
        self._run(results).assert_not_called()

    def test_outlier_usage_triggers_trainer_with_iteration_cap(self):
        from config import TRAINER_HIGH_USAGE_TOKENS_PER_CALL, TRAINER_MAX_TOOL_ITERATIONS

        results = [AgentResult(task_id="t", agent_id="tester", agent_name="Tester", success=True,
                               content="ok", total_tokens=TRAINER_HIGH_USAGE_TOKENS_PER_CALL + 1)]
        mock_execute = self._run(results)
        mock_execute.assert_called_once()
        self.assertEqual(mock_execute.call_args.args[0].max_tool_iterations, TRAINER_MAX_TOOL_ITERATIONS)


class TestLeadCallsAreLogged(unittest.TestCase):
    def test_department_delegation_and_consolidation_reach_run_logger(self):
        from agents.orchestrator import Orchestrator

        orchestrator = Orchestrator()
        orchestrator._run_logger = MagicMock()
        lead = orchestrator._dept_leads["dev_lead"]
        result = AgentResult(task_id="x", agent_id="dev_lead", agent_name="Lead", success=True, content="ok")
        with patch.object(lead, "execute", AsyncMock(return_value=result)):
            asyncio.run(orchestrator._run_department_delegation(lead, "Aufgabe", [], tempfile.mkdtemp()))
            asyncio.run(orchestrator._run_department_consolidation(lead, [result], tempfile.mkdtemp()))
        self.assertEqual(orchestrator._run_logger.log_agent_result.call_count, 2)


class TestServedHtmlUi(unittest.TestCase):
    def test_dashboard_under_app_static_counts_as_delivered_ui(self):
        from core.definition_of_done import has_served_html_ui

        root = Path(tempfile.mkdtemp())
        self.assertFalse(has_served_html_ui(root))
        (root / "app" / "static").mkdir(parents=True)
        (root / "app" / "static" / "dashboard.html").write_text("<html>" + "x" * 300 + "</html>", encoding="utf-8")
        self.assertTrue(has_served_html_ui(root))

    def test_tiny_placeholder_and_node_modules_do_not_count(self):
        from core.definition_of_done import has_served_html_ui

        root = Path(tempfile.mkdtemp())
        (root / "static").mkdir()
        (root / "static" / "index.html").write_text("<html></html>", encoding="utf-8")
        (root / "node_modules" / "pkg" / "public").mkdir(parents=True)
        (root / "node_modules" / "pkg" / "public" / "a.html").write_text("x" * 500, encoding="utf-8")
        self.assertFalse(has_served_html_ui(root))


class TestPathPlausibility(unittest.TestCase):
    def test_symbol_like_names_are_rejected(self):
        from core.write_guard import check_path_plausible

        for bad in ("asyncio.Lock", "app/os.path.Join", "settings.Settings", "app/x:y.py", "foo. "):
            self.assertIsNotNone(check_path_plausible(bad), bad)
        for good in ("app/main.py", "Dockerfile", ".env.example", "CACHEDIR.TAG", "src/App.tsx", "README.md"):
            self.assertIsNone(check_path_plausible(good), good)

    def test_toolbox_write_file_refuses_symbol_like_file(self):
        from core.agent_toolbox import AgentToolbox

        root = Path(tempfile.mkdtemp())
        toolbox = AgentToolbox(project_dir=root, agent_id="backend")
        result = asyncio.run(toolbox._tool_write_file("asyncio.Lock", "import asyncio\n"))
        self.assertIn("error", result)
        self.assertFalse((root / "asyncio.Lock").exists())


class TestBacklogHygiene(unittest.TestCase):
    def setUp(self):
        self.file_path = Path(tempfile.mkdtemp()) / "backlog.json"
        self._patcher = patch.object(backlog_store, "BACKLOG_FILE", self.file_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def _age(self, ticket_id: str, hours: float):
        raw = json.loads(self.file_path.read_text(encoding="utf-8"))
        for t in raw:
            if t["id"] == ticket_id:
                t["updated_at"] = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        self.file_path.write_text(json.dumps(raw), encoding="utf-8")

    def test_stale_cli_ticket_becomes_blocked_not_todo(self):
        from core.backlog_hygiene import run_backlog_hygiene

        backlog_store.upsert_ticket("cli-aaaa1111", "Großprojekt", "cli", "in_progress")
        backlog_store.upsert_ticket("cli-bbbb2222", "Frisch", "cli", "in_progress")
        self._age("cli-aaaa1111", 10)
        report = run_backlog_hygiene(commit_messages="")
        self.assertEqual(report.recovered, ["cli-aaaa1111"])
        self.assertEqual(backlog_store.get_ticket("cli-aaaa1111").status, "blocked")
        self.assertEqual(backlog_store.get_ticket("cli-bbbb2222").status, "in_progress")

    def test_duplicates_keep_only_newest_open(self):
        from core.backlog_hygiene import run_backlog_hygiene

        for i, tid in enumerate(("goal-00000001", "goal-00000002", "goal-00000003")):
            backlog_store.upsert_ticket(tid, "Goal: Baue Auth-API", "goal", "review", project_slug="oszillation")
            self._age(tid, 10 - i)
        report = run_backlog_hygiene(commit_messages="")
        self.assertCountEqual(report.duplicates_cancelled, ["goal-00000001", "goal-00000002"])
        self.assertEqual(backlog_store.get_ticket("goal-00000003").status, "review")

    def test_ticket_referenced_in_commit_is_closed_with_word_boundaries(self):
        from core.backlog_hygiene import run_backlog_hygiene

        backlog_store.upsert_ticket("audit-foo", "Audit foo", "workspace_audit", "blocked", project_slug="foo")
        backlog_store.upsert_ticket("audit-foo-adr-duplicate", "ADR", "workspace_audit", "blocked", project_slug="foo")
        report = run_backlog_hygiene(commit_messages="fix: DoD erkennt Dashboards\n\nCloses: audit-foo-adr-duplicate\n")
        self.assertEqual(report.closed_by_commit, ["audit-foo-adr-duplicate"])
        self.assertEqual(backlog_store.get_ticket("audit-foo").status, "blocked")
        self.assertEqual(backlog_store.get_ticket("audit-foo-adr-duplicate").status, "done")


if __name__ == "__main__":
    unittest.main()
