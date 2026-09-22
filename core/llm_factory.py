"""
core/llm_factory.py – Erstellt und verwaltet LLM-Clients (Gemini, Groq, DeepSeek, OpenRouter,
HuggingFace, Claude) mit einheitlicher Schnittstelle (Text, JSON, Function-Calling).

Enthält Token-Messung, Gemini-Key-Pool, provider-übergreifende Fallback-Ketten, Cooldowns
für Rate-Limits/Kontingent-/Auth-Fehler (via core/token_guard.py) und sichtbare Modell-Abwertungen.
"""

import hashlib
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from typing import Any

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
    MAX_OUTPUT_TOKENS,  # noqa: F401 - von core/llm_providers/*.py über `_lf.MAX_OUTPUT_TOKENS` gelesen
    OPENROUTER_API_KEY,
    TEMPERATURE,  # noqa: F401 - von core/llm_providers/*.py über `_lf.TEMPERATURE` gelesen
)
from core.model_capability import CapabilityFloorError, filter_by_floor, record_downgrade
from core.rate_limiter import RateLimiter
from core.token_guard import token_guard

logger = logging.getLogger(__name__)

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

# ──────────────────────────────────────────
# Gemini Explizites Context-Caching (P5-2, ROADMAP_TEMP.md)
# ──────────────────────────────────────────
# Realer Fund 2026-09-20: core/llm_factory.py hat bisher nur `cached_content_token_count` aus der
# Antwort GELESEN (Zeile weiter unten in _parse_gemini_tool_response), aber nie ein Cache-Objekt
# ERZEUGT - Gemini betreibt (anders als Anthropic) kein implizites Prompt-Caching, ohne ein
# explizites `caches.create(...)` gibt es schlicht nichts zu lesen. Scan über alle 264
# `agent_call`-Events in `workspace/*/.ai_team_runs/*_trace.jsonl`: 0% Cache-Trefferquote,
# ausnahmslos. Bei 19,56 Mio. Prompt-Tokens in Summe (Stand 2026-09-20) der groesste bezifferbare
# Hebel aus P5-2.
#
# Design bewusst maximal defensiv: JEDE Cache-Erstellung ist reiner Best-Effort. Scheitert sie
# (Modell unterstuetzt kein Caching, Prompt unter dem Mindest-Token-Wert des Modells, API-Version
# ohne `caches`-Endpunkt, Netzwerkfehler) faellt der Aufruf exakt auf das bisherige Verhalten
# zurueck (system_instruction inline, kein cached_content) - eine fehlgeschlagene Cache-Erstellung
# darf NIEMALS den eigentlichen generate_content-Aufruf verhindern oder verfaelschen.
#
# Registry-Schluessel enthaelt den API-Key: ein Cache-Objekt ist an den Key/das Projekt gebunden,
# unter dem er angelegt wurde (_get_gemini_client() kann je nach Erschoepfungs-Zustand zwischen
# mehreren Keys rotieren). Ohne den Key im Schluessel wuerde bei Key-Rotation ein Cache-Name aus
# einem fremden Key weitergereicht - das API-seitige Scheitern faengt der Try/Except zwar sicher
# ab, verschenkt die Trefferquote aber unnoetig.
_gemini_cache_registry: dict[tuple[str, str, str], tuple[str, float]] = {}
# Modelle, bei denen eine Cache-Erstellung zuletzt fehlgeschlagen ist (z.B. weil das Modell/die
# Free-Tier-Stufe explizites Caching gar nicht anbietet) - verhindert, dass jeder einzelne
# Agenten-Aufruf erneut denselben aussichtslosen API-Roundtrip verschwendet. Zeitbasiert statt
# dauerhaft (analog zu _gemini_exhausted_keys): eine einzelne transiente Ursache (Netzwerk,
# kurzzeitiger 503) soll Caching nicht fuer den Rest des Prozesses abschalten.
_gemini_cache_unsupported_models: dict[str, float] = {}  # model -> Zeitpunkt (monotonic), ab dem erneut versucht wird
GEMINI_CACHE_UNSUPPORTED_COOLDOWN_SECONDS = 3600  # 1 Stunde
GEMINI_CACHE_MIN_CHARS = 6000  # konservativ oberhalb der dokumentierten Modell-Mindestwerte
GEMINI_CACHE_TTL_SECONDS = 900  # 15 Minuten - deckt einen typischen Agentic-Loop-Durchlauf ab


