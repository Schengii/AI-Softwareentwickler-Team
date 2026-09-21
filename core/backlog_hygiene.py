"""
core/backlog_hygiene.py – Hält das Backlog ehrlich: hängende, doppelte und bereits behobene Tickets

Backlog-Analyse 2026-09-15: 10 Tickets hingen seit Tagen auf "in_progress", dreimal dasselbe
"Goal: Baue Auth-API" lag in "review", und ein Root-Cause-Ticket blieb "blocked", obwohl der Fix
längst committet war. Ohne Hygiene schließt sich der Lernkreislauf nie sichtbar.

Regeln (alle deterministisch, kein LLM):
1. Hängende "in_progress"-Tickets (> STALE_IN_PROGRESS_HOURS) → vorheriger Status. Tickets aus
   interaktiven CLI-Läufen werden dabei "blocked" statt "todo", damit der Backlog-Worker nicht
   ungefragt ein komplettes Großprojekt neu startet.
2. Dubletten (gleicher Projekt-Slug + gleicher normalisierter Titel, offen) → nur das neueste
   bleibt offen, ältere werden "cancelled".
3. Tickets, die eine Commit-Nachricht per `Closes: <id>` (auch Fixes:/Resolves:) nennt, → "done".
4. Offene Tickets, deren `project_slug` auf ein Workspace-Projekt zeigt, das es nicht mehr gibt,
   → "cancelled". Nur für projektgebundene Quellen (siehe `_PROJECT_BOUND_SOURCES`), denn ein
   frisches "cli"/"dashboard"-Ticket beschreibt naturgemäß ein noch nicht existierendes Projekt.
5. Offene Tickets, die seit über STALE_OPEN_DAYS Tagen offen sind (gemessen an `created_at`),
   → "cancelled".

Backlog-Analyse 2026-09-16 (Anlass für Regel 4 und 5): 54 der 200 Tickets waren offen, 45 davon
mit `retries=0` – also nie erneut aufgegriffen, das älteste zwei Wochen alt; 25 zeigten auf
Projekte, die im Workspace längst nicht mehr existieren. Der Backlog lief damit nie leer, und
zwischen "wartet noch auf Bearbeitung" und "wird nie mehr bearbeitet" war kein Unterschied zu
sehen. "cancelled" statt Löschen, damit Ticket und Begründung nachlesbar bleiben – dieselbe
Konvention wie bei den Dubletten aus Regel 2.
"""

from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from config import BASE_DIR, WORKSPACE_DIR
from core.backlog_store import Ticket, list_tickets, upsert_ticket

logger = logging.getLogger(__name__)

OPEN_STATUSES = frozenset({"todo", "in_progress", "review", "blocked"})
STALE_IN_PROGRESS_HOURS = 3.0
GIT_LOG_MAX_COMMITS = 300

# Ab wann ein offenes Ticket als endgültig liegengeblieben gilt. Bewusst deutlich großzügiger als
# STALE_IN_PROGRESS_HOURS: ein "todo" darf ruhig Tage auf einen Poll-Zyklus warten, zwei Wochen
# ohne jede Statusänderung sind aber keine Warteschlange mehr, sondern ein Friedhof.
STALE_OPEN_DAYS = 14.0

# Quellen, deren Tickets sich auf ein BEREITS BESTEHENDES Workspace-Projekt beziehen (Befunde aus
# Verifikation, Governance und Workspace-Audit). Nur bei diesen ist ein fehlendes Projekt-
# verzeichnis ein Beweis dafür, dass das Ticket gegenstandslos ist. "cli"/"dashboard"/"issue"
# beauftragen dagegen oft etwas Neues, "pr_review" trägt einen Branch-Namen im `project_slug`.
_PROJECT_BOUND_SOURCES = frozenset({"orchestrator", "workspace_audit"})


