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
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime

from config import BASE_DIR
from core.backlog_store import Ticket, list_tickets, upsert_ticket

logger = logging.getLogger(__name__)

OPEN_STATUSES = frozenset({"todo", "in_progress", "review", "blocked"})
STALE_IN_PROGRESS_HOURS = 3.0
GIT_LOG_MAX_COMMITS = 300


@dataclass
class HygieneReport:
    recovered: list[str] = field(default_factory=list)
    duplicates_cancelled: list[str] = field(default_factory=list)
    closed_by_commit: list[str] = field(default_factory=list)

    @property
    def changed(self) -> int:
        return len(self.recovered) + len(self.duplicates_cancelled) + len(self.closed_by_commit)

    def format_summary(self) -> str:
        lines = ["🧹 Backlog-Hygiene:"]
        lines.append(f"  - {len(self.recovered)} hängende 'in_progress'-Tickets zurückgesetzt")
        lines.append(f"  - {len(self.duplicates_cancelled)} Dubletten geschlossen")
        lines.append(f"  - {len(self.closed_by_commit)} Tickets per Commit-Referenz als erledigt markiert")
        for label, ids in (("zurückgesetzt", self.recovered), ("Dublette", self.duplicates_cancelled),
                           ("per Commit erledigt", self.closed_by_commit)):
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


def _update_status(t: Ticket, status: str, detail: str | None = None) -> None:
    upsert_ticket(
        ticket_id=t.id, title=t.title, source=t.source, status=status,
        detail=t.detail if detail is None else detail[:1200],
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
        target = "blocked" if (t.source == "cli" or t.id.startswith(_GOVERNANCE_RETRY_PREFIXES)) else "todo"
        note = f"[Hygiene] Seit über {STALE_IN_PROGRESS_HOURS:g} h ohne Fortschritt – Status auf '{target}' gesetzt."
        _update_status(t, target, f"{note}\n{t.detail}".strip())
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


def run_backlog_hygiene(commit_messages: str | None = None, now: datetime | None = None) -> HygieneReport:
    """Führt alle Hygiene-Regeln aus. `commit_messages` ist für Tests injizierbar."""
    report = HygieneReport()
    report.closed_by_commit = close_tickets_referenced_in_commits(
        list_tickets(), read_commit_messages() if commit_messages is None else commit_messages,
    )
    report.recovered = recover_stale_in_progress(list_tickets(), now=now)
    report.duplicates_cancelled = cancel_duplicates(list_tickets())
    return report
