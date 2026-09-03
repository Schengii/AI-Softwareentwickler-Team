"""
core/backlog_store.py – Persistenter Backlog/Kanban-Zustand über ALLE Trigger-Quellen hinweg

Bisher hatte jede Trigger-Quelle ihren eigenen, isolierten Fortschritts-Begriff: das
Web-Dashboard hält Jobs nur IM SPEICHER (weg nach jedem Neustart), core/issue_watcher.py
trackt Fortschritt ausschließlich über GitHub-Labels (nur auf GitHub selbst sichtbar), die CLI
gar nicht. Es gab keine EINZIGE Stelle, die zeigt, woran das Team gerade oder zuletzt
gearbeitet hat – unabhängig davon, ob der Auftrag über CLI, Dashboard oder autonom über ein
GitHub-Issue kam. Genau das macht ein echtes Team über ein Kanban-Board sichtbar.

`memory/backlog.json` hält eine flache Liste von Tickets (dieselbe Lade-/Speicher-Konvention
wie memory/cost_history.py: Modul-Konstante für den Dateipfad, in Tests per patch.object()
ausgetauscht). JEDE Trigger-Quelle (interface/cli.py, interface/web_dashboard.py,
core/issue_watcher.py) schreibt hier hinein statt eigene Parallel-Zustände zu pflegen.
"""

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from config import BASE_DIR

BACKLOG_FILE = Path(BASE_DIR) / "memory" / "backlog.json"

# Kanban-Spaltenreihenfolge (siehe interface/web_dashboard.py Board-Rendering und
# interface/cli.py /backlog). "review" = ein PR wurde eröffnet und wartet auf Freigabe/Merge
# (core/issue_watcher.py, interface/cli.py bei aktivem PR-Workflow) - "done" heißt NICHT
# gemerged, sondern "das Team hat seinen Teil abgeschlossen" (Merge-Erkennung wäre ein
# zusätzlicher gh-Aufruf, den es aktuell bewusst noch nicht gibt).
STATUSES: tuple[str, ...] = ("todo", "in_progress", "review", "blocked", "cancelled", "done")

# Deckelt die Datei gegen unbegrenztes Wachstum über viele Sitzungen/Poll-Zyklen hinweg -
# dieselbe Vorsicht wie MAX_RULE_LENGTH/MAX_LOG_LINES_KEPT an anderer Stelle im Projekt.
MAX_TICKETS_KEPT = 200