def _gemini_config_with_cache(
    base_config: "genai_types.GenerateContentConfig", model: str, system_prompt: str | None,
) -> "genai_types.GenerateContentConfig":
    """Liefert `base_config` mit `cached_content` gesetzt, wenn ein Cache-Treffer/-Erstellung
    gelingt - sonst UNVERÄNDERT `base_config`. Für Aufrufstellen, die bereits ein fertiges
    `GenerateContentConfig` gebaut haben (z.B. `_call_with_retry_and_usage`, gemeinsam genutzt von
    mehreren Aufrufern) und keine eigene Cache-fähige Konstruktion rechtfertigen."""
    try:
        cache_name = _gemini_cached_content_name(model, system_prompt)
        if not cache_name:
            return base_config
        return base_config.model_copy(update={"cached_content": cache_name, "system_instruction": None})
    except Exception:
        # Doppelt abgesichert (auch wenn _gemini_cached_content_name selbst schon nie werfen
        # sollte): der eigentliche generate_content-Aufruf darf durch diese Optimierung nie
        # gefaehrdet werden - im Zweifel unveraendert ohne Caching weitermachen.
        return base_config


def _gemini_cached_content_name(
    model: str,
    system_prompt: str | None,
    tools: "list[genai_types.Tool] | None" = None,
    tool_config: "genai_types.ToolConfig | None" = None,
) -> str | None:
    """Best-Effort: liefert den Namen eines Gemini-Cache-Objekts fuer `system_prompt` (und, falls
    gesetzt, `tools`/`tool_config`), oder `None`, wenn Caching fuer diesen Aufruf nicht
    sinnvoll/moeglich ist. Wirft NIE - jeder Fehler (Modell ohne Cache-Unterstuetzung, Prompt zu
    kurz, API-Fehler) fuehrt zu `None`, der Aufrufer verhaelt sich dann exakt wie vor dieser
    Optimierung.

    WICHTIG (live an der echten API gefunden, 2026-09-20 - der erste Versuch dieser Optimierung
    ohne `tools`/`tool_config` schlug in JEDEM Aufruf mit Werkzeugkatalog fehl, siehe
    ROADMAP_TEMP.md P5-2): die Gemini-API akzeptiert `cached_content` NICHT gleichzeitig mit
    `system_instruction`, `tools` ODER `tool_config` im GenerateContentConfig - wörtliche
    Fehlermeldung: "CachedContent can not be used with GenerateContent request setting
    system_instruction, tools or tool_config. Proposed fix: move those values to CachedContent
    from GenerateContent request." Alle drei muessen deshalb, wenn vorhanden, TEIL des
    Cache-Objekts selbst sein, nicht nur der System-Prompt - der Aufrufer darf sie dann im
    GenerateContentConfig NICHT mehr zusaetzlich setzen (siehe _gemini_config_with_cache() bzw.
    generate_with_tools()."""
    # Defensive Typpruefung statt Annahme: an einigen Aufrufstellen koennte hier theoretisch ein
    # bereits von der SDK umgewandeltes Objekt statt eines rohen Strings ankommen (z.B. ueber
    # `config.system_instruction` zurückgelesen) - `isinstance` statt `len()`/`.encode()` direkt
    # aufzurufen verhindert, dass ein unerwarteter Typ hier unabgefangen crasht.
    if not isinstance(system_prompt, str) or not model:
        return None
    now = time.monotonic()
    if len(system_prompt) < GEMINI_CACHE_MIN_CHARS:
        return None
    if now < _gemini_cache_unsupported_models.get(model, 0.0):
        return None
    try:
        client, active_key = _get_gemini_client(model=model)
        if client is None or not active_key:
            return None
        # tools/tool_config gehen als STRING mit in den Hash ein: unterschiedliche Werkzeug-
        # Kataloge (verschiedene Rollen) brauchen unterschiedliche Caches, sonst würde eine Rolle
        # versehentlich den Werkzeugkatalog einer anderen Rolle aus dem Cache bekommen.
        try:
            tools_repr = repr(tools) + repr(tool_config)
        except Exception:
            tools_repr = ""
        prompt_hash = hashlib.sha256((system_prompt + tools_repr).encode("utf-8")).hexdigest()
        registry_key = (active_key, model, prompt_hash)
        cached = _gemini_cache_registry.get(registry_key)
        if cached and cached[1] > now:
            return cached[0]
        cache = client.caches.create(
            model=model,
            config=genai_types.CreateCachedContentConfig(
                system_instruction=system_prompt,
                tools=tools or None,
                tool_config=tool_config,
                ttl=f"{GEMINI_CACHE_TTL_SECONDS}s",
            ),
        )
        cache_name = getattr(cache, "name", None)
        if not cache_name:
            return None
        _gemini_cache_registry[registry_key] = (cache_name, now + GEMINI_CACHE_TTL_SECONDS - 30)
        return cache_name
    except Exception as e:
        # Best-Effort: einmal pro Modell protokollieren statt bei jedem Aufruf erneut - danach
        # gilt das Modell fuer eine Stunde als "kein Caching" (siehe Docstring der Registry oben).
        was_already_marked = now < _gemini_cache_unsupported_models.get(model, 0.0)
        if not was_already_marked:
            logger.debug("Gemini Context-Caching fuer Modell '%s' nicht verfuegbar: %s", model, e)
        _gemini_cache_unsupported_models[model] = now + GEMINI_CACHE_UNSUPPORTED_COOLDOWN_SECONDS
        return None


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
#
# Realer Fund (pulse_queue, 2026-09-22, FEHLERANALYSE_PULSE_QUEUE_20260922_TEMP.md, Problem 1):
# Ein 429-Rate-Limit ("Please try again in 13m52s") ließ den Tester-Aufruf 316 Sekunden hängen,
# obwohl P7-1 bereits einen anwendungsseitigen Failover zu OpenRouter/DeepSeek/Gemini bereitstellt
# (core.llm_providers.groq._same_schema_failover_with_usage()). Ursache: der Groq-SDK-Client
# (max_retries=2 per Default, kein explizites Timeout) respektiert den Retry-After-Header selbst
# und schläft SDK-intern, bevor unser eigener Fallback überhaupt zum Zug kommt. max_retries=0
# gibt jeden Fehler SOFORT an core/llm_providers/groq.py zurück, das dort bereits robust
# klassifiziert (Rate-Limit/Auth/zu groß/404) und selbst entscheidet, ob und wohin gewechselt
# wird; timeout=20 verhindert zusätzlich ein Hängenbleiben bei einem antwortlosen Request.
_groq_client = None
if GROQ_API_KEY:
    try:
        from groq import Groq
        _groq_client = Groq(api_key=GROQ_API_KEY, max_retries=0, timeout=20.0)
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
# Meldung zu liefern. Ein Hop zu einem SCHEMA-FREMDEN Provider (Gemini) bleibt nach dem Pinning
# bewusst aus (Provider-Historie-Korruption, siehe agents/base_agent.py._run_agentic_loop());
# ein Hop zu einem schema-GLEICHEN Provider ist dagegen sicher und in
# _same_schema_failover_with_tools()/_with_usage() unten eigens erlaubt (P7-1, ROADMAP_TEMP.md).
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


