"""
core/token_guard.py – Token Guard & Budget Monitoring

Überwacht den Tokenverbrauch in Echtzeit, warnt bei hohen Verbräuchen
und steuert das automatische Downgraden auf leichtere/günstigere Modelle bei Quota-Erschöpfung.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional


@dataclass
class ModelUsageStats:
    """Verbrauchsstatistik für ein Modell."""
    model_name: str
    total_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class TokenGuard:
    """
    Zentraler Token-Wächter für das gesamte KI-Team.
    """

    def __init__(
        self,
        high_usage_threshold_per_call: int = 6000,
        warning_callback: Optional[Callable[[str], None]] = None,
    ):
        self.high_usage_threshold_per_call = high_usage_threshold_per_call
        self.warning_callback = warning_callback
        self._stats: dict[str, ModelUsageStats] = {}
        self._exhausted_models: set[str] = set()

    def record_usage(
        self,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        agent_name: str = "Agent",
    ) -> list[str]:
        """
        Registriert Tokenverbrauch und prüft auf Schwellenwerte.
        Gibt Warnmeldungen zurück, falls Limits überschritten werden.
        """
        total = prompt_tokens + completion_tokens

        if model_name not in self._stats:
            self._stats[model_name] = ModelUsageStats(model_name=model_name)

        stat = self._stats[model_name]
        stat.total_calls += 1
        stat.prompt_tokens += prompt_tokens
        stat.completion_tokens += completion_tokens
        stat.total_tokens += total

        warnings = []

        # 1. Warnung bei überdurchschnittlichem Einzelaufruf
        if total >= self.high_usage_threshold_per_call:
            msg = (
                f"⚠️ Hoher Tokenverbrauch bei {agent_name}: {total:,} Tokens "
                f"({model_name}). Token-Guard empfiehlt Kontext-Straffung."
            )
            warnings.append(msg)
            if self.warning_callback:
                self.warning_callback(msg)

        return warnings

    def mark_model_exhausted(self, model_name: str, reason: str = "Quota erreicht") -> str:
        """Markiert ein Modell als erschöpft / verbraucht."""
        self._exhausted_models.add(model_name)
        msg = f"🚨 Quota-Limit für '{model_name}' erreicht ({reason}). Schalte automatisch auf Fallback-Modell um!"
        if self.warning_callback:
            self.warning_callback(msg)
        return msg

    def is_model_exhausted(self, model_name: str) -> bool:
        return model_name in self._exhausted_models

    def get_summary(self) -> dict:
        """Gibt aggregierte Verbrauchsdaten zurück."""
        return {
            "models": {k: vars(v) for k, v in self._stats.items()},
            "exhausted_models": list(self._exhausted_models),
            "grand_total_tokens": sum(v.total_tokens for v in self._stats.values()),
        }


# Globale Instanz
token_guard = TokenGuard()
