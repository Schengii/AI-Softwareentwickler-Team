"""
core/provider_exhaustion.py – Gemeinsame Erkennung einer API-Kontingent-/Rate-Limit-Erschöpfung
(429/RESOURCE_EXHAUSTED/quota) anhand einer AgentResult.error-Meldung.

Team-Optimierung (KI-Team-Weiterentwicklung): core/backlog_worker.py._is_provider_exhaustion_
error() erkannte diesen Fehlerfall bisher nur für den autonomen Ticket-Worker-Pfad
(--work-backlog) - der interaktive Orchestrator-Lauf (agents/orchestrator/dispatch.py) hatte
dieselbe Erschöpfungssituation real getroffen (memory/history_default.json, 2026-09-09: 11 von
32 Agenten-Aufrufen scheiterten am Laufende in Folge mit `total_tokens: 0`, weil alle
konfigurierten Provider gleichzeitig ihr Tages-Kontingent ausgeschöpft hatten), aber KEINE
Möglichkeit, das von einem echten Code-Defekt zu unterscheiden - das daraus resultierende
`unresolved-governance-critical-agent_governance`-Ticket sah für eine spätere Prüfung identisch
aus wie ein echter, ungelöster Bug. Diese Logik hierher ausgelagert, damit beide Pfade
(core/backlog_worker.py UND agents/orchestrator/dispatch.py) dieselbe, einmal geprüfte
Erkennung nutzen, statt sie ein zweites Mal (und potenziell abweichend) zu duplizieren.
"""

# "capability_floor": core/model_capability.CapabilityFloorError - alle ausreichend starken
# Modelle einer kritischen Rolle sind erschöpft. Infrastruktur, kein Agentenfehler: der Circuit
# Breaker soll pausieren, statt die Aufgabe einem zu schwachen Modell zu überlassen.
_PROVIDER_EXHAUSTION_MARKERS = ("429", "resource_exhausted", "quota", "capability_floor")


def is_provider_exhaustion_error(error: str | None) -> bool:
    """Erkennt eine API-Kontingent-/Rate-Limit-Erschöpfung (429/RESOURCE_EXHAUSTED/quota) in
    einer Fehlermeldung - siehe Moduldocstring für die volle Herleitung."""
    if not error:
        return False
    lowered = error.lower()
    return any(marker in lowered for marker in _PROVIDER_EXHAUSTION_MARKERS)


def all_failed_on_provider_exhaustion(results: list) -> bool:
    """True, wenn `results` (eine Liste von Objekten mit `.success`/`.error`, z.B.
    core/message_bus.py.AgentResult) mindestens ein Ergebnis enthält UND ALLE davon an einer
    API-Kontingent-Erschöpfung scheiterten. Eine leere Liste (kein Agent lief überhaupt) zählt
    bewusst NICHT als "alle gescheitert" - das ist ein anderer, hier nicht behandelter Fall."""
    return bool(results) and all(
        not getattr(r, "success", True) and is_provider_exhaustion_error(getattr(r, "error", None))
        for r in results
    )


# ── Fehler-Klassifikation (Stufe 0 der Masterplan-Optimierung) ────────────────────────────
#
# Realer Fund (KI-Team-Masterplan-Analyse, 09.09.2026): In memory/run_history.json standen
# 160 Fehlschläge unter dem Modell `claude-sonnet-5` - für ein Modell, das laut
# memory/cost_history.json NIE einen einzigen Call gemacht hat (ANTHROPIC_API_KEY leer). Der
# Grund: agents/base_agent.py protokollierte im Fehlerpfad das KONFIGURIERTE statt des
# tatsächlich kontaktierten Modells. Dadurch wurden reine Infrastruktur-Ausfälle (fehlender
# API-Key, erschöpftes Tageskontingent) statistisch wie echte Qualitätsmängel des Agenten
# gewertet. core/optimization_advisor.py und core/team_retro.py zogen daraus Schlüsse und
# schrieben Einträge wie "Agent 'tester' liegt mit 57.1% Erfolgsquote deutlich unter dem
# Durchschnitt" nach memory/team_lessons.jsonl - der Selbstoptimierungs-Kreislauf lief also
# auf verfälschten Daten.
#
# Diese Klassifikation trennt beide Welten: Nur AGENT_ERROR/TIMEOUT sind dem Agenten
# zuzurechnen, PROVIDER_* sind Infrastruktur und müssen aus jeder Erfolgsquote herausgerechnet
# werden (siehe is_infrastructure_failure()).

FAILURE_CLASS_PROVIDER_EXHAUSTED = "provider_exhausted"   # 429 / RESOURCE_EXHAUSTED / Quota
FAILURE_CLASS_PROVIDER_UNAVAILABLE = "provider_unavailable"  # Kein API-Key / Client nicht instanziierbar
FAILURE_CLASS_TIMEOUT = "timeout"                          # Zeitüberschreitung
FAILURE_CLASS_AGENT_ERROR = "agent_error"                  # Echter, dem Agenten zurechenbarer Fehler

# Meldungen, die eine fehlende/nicht instanziierbare Provider-Anbindung kennzeichnen - also
# eine Konfigurationslücke, keinen Agentenfehler. Der erste Marker stammt wörtlich aus
# core/llm_factory.py.ClaudeClient.generate_with_usage()/generate_with_tools().
_PROVIDER_UNAVAILABLE_MARKERS = (
    "innerhalb einer fallback-kette nicht verfügbar",
    "kein anthropic_api_key",
    "api_key",
    "api key not",
    "no api key",
    "authentication",
    "unauthorized",
    "401",
    "invalid_api_key",
)

_TIMEOUT_MARKERS = ("timeout", "timed out", "deadline exceeded", "zeitüberschreitung")


