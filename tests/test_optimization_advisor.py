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

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
import memory.run_history as run_history_module
from core.optimization_advisor import (
    MIN_SAMPLE_SIZE,
    MIN_SUCCESS_RATE_GAP,
    MIN_VERIFICATION_SAMPLE_SIZE,
    ModelSuggestion,
    OptimizationReport,
    analyze,
    apply_auto_tuning,
    format_report_for_humans,
)
from memory.run_history import record_run


class TestOptimizationAdvisor(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._patcher = patch.object(run_history_module, "RUN_HISTORY_FILE", Path(self.temp_dir) / "run_history.json")
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def _record(self, agent_id: str, model: str, success: bool, calls: int = 1, tokens: int = 100):
        for _ in range(calls):
            record_run(
                project_slug="p", task_summary="x", verification_ok=success, total_tokens=1, duration_seconds=1,
                agent_results=[{"agent_id": agent_id, "success": success, "total_tokens": tokens, "model_used": model}],
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

    def test_no_suggestion_when_better_model_is_meaningfully_more_expensive_and_gap_only_moderate(self):
        # Team-Optimierung (Retrospektive, 2026-09-04): model-b hat einen normalerweise
        # ausreichenden Vorsprung (20 Punkte: >= MIN_SUCCESS_RATE_GAP, aber < SIGNIFICANT_
        # SUCCESS_RATE_GAP), verbraucht aber >20% mehr Tokens pro Aufruf (TOKEN_COST_INCREASE_
        # TOLERANCE) - ohne die höhere Hürde für teurere Modelle wäre das ein reiner
        # Mehrverbrauch ohne verhältnismäßigen Nutzen, das Gegenteil von optimaler Tokennutzung.
        self._record("backend", "model-a", success=True, calls=3, tokens=100)
        self._record("backend", "model-a", success=False, calls=2, tokens=100)
        self._record("backend", "model-b", success=True, calls=4, tokens=200)
        self._record("backend", "model-b", success=False, calls=1, tokens=200)

        report = analyze()

        self.assertEqual(report.model_suggestions, [])

    def test_suggests_expensive_model_when_success_gap_is_significant_enough(self):
        # Dieselbe Kostensituation wie oben (model-b deutlich teurer), aber der Erfolgsquoten-
        # Vorsprung erreicht SIGNIFICANT_SUCCESS_RATE_GAP - der Mehrverbrauch ist gerechtfertigt.
        self._record("backend", "model-a", success=True, calls=1, tokens=100)
        self._record("backend", "model-a", success=False, calls=4, tokens=100)
        self._record("backend", "model-b", success=True, calls=5, tokens=200)

        report = analyze()

        self.assertEqual(len(report.model_suggestions), 1)
        s = report.model_suggestions[0]
        self.assertEqual(s.suggested_model, "model-b")
        self.assertEqual(s.current_avg_tokens, 100.0)
        self.assertEqual(s.suggested_avg_tokens, 200.0)

    def test_suggests_cheaper_better_model_without_needing_the_larger_gap(self):
        # Derselbe moderate 20-Punkte-Vorsprung wie im "zu teuer"-Test oben, aber model-b ist
        # hier NICHT teurer (sogar günstiger) - der normale MIN_SUCCESS_RATE_GAP reicht,
        # SIGNIFICANT_SUCCESS_RATE_GAP wird nicht verlangt, wenn kein Mehrverbrauch vorliegt.
        self._record("backend", "model-a", success=True, calls=3, tokens=200)
        self._record("backend", "model-a", success=False, calls=2, tokens=200)
        self._record("backend", "model-b", success=True, calls=4, tokens=100)
        self._record("backend", "model-b", success=False, calls=1, tokens=100)

        report = analyze()

        self.assertEqual(len(report.model_suggestions), 1)
        self.assertEqual(report.model_suggestions[0].suggested_model, "model-b")

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
        self.assertIn("sonst rein informativ", text)
        self.assertIn("backend", text)
        self.assertIn("model-b", text)

    def test_verification_trend_flagged_when_persistently_low(self):
        # Team-Retrospektive nach dem taskpulse-Lauf: mehrere aufeinanderfolgende Läufe mit
        # verification_ok=False (unabhängig vom einzelnen Agenten-Erfolg) müssen als
        # anhaltendes Muster erkannt werden.
        for _ in range(MIN_VERIFICATION_SAMPLE_SIZE):
            record_run(project_slug="p", task_summary="x", verification_ok=False, total_tokens=1, duration_seconds=1, agent_results=[])

        report = analyze()

        self.assertIsNotNone(report.verification_trend)
        self.assertEqual(report.verification_trend.rate, 0.0)
        self.assertFalse(report.is_empty())
        text = format_report_for_humans(report)
        self.assertIn("Verifikations-Trend", text)

    def test_verification_trend_not_flagged_when_healthy(self):
        for _ in range(MIN_VERIFICATION_SAMPLE_SIZE):
            record_run(project_slug="p", task_summary="x", verification_ok=True, total_tokens=1, duration_seconds=1, agent_results=[])

        report = analyze()

        self.assertIsNone(report.verification_trend)

    def test_verification_trend_not_flagged_below_min_sample(self):
        # Nur MIN_VERIFICATION_SAMPLE_SIZE - 1 Läufe - zu wenig Stichprobe für eine Aussage.
        for _ in range(MIN_VERIFICATION_SAMPLE_SIZE - 1):
            record_run(project_slug="p", task_summary="x", verification_ok=False, total_tokens=1, duration_seconds=1, agent_results=[])

        report = analyze()

        self.assertIsNone(report.verification_trend)
        self.assertTrue(report.is_empty())


class TestApplyAutoTuning(unittest.TestCase):
    """
    Testet core/optimization_advisor.py.apply_auto_tuning() - schließt den Kreislauf, den
    _record()-basierte analyze()-Tests oben bewusst offenlassen: eine Empfehlung ist erst dann
    wirklich "Selbstoptimierung", wenn sie (opt-in) auch tatsächlich angewendet wird, statt nur
    im Abschlussbericht zu stehen.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.auto_tuned_file = Path(self.temp_dir) / "auto_tuned_models.json"
        self._flag_patcher = patch.object(config, "ENABLE_AUTO_MODEL_TUNING", True)
        self._file_patcher = patch.object(config, "AUTO_TUNED_MODELS_FILE", str(self.auto_tuned_file))
        self._flag_patcher.start()
        self._file_patcher.start()
        self.addCleanup(self._flag_patcher.stop)
        self.addCleanup(self._file_patcher.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _suggestion(self, agent_id="backend", suggested_model="model-b"):
        return ModelSuggestion(
            agent_id=agent_id, current_model="model-a", current_success_rate=20.0,
            current_calls=5, current_avg_tokens=100.0, suggested_model=suggested_model,
            suggested_success_rate=80.0, suggested_calls=5, suggested_avg_tokens=100.0,
        )

    def test_disabled_flag_is_a_no_op(self):
        with patch.object(config, "ENABLE_AUTO_MODEL_TUNING", False):
            applied = apply_auto_tuning(OptimizationReport(model_suggestions=[self._suggestion()]))

        self.assertEqual(applied, [])
        self.assertFalse(self.auto_tuned_file.exists())

    def test_empty_suggestions_is_a_no_op_even_when_enabled(self):
        applied = apply_auto_tuning(OptimizationReport(model_suggestions=[]))

        self.assertEqual(applied, [])
        self.assertFalse(self.auto_tuned_file.exists())

    def test_enabled_flag_writes_suggested_model_with_context(self):
        applied = apply_auto_tuning(OptimizationReport(model_suggestions=[self._suggestion()]))

        self.assertEqual(applied, ["backend"])
        data = json.loads(self.auto_tuned_file.read_text(encoding="utf-8"))
        self.assertEqual(data["backend"]["model"], "model-b")
        self.assertEqual(data["backend"]["previous_model"], "model-a")
        self.assertIn("applied_at", data["backend"])
        self.assertIn("Empirisch bessere Erfolgsquote", data["backend"]["reason"])

    def test_second_application_merges_instead_of_overwriting_other_agents(self):
        apply_auto_tuning(OptimizationReport(model_suggestions=[self._suggestion(agent_id="backend")]))
        apply_auto_tuning(OptimizationReport(model_suggestions=[self._suggestion(agent_id="frontend")]))

        data = json.loads(self.auto_tuned_file.read_text(encoding="utf-8"))
        self.assertIn("backend", data)
        self.assertIn("frontend", data)

    def test_get_model_for_agent_uses_auto_tuned_model_when_no_explicit_override(self):
        self.auto_tuned_file.write_text(
            json.dumps({"backend": {"model": "auto-tuned-model"}}), encoding="utf-8",
        )
        # Explizit sicherstellen, dass weder ein Rollen- noch ein Fachbereichs-Override aus der
        # echten Laufzeitumgebung dieses Tests dazwischenfunkt (hermetisch, unabhängig davon,
        # was in der lokalen .env sonst konfiguriert ist) - dasselbe Muster wie
        # tests/test_model_routing_matrix.py.
        with patch.object(config, "AGENT_MODELS", {**config.AGENT_MODELS, "backend": config.STANDARD_MODEL}), \
             patch.dict(config.DEPARTMENT_MODELS, {"dev": ""}), \
             patch.dict("os.environ", {"BACKEND_MODEL": ""}):
            self.assertEqual(config.get_model_for_agent("backend"), "auto-tuned-model")

    def test_explicit_env_override_wins_over_auto_tuned_model(self):
        self.auto_tuned_file.write_text(
            json.dumps({"backend": {"model": "auto-tuned-model"}}), encoding="utf-8",
        )
        with patch.dict("os.environ", {"BACKEND_MODEL": "explicit-human-choice"}), \
             patch.object(config, "AGENT_MODELS", {**config.AGENT_MODELS, "backend": "explicit-human-choice"}):
            self.assertEqual(config.get_model_for_agent("backend"), "explicit-human-choice")

    def test_auto_tuning_disabled_ignores_the_file_entirely(self):
        self.auto_tuned_file.write_text(
            json.dumps({"backend": {"model": "auto-tuned-model"}}), encoding="utf-8",
        )
        with patch.object(config, "ENABLE_AUTO_MODEL_TUNING", False), \
             patch.object(config, "AGENT_MODELS", {**config.AGENT_MODELS, "backend": config.STANDARD_MODEL}), \
             patch.dict(config.DEPARTMENT_MODELS, {"dev": ""}), \
             patch.dict("os.environ", {"BACKEND_MODEL": ""}):
            self.assertEqual(config.get_model_for_agent("backend"), config.STANDARD_MODEL)


if __name__ == "__main__":
    unittest.main()