@dataclass
class Ticket:
    id: str
    title: str
    source: str  # "cli" | "dashboard" | "issue"
    status: str
    created_at: str
    updated_at: str
    detail: str = ""       # PR-URL / Fehlermeldung / Issue-Nummer, je nach Status
    project_slug: str = ""
    # Sprint-/Kapazitäts-Konzept: 1=hoch, 2=mittel (Standard), 3=niedrig - dieselbe
    # Konvention wie core/message_bus.py.AgentTask.priority, damit sich beide Systeme nicht
    # widersprechen. estimate ist bewusst freier Text (z.B. "S"/"M"/"L" oder Story Points wie
    # "3") statt eines festen Enums - unterschiedliche Teams/Nutzer schätzen unterschiedlich.
    priority: int = 2
    estimate: str = ""
    # Realer Fund: Tickets waren bisher eine flache, unzusammenhängende Liste - ein größeres
    # Vorhaben ("kompletter Checkout-Flow") ließ sich nicht als zusammengehörige, sinnvoll
    # sortierte Kette abbilden, jede Anfrage wurde isoliert bearbeitet. epic ist freier Text
    # (z.B. "Checkout-Flow") statt eines festen Enums - dieselbe Konvention wie `estimate`,
    # unterschiedliche Teams benennen Epics unterschiedlich. depends_on sind IDs anderer
    # Tickets, die zuerst status="done" erreichen müssen - siehe is_ticket_ready() unten.
    epic: str = ""
    depends_on: list[str] = field(default_factory=list)
    # Team-Optimierung (Retrospektive 2026-09-03): ein von der Governance-/Verifikations-
    # Fix-Schleife (agents/orchestrator/verification.py) als "blocked" eröffnetes Ticket zu
    # einem ungelösten kritischen Befund wurde bisher NIRGENDS mehr aufgegriffen - core/
    # backlog_worker.py betrachtete nur status="todo" aus den Quellen "cli"/"dashboard", ein
    # "blocked"-Ticket mit source="orchestrator" blieb für immer liegen, selbst wenn ein
    # späterer, unabhängiger Poll-Zyklus das Problem durchaus hätte angehen können. `retries`
    # zählt, wie oft core/backlog_worker.py ein SOLCHES Ticket bereits eigenständig erneut
    # aufgegriffen hat (siehe dort, GOVERNANCE_TICKET_RETRY_PREFIXES) - begrenzt auf
    # MAX_GOVERNANCE_TICKET_RETRIES, damit ein Befund, den das Team nachweislich nicht lösen
    # kann, nicht endlos Budget in identischen Fehlversuchen verbrennt, sondern nach Erreichen
    # der Grenze sichtbar für eine menschliche Prüfung liegen bleibt.
    retries: int = 0


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _load_raw() -> list[dict]:
    if not BACKLOG_FILE.exists():
        return []
    try:
        return json.loads(BACKLOG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_raw(tickets: list[dict]) -> None:
    """
    Realer Fund (Testflake unter `pytest tests/`, reproduzierbar über einen echten
    Lese-/Schreib-Race): `write_text()` direkt auf BACKLOG_FILE ist NICHT atomar - ein
    gleichzeitiger Leser (core/issue_watcher.py-Poll-Zyklus UND interface/web_dashboard.py
    laufen mehrere Jobs bewusst PARALLEL, siehe DASHBOARD_MAX_CONCURRENT_JOBS) konnte die
    Datei mitten im Schreibvorgang lesen, bekam ungültiges/abgeschnittenes JSON und landete
    dadurch in `_load_raw()`s JSONDecodeError-Fallback, der das STILLSCHWEIGEND als "keine
    Tickets" (leere Liste) behandelt - kein Fehler, keine Warnung. Traf dieser torn read
    genau einen GLEICHZEITIGEN upsert_ticket()-Aufruf (liest zuerst per _load_raw(), hängt an,
    schreibt zurück), überschrieb dessen nächster _save_raw() das GESAMTE Backlog mit nur dem
    einen eigenen Ticket - ein echter Datenverlust für alle anderen Tickets, nicht nur ein
    Test-Timing-Problem. Schreiben in eine temporäre Datei im SELBEN Verzeichnis (garantiert
    dasselbe Dateisystem) + os.replace() (atomarer Rename auf POSIX UND Windows) macht jeden
    Lesevorgang entweder den kompletten alten ODER den kompletten neuen Stand sehen, nie etwas
    dazwischen. Zusätzlicher, Windows-spezifischer Fund beim Verifizieren dieses Fixes über
    einen echten Nebenläufigkeits-Stresstest: os.replace() kann unter Windows (anders als
    POSIX) transient mit PermissionError scheitern, wenn ein anderer Thread die Zieldatei
    GENAU in diesem Moment zum Lesen offen hat (kurze Sharing-Violation, kein echter
    Dauerzustand) - kurzer Retry mit minimaler Pause behebt das, ohne die Atomizität
    aufzugeben (jeder einzelne os.replace()-Versuch bleibt für sich atomar).
    """
    BACKLOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Listenreihenfolge IST bereits Aktualisierungsreihenfolge (upsert_ticket hängt jedes
    # aktualisierte Ticket ans Ende an, siehe dort) - beim Kürzen also einfach die ÄLTESTEN
    # (vorne) fallen lassen. Bewusst KEINE erneute Sortierung nach updated_at hier: die
    # Zeitstempel-Auflösung ist Sekunden, mehrere Aktualisierungen in derselben Sekunde
    # ließen sich damit nicht mehr eindeutig ordnen.
    tickets = tickets[-MAX_TICKETS_KEPT:]
    tmp_path = BACKLOG_FILE.with_suffix(f"{BACKLOG_FILE.suffix}.tmp-{os.getpid()}-{threading.get_ident()}")
    tmp_path.write_text(json.dumps(tickets, indent=2, ensure_ascii=False), encoding="utf-8")
    max_attempts = 10
    for attempt in range(max_attempts):
        try:
            os.replace(tmp_path, BACKLOG_FILE)
            return
        except PermissionError:
            if attempt == max_attempts - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


def list_tickets(status: str | None = None) -> list[Ticket]:
    """Alle Tickets, zuletzt aktualisierte zuerst. `status=None` liefert alle Spalten."""
    tickets = [Ticket(**t) for t in _load_raw()]
    if status:
        tickets = [t for t in tickets if t.status == status]
    return list(reversed(tickets))  # Listenreihenfolge = Aktualisierungsreihenfolge, siehe _save_raw()


def get_ticket(ticket_id: str) -> Ticket | None:
    """Ein einzelnes Ticket anhand seiner ID, oder None, wenn es nicht existiert. Team-
    Retrospektive nach dem taskpulse-Lauf: Fix-Schleifen (agents/orchestrator/verification.py)
    öffnen bereits Tickets für ungelöste Funde NACH einem Lauf, prüften aber bisher nie VOR
    einem neuen Lauf, ob für dasselbe Projekt schon ein offenes Ticket zu genau diesem Problem
    existiert - ein neuer Lauf startete jedes Mal bei Null, ohne zu wissen, dass ein Fixversuch
    für ein ähnliches Problem im letzten Lauf bereits gescheitert war."""
    return next((t for t in list_tickets() if t.id == ticket_id), None)


def new_ticket_id(source: str) -> str:
    return f"{source}-{uuid.uuid4().hex[:8]}"


def upsert_ticket(
    ticket_id: str, title: str, source: str, status: str, detail: str = "", project_slug: str = "",
    priority: int | None = None, estimate: str | None = None,
    epic: str | None = None, depends_on: list[str] | None = None,
    retries: int | None = None,
) -> Ticket:
    """
    Legt ein Ticket an ODER aktualisiert ein bestehendes (anhand `ticket_id`) – ein einziger
    Aufruf für beide Fälle, damit Aufrufer nicht selbst prüfen müssen, ob das Ticket schon
    existiert (core/issue_watcher.py ruft z.B. beim Aufgreifen UND beim Abschluss desselben
    Issues auf). `created_at` bleibt beim ersten Anlegen fix, `updated_at` wird bei JEDEM
    Aufruf erneuert. `status` außerhalb von STATUSES wird nicht validiert (bewusst tolerant -
    ein unbekannter Status soll den aufrufenden Lauf nicht crashen, nur unpassend einsortiert
    im Board landen).

    `priority`/`estimate`: None (Standard) übernimmt den bereits vorhandenen Wert unverändert
    (Sentinel, KEIN Reset auf den Ticket-Standard) – die meisten bestehenden Aufrufer
    aktualisieren ein Ticket mehrfach über seinen Lebenszyklus (z.B. core/issue_watcher.py:
    "in_progress" beim Aufgreifen, "review"/"blocked" beim Abschluss) OHNE Priorität/Schätzung
    jedes Mal erneut mitzugeben – ein echter Zahlen-Default hier hätte eine beim Anlegen
    gesetzte Priorität beim nächsten Status-Update stillschweigend wieder auf "mittel"
    zurückgesetzt.
    """
    tickets = _load_raw()
    existing = next((t for t in tickets if t["id"] == ticket_id), None)
    created_at = existing["created_at"] if existing else _now()
    resolved_priority = priority if priority is not None else (existing.get("priority", 2) if existing else 2)
    resolved_estimate = estimate if estimate is not None else (existing.get("estimate", "") if existing else "")
    resolved_epic = epic if epic is not None else (existing.get("epic", "") if existing else "")
    resolved_depends_on = depends_on if depends_on is not None else (existing.get("depends_on", []) if existing else [])
    resolved_retries = retries if retries is not None else (existing.get("retries", 0) if existing else 0)
    # Alte Position entfernen (falls vorhanden) - das aktualisierte Ticket wird unten ans
    # ENDE angehängt, damit die Listenreihenfolge selbst die Aktualisierungsreihenfolge
    # abbildet (siehe list_tickets()/_save_raw()).
    tickets = [t for t in tickets if t["id"] != ticket_id]
    result = Ticket(
        id=ticket_id, title=title, source=source, status=status,
        created_at=created_at, updated_at=_now(), detail=detail, project_slug=project_slug,
        priority=resolved_priority, estimate=resolved_estimate,
        epic=resolved_epic, depends_on=list(resolved_depends_on), retries=resolved_retries,
    )
    tickets.append(asdict(result))
    _save_raw(tickets)
    return result


def is_ticket_ready(ticket: Ticket, all_tickets: list[Ticket] | None = None) -> tuple[bool, list[str]]:
    """
    Prüft, ob ALLE Abhängigkeiten eines Tickets bereits status="done" erreicht haben - genau
    die Prüfung, die core/backlog_worker.py vor dem eigenständigen Aufgreifen eines
    "todo"-Tickets braucht, damit ein autonom arbeitendes Team nicht Ticket 2 einer Kette
    beginnt, bevor Ticket 1 fertig ist. Gibt (ready, blocking_ids) zurück - blocking_ids IMMER
    sichtbar statt eines reinen bool, damit ein Aufrufer den Grund loggen kann (dieselbe
    "niemals stumm überspringen"-Linie wie reason_skipped an anderer Stelle im Projekt).

    Ein depends_on-Eintrag ohne zugehöriges Ticket (z.B. Tippfehler in der ID, oder das Ticket
    wurde inzwischen durch MAX_TICKETS_KEPT verdrängt) gilt bewusst als NICHT erfüllt - lieber
    ein Ticket fälschlich blockiert liegen lassen (sichtbar im Backlog/Board) als eine
    tatsächlich noch offene Abhängigkeit stillschweigend zu ignorieren.
    """
    if not ticket.depends_on:
        return True, []
    by_id = {t.id: t for t in (all_tickets if all_tickets is not None else list_tickets())}
    blocking = [dep_id for dep_id in ticket.depends_on if by_id.get(dep_id, None) is None or by_id[dep_id].status != "done"]
    return not blocking, blocking


def count_by_status(status: str) -> int:
    """Anzahl Tickets in einer Spalte – Grundlage für die WIP-Limit-Warnung (siehe
    config.BACKLOG_WIP_LIMIT_IN_PROGRESS) ohne die komplette Liste beim Aufrufer neu zu filtern."""
    return sum(1 for t in _load_raw() if t.get("status") == status)
