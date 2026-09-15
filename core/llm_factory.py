"""
core/llm_factory.py – Erstellt und verwaltet LLM-Clients (Gemini, Groq, DeepSeek, OpenRouter,
HuggingFace, Claude) mit einheitlicher Schnittstelle (Text, JSON, Function-Calling).

Enthält Token-Messung, Gemini-Key-Pool, provider-übergreifende Fallback-Ketten, Cooldowns
für Rate-Limits/Kontingent-/Auth-Fehler (via core/token_guard.py) und sichtbare Modell-Abwertungen.
"""

import asyncio
import contextlib
import contextvars
import json
import os
import re
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

import httpx
from google import genai
from google.genai import types as genai_types

from config import (
    ANTHROPIC_API_KEY,
    DEEPSEEK_API_KEY,
    GEMINI_API_KEYS,
    GEMINI_MAX_CALLS_PER_MINUTE,
    GEMINI_STANDARD_MODEL,
    GROQ_API_KEY,
    GROQ_FALLBACK_MODELS,
    GROQ_HEAVY_MODEL,
    HUGGINGFACE_API_KEY,
    MAX_OUTPUT_TOKENS,
    OPENROUTER_API_KEY,
    TEMPERATURE,
)
from core.model_capability import CapabilityFloorError, filter_by_floor, record_downgrade
from core.rate_limiter import RateLimiter
from core.token_guard import token_guard

# ──────────────────────────────────────────
# Gemini API-Key-Pool & Client-Manager
# ──────────────────────────────────────────
# Mehrere Gemini-Keys (kommagetrennt oder GEMINI_API_KEY_1..N). Ein Key mit 429
# RESOURCE_EXHAUSTED wird temporär deaktiviert und auf den nächsten umgeschaltet.
_gemini_clients_by_key: dict[str, genai.Client] = {}
_gemini_model_exhausted_keys: dict[tuple[str, str], float] = {}  # (key, model) -> timestamp bis wann key für dieses Modell erschöpft
_gemini_active_key_index: int = 0
_gemini_active_model: str = ""


class _ExhaustedKeysDict(dict):
    """Spezialisiertes Dict, das bei .clear() auch das modell-spezifische Dict bereinigt (wichtig für Test-Setups)."""
    def clear(self):
        super().clear()
        _gemini_model_exhausted_keys.clear()


_gemini_exhausted_keys: dict[str, float] = _ExhaustedKeysDict()  # key -> timestamp bis wann key global erschöpft


def _get_gemini_client(model: str = "") -> tuple[genai.Client | None, str]:
    """Gibt den aktiven (nicht erschöpften) Gemini-Client und dessen Key zurück.

    Mit `model` zählen auch modellspezifisch erschöpfte Keys: das Free-Tier limitiert
    manche Modelle pro Modell, andere Modelle bleiben auf demselben Key frei.
    """
    global _gemini_active_key_index
    import os
    import time
    now = time.time()
    effective_model = model or _gemini_active_model

    # Abgelaufene Cooldowns bei Keys bereinigen
    expired = [k for k, until in _gemini_exhausted_keys.items() if now >= until]
    for k in expired:
        _gemini_exhausted_keys.pop(k, None)

    expired_m = [km for km, until in _gemini_model_exhausted_keys.items() if now >= until]
    for km in expired_m:
        _gemini_model_exhausted_keys.pop(km, None)

    from config import _collect_gemini_api_keys
    # Priorisiere GEMINI_API_KEYS (falls im Modul gepatcht/gesetzt) vor _collect_gemini_api_keys()
    keys = GEMINI_API_KEYS or _collect_gemini_api_keys() or ([os.getenv("GEMINI_API_KEY")] if os.getenv("GEMINI_API_KEY") else [])
    if not keys:
        return None, ""

    def is_key_exhausted(k: str) -> bool:
        if k in _gemini_exhausted_keys:
            return True
        if effective_model and (k, effective_model) in _gemini_model_exhausted_keys:
            return True
        return False

    # Verfügbare Keys suchen
    available_keys = [k for k in keys if not is_key_exhausted(k)]
    if not available_keys:
        # Alle Keys sind erschöpft - nimm den mit dem kürzesten Cooldown
        def key_cooldown(k: str) -> float:
            g_cd = _gemini_exhausted_keys.get(k, 0)
            m_cd = _gemini_model_exhausted_keys.get((k, effective_model), 0) if effective_model else 0
            return max(g_cd, m_cd)
        best_key = min(keys, key=key_cooldown)
        if best_key not in _gemini_clients_by_key:
            _gemini_clients_by_key[best_key] = genai.Client(api_key=best_key)
        return _gemini_clients_by_key[best_key], best_key

    # Aktuellen bevorzugten Key wählen
    _gemini_active_key_index = _gemini_active_key_index % len(available_keys)
    selected_key = available_keys[_gemini_active_key_index]

    if selected_key not in _gemini_clients_by_key:
        _gemini_clients_by_key[selected_key] = genai.Client(api_key=selected_key)

    return _gemini_clients_by_key[selected_key], selected_key


def _mark_gemini_key_exhausted(key: str, cooldown_seconds: float = 3600.0, *, model: str = "") -> bool:
    """Markiert einen Gemini-Key als erschöpft; True, wenn noch ein anderer Key verfügbar ist.

    Mit `model` gilt die Sperre nur für dieses Modell (modellspezifische Free-Tier-Quote).
    """
    global _gemini_active_key_index
    import os
    import time
    effective_model = model or _gemini_active_model
    if key:
        if effective_model:
            _gemini_model_exhausted_keys[(key, effective_model)] = time.time() + cooldown_seconds
        else:
            _gemini_exhausted_keys[key] = time.time() + cooldown_seconds
    from config import _collect_gemini_api_keys
    keys = GEMINI_API_KEYS or _collect_gemini_api_keys() or ([os.getenv("GEMINI_API_KEY")] if os.getenv("GEMINI_API_KEY") else [])

    def is_key_exhausted(k: str) -> bool:
        if k in _gemini_exhausted_keys:
            return True
        if effective_model and (k, effective_model) in _gemini_model_exhausted_keys:
            return True
        return False

    remaining = [k for k in keys if not is_key_exhausted(k)]
    if remaining:
        _gemini_active_key_index = 0
        return True
    return False


# Globaler Gemini-Client (Kompatibilität für bestehende Zugriffe)
class _DynamicGeminiClientProxy:
    """Proxy, der Aufrufe immer an den aktuellen, nicht-erschöpften Client aus dem Pool weiterleitet."""
    def __getattr__(self, name: str):
        client, _ = _get_gemini_client(model=_gemini_active_model)
        if client is None:
            raise RuntimeError("Gemini Client nicht initialisiert. Bitte GEMINI_API_KEY setzen.")
        return getattr(client, name)

    def __bool__(self) -> bool:
        import os

        from config import _collect_gemini_api_keys
        keys = _collect_gemini_api_keys() or GEMINI_API_KEYS or ([os.getenv("GEMINI_API_KEY")] if os.getenv("GEMINI_API_KEY") else [])
        return bool(keys)


_gemini_client = _DynamicGeminiClientProxy()

# Globaler Groq-Client
_groq_client = None
if GROQ_API_KEY:
    try:
        from groq import Groq
        _groq_client = Groq(api_key=GROQ_API_KEY)
    except ImportError:
        _groq_client = None

# Fallback-Ketten bei Ausfall/Quota-Erschöpfung. Wird NUR von GeminiClient gelesen (keyed auf
# dessen model_name); daher gehören hier nur Gemini-Modellnamen als Key hinein. Die anderen
# Clients haben einen fest verdrahteten Hop zu Gemini. Kein Endlosloop: Fallback-Hops laufen mit
# _allow_self_fallback=False.
MODEL_FALLBACKS = {
    # DeepSeek/OpenRouter/Groq haben eigene, von Gemini und Anthropic unabhängige Kontingente.
    # Claude steht bei den Flash-Stufen nur am Ende, weil sonst jede Gemini-Störung das
    # Anthropic-Monatslimit in einem Lauf aufbraucht. Für die seltene HEAVY-Stufe bleibt Claude
    # die erste Ausweichstufe.
    "gemini-pro-latest":    ["claude-opus-5", "claude-sonnet-5", "deepseek:deepseek-chat", "openrouter:openrouter/auto", "gemini-3.8-flash", "gemini-3.6-flash"],
    "gemini-3.8-flash":     ["deepseek:deepseek-chat", "openrouter:openrouter/auto", "groq:openai/gpt-oss-120b", "gemini-3.6-flash", "gemini-3.1-flash-lite", "claude-sonnet-5"],
    "gemini-3.6-flash":     ["deepseek:deepseek-chat", "openrouter:openrouter/auto", "groq:openai/gpt-oss-120b", "gemini-3.8-flash", "gemini-3.1-flash-lite", "claude-sonnet-5"],
    "gemini-3.1-flash-lite": ["deepseek:deepseek-chat", "openrouter:openrouter/auto", "groq:openai/gpt-oss-120b", "gemini-3.8-flash", "gemini-3.6-flash", "claude-haiku-4-5-20251001"],
    # Ältere/abweichende Konfigurationswerte (falls per .env manuell gesetzt) ebenfalls abdecken.
    "gemini-3.5-flash":     ["deepseek:deepseek-chat", "openrouter:openrouter/auto", "groq:openai/gpt-oss-120b", "gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.1-flash-lite", "claude-sonnet-5"],
}

# Prozessweiter Schalter statt token_guard-Eintrag (der gilt pro Modellname): ein erschöpftes
# Anthropic-Nutzungslimit betrifft alle Claude-Varianten, da sie dasselbe Konto teilen.
_claude_billing_exhausted_reason: str | None = None


def mark_claude_billing_exhausted(reason: str) -> None:
    """Markiert Claude (alle Modellvarianten) für den Rest dieses Prozesses als erschöpft."""
    global _claude_billing_exhausted_reason
    _claude_billing_exhausted_reason = reason


