"""
core/red_project_repair.py – Rote Projekte automatisch zur Nachbesserung einplanen

Analyse 2026-09-15: alle 8 roten Workspace-Projekte wurden genau einmal ausgeführt und blieben
danach liegen. Ein echtes Team lässt einen roten Build nicht über Nacht stehen.

`queue_red_projects()` legt für jedes Projekt, dessen letzter Lauf nicht verifiziert wurde und für
das noch kein offenes Nachbesserungs-Ticket existiert, ein `recurring-failure-<slug>`-Ticket an.
Der Backlog-Worker (`--work-backlog`) greift es über seinen Governance-Retry-Pool auf und schickt
genau den bekannten Befund als Fix-Auftrag – keine Neuentwicklung, begrenzt durch
MAX_GOVERNANCE_TICKET_RETRIES.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from config import MAX_GOVERNANCE_TICKET_RETRIES
from core.backlog_store import get_ticket, upsert_ticket
from core.definition_of_done import read_definition_of_done
from core.project_status import read_full_detail, read_status

logger = logging.getLogger(__name__)

REPAIR_TICKET_PREFIX = "recurring-failure-"
# "test-regression-" ergänzt (Token-/Erfolgsquoten-Analyse 2026-09-17): ohne diesen Eintrag hätte
# ein Projekt mit offenem test-regression-<slug>-Ticket (core.backlog_worker._GOVERNANCE_RETRY_
# PREFIXES kümmert sich bereits darum) HIER zusätzlich ein redundantes recurring-failure-<slug>-
# Ticket für denselben roten Stand bekommen - zwei parallele automatische Nachbesserungsversuche
# für dasselbe Projekt statt eines koordinierten.
_RELATED_PREFIXES = ("recurring-failure-", "unresolved-governance-critical-", "audit-", "recurring-lint-", "test-regression-")
MAX_DETAIL_CHARS = 3000


@dataclass
class RepairQueueReport:
    queued: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)

    def format_summary(self) -> str:
        lines = [f"🔁 Rote Projekte: {len(self.queued)} zur Nachbesserung eingeplant"]
        lines += [f"  • {slug}" for slug in self.queued]
        lines += [f"  - {slug}: {reason}" for slug, reason in sorted(self.skipped.items())]
        return "\n".join(lines)


def _existing_repair_state(slug: str) -> str | None:
    """Grund, warum kein neues Ticket nötig ist – None, wenn eingeplant werden darf."""
    for prefix in _RELATED_PREFIXES:
        ticket = get_ticket(f"{prefix}{slug}")
        if ticket is None:
            continue
        if ticket.status in ("todo", "in_progress", "review"):
            return f"Ticket {ticket.id} ist bereits '{ticket.status}'"
        if ticket.status == "blocked":
            if ticket.retries >= MAX_GOVERNANCE_TICKET_RETRIES:
                return f"Ticket {ticket.id}: automatische Versuche ausgeschöpft – menschliche Prüfung nötig"
            return f"Ticket {ticket.id} wartet bereits auf den Backlog-Worker"
    return None


def queue_red_projects(workspace_dir: str | Path | None = None, max_new: int = 3) -> RepairQueueReport:
    from core.workspace import WorkspaceManager

    manager = WorkspaceManager(base_workspace_dir=str(workspace_dir)) if workspace_dir else WorkspaceManager()
    report = RepairQueueReport()
    for slug in manager.list_projects():
        project_dir = str(Path(manager.base_dir) / slug)
        history = read_status(project_dir)
        if not history:
            continue
        last = history[0]
        if last.get("cancelled"):
            continue
        # Realer Fund (nexus_mesh/aegisflow, 2026-09-18): `verification_ok` und die maschinen-
        # lesbare Definition of Done (.ai_team_dod.json, core/definition_of_done.py) können
        # auseinanderlaufen - z.B. wenn der Runtime-Smoke-Test nie zu Ende lief
        # (verification_ok=True, obwohl die DoD `app_starts` mit "nicht gemessen" als Blocker
        # führt). `verification_ok` sieht einen NIE aufgezeichneten Check nie als Fehlschlag,
        # die DoD dagegen schon. Ohne diesen Zusatz-Check ignorierte `queue_red_projects()` genau
        # solche Projekte für immer, weil es ausschließlich `verification_ok` kannte.
        dod = read_definition_of_done(project_dir)
        dod_blocking = list(dod.get("blocking") or []) if isinstance(dod, dict) else []
        if last.get("verification_ok") and not dod_blocking:
            continue
        reason = _existing_repair_state(slug)
        if reason:
            report.skipped[slug] = reason
            continue
        if len(report.queued) >= max_new:
            report.skipped[slug] = "Limit pro Durchlauf erreicht"
            continue
        detail = read_full_detail(project_dir, last)[:MAX_DETAIL_CHARS]
        if dod_blocking:
            detail = f"Definition of Done blockiert an: {', '.join(dod_blocking)}\n\n{detail}"
        budget_note = " Der letzte Lauf endete am Token-Budget - führe zuerst die Verifikation aus." if last.get("budget_aborted") else ""
        try:
            upsert_ticket(
                ticket_id=f"{REPAIR_TICKET_PREFIX}{slug}",
                title=f"Nicht behobener Verifikations-Fehler: {slug}",
                source="orchestrator",
                status="blocked",
                project_slug=slug,
                detail=(
                    "Automatisch eingeplante Nachbesserung (core/red_project_repair.py): Behebe die verbleibenden "
                    f"Befunde dieses bestehenden Projekts, keine Neuentwicklung.{budget_note}\n\n{detail}"
                ),
            )
        except Exception as e:  # noqa: BLE001 - ein defektes Backlog darf die übrigen Projekte nicht blockieren
            logger.warning("Nachbesserungs-Ticket für %s nicht anlegbar: %r", slug, e)
            report.skipped[slug] = f"Ticket konnte nicht angelegt werden: {e}"
            continue
        report.queued.append(slug)
    return report
