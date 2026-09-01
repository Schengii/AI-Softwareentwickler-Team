"""
agents/orchestrator/budget.py – BudgetMixin: Budget-/Kosten-Tracking über zwei unabhängige
Budgets hinweg – das harte, globale Lauf-Budget (config.MAX_RUN_TOKENS) und das optionale,
projektspezifische Kostenbudget aus `/constitution` (self._project_token_budget).
"""

from config import MAX_RUN_TOKENS
from core.token_guard import token_guard


class BudgetMixin:
    """Verfolgt Token-Verbrauch und prüft Lauf-/Projekt-Budgets."""

    @staticmethod
    def _tokens_used_since(start_tokens: int) -> int:
        """Tokenverbrauch SEIT dem Schnappschuss start_tokens (nicht der globale Gesamtzähler)."""
        return token_guard.get_summary()["grand_total_tokens"] - start_tokens

    @staticmethod
    def _model_usage_deltas(start_model_stats: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
        """
        Pro-Modell-Verbrauch SEIT dem Schnappschuss start_model_stats (Pendant zu
        _tokens_used_since(), nur pro Modell statt als einzelner Gesamtwert) – Grundlage für
        memory/cost_history.py.record_run_usage(). Ein Modell, das erst WÄHREND dieses Laufs
        zum ersten Mal genutzt wurde, hatte in start_model_stats naturgemäß noch keinen
        Eintrag (Delta = voller aktueller Wert, nicht 0).

        Realer Fund: "cache_read_tokens"/"cache_write_tokens" fehlten hier bisher komplett -
        record_run_usage() erhielt dadurch für jedes Modell IMMER ein Delta von 0 für beide
        Werte, selbst wenn Prompt-Caching (core/llm_factory.py) tatsächlich Cache-Treffer
        hatte. memory/cost_history.json blieb für diese beiden Spalten dauerhaft bei 0 stehen,
        obwohl core/token_guard.py sie längst korrekt mitzählt.
        """
        end_stats = token_guard.get_summary()["models"]
        deltas: dict[str, dict[str, int]] = {}
        for model_name, end_stat in end_stats.items():
            start_stat = start_model_stats.get(model_name, {})
            deltas[model_name] = {
                key: end_stat.get(key, 0) - start_stat.get(key, 0)
                for key in (
                    "total_calls", "prompt_tokens", "completion_tokens", "total_tokens",
                    "cache_read_tokens", "cache_write_tokens",
                )
            }
        return deltas

    @classmethod
    def _run_budget_exceeded(cls, start_tokens: int) -> bool:
        """MAX_RUN_TOKENS<=0 deaktiviert das harte Budget (Standard) – siehe config.py."""
        if MAX_RUN_TOKENS <= 0:
            return False
        return cls._tokens_used_since(start_tokens) >= MAX_RUN_TOKENS

    def _project_budget_exceeded(self, start_tokens: int) -> bool:
        """
        Pro-Projekt-Kostenbudget (`/constitution` `max_project_tokens`) – unabhängig vom
        globalen MAX_RUN_TOKENS oben, das nur EINEN einzelnen Lauf begrenzt.
        self._project_token_budget<=0 (Standard, kein Feld in der Konstitution gesetzt)
        deaktiviert diese Prüfung vollständig.
        """
        if self._project_token_budget <= 0:
            return False
        total_for_project = self._project_tokens_before_run + self._tokens_used_since(start_tokens)
        return total_for_project >= self._project_token_budget

    def _budget_exceeded_label(self, start_tokens: int) -> str:
        """
        Menschlich lesbare Kennzeichnung, WELCHES der beiden unabhängigen Budgets (Lauf oder
        Projekt) eine Abbruch-Meldung ausgelöst hat – für ehrliche Kommunikation statt
        pauschal auf MAX_RUN_TOKENS zu verweisen, wenn tatsächlich das (u.U. strengere)
        Projekt-Budget bindend war. Nur sinnvoll aufrufbar, wenn mindestens eines von beiden
        tatsächlich überschritten ist.
        """
        if self._project_budget_exceeded(start_tokens):
            return f"Projekt-Budget (`/constitution`, `{self._project_token_budget:,}` Tokens für `{self.last_project_slug}`)"
        return f"Lauf-Budget (`MAX_RUN_TOKENS={MAX_RUN_TOKENS:,}`)"

    def _budget_or_cancel_reason(
        self, budget_aborted: bool, manually_cancelled: bool, stage: str, start_tokens: int | None = None,
    ) -> str:
        """
        Begründungstext für einen übersprungenen nachfolgenden Schritt (Governance-Fix-Schleife/
        Verifikation) – EIN gebündelter Ort statt der Budget-vs.-Abbruch-Fallunterscheidung
        mehrfach inline zu duplizieren. Nur sinnvoll aufrufbar, wenn budget_aborted ODER
        manually_cancelled bereits True ist (siehe process()).
        """
        if budget_aborted:
            label = self._budget_exceeded_label(start_tokens) if start_tokens is not None else f"Lauf-Budget (`MAX_RUN_TOKENS={MAX_RUN_TOKENS:,}`)"
            return f"{label} wurde bereits {stage} erreicht"
        assert manually_cancelled, "aufrufbar nur wenn budget_aborted ODER manually_cancelled True ist"
        return f"Lauf wurde bereits {stage} manuell abgebrochen"
