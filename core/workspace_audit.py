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
from core.backlog_store import get_ticket, list_tickets, upsert_ticket
from core.notifier import notify_external
from core.optimization_advisor import analyze
from core.verifier import ProjectVerifier
from core.workspace import WorkspaceManager

StatusCallback = Callable[[str], None]

# Team-Optimierung (Retrospektive 2026-09-05, KI-Team-Optimierungs-Session): core/
# optimization_advisor.py erkennt eine anhaltend niedrige TEAM-WEITE Verifikations-
# Erfolgsquote bereits rein deterministisch (memory/run_history.py, projektübergreifend über
# ALLE zuletzt bearbeiteten Projekte hinweg) - lief aber bisher NUR auf manuellen Abruf
# (interface/cli.py, `/optimization-advisor`), niemand sah die Warnung von selbst. Real
# beobachtet: 0 von 10 der letzten Läufe endeten mit verification_ok=True, ohne dass irgendein
# automatischer Mechanismus das gemeldet hätte. Da dieser Zyklus ohnehin regelmäßig läuft
# (Cron/GitHub-Actions, siehe .github/workflows/ai-team-scheduler.yml), prüft er das jetzt bei
# jedem Durchlauf mit und eröffnet/schließt ein eigenes Backlog-Ticket dafür - dasselbe
# On-Call-Prinzip wie bei einem einzelnen fehlgeschlagenen Projekt oben, nur teamweit statt
# projektbezogen. Eine feste Ticket-ID (kein projektspezifischer Slug) - der Trend betrifft per
# Definition mehrere Projekte gleichzeitig, kein einzelnes.
TEAM_VERIFICATION_TREND_TICKET_ID = "team-verification-trend"


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
    verification_trend_warning: str = ""


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
        # Bugfix (Ultrareview-Fund): run_tests() installiert KEINE Abhängigkeiten selbst - ohne
        # vorheriges ensure_environment() (wie agents/orchestrator.py es vor jedem Verifikations-
        # Lauf tut) fällt _resolve_python() auf die System-Python zurück, sobald .ai_team_venv
        # fehlt (frischer Checkout, manuell aufgeräumtes venv, neue requirements.txt) - jeder
        # Python-Test schlägt dann mit ModuleNotFoundError fehl und der Audit eröffnet ein
        # falsch-positives "Verifikation fehlgeschlagen"-Ticket für ein eigentlich gesundes
        # Projekt.
        await asyncio.to_thread(verifier.ensure_environment)
        result = await asyncio.to_thread(verifier.run_tests)
        report.scanned_projects += 1

        healthy = result.passed
        ticket_id = _ticket_id(project_name)

        if not healthy:
            # Team-Optimierung (echter Fund, dieselbe Fehlerklasse wie core/backlog_worker.py's
            # detail-Erhalt-Fix): "audit-<slug>"-Tickets sind über `_GOVERNANCE_RETRY_PREFIXES`
            # (core/backlog_worker.py) selbst retry-fähig - `ticket.detail` ist dabei der EINZIGE
            # Kontext, den `_process_single_ticket()` in den Fix-Auftrag mischt. Bisher warf der
            # reine Zähler ("1 echte(r) Testfehler") die bereits vorhandenen, echten Testfehler-
            # Details (Test-ID, Fehlermeldung, betroffene Dateien - dieselben Felder, die
            # agents/orchestrator/verification.py._run_verification_loop() für einen gezielten
            # Fix-Auftrag nutzt) ungenutzt weg, obwohl run_tests() sie bereits berechnet hatte.
            if result.reason_skipped:
                detail = result.reason_skipped.strip()[:300]
            elif result.failures:
                detail = "\n\n".join(
                    f"Test: {f.test_id}\nFehlermeldung: {f.message}\nBetroffene Dateien: {', '.join(f.files) or 'unbekannt'}"
                    for f in result.failures[:5]
                )[:1500]
            else:
                detail = "Verifikation fehlgeschlagen (kein Detail verfügbar)."
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

    # Team-weite Verifikations-Trend-Prüfung (siehe TEAM_VERIFICATION_TREND_TICKET_ID-Docstring
    # oben) - läuft NACH der Pro-Projekt-Schleife, unabhängig davon, ob überhaupt Projekte
    # gescannt wurden (die Trend-Daten kommen aus memory/run_history.py, nicht aus DIESEM
    # Zyklus). analyze() ist rein deterministisch (keine LLM-Kosten).
    optimization_report = analyze()
    trend = optimization_report.verification_trend
    if trend is not None:
        detail = (
            f"Nur {trend.passed}/{trend.runs} der letzten Läufe (projektübergreifend) endeten "
            f"mit verification_ok=True ({trend.rate:.1f}%) - deutet auf ein strukturelles "
            "Problem hin (z.B. zu ambitionierte Aufgaben, ein systematisch fehlender Agenten-"
            "Fähigkeitsbereich), nicht nur auf einzelne Projekt-Ausreißer."
        )
        report.verification_trend_warning = detail
        if status_callback:
            status_callback(f"⚠️ Team-weite Verifikations-Erfolgsquote niedrig: {trend.passed}/{trend.runs} ({trend.rate:.1f}%)")
        upsert_ticket(
            ticket_id=TEAM_VERIFICATION_TREND_TICKET_ID,
            title="Team-weite Verifikations-Erfolgsquote anhaltend niedrig",
            source="workspace_audit", status="blocked", detail=detail,
        )
        await asyncio.to_thread(
            notify_external, "Team-weite Verifikations-Erfolgsquote niedrig", detail,
        )
    else:
        # Trend hat sich erholt (oder es gibt noch keine ausreichende Stichprobe) - ein zuvor
        # offenes Ticket dazu gilt als erledigt, dasselbe Prinzip wie bei den Pro-Projekt-
        # Tickets oben.
        existing_trend_ticket = get_ticket(TEAM_VERIFICATION_TREND_TICKET_ID)
        if existing_trend_ticket is not None and existing_trend_ticket.status == "blocked":
            upsert_ticket(
                ticket_id=TEAM_VERIFICATION_TREND_TICKET_ID, title=existing_trend_ticket.title,
                source="workspace_audit", status="done",
                detail="Erholt - die Verifikations-Erfolgsquote liegt wieder über dem Schwellwert.",
            )

    return report
