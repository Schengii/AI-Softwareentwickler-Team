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
# P6-4 (ROADMAP_TEMP.md): memory/backlog.json lag bei 200 Tickets/143 KB, davon 19 "cancelled" +
# 96 "done" - über die Hälfte des aktiven Boards war längst abgeschlossene Arbeit, die
# is_ticket_ready()/list_tickets() trotzdem bei jedem Aufruf mitschleppen. archive_completed_
# tickets() unten verschiebt sie hierher, statt sie zu löschen - die Historie bleibt erhalten,
# nur außerhalb des aktiven Arbeitszustands.
BACKLOG_ARCHIVE_FILE = Path(BASE_DIR) / "memory" / "backlog_archive.json"
# Erst nach dieser Ruhezeit seit dem letzten Update archiviert - ein soeben erst geschlossenes
# Ticket bleibt eine Weile im aktiven Board sichtbar (z.B. für ein Dashboard-"kürzlich
# erledigt"), statt sofort im nächsten Poll-Zyklus zu verschwinden.
ARCHIVE_COMPLETED_AFTER_DAYS = 14

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
    # Team-Optimierung (P1-3, ROADMAP_TEMP.md, realer Fund 2026-09-20): 9 von 17 "blocked"-
    # Tickets waren nie inhaltlich blockiert - core/backlog_hygiene.py.recover_stale_in_progress()
    # setzt "cli"-Tickets, die einfach nur nie in einem Poll-Zyklus aufgegriffen wurden, auf
    # "blocked" statt "todo" (bewusst so, damit der Backlog-Worker kein komplettes Großprojekt
    # ungefragt neu startet - siehe dort). Ohne diese Unterscheidung sah ein solches Ticket im
    # Backlog GENAUSO aus wie ein Ticket, das eine Fix-Schleife nachweislich nicht lösen konnte
    # (core/backlog_worker.py._GOVERNANCE_RETRY_PREFIXES) - beide blieben für immer liegen, weil
    # der Worker "blocked" ohne bekanntes Präfix grundsätzlich NICHT anfasst (bewusst, ein Mensch
    # könnte "blocked" gesetzt haben). "stale" macht sichtbar, dass die Blockade rein
    # operationell ist (nie ein echter Versuch) und der Worker sie deshalb gefahrlos wie ein
    # "todo" behandeln darf, ohne dass ein generisches "jedes blocked-Ticket erneut versuchen"
    # auch bewusst blockierte Tickets aufgreift.
    blocked_reason: str = ""  # "" | "stale" (nur aussagekräftig, solange status == "blocked")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _load_raw() -> list[dict]:
    """
    Realer Fund (Testflake beim Verifizieren des _save_raw()-Torn-Read-Fixes, siehe dort):
    os.replace() dort ist zwar atomar, aber auf Windows kann ein GLEICHZEITIGER read_text()
    hier mit einem transienten PermissionError scheitern, wenn genau in diesem Moment der
    Rename der Zieldatei passiert (kurze Sharing-Violation, kein echter Dauerzustand - exakt
    dasselbe Phänomen wie beim Writer, nur diesmal auf der Leseseite). Das ursprüngliche
    `except (..., OSError): return []` fing diesen transienten Fehler mit ab und lieferte
    STILLSCHWEIGEND eine leere Liste zurück - derselbe "keine Tickets vorgetäuscht"-Bug wie
    beim torn read, nur über einen anderen Auslöser. Kurzer Retry für PermissionError
    unterscheidet das vom echten "Datei fehlt"-Fall (der weiterhin sofort [] liefert) und vom
    echten JSONDecodeError (korrupte Datei, kein Race - kein Retry sinnvoll).
    """
    if not BACKLOG_FILE.exists():
        return []
    max_attempts = 10
    for attempt in range(max_attempts):
        try:
            return json.loads(BACKLOG_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        except PermissionError:
            if attempt == max_attempts - 1:
                return []
            time.sleep(0.05 * (attempt + 1))
        except OSError:
            return []
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
    ticket_id: str, title: str, source: str, status: str, detail: str = "", project_slug: str | None = None,
    priority: int | None = None, estimate: str | None = None,
    epic: str | None = None, depends_on: list[str] | None = None,
    retries: int | None = None, blocked_reason: str | None = None,
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

    `blocked_reason` folgt DEMSELBEN None-Sentinel wie priority/estimate/epic/retries, ist aber
    zusätzlich an `status` gekoppelt: verlässt das Ticket "blocked" (jeder andere `status`-Wert),
    wird `blocked_reason` IMMER auf "" zurückgesetzt, unabhängig vom übergebenen Wert - ein
    "stale"-Vermerk an einem inzwischen "todo"/"in_progress"/"done"-Ticket wäre irreführend
    (core/backlog_worker.py würde ihn zwar ohnehin nicht mehr lesen, da er nur bei
    status=="blocked" ausgewertet wird, aber ein Board/Dashboard könnte ihn missverständlich
    anzeigen).
    """
    tickets = _load_raw()
    existing = next((t for t in tickets if t["id"] == ticket_id), None)
    created_at = existing["created_at"] if existing else _now()
    # Bugfix (Team-Optimierung, real beobachtet im mockforge-Governance-Retry): project_slug
    # hatte bisher einen blanken Default ("", KEIN Sentinel wie priority/estimate/epic/retries
    # unten) - core/backlog_worker.py._process_single_ticket() aktualisiert denselben Ticket
    # aber MEHRFACH über seinen Lebenszyklus hinweg (Aufgreifen, Retry-Zähler, finaler Status),
    # ohne project_slug bei jedem Aufruf erneut mitzugeben. Der finale Status-Update-Aufruf
    # (nach dem Orchestrator-Lauf) überschrieb project_slug dadurch STILLSCHWEIGEND mit "" -
    # beim nächsten automatischen Retry desselben Governance-Tickets (core/backlog_worker.py.
    # _governance_retry_pool()) fand `if ticket.project_slug:` dadurch nichts mehr, der
    # Orchestrator legte statt einer Fortsetzung des BESTEHENDEN Projekts ein komplett neues,
    # leeres Projekt an. Jetzt derselbe Sentinel wie bei priority/estimate/epic/retries: None
    # (Standard) übernimmt den vorhandenen Wert unverändert, nur ein EXPLIZITES "" löscht ihn.
    resolved_project_slug = project_slug if project_slug is not None else (existing.get("project_slug", "") if existing else "")
    resolved_priority = priority if priority is not None else (existing.get("priority", 2) if existing else 2)
    resolved_estimate = estimate if estimate is not None else (existing.get("estimate", "") if existing else "")
    resolved_epic = epic if epic is not None else (existing.get("epic", "") if existing else "")
    resolved_depends_on = depends_on if depends_on is not None else (existing.get("depends_on", []) if existing else [])
    resolved_retries = retries if retries is not None else (existing.get("retries", 0) if existing else 0)
    if status != "blocked":
        resolved_blocked_reason = ""
    else:
        resolved_blocked_reason = (
            blocked_reason if blocked_reason is not None else (existing.get("blocked_reason", "") if existing else "")
        )
    # Alte Position entfernen (falls vorhanden) - das aktualisierte Ticket wird unten ans
    # ENDE angehängt, damit die Listenreihenfolge selbst die Aktualisierungsreihenfolge
    # abbildet (siehe list_tickets()/_save_raw()).
    tickets = [t for t in tickets if t["id"] != ticket_id]
    result = Ticket(
        id=ticket_id, title=title, source=source, status=status,
        created_at=created_at, updated_at=_now(), detail=detail, project_slug=resolved_project_slug,
        priority=resolved_priority, estimate=resolved_estimate,
        epic=resolved_epic, depends_on=list(resolved_depends_on), retries=resolved_retries,
        blocked_reason=resolved_blocked_reason,
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


def prune_orphaned_tickets(existing_project_slugs: set[str] | None = None) -> list[str]:
    """
    Nutzerauftrag: automatisches Pruning für verwaiste Tickets gelöschter Projekte. Ein Ticket
    mit gesetztem `project_slug` (z.B. "audit-<slug>", "unresolved-governance-critical-<slug>",
    "recurring-failure-<slug>") verweist auf ein konkretes `workspace/<slug>`-Projekt - wird
    dieses Projekt gelöscht (manuell oder über core/project_cleaner_agent.py aufgeräumt), bleibt
    das Ticket sonst für IMMER im Backlog liegen: `is_ticket_ready()` behandelt eine fehlende
    Abhängigkeit bereits bewusst als "blockiert statt stillschweigend ignoriert" (siehe dort),
    aber es gibt bisher KEINE Prüfung, ob das PROJEKT selbst, auf das ein Ticket sich bezieht,
    überhaupt noch existiert - ein solches Ticket kann nie mehr sinnvoll bearbeitet werden (kein
    Verzeichnis, das ein Fix-Auftrag betreffen könnte) und blockiert nur weiter Platz im
    MAX_TICKETS_KEPT-Fenster.

    Tickets OHNE project_slug (z.B. teamweite Meta-Tickets wie "unused-agent-<id>" oder
    "team-verification-trend", siehe core/optimization_advisor.py/core/workspace_audit.py)
    gelten bewusst NIE als verwaist - sie beziehen sich nicht auf ein einzelnes Workspace-
    Projekt und dürfen nicht versehentlich mitgelöscht werden.

    `existing_project_slugs`: optional injizierbar für Tests (vermeidet eine echte
    WorkspaceManager-Instanz/echtes Dateisystem) - `None` (Standard) ermittelt die tatsächlich
    vorhandenen Workspace-Projekte selbst. Gibt die IDs der entfernten Tickets zurück (leer,
    wenn nichts zu tun war - dann wird auch NICHT geschrieben, um unnötiges `_save_raw()` bei
    jedem Aufruf ohne echte Änderung zu vermeiden).
    """
    if existing_project_slugs is None:
        from core.workspace import WorkspaceManager
        existing_project_slugs = set(WorkspaceManager().list_projects())

    tickets = _load_raw()
    kept: list[dict] = []
    pruned_ids: list[str] = []
    for t in tickets:
        slug = t.get("project_slug", "")
        if slug and slug not in existing_project_slugs:
            pruned_ids.append(t["id"])
            continue
        kept.append(t)

    if pruned_ids:
        _save_raw(kept)
    return pruned_ids


def _load_archive() -> list[dict]:
    if not BACKLOG_ARCHIVE_FILE.exists():
        return []
    try:
        data = json.loads(BACKLOG_ARCHIVE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save_archive(tickets: list[dict]) -> None:
    BACKLOG_ARCHIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = BACKLOG_ARCHIVE_FILE.with_suffix(f"{BACKLOG_ARCHIVE_FILE.suffix}.tmp-{os.getpid()}-{threading.get_ident()}")
    try:
        tmp_path.write_text(json.dumps(tickets, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, BACKLOG_ARCHIVE_FILE)
    except OSError:
        tmp_path.unlink(missing_ok=True)


def archive_completed_tickets(
    older_than_days: float = ARCHIVE_COMPLETED_AFTER_DAYS, now: datetime | None = None,
) -> list[str]:
    """Verschiebt "done"/"cancelled"-Tickets, deren letzte Aktualisierung mehr als
    `older_than_days` zurückliegt, nach `memory/backlog_archive.json` - hält das aktive Board
    (`memory/backlog.json`) klein, OHNE die Historie zu verlieren (die archivierten Tickets
    bleiben vollständig erhalten, nur außerhalb von `list_tickets()`). Gibt die IDs der
    archivierten Tickets zurück (leer, wenn nichts zu tun war - dann wird auch nichts
    geschrieben)."""
    now = now or datetime.now(UTC)
    tickets = _load_raw()
    kept: list[dict] = []
    archived: list[dict] = []
    for t in tickets:
        if t.get("status") not in ("done", "cancelled"):
            kept.append(t)
            continue
        try:
            updated = datetime.fromisoformat(str(t.get("updated_at", "")))
        except ValueError:
            kept.append(t)
            continue
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        age_days = (now - updated).total_seconds() / 86400
        if age_days < older_than_days:
            kept.append(t)
            continue
        archived.append(t)

    if not archived:
        return []
    _save_archive(_load_archive() + archived)
    _save_raw(kept)
    return [t["id"] for t in archived]
