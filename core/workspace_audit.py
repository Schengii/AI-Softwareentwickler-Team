"""
core/workspace_audit.py – Periodische Re-Verifikation ALLER Workspace-Projekte

Realer Fund bei einer Bestandsaufnahme des eigenen Teams: mehrere Workspace-Projekte trugen
`verification_ok: false` in ihrer `.ai_team_status.json`, ohne dass danach je wieder geprüft
wurde, ob der Zustand noch aktuell ist – ein Fix in einem SPÄTEREN Lauf (oder eine manuelle
Reparatur wie hier) macht das alte "false" nicht automatisch rückgängig, und ein Projekt, das
seit dem letzten Lauf nie wieder angefasst wurde, bekommt nie von selbst eine neue Verifikation.
Zusätzlich zeigte derselbe Rundgang zwei echte, unvollständig abgebrochen wirkende Projekte
(fehlender Einstiegspunkt bzw. nur eine `conftest.py` ohne echte Testdatei – siehe
core/verifier.py.ProjectVerifier._find_incomplete_project_reason()), die als "keine Tests
gefunden" bisher als bestanden durchgingen.

Ergänzt core/dependency_watch.py um denselben externen Poll-Zyklus-Ansatz (aufgerufen über
`python main.py --audit-workspace`, z.B. per Cron/Windows-Taskplaner) – EIN Aufruf = EIN Zyklus
über ALLE Workspace-Projekte, kein eingebauter Dauer-Scheduler. Anders als core/issue_watcher.py:
keine LLM-Aufrufe (reine Testausführung über die bereits vorhandene ProjectVerifier.run_tests()),
daher kostenlos und schnell.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

from core.adr import find_existing_near_duplicate_adr_pairs
from core.backlog_store import list_tickets, upsert_ticket
from core.notifier import notify_external
from core.verifier import ProjectVerifier
from core.workspace import WorkspaceManager

StatusCallback = Callable[[str], None]


@dataclass
class ProjectAuditResult:
    """Ergebnis EINES neu verifizierten Projekts in einem Zyklus."""
    project_name: str
    healthy: bool
    detail: str = ""


@dataclass
class WorkspaceAuditReport:
    """Ergebnis eines gesamten Audit-Zyklus (ein Aufruf von `python main.py --audit-workspace`)."""
    scanned_projects: int = 0
    results: list[ProjectAuditResult] = field(default_factory=list)


def _ticket_id(project_name: str) -> str:
    return f"audit-{project_name}"


async def run_workspace_audit_cycle(status_callback: StatusCallback | None = None) -> WorkspaceAuditReport:
    """
    Ein einzelner Audit-Durchlauf: führt ProjectVerifier.run_tests() erneut gegen JEDES
    vorhandene Workspace-Projekt aus – unabhängig davon, ob es gerade aktiv bearbeitet wird.
    Ein echter Fehlschlag (inkl. des neuen "Unvollständiges Projekt erkannt"-Falls) öffnet ein
    Backlog-Ticket, damit unbemerkt liegen gebliebene Projekte sichtbar werden, statt nur beim
    nächsten zufälligen `/load` desselben Projekts aufzufallen. Wird von außen wiederholt
    aufgerufen (Cron/Taskplaner) – KEINE eigene Schleife/Sleep hier, ein Aufruf = ein Zyklus.
    """
    report = WorkspaceAuditReport()
    workspace = WorkspaceManager()
    project_names = workspace.list_projects()

    for project_name in project_names:
        if status_callback:
            status_callback(f"🔍 Prüfe Verifikation erneut: {project_name}...")

        verifier = ProjectVerifier(workspace.get_project_dir(project_name))
        result = await asyncio.to_thread(verifier.run_tests)
        report.scanned_projects += 1

        healthy = result.passed
        ticket_id = _ticket_id(project_name)

        if not healthy:
            detail = (result.reason_skipped or f"{len(result.failures)} echte(r) Testfehler").strip()[:300]
            upsert_ticket(
                ticket_id=ticket_id, title=f"Verifikation fehlgeschlagen: {project_name}",
                source="workspace_audit", status="blocked", detail=detail, project_slug=project_name,
            )
            report.results.append(ProjectAuditResult(project_name=project_name, healthy=False, detail=detail))
            await asyncio.to_thread(
                notify_external, "Workspace-Audit: Verifikation fehlgeschlagen", f"{project_name}: {detail}",
            )
        else:
            # War das Ticket vorher "blocked" (Verifikation fehlgeschlagen), jetzt aber sauber
            # (z.B. inzwischen manuell oder in einem späteren Lauf gefixt) - auf "done" ziehen,
            # statt es für immer als "blocked" stehen zu lassen (dasselbe Prinzip wie
            # core/dependency_watch.py und core/merge_watcher.py.check_merged_tickets()).
            existing = next((t for t in list_tickets() if t.id == ticket_id), None)
            if existing and existing.status == "blocked":
                upsert_ticket(
                    ticket_id=ticket_id, title=existing.title, source="workspace_audit",
                    status="done", project_slug=project_name,
                )
            report.results.append(ProjectAuditResult(project_name=project_name, healthy=True))

        # Nahezu-Duplikat-ADRs (core/adr.py.find_existing_near_duplicate_adr_pairs) - unabhängig
        # vom Test-Ergebnis oben, da ein Projekt mit grünen Tests trotzdem eine doppelt
        # dokumentierte Architektur-Entscheidung enthalten kann. Eigene Ticket-ID, damit ein
        # bereits offenes "Verifikation fehlgeschlagen"-Ticket für dasselbe Projekt nicht
        # überschrieben wird.
        adr_ticket_id = f"{_ticket_id(project_name)}-adr-duplicate"
        duplicate_pairs = find_existing_near_duplicate_adr_pairs(workspace.get_project_dir(project_name))
        if duplicate_pairs:
            detail = "; ".join(
                f"ADR-{a.number:04d} ~ ADR-{b.number:04d} ('{a.title}')" for a, b in duplicate_pairs
            )[:300]
            upsert_ticket(
                ticket_id=adr_ticket_id, title=f"Nahezu-Duplikat-ADRs gefunden: {project_name}",
                source="workspace_audit", status="blocked", detail=detail, project_slug=project_name,
            )
        else:
            existing_adr_ticket = next((t for t in list_tickets() if t.id == adr_ticket_id), None)
            if existing_adr_ticket and existing_adr_ticket.status == "blocked":
                upsert_ticket(
                    ticket_id=adr_ticket_id, title=existing_adr_ticket.title, source="workspace_audit",
                    status="done", project_slug=project_name,
                )

    return report
