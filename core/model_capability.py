"""
core/model_capability.py – Fähigkeitsstufen von LLM-Modellen und eine Mindeststufe
("Capability Floor") für kritische Rollen.

Realer Fund (logipulse-/vaultguard-Läufe, 2026-09): Sobald Groq sein Tageskontingent erreichte,
liefen ALLE HEAVY-Rollen (architect, security, backend, refactoring) über die Fallback-Ketten in
core/llm_factory.py auf `gemini-3.1-flash-lite` weiter. Die Ketten stellten flash-lite zwar
bereits ans Ende, ließen es aber als "letzte Rettung" zu - Architektur- und Sicherheits-
entscheidungen wurden damit unbemerkt von der schwächsten Stufe getroffen und produzierten
wiederholt dieselben Strukturfehler, die der Fix-Loop anschließend teuer reparieren musste.

Strategie (Graceful Degradation statt Silent Degradation):
1. Jedes Modell bekommt eine grobe Fähigkeitsstufe (lite < standard < heavy).
2. Kritische Rollen (config.CRITICAL_AGENT_IDS) setzen für die Dauer ihrer Aufgabe eine
   Mindeststufe (config.HEAVY_ROLE_MIN_TIER, Standard: "standard"). Die Fallback-Ketten filtern
   alle Kandidaten darunter heraus - Provider-Failover auf gleichwertige Modelle bleibt erlaubt.
3. Ist KEIN ausreichend starkes Modell verfügbar, scheitert die Aufgabe mit einer
   CapabilityFloorError. Deren Meldung wird von core/provider_exhaustion.py als
   Kontingent-Erschöpfung (Infrastruktur, kein Agentenfehler) klassifiziert, sodass der
   bestehende Circuit Breaker den Lauf pausiert, statt minderwertigen Code zu erzeugen.
4. Jede tatsächliche Abstufung wird protokolliert (record_downgrade) und kritische Rollen,
   die unterhalb ihrer konfigurierten Stufe liefen, erscheinen im Lauf-Report
   (describe_degraded_results).

Die Mindeststufe lebt in einer ContextVar: asyncio-Tasks und asyncio.to_thread() übernehmen
den Kontext automatisch, sodass auch verschachtelte Fallback-Hops (Groq -> DeepSeek -> Gemini)
sie sehen, ohne dass jede der rund 30 Aufrufstellen einen zusätzlichen Parameter braucht.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

TIER_LITE = 0
TIER_STANDARD = 1
TIER_HEAVY = 2

TIER_NAMES: dict[int, str] = {TIER_LITE: "lite", TIER_STANDARD: "standard", TIER_HEAVY: "heavy"}
_TIER_BY_NAME: dict[str, int] = {name: tier for tier, name in TIER_NAMES.items()}

# Marker, über den core/provider_exhaustion.py eine CapabilityFloorError erkennt.
CAPABILITY_FLOOR_MARKER = "capability_floor"

# Bewusst Teilstrings statt einer vollständigen Modellliste: neue Modellversionen
# (gemini-3.9-flash-lite, claude-haiku-5 ...) werden ohne Codeänderung richtig eingestuft.
# "mini" ist absichtlich nur mit Bindestrich gelistet - sonst träfe es jedes "gemini".
_LITE_MARKERS = ("lite", "haiku", "huggingface", "-mini", "nano", "-8b")
_HEAVY_MARKERS = ("opus", "sonnet", "-pro", "gpt-oss-120b", "deepseek-reasoner")


def model_capability_tier(model_name: str) -> int:
    """Grobe Fähigkeitsstufe eines Modellnamens (Provider-Präfixe werden ignoriert)."""
    name = model_name.lower() if isinstance(model_name, str) else ""
    if any(marker in name for marker in _LITE_MARKERS):
        return TIER_LITE
    if any(marker in name for marker in _HEAVY_MARKERS):
        return TIER_HEAVY
    return TIER_STANDARD


def parse_tier(value: str) -> int:
    """Wandelt "lite"/"standard"/"heavy" (oder 0/1/2) in eine Stufe um; Unbekanntes -> standard."""
    text = (value or "").strip().lower()
    if text in _TIER_BY_NAME:
        return _TIER_BY_NAME[text]
    if text.isdigit() and int(text) in TIER_NAMES:
        return int(text)
    logger.warning("Unbekannte Modell-Mindeststufe %r – verwende 'standard'.", value)
    return TIER_STANDARD


# ── Mindeststufe pro laufender Aufgabe ─────────────────────────────────────────────────────

_capability_floor: ContextVar[int] = ContextVar("capability_floor", default=TIER_LITE)
_floor_owner: ContextVar[str] = ContextVar("capability_floor_owner", default="")

FloorTokens = tuple[Token[int], Token[str]]


def current_capability_floor() -> int:
    return _capability_floor.get()


def push_capability_floor(min_tier: int, owner: str = "") -> FloorTokens:
    """Setzt die Mindeststufe für den aktuellen Kontext; Rückgabe an pop_capability_floor()."""
    return _capability_floor.set(min_tier), _floor_owner.set(owner)


def pop_capability_floor(tokens: FloorTokens) -> None:
    floor_token, owner_token = tokens
    _capability_floor.reset(floor_token)
    _floor_owner.reset(owner_token)


@contextmanager
def capability_floor(min_tier: int, owner: str = "") -> Iterator[None]:
    tokens = push_capability_floor(min_tier, owner)
    try:
        yield
    finally:
        pop_capability_floor(tokens)


def filter_by_floor(candidates: Iterable[str], floor: int | None = None) -> list[str]:
    """Behält nur Modelle, die mindestens die (aktuelle) Mindeststufe erreichen."""
    min_tier = current_capability_floor() if floor is None else floor
    return [model for model in candidates if model_capability_tier(model) >= min_tier]


class CapabilityFloorError(RuntimeError):
    """Kein Modell oberhalb der Mindeststufe verfügbar - bewusst KEINE stille Abstufung."""

    def __init__(self, requested_model: str, rejected_models: Iterable[str]):
        floor = current_capability_floor()
        owner = _floor_owner.get() or requested_model
        rejected = ", ".join(dict.fromkeys(rejected_models)) or "-"
        super().__init__(
            f"{CAPABILITY_FLOOR_MARKER}: Für '{owner}' ist kein Modell mit Mindeststufe "
            f"'{TIER_NAMES.get(floor, floor)}' verfügbar (angefordert: {requested_model}; unterhalb "
            f"der Mindeststufe verworfen: {rejected}). Die Aufgabe wird bewusst NICHT auf ein zu "
            "schwaches Modell abgestuft – Kontingent abwarten, einen weiteren API-Key ergänzen "
            "oder HEAVY_ROLE_MIN_TIER=lite setzen."
        )
        self.requested_model = requested_model
        self.floor = floor


def min_tier_for_agent(agent_id: str, configured_model: str) -> int:
    """Mindeststufe einer Rolle: nur kritische Rollen bekommen eine, und nie höher als das
    Modell, das der Nutzer der Rolle selbst zugewiesen hat (eine bewusst auf lite gesetzte
    Rolle darf weiterlaufen)."""
    from config import CRITICAL_AGENT_IDS, HEAVY_ROLE_MIN_TIER

    if agent_id not in CRITICAL_AGENT_IDS:
        return TIER_LITE
    return min(parse_tier(HEAVY_ROLE_MIN_TIER), model_capability_tier(configured_model))


# ── Sichtbarkeit tatsächlicher Abstufungen ─────────────────────────────────────────────────


@dataclass(frozen=True)
class DowngradeEvent:
    owner: str
    requested: str
    actual: str
    reason: str


_downgrade_events: deque[DowngradeEvent] = deque(maxlen=200)


def record_downgrade(requested: str, actual: str, reason: str = "") -> None:
    """Protokolliert eine Abstufung; ein Stufenverlust wird zusätzlich als Warnung geloggt."""
    event = DowngradeEvent(owner=_floor_owner.get(), requested=requested, actual=actual, reason=reason)
    _downgrade_events.append(event)
    if model_capability_tier(actual) < model_capability_tier(requested):
        logger.warning(
            "Modell-Abstufung%s: %s -> %s (%s)",
            f" für {event.owner}" if event.owner else "", requested, actual, reason or "Fallback",
        )


def drain_downgrade_events() -> list[DowngradeEvent]:
    events = list(_downgrade_events)
    _downgrade_events.clear()
    return events


def describe_degraded_results(results: Iterable[Any]) -> list[str]:
    """Report-Zeilen für erfolgreiche Aufgaben kritischer Rollen, die auf einem schwächeren als
    dem konfigurierten Modell liefen (erwartet Objekte mit agent_id/model_used/success)."""
    from config import CRITICAL_AGENT_IDS, get_model_for_agent

    lines: list[str] = []
    seen: set[tuple[str, str]] = set()
    for result in results:
        agent_id = getattr(result, "agent_id", "")
        used = getattr(result, "model_used", "")
        if not used or agent_id not in CRITICAL_AGENT_IDS or not getattr(result, "success", False):
            continue
        configured = get_model_for_agent(agent_id)
        used_tier, configured_tier = model_capability_tier(used), model_capability_tier(configured)
        if used_tier < configured_tier and (agent_id, used) not in seen:
            seen.add((agent_id, used))
            lines.append(
                f"`{agent_id}`: konfiguriert `{configured}` ({TIER_NAMES[configured_tier]}), "
                f"tatsächlich `{used}` ({TIER_NAMES[used_tier]})"
            )
    return lines