def _provider_available(model_name: str) -> bool:
    """
    True, wenn für den Provider des Modells ein API-Key konfiguriert ist (und Claude nicht
    billing-erschöpft ist). Filtert Fallback-Kandidaten vor dem Versuch, statt Latenz und
    irreführende Fehlerzeilen zu erzeugen. Gemini gilt hier immer als verfügbar.
    """
    name = model_name.lower()
    if "claude" in name:
        if _claude_billing_exhausted_reason is not None:
            return False
        return bool(ANTHROPIC_API_KEY)
    if name.startswith("groq:") or "gpt-oss" in name or "qwen" in name:
        return bool(GROQ_API_KEY)
    if name.startswith("deepseek:") or "deepseek" in name:
        return bool(DEEPSEEK_API_KEY)
    if name.startswith("openrouter:") or "openrouter" in name:
        return bool(OPENROUTER_API_KEY)
    if name.startswith("huggingface:") or "huggingface" in name:
        return bool(HUGGINGFACE_API_KEY)
    return True


MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 1.5

# Ist die gesamte Fallback-Kette erschöpft, wird auf den kürzesten Cooldown gewartet (Minutenlimits
# sind oft nur Sekunden entfernt), gedeckelt, damit ein Lauf nie unbegrenzt hängt.
MAX_EXHAUSTION_WAIT_SECONDS = 20.0

# Gemini-Tageskontingente ("...PerDay..." in quotaId) bekommen einen langen Cooldown statt 60 s.
# 12 h, weil der Cooldown persistiert wird (memory/provider_cooldowns.json) und
# core/capacity_gate.py ihn vor neuen Läufen prüft; das Limit setzt erst am Folgetag zurück.
_DAILY_QUOTA_MARKER = "PerDay"
DAILY_QUOTA_COOLDOWN_SECONDS = 12 * 3600.0


# Leeres Guthaben (alle Provider, inkl. Anthropics "API usage limits reached") erholt sich nie von
# selbst; ohne Marker fiele es auf den 60-s-Standard-Cooldown und würde jede Minute neu versucht.
_BILLING_EXHAUSTION_MARKERS = (
    "insufficient balance", "requires more credits", "insufficient credits", "insufficient_quota",
    "payment required",
    "api usage limits", "usage limit", "credit balance too low",
)
# 24 h, damit core/capacity_gate.py einen toten Key (persistierter Cooldown) nicht stündlich neu freigibt.
BILLING_EXHAUSTION_COOLDOWN_SECONDS = 24 * 3600.0

# Ein ungültiger/widerrufener Key repariert sich innerhalb eines Laufs nie - Cooldown daher
# bewusst so lang, dass er praktisch für den Rest des Prozesses nicht mehr versucht wird.
_AUTH_ERROR_MARKERS = (
    "401", "unauthorized", "authentication_error", "invalid_api_key", "invalid x-api-key",
    "incorrect api key", "invalid api key",
)
AUTH_FAILURE_COOLDOWN_SECONDS = 24 * 3600.0
_DAILY_TEXT_MARKERS = ("tokens per day", "requests per day")
_RETRY_AFTER_RE = re.compile(r"(?:try again|retry) in\s+(?P<spec>(?:\d+(?:\.\d+)?(?:ms|h|m|s))+)", re.IGNORECASE)
_DURATION_PART_RE = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
_DURATION_FACTORS = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}
# Gemini nennt auch bei TAGES-Kontingenten nur die Minuten-Wartezeit ("retry in 56s") - eine
# kürzere Angabe als diese Schwelle ist bei einem Tageskontingent kein verlässlicher Reset-Zeitpunkt.
_MIN_TRUSTED_DAILY_RETRY_SECONDS = 300.0


def _retry_after_seconds(err_str: str) -> float | None:
    """Vom Provider genannte Wartezeit ("try again in 2h42m9.5s", "retry in 56.8s", "in 850ms")."""
    match = _RETRY_AFTER_RE.search(err_str or "")
    if not match:
        return None
    return sum(float(value) * _DURATION_FACTORS[unit] for value, unit in _DURATION_PART_RE.findall(match.group("spec")))


def is_authentication_error(exc: Exception | str) -> bool:
    """True, wenn der Fehler nach ungültigem/abgelehntem API-Key aussieht (401 o.ä.).
    Öffentlich, weil core/model_preflight.py denselben Marker-Abgleich nutzt."""
    text = str(exc).lower()
    return any(marker in text for marker in _AUTH_ERROR_MARKERS)


def is_billing_exhaustion_error(exc: Exception | str) -> bool:
    """True bei erschöpftem Kontingent/Guthaben (siehe _BILLING_EXHAUSTION_MARKERS). Anders als
    ein Rate-Limit oder Auth-Fehler erholt sich das nie innerhalb desselben Laufs."""
    text = str(exc).lower()
    return any(marker in text for marker in _BILLING_EXHAUSTION_MARKERS)


def _exhaustion_cooldown_seconds(err_str: str) -> float | None:
    """Cooldown für einen Kontingent-/Guthaben-/Auth-Fehler - None = Standard-Cooldown des Aufrufers.

    Reihenfolge: ungültiger API-Key (AUTH_FAILURE_COOLDOWN_SECONDS, repariert sich nie von selbst)
    > fehlendes Guthaben (BILLING_EXHAUSTION_COOLDOWN_SECONDS) > Tageskontingent (exakte
    Provider-Angabe, sonst DAILY_QUOTA_COOLDOWN_SECONDS) > sonstige Provider-Wartezeit."""
    text = (err_str or "").lower()
    if any(marker in text for marker in _AUTH_ERROR_MARKERS):
        return AUTH_FAILURE_COOLDOWN_SECONDS
    if any(marker in text for marker in _BILLING_EXHAUSTION_MARKERS):
        return BILLING_EXHAUSTION_COOLDOWN_SECONDS
    retry_after = _retry_after_seconds(err_str)
    if _DAILY_QUOTA_MARKER in (err_str or "") or any(marker in text for marker in _DAILY_TEXT_MARKERS):
        if retry_after is not None and retry_after >= _MIN_TRUSTED_DAILY_RETRY_SECONDS:
            return retry_after
        return DAILY_QUOTA_COOLDOWN_SECONDS
    return retry_after if retry_after else None


def _short_error(exc: BaseException | None, limit: int = 160) -> str:
    return re.sub(r"\s+", " ", str(exc) if exc is not None else "unbekannter Fehler")[:limit]


def _describe_chain_failures(all_candidates: list[str], attempted: dict[str, str]) -> str:
    """Anhang für die finale Fehlermeldung einer Fallback-Kette: warum JEDER Kandidat ausfiel."""
    parts: list[str] = []
    for model in dict.fromkeys(all_candidates):
        if model in attempted:
            parts.append(f"{model}: {attempted[model]}")
        elif not _provider_available(model):
            parts.append(f"{model}: übersprungen (kein API-Key)")
        elif (reason := token_guard.get_exhausted_reason(model)) is not None:
            parts.append(f"{model}: übersprungen ({_short_error(reason, 120)})")
    return (" | Kette: " + "; ".join(parts)) if parts else ""

# Proaktive Rate-Begrenzung, da parallele Fachbereichs-Agenten sonst gleichzeitig denselben
# Provider anstürmen. Eine geteilte Instanz pro Prozess, weil alle dasselbe Kontingent teilen.
_gemini_rate_limiter = RateLimiter(
    max_calls=GEMINI_MAX_CALLS_PER_MINUTE * max(1, len(GEMINI_API_KEYS)),
    window_seconds=60.0,
)


# ── Sichtbare Modell-Abwertung ─────────────────────────────────────────────────────────────
# Fallbacks auf schwächere Modelle dürfen nicht lautlos geschehen. Ein einzelner optionaler
# Callback statt Logging-Framework, damit dieses Basismodul keine UI-Abhängigkeit bekommt.
_model_downgrade_listener: Callable[[str, str, str], None] | None = None


def set_model_downgrade_listener(listener) -> None:
    """Registriert einen Callback `(angefordert, tatsaechlich, grund)`, der bei jeder echten
    Modell-Abwertung aufgerufen wird. `None` schaltet die Benachrichtigung wieder ab."""
    global _model_downgrade_listener
    _model_downgrade_listener = listener


def _notify_model_downgrade(requested: str, actual: str, reason: str = "") -> None:
    """Meldet eine Abwertung - schluckt jeden Fehler des Listeners, damit eine reine
    Benachrichtigung nie einen laufenden LLM-Aufruf zum Scheitern bringt."""
    # Kanonischer Vergleich, da Clients das Provider-Präfix entfernen (sonst Schein-Abwertung).
    if is_same_model(requested, actual):
        return
    record_downgrade(requested, actual, reason)
    if _model_downgrade_listener is None:
        return
    try:
        _model_downgrade_listener(requested, actual, reason)
    except Exception:
        pass


# Provider-Präfixe, die die jeweiligen Client-Wrapper bei der Instanziierung ENTFERNEN
# (GroqClient/OpenRouterClient/DeepSeekClient setzen `self.model_name = name.replace("<p>:", "")`,
# weil die jeweilige API den reinen Modellnamen erwartet).
_PROVIDER_PREFIXES = ("groq:", "openrouter:", "deepseek:", "huggingface:")


def normalize_model_name(model_name: str) -> str:
    """
    Kanonische Form eines Modellnamens für VERGLEICHE (nie für API-Aufrufe).

    Nötig, weil Clients das Provider-Präfix entfernen ("groq:openai/gpt-oss-120b" ->
    "openai/gpt-oss-120b"); direkte Vergleiche mit Konfigwerten wären sonst falsch.
    """
    name = (model_name or "").strip()
    for prefix in _PROVIDER_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def is_same_model(a: str, b: str) -> bool:
    """True, wenn beide Namen dasselbe Modell bezeichnen - unabhängig vom Provider-Präfix."""
    return normalize_model_name(a) == normalize_model_name(b)


def _resolve_gemini_candidates(start_model: str, allow_fallback: bool) -> list[str]:
    """
    Ermittelt die tatsächlich zu versuchenden Modelle für einen Gemini-Aufruf.

    Ist `allow_fallback` False (Fallback-Hop oder gepinnter Provider), bleibt es bei GENAU
    diesem Modell - eine Ersatzkette würde das Pinning aushebeln.
    """
    if not allow_fallback:
        ordered = [start_model]
    else:
        candidates = [start_model] + MODEL_FALLBACKS.get(start_model, [])
        # Lite-Stufen nur als letzte Rettung, sonst landen HEAVY-Rollen lautlos auf flash-lite.
        ordered = candidates if _is_lite_model(start_model) else (
            [m for m in candidates if not _is_lite_model(m)] + [m for m in candidates if _is_lite_model(m)]
        )
    # Kritische Rollen setzen eine Mindeststufe (core/model_capability.py): Kandidaten darunter
    # entfallen ganz, statt als "letzte Rettung" Architektur-/Security-Aufgaben still zu übernehmen.
    floored = filter_by_floor(ordered)
    if not floored:
        raise CapabilityFloorError(start_model, ordered)
    return floored

