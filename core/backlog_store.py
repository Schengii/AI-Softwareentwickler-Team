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
import uuid
from dataclasses import asdict, dataclass
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
    BACKLOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Listenreihenfolge IST bereits Aktualisierungsreihenfolge (upsert_ticket hängt jedes
    # aktualisierte Ticket ans Ende an, siehe dort) - beim Kürzen also einfach die ÄLTESTEN
    # (vorne) fallen lassen. Bewusst KEINE erneute Sortierung nach updated_at hier: die
    # Zeitstempel-Auflösung ist Sekunden, mehrere Aktualisierungen in derselben Sekunde
    # ließen sich damit nicht mehr eindeutig ordnen.
    tickets = tickets[-MAX_TICKETS_KEPT:]
    BACKLOG_FILE.write_text(json.dumps(tickets, indent=2, ensure_ascii=False), encoding="utf-8")


def list_tickets(status: str | None = None) -> list[Ticket]:
    """Alle Tickets, zuletzt aktualisierte zuerst. `status=None` liefert alle Spalten."""
    tickets = [Ticket(**t) for t in _load_raw()]
    if status:
        tickets = [t for t in tickets if t.status == status]
    return list(reversed(tickets))  # Listenreihenfolge = Aktualisierungsreihenfolge, siehe _save_raw()


def new_ticket_id(source: str) -> str:
    return f"{source}-{uuid.uuid4().hex[:8]}"


def upsert_ticket(
    ticket_id: str, title: str, source: str, status: str, detail: str = "", project_slug: str = "",
) -> Ticket:
    """
    Legt ein Ticket an ODER aktualisiert ein bestehendes (anhand `ticket_id`) – ein einziger
    Aufruf für beide Fälle, damit Aufrufer nicht selbst prüfen müssen, ob das Ticket schon
    existiert (core/issue_watcher.py ruft z.B. beim Aufgreifen UND beim Abschluss desselben
    Issues auf). `created_at` bleibt beim ersten Anlegen fix, `updated_at` wird bei JEDEM
    Aufruf erneuert. `status` außerhalb von STATUSES wird nicht validiert (bewusst tolerant -
    ein unbekannter Status soll den aufrufenden Lauf nicht crashen, nur unpassend einsortiert
    im Board landen).
    """
    tickets = _load_raw()
    existing = next((t for t in tickets if t["id"] == ticket_id), None)
    created_at = existing["created_at"] if existing else _now()
    # Alte Position entfernen (falls vorhanden) - das aktualisierte Ticket wird unten ans
    # ENDE angehängt, damit die Listenreihenfolge selbst die Aktualisierungsreihenfolge
    # abbildet (siehe list_tickets()/_save_raw()).
    tickets = [t for t in tickets if t["id"] != ticket_id]
    result = Ticket(
        id=ticket_id, title=title, source=source, status=status,
        created_at=created_at, updated_at=_now(), detail=detail, project_slug=project_slug,
    )
    tickets.append(asdict(result))
    _save_raw(tickets)
    return result
