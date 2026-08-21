"""
core/issue_watcher.py – Autonome, getriggerte Läufe: GitHub-Issues als Backlog

Ergänzt den bestehenden PR-Workflow (agents/github_agent.py) um die Trigger-Seite: ein
wiederkehrender Poll-Zyklus (aufgerufen über `python main.py --check-issues`, z.B. per
Cron/Windows-Taskplaner/GitHub-Actions-Schedule alle 10-15 Minuten) findet eigenständig neue
Arbeit über GitHub Issues, statt nur auf eine manuelle CLI-Eingabe zu warten – genau die
Reaktionsfähigkeit, die ein echtes Team neben der direkten Auftragsannahme auch hat. Bewusst
als externer Poll-Aufruf statt eines eingebauten Schedulers/Webhook-Servers: Cron/Taskplaner/
CI-Schedule lösen das zuverlässiger, als eine eigene Scheduler-Implementierung es könnte.

Derselbe Zyklus zieht außerdem die Merge-Erkennung fürs Backlog mit (core/merge_watcher.py) -
Tickets, deren PR inzwischen echt gemerged wurde, wandern dabei von "review" auf "done".

Sicherheitsmodell (bewusst konservativer als der interaktive CLI-Pfad, da KEIN Mensch zur
Bestätigung verfügbar ist):
- Nur Issues mit einem expliziten Opt-in-Label (config.ISSUE_TRIGGER_LABEL) werden
  aufgegriffen – ein echtes Team arbeitet auch einen triagierten Backlog ab, nicht wahllos
  JEDES offene Issue im Tracker.
- Label-basierte Zustandsmaschine verhindert Doppelbearbeitung bei überlappenden
  Poll-Zyklen: ISSUE_IN_PROGRESS_LABEL wird VOR dem Lauf gesetzt (nicht danach), damit ein
  zweiter, während des ersten Laufs gestarteter Zyklus dasselbe Issue nicht erneut aufgreift.
- Ein Secret-Fund blockiert HART (kein Push, kein PR) – anders als im interaktiven Pfad, wo
  ein Mensch bewusst übersteuern kann, gibt es hier niemanden, der das täte.
- Fehlgeschlagene Verifikation blockiert NICHT hart, sondern öffnet trotzdem den PR – mit
  deutlicher Kennzeichnung in Titel/Body und einem Issue-Kommentar, damit ein Mensch das beim
  Review sieht (Transparenz statt stillem Verwerfen bereits geleisteter Arbeit).
- IMMER über einen frischen Feature-Branch + Pull Request, NIE Direct-Push – anders als
  interface/cli.py._ask_for_git_push() gibt es hier keinen gh_ready()-Fallback auf
  Direct-Push, da dafür eine menschliche Bestätigung nötig wäre, die hier nicht existiert.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from agents.github_agent import GitHubAgent
from agents.orchestrator import Orchestrator
from config import (
    GIT_PROTECTED_BRANCHES,
    ISSUE_BLOCKED_LABEL,
    ISSUE_DONE_LABEL,
    ISSUE_IN_PROGRESS_LABEL,
    ISSUE_POLL_MAX_PER_CYCLE,
    ISSUE_TRIGGER_LABEL,
)
from core.backlog_store import upsert_ticket
from core.merge_watcher import check_merged_tickets

StatusCallback = Callable[[str], None]

# Mapping von IssueRunResult.outcome auf eine core/backlog_store.py-Ticket-Spalte -
# "pr_opened" ist die einzige Erfolgs-Terminalstellung (wartet auf menschlichen Review/Merge,
# daher "review" statt "done"); alles andere braucht menschliche Aufmerksamkeit -> "blocked".
_OUTCOME_TO_TICKET_STATUS = {"pr_opened": "review"}


@dataclass
class IssueRunResult:
    """Ergebnis der Bearbeitung EINES Issues in einem Poll-Zyklus."""
    issue_number: int
    title: str
    outcome: str  # "pr_opened" | "no_changes" | "blocked_secret" | "error"
    detail: str = ""


@dataclass
class IssuePollReport:
    """Ergebnis eines gesamten Poll-Zyklus (ein Aufruf von `python main.py --check-issues`)."""
    gh_ready: bool = True
    results: list[IssueRunResult] = field(default_factory=list)
    # IDs der Backlog-Tickets, die in DIESEM Zyklus per core/merge_watcher.py von "review" auf
    # "done"/"blocked" gezogen wurden (echter GitHub-Merge erkannt) - siehe dort.
    merged_ticket_ids: list[str] = field(default_factory=list)


async def run_issue_poll_cycle(
    max_issues: int | None = None, status_callback: StatusCallback | None = None,
) -> IssuePollReport:
    """
    Ein einzelner Poll-Durchlauf: findet neue, noch unbearbeitete Issues mit
    config.ISSUE_TRIGGER_LABEL und bearbeitet bis zu `max_issues` davon (Standard:
    config.ISSUE_POLL_MAX_PER_CYCLE) nacheinander. Wird von außen wiederholt aufgerufen
    (Cron/Taskplaner) – KEINE eigene Schleife/Sleep hier, ein Aufruf = ein Zyklus.
    """
    github_agent = GitHubAgent()
    if not github_agent.gh_ready():
        # Kein Fehler – nur (noch) nicht möglich, z.B. `gh` fehlt oder kein Login. Der
        # nächste Poll-Zyklus versucht es einfach erneut.
        return IssuePollReport(gh_ready=False)

    # Best effort – falls die Labels im Ziel-Repo noch nie angelegt wurden, sonst würde
    # add_issue_label() weiter unten fehlschlagen, sobald das erste Issue gefunden wird.
    github_agent.ensure_label_exists(ISSUE_IN_PROGRESS_LABEL, color="fbca04", description="KI-Team bearbeitet gerade")
    github_agent.ensure_label_exists(ISSUE_DONE_LABEL, color="0e8a16", description="KI-Team hat einen PR eröffnet")
    github_agent.ensure_label_exists(ISSUE_BLOCKED_LABEL, color="d93f0b", description="KI-Team konnte nicht abschließen")

    report = IssuePollReport(gh_ready=True)
    # Merge-Erkennung fürs Backlog nutzt DENSELBEN Poll-Zyklus mit (core/merge_watcher.py) -
    # kein zusätzlicher Cron-Eintrag nötig, gh_ready() wurde oben schon geprüft.
    report.merged_ticket_ids = check_merged_tickets(github_agent)

    limit = max_issues if max_issues is not None else ISSUE_POLL_MAX_PER_CYCLE
    issues = github_agent.list_actionable_issues(
        label=ISSUE_TRIGGER_LABEL,
        exclude_labels=[ISSUE_IN_PROGRESS_LABEL, ISSUE_DONE_LABEL, ISSUE_BLOCKED_LABEL],
    )[:limit]
    for issue in issues:
        if status_callback:
            status_callback(f"🎫 Issue #{issue.get('number')} '{issue.get('title', '')}' wird aufgegriffen...")
        result = await _process_single_issue(github_agent, issue, status_callback)
        # Terminal-Status im Backlog nachziehen (der "in_progress"-Stand wurde bereits beim
        # Aufgreifen geschrieben, siehe _process_single_issue()) - EIN Mapping-Ort statt an
        # jedem der mehreren Rückgabepunkte in _process_single_issue().
        upsert_ticket(
            ticket_id=f"issue-{result.issue_number}", title=result.title, source="issue",
            status=_OUTCOME_TO_TICKET_STATUS.get(result.outcome, "blocked"), detail=result.detail,
        )
        report.results.append(result)
    return report


async def _process_single_issue(
    github_agent: GitHubAgent, issue: dict, status_callback: StatusCallback | None,
) -> IssueRunResult:
    issue_number = issue["number"]
    title = issue.get("title", "") or f"Issue #{issue_number}"
    body = issue.get("body", "") or ""

    # VOR dem Lauf setzen (nicht danach) – verhindert, dass ein überlappender Poll-Zyklus
    # (z.B. ein sehr langer vorheriger Lauf plus ein neuer Cron-Tick) dasselbe Issue doppelt
    # aufgreift.
    github_agent.add_issue_label(issue_number, ISSUE_IN_PROGRESS_LABEL)
    # Sofort sichtbar im Backlog/Kanban-Board (interface/web_dashboard.py, /backlog in der
    # CLI), nicht erst nach Abschluss - sonst würde ein noch laufendes Issue auf dem Board
    # gar nicht auftauchen. Der Ticket-ID-Präfix "issue-" hält sie eindeutig von CLI-/
    # Dashboard-Tickets getrennt, siehe core/backlog_store.py.
    upsert_ticket(ticket_id=f"issue-{issue_number}", title=title, source="issue", status="in_progress")
    # Realer Fund: das Arbeitsverzeichnis kann hier bereits auf einem "feat/"-Branch eines
    # VORHERIGEN Issues in diesem Poll-Zyklus stehen (seit dem entsprechenden Fix wird nach
    # einem PR-Workflow-Lauf NICHT mehr zurückgewechselt, siehe unten) - original_branch wäre
    # dann fälschlich dieser Leftover-Branch statt des echten Hauptbranchs. base_branch ist
    # deshalb explizit der erste konfigurierte Hauptbranch, falls original_branch selbst
    # keiner ist.
    original_branch = github_agent.get_current_branch()
    base_branch = original_branch if original_branch in GIT_PROTECTED_BRANCHES else (GIT_PROTECTED_BRANCHES[0] if GIT_PROTECTED_BRANCHES else "main")

    try:
        orchestrator = Orchestrator()
        final_report = await orchestrator.process(f"{title}\n\n{body}".strip(), status_callback=status_callback)
    except Exception as e:
        github_agent.remove_issue_label(issue_number, ISSUE_IN_PROGRESS_LABEL)
        github_agent.add_issue_label(issue_number, ISSUE_BLOCKED_LABEL)
        github_agent.comment_on_issue(
            issue_number,
            f"🤖 Das KI-Softwareentwickler-Team konnte diese Aufgabe nicht abschließen "
            f"(unerwarteter Fehler): {e}",
        )
        return IssueRunResult(issue_number, title, "error", str(e))

    diff_status = github_agent.get_status()
    if not diff_status:
        github_agent.remove_issue_label(issue_number, ISSUE_IN_PROGRESS_LABEL)
        github_agent.comment_on_issue(
            issue_number,
            "🤖 Das KI-Softwareentwickler-Team hat diese Aufgabe bearbeitet, dabei aber keine "
            "Datei geändert – vermutlich war die Issue-Beschreibung nicht eindeutig genug.",
        )
        return IssueRunResult(issue_number, title, "no_changes")

    # Kein Mensch zur Bestätigung verfügbar – ein Secret-Fund blockiert deshalb HART, anders
    # als im interaktiven Pfad (interface/cli.py), wo bewusst übersteuert werden kann.
    if github_agent.scan_for_secrets():
        github_agent.remove_issue_label(issue_number, ISSUE_IN_PROGRESS_LABEL)
        github_agent.add_issue_label(issue_number, ISSUE_BLOCKED_LABEL)
        github_agent.comment_on_issue(
            issue_number,
            "🔑 Das KI-Softwareentwickler-Team hat mögliche Secrets in den Änderungen "
            "gefunden und den Push abgebrochen – bitte manuell prüfen.",
        )
        return IssueRunResult(issue_number, title, "blocked_secret")

    feature_branch = github_agent.build_feature_branch_name(title)
    success_b, out_b = github_agent.create_branch(feature_branch, base=base_branch)
    if not success_b:
        github_agent.remove_issue_label(issue_number, ISSUE_IN_PROGRESS_LABEL)
        github_agent.add_issue_label(issue_number, ISSUE_BLOCKED_LABEL)
        github_agent.comment_on_issue(issue_number, f"🤖 Feature-Branch konnte nicht angelegt werden: {out_b}")
        return IssueRunResult(issue_number, title, "error", out_b)

    commit_msg = f"feat: {title[:60]} (Issue #{issue_number}) via AI Developer Team"
    success_c, out_c = github_agent.commit(commit_msg)
    if not success_c:
        github_agent.remove_issue_label(issue_number, ISSUE_IN_PROGRESS_LABEL)
        github_agent.add_issue_label(issue_number, ISSUE_BLOCKED_LABEL)
        return IssueRunResult(issue_number, title, "error", out_c)

    success_p, out_p = github_agent.push(branch=feature_branch)
    if not success_p:
        github_agent.remove_issue_label(issue_number, ISSUE_IN_PROGRESS_LABEL)
        github_agent.add_issue_label(issue_number, ISSUE_BLOCKED_LABEL)
        return IssueRunResult(issue_number, title, "error", out_p)

    verification_ok = getattr(orchestrator, "last_verification_ok", False)
    verification_flag = (
        "" if verification_ok else
        "⚠️ **Verifikation nicht bestanden** – bitte vor dem Merge besonders genau prüfen.\n\n"
    )
    # final_report gedeckelt, damit ein sehr großer Fachbereichs-Bericht den PR-Body nicht
    # unbegrenzt aufbläht (dieselbe Token-/Größen-Vorsicht wie bei den bestehenden
    # Ergebnis-Kürzungen in agents/orchestrator.py).
    pr_body = (
        f"{verification_flag}Automatisch erstellt vom KI-Softwareentwickler-Team.\n\n"
        f"Closes #{issue_number}\n\n---\n\n{final_report[:3000]}"
    )
    success_pr, pr_out = github_agent.create_pull_request(
        title=commit_msg, body=pr_body, base=base_branch, head=feature_branch,
    )
    # Bewusst KEIN Zurückwechseln zum Hauptbranch mehr (realer Fund: ein `git checkout` weg
    # vom Feature-Branch entfernt jede Datei, die NUR auf diesem Branch committet ist, aus
    # dem Arbeitsverzeichnis - ein gerade erst generiertes Projekt wäre bis zum PR-Merge
    # lokal komplett verschwunden). base_branch oben sorgt dafür, dass das NÄCHSTE Issue in
    # diesem Poll-Zyklus trotzdem korrekt vom echten Hauptbranch statt von diesem
    # Leftover-Branch abzweigt.
    github_agent.remove_issue_label(issue_number, ISSUE_IN_PROGRESS_LABEL)

    if not success_pr:
        github_agent.add_issue_label(issue_number, ISSUE_BLOCKED_LABEL)
        github_agent.comment_on_issue(
            issue_number,
            f"🤖 Branch `{feature_branch}` wurde gepusht, der Pull Request konnte aber nicht "
            f"automatisch erstellt werden: {pr_out}",
        )
        return IssueRunResult(issue_number, title, "error", pr_out)

    github_agent.add_issue_label(issue_number, ISSUE_DONE_LABEL)
    pr_url = pr_out.splitlines()[-1] if pr_out else pr_out
    github_agent.comment_on_issue(issue_number, f"🤖 Pull Request erstellt: {pr_url}")
    return IssueRunResult(issue_number, title, "pr_opened", pr_url)
