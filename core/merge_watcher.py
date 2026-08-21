"""
core/merge_watcher.py – Merge-Erkennung für das Backlog (core/backlog_store.py)

Tickets landen bei einem geöffneten Pull Request auf dem Status "review" (siehe
interface/cli.py._ask_for_git_push() und core/issue_watcher.py), aber NIE automatisch
weiter auf "done", selbst wenn der PR längst gemerged wurde – das Backlog driftete dadurch
zwangsläufig auseinander: der wirkliche GitHub-Zustand ("gemerged") und der im Board
angezeigte Zustand ("review") liefen nach dem ersten Merge sofort auseinander.

check_merged_tickets() schließt diese Lücke: fragt für jedes "review"-Ticket den echten
PR-Status per `gh pr view` ab (agents/github_agent.py.get_pr_status()) und zieht den
Backlog-Status nach. Wird vom selben Poll-Zyklus mitgenutzt, der bereits für die
Issue-getriggerte Arbeit läuft (core/issue_watcher.py.run_issue_poll_cycle(), aufgerufen über
`python main.py --check-issues`) UND von `/backlog` in der CLI vor der Anzeige – kein
zusätzlicher Cron-Eintrag nötig, das Board zieht sich einfach bei jeder Gelegenheit nach.
"""

from agents.github_agent import GitHubAgent
from core.backlog_store import list_tickets, upsert_ticket


def check_merged_tickets(github_agent: GitHubAgent | None = None) -> list[str]:
    """
    Prüft jedes Ticket im Status "review" gegen den echten GitHub-PR-Status und aktualisiert
    es bei Bedarf: gemerged -> "done", geschlossen ohne Merge -> "blocked" (abgelehnt, braucht
    menschliche Aufmerksamkeit), weiterhin offen -> unverändert. Tickets ohne erkennbare
    PR-URL im `detail`-Feld werden übersprungen (nichts Prüfbares vorhanden). Ohne
    installierte/eingeloggte `gh`-CLI wird NICHTS geprüft (leere Liste, kein Fehler) – das
    Board bleibt dann einfach auf dem letzten bekannten Stand.

    Gibt die IDs der tatsächlich aktualisierten Tickets zurück.
    """
    github_agent = github_agent or GitHubAgent()
    if not github_agent.gh_ready():
        return []

    updated: list[str] = []
    for ticket in list_tickets(status="review"):
        if not ticket.detail.startswith("http"):
            continue  # kein PR-Link im detail-Feld (z.B. manuell gesetzter Status) - nichts prüfbar

        pr_state, _detail = github_agent.get_pr_status(ticket.detail)
        if pr_state == "merged":
            new_status, new_detail = "done", ticket.detail
        elif pr_state == "closed":
            new_status, new_detail = "blocked", f"PR geschlossen ohne Merge: {ticket.detail}"
        else:  # "open" oder "unknown" -> Ticket bleibt unverändert auf "review"
            continue

        upsert_ticket(
            ticket_id=ticket.id, title=ticket.title, source=ticket.source,
            status=new_status, detail=new_detail, project_slug=ticket.project_slug,
        )
        updated.append(ticket.id)

    return updated
