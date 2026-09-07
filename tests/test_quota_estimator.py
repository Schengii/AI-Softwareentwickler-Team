"""
tests/test_quota_estimator.py – Testet den /tokens-Verbrauchsreport (core/quota_estimator.py)

Realer Fund: Seit der Einführung des Claude-Modell-Tierings fehlte Claude komplett in der
Provider-Aufschlüsselung – Tokenverbrauch gegen claude-* Modelle fiel in den nirgends
angezeigten "other"-Topf und war im /tokens-Report unsichtbar.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import core.quota_estimator as quota_estimator_module
import memory.cost_history as cost_history_module
from core.quota_estimator import QuotaEstimator
from core.token_guard import TokenGuard
from memory.cost_history import record_run_usage


class TestProactiveDailyBudgetWarnings(unittest.TestCase):
    """Testet get_proactive_daily_budget_warnings() (Team-Optimierung 2026-09-07): tagesweite
    Warnung ÜBER SITZUNGSGRENZEN HINWEG, gespeist aus memory/cost_history.py.get_today_totals()
    statt aus dem sitzungsgebundenen core/token_guard.py."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._cost_patcher = patch.object(
            cost_history_module, "COST_HISTORY_FILE", Path(self.temp_dir) / "cost_history.json",
        )
        self._cost_patcher.start()
        self.addCleanup(self._cost_patcher.stop)
        self.addCleanup(lambda: shutil.rmtree(self.temp_dir, ignore_errors=True))

    def test_no_warning_below_threshold(self):
        record_run_usage({"groq:openai/gpt-oss-120b": {"total_calls": 1, "prompt_tokens": 800, "completion_tokens": 200, "total_tokens": 1000}})
        self.assertEqual(QuotaEstimator.get_proactive_daily_budget_warnings(), [])

    def test_warning_above_threshold_across_simulated_sessions(self):
        # Zwei getrennte record_run_usage()-Aufrufe simulieren zwei kurze CLI-Sitzungen am
        # selben Tag - token_guard (session-gebunden) hätte das NICHT summiert gesehen.
        record_run_usage({"groq:openai/gpt-oss-120b": {"total_calls": 1, "prompt_tokens": 300_000, "completion_tokens": 0, "total_tokens": 300_000}})
        record_run_usage({"groq:openai/gpt-oss-120b": {"total_calls": 1, "prompt_tokens": 150_000, "completion_tokens": 0, "total_tokens": 150_000}})
        warnings = QuotaEstimator.get_proactive_daily_budget_warnings()
        self.assertTrue(any("Groq" in w for w in warnings))

    def test_provider_without_daily_budget_never_warns(self):
        record_run_usage({"claude-sonnet-5": {"total_calls": 1, "prompt_tokens": 10_000_000, "completion_tokens": 5_000_000, "total_tokens": 15_000_000}})
        warnings = QuotaEstimator.get_proactive_daily_budget_warnings()
        self.assertFalse(any("Claude" in w for w in warnings))

    def test_no_recorded_usage_today_produces_no_warnings(self):
        self.assertEqual(QuotaEstimator.get_proactive_daily_budget_warnings(), [])

    def test_custom_threshold_is_respected(self):
        record_run_usage({"groq:openai/gpt-oss-120b": {"total_calls": 1, "prompt_tokens": 200_000, "completion_tokens": 0, "total_tokens": 200_000}})
        self.assertEqual(QuotaEstimator.get_proactive_daily_budget_warnings(threshold=0.5), [])
        warnings = QuotaEstimator.get_proactive_daily_budget_warnings(threshold=0.3)
        self.assertTrue(any("Groq" in w for w in warnings))


