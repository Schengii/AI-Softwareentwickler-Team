"""
core/backlog_worker.py – Selbstgesteuertes Abarbeiten des eigenen Backlogs (autonome Arbeit
ohne externen Trigger)

Realer Fund: core/issue_watcher.py reagiert eigenständig auf GitHub-Issues, ABER nur auf neu
gelabelte – ein "todo"-Ticket aus `/backlog-add` (interface/cli.py) oder core/pr_review_watcher.py
wurde laut eigenem Docstring bisher NIE automatisch angegangen ("Führt selbst nichts aus – ein
'todo'-Ticket wird erst zu echter Arbeit, wenn du die Aufgabe regulär in den Chat schreibst").
Ein echtes, produktives Team wartet nicht auf ein manuelles Label, um mit dem nächsten
priorisierten Backlog-Punkt zu beginnen – genau diese Lücke schließt dieser Poll-Zyklus
(aufgerufen über `python main.py --work-backlog`, z.B. per Cron/Taskplaner/GitHub-Actions-
Schedule, analog zu core/issue_watcher.py).

Scope bewusst auf `source in ("cli", "dashboard")` begrenzt:
- "issue"-Tickets werden bereits vollständig von core/issue_watcher.py verwaltet – ein
  zweiter, konkurrierender Aufgreif-Mechanismus für dieselbe Quelle würde Doppelarbeit/
  widersprüchliche Zustände riskieren.
- "pr_review"-Tickets (core/pr_review_watcher.py) beziehen sich auf einen BEREITS
  bestehenden Feature-Branch – ihre `project_slug` ist der Branch-Name, kein Workspace-
  Projekt-Slug. Sie sinnvoll abzuarbeiten bräuchte einen echten Checkout dieses Branches
  VOR dem Orchestrator-Lauf, was dieser Worker (noch) nicht beherrscht – lieber ehrlich
  ausklammern als sie falsch (auf einem frischen Branch statt dem PR-Branch) zu bearbeiten.

Respektiert core/backlog_store.py.is_ticket_ready(): ein Ticket mit noch offenen
Abhängigkeiten wird übersprungen, nicht blind aufgegriffen – ein echtes Team beginnt Schritt 2
einer Kette auch nicht, bevor Schritt 1 fertig ist. Sicherheitsmodell identisch zu
core/issue_watcher.py (siehe dort für die ausführliche Begründung): kein Mensch zur
Bestätigung verfügbar, deshalb harter Secret-Block, immer Feature-Branch+PR statt Direct-Push,
und ein Fehlschlag der Verifikation ODER eine offene Rückfrage (core/agent_toolbox.py.
ask_human_for_clarification) öffnen trotzdem einen (dann als Draft markierten) PR statt
bereits geleistete Arbeit stillschweigend zu verwerfen.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

from agents.github_agent import GitHubAgent
from agents.orchestrator import Orchestrator
from config import BACKLOG_WORKER_MAX_PER_CYCLE, BACKLOG_WORKER_WIP_LIMIT, GIT_PROTECTED_BRANCHES
from core.backlog_store import Ticket, count_by_status, is_ticket_ready, list_tickets, upsert_ticket
from core.merge_watcher import check_merged_tickets
from core.notifier import notify_external
from core.workspace import WorkspaceManager

StatusCallback = Callable[[str], None]

_AUTONOMOUS_SOURCES = ("cli", "dashboard")

# Dieselbe Terminal-Status-Zuordnung wie core/issue_watcher.py._OUTCOME_TO_TICKET_STATUS -
# siehe dort für die Begründung je Ausgang.
_OUTCOME_TO_TICKET_STATUS = {
    "pr_opened": "review",
    "pr_opened_ci_failed": "blocked",
    "pr_opened_needs_clarification": "blocked",
}


@dataclass
class BacklogRunResult:
    """Ergebnis der Bearbeitung EINES Tickets in einem Poll-Zyklus."""
    ticket_id: str
    title: str
    outcome: str  # "pr_opened" | "pr_opened_ci_failed" | "pr_opened_needs_clarification" | "no_changes" | "blocked_secret" | "error"
    detail: str = ""


@dataclass
class BacklogPollReport:
    """Ergebnis eines gesamten Poll-Zyklus (ein Aufruf von `python main.py --work-backlog`)."""
    results: list[BacklogRunResult] = field(default_factory=list)
    # Sichtbar statt stumm nichts zu tun, wenn dieser Zyklus bewusst NICHTS aufgegriffen hat
    # (WIP-Limit erreicht, `gh` nicht bereit, oder kein bereites "todo"-Ticket) - dieselbe
    # "niemals stumm überspringen"-Linie wie reason_skipped an anderer Stelle im Projekt.
    skipped_reason: str = ""
    merged_ticket_ids: list[str] = field(default_factory=list)


async def run_backlog_poll_cycle(
    max_tickets: int | None = None, status_callback: StatusCallback | None = None,
) -> BacklogPollReport:
    """
    Ein einzelner Poll-Durchlauf: greift bis zu `max_tickets` (Standard:
    config.BACKLOG_WORKER_MAX_PER_CYCLE) abhängigkeitsfreie "todo"-Tickets aus `_AUTONOMOUS_
    SOURCES` auf, höchste Priorität zuerst. Wird von außen wiederholt aufgerufen (Cron/
    Taskplaner) – KEINE eigene Schleife/Sleep hier, ein Aufruf = ein Zyklus (dasselbe Prinzip
    wie core/issue_watcher.py.run_issue_poll_cycle()).
    """
    report = BacklogPollReport()
    github_agent = GitHubAgent()
    if not github_agent.gh_ready():
        report.skipped_reason = "`gh`-CLI ist auf diesem System nicht bereit (fehlt/kein Login) - übersprungen."
        return report

    # Merge-Erkennung fürs Backlog (core/merge_watcher.py) opportunistisch mitnehmen, exakt
    # wie core/issue_watcher.py es tut - kein zusätzlicher Cron-Eintrag nötig.
    report.merged_ticket_ids = check_merged_tickets(github_agent)

    if BACKLOG_WORKER_WIP_LIMIT > 0 and count_by_status("in_progress") >= BACKLOG_WORKER_WIP_LIMIT:
        report.skipped_reason = (
            f"WIP-Limit erreicht ({BACKLOG_WORKER_WIP_LIMIT} Ticket(s) gleichzeitig 'in_progress') "
            "- laufende Arbeit wird zuerst abgeschlossen, bevor Neues eigenständig begonnen wird."
        )
        return report

    all_tickets = list_tickets()
    ready_todo = [
        t for t in all_tickets
        if t.status == "todo" and t.source in _AUTONOMOUS_SOURCES and is_ticket_ready(t, all_tickets)[0]
    ]
    if not ready_todo:
        report.skipped_reason = "Kein abhängigkeitsfreies 'todo'-Ticket aus cli/dashboard im Backlog gefunden."
        return report
    ready_todo.sort(key=lambda t: t.priority)  # 1=hoch zuerst

    limit = max_tickets if max_tickets is not None else BACKLOG_WORKER_MAX_PER_CYCLE
    for ticket in ready_todo[:limit]:
        if status_callback:
            status_callback(f"🎫 Backlog-Ticket `{ticket.id}` '{ticket.title}' wird eigenständig aufgegriffen...")
        result = await _process_single_ticket(github_agent, ticket, status_callback)
        # Terminal-Status im Backlog nachziehen (der "in_progress"-Stand wurde bereits beim
        # Aufgreifen geschrieben, siehe _process_single_ticket()) - EIN Mapping-Ort statt an
        # jedem der mehreren Rückgabepunkte dort.
        upsert_ticket(
            ticket_id=ticket.id, title=ticket.title, source=ticket.source,
            status=_OUTCOME_TO_TICKET_STATUS.get(result.outcome, "blocked"), detail=result.detail,
        )
        if result.outcome != "pr_opened":
            await asyncio.to_thread(
                notify_external, "Backlog-Ticket benötigt Aufmerksamkeit",
                f"`{result.ticket_id}` '{result.title}' ({result.outcome}): {result.detail[:200]}",
            )
        report.results.append(result)
    return report


async def _process_single_ticket(
    github_agent: GitHubAgent, ticket: Ticket, status_callback: StatusCallback | None,
) -> BacklogRunResult:
    # Sofort sichtbar im Backlog/Kanban-Board, nicht erst nach Abschluss - sonst würde ein noch
    # laufendes Ticket auf dem Board gar nicht auftauchen (dasselbe Prinzip wie
    # core/issue_watcher.py._process_single_issue()).
    upsert_ticket(ticket_id=ticket.id, title=ticket.title, source=ticket.source, status="in_progress")

    original_branch = github_agent.get_current_branch()
    base_branch = original_branch if original_branch in GIT_PROTECTED_BRANCHES else (GIT_PROTECTED_BRANCHES[0] if GIT_PROTECTED_BRANCHES else "main")

    # Best effort: existiert bereits ein Workspace-Projekt mit diesem Slug, arbeitet der Lauf
    # DARIN weiter statt (fälschlich) ein neues zu beginnen. Kein project_slug oder kein
    # existierendes Verzeichnis -> Orchestrator entscheidet wie gewohnt selbst (core/task_
    # manager.py leitet einen Slug aus der Aufgabe ab), exakt wie core/issue_watcher.py es
    # bereits für Issues tut.
    forced_project_dir: str | None = None
    if ticket.project_slug:
        candidate = WorkspaceManager().get_project_dir(ticket.project_slug)
        if candidate.exists():
            forced_project_dir = str(candidate)

    try:
        orchestrator = Orchestrator()
        final_report = await orchestrator.process(
            ticket.title, status_callback=status_callback, forced_project_dir=forced_project_dir,
        )
    except Exception as e:
        return BacklogRunResult(ticket.id, ticket.title, "error", str(e))

    diff_status = github_agent.get_status()
    if not diff_status:
        return BacklogRunResult(
            ticket.id, ticket.title, "no_changes",
            "Ticket bearbeitet, dabei aber keine Datei geändert - vermutlich war der Titel nicht eindeutig genug.",
        )

    # Kein Mensch zur Bestätigung verfügbar – ein Secret-Fund blockiert deshalb HART, anders
    # als im interaktiven Pfad (interface/cli.py), wo bewusst übersteuert werden kann (siehe
    # dieselbe Begründung in core/issue_watcher.py).
    if github_agent.scan_for_secrets():
        return BacklogRunResult(
            ticket.id, ticket.title, "blocked_secret",
            "Mögliche Secrets in den Änderungen gefunden und den Push abgebrochen - bitte manuell prüfen.",
        )

    feature_branch = github_agent.build_feature_branch_name(ticket.title)
    success_b, out_b = github_agent.create_branch(feature_branch, base=base_branch)
    if not success_b:
        return BacklogRunResult(ticket.id, ticket.title, "error", out_b)

    commit_msg = f"feat: {ticket.title[:60]} (Backlog {ticket.id}) via AI Developer Team"
    success_c, out_c = github_agent.commit(commit_msg)
    if not success_c:
        return BacklogRunResult(ticket.id, ticket.title, "error", out_c)

    success_p, out_p = github_agent.push(branch=feature_branch)
    if not success_p:
        return BacklogRunResult(ticket.id, ticket.title, "error", out_p)

    verification_ok = getattr(orchestrator, "last_verification_ok", False)
    needs_human_input = getattr(orchestrator, "last_needs_human_input", False)
    clarification_questions = getattr(orchestrator, "last_clarification_questions", [])

    clarification_flag = (
        "❓ **Offene Rückfrage(n):**\n" + "\n".join(f"- {q}" for q in clarification_questions) + "\n\n"
        if needs_human_input else ""
    )
    verification_flag = (
        "" if verification_ok else
        "⚠️ **Verifikation nicht bestanden** – bitte vor dem Merge besonders genau prüfen.\n\n"
    )
    # final_report gedeckelt, damit ein sehr großer Fachbereichs-Bericht den PR-Body nicht
    # unbegrenzt aufbläht (dieselbe Vorsicht wie core/issue_watcher.py).
    pr_body = (
        f"{clarification_flag}{verification_flag}Automatisch aus dem Backlog aufgegriffen vom "
        f"KI-Softwareentwickler-Team.\n\nTicket: `{ticket.id}`\n\n---\n\n{final_report[:3000]}"
    )
    success_pr, pr_out = github_agent.create_pull_request(
        title=commit_msg, body=pr_body, base=base_branch, head=feature_branch,
        draft=needs_human_input or not verification_ok,
    )
    # Bewusst KEIN Zurückwechseln zum Hauptbranch mehr - dieselbe Begründung wie
    # core/issue_watcher.py: ein Checkout weg vom Feature-Branch würde jede nur dort committete
    # Datei aus dem Arbeitsverzeichnis entfernen, bis der PR gemerged ist.
    if not success_pr:
        return BacklogRunResult(ticket.id, ticket.title, "error", pr_out)

    pr_url = pr_out.splitlines()[-1] if pr_out else pr_out

    # Eine offene Rückfrage ist wichtiger als das CI-Ergebnis (das kann durchaus grün sein,
    # obwohl eine fachliche Frage offen ist) - deshalb vor der CI-Prüfung behandelt.
    if needs_human_input:
        return BacklogRunResult(ticket.id, ticket.title, "pr_opened_needs_clarification", pr_url)

    ci_status, ci_detail = await github_agent.wait_for_ci_status(feature_branch)
    if ci_status == "failed":
        return BacklogRunResult(ticket.id, ticket.title, "pr_opened_ci_failed", f"{pr_url} (CI fehlgeschlagen: {ci_detail})")
    return BacklogRunResult(ticket.id, ticket.title, "pr_opened", pr_url)
