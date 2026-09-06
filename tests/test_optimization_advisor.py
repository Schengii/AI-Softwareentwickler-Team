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
import core.team_memory as team_memory_module
import memory.run_history as run_history_module
from core.optimization_advisor import (
    MIN_LESSON_RECURRENCE,
    MIN_SAMPLE_SIZE,
    MIN_SUCCESS_RATE_GAP,
    MIN_TOTAL_RUNS_FOR_UNUSED_CHECK,
    MIN_VERIFICATION_SAMPLE_SIZE,
    LowPerformingAgent,
    ModelSuggestion,
    OptimizationReport,
    UnusedAgent,
    analyze,
    apply_auto_tuning,
    apply_single_suggestion,
    format_report_for_humans,
    get_recent_verification_trend_warning,
    record_suggestions_as_lessons,
)
from core.team_memory import read_team_lessons
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

    def test_apply_single_suggestion_writes_only_the_named_agent(self):
        """Punkt 4 der Team-Retrospektive (2026-09-06): /apply-tuning <agent_id> übernimmt
        GEZIELT genau einen Vorschlag, nicht alle - unabhängig von ENABLE_AUTO_MODEL_TUNING."""
        with patch.object(config, "ENABLE_AUTO_MODEL_TUNING", False):
            report = OptimizationReport(model_suggestions=[
                self._suggestion(agent_id="backend"),
                self._suggestion(agent_id="frontend", suggested_model="model-f"),
            ])
            applied = apply_single_suggestion(report, "backend")

        self.assertIsNotNone(applied)
        self.assertEqual(applied.agent_id, "backend")
        data = json.loads(self.auto_tuned_file.read_text(encoding="utf-8"))
        self.assertIn("backend", data)
        self.assertNotIn("frontend", data)
        self.assertTrue(data["backend"]["manual"])

    def test_apply_single_suggestion_returns_none_for_unknown_agent(self):
        report = OptimizationReport(model_suggestions=[self._suggestion(agent_id="backend")])
        applied = apply_single_suggestion(report, "does-not-exist")

        self.assertIsNone(applied)
        self.assertFalse(self.auto_tuned_file.exists())

    def test_manual_entry_applies_even_when_auto_tuning_disabled(self):
        """Der ganze Sinn von apply_single_suggestion(): eine explizite Einzel-Bestätigung wirkt
        auch dann, wenn der globale ENABLE_AUTO_MODEL_TUNING-Schalter aus bleibt - anders als
        eine automatisch (apply_auto_tuning()) geschriebene Zeile, siehe
        test_auto_tuning_disabled_ignores_the_file_entirely oben."""
        with patch.object(config, "ENABLE_AUTO_MODEL_TUNING", False):
            report = OptimizationReport(model_suggestions=[self._suggestion(agent_id="backend")])
            apply_single_suggestion(report, "backend")

            with patch.object(config, "AGENT_MODELS", {**config.AGENT_MODELS, "backend": config.STANDARD_MODEL}), \
                 patch.dict(config.DEPARTMENT_MODELS, {"dev": ""}), \
                 patch.dict("os.environ", {"BACKEND_MODEL": ""}):
                self.assertEqual(config.get_model_for_agent("backend"), "model-b")

    def test_auto_applied_entry_still_ignored_when_disabled_afterwards(self):
        """Gegenprobe: ein von apply_auto_tuning() (nicht manuell) geschriebener Eintrag bleibt
        weiterhin an ENABLE_AUTO_MODEL_TUNING gebunden - `manual` unterscheidet die beiden
        Schreibwege, keine unbeabsichtigte globale Aufweichung der bestehenden Opt-in-Regel."""
        apply_auto_tuning(OptimizationReport(model_suggestions=[self._suggestion(agent_id="backend")]))

        with patch.object(config, "ENABLE_AUTO_MODEL_TUNING", False), \
             patch.object(config, "AGENT_MODELS", {**config.AGENT_MODELS, "backend": config.STANDARD_MODEL}), \
             patch.dict(config.DEPARTMENT_MODELS, {"dev": ""}), \
             patch.dict("os.environ", {"BACKEND_MODEL": ""}):
            self.assertEqual(config.get_model_for_agent("backend"), config.STANDARD_MODEL)


