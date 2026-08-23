"""
tests/test_optimization_advisor.py – Testet core/optimization_advisor.py (datenbasierte
Selbstoptimierungs-Vorschläge über mehrere Läufe hinweg)

Nutzerwunsch: agent_trainer/retrospective analysieren bisher nur EINEN Lauf per LLM. Diese
rein deterministische Auswertung erkennt zwei Muster über memory/run_history.py hinweg: eine
empirisch bessere Modellzuweisung je Agent, und Agenten mit auffällig niedriger Erfolgsquote
gegenüber dem Team-Durchschnitt. Bewusst NUR ein Vorschlag - der Bericht ändert nie config.py.
Nutzt echte record_run()-Aufrufe gegen eine temporäre run_history.json statt roher
Dict-Fixtures, um konsistent mit dem echten Speicherformat zu bleiben.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import memory.run_history as run_history_module
from core.optimization_advisor import (
    MIN_SAMPLE_SIZE,
    MIN_SUCCESS_RATE_GAP,
    analyze,
    format_report_for_humans,
)
from memory.run_history import record_run


class TestOptimizationAdvisor(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._patcher = patch.object(run_history_module, "RUN_HISTORY_FILE", Path(self.temp_dir) / "run_history.json")
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def _record(self, agent_id: str, model: str, success: bool, calls: int = 1):
        for _ in range(calls):
            record_run(
                project_slug="p", task_summary="x", verification_ok=success, total_tokens=1, duration_seconds=1,
                agent_results=[{"agent_id": agent_id, "success": success, "total_tokens": 100, "model_used": model}],
            )

    def test_empty_history_yields_empty_report(self):
        report = analyze()
        self.assertTrue(report.is_empty())
        self.assertEqual(format_report_for_humans(report), "")

    def test_suggests_better_model_when_gap_is_significant(self):
        # backend: model-a scheitert meistens (5 Aufrufe, 20% Erfolg), model-b läuft fast immer (5 Aufrufe, 80% Erfolg).
        self._record("backend", "model-a", success=True, calls=1)
        self._record("backend", "model-a", success=False, calls=4)
        self._record("backend", "model-b", success=True, calls=4)
        self._record("backend", "model-b", success=False, calls=1)

        report = analyze()

        self.assertEqual(len(report.model_suggestions), 1)
        s = report.model_suggestions[0]
        self.assertEqual(s.agent_id, "backend")
        self.assertEqual(s.current_model, "model-a")
        self.assertEqual(s.suggested_model, "model-b")
        self.assertGreaterEqual(s.suggested_success_rate - s.current_success_rate, MIN_SUCCESS_RATE_GAP)

    def test_no_suggestion_when_only_one_model_used(self):
        self._record("backend", "model-a", success=True, calls=MIN_SAMPLE_SIZE)
        report = analyze()
        self.assertEqual(report.model_suggestions, [])

    def test_no_suggestion_when_gap_is_too_small(self):
        # 60% vs. 70% - unter MIN_SUCCESS_RATE_GAP, gilt als Rauschen.
        self._record("backend", "model-a", success=True, calls=3)
        self._record("backend", "model-a", success=False, calls=2)
        self._record("backend", "model-b", success=True, calls=3)
        self._record("backend", "model-b", success=False, calls=1)
        report = analyze()
        self.assertEqual(report.model_suggestions, [])

    def test_no_suggestion_below_min_sample_size(self):
        self._record("backend", "model-a", success=False, calls=2)
        self._record("backend", "model-b", success=True, calls=2)  # jeweils unter MIN_SAMPLE_SIZE
        report = analyze()
        self.assertEqual(report.model_suggestions, [])

    def test_flags_agent_with_low_success_rate_below_team_average(self):
        # Team-Durchschnitt wird von zwei starken Agenten (100%) hochgezogen, "struggling_agent"
        # fällt mit 20% deutlich ab.
        self._record("frontend", "model-a", success=True, calls=MIN_SAMPLE_SIZE)
        self._record("database", "model-a", success=True, calls=MIN_SAMPLE_SIZE)
        self._record("struggling_agent", "model-a", success=True, calls=1)
        self._record("struggling_agent", "model-a", success=False, calls=4)

        report = analyze()

        low = next((a for a in report.low_performing_agents if a.agent_id == "struggling_agent"), None)
        self.assertIsNotNone(low)
        self.assertEqual(low.success_rate, 20.0)

    def test_no_low_performer_flag_when_all_agents_comparable(self):
        self._record("frontend", "model-a", success=True, calls=MIN_SAMPLE_SIZE)
        self._record("database", "model-a", success=True, calls=MIN_SAMPLE_SIZE)
        report = analyze()
        self.assertEqual(report.low_performing_agents, [])

    def test_format_report_includes_both_kinds_of_findings(self):
        self._record("backend", "model-a", success=True, calls=1)
        self._record("backend", "model-a", success=False, calls=4)
        self._record("backend", "model-b", success=True, calls=4)
        self._record("backend", "model-b", success=False, calls=1)
        self._record("weak_agent", "model-a", success=True, calls=1)
        self._record("weak_agent", "model-a", success=False, calls=4)
        self._record("strong_agent", "model-a", success=True, calls=MIN_SAMPLE_SIZE)

        text = format_report_for_humans(analyze())

        self.assertIn("Selbstoptimierungs-Vorschläge", text)
        self.assertIn("keine automatische Änderung", text)
        self.assertIn("backend", text)
        self.assertIn("model-b", text)


if __name__ == "__main__":
    unittest.main()
