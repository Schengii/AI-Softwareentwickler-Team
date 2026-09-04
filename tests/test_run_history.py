"""
tests/test_run_history.py – Testet memory/run_history.py (Observability über Zeit)

Realer Fund bei einer Bestandsaufnahme des eigenen Teams: core/project_status.py speichert
Lauf-Historie NUR pro Projekt, memory/cost_history.py NUR kumulierte Summen pro Modell - es
gab keine Möglichkeit zu sehen, welche Agenten über die Zeit häufiger scheitern oder wie sich
Tokenverbrauch/Dauer PROJEKTÜBERGREIFEND entwickeln.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import memory.run_history as run_history_module
from memory.run_history import (
    get_agent_model_performance,
    get_agent_success_rates,
    get_recent_runs,
    get_total_tokens_for_project,
    get_verification_success_rate,
    record_run,
)


class TestRunHistory(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._patcher = patch.object(run_history_module, "RUN_HISTORY_FILE", Path(self.temp_dir) / "run_history.json")
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_recorded_run_is_retrievable(self):
        record_run(
            project_slug="proj_a", task_summary="X gebaut", verification_ok=True,
            total_tokens=500, duration_seconds=12.3,
            agent_results=[{"agent_id": "backend", "success": True, "total_tokens": 500}],
        )

        runs = get_recent_runs()

        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["project_slug"], "proj_a")
        self.assertTrue(runs[0]["verification_ok"])
        self.assertEqual(runs[0]["total_tokens"], 500)

    def test_recent_runs_returns_newest_first(self):
        record_run(project_slug="alt", task_summary="alt", verification_ok=True, total_tokens=1, duration_seconds=1, agent_results=[])
        record_run(project_slug="neu", task_summary="neu", verification_ok=True, total_tokens=1, duration_seconds=1, agent_results=[])

        runs = get_recent_runs()

        self.assertEqual(runs[0]["project_slug"], "neu")
        self.assertEqual(runs[1]["project_slug"], "alt")

    def test_recent_runs_respects_limit(self):
        for i in range(5):
            record_run(project_slug=f"p{i}", task_summary="x", verification_ok=True, total_tokens=1, duration_seconds=1, agent_results=[])

        self.assertEqual(len(get_recent_runs(limit=2)), 2)

    def test_history_is_capped_at_max_runs_kept(self):
        with patch.object(run_history_module, "MAX_RUNS_KEPT", 3):
            for i in range(5):
                record_run(project_slug=f"p{i}", task_summary="x", verification_ok=True, total_tokens=1, duration_seconds=1, agent_results=[])
            all_runs = get_recent_runs(limit=100)

        self.assertEqual(len(all_runs), 3)
        # Die ÄLTESTEN fallen raus - die letzten 3 (p2,p3,p4) bleiben.
        self.assertEqual({r["project_slug"] for r in all_runs}, {"p2", "p3", "p4"})

    def test_agent_success_rate_is_computed_across_runs(self):
        record_run(
            project_slug="a", task_summary="x", verification_ok=True, total_tokens=1, duration_seconds=1,
            agent_results=[{"agent_id": "backend", "success": True, "total_tokens": 10}],
        )
        record_run(
            project_slug="b", task_summary="x", verification_ok=False, total_tokens=1, duration_seconds=1,
            agent_results=[{"agent_id": "backend", "success": False, "total_tokens": 10}],
        )

        rates = get_agent_success_rates()

        backend = next(r for r in rates if r["agent_id"] == "backend")
        self.assertEqual(backend["calls"], 2)
        self.assertEqual(backend["successes"], 1)
        self.assertEqual(backend["success_rate"], 50.0)

    def test_success_rates_sorted_by_call_count_descending(self):
        record_run(
            project_slug="a", task_summary="x", verification_ok=True, total_tokens=1, duration_seconds=1,
            agent_results=[
                {"agent_id": "rare_agent", "success": True, "total_tokens": 1},
                {"agent_id": "busy_agent", "success": True, "total_tokens": 1},
            ],
        )
        record_run(
            project_slug="b", task_summary="x", verification_ok=True, total_tokens=1, duration_seconds=1,
            agent_results=[{"agent_id": "busy_agent", "success": True, "total_tokens": 1}],
        )

        rates = get_agent_success_rates()

        self.assertEqual(rates[0]["agent_id"], "busy_agent")
        self.assertEqual(rates[0]["calls"], 2)

    def test_no_history_yet_returns_empty_lists(self):
        self.assertEqual(get_recent_runs(), [])
        self.assertEqual(get_agent_success_rates(), [])

    def test_total_tokens_for_project_sums_only_that_project(self):
        record_run(project_slug="proj_a", task_summary="x", verification_ok=True, total_tokens=1000, duration_seconds=1, agent_results=[])
        record_run(project_slug="proj_a", task_summary="y", verification_ok=True, total_tokens=2500, duration_seconds=1, agent_results=[])
        record_run(project_slug="proj_b", task_summary="z", verification_ok=True, total_tokens=9999, duration_seconds=1, agent_results=[])

        self.assertEqual(get_total_tokens_for_project("proj_a"), 3500)
        self.assertEqual(get_total_tokens_for_project("proj_b"), 9999)

    def test_total_tokens_for_unknown_project_is_zero(self):
        record_run(project_slug="proj_a", task_summary="x", verification_ok=True, total_tokens=1000, duration_seconds=1, agent_results=[])
        self.assertEqual(get_total_tokens_for_project("never_ran"), 0)

    def test_model_performance_grouped_by_agent_and_model(self):
        record_run(
            project_slug="a", task_summary="x", verification_ok=True, total_tokens=1, duration_seconds=1,
            agent_results=[{"agent_id": "backend", "success": True, "total_tokens": 100, "model_used": "gemini-flash"}],
        )
        record_run(
            project_slug="b", task_summary="x", verification_ok=False, total_tokens=1, duration_seconds=1,
            agent_results=[{"agent_id": "backend", "success": False, "total_tokens": 200, "model_used": "gemini-flash"}],
        )
        record_run(
            project_slug="c", task_summary="x", verification_ok=True, total_tokens=1, duration_seconds=1,
            agent_results=[{"agent_id": "backend", "success": True, "total_tokens": 50, "model_used": "claude-sonnet"}],
        )

        perf = get_agent_model_performance()

        flash = next(r for r in perf if r["agent_id"] == "backend" and r["model"] == "gemini-flash")
        self.assertEqual(flash["calls"], 2)
        self.assertEqual(flash["successes"], 1)
        self.assertEqual(flash["success_rate"], 50.0)
        self.assertEqual(flash["avg_tokens"], 150.0)

        sonnet = next(r for r in perf if r["agent_id"] == "backend" and r["model"] == "claude-sonnet")
        self.assertEqual(sonnet["calls"], 1)
        self.assertEqual(sonnet["success_rate"], 100.0)

    def test_model_performance_handles_entries_without_model_used(self):
        """Ältere Historien-Einträge von vor dieser Erweiterung haben noch kein model_used -
        müssen unter 'unbekannt' gruppiert werden statt zu crashen."""
        record_run(
            project_slug="a", task_summary="x", verification_ok=True, total_tokens=1, duration_seconds=1,
            agent_results=[{"agent_id": "backend", "success": True, "total_tokens": 100}],
        )

        perf = get_agent_model_performance()

        entry = next(r for r in perf if r["agent_id"] == "backend")
        self.assertEqual(entry["model"], "unbekannt")

    def test_model_performance_empty_without_history(self):
        self.assertEqual(get_agent_model_performance(), [])

    def test_verification_success_rate_mixed_runs(self):
        # Team-Retrospektive nach dem taskpulse-Lauf: get_verification_success_rate() macht
        # eine anhaltend niedrige verification_ok-Quote projektübergreifend sichtbar.
        record_run(project_slug="a", task_summary="x", verification_ok=False, total_tokens=1, duration_seconds=1, agent_results=[])
        record_run(project_slug="b", task_summary="x", verification_ok=False, total_tokens=1, duration_seconds=1, agent_results=[])
        record_run(project_slug="c", task_summary="x", verification_ok=True, total_tokens=1, duration_seconds=1, agent_results=[])

        result = get_verification_success_rate(limit_runs=10)

        self.assertEqual(result["runs"], 3)
        self.assertEqual(result["passed"], 1)
        self.assertAlmostEqual(result["rate"], 33.3, places=1)

    def test_verification_success_rate_respects_window(self):
        for _ in range(5):
            record_run(project_slug="a", task_summary="x", verification_ok=False, total_tokens=1, duration_seconds=1, agent_results=[])
        for _ in range(5):
            record_run(project_slug="b", task_summary="x", verification_ok=True, total_tokens=1, duration_seconds=1, agent_results=[])

        result = get_verification_success_rate(limit_runs=5)

        # Nur die letzten 5 (alle verification_ok=True) zählen, nicht die ersten 5 falschen.
        self.assertEqual(result["runs"], 5)
        self.assertEqual(result["passed"], 5)
        self.assertEqual(result["rate"], 100.0)

    def test_verification_success_rate_empty_without_history(self):
        result = get_verification_success_rate()
        self.assertEqual(result, {"runs": 0, "passed": 0, "rate": 0.0})


if __name__ == "__main__":
    unittest.main()