class TestRecurringLessonCategories(unittest.TestCase):
    """
    Testet Punkt 5 der Team-Retrospektive (2026-09-06): core/optimization_advisor.py.analyze()
    erkennt jetzt zusätzlich, wenn dieselbe team_lessons.jsonl-Kategorie am selben Projekt
    MIN_LESSON_RECURRENCE-mal oder öfter auftritt - ein Muster, das der reguläre
    Fix-/Governance-Loop an diesem Projekt offenbar nicht dauerhaft behebt.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._patcher = patch.object(
            team_memory_module, "TEAM_MEMORY_FILE", Path(self.temp_dir) / "team_lessons.jsonl",
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_flags_recurring_category_at_same_project(self):
        for i in range(MIN_LESSON_RECURRENCE):
            team_memory_module.record_lesson("mockforge", "unresolved_governance_critical", f"Fund Nr. {i}")

        report = analyze()

        self.assertEqual(len(report.recurring_lesson_categories), 1)
        finding = report.recurring_lesson_categories[0]
        self.assertEqual(finding.project_slug, "mockforge")
        self.assertEqual(finding.category, "unresolved_governance_critical")
        self.assertEqual(finding.count, MIN_LESSON_RECURRENCE)
        self.assertFalse(report.is_empty())

    def test_no_flag_below_recurrence_threshold(self):
        for i in range(MIN_LESSON_RECURRENCE - 1):
            team_memory_module.record_lesson("mockforge", "unresolved_governance_critical", f"Fund Nr. {i}")

        report = analyze()

        self.assertEqual(report.recurring_lesson_categories, [])

    def test_different_projects_are_not_conflated(self):
        for i in range(MIN_LESSON_RECURRENCE):
            team_memory_module.record_lesson("mockforge", "unresolved_governance_critical", f"Fund A {i}")
        for i in range(MIN_LESSON_RECURRENCE - 1):
            team_memory_module.record_lesson("logpulse", "unresolved_governance_critical", f"Fund B {i}")

        report = analyze()

        projects_flagged = {f.project_slug for f in report.recurring_lesson_categories}
        self.assertEqual(projects_flagged, {"mockforge"})

    def test_format_report_includes_recurring_category(self):
        for i in range(MIN_LESSON_RECURRENCE):
            team_memory_module.record_lesson("mockforge", "unresolved_governance_critical", f"Fund Nr. {i}")

        text = format_report_for_humans(analyze())

        self.assertIn("unresolved_governance_critical", text)
        self.assertIn("mockforge", text)


class TestUnusedAgents(unittest.TestCase):
    """
    Testet die neue Unterauslastungs-Erkennung (Team-Wachstums-Retrospektive 2026-09-06):
    core/optimization_advisor.py.analyze() erkannte bisher nur AUFGERUFENE Agenten mit
    schlechter Erfolgsquote (LowPerformingAgent), nicht Rollen, die der Planer über viele
    Läufe hinweg NIE auswählt - relevant vor allem für ein wachsendes Team mit immer mehr
    Rollen, bei dem eine ungenutzte Rolle sonst unbemerkt Wartungsaufwand bindet.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._run_history_patcher = patch.object(
            run_history_module, "RUN_HISTORY_FILE", Path(self.temp_dir) / "run_history.json",
        )
        self._run_history_patcher.start()
        self.addCleanup(self._run_history_patcher.stop)

        # Deterministisch: nur zwei "wählbare" Rollen statt aller 33, damit die Tests nicht
        # von der echten AVAILABLE_AGENTS-Liste abhängen.
        self._agents_patcher = patch(
            "core.optimization_advisor.AVAILABLE_AGENTS",
            {
                "backend": {"name": "Backend", "phase": 3, "description": "..."},
                "readme": {"name": "Readme", "phase": 6, "description": "..."},
            },
        )
        self._agents_patcher.start()
        self.addCleanup(self._agents_patcher.stop)

    def _record(self, agent_id: str):
        record_run(
            project_slug="p", task_summary="x", verification_ok=True, total_tokens=1, duration_seconds=1,
            agent_results=[{"agent_id": agent_id, "success": True, "total_tokens": 100, "model_used": "m"}],
        )

    def test_flags_agent_never_selected_over_enough_runs(self):
        for _ in range(MIN_TOTAL_RUNS_FOR_UNUSED_CHECK):
            self._record("backend")  # "readme" wird in keinem der Läufe aufgerufen

        report = analyze()

        self.assertEqual(len(report.unused_agents), 1)
        self.assertEqual(report.unused_agents[0].agent_id, "readme")
        self.assertFalse(report.is_empty())

    def test_no_flag_when_every_selectable_agent_was_used(self):
        for _ in range(MIN_TOTAL_RUNS_FOR_UNUSED_CHECK):
            self._record("backend")
            self._record("readme")

        report = analyze()

        self.assertEqual(report.unused_agents, [])

    def test_no_flag_below_minimum_total_runs(self):
        # Nur wenige Läufe insgesamt - "nie gewählt" wäre hier noch reines Rauschen.
        for _ in range(MIN_TOTAL_RUNS_FOR_UNUSED_CHECK - 1):
            self._record("backend")

        report = analyze()

        self.assertEqual(report.unused_agents, [])

    def test_format_report_includes_unused_agent(self):
        for _ in range(MIN_TOTAL_RUNS_FOR_UNUSED_CHECK):
            self._record("backend")

        text = format_report_for_humans(analyze())

        self.assertIn("readme", text)
        self.assertIn("kein einziges Mal vom Planer ausgewählt", text)

    def test_record_suggestions_as_lessons_writes_unused_agent_lesson(self):
        unused = UnusedAgent(agent_id="readme", configured_model="gemini-3.1-flash-lite", sample_runs=20)
        with patch.object(team_memory_module, "TEAM_MEMORY_FILE", Path(self.temp_dir) / "team_lessons.jsonl"):
            record_suggestions_as_lessons(OptimizationReport(unused_agents=[unused]))
            lessons = read_team_lessons(limit=10)
        self.assertEqual(len(lessons), 1)
        self.assertEqual(lessons[0]["category"], "unused_agent")
        self.assertIn("readme", lessons[0]["detail"])