# Erkennt Rate-Limits eines gepinnten Providers, um statt rohem Provider-JSON eine verständliche
# Meldung zu liefern. Ein Hop nach dem Pinning bleibt bewusst aus (Provider-Historie-Korruption).
_RATE_LIMIT_ERROR_MARKERS = ("429", "rate_limit", "resource_exhausted", "quota")


def _is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _RATE_LIMIT_ERROR_MARKERS)


# Groqs Free-Tier-TPM-Limit (z.B. 8.000 bei gpt-oss-120b) sprengt schon ein einzelner großer
# Prompt (HTTP 413). Andere Groq-Modelle (config.GROQ_FALLBACK_MODELS) haben höhere TPM-Limits.
_REQUEST_TOO_LARGE_MARKERS = ("413", "request too large", "tokens per minute", "reduce your message size")


def _is_request_too_large_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _REQUEST_TOO_LARGE_MARKERS)


# Vom Provider entfernte Modelle (HTTP 404) sind dauerhaft ungültig: nächstes Modell probieren
# und langer Cooldown, damit kein Agent den toten Namen erneut anfragt.
_MODEL_NOT_FOUND_MARKERS = ("404", "does not exist", "model_not_found", "model_decommissioned")
_MODEL_NOT_FOUND_COOLDOWN_SECONDS = 86400.0


def _is_model_not_found_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _MODEL_NOT_FOUND_MARKERS)


# Ungültiges Tool-Call-JSON (Groq 400) ist ein Generierungsfehler, keine Quota-Erschöpfung: Failover
# ist auch bei gepinntem Provider erlaubt, da keine gültige Antwort in die Historie gelangte.
_TOOL_CALL_JSON_ERROR_MARKERS = ("failed to parse tool call arguments", "tool_use_failed")


def _is_tool_call_json_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _TOOL_CALL_JSON_ERROR_MARKERS)


def _next_groq_fallback_model(current_model: str, already_tried: frozenset[str]) -> str | None:
    """
    Nächstes weder versuchte noch erschöpfte Modell aus config.GROQ_FALLBACK_MODELS, sonst None.
    """
    exhausted = already_tried | {current_model}
    for candidate in GROQ_FALLBACK_MODELS:
        if candidate in exhausted:
            continue
        if not token_guard.is_model_exhausted(f"groq:{candidate}"):
            return candidate
    return None


def _pinned_provider_failure(provider_label: str, model_name: str, exc: Exception) -> Exception:
    """
    Verständliche Fehlermeldung, wenn ein GEPINNTER Provider (_allow_self_fallback=False) an
    Kontingent/Rate-Limit scheitert. Aufrufer verketten die Original-Exception per `from exc`.
    """
    return RuntimeError(
        f"{provider_label} ({model_name}) ist für diese Aufgabe bereits fest eingeplant "
        f"und gerade nicht verfügbar (Kontingent erschöpft oder Rate-Limit erreicht) – kein "
        f"weiterer automatischer Wechsel innerhalb dieser Aufgabe, um die Konversation nicht "
        f"zu beschädigen. Kurz warten oder einen zusätzlichen API-Key ergänzen. "
        f"Rohe Provider-Meldung: {exc}"
    )


# ── Provider-unabhängiges Failover bei Quota-Erschöpfung ───────────────────────────────────
# Bei Quota-Erschöpfung zuerst auf einen anderen, unabhängigen Provider wechseln, statt kurz zu
# retryen (hilft bei Quota nie) oder auf schwächere Stufen desselben Providers auszuweichen.
_INDEPENDENT_FAILOVER_MODELS: tuple[str, ...] = (
    GROQ_HEAVY_MODEL, "deepseek:deepseek-chat", "openrouter:openrouter/auto",
)
_QUOTA_EXHAUSTION_MARKERS = (
    "resource_exhausted", "exceeded your current quota", "quotafailure", "insufficient_quota",
    "tokens per day", "perday",
)


def _is_quota_exhaustion(err_str: str) -> bool:
    """True für eine echte Kontingent-Erschöpfung - im Gegensatz zu einem kurzen, per Retry
    überbrückbaren Rate-Limit-Spike oder einer 503-Überlastung."""
    text = err_str.lower()
    return any(marker in text for marker in _QUOTA_EXHAUSTION_MARKERS)


def _provider_of(model_name: str) -> str:
    """Provider-Kennung eines Modellnamens - dieselbe Erkennung wie LLMFactory.create_for_model()."""
    name = model_name.lower()
    if "huggingface" in name:
        return "huggingface"
    if "openrouter" in name:
        return "openrouter"
    if "deepseek" in name:
        return "deepseek"
    if name.startswith("groq:") or "gpt-oss" in name or "qwen" in name:
        return "groq"
    if "claude" in name:
        return "anthropic"
    return "gemini"


def _is_lite_model(model_name: str) -> bool:
    return "lite" in model_name.lower()


def _prefer_independent_providers(pending: list[str], failed_provider: str) -> list[str]:
    """Stabile Umsortierung: Kandidaten ANDERER Provider zuerst, Stufen des gerade
    quota-erschöpften Providers erst danach (Gemini-Kontingente sind pro Modell, deshalb
    nicht verworfen, nur nachrangig)."""
    return (
        [m for m in pending if _provider_of(m) != failed_provider]
        + [m for m in pending if _provider_of(m) == failed_provider]
    )


def _independent_failover_candidates(failed_provider: str) -> list[str]:
    return filter_by_floor(
        m for m in _INDEPENDENT_FAILOVER_MODELS
        if _provider_of(m) != failed_provider and _provider_available(m) and not token_guard.is_model_exhausted(m)
    )


async def _cross_provider_failover_with_usage(
    failed_provider: str, prompt: str, system_prompt: str | None,
) -> "LLMResponse":
    """Selbst-Fallback eines Nicht-Gemini-Providers: erst unabhängige Provider (je genau ein
    Versuch, _allow_self_fallback=False verhindert Ping-Pong), zuletzt die Gemini-Kette."""
    for model in _independent_failover_candidates(failed_provider):
        try:
            return await LLMFactory.create_for_model(model).generate_with_usage(
                prompt, system_prompt, _allow_self_fallback=False,
            )
        except Exception:
            continue
    return await GeminiClient(model_name=GEMINI_STANDARD_MODEL).generate_with_usage(prompt, system_prompt)


async def _cross_provider_failover_with_tools(
    failed_provider: str, messages: list["AgentMessage"], system_prompt: str | None, tools: list[dict],
) -> "LLMResponse":
    """Wie _cross_provider_failover_with_usage(), für Function-Calling-Aufrufe."""
    for model in _independent_failover_candidates(failed_provider):
        try:
            return await LLMFactory.create_for_model(model).generate_with_tools(
                messages, system_prompt, tools, _allow_self_fallback=False,
            )
        except Exception:
            continue
    return await GeminiClient(model_name=GEMINI_STANDARD_MODEL).generate_with_tools(messages, system_prompt, tools)


# Erzwungener Werkzeug-Aufruf, damit Code-Rollen Code nicht als Chat-Text liefern. Gesetzt von
# agents/base_agent.py; Provider übersetzen ihn nativ (Gemini mode=ANY, OpenAI tool_choice="required",
# Anthropic tool_choice={"type": "any"}).
_TOOL_CALL_REQUIRED: contextvars.ContextVar[bool] = contextvars.ContextVar("tool_call_required", default=False)


def tool_call_required() -> bool:
    return _TOOL_CALL_REQUIRED.get()


def openai_tool_choice() -> str:
    return "required" if tool_call_required() else "auto"


@contextlib.contextmanager
def require_tool_call(active: bool = True):
    """Erzwingt für Aufrufe innerhalb des Blocks einen Werkzeug-Aufruf (sofern `active`)."""
    token = _TOOL_CALL_REQUIRED.set(bool(active))
    try:
        yield
    finally:
        _TOOL_CALL_REQUIRED.reset(token)


@dataclass
class ToolCall:
    """Ein vom Modell angeforderter Werkzeug-Aufruf innerhalb des agentischen Loops."""
    id: str
    name: str
    arguments: dict[str, Any]
    # Gemini verlangt die thought_signature des ORIGINALEN function_call-Parts unverändert im
    # Verlauf, sonst 400 "Function call is missing a thought_signature". Nur Gemini setzt sie.
    thought_signature: bytes | None = None


@dataclass
class AgentMessage:
    """
    Provider-neutraler Konversations-Turn des Werkzeug-Loops; jeder Client übersetzt ihn nativ.

    role: "user" (Eingabe), "assistant" (Text/tool_calls), "tool" (Ergebnis, via tool_call_id).
    """
    role: str
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str = ""
    tool_name: str = ""


@dataclass
class LLMResponse:
    """Antwort eines LLM-Aufrufs mit Metriken."""
    text: str
    model_name: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    tool_calls: list[ToolCall] = field(default_factory=list)


# ── Gemeinsame Helfer für OpenAI-kompatible Clients (Groq, DeepSeek, OpenRouter) ──

def _openai_build_messages(messages: list["AgentMessage"], system_prompt: str | None) -> list[dict]:
    payload_messages: list[dict] = []
    if system_prompt:
        payload_messages.append({"role": "system", "content": system_prompt})

    for msg in messages:
        if msg.role == "user":
            payload_messages.append({"role": "user", "content": msg.text})
        elif msg.role == "assistant":
            entry: dict = {"role": "assistant", "content": msg.text or None}
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)},
                    }
                    for tc in msg.tool_calls
                ]
            payload_messages.append(entry)
        elif msg.role == "tool":
            payload_messages.append({"role": "tool", "tool_call_id": msg.tool_call_id, "content": msg.text})

    return payload_messages