@dataclass
class HygieneReport:
    recovered: list[str] = field(default_factory=list)
    duplicates_cancelled: list[str] = field(default_factory=list)
    closed_by_commit: list[str] = field(default_factory=list)
    orphans_cancelled: list[str] = field(default_factory=list)
    stale_open_cancelled: list[str] = field(default_factory=list)

    @property
    def changed(self) -> int:
        return (len(self.recovered) + len(self.duplicates_cancelled) + len(self.closed_by_commit)
                + len(self.orphans_cancelled) + len(self.stale_open_cancelled))

    def format_summary(self) -> str:
        lines = ["🧹 Backlog-Hygiene:"]
        lines.append(f"  - {len(self.recovered)} hängende 'in_progress'-Tickets zurückgesetzt")
        lines.append(f"  - {len(self.duplicates_cancelled)} Dubletten geschlossen")
        lines.append(f"  - {len(self.closed_by_commit)} Tickets per Commit-Referenz als erledigt markiert")
        lines.append(f"  - {len(self.orphans_cancelled)} Tickets ohne existierendes Projekt geschlossen")
        lines.append(f"  - {len(self.stale_open_cancelled)} dauerhaft liegengebliebene Tickets geschlossen")
        for label, ids in (("zurückgesetzt", self.recovered), ("Dublette", self.duplicates_cancelled),
                           ("per Commit erledigt", self.closed_by_commit),
                           ("Projekt existiert nicht mehr", self.orphans_cancelled),
                           ("liegengeblieben", self.stale_open_cancelled)):
            lines.extend(f"    • {tid} ({label})" for tid in ids)
        return "\n".join(lines)


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", title.lower())).strip()[:80]


def _parse_ts(value: str) -> datetime | None:
    try:
        ts = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def _update_status(t: Ticket, status: str, detail: str | None = None, *, blocked_reason: str | None = None) -> None:
    upsert_ticket(
        ticket_id=t.id, title=t.title, source=t.source, status=status,
        detail=t.detail if detail is None else detail[:1200],
        blocked_reason=blocked_reason,
    )


def recover_stale_in_progress(tickets: list[Ticket], now: datetime | None = None) -> list[str]:
    now = now or datetime.now(UTC)
    recovered: list[str] = []
    for t in tickets:
        if t.status != "in_progress":
            continue
        updated = _parse_ts(t.updated_at)
        if updated is None or (now - updated).total_seconds() < STALE_IN_PROGRESS_HOURS * 3600:
            continue
        # Nur Governance-/Audit-Retry-Tickets dürfen automatisch erneut aufgegriffen werden.
        from core.backlog_worker import _GOVERNANCE_RETRY_PREFIXES
        is_governance_retry = t.id.startswith(_GOVERNANCE_RETRY_PREFIXES)
        target = "blocked" if (t.source == "cli" or is_governance_retry) else "todo"
        note = f"[Hygiene] Seit über {STALE_IN_PROGRESS_HOURS:g} h ohne Fortschritt – Status auf '{target}' gesetzt."
        # P1-3 (ROADMAP_TEMP.md): ein "cli"-Ticket, das HIER "blocked" wird, ist rein operationell
        # liegengeblieben (nie ein Poll-Zyklus lief) - inhaltlich unterscheidet es sich in NICHTS
        # von einem frischen "todo". blocked_reason="stale" markiert genau das maschinenlesbar,
        # damit core/backlog_worker.py es gefahrlos wie "todo" behandeln kann, OHNE das
        # bestehende _GOVERNANCE_RETRY_PREFIXES-Sicherheitsnetz für bewusst blockierte
        # Governance-Tickets aufzuweichen (die bekommen hier weiterhin KEINEN blocked_reason,
        # ihre Blockade ist inhaltlich, nicht operationell).
        _update_status(t, target, f"{note}\n{t.detail}".strip(),
                       blocked_reason="stale" if (target == "blocked" and not is_governance_retry) else None)
        recovered.append(t.id)
    return recovered


