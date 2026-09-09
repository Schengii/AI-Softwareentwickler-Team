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

_PROVIDER_EXHAUSTION_MARKERS = ("429", "resource_exhausted", "quota")


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