class TestRecordSuggestionsAsLessons(unittest.TestCase):
    """
    Testet Punkt 2 der Team-Retrospektive (2026-09-06): record_suggestions_as_lessons() macht
    Modell-/Underperformer-Funde auch dann teamweit sichtbar, wenn ENABLE_AUTO_MODEL_TUNING
    (bewusst) aus ist und niemand den Abschlussbericht dieses einen Laufs liest.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._patcher = patch.object(
            team_memory_module, "TEAM_MEMORY_FILE", Path(self.temp_dir) / "team_lessons.jsonl",
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_records_a_lesson_for_each_model_suggestion(self):
        suggestion = ModelSuggestion(
            agent_id="backend", current_model="model-a", current_success_rate=20.0,
            current_calls=5, current_avg_tokens=100.0, suggested_model="model-b",
            suggested_success_rate=80.0, suggested_calls=5, suggested_avg_tokens=100.0,
        )
        record_suggestions_as_lessons(OptimizationReport(model_suggestions=[suggestion]))

        lessons = read_team_lessons(limit=10)
        self.assertEqual(len(lessons), 1)
        self.assertEqual(lessons[0]["category"], "model_performance")
        self.assertIn("backend", lessons[0]["detail"])

    def test_records_a_lesson_for_each_low_performing_agent(self):
        low_performer = LowPerformingAgent(agent_id="frontend", success_rate=20.0, calls=5, team_average=85.0)
        record_suggestions_as_lessons(OptimizationReport(low_performing_agents=[low_performer]))

        lessons = read_team_lessons(limit=10)
        self.assertEqual(len(lessons), 1)
        self.assertEqual(lessons[0]["category"], "low_performing_agent")
        self.assertIn("frontend", lessons[0]["detail"])

    def test_empty_report_records_nothing(self):
        record_suggestions_as_lessons(OptimizationReport())

        self.assertEqual(read_team_lessons(limit=10), [])


class TestVerificationTrendWarning(unittest.TestCase):
    """Testet Punkt 3 der Team-Retrospektive (2026-09-06): get_recent_verification_trend_warning()
    liefert den kurzen, einzeiligen Hinweis für core/goal_loop.py's Eval-Prompt."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._patcher = patch.object(run_history_module, "RUN_HISTORY_FILE", Path(self.temp_dir) / "run_history.json")
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_empty_history_yields_no_warning(self):
        self.assertEqual(get_recent_verification_trend_warning(), "")

    def test_persistent_failures_yield_warning(self):
        for _ in range(MIN_VERIFICATION_SAMPLE_SIZE):
            record_run(project_slug="p", task_summary="x", verification_ok=False, total_tokens=1, duration_seconds=1, agent_results=[])

        warning = get_recent_verification_trend_warning()

        self.assertIn("Verifikations-Trend", warning)


if __name__ == "__main__":
    unittest.main()