# ── Schema-gleicher Failover innerhalb eines GEPINNTEN Aufrufs (P7-1, ROADMAP_TEMP.md) ─────
#
# Realer Fund (webhook_sentinel 2026-09-22, omnimetric_engine 2026-09-21): der `tester` scheiterte
# in beiden Läufen an genau derselben Meldung - Groq (openai/gpt-oss-120b) TPM-/Größen-erschöpft,
# UND bereits gepinnt (_allow_self_fallback=False, weil ein früherer Fallback-Hop innerhalb
# desselben Werkzeug-Loops bereits auf Groq gewechselt hatte). Der bestehende Code probiert dann
# nur noch andere GROQ-Modelle (_next_groq_fallback_model); sind auch die erschöpft, endet der
# Aufruf sofort in _pinned_provider_failure() - ohne je zu prüfen, ob ein anderer Provider
# tatsächlich in Frage käme.
#
# Das Pinning selbst existiert, weil ein Wechsel MITTEN in der Tool-Call-Historie bei Gemini
# bricht (thought_signature-Pflicht, siehe agents/base_agent.py). Groq, DeepSeek und OpenRouter
# teilen sich dagegen exakt dasselbe OpenAI-kompatible Tool-Call-Schema
# (core/llm_providers/_shared.py._openai_build_messages/_openai_build_tools - von allen drei
# Client-Klassen unverändert wiederverwendet). Ein Hop zwischen GENAU DIESEN drei Providern
# korrumpiert die Historie also nicht - dieselbe Begründung, mit der _is_tool_call_json_error()
# oben bereits einen Hop trotz Pinning erlaubt. _independent_failover_candidates() liefert ohnehin
# nur Kandidaten aus _INDEPENDENT_FAILOVER_MODELS (Groq/DeepSeek/OpenRouter, niemals Gemini/Claude)
# - hier direkt wiederverwendet, keine neue Kandidatenliste nötig.
#
# Jeder Versuch bleibt selbst _allow_self_fallback=False (kein Ping-Pong über mehr als einen Hop);
# scheitern alle, wirft die Funktion die letzte Exception weiter - der Aufrufer (GroqClient etc.)
# fängt sie und meldet _pinned_provider_failure() wie bisher, jetzt aber erst NACHDEM ein echter
# Ausweich-Versuch stattgefunden hat.