def _openai_build_tools(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


def _openai_parse_tool_calls(message: dict) -> list[ToolCall]:
    raw_calls = message.get("tool_calls") or []
    parsed: list[ToolCall] = []
    for call in raw_calls:
        fn = call.get("function", {})
        raw_args = fn.get("arguments", "{}")
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        except json.JSONDecodeError:
            args = {}
        parsed.append(ToolCall(id=call.get("id") or str(uuid.uuid4())[:8], name=fn.get("name", ""), arguments=args))
    return parsed


class HuggingFaceClient:
    """Wrapper für Hugging Face Models & Inference mit Fallback."""

    def __init__(self, model_name: str = "huggingface:auto"):
        self.model_name = model_name

    async def generate_with_usage(
        self, prompt: str, system_prompt: str | None = None, _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        # Fallback auf Gemini; _allow_self_fallback=False verhindert Gemini<->HF-Endlosschleifen.
        if not _allow_self_fallback:
            raise RuntimeError("HuggingFace-Provider innerhalb einer Fallback-Kette nicht verfügbar.")
        fallback = GeminiClient(model_name=GEMINI_STANDARD_MODEL)
        return await fallback.generate_with_usage(prompt, system_prompt)

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        res = await self.generate_with_usage(prompt, system_prompt)
        return res.text

    async def generate_with_tools(
        self, messages: list["AgentMessage"], system_prompt: str | None, tools: list[dict],
        _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        # Kein natives Function-Calling für HuggingFace - Gemini übernimmt.
        if not _allow_self_fallback:
            raise RuntimeError("HuggingFace-Provider innerhalb einer Fallback-Kette nicht verfügbar.")
        fallback = GeminiClient(model_name=GEMINI_STANDARD_MODEL)
        return await fallback.generate_with_tools(messages, system_prompt, tools)

    async def generate_json(self, prompt: str, system_prompt: str | None = None) -> str:
        fallback = GeminiClient(model_name=GEMINI_STANDARD_MODEL)
        return await fallback.generate_json(prompt, system_prompt)


class OpenRouterClient:
    """Wrapper für OpenRouter API (Universal Multi-Model Gateway)."""

    def __init__(self, model_name: str = "openrouter/auto"):
        self.model_name = model_name.replace("openrouter:", "")
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"

    async def generate_with_usage(
        self, prompt: str, system_prompt: str | None = None, _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        if not OPENROUTER_API_KEY or token_guard.is_model_exhausted(f"openrouter:{self.model_name}"):
            if not _allow_self_fallback:
                raise RuntimeError("OpenRouter innerhalb einer Fallback-Kette nicht verfügbar (kein Key/erschöpft).")
            return await _cross_provider_failover_with_usage("openrouter", prompt, system_prompt)

        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": "https://github.com/Schengii/AI-Softwareentwickler-Team",
            "X-Title": "AI Developer Team",
            "Content-Type": "application/json",
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model_name if self.model_name != "auto" else "google/gemini-2.5-flash",
            "messages": messages,
            "temperature": TEMPERATURE,
            "max_tokens": MAX_OUTPUT_TOKENS,
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(self.api_url, headers=headers, json=payload)
                data = response.json()

                if response.status_code == 200 and "choices" in data:
                    text = data["choices"][0]["message"]["content"]
                    usage = data.get("usage", {})
                    p_tok = usage.get("prompt_tokens", len(prompt) // 4)
                    c_tok = usage.get("completion_tokens", len(text) // 4)
                    tot = usage.get("total_tokens", p_tok + c_tok)

                    token_guard.record_usage(f"openrouter:{self.model_name}", p_tok, c_tok)

                    return LLMResponse(
                        text=text,
                        model_name=f"openrouter:{self.model_name}",
                        prompt_tokens=p_tok,
                        completion_tokens=c_tok,
                        total_tokens=tot,
                    )
                else:
                    err_msg = data.get("error", {}).get("message", "OpenRouter API Error")
                    if response.status_code in (401, 402, 429) or "balance" in err_msg.lower() or "limit" in err_msg.lower():
                        token_guard.mark_model_exhausted(f"openrouter:{self.model_name}", f"OpenRouter: {err_msg}", cooldown_seconds=_exhaustion_cooldown_seconds(err_msg))
                    if not _allow_self_fallback:
                        raise RuntimeError(f"OpenRouter-Fehler innerhalb einer Fallback-Kette: {err_msg}")
                    return await _cross_provider_failover_with_usage("openrouter", prompt, system_prompt)

        except Exception as e:
            token_guard.mark_model_exhausted(f"openrouter:{self.model_name}", str(e), cooldown_seconds=_exhaustion_cooldown_seconds(str(e)))
            if not _allow_self_fallback:
                raise
            return await _cross_provider_failover_with_usage("openrouter", prompt, system_prompt)

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        res = await self.generate_with_usage(prompt, system_prompt)
        return res.text

    async def generate_with_tools(
        self, messages: list["AgentMessage"], system_prompt: str | None, tools: list[dict],
        _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        if not OPENROUTER_API_KEY or token_guard.is_model_exhausted(f"openrouter:{self.model_name}"):
            if not _allow_self_fallback:
                raise RuntimeError("OpenRouter innerhalb einer Fallback-Kette nicht verfügbar (kein Key/erschöpft).")
            return await _cross_provider_failover_with_tools("openrouter", messages, system_prompt, tools)

        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": "https://github.com/Schengii/AI-Softwareentwickler-Team",
            "X-Title": "AI Developer Team",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model_name if self.model_name != "auto" else "google/gemini-2.5-flash",
            "messages": _openai_build_messages(messages, system_prompt),
            "tools": _openai_build_tools(tools),
            "tool_choice": openai_tool_choice(),
            "temperature": TEMPERATURE,
            "max_tokens": MAX_OUTPUT_TOKENS,
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(self.api_url, headers=headers, json=payload)
                data = response.json()

                if response.status_code == 200 and "choices" in data:
                    message = data["choices"][0]["message"]
                    usage = data.get("usage", {})
                    p_tok = usage.get("prompt_tokens", 0)
                    c_tok = usage.get("completion_tokens", 0)
                    token_guard.record_usage(f"openrouter:{self.model_name}", p_tok, c_tok)

                    return LLMResponse(
                        text=message.get("content") or "",
                        model_name=f"openrouter:{self.model_name}",
                        prompt_tokens=p_tok,
                        completion_tokens=c_tok,
                        total_tokens=usage.get("total_tokens", p_tok + c_tok),
                        tool_calls=_openai_parse_tool_calls(message),
                    )

                err_msg = data.get("error", {}).get("message", "OpenRouter API Error")
                if response.status_code in (401, 402, 429) or "balance" in err_msg.lower() or "limit" in err_msg.lower():
                    token_guard.mark_model_exhausted(f"openrouter:{self.model_name}", f"OpenRouter: {err_msg}", cooldown_seconds=_exhaustion_cooldown_seconds(err_msg))
                if not _allow_self_fallback:
                    raise RuntimeError(f"OpenRouter-Fehler innerhalb einer Fallback-Kette: {err_msg}")
                return await _cross_provider_failover_with_tools("openrouter", messages, system_prompt, tools)

        except Exception as e:
            token_guard.mark_model_exhausted(f"openrouter:{self.model_name}", str(e), cooldown_seconds=_exhaustion_cooldown_seconds(str(e)))
            if not _allow_self_fallback:
                raise
            return await _cross_provider_failover_with_tools("openrouter", messages, system_prompt, tools)

    async def generate_json(self, prompt: str, system_prompt: str | None = None) -> str:
        json_instruction = "\n\nAntworte AUSSCHLIESSLICH mit einem gültigen JSON-Objekt, ohne Markdown-Codeblock, ohne Erklärungen davor oder danach."
        res = await self.generate_with_usage(prompt, (system_prompt or "") + json_instruction)
        return res.text


class DeepSeekClient:
    """Wrapper für die DeepSeek API (OpenAI-kompatibel via REST)."""

    def __init__(self, model_name: str = "deepseek-chat"):
        self.model_name = model_name.replace("deepseek:", "")
        self.api_url = "https://api.deepseek.com/chat/completions"

    async def generate_with_usage(
        self, prompt: str, system_prompt: str | None = None, _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        if not DEEPSEEK_API_KEY or token_guard.is_model_exhausted(f"deepseek:{self.model_name}"):
            if not _allow_self_fallback:
                raise RuntimeError("DeepSeek innerhalb einer Fallback-Kette nicht verfügbar (kein Key/erschöpft).")
            return await _cross_provider_failover_with_usage("deepseek", prompt, system_prompt)

        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": TEMPERATURE,
            "max_tokens": MAX_OUTPUT_TOKENS,
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(self.api_url, headers=headers, json=payload)
                data = response.json()

                if response.status_code == 200 and "choices" in data:
                    text = data["choices"][0]["message"]["content"]
                    usage = data.get("usage", {})
                    p_tok = usage.get("prompt_tokens", len(prompt) // 4)
                    c_tok = usage.get("completion_tokens", len(text) // 4)
                    tot = usage.get("total_tokens", p_tok + c_tok)

                    token_guard.record_usage(f"deepseek:{self.model_name}", p_tok, c_tok)

                    return LLMResponse(
                        text=text,
                        model_name=f"deepseek:{self.model_name}",
                        prompt_tokens=p_tok,
                        completion_tokens=c_tok,
                        total_tokens=tot,
                    )
                else:
                    err_msg = data.get("error", {}).get("message", "DeepSeek API Error")
                    if response.status_code in (402, 429) or "balance" in err_msg.lower() or "quota" in err_msg.lower():
                        token_guard.mark_model_exhausted(f"deepseek:{self.model_name}", f"DeepSeek: {err_msg}", cooldown_seconds=_exhaustion_cooldown_seconds(err_msg))
                    if not _allow_self_fallback:
                        raise RuntimeError(f"DeepSeek-Fehler innerhalb einer Fallback-Kette: {err_msg}")
                    return await _cross_provider_failover_with_usage("deepseek", prompt, system_prompt)

        except Exception as e:
            token_guard.mark_model_exhausted(f"deepseek:{self.model_name}", str(e), cooldown_seconds=_exhaustion_cooldown_seconds(str(e)))
            if not _allow_self_fallback:
                raise
            return await _cross_provider_failover_with_usage("deepseek", prompt, system_prompt)

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        res = await self.generate_with_usage(prompt, system_prompt)
        return res.text

    async def generate_with_tools(
        self, messages: list["AgentMessage"], system_prompt: str | None, tools: list[dict],
        _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        if not DEEPSEEK_API_KEY or token_guard.is_model_exhausted(f"deepseek:{self.model_name}"):
            if not _allow_self_fallback:
                raise RuntimeError("DeepSeek innerhalb einer Fallback-Kette nicht verfügbar (kein Key/erschöpft).")
            return await _cross_provider_failover_with_tools("deepseek", messages, system_prompt, tools)

        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": self.model_name,
            "messages": _openai_build_messages(messages, system_prompt),
            "tools": _openai_build_tools(tools),
            "tool_choice": openai_tool_choice(),
            "temperature": TEMPERATURE,
            "max_tokens": MAX_OUTPUT_TOKENS,
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(self.api_url, headers=headers, json=payload)
                data = response.json()

                if response.status_code == 200 and "choices" in data:
                    message = data["choices"][0]["message"]
                    usage = data.get("usage", {})
                    p_tok = usage.get("prompt_tokens", 0)
                    c_tok = usage.get("completion_tokens", 0)
                    token_guard.record_usage(f"deepseek:{self.model_name}", p_tok, c_tok)

                    return LLMResponse(
                        text=message.get("content") or "",
                        model_name=f"deepseek:{self.model_name}",
                        prompt_tokens=p_tok,
                        completion_tokens=c_tok,
                        total_tokens=usage.get("total_tokens", p_tok + c_tok),
                        tool_calls=_openai_parse_tool_calls(message),
                    )

                err_msg = data.get("error", {}).get("message", "DeepSeek API Error")
                if response.status_code in (402, 429) or "balance" in err_msg.lower() or "quota" in err_msg.lower():
                    token_guard.mark_model_exhausted(f"deepseek:{self.model_name}", f"DeepSeek: {err_msg}", cooldown_seconds=_exhaustion_cooldown_seconds(err_msg))
                if not _allow_self_fallback:
                    raise RuntimeError(f"DeepSeek-Fehler innerhalb einer Fallback-Kette: {err_msg}")
                return await _cross_provider_failover_with_tools("deepseek", messages, system_prompt, tools)

        except Exception as e:
            token_guard.mark_model_exhausted(f"deepseek:{self.model_name}", str(e), cooldown_seconds=_exhaustion_cooldown_seconds(str(e)))
            if not _allow_self_fallback:
                raise
            return await _cross_provider_failover_with_tools("deepseek", messages, system_prompt, tools)

    async def generate_json(self, prompt: str, system_prompt: str | None = None) -> str:
        json_instruction = "\n\nAntworte AUSSCHLIESSLICH mit einem gültigen JSON-Objekt, ohne Markdown-Codeblock, ohne Erklärungen davor oder danach."
        res = await self.generate_with_usage(prompt, (system_prompt or "") + json_instruction)
        return res.text


class GeminiClient:
    """Wrapper für die Google Gemini API."""

    def __init__(self, model_name: str = GEMINI_STANDARD_MODEL):
        self.model_name = model_name

    async def generate_with_usage(
        self, prompt: str, system_prompt: str | None = None, _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        config = genai_types.GenerateContentConfig(
            temperature=TEMPERATURE,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            system_instruction=system_prompt if system_prompt else None,
        )
        return await self._call_with_retry_and_usage(prompt, config, _allow_self_fallback=_allow_self_fallback)

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        res = await self.generate_with_usage(prompt, system_prompt)
        return res.text

    async def generate_with_tools(
        self, messages: list["AgentMessage"], system_prompt: str | None, tools: list[dict],
        _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        """
        Function-Calling-fähiger Gemini-Aufruf: liefert finalen Text oder tool_calls.

        _allow_self_fallback=False (Aufruf ist selbst ein Fallback-Hop) wirft sofort, statt
        weiterzureichen - verhindert Endlosschleifen; der Aufrufer nimmt den nächsten Kandidaten.
        """
        if not _gemini_client:
            if _groq_client and _allow_self_fallback:
                groq_fallback = GroqClient(model_name="openai/gpt-oss-120b")
                return await groq_fallback.generate_with_tools(messages, system_prompt, tools, _allow_self_fallback=False)
            raise RuntimeError("Gemini Client nicht initialisiert. Bitte GEMINI_API_KEY setzen.")

        genai_tool = genai_types.Tool(function_declarations=[
            genai_types.FunctionDeclaration(
                name=t["name"],
                description=t.get("description", ""),
                parameters_json_schema=t.get("parameters", {"type": "object", "properties": {}}),
            )
            for t in tools
        ]) if tools else None

        contents = self._build_gemini_contents(messages)
        config = genai_types.GenerateContentConfig(
            temperature=TEMPERATURE,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            system_instruction=system_prompt if system_prompt else None,
            tools=[genai_tool] if genai_tool else None,
            tool_config=(
                genai_types.ToolConfig(function_calling_config=genai_types.FunctionCallingConfig(mode="ANY"))
                if genai_tool and tool_call_required() else None
            ),
        )

        all_candidates = _resolve_gemini_candidates(self.model_name, _allow_self_fallback)
        models_to_try = [m for m in all_candidates if _provider_available(m) and not token_guard.is_model_exhausted(m)]
        if not models_to_try:
            # Ganze Kette erschöpft: kurz auf den kürzesten Cooldown warten. Kandidaten ohne Key
            # bleiben aussortiert - ein Cooldown behebt keinen fehlenden API-Key.
            wait_s = min(token_guard.seconds_until_available(all_candidates), MAX_EXHAUSTION_WAIT_SECONDS)
            if wait_s > 0:
                await asyncio.sleep(wait_s)
            # all_candidates[:1] statt self.model_name: das angeforderte Modell kann unter der
            # Mindeststufe liegen (core/model_capability.py) und wurde dann bereits aussortiert.
            models_to_try = [m for m in all_candidates if _provider_available(m) and not token_guard.is_model_exhausted(m)] or all_candidates[:1]

        last_error: Exception | None = None
        chain_errors: dict[str, str] = {}
        pending = list(models_to_try)
        while pending:
            model = pending.pop(0)
            if not model.startswith("gemini"):
                # Fremd-Provider über LLMFactory delegieren, nie an die Gemini-API. Mit
                # _allow_self_fallback=False wirft er bei Scheitern -> nächster Kandidat.
                try:
                    return await LLMFactory.create_for_model(model).generate_with_tools(
                        messages, system_prompt, tools, _allow_self_fallback=False
                    )
                except Exception as e:
                    last_error = e
                    chain_errors[model] = _short_error(e)
                    continue

            global _gemini_active_model
            _gemini_active_model = model
            for attempt in range(MAX_RETRIES):
                try:
                    await _gemini_rate_limiter.acquire()
                    response = await asyncio.to_thread(
                        _gemini_client.models.generate_content, model=model, contents=contents, config=config,
                    )
                    _notify_model_downgrade(self.model_name, model, "Fallback-Kette (generate_with_tools)")
                    return self._parse_gemini_tool_response(response, model)
                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower()
                    is_unavailable = "503" in err_str or "UNAVAILABLE" in err_str or "high demand" in err_str.lower()
                    # Echte Quota-Erschöpfung: kein Retry, sofort unabhängiger Provider.
                    is_quota_exhausted = is_rate_limit and _is_quota_exhaustion(err_str)

                    if (is_rate_limit or is_unavailable) and not is_quota_exhausted and attempt < MAX_RETRIES - 1:
                        wait = RETRY_DELAY_SECONDS * (attempt + 1) * 1.5
                        await asyncio.sleep(wait)
                        continue

                    if is_rate_limit:
                        if is_quota_exhausted:
                            _, active_key = _get_gemini_client(model=model)
                            has_next_gemini_key = _mark_gemini_key_exhausted(
                                active_key, cooldown_seconds=_exhaustion_cooldown_seconds(err_str) or 86400.0,
                                model=model,
                            )
                            if has_next_gemini_key:
                                # Weiterer Key im Pool: dasselbe Modell sofort erneut versuchen
                                continue
                            # Alle Keys erschöpft -> Modell sperren, andere Provider vorziehen
                            token_guard.mark_model_exhausted(
                                model, "429 Quota Exceeded (alle Gemini-Keys erschöpft)", cooldown_seconds=_exhaustion_cooldown_seconds(err_str),
                            )
                            pending = _prefer_independent_providers(pending, failed_provider="gemini")
                        else:
                            token_guard.mark_model_exhausted(
                                model, "429 Quota Exceeded", cooldown_seconds=_exhaustion_cooldown_seconds(err_str),
                            )
                    elif is_unavailable:
                        token_guard.mark_model_exhausted(model, "503 High Demand", cooldown_seconds=20.0)
                    break
            chain_errors[model] = _short_error(last_error)

        raise RuntimeError(
            f"Gemini Function-Calling Fehler nach allen Fallback-Modellen ({self.model_name}): {last_error}"
            + _describe_chain_failures(all_candidates, chain_errors)
        ) from last_error

    @staticmethod
    def _build_gemini_contents(messages: list["AgentMessage"]) -> list:
        """Übersetzt neutrale AgentMessage-Turns in Gemini Content-Objekte."""
        contents = []
        for msg in messages:
            if msg.role == "user":
                contents.append(genai_types.Content(role="user", parts=[genai_types.Part(text=msg.text)]))
            elif msg.role == "assistant":
                parts = []
                if msg.text:
                    parts.append(genai_types.Part(text=msg.text))
                for tc in msg.tool_calls:
                    fc_part = genai_types.Part.from_function_call(name=tc.name, args=tc.arguments)
                    # thought_signature MUSS erhalten bleiben, sonst 400 INVALID_ARGUMENT (siehe ToolCall).
                    if tc.thought_signature:
                        fc_part.thought_signature = tc.thought_signature
                    parts.append(fc_part)
                contents.append(genai_types.Content(role="model", parts=parts))
            elif msg.role == "tool":
                # Gemini hat keine "tool"-Rolle: function_response geht als "user"-Content.
                contents.append(genai_types.Content(
                    role="user",
                    parts=[genai_types.Part.from_function_response(name=msg.tool_name, response={"result": msg.text})],
                ))
        return contents

    @staticmethod
    def _parse_gemini_tool_response(response, model: str) -> LLMResponse:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        candidate = response.candidates[0] if getattr(response, "candidates", None) else None
        parts = candidate.content.parts if candidate and candidate.content else []
        for part in parts or []:
            if getattr(part, "function_call", None):
                fc = part.function_call
                call_id = getattr(fc, "id", None) or str(uuid.uuid4())[:8]
                tool_calls.append(ToolCall(
                    id=call_id, name=fc.name, arguments=dict(fc.args) if fc.args else {},
                    thought_signature=getattr(part, "thought_signature", None),
                ))
            elif getattr(part, "text", None):
                text_parts.append(part.text)

        prompt_tokens = completion_tokens = total_tokens = cache_read_tokens = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            meta = response.usage_metadata
            prompt_tokens = getattr(meta, "prompt_token_count", 0) or 0
            completion_tokens = getattr(meta, "candidates_token_count", 0) or 0
            total_tokens = getattr(meta, "total_token_count", 0) or (prompt_tokens + completion_tokens)
            cache_read_tokens = getattr(meta, "cached_content_token_count", 0) or 0

        token_guard.record_usage(model, prompt_tokens, completion_tokens, cache_read_tokens=cache_read_tokens)

        return LLMResponse(
            text="\n".join(text_parts),
            model_name=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cache_read_tokens=cache_read_tokens,
            tool_calls=tool_calls,
        )

    async def _call_with_retry_and_usage(
        self,
        contents: str,
        config: genai_types.GenerateContentConfig,
        _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        if not _gemini_client:
            if _groq_client and _allow_self_fallback:
                groq_fallback = GroqClient(model_name="openai/gpt-oss-120b")
                return await groq_fallback.generate_with_usage(contents, config.system_instruction, _allow_self_fallback=False)
            raise RuntimeError("Gemini Client nicht initialisiert. Bitte GEMINI_API_KEY setzen.")

        start_model = self.model_name
        all_candidates = _resolve_gemini_candidates(start_model, _allow_self_fallback)
        models_to_try = [m for m in all_candidates if _provider_available(m) and not token_guard.is_model_exhausted(m)]
        if not models_to_try:
            # Wie in generate_with_tools(): kurz auf den kürzesten Cooldown warten.
            wait_s = min(token_guard.seconds_until_available(all_candidates), MAX_EXHAUSTION_WAIT_SECONDS)
            if wait_s > 0:
                await asyncio.sleep(wait_s)
            models_to_try = [m for m in all_candidates if _provider_available(m) and not token_guard.is_model_exhausted(m)] or all_candidates[:1]

        last_error: Exception | None = None
        chain_errors: dict[str, str] = {}
        pending = list(models_to_try)
        while pending:
            model = pending.pop(0)
            if not model.startswith("gemini"):
                # Wie in generate_with_tools(): Delegation an den Fremd-Provider ohne Self-Fallback.
                try:
                    return await LLMFactory.create_for_model(model).generate_with_usage(
                        contents, config.system_instruction, _allow_self_fallback=False
                    )
                except Exception as e:
                    last_error = e
                    chain_errors[model] = _short_error(e)
                    continue

            global _gemini_active_model
            _gemini_active_model = model
            for attempt in range(MAX_RETRIES):
                try:
                    await _gemini_rate_limiter.acquire()
                    response = await asyncio.to_thread(
                        _gemini_client.models.generate_content,
                        model=model,
                        contents=contents,
                        config=config,
                    )
                    text = response.text or ""

                    prompt_tokens = 0
                    completion_tokens = 0
                    total_tokens = 0
                    cache_read_tokens = 0

                    if hasattr(response, "usage_metadata") and response.usage_metadata:
                        meta = response.usage_metadata
                        prompt_tokens = getattr(meta, "prompt_token_count", 0) or 0
                        completion_tokens = getattr(meta, "candidates_token_count", 0) or 0
                        total_tokens = getattr(meta, "total_token_count", 0) or (prompt_tokens + completion_tokens)
                        cache_read_tokens = getattr(meta, "cached_content_token_count", 0) or 0
                    else:
                        prompt_tokens = len(contents) // 4
                        completion_tokens = len(text) // 4
                        total_tokens = prompt_tokens + completion_tokens

                    token_guard.record_usage(model, prompt_tokens, completion_tokens, cache_read_tokens=cache_read_tokens)
                    _notify_model_downgrade(start_model, model, "Fallback-Kette (generate_with_usage)")

                    return LLMResponse(
                        text=text,
                        model_name=model,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        cache_read_tokens=cache_read_tokens,
                    )

                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower()
                    is_unavailable = "503" in err_str or "UNAVAILABLE" in err_str or "high demand" in err_str.lower()
                    # Echte Quota-Erschöpfung: kein Retry, sofort unabhängiger Provider.
                    is_quota_exhausted = is_rate_limit and _is_quota_exhaustion(err_str)

                    if (is_rate_limit or is_unavailable) and not is_quota_exhausted and attempt < MAX_RETRIES - 1:
                        wait = RETRY_DELAY_SECONDS * (attempt + 1) * 1.5
                        await asyncio.sleep(wait)
                        continue

                    if is_rate_limit:
                        if is_quota_exhausted:
                            _, active_key = _get_gemini_client(model=model)
                            has_next_gemini_key = _mark_gemini_key_exhausted(
                                active_key, cooldown_seconds=_exhaustion_cooldown_seconds(err_str) or 86400.0,
                                model=model,
                            )
                            if has_next_gemini_key:
                                # Weiterer Key im Pool: dasselbe Modell sofort erneut versuchen
                                continue
                            # Alle Keys erschöpft -> Modell sperren, andere Provider vorziehen
                            token_guard.mark_model_exhausted(
                                model, "429 Quota Exceeded (alle Gemini-Keys erschöpft)", cooldown_seconds=_exhaustion_cooldown_seconds(err_str),
                            )
                            pending = _prefer_independent_providers(pending, failed_provider="gemini")
                        else:
                            token_guard.mark_model_exhausted(
                                model, "429 Quota Exceeded", cooldown_seconds=_exhaustion_cooldown_seconds(err_str),
                            )
                    elif is_unavailable:
                        token_guard.mark_model_exhausted(model, "503 High Demand", cooldown_seconds=20.0)
                    break
            chain_errors[model] = _short_error(last_error)

        raise RuntimeError(
            f"Gemini API Fehler nach allen Versuchen ({self.model_name}): {last_error}"
            + _describe_chain_failures(all_candidates, chain_errors)
        ) from last_error

    async def generate_json(self, prompt: str, system_prompt: str | None = None) -> str:
        config = genai_types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            system_instruction=system_prompt if system_prompt else None,
            response_mime_type="application/json",
        )
        res = await self._call_with_retry_and_usage(prompt, config)
        return res.text


# ── Prompt-Kompression für Groq-Fallbacks ──────────────────────────────────────────────────
# Groqs Free-Tier-TPM-Limit sprengt schon ein einzelner großer Agenten-Prompt; core/rate_limiter.py
# begrenzt nur die Anzahl der Aufrufe. Ein grober Schätzer (1 Token ≈ 4 Zeichen) reicht als Marge.
GROQ_PROMPT_TOKEN_BUDGET = int(os.getenv("GROQ_PROMPT_TOKEN_BUDGET", "6000"))
_CHARS_PER_TOKEN_ESTIMATE = 4


def _compress_text_for_groq(text: str, budget_chars: int) -> str:
    """Kürzt einen Text auf `budget_chars` durch Entfernen der Mitte - Anfang (Aufgabe) und Ende
    (oft die entscheidende Format-Anweisung) bleiben erhalten."""
    if budget_chars <= 0:
        return ""
    if len(text) <= budget_chars:
        return text
    marker = "\n…[wegen Groq-TPM-Limit gekürzt]…\n"
    head = int(budget_chars * 0.65)
    tail = budget_chars - head - len(marker)
    if tail <= 0:
        return text[:budget_chars]
    return text[:head] + marker + text[-tail:]


def _compress_prompt_for_groq(prompt: str, system_prompt: str | None) -> tuple[str, str | None]:
    """Komprimiert `prompt`/`system_prompt` gemeinsam auf GROQ_PROMPT_TOKEN_BUDGET."""
    budget_chars = GROQ_PROMPT_TOKEN_BUDGET * _CHARS_PER_TOKEN_ESTIMATE
    if len(prompt) + len(system_prompt or "") <= budget_chars:
        return prompt, system_prompt
    system_budget = budget_chars // 3 if system_prompt else 0
    compressed_system = _compress_text_for_groq(system_prompt, system_budget) if system_prompt else None
    prompt_budget = max(budget_chars - len(compressed_system or ""), budget_chars // 3)
    compressed_prompt = _compress_text_for_groq(prompt, prompt_budget)
    return compressed_prompt, compressed_system


def _compress_messages_for_groq(
    messages: list["AgentMessage"], system_prompt: str | None,
) -> tuple[list["AgentMessage"], str | None]:
    """Komprimiert die Werkzeug-Loop-History auf GROQ_PROMPT_TOKEN_BUDGET. Gekürzt wird nur `text`
    (gleiches Budget pro Turn); tool_calls/tool_call_id bleiben intakt, sonst bricht das Tool-Protokoll."""
    budget_chars = GROQ_PROMPT_TOKEN_BUDGET * _CHARS_PER_TOKEN_ESTIMATE
    total_len = len(system_prompt or "") + sum(len(m.text or "") for m in messages)
    if total_len <= budget_chars:
        return messages, system_prompt

    compressed_system = _compress_text_for_groq(system_prompt, budget_chars // 3) if system_prompt else None
    remaining = max(budget_chars - len(compressed_system or ""), 0)
    if remaining <= 0 or not messages:
        return messages, compressed_system

    per_message_budget = max(remaining // max(len(messages), 1), 200)
    compressed: list[AgentMessage] = []
    for msg in messages:
        if msg.text and len(msg.text) > per_message_budget:
            msg = replace(msg, text=_compress_text_for_groq(msg.text, per_message_budget))
        compressed.append(msg)
    return compressed, compressed_system


class GroqClient:
    """High-Speed Groq Inferenz Client (Llama 3, Qwen, GPT-OSS)."""

    def __init__(self, model_name: str = "openai/gpt-oss-120b"):
        self.model_name = model_name.replace("groq:", "")

    async def generate_with_usage(
        self, prompt: str, system_prompt: str | None = None, _allow_self_fallback: bool = True,
        _tried_groq_models: frozenset[str] = frozenset(),
    ) -> LLMResponse:
        if not _groq_client:
            if not _allow_self_fallback:
                raise RuntimeError("Groq innerhalb einer Fallback-Kette nicht verfügbar (kein Key).")
            return await _cross_provider_failover_with_usage("groq", prompt, system_prompt)
        # Bereits erkannte Key-/Kontingent-Fehler aus token_guard vor dem Live-Aufruf abfangen.
        if token_guard.is_model_exhausted(f"groq:{self.model_name}"):
            if not _allow_self_fallback:
                raise _pinned_provider_failure(
                    "Groq", self.model_name,
                    RuntimeError(token_guard.get_exhausted_reason(f"groq:{self.model_name}") or "bekannt nicht verfügbar"),
                )
            return await _cross_provider_failover_with_usage("groq", prompt, system_prompt)

        # Prompt-Kompression vor dem Senden wegen Groqs TPM-Limit.
        prompt, system_prompt = _compress_prompt_for_groq(prompt, system_prompt)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = await asyncio.to_thread(
                _groq_client.chat.completions.create,
                model=self.model_name,
                messages=messages,
                temperature=TEMPERATURE,
                max_tokens=MAX_OUTPUT_TOKENS,
            )
            raw_text = response.choices[0].message.content or ""
            
            import re
            clean_text = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL).strip()

            prompt_tokens = response.usage.prompt_tokens if hasattr(response, "usage") and response.usage else len(prompt) // 4
            comp_tokens = response.usage.completion_tokens if hasattr(response, "usage") and response.usage else len(clean_text) // 4
            total = prompt_tokens + comp_tokens

            token_guard.record_usage(f"groq:{self.model_name}", prompt_tokens, comp_tokens)

            return LLMResponse(
                text=clean_text,
                model_name=f"groq:{self.model_name}",
                prompt_tokens=prompt_tokens,
                completion_tokens=comp_tokens,
                total_tokens=total,
            )
        except Exception as e:
            is_rate_limit = _is_rate_limit_error(e)
            is_too_large = _is_request_too_large_error(e)
            is_not_found = _is_model_not_found_error(e)
            is_auth_error = is_authentication_error(e)
            if is_not_found:
                # Dauerhaft ungültiger Modellname -> langer Cooldown.
                token_guard.mark_model_exhausted(
                    f"groq:{self.model_name}", f"Groq Modell nicht gefunden (404): {_short_error(e, 200)}",
                    cooldown_seconds=_MODEL_NOT_FOUND_COOLDOWN_SECONDS,
                )
            elif is_rate_limit or is_too_large:
                token_guard.mark_model_exhausted(
                    f"groq:{self.model_name}", f"Groq Rate Limit/TPM: {_short_error(e, 200)}",
                    cooldown_seconds=_exhaustion_cooldown_seconds(str(e)),
                )
            elif is_auth_error:
                token_guard.mark_model_exhausted(
                    f"groq:{self.model_name}", f"Groq Auth-Fehler (ungültiger/abgelehnter API-Key): {_short_error(e, 160)}",
                    cooldown_seconds=AUTH_FAILURE_COOLDOWN_SECONDS,
                )
            # TPM-/Größen-Fehler und 404 betreffen nur DIESES Groq-Modell: erst das nächste
            # Modell aus config.GROQ_FALLBACK_MODELS probieren, ohne Provider-Wechsel.
            if is_too_large or is_not_found:
                next_model = _next_groq_fallback_model(self.model_name, _tried_groq_models)
                if next_model:
                    return await GroqClient(model_name=next_model).generate_with_usage(
                        prompt, system_prompt, _allow_self_fallback=_allow_self_fallback,
                        _tried_groq_models=_tried_groq_models | {self.model_name},
                    )
            if not _allow_self_fallback:
                if _is_tool_call_json_error(e):
                    return await _cross_provider_failover_with_usage("groq", prompt, system_prompt)
                if is_rate_limit or is_auth_error or is_too_large or is_not_found:
                    raise _pinned_provider_failure("Groq", self.model_name, e) from e
                raise
            return await _cross_provider_failover_with_usage("groq", prompt, system_prompt)

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        res = await self.generate_with_usage(prompt, system_prompt)
        return res.text

    async def generate_with_tools(
        self, messages: list["AgentMessage"], system_prompt: str | None, tools: list[dict],
        _allow_self_fallback: bool = True, _tried_groq_models: frozenset[str] = frozenset(),
    ) -> LLMResponse:
        if not _groq_client:
            if not _allow_self_fallback:
                raise RuntimeError("Groq innerhalb einer Fallback-Kette nicht verfügbar (kein Key).")
            return await _cross_provider_failover_with_tools("groq", messages, system_prompt, tools)
        if token_guard.is_model_exhausted(f"groq:{self.model_name}"):
            if not _allow_self_fallback:
                raise _pinned_provider_failure(
                    "Groq", self.model_name,
                    RuntimeError(token_guard.get_exhausted_reason(f"groq:{self.model_name}") or "bekannt nicht verfügbar"),
                )
            return await _cross_provider_failover_with_tools("groq", messages, system_prompt, tools)

        # Prompt-Kompression vor dem Senden (siehe _compress_messages_for_groq).
        messages, system_prompt = _compress_messages_for_groq(messages, system_prompt)

        try:
            response = await asyncio.to_thread(
                _groq_client.chat.completions.create,
                model=self.model_name,
                messages=_openai_build_messages(messages, system_prompt),
                tools=_openai_build_tools(tools),
                tool_choice=openai_tool_choice(),
                temperature=TEMPERATURE,
                max_tokens=MAX_OUTPUT_TOKENS,
            )
            message = response.choices[0].message
            raw_text = message.content or ""
            import re
            clean_text = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL).strip()

            tool_calls = []
            for call in (getattr(message, "tool_calls", None) or []):
                try:
                    args = json.loads(call.function.arguments) if call.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(id=call.id, name=call.function.name, arguments=args))

            usage = getattr(response, "usage", None)
            p_tok = usage.prompt_tokens if usage else 0
            c_tok = usage.completion_tokens if usage else 0
            token_guard.record_usage(f"groq:{self.model_name}", p_tok, c_tok)

            return LLMResponse(
                text=clean_text, model_name=f"groq:{self.model_name}",
                prompt_tokens=p_tok, completion_tokens=c_tok, total_tokens=p_tok + c_tok,
                tool_calls=tool_calls,
            )
        except Exception as e:
            is_rate_limit = _is_rate_limit_error(e)
            is_too_large = _is_request_too_large_error(e)
            is_not_found = _is_model_not_found_error(e)
            is_auth_error = is_authentication_error(e)
            if is_not_found:
                token_guard.mark_model_exhausted(
                    f"groq:{self.model_name}", f"Groq Modell nicht gefunden (404): {_short_error(e, 200)}",
                    cooldown_seconds=_MODEL_NOT_FOUND_COOLDOWN_SECONDS,
                )
            elif is_rate_limit or is_too_large:
                token_guard.mark_model_exhausted(
                    f"groq:{self.model_name}", f"Groq Rate Limit/TPM: {_short_error(e, 200)}",
                    cooldown_seconds=_exhaustion_cooldown_seconds(str(e)),
                )
            elif is_auth_error:
                token_guard.mark_model_exhausted(
                    f"groq:{self.model_name}", f"Groq Auth-Fehler (ungültiger/abgelehnter API-Key): {_short_error(e, 160)}",
                    cooldown_seconds=AUTH_FAILURE_COOLDOWN_SECONDS,
                )
            # Innerhalb-Groq-Ausweichkette, wie in generate_with_usage().
            if is_too_large or is_not_found:
                next_model = _next_groq_fallback_model(self.model_name, _tried_groq_models)
                if next_model:
                    return await GroqClient(model_name=next_model).generate_with_tools(
                        messages, system_prompt, tools, _allow_self_fallback=_allow_self_fallback,
                        _tried_groq_models=_tried_groq_models | {self.model_name},
                    )
            if not _allow_self_fallback:
                # Ungültiges Tool-Call-JSON: auch gepinnt failovern (siehe _TOOL_CALL_JSON_ERROR_MARKERS).
                if _is_tool_call_json_error(e):
                    return await _cross_provider_failover_with_tools("groq", messages, system_prompt, tools)
                if is_rate_limit or is_auth_error or is_too_large or is_not_found:
                    raise _pinned_provider_failure("Groq", self.model_name, e) from e
                raise
            return await _cross_provider_failover_with_tools("groq", messages, system_prompt, tools)

    async def generate_json(self, prompt: str, system_prompt: str | None = None) -> str:
        json_instruction = "\n\nAntworte AUSSCHLIESSLICH mit einem gültigen JSON-Objekt, ohne Markdown-Codeblock, ohne Erklärungen davor oder danach."
        res = await self.generate_with_usage(prompt, (system_prompt or "") + json_instruction)
        return res.text


_shared_anthropic_client: Any = None
_shared_anthropic_client_lock = threading.Lock()


def _get_shared_anthropic_client() -> Any:
    """
    Ein geteilter `anthropic.AsyncAnthropic()`-Client für alle `ClaudeClient`-Instanzen.

    Jede Instanz lädt beim Anlegen das CA-Bundle neu (~0,7 s); bei ~15 Claude-Agenten pro
    `Orchestrator()` summierte sich das auf ~10 s. Der Client ist modellneutral (Modell pro Aufruf).
    """
    global _shared_anthropic_client
    if _shared_anthropic_client is None:
        with _shared_anthropic_client_lock:
            if _shared_anthropic_client is None:
                import anthropic
                _shared_anthropic_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    return _shared_anthropic_client


class ClaudeClient:
    """Wrapper für die Anthropic Claude API mit Token-Tracking & Fallback."""

    def __init__(self, model_name: str = "claude-sonnet-5"):
        self.model_name = model_name
        self._client = None
        if ANTHROPIC_API_KEY:
            try:
                self._client = _get_shared_anthropic_client()
            except ImportError:
                self._client = None

    @staticmethod
    def _free_heavy_fallback_client():
        """
        Ausweichstufe, wenn Claude nicht verfügbar ist: Groq, DeepSeek, OpenRouter (jeweils nur,
        wenn Key vorhanden und nicht erschöpft), zuletzt die schwächere Gemini-Standardstufe.
        """
        if GROQ_API_KEY and not token_guard.is_model_exhausted(GROQ_HEAVY_MODEL):
            return GroqClient(model_name=GROQ_HEAVY_MODEL)
        if DEEPSEEK_API_KEY and not token_guard.is_model_exhausted("deepseek:deepseek-chat"):
            return DeepSeekClient()
        if OPENROUTER_API_KEY and not token_guard.is_model_exhausted("openrouter:openrouter/auto"):
            return OpenRouterClient()
        return GeminiClient(model_name=GEMINI_STANDARD_MODEL)

    async def generate_with_usage(
        self, prompt: str, system_prompt: str | None = None, _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        if not self._client:
            if not _allow_self_fallback:
                raise RuntimeError("Claude innerhalb einer Fallback-Kette nicht verfügbar (kein ANTHROPIC_API_KEY).")
            return await self._free_heavy_fallback_client().generate_with_usage(prompt, system_prompt)
        # `self._client` existiert auch bei ungültigem Key; bereits erkannte Auth-/Limit-Fehler
        # aus token_guard vor dem nächsten, sicher scheiternden Live-Aufruf abfangen.
        if token_guard.is_model_exhausted(self.model_name):
            if not _allow_self_fallback:
                raise _pinned_provider_failure(
                    "Claude", self.model_name,
                    RuntimeError(token_guard.get_exhausted_reason(self.model_name) or "bekannt nicht verfügbar"),
                )
            return await self._free_heavy_fallback_client().generate_with_usage(prompt, system_prompt)

        messages = [{"role": "user", "content": prompt}]
        kwargs: dict = {
            "model": self.model_name,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "messages": messages,
        }
        if system_prompt:
            # Anthropic Prompt Caching für den System-Prompt
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        try:
            response = await self._client.messages.create(**kwargs)
            text = response.content[0].text if response.content else ""
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "input_tokens", len(prompt) // 4) if usage else len(prompt) // 4
            comp_tokens = getattr(usage, "output_tokens", len(text) // 4) if usage else len(text) // 4
            cache_read_tokens = getattr(usage, "cache_read_input_tokens", 0) or 0 if usage else 0
            cache_write_tokens = getattr(usage, "cache_creation_input_tokens", 0) or 0 if usage else 0
            total = prompt_tokens + comp_tokens + cache_read_tokens + cache_write_tokens

            token_guard.record_usage(
                self.model_name, prompt_tokens, comp_tokens,
                cache_read_tokens=cache_read_tokens, cache_write_tokens=cache_write_tokens,
            )

            return LLMResponse(
                text=text,
                model_name=self.model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=comp_tokens,
                total_tokens=total,
                cache_read_tokens=cache_read_tokens,
                cache_write_tokens=cache_write_tokens,
            )
        except Exception as e:
            is_rate_limit = _is_rate_limit_error(e)
            is_auth_error = is_authentication_error(e)
            is_billing_exhausted = is_billing_exhaustion_error(e)
            if is_rate_limit:
                token_guard.mark_model_exhausted(self.model_name, "Claude Rate Limit")
            elif is_auth_error:
                token_guard.mark_model_exhausted(
                    self.model_name, f"Claude Auth-Fehler (ungültiger/abgelehnter API-Key): {_short_error(e, 160)}",
                    cooldown_seconds=AUTH_FAILURE_COOLDOWN_SECONDS,
                )
            elif is_billing_exhausted:
                # 400 "API usage limits reached": weder Rate-Limit noch Auth-Fehler, gilt für alle Claude-Modelle.
                reason = f"Claude Nutzungslimit erschöpft: {_short_error(e, 160)}"
                mark_claude_billing_exhausted(reason)
                token_guard.mark_model_exhausted(
                    self.model_name, reason,
                    cooldown_seconds=_exhaustion_cooldown_seconds(str(e)) or BILLING_EXHAUSTION_COOLDOWN_SECONDS,
                )
            if not _allow_self_fallback:
                if is_rate_limit or is_auth_error or is_billing_exhausted:
                    raise _pinned_provider_failure("Claude", self.model_name, e) from e
                raise
            return await self._free_heavy_fallback_client().generate_with_usage(prompt, system_prompt)

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        res = await self.generate_with_usage(prompt, system_prompt)
        return res.text

    async def generate_with_tools(
        self, messages: list["AgentMessage"], system_prompt: str | None, tools: list[dict],
        _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        if not self._client:
            if not _allow_self_fallback:
                raise RuntimeError("Claude innerhalb einer Fallback-Kette nicht verfügbar (kein ANTHROPIC_API_KEY).")
            return await self._free_heavy_fallback_client().generate_with_tools(messages, system_prompt, tools)
        if token_guard.is_model_exhausted(self.model_name):
            if not _allow_self_fallback:
                raise _pinned_provider_failure(
                    "Claude", self.model_name,
                    RuntimeError(token_guard.get_exhausted_reason(self.model_name) or "bekannt nicht verfügbar"),
                )
            return await self._free_heavy_fallback_client().generate_with_tools(messages, system_prompt, tools)

        anthropic_messages = self._build_anthropic_messages(messages)
        anthropic_tools = [
            {"name": t["name"], "description": t.get("description", ""), "input_schema": t.get("parameters", {"type": "object", "properties": {}})}
            for t in tools
        ]
        # Prompt Caching: Letztes Werkzeug im Katalog cachen
        if anthropic_tools:
            anthropic_tools[-1]["cache_control"] = {"type": "ephemeral"}

        kwargs: dict = {
            "model": self.model_name,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "messages": anthropic_messages,
            "tools": anthropic_tools,
        }
        if anthropic_tools and tool_call_required():
            kwargs["tool_choice"] = {"type": "any"}
        if system_prompt:
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        try:
            response = await self._client.messages.create(**kwargs)
            text_parts = []
            tool_calls = []
            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input) if block.input else {}))

            usage = getattr(response, "usage", None)
            p_tok = getattr(usage, "input_tokens", 0) if usage else 0
            c_tok = getattr(usage, "output_tokens", 0) if usage else 0
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0 if usage else 0
            cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0 if usage else 0
            tot = p_tok + c_tok + cache_read + cache_write

            token_guard.record_usage(
                self.model_name, p_tok, c_tok,
                cache_read_tokens=cache_read, cache_write_tokens=cache_write,
            )

            return LLMResponse(
                text="\n".join(text_parts), model_name=self.model_name,
                prompt_tokens=p_tok, completion_tokens=c_tok, total_tokens=tot,
                cache_read_tokens=cache_read, cache_write_tokens=cache_write,
                tool_calls=tool_calls,
            )
        except Exception as e:
            is_rate_limit = _is_rate_limit_error(e)
            is_auth_error = is_authentication_error(e)
            is_billing_exhausted = is_billing_exhaustion_error(e)
            if is_rate_limit:
                token_guard.mark_model_exhausted(self.model_name, "Claude Rate Limit")
            elif is_auth_error:
                token_guard.mark_model_exhausted(
                    self.model_name, f"Claude Auth-Fehler (ungültiger/abgelehnter API-Key): {_short_error(e, 160)}",
                    cooldown_seconds=AUTH_FAILURE_COOLDOWN_SECONDS,
                )
            elif is_billing_exhausted:
                # Wie in generate_with_usage(): Nutzungslimit gilt für alle Claude-Modelle.
                reason = f"Claude Nutzungslimit erschöpft: {_short_error(e, 160)}"
                mark_claude_billing_exhausted(reason)
                token_guard.mark_model_exhausted(
                    self.model_name, reason,
                    cooldown_seconds=_exhaustion_cooldown_seconds(str(e)) or BILLING_EXHAUSTION_COOLDOWN_SECONDS,
                )
            if not _allow_self_fallback:
                if is_rate_limit or is_auth_error or is_billing_exhausted:
                    raise _pinned_provider_failure("Claude", self.model_name, e) from e
                raise
            return await self._free_heavy_fallback_client().generate_with_tools(messages, system_prompt, tools)

    @staticmethod
    def _build_anthropic_messages(messages: list["AgentMessage"]) -> list[dict]:
        anthropic_messages: list[dict] = []
        for msg in messages:
            if msg.role == "user":
                anthropic_messages.append({"role": "user", "content": msg.text})
            elif msg.role == "assistant":
                content = []
                if msg.text:
                    content.append({"type": "text", "text": msg.text})
                for tc in msg.tool_calls:
                    content.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
                anthropic_messages.append({"role": "assistant", "content": content})
            elif msg.role == "tool":
                anthropic_messages.append({
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": msg.tool_call_id, "content": msg.text}],
                })
        return anthropic_messages

    async def generate_json(self, prompt: str, system_prompt: str | None = None) -> str:
        json_instruction = "\n\nAntworte AUSSCHLIESSLICH mit einem gültigen JSON-Objekt, ohne Markdown-Codeblock, ohne Erklärungen davor oder danach."
        res = await self.generate_with_usage(prompt, (system_prompt or "") + json_instruction)
        return res.text


class LLMFactory:
    """Factory zum Erstellen von LLM-Instanzen basierend auf Konfiguration."""

    @staticmethod
    def create_gemini(model_name: str = "gemini-3.8-flash") -> GeminiClient:
        return GeminiClient(model_name=model_name)

    @staticmethod
    def create_groq(model_name: str = "openai/gpt-oss-120b") -> GroqClient:
        return GroqClient(model_name=model_name)

    @staticmethod
    def create_deepseek(model_name: str = "deepseek-chat") -> DeepSeekClient:
        return DeepSeekClient(model_name=model_name)

    @staticmethod
    def create_openrouter(model_name: str = "openrouter/auto") -> OpenRouterClient:
        return OpenRouterClient(model_name=model_name)

    @staticmethod
    def create_huggingface(model_name: str = "huggingface:auto") -> HuggingFaceClient:
        return HuggingFaceClient(model_name=model_name)

    @staticmethod
    def create_claude(model_name: str = "claude-sonnet-5") -> ClaudeClient:
        return ClaudeClient(model_name=model_name)

    @staticmethod
    def create_for_model(model_name: str):
        """
        Zentrale Zuordnung Modellname -> passender Provider-Client.
        """
        if model_name.startswith("huggingface:") or "huggingface" in model_name:
            return HuggingFaceClient(model_name=model_name)
        elif model_name.startswith("openrouter:") or "openrouter" in model_name:
            return OpenRouterClient(model_name=model_name)
        elif model_name.startswith("deepseek:") or "deepseek" in model_name:
            return DeepSeekClient(model_name=model_name)
        elif model_name.startswith("groq:") or "gpt-oss" in model_name or "qwen" in model_name:
            return GroqClient(model_name=model_name)
        elif "claude" in model_name.lower():
            return ClaudeClient(model_name=model_name)
        return GeminiClient(model_name=model_name)

    @staticmethod
    def create_for_agent(agent_id: str):
        from config import get_model_for_agent
        model_name = get_model_for_agent(agent_id)
        return LLMFactory.create_for_model(model_name)

