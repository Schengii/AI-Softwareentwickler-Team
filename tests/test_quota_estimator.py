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


if __name__ == "__main__":
    unittest.main()