class TestQuotaEstimator(unittest.TestCase):
    def setUp(self):
        # Isolierter TokenGuard statt des globalen Singletons, damit Tests sich nicht
        # gegenseitig beeinflussen.
        self._original_token_guard = quota_estimator_module.token_guard
        quota_estimator_module.token_guard = TokenGuard()

        # Isolierte Kosten-Historie-Datei, damit Tests nicht die echte
        # memory/cost_history.json des Repos lesen/beschreiben.
        self.temp_dir = tempfile.mkdtemp()
        self._cost_patcher = patch.object(
            cost_history_module, "COST_HISTORY_FILE", Path(self.temp_dir) / "cost_history.json",
        )
        self._cost_patcher.start()

    def tearDown(self):
        quota_estimator_module.token_guard = self._original_token_guard
        self._cost_patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_claude_usage_is_visible_in_report(self):
        quota_estimator_module.token_guard.record_usage("claude-sonnet-5", 500, 200)
        report = QuotaEstimator.get_detailed_report()
        self.assertEqual(report["provider_usage"]["claude"], 700)

    def test_claude_appears_in_markdown_table_without_misleading_zero_budget(self):
        quota_estimator_module.token_guard.record_usage("claude-opus-5", 1000, 500)
        table = QuotaEstimator.format_markdown_table()
        claude_row = next(line for line in table.splitlines() if "Anthropic Claude" in line)
        self.assertIn("1,500", claude_row)
        # Claude hat kein Free-Tier-Kontingent -> darf NICHT "X Tokens übrig" vortäuschen
        self.assertNotIn("Tokens übrig", claude_row)

    def test_gemini_and_groq_usage_still_bucketed_correctly(self):
        quota_estimator_module.token_guard.record_usage("gemini-3.6-flash", 300, 100)
        quota_estimator_module.token_guard.record_usage("groq:openai/gpt-oss-120b", 50, 20)
        report = QuotaEstimator.get_detailed_report()
        self.assertEqual(report["provider_usage"]["gemini"], 400)
        self.assertEqual(report["provider_usage"]["groq"], 70)
        self.assertEqual(report["provider_usage"]["claude"], 0)

    def test_no_lifetime_section_without_recorded_history(self):
        table = QuotaEstimator.format_markdown_table()
        self.assertNotIn("Kumulierter Verbrauch", table)

    def test_lifetime_section_shows_cumulative_totals_across_sessions(self):
        record_run_usage({"claude-sonnet-5": {"total_calls": 2, "prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500}})
        record_run_usage({"claude-sonnet-5": {"total_calls": 1, "prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300}})

        table = QuotaEstimator.format_markdown_table()

        self.assertIn("Kumulierter Verbrauch", table)
        self.assertIn("1,800", table)  # 1500 + 300, unabhängig vom aktuellen Sitzungs-Zähler
        self.assertIn("claude-sonnet-5", table)

    def test_agent_availability_reflects_exhausted_model(self):
        """
        Nutzeranfrage: Übersicht, welche AGENTEN (nicht nur welche Modelle) gerade betroffen
        sind, wenn ein Modell erschöpft ist, und wann es wieder verfügbar ist. Ermittelt das
        Modell des "architect"-Agenten dynamisch über `get_model_for_agent()` statt es
        hart zu kodieren - welches Modell einer Rolle zugeordnet ist, hängt von
        Env-Overrides ab (siehe config.AGENT_MODELS), auch von hier nicht kontrollierten
        .env-Werten in der jeweiligen Umgebung.
        """
        from config import get_model_for_agent
        target_model = get_model_for_agent("architect")
        quota_estimator_module.token_guard.mark_model_exhausted(
            target_model, reason="Test: simulierte Quota-Erschöpfung", cooldown_seconds=120.0,
        )
        rows = QuotaEstimator.get_agent_availability()
        affected_rows = [r for r in rows if r["model_name"] == target_model]
        self.assertIn("architect", [r["agent_id"] for r in affected_rows])
        for row in affected_rows:
            self.assertFalse(row["available"])
            self.assertIsNotNone(row["available_at"])
            self.assertEqual(row["reason"], "Test: simulierte Quota-Erschöpfung")

        # Ein Agent auf einem NICHT erschöpften Modell bleibt verfügbar.
        available_rows = [r for r in rows if r["model_name"] != target_model]
        self.assertTrue(available_rows)
        for row in available_rows:
            self.assertTrue(row["available"])
            self.assertIsNone(row["available_at"])

    def test_markdown_table_shows_exhausted_models_with_eta_and_affected_agents(self):
        from config import get_model_for_agent
        target_model = get_model_for_agent("tester")
        quota_estimator_module.token_guard.mark_model_exhausted(
            target_model, reason="429 Quota Exceeded", cooldown_seconds=60.0,
        )
        table = QuotaEstimator.format_markdown_table()

        self.assertIn("Aktuell erschöpfte Modelle", table)
        self.assertIn(target_model, table)
        self.assertIn("429 Quota Exceeded", table)
        self.assertIn("Agenten → Modell-Zuordnung", table)
        self.assertIn("🚨 Cooldown bis", table)
        self.assertIn("🟢 Verfügbar", table)

    def test_markdown_table_has_no_exhausted_section_when_everything_is_available(self):
        table = QuotaEstimator.format_markdown_table()
        self.assertNotIn("Aktuell erschöpfte Modelle", table)
        self.assertIn("🟢 Verfügbar", table)
        self.assertNotIn("🚨 Cooldown bis", table)


if __name__ == "__main__":
    unittest.main()
