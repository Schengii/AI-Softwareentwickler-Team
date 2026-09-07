"""
tests/test_cost_history.py – Testet memory/cost_history.py (kumulierte, sitzungsübergreifende
Kosten-Historie)

Realer Fund: core/token_guard.py ist eine reine In-Memory-Instanz - bei jedem Neustart (neues
CLI-Terminal, neuer Dashboard-Prozess) beginnt der gezeigte Tokenverbrauch wieder bei Null.
Kein Weg zu sehen, wie viele Tokens das Team INSGESAMT seit Beginn der Nutzung verbraucht hat.
"""

import json
import shutil
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import memory.cost_history as cost_history_module
from memory.cost_history import get_lifetime_totals, get_today_totals, record_run_usage


class TestCostHistory(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.file_path = Path(self.temp_dir) / "cost_history.json"
        self._patcher = patch.object(cost_history_module, "COST_HISTORY_FILE", self.file_path)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.addCleanup(lambda: shutil.rmtree(self.temp_dir, ignore_errors=True))

    def test_lifetime_totals_empty_when_never_recorded(self):
        self.assertEqual(get_lifetime_totals(), {})

    def test_records_a_single_run(self):
        record_run_usage({"claude-sonnet-5": {"total_calls": 3, "prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500}})
        totals = get_lifetime_totals()
        self.assertEqual(totals["models"]["claude-sonnet-5"]["total_tokens"], 1500)
        self.assertEqual(totals["runs_recorded"], 1)

    def test_accumulates_across_multiple_runs(self):
        record_run_usage({"gemini-3.6-flash": {"total_calls": 2, "prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300}})
        record_run_usage({"gemini-3.6-flash": {"total_calls": 1, "prompt_tokens": 50, "completion_tokens": 25, "total_tokens": 75}})

        totals = get_lifetime_totals()
        stat = totals["models"]["gemini-3.6-flash"]
        self.assertEqual(stat["total_calls"], 3)
        self.assertEqual(stat["total_tokens"], 375)
        self.assertEqual(totals["runs_recorded"], 2)

    def test_multiple_models_in_the_same_run_are_tracked_separately(self):
        record_run_usage({
            "claude-opus-5": {"total_calls": 1, "prompt_tokens": 500, "completion_tokens": 200, "total_tokens": 700},
            "gemini-3.1-flash-lite": {"total_calls": 4, "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        })
        totals = get_lifetime_totals()
        self.assertEqual(totals["models"]["claude-opus-5"]["total_tokens"], 700)
        self.assertEqual(totals["models"]["gemini-3.1-flash-lite"]["total_tokens"], 150)

    def test_run_with_zero_total_tokens_creates_no_entry(self):
        record_run_usage({"claude-sonnet-5": {"total_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})
        self.assertEqual(get_lifetime_totals(), {})

    def test_zero_delta_model_within_a_nonzero_run_is_not_added(self):
        """Ein Modell mit 0 Tokens Delta (z.B. nie genutzt) darf nicht als leerer Eintrag auftauchen."""
        record_run_usage({
            "claude-sonnet-5": {"total_calls": 1, "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            "unused-model": {"total_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })
        totals = get_lifetime_totals()
        self.assertNotIn("unused-model", totals["models"])

    def test_persists_to_disk_and_survives_reload(self):
        record_run_usage({"claude-sonnet-5": {"total_calls": 1, "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}})
        raw = json.loads(self.file_path.read_text(encoding="utf-8"))
        self.assertEqual(raw["models"]["claude-sonnet-5"]["total_tokens"], 150)

    def test_corrupted_file_does_not_crash(self):
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.write_text("{not valid json", encoding="utf-8")
        self.assertEqual(get_lifetime_totals(), {})
        # Sollte trotzdem wieder normal aufzeichnen können, statt dauerhaft kaputt zu bleiben.
        record_run_usage({"claude-sonnet-5": {"total_calls": 1, "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})
        self.assertEqual(get_lifetime_totals()["models"]["claude-sonnet-5"]["total_tokens"], 15)

    def test_records_first_and_last_recorded_timestamps(self):
        record_run_usage({"claude-sonnet-5": {"total_calls": 1, "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})
        totals = get_lifetime_totals()
        self.assertIn("first_recorded_at", totals)
        self.assertIn("last_recorded_at", totals)

    def test_legacy_entry_missing_cache_keys_does_not_crash_on_next_run(self):
        """
        Realer Fund aus einem echten Praxislauf: memory/cost_history.json wurde ursprünglich
        OHNE "cache_read_tokens"/"cache_write_tokens" geschrieben (bevor diese Spalten zu
        _STAT_KEYS hinzukamen). record_run_usage()s setdefault() füllt einen Standardwert nur
        bei einem komplett NEUEN Modell-Eintrag, NICHT bei einem bereits vorhandenen -
        entry["cache_read_tokens"] += ... schlug deshalb bei jedem folgenden Lauf mit
        KeyError('cache_read_tokens') fehl. Der Lauf selbst überlebte nur, weil
        agents/orchestrator.py diesen Aufruf separat in try/except kapselt - hier wird
        record_run_usage() direkt getestet, ohne dieses Sicherheitsnetz.
        """
        # Simuliert einen alten, VOR der cache_read/write-Erweiterung geschriebenen Eintrag.
        self.file_path.write_text(json.dumps({
            "models": {
                "gemini-3.6-flash": {
                    "total_calls": 5, "prompt_tokens": 500, "completion_tokens": 200, "total_tokens": 700,
                },
            },
            "runs_recorded": 1,
        }), encoding="utf-8")

        record_run_usage({
            "gemini-3.6-flash": {
                "total_calls": 1, "prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70,
                "cache_read_tokens": 30, "cache_write_tokens": 10,
            },
        })

        stat = get_lifetime_totals()["models"]["gemini-3.6-flash"]
        self.assertEqual(stat["total_tokens"], 770)
        self.assertEqual(stat["cache_read_tokens"], 30)
        self.assertEqual(stat["cache_write_tokens"], 10)


class TestCostHistoryDailyBuckets(unittest.TestCase):
    """Testet die Kalendertag-Bucketierung (Team-Optimierung 2026-09-07): Grundlage für eine
    über mehrere kurze CLI-Sitzungen am selben Tag hinweg wirksame Budget-Warnung (siehe
    core/quota_estimator.py.get_proactive_daily_budget_warnings()) - core/token_guard.py allein
    (reiner In-Memory-Zähler pro Prozess) kann das nicht leisten."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.file_path = Path(self.temp_dir) / "cost_history.json"
        self._patcher = patch.object(cost_history_module, "COST_HISTORY_FILE", self.file_path)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.addCleanup(lambda: shutil.rmtree(self.temp_dir, ignore_errors=True))

    def test_today_totals_empty_when_never_recorded(self):
        self.assertEqual(get_today_totals(), {})

    def test_records_today_bucket_alongside_lifetime(self):
        record_run_usage({"claude-sonnet-5": {"total_calls": 1, "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}})
        today_key = datetime.now(UTC).strftime("%Y-%m-%d")
        today = get_today_totals()
        self.assertEqual(today["claude-sonnet-5"]["total_tokens"], 150)
        # get_today_totals() ohne Argument muss identisch zum expliziten heutigen Schlüssel sein.
        self.assertEqual(get_today_totals(today_key), today)

    def test_today_bucket_accumulates_across_multiple_runs_same_day(self):
        record_run_usage({"gemini-3.6-flash": {"total_calls": 1, "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}})
        record_run_usage({"gemini-3.6-flash": {"total_calls": 1, "prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}})
        self.assertEqual(get_today_totals()["gemini-3.6-flash"]["total_tokens"], 180)

    def test_get_today_totals_for_unrecorded_past_day_is_empty(self):
        record_run_usage({"claude-sonnet-5": {"total_calls": 1, "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}})
        self.assertEqual(get_today_totals("2000-01-01"), {})

    def test_daily_buckets_beyond_max_kept_are_pruned(self):
        # 20 künstliche, weit in der Vergangenheit liegende Tage vorab ins Rohformat schreiben -
        # weit über _MAX_DAILY_BUCKETS_KEPT (14) hinaus.
        old_daily = {
            f"2020-01-{day:02d}": {"claude-sonnet-5": {"total_calls": 1, "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cache_read_tokens": 0, "cache_write_tokens": 0}}
            for day in range(1, 21)
        }
        self.file_path.write_text(json.dumps({"models": {}, "daily": old_daily, "runs_recorded": 20}), encoding="utf-8")

        record_run_usage({"claude-sonnet-5": {"total_calls": 1, "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})

        raw = json.loads(self.file_path.read_text(encoding="utf-8"))
        self.assertLessEqual(len(raw["daily"]), cost_history_module._MAX_DAILY_BUCKETS_KEPT + 1)  # +1 für den neu hinzugekommenen heutigen Tag
        # Die ältesten Tage müssen weg sein, die jüngsten (2020-01-20 etc.) erhalten bleiben.
        self.assertNotIn("2020-01-01", raw["daily"])
        self.assertIn("2020-01-20", raw["daily"])

    def test_lifetime_totals_unaffected_by_daily_bucketing(self):
        """Die neue Tages-Bucketierung darf die bestehende, unabhängige Lifetime-Summe nicht
        verändern - reine Ergänzung, kein Ersatz."""
        record_run_usage({"claude-sonnet-5": {"total_calls": 1, "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}})
        totals = get_lifetime_totals()
        self.assertEqual(totals["models"]["claude-sonnet-5"]["total_tokens"], 150)


if __name__ == "__main__":
    unittest.main()
