"""
core/provider_budget.py – Provider-Budget-Awareness (bekannte Free-Tier-Kontingente).

Ursprung (ki_team_verbesserungsanalyse.md, Teil 2/P2, 10.09.2026): Das Team hatte keinerlei
Kenntnis über die tatsächlichen Tageskontingente der Provider und probierte bei jedem Aufruf
blind, bis die komplette Fallback-Kette (Claude -> DeepSeek -> OpenRouter -> Gemini-Stufen ->
Groq) an ihre 429er lief. Ein einzelner Lauf (auditlog_sentinel, 10.09.2026) verbrauchte dabei
40+ Calls, wovon praktisch alle auf `gemini-3.1-flash-lite` landeten, weil dessen Free-Tier-
Kontingent (500 Calls/Tag) das einzige war, das noch nicht erschöpft war.

Dieses Modul schätzt VOR einem Lauf ab, wie viel bekanntes Tageskontingent auf den in DIESEM
Prozess bereits beobachteten Modellen noch übrig ist, und warnt, wenn das knapp wird. Bewusst
KEIN Persistenz-Layer über Prozessgrenzen hinweg (Provider melden Tages-Resets ohnehin nicht
exakt vorhersehbar) - die Zahlen sind eine grobe Heuristik für den aktuellen Prozess, kein
exaktes Accounting. Die tatsächliche Quelle der Wahrheit bleibt der reale 429-Fehler
(core/token_guard.py.mark_model_exhausted), dieses Modul ergänzt nur eine PROAKTIVE Warnung,
bevor die Kette das erst live herausfindet.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.token_guard import TokenGuard

# Bekannte/beobachtete Free-Tier-Tageskontingente (Calls/Tag). Grobe, aus echten Lauf-Logs
# gewonnene Schätzwerte (siehe ki_team_verbesserungsanalyse.md Teil 4.1) - keine offiziellen,
# garantierten Werte der Anbieter, da diese sich ändern können und je nach Account variieren.
KNOWN_FREE_TIER_DAILY_LIMITS: dict[str, int] = {
    "gemini-3.1-flash-lite": 500,
    "gemini-3.8-flash": 20,
    "gemini-3.6-flash": 100,
    "groq:openai/gpt-oss-120b": 30,
}

# Ab diesem Anteil des bekannten Tageskontingents wird gewarnt statt nur informiert.
WARNING_THRESHOLD = 0.8


@dataclass(frozen=True)
class ProviderBudgetStatus:
    model_name: str
    daily_limit: int
    used_today: int

    @property
    def remaining(self) -> int:
        return max(0, self.daily_limit - self.used_today)

    @property
    def usage_ratio(self) -> float:
        return self.used_today / self.daily_limit if self.daily_limit else 0.0

    @property
    def critical(self) -> bool:
        return self.usage_ratio >= WARNING_THRESHOLD


def snapshot_budgets(guard: TokenGuard) -> list[ProviderBudgetStatus]:
    """Vergleicht die in DIESEM Prozess bereits gezählten Aufrufe (guard._stats) mit den
    bekannten Tageskontingenten. Nur Modelle mit bekanntem Limit UND mindestens einem
    beobachteten Call werden gemeldet - unbekannte/ungenutzte Modelle sind kein Budget-Risiko."""
    stats = guard._stats  # noqa: SLF001 - bewusster, dokumentierter Zugriff innerhalb desselben Package
    result = []
    for model_name, limit in KNOWN_FREE_TIER_DAILY_LIMITS.items():
        used = stats[model_name].total_calls if model_name in stats else 0
        if used == 0:
            continue
        result.append(ProviderBudgetStatus(model_name=model_name, daily_limit=limit, used_today=used))
    return sorted(result, key=lambda b: b.usage_ratio, reverse=True)


def format_budget_report(guard: TokenGuard) -> str:
    """Menschenlesbarer Bericht über das bekannte Tageskontingent der bisher in diesem Prozess
    genutzten Free-Tier-Modelle. Leer (keine Zeilen), wenn noch keines davon benutzt wurde."""
    budgets = snapshot_budgets(guard)
    if not budgets:
        return ""
    zeilen = ["", "💰 Provider-Budget (bekannte Free-Tier-Tageskontingente, dieser Prozess)", "─" * 88]
    any_critical = False
    for b in budgets:
        marker = "🔴" if b.critical else "🟢"
        if b.critical:
            any_critical = True
        zeilen.append(
            f"{marker} {b.model_name:<28} {b.used_today}/{b.daily_limit} Calls "
            f"(~{b.usage_ratio:.0%}, {b.remaining} übrig)"
        )
    if any_critical:
        zeilen.append(
            "⚠️  Mindestens ein Modell ist nahe seinem bekannten Tageskontingent. Weitere Läufe "
            "landen wahrscheinlich zunehmend auf schwächeren Fallback-Stufen oder scheitern ganz."
        )
    return "\n".join(zeilen)