def classify_failure(error: str | None) -> str:
    """
    Ordnet eine AgentResult.error-Meldung genau einer der FAILURE_CLASS_*-Konstanten zu.

    Reihenfolge ist bewusst: Kontingent-Erschöpfung wird ZUERST geprüft, weil eine
    429-Meldung mancher Provider zusätzlich das Wort "timeout" enthalten kann - der
    eigentliche, handlungsleitende Befund ist dann trotzdem die Erschöpfung.
    """
    if not error:
        return FAILURE_CLASS_AGENT_ERROR
    if is_provider_exhaustion_error(error):
        return FAILURE_CLASS_PROVIDER_EXHAUSTED
    lowered = error.lower()
    if any(marker in lowered for marker in _PROVIDER_UNAVAILABLE_MARKERS):
        return FAILURE_CLASS_PROVIDER_UNAVAILABLE
    if any(marker in lowered for marker in _TIMEOUT_MARKERS):
        return FAILURE_CLASS_TIMEOUT
    return FAILURE_CLASS_AGENT_ERROR


def is_infrastructure_failure(failure_class: str | None) -> bool:
    """
    True, wenn ein Fehlschlag der Infrastruktur (Kontingent, fehlender Key) zuzurechnen ist und
    daher NICHT in die Erfolgsquote eines Agenten einfließen darf. Ein Agent, der wegen eines
    429 gar nicht erst laufen konnte, hat nicht "versagt" - er wurde nie gefragt.
    """
    return failure_class in (FAILURE_CLASS_PROVIDER_EXHAUSTED, FAILURE_CLASS_PROVIDER_UNAVAILABLE)


def is_infrastructure_error(error: str | None) -> bool:
    """Bequemlichkeits-Variante von is_infrastructure_failure() direkt auf der Fehlermeldung -
    für Auswertungen über ältere Historien-Einträge, die noch kein `failure_class`-Feld haben."""
    return is_infrastructure_failure(classify_failure(error))


# ── Circuit Breaker bei Massen-Ausfall (Masterplan-Optimierung, Stufe 1) ───────────────────
#
# Realer Fund (workspace/event_ticket_api, Lauf vom 09.09.2026 14:43): 21 Agenten-Aufrufe,
# davon 19 gescheitert, 8.193 Tokens, `files_written_count: 0`. Trotzdem lief der Lauf
# vollständig weiter: Alle Phasen wurden durchlaufen, die Verifikation gestartet, ein
# Fix-Auftrag an den tester dispatcht (.ai_team_decisions.jsonl: "missing_tests_fix_dispatched")
# und PROJECT_STATE.md mit dem Status "⚠️ In Entwicklung / Verifikation ausstehend" geschrieben -
# obwohl KEIN EINZIGER Agent Code produziert hatte.
#
# all_failed_on_provider_exhaustion() oben erkennt nur den Fall, dass eine Welle VOLLSTÄNDIG
# scheiterte. Real ist das Bild fast immer gemischt (19 von 21), weil einzelne Aufrufe noch aus
# einem Rest-Kontingent bedient werden. Deshalb hier eine Quote statt eines Alles-oder-nichts.


def infrastructure_failure_ratio(results: list) -> float:
    """
    Anteil der Ergebnisse, die an der Infrastruktur (Kontingent/fehlender Key) scheiterten -
    0.0 für eine leere Liste (kein Agent lief, das ist ein anderer Fall).
    """
    if not results:
        return 0.0
    betroffen = sum(
        1 for r in results
        if not getattr(r, "success", True)
        and is_infrastructure_failure(
            getattr(r, "failure_class", "") or classify_failure(getattr(r, "error", None))
        )
    )
    return betroffen / len(results)


def should_trip_breaker(results: list, threshold: float) -> bool:
    """
    True, wenn so viele Aufrufe einer Welle an der Infrastruktur scheiterten, dass ein
    Weiterarbeiten sinnlos ist. `threshold` ist der Anteil (0.0-1.0), ab dem abgebrochen wird;
    ein Wert <= 0 schaltet den Breaker ab (Verhalten wie zuvor).
    """
    if threshold <= 0 or not results:
        return False
    return infrastructure_failure_ratio(results) >= threshold


def should_trip_run_breaker(results: list, threshold: float, min_sample: int) -> bool:
    """
    Dasselbe über ALLE bisherigen Aufrufe eines Laufs statt nur über die aktuelle Welle.

    Realer Fund (Laufanalyse 2026-09-16): should_trip_breaker() oben sieht immer nur EINE Welle.
    Verteilt sich der Kontingent-Engpass gleichmäßig über viele kleine Wellen, bleibt jede
    einzelne unter der Schwelle, obwohl der Lauf als Ganzes längst ausblutet. Im Lauf
    `sentinelgrid` scheiterten 5 von 15 Aufrufen (33%) an erschöpften Kontingenten - keine Welle
    erreichte die 60%-Wellenschwelle, der Lauf arbeitete alle Phasen ab, verbrauchte 105.972
    Tokens und endete trotzdem rot. Dasselbe Muster bei `certpulse` (20%, 115.117 Tokens). Alle
    Läufe des Auswertungsfensters mit Kontingent-Ausfällen endeten ohne bestandene Verifikation.

    `min_sample` verhindert den umgekehrten Fehler: Bei zwei Aufrufen ist ein einzelner
    429er-Ausfall bereits eine Quote von 50%, aber keine Aussage über den Lauf (realer Fall
    `ai_team_framework`: 1 von 2). Erst ab genug Aufrufen ist die Quote belastbar.
    """
    if threshold <= 0 or len(results) < max(min_sample, 1):
        return False
    return infrastructure_failure_ratio(results) >= threshold