async def _same_schema_failover_with_usage(
    failed_provider: str, prompt: str, system_prompt: str | None,
) -> "LLMResponse":
    """Schema-gleicher Ausweich-Versuch für einen GEPINNTEN Aufruf, siehe Moduldocstring oberhalb."""
    last_exc: Exception | None = None
    for model in _independent_failover_candidates(failed_provider):
        try:
            return await LLMFactory.create_for_model(model).generate_with_usage(
                prompt, system_prompt, _allow_self_fallback=False,
            )
        except Exception as exc:
            last_exc = exc
            continue
    raise last_exc or RuntimeError(
        f"Kein schema-gleicher Ausweich-Provider für '{failed_provider}' verfügbar.",
    )


async def _same_schema_failover_with_tools(
    failed_provider: str, messages: list["AgentMessage"], system_prompt: str | None, tools: list[dict],
) -> "LLMResponse":
    """Wie _same_schema_failover_with_usage(), für Function-Calling-Aufrufe."""
    last_exc: Exception | None = None
    for model in _independent_failover_candidates(failed_provider):
        try:
            return await LLMFactory.create_for_model(model).generate_with_tools(
                messages, system_prompt, tools, _allow_self_fallback=False,
            )
        except Exception as exc:
            last_exc = exc
            continue
    raise last_exc or RuntimeError(
        f"Kein schema-gleicher Ausweich-Provider für '{failed_provider}' verfügbar.",
    )


# ── Prompt-Kompression für Groq-Fallbacks ──────────────────────────────────────────────────
# Groqs Free-Tier-TPM-Limit sprengt schon ein einzelner großer Agenten-Prompt; core/rate_limiter.py
# begrenzt nur die Anzahl der Aufrufe. Ein grober Schätzer (1 Token ≈ 4 Zeichen) reicht als Marge.
GROQ_PROMPT_TOKEN_BUDGET = int(os.getenv("GROQ_PROMPT_TOKEN_BUDGET", "6000"))
_CHARS_PER_TOKEN_ESTIMATE = 4

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


# ── Re-Exports: P6-5 (ROADMAP_TEMP.md) hat die Provider-Klassen nach core/llm_providers/
# verschoben. Sie werden hier zurückimportiert, damit `from core.llm_factory import X` für
# jeden bestehenden Importpfad unverändert funktioniert - dieses Modul bleibt die stabile,
# kanonische Importoberfläche. Reihenfolge hier ist unkritisch (alphabetisch): jeder Provider,
# der einen ANDEREN Provider als Fallback braucht (Gemini→Groq, HuggingFace→Gemini,
# Claude→alle vier), importiert diesen direkt aus dessen eigenem Modul, nicht über
# core.llm_factory zurück - keine Kreisimport-Reihenfolge zu beachten. Geteilten Zustand aus
# DIESEM Modul liest jeder Provider nur über `import core.llm_factory as _lf; _lf.NAME`, nie
# über `from core.llm_factory import NAME` - ein `@patch("core.llm_factory.NAME", ...)` in
# Tests trifft so immer die tatsächlich gelesene Bindung, nie nur eine unabhängige Kopie in
# einem Provider-Modul.
from core.llm_providers._shared import (
    AgentMessage,
    LLMResponse,
    ToolCall,
    openai_tool_choice,
    require_tool_call,
    tool_call_required,
)
from core.llm_providers.claude import ClaudeClient
from core.llm_providers.deepseek import DeepSeekClient
from core.llm_providers.gemini import GeminiClient
from core.llm_providers.groq import GroqClient
from core.llm_providers.huggingface import HuggingFaceClient
from core.llm_providers.openrouter import OpenRouterClient

__all__ = [
    "AgentMessage", "ClaudeClient", "DeepSeekClient", "GeminiClient", "GroqClient",
    "HuggingFaceClient", "LLMFactory", "LLMResponse", "OpenRouterClient", "ToolCall",
    "openai_tool_choice", "require_tool_call", "tool_call_required",
]


class LLMFactory:
    """Factory zum Erstellen von LLM-Instanzen basierend auf Konfiguration."""

    @staticmethod
    def create_gemini(model_name: str = "gemini-3.8-flash") -> GeminiClient:
        return GeminiClient(model_name=model_name)

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

