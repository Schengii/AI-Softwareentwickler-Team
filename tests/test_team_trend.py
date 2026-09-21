"""
tests/test_team_trend.py – Testet P3-2 (ROADMAP_TEMP.md): "Kein Trendbericht über Läufe hinweg"

core/team_trend.py.build_team_trend() beantwortet "werden wir besser?" aus bereits bestehenden
Datenquellen (memory/run_history.json, workspace/*/.ai_team_status.json + P0-5s
categorize_failure(), memory/agent_learnings.json + P2-1s Wirksamkeitsmessung,
workspace/*/.ai_team_runs/*_postmortem.md aus P3-1) - ohne LLM-Aufruf.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import memory.run_history as run_history_module
from core.project_status import record_run
from memory.agent_knowledge_base import AgentKnowledgeBase
from memory.run_history import record_run as record_team_run


def _iso_days_ago(days: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")


class TestBuildTeamTrend(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace_dir = Path(self.temp_dir) / "workspace"
        self.workspace_dir.mkdir()
        self._run_patcher = patch.object(run_history_module, "RUN_HISTORY_FILE", Path(self.temp_dir) / "run_history.json")
        self._run_patcher.start()
        self.addCleanup(self._run_patcher.stop)
        self.empty_kb = AgentKnowledgeBase(file_path=Path(self.temp_dir) / "learnings.json")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_empty_state_does_not_crash(self):
        from core.team_trend import build_team_trend

        trend = build_team_trend(window_days=30, workspace_dir=str(self.workspace_dir), knowledge_base=self.empty_kb)
        self.assertEqual(trend.total_runs_in_window, 0)
        self.assertIn("Keine Läufe", trend.format_for_humans())

    def test_weekly_success_rate_only_counts_runs_within_window(self):
        from core.team_trend import build_team_trend

        record_team_run("proj", "Aufgabe", verification_ok=True, total_tokens=100, duration_seconds=1.0, agent_results=[])
        record_team_run("proj", "Aufgabe", verification_ok=False, total_tokens=200, duration_seconds=1.0, agent_results=[])
        raw = run_history_module._load()
        raw.append({
            "timestamp": _iso_days_ago(90), "project_slug": "proj", "task_summary": "alt",
            "verification_ok": False, "total_tokens": 999, "duration_seconds": 1.0, "agent_results": [],
        })
        run_history_module._save(raw)

        trend = build_team_trend(window_days=7, workspace_dir=str(self.workspace_dir), knowledge_base=self.empty_kb)

        self.assertEqual(trend.total_runs_in_window, 2)  # der 90 Tage alte Lauf zählt nicht
        self.assertEqual(trend.avg_tokens_per_run, 150.0)
        self.assertEqual(sum(w["runs"] for w in trend.weekly_success), 2)

    def test_regression_warning_when_recent_ten_runs_worse_than_previous_ten(self):
        from core.team_trend import build_team_trend

        # Läufe 1-10 (älter, "davor"): alle gruen. Läufe 11-20 (neuer, "letzte 10"): alle rot.
        for _ in range(10):
            record_team_run("proj", "alt", verification_ok=True, total_tokens=10, duration_seconds=1.0, agent_results=[])
        for _ in range(10):
            record_team_run("proj", "neu", verification_ok=False, total_tokens=10, duration_seconds=1.0, agent_results=[])

        trend = build_team_trend(window_days=365, workspace_dir=str(self.workspace_dir), knowledge_base=self.empty_kb)

        self.assertIsNotNone(trend.regression_warning)
        self.assertIn("Regression", trend.regression_warning)

    def test_no_regression_warning_with_too_few_runs(self):
        from core.team_trend import build_team_trend

        record_team_run("proj", "alt", verification_ok=False, total_tokens=10, duration_seconds=1.0, agent_results=[])

        trend = build_team_trend(window_days=365, workspace_dir=str(self.workspace_dir), knowledge_base=self.empty_kb)

        self.assertIsNone(trend.regression_warning)

    def test_top_blockers_aggregate_over_all_runs_not_just_latest(self):
        from core.team_trend import build_team_trend

        project_dir = self.workspace_dir / "demoproj"
        project_dir.mkdir()
        # run_stamp() hat nur Sekundenauflösung - ohne explizit unterschiedliche Stempel würde
        # der zweite record_run()-Aufruf das Verifikationsprotokoll des ersten überschreiben.
        record_run(
            str(project_dir), "Aufgabe 1", verification_ok=False, budget_aborted=False, files_written_count=3,
            verification_summary="❌ **Verifikations-Veto durch offene Sicherheits-Übergabe**: HMAC fehlt",
            run_stamp="20260101_100000",
        )
        record_run(
            str(project_dir), "Aufgabe 2", verification_ok=False, budget_aborted=False, files_written_count=3,
            verification_summary="Testfehler: 2 von 5 Tests fehlgeschlagen",
            run_stamp="20260101_110000",
        )

        trend = build_team_trend(window_days=30, workspace_dir=str(self.workspace_dir), knowledge_base=self.empty_kb)

        categories = dict(trend.top_blockers)
        self.assertIn("Sicherheits-Übergabe offen", categories)
        self.assertIn("Testsuite", categories)

    def test_top_blockers_skip_cancelled_and_budget_aborted_runs(self):
        from core.team_trend import build_team_trend

        project_dir = self.workspace_dir / "demoproj"
        project_dir.mkdir()
        record_run(
            str(project_dir), "Aufgabe", verification_ok=False, budget_aborted=True, files_written_count=0,
            verification_summary="🚫 Lauf-Budget erreicht",
        )

        trend = build_team_trend(window_days=30, workspace_dir=str(self.workspace_dir), knowledge_base=self.empty_kb)

        self.assertEqual(trend.top_blockers, [])

    def test_learning_effectiveness_splits_effective_and_ineffective(self):
        from core.team_trend import build_team_trend
        from memory.agent_knowledge_base import MIN_INJECTIONS_FOR_EFFECTIVENESS

        self.empty_kb.add_learning("backend", "Immer wirksame Regel", trigger_signature="effective_sig")
        self.empty_kb.add_learning("backend", "Nie wirksame Regel", trigger_signature="ineffective_sig")
        for _ in range(MIN_INJECTIONS_FOR_EFFECTIVENESS):
            self.empty_kb.get_augmented_prompt("backend", "Basis-Prompt")
        # "Immer wirksame Regel" tritt nach der Injektion nie wieder auf (0 Verletzungen danach).
        # "Nie wirksame Regel" tritt bei jeder Injektion erneut auf.
        for _ in range(MIN_INJECTIONS_FOR_EFFECTIVENESS):
            self.empty_kb.add_learning("backend", "Nie wirksame Regel", trigger_signature="ineffective_sig")

        trend = build_team_trend(window_days=30, workspace_dir=str(self.workspace_dir), knowledge_base=self.empty_kb)

        effective_rules = [e["rule"] for e in trend.effective_learnings]
        ineffective_rules = [e["rule"] for e in trend.ineffective_learnings]
        self.assertIn("Immer wirksame Regel", effective_rules)
        self.assertIn("Nie wirksame Regel", ineffective_rules)

    def test_avg_repair_calls_reads_postmortem_reports_in_window(self):
        from core.team_trend import build_team_trend

        runs_dir = self.workspace_dir / "demoproj" / ".ai_team_runs"
        runs_dir.mkdir(parents=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        (runs_dir / f"{stamp}_postmortem.md").write_text(
            "## Fix-Ökonomie\n\n- Produktion: 1,000 Tokens (1 Aufruf(e))\n"
            "- Reparatur (Verifikations-/Governance-Fixloop): 300 Tokens (3 Aufruf(e))\n",
            encoding="utf-8",
        )

        trend = build_team_trend(window_days=30, workspace_dir=str(self.workspace_dir), knowledge_base=self.empty_kb)

        self.assertEqual(trend.postmortems_seen, 1)
        self.assertEqual(trend.avg_repair_calls_per_run, 3.0)


if __name__ == "__main__":
    unittest.main()
