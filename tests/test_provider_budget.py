"""
tests/test_provider_budget.py – Provider-Budget-Awareness (bekannte Free-Tier-Tageskontingente)

Regressionsschutz für ki_team_verbesserungsanalyse.md Teil 2/P2: Das Team konnte vor einem
Lauf nicht abschätzen, wie knapp die bekannten Free-Tier-Kontingente bereits sind, und probierte
blind, bis die gesamte Fallback-Kette an ihren 429ern hing.
"""

from core.provider_budget import (
    KNOWN_FREE_TIER_DAILY_LIMITS,
    format_budget_report,
    snapshot_budgets,
)
from core.token_guard import TokenGuard


class TestSnapshotBudgets:
    def test_unbenutzte_modelle_erscheinen_nicht(self):
        guard = TokenGuard()
        assert snapshot_budgets(guard) == []

    def test_zaehlt_bekannte_tageskontingente(self):
        guard = TokenGuard()
        for _ in range(3):
            guard.record_usage("gemini-3.1-flash-lite", 100, 50)
        [status] = snapshot_budgets(guard)
        assert status.model_name == "gemini-3.1-flash-lite"
        assert status.used_today == 3
        assert status.daily_limit == KNOWN_FREE_TIER_DAILY_LIMITS["gemini-3.1-flash-lite"]
        assert status.remaining == status.daily_limit - 3
        assert not status.critical

    def test_unbekanntes_modell_wird_ignoriert(self):
        guard = TokenGuard()
        guard.record_usage("claude-sonnet-5", 100, 50)
        assert snapshot_budgets(guard) == []

    def test_kritisch_ab_80_prozent(self):
        guard = TokenGuard()
        # gemini-3.8-flash: bekanntes Limit 20/Tag -> 16 Calls = 80%
        for _ in range(16):
            guard.record_usage("gemini-3.8-flash", 10, 5)
        [status] = snapshot_budgets(guard)
        assert status.critical

    def test_sortiert_nach_hoechster_auslastung_zuerst(self):
        guard = TokenGuard()
        for _ in range(1):
            guard.record_usage("gemini-3.1-flash-lite", 10, 5)  # 1/500 = 0.2%
        for _ in range(18):
            guard.record_usage("gemini-3.8-flash", 10, 5)  # 18/20 = 90%
        result = snapshot_budgets(guard)
        assert [r.model_name for r in result] == ["gemini-3.8-flash", "gemini-3.1-flash-lite"]


class TestFormatBudgetReport:
    def test_leer_ohne_beobachtete_calls(self):
        guard = TokenGuard()
        assert format_budget_report(guard) == ""

    def test_enthaelt_warnung_bei_kritischem_kontingent(self):
        guard = TokenGuard()
        for _ in range(18):
            guard.record_usage("gemini-3.8-flash", 10, 5)
        report = format_budget_report(guard)
        assert "gemini-3.8-flash" in report
        assert "18/20" in report
        assert "🔴" in report
        assert "Tageskontingent" in report

    def test_kein_warnhinweis_wenn_alles_unkritisch(self):
        guard = TokenGuard()
        guard.record_usage("gemini-3.1-flash-lite", 10, 5)
        report = format_budget_report(guard)
        assert "🟢" in report
        assert "🔴" not in report