def cancel_duplicates(tickets: list[Ticket]) -> list[str]:
    groups: dict[tuple[str, str], list[Ticket]] = {}
    for t in tickets:
        if t.status in OPEN_STATUSES:
            groups.setdefault((t.project_slug, _normalize_title(t.title)), []).append(t)
    cancelled: list[str] = []
    for group in groups.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda t: _parse_ts(t.updated_at) or datetime.min.replace(tzinfo=UTC))
        newest = group[-1]
        for t in group[:-1]:
            _update_status(t, "cancelled", f"[Hygiene] Dublette von {newest.id}.\n{t.detail}".strip())
            cancelled.append(t.id)
    return cancelled


def _canonical_slug_key(name: str) -> str:
    """
    Vergleichsschlüssel wie `core/workspace.py.WorkspaceManager._canonical_key()`: lowercased und
    ohne jedes Nicht-Alphanumerische, damit "WebhookShield", "webhook_shield" und "Webhook Shield"
    denselben Ordner treffen. Absichtlich hier dupliziert statt die private Methode dort zu
    benutzen - und absichtlich NICHT `get_project_dir()`, denn das LEGT das Verzeichnis an
    (mkdir am Ende) und würde damit jede Existenzprüfung selbst wahr machen.
    """
    return re.sub(r"[^a-z0-9]", "", name.lower())


def workspace_project_exists(slug: str, workspace_dir: str | Path | None = None) -> bool:
    """
    Nur lesende Prüfung, ob zu `slug` noch ein Projektverzeichnis existiert. Ist der Workspace
    selbst nicht lesbar, lautet die Antwort bewusst True: ohne verlässliche Auskunft darf kein
    Ticket geschlossen werden (ein vorübergehend nicht erreichbares Laufwerk würde sonst den
    halben Backlog abräumen).
    """
    base = Path(workspace_dir) if workspace_dir else Path(WORKSPACE_DIR)
    try:
        existing = [d.name for d in base.iterdir() if d.is_dir()]
    except OSError:
        return True
    key = _canonical_slug_key(slug)
    return any(_canonical_slug_key(name) == key for name in existing)


def cancel_orphaned_project_tickets(tickets: list[Ticket], workspace_dir: str | Path | None = None) -> list[str]:
    """
    Schließt offene Tickets projektgebundener Quellen, deren Projekt es im Workspace nicht mehr
    gibt (Regel 4). Ein Befund zu gelöschtem Code ist nicht mehr behebbar - solche Tickets
    blockieren nur die Sicht auf die echte Arbeit und lassen den Backlog nie leerlaufen.
    """
    cancelled: list[str] = []
    for t in tickets:
        if t.status not in OPEN_STATUSES or not t.project_slug:
            continue
        if t.source not in _PROJECT_BOUND_SOURCES:
            continue
        if workspace_project_exists(t.project_slug, workspace_dir):
            continue
        note = f"[Hygiene] Projekt '{t.project_slug}' existiert im Workspace nicht mehr - Ticket gegenstandslos."
        _update_status(t, "cancelled", f"{note}\n{t.detail}".strip())
        cancelled.append(t.id)
    return cancelled


