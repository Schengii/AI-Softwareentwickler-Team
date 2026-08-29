"""
core/token_guard.py – Token Guard & Intelligentes Quota-Lifecycle-Management

Überwacht:
- Tokenverbrauch in Echtzeit
- Automatisches Umschalten auf Fallback-Modelle bei Quota-Erschöpfung (429 / Rate Limit)
- Zeitgesteuertes, automatisches Reaktivieren der Primärmodelle, sobald das Quota-Reset-Intervall abgelaufen ist (z. B. nach 60s für RPM/TPM oder nächstem Zyklus)
"""

import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class ModelUsageStats:
    """Verbrauchsstatistik für ein Modell."""
    model_name: str
    total_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class ExhaustedModelInfo:
    """Informationen über ein temporär erschöpftes Modell."""
    model_name: str
    exhausted_at: float
    cooldown_seconds: float
    reason: str


class TokenGuard:
    """
    Zentraler Token-Wächter mit automatischer Modell-Wiederherstellung (Auto-Recovery).
    """

    def __init__(
        self,
        high_usage_threshold_per_call: int = 6000,
        default_cooldown_seconds: float = 60.0,
        warning_callback: Callable[[str], None] | None = None,
    ):
        self.high_usage_threshold_per_call = high_usage_threshold_per_call
        self.default_cooldown_seconds = default_cooldown_seconds
        self.warning_callback = warning_callback
        self._stats: dict[str, ModelUsageStats] = {}
        self._exhausted_models: dict[str, ExhaustedModelInfo] = {}

    def record_usage(
        self,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        agent_name: str = "Agent",
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
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
        stat.cache_read_tokens += cache_read_tokens
        stat.cache_write_tokens += cache_write_tokens

        # Wenn ein Modell erfolgreich antwortet, ist es definitiv wieder aktiv
        if model_name in self._exhausted_models:
            del self._exhausted_models[model_name]

        warnings = []

        if total >= self.high_usage_threshold_per_call:
            msg = (
                f"⚠️ Hoher Tokenverbrauch bei {agent_name}: {total:,} Tokens "
                f"({model_name}). Token-Guard empfiehlt Kontext-Straffung."
            )
            warnings.append(msg)
            if self.warning_callback:
                self.warning_callback(msg)

        return warnings

    def mark_model_exhausted(
        self,
        model_name: str,
        reason: str = "Quota erreicht",
        cooldown_seconds: float | None = None
    ) -> str:
        """Markiert ein Modell als temporär erschöpft mit Cooldown-Timer."""
        cooldown = cooldown_seconds if cooldown_seconds is not None else self.default_cooldown_seconds
        self._exhausted_models[model_name] = ExhaustedModelInfo(
            model_name=model_name,
            exhausted_at=time.monotonic(),
            cooldown_seconds=cooldown,
            reason=reason
        )
        msg = f"🚨 Quota-Limit für '{model_name}' erreicht ({reason}). Schalte automatisch auf Fallback-Modell um (Cooldown: {cooldown:.0f}s)!"
        if self.warning_callback:
            self.warning_callback(msg)
        return msg

    def is_model_exhausted(self, model_name: str) -> bool:
        """
        Prüft, ob ein Modell noch erschöpft ist.
        Wenn der Cooldown abgelaufen ist, wird das Modell automatisch wieder reaktiviert!
        """
        if model_name not in self._exhausted_models:
            return False

        info = self._exhausted_models[model_name]
        elapsed = time.monotonic() - info.exhausted_at

        # Cooldown abgelaufen? -> Modell wieder freigeben!
        if elapsed >= info.cooldown_seconds:
            del self._exhausted_models[model_name]
            msg = f"🔄 Quota-Reset: '{model_name}' wurde nach {elapsed:.0f}s Cooldown automatisch wieder reaktiviert!"
            if self.warning_callback:
                self.warning_callback(msg)
            return False

        return True

    def seconds_until_available(self, model_names: list[str]) -> float:
        """
        Gibt zurück, wie viele Sekunden mindestens gewartet werden muss, bis WENIGSTENS
        eines der genannten Modelle wieder verfügbar ist – 0.0, wenn eines davon bereits
        verfügbar ist (oder gar keines als erschöpft bekannt ist).

        Wird genutzt, um bei einer komplett erschöpften Fallback-Kette (z.B. alle
        Gratis-Kontingente gleichzeitig an ihrem Minutenlimit) kurz auf den kürzesten
        bekannten Cooldown zu warten, statt sofort denselben 429-Fehler erneut zu kassieren
        (siehe core/llm_factory.py, GeminiClient.generate_with_tools/generate_with_usage).
        """
        waits: list[float] = []
        for name in model_names:
            if name not in self._exhausted_models:
                return 0.0
            info = self._exhausted_models[name]
            remaining = info.cooldown_seconds - (time.monotonic() - info.exhausted_at)
            if remaining <= 0:
                return 0.0
            waits.append(remaining)
        return min(waits) if waits else 0.0

    def get_summary(self) -> dict:
        """
        Gibt aggregierte Verbrauchsdaten zurück – ein echter SNAPSHOT, kein Live-Blick auf den
        internen Zustand. Realer Fund: `vars(v)` liefert direkt `v.__dict__` zurück (keine
        Kopie) – ein Aufrufer, der sich `get_summary()["models"]` als "Stand zu diesem
        Zeitpunkt" merkt (z.B. für eine Delta-Berechnung, siehe
        agents/orchestrator.py._model_usage_deltas()), sah durch nachfolgende record_usage()-
        Aufrufe unbemerkt den STAND ZUM SPÄTEREN ZEITPUNKT, weil beide Referenzen auf
        dasselbe Dict zeigten – jede berechnete Differenz wäre dadurch fälschlich 0 gewesen.
        `dict(vars(v))` erzeugt eine echte flache Kopie.
        """
        # Bereinige abgelaufene Modelle
        for m in list(self._exhausted_models.keys()):
            self.is_model_exhausted(m)

        return {
            "models": {k: dict(vars(v)) for k, v in self._stats.items()},
            "exhausted_models": list(self._exhausted_models.keys()),
            "grand_total_tokens": sum(v.total_tokens for v in self._stats.values()),
        }


# Globale Instanz
token_guard = TokenGuard()
