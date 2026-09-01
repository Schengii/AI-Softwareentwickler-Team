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
from pathlib import Path

from config import ENABLE_DEPENDENCY_AUTO_UPDATE, GIT_PROTECTED_BRANCHES
from core.backlog_store import list_tickets, upsert_ticket
from core.dependency_updater import apply_python_dependency_fixes
from core.notifier import notify_external
from core.verifier import DependencyAuditReport, ProjectVerifier
from core.workspace import WorkspaceManager

StatusCallback = Callable[[str], None]


@dataclass
class ProjectVulnerabilityResult:
    """Ergebnis EINES gescannten Projekts in einem Zyklus."""
    project_name: str
    vulnerable: bool
    detail: str = ""
    # PR-URL, falls core/dependency_updater.py automatisch einen Update-PR öffnen konnte
    # (siehe _open_dependency_update_pr) - leer, wenn nichts anhebbar war oder der PR-Versuch
    # aus irgendeinem Grund fehlschlug (dann bleibt es bei der reinen Meldung wie bisher).
    pr_url: str = ""


def _open_dependency_update_pr(
    project_dir: Path, project_name: str, vulnerable_reports: list[DependencyAuditReport],
) -> str:
    """
    Best-effort: hebt betroffene Python-Pakete an (core/dependency_updater.py) und öffnet
    dafür einen echten Feature-Branch + Pull Request – dieselben agents/github_agent.py-
    Primitiven wie core/issue_watcher.py, OHNE menschliche Bestätigung (unbeaufsichtigter
    Poll-Zyklus; ein Mensch reviewt/merged den PR anschließend ganz normal über GitHub).

    Gibt die PR-URL zurück, oder "" bei JEDEM Grund, es nicht zu tun (nichts Anhebbares,
    `gh` nicht bereit/eingeloggt, aktueller Branch ist kein konfigurierter Hauptbranch – z.B.
    weil parallel ein interaktiver Lauf gerade selbst einen Feature-Branch ausgecheckt hat, ein
    Git-/PR-Schritt schlägt fehl) – wirft nie eine Exception, ein Fehlschlag hier darf den
    restlichen Scan-Zyklus nie stoppen. Synchron (echte Subprozesse), IMMER über
    `asyncio.to_thread` aufrufen.
    """
    changes = apply_python_dependency_fixes(project_dir, vulnerable_reports)
    if not changes:
        return ""

    from agents.github_agent import GitHubAgent

    github_agent = GitHubAgent()
    if not github_agent.gh_ready():
        return ""

    original_branch = github_agent.get_current_branch()
    if original_branch not in GIT_PROTECTED_BRANCHES:
        return ""

    branch_name = github_agent.build_feature_branch_name(f"dependency-update-{project_name}")
    created, _ = github_agent.create_branch(branch_name, base=original_branch)
    if not created:
        return ""

    change_list = "\n".join(f"- {c}" for c in changes)
    committed, _ = github_agent.commit(f"fix(deps): update vulnerable dependencies in {project_name}\n\n{change_list}")
    if not committed:
        github_agent.checkout(original_branch)
        return ""

    pushed, _ = github_agent.push(branch=branch_name)
    if not pushed:
        github_agent.checkout(original_branch)
        return ""

    pr_ok, pr_output = github_agent.create_pull_request(
        title=f"fix(deps): update vulnerable dependencies in {project_name}",
        body=(
            "Automatischer Dependency-Update-PR von `core/dependency_watch.py` "
            f"(`python main.py --check-dependencies`).\n\nAngehobene Pakete:\n{change_list}\n\n"
            "Bitte vor dem Merge die echte CI-Pipeline abwarten."
        ),
        base=original_branch, head=branch_name,
    )
    # Immer zurück auf den Hauptbranch, egal ob der PR erfolgreich war - sonst würde der
    # NÄCHSTE gescannte Projekt in diesem Zyklus fälschlich vom Feature-Branch DIESES
    # Projekts abzweigen (dasselbe Prinzip wie beim interaktiven PR-Workflow-Fallback).
    github_agent.checkout(original_branch)
    if not pr_ok:
        return ""
    last_line = pr_output.strip().splitlines()[-1] if pr_output.strip() else ""
    return last_line


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

            pr_url = ""
            if ENABLE_DEPENDENCY_AUTO_UPDATE:
                pr_url = await asyncio.to_thread(
                    _open_dependency_update_pr, workspace.get_project_dir(project_name), project_name, vulnerable_reports,
                )
            # Ein erfolgreich geöffneter Update-PR ist derselbe Zustand wie beim PR-Workflow
            # (core/backlog_store.py: "review" = PR eröffnet, wartet auf Merge) - "blocked"
            # bleibt reserviert für den Fall, dass automatisch nichts unternommen werden konnte.
            ticket_status = "review" if pr_url else "blocked"
            ticket_detail = f"{detail} — Automatischer Update-PR: {pr_url}"[:300] if pr_url else detail
            upsert_ticket(
                ticket_id=ticket_id, title=f"Dependency-Schwachstellen: {project_name}",
                source="dependency_watch", status=ticket_status, detail=ticket_detail, project_slug=project_name,
            )
            report.results.append(ProjectVulnerabilityResult(project_name=project_name, vulnerable=True, detail=detail, pr_url=pr_url))
            notify_message = f"{project_name}: {detail}" + (f" — Update-PR: {pr_url}" if pr_url else "")
            await asyncio.to_thread(notify_external, "Bekannte Schwachstelle in Abhängigkeiten", notify_message)
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