def cancel_stale_open_tickets(tickets: list[Ticket], now: datetime | None = None,
                              skip_ids: Iterable[str] = ()) -> list[str]:
    """
    Schließt offene Tickets, die seit über STALE_OPEN_DAYS Tagen unverändert liegen (Regel 5).

    "in_progress" ist hier ausgenommen: dafür ist `recover_stale_in_progress()` zuständig, das
    solche Tickets wieder aufgreifbar macht statt sie zu schließen - ein abgestürzter Lauf ist ein
    Wiederholungs-, kein Verwerfungsfall. `skip_ids` nimmt genau diese soeben wieder aufgegriffenen
    Tickets aus: sonst hätte `run_backlog_hygiene()` ein altes, abgestürztes Ticket im selben
    Durchlauf erst auf "todo" gesetzt und direkt danach geschlossen - der Worker bekäme nie eine
    Chance darauf.

    Gemessen wird bewusst an `created_at`, nicht an `updated_at`: ein Status- oder Hygiene-Kommentar
    erneuert `updated_at`, ist aber KEIN Fortschritt an der Sache. Am echten Backlog (2026-09-16)
    hätte die Variante über `updated_at` deshalb null Tickets gefunden, obwohl das älteste offene
    Ticket seit zwei Wochen unbearbeitet lag - genau der Zustand, der abgeräumt werden soll.
    """
    now = now or datetime.now(UTC)
    geschont = set(skip_ids)
    cancelled: list[str] = []
    for t in tickets:
        if t.status not in OPEN_STATUSES or t.status == "in_progress" or t.id in geschont:
            continue
        created = _parse_ts(t.created_at)
        if created is None or (now - created).total_seconds() < STALE_OPEN_DAYS * 86400:
            continue
        tage = (now - created).total_seconds() / 86400
        note = (f"[Hygiene] Seit {tage:.0f} Tagen offen ohne Abschluss (Status '{t.status}', "
                f"{t.retries} automatische Versuche) - geschlossen. Bei Bedarf neu einplanen.")
        _update_status(t, "cancelled", f"{note}\n{t.detail}".strip())
        cancelled.append(t.id)
    return cancelled


def read_commit_messages(max_commits: int = GIT_LOG_MAX_COMMITS) -> str:
    try:
        proc = subprocess.run(
            ["git", "log", f"-{max_commits}", "--format=%B"],
            cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("git log für Backlog-Hygiene nicht lesbar: %r", e)
        return ""
    return proc.stdout if proc.returncode == 0 else ""


_CLOSE_LINE_RE = re.compile(r"^[ \t>*-]*(?:closes|fixes|resolves)[ \t]*:[ \t]*(.+)$", re.IGNORECASE | re.MULTILINE)


def referenced_ticket_ids(commit_messages: str) -> set[str]:
    """Ticket-IDs aus expliziten Zeilen wie `Closes: audit-foo, root-cause-bar`.

    Bewusst nur mit Schlüsselwort: Commit-Nachrichten erwähnen Ticket-IDs oft als bloßen Kontext
    ("Fund aus Ticket recurring-failure-x"), ohne dass das Ticket damit erledigt ist.
    """
    ids: set[str] = set()
    for match in _CLOSE_LINE_RE.finditer(commit_messages or ""):
        ids.update(token.strip("`'\".;") for token in re.split(r"[,\s]+", match.group(1)) if token.strip())
    return ids


def close_tickets_referenced_in_commits(tickets: list[Ticket], commit_messages: str) -> list[str]:
    referenced = referenced_ticket_ids(commit_messages)
    if not referenced:
        return []
    closed: list[str] = []
    for t in tickets:
        if t.status in OPEN_STATUSES and t.id in referenced:
            _update_status(t, "done", f"[Hygiene] Per Commit (Closes:) als erledigt markiert.\n{t.detail}".strip())
            closed.append(t.id)
    return closed


def run_backlog_hygiene(commit_messages: str | None = None, now: datetime | None = None,
                        workspace_dir: str | Path | None = None) -> HygieneReport:
    """Führt alle Hygiene-Regeln aus. `commit_messages`/`workspace_dir` sind für Tests injizierbar."""
    report = HygieneReport()
    report.closed_by_commit = close_tickets_referenced_in_commits(
        list_tickets(), read_commit_messages() if commit_messages is None else commit_messages,
    )
    report.recovered = recover_stale_in_progress(list_tickets(), now=now)
    report.duplicates_cancelled = cancel_duplicates(list_tickets())
    report.orphans_cancelled = cancel_orphaned_project_tickets(list_tickets(), workspace_dir=workspace_dir)
    # Zuletzt: die beiden Regeln davor können ein Ticket gerade erst angefasst haben, dessen
    # `updated_at` damit frisch ist - es soll nicht im selben Durchlauf doppelt kommentiert werden.
    report.stale_open_cancelled = cancel_stale_open_tickets(
        list_tickets(), now=now, skip_ids=report.recovered)
    return report
