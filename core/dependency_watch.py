"""
core/dependency_watch.py – Periodischer Vulnerability-Scan über ALLE Workspace-Projekte

Realer Fund bei einer Bestandsaufnahme des eigenen Teams:
core/verifier.py.check_dependency_vulnerabilities() lief bisher NUR als Teil eines AKTIVEN
Orchestrator-Laufs an genau diesem Projekt – eine erst NACH Projektabschluss öffentlich
gewordene CVE in einer bereits gepinnten Abhängigkeit eines seither unberührten
Workspace-Projekts blieb unentdeckt, bis (falls überhaupt) irgendwann ein neuer Lauf gegen
genau dieses Projekt gestartet wurde. Ein echtes Team hat einen Dependabot-artigen Mechanismus,
der unabhängig von aktiver Entwicklung nach bekannten Schwachstellen sucht.

Ergänzt core/issue_watcher.py um denselben externen Poll-Zyklus-Ansatz (aufgerufen über
`python main.py --check-dependencies`, z.B. per Cron/Windows-Taskplaner) – EIN Aufruf = EIN
Zyklus über ALLE Workspace-Projekte, kein eingebauter Dauer-Scheduler. Anders als
core/issue_watcher.py: keine LLM-Aufrufe (reine Subprozess-Scans über die bereits vorhandene
ProjectVerifier.check_dependency_vulnerabilities()), daher kostenlos und schnell – kein
Opt-in-Label/Limit pro Zyklus nötig, alle Projekte werden bei jedem Aufruf geprüft.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

from core.backlog_store import list_tickets, upsert_ticket
from core.notifier import notify_external
from core.verifier import ProjectVerifier
from core.workspace import WorkspaceManager

StatusCallback = Callable[[str], None]


@dataclass
class ProjectVulnerabilityResult:
    """Ergebnis EINES gescannten Projekts in einem Zyklus."""
    project_name: str
    vulnerable: bool
    detail: str = ""


@dataclass
class DependencyWatchReport:
    """Ergebnis eines gesamten Scan-Zyklus (ein Aufruf von `python main.py --check-dependencies`)."""
    scanned_projects: int = 0
    results: list[ProjectVulnerabilityResult] = field(default_factory=list)


def _ticket_id(project_name: str) -> str:
    return f"depwatch-{project_name}"


async def run_dependency_watch_cycle(status_callback: StatusCallback | None = None) -> DependencyWatchReport:
    """
    Ein einzelner Scan-Durchlauf: prüft JEDES vorhandene Workspace-Projekt auf bekannte
    Schwachstellen in seinen Abhängigkeiten (pip-audit für requirements.txt, npm audit für
    Node-Projekte MIT bereits vorhandener package-lock.json – siehe
    ProjectVerifier.check_dependency_vulnerabilities()). Wird von außen wiederholt aufgerufen
    (Cron/Taskplaner) – KEINE eigene Schleife/Sleep hier, ein Aufruf = ein Zyklus.
    """
    report = DependencyWatchReport()
    workspace = WorkspaceManager()
    project_names = workspace.list_projects()

    for project_name in project_names:
        if status_callback:
            status_callback(f"🔍 Prüfe Abhängigkeiten: {project_name}...")

        verifier = ProjectVerifier(workspace.get_project_dir(project_name))
        audit_reports = await asyncio.to_thread(verifier.check_dependency_vulnerabilities)
        report.scanned_projects += 1

        vulnerable_reports = [a for a in audit_reports if a.attempted and a.vulnerable]
        ticket_id = _ticket_id(project_name)

        if vulnerable_reports:
            total = sum(len(a.vulnerabilities) for a in vulnerable_reports)
            top = "; ".join(
                f"{v.package} {v.version} ({v.vulnerability_id})"
                for a in vulnerable_reports for v in a.vulnerabilities[:3]
            )
            detail = f"{total} bekannte Schwachstelle(n): {top}"[:300]
            upsert_ticket(
                ticket_id=ticket_id, title=f"Dependency-Schwachstellen: {project_name}",
                source="dependency_watch", status="blocked", detail=detail, project_slug=project_name,
            )
            report.results.append(ProjectVulnerabilityResult(project_name=project_name, vulnerable=True, detail=detail))
            await asyncio.to_thread(
                notify_external, "Bekannte Schwachstelle in Abhängigkeiten", f"{project_name}: {detail}",
            )
        else:
            # War das Ticket vorher "blocked" (Schwachstelle gefunden), jetzt aber sauber (z.B.
            # Abhängigkeit inzwischen manuell aktualisiert) - auf "done" ziehen, statt es für
            # immer als "blocked" stehen zu lassen (dasselbe Prinzip wie
            # core/merge_watcher.py.check_merged_tickets() für PR-Tickets).
            existing = next((t for t in list_tickets() if t.id == ticket_id), None)
            if existing and existing.status == "blocked":
                upsert_ticket(
                    ticket_id=ticket_id, title=existing.title, source="dependency_watch",
                    status="done", project_slug=project_name,
                )

    return report
