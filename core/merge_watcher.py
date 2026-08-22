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

Ein echt gemergter PR ist außerdem GENAU der Zeitpunkt, an dem ein echtes Team einen Release
schneidet (core/release_manager.py) – siehe _tag_release_for_merged_ticket() unten.
"""

import re

from agents.github_agent import GitHubAgent
from core.backlog_store import list_tickets, upsert_ticket
from core.release_manager import tag_release

# Die meisten "review"-Tickets (PR-Workflow, Issue-Watcher) haben NUR die PR-URL als
# detail-Feld – core/dependency_watch.py hängt die URL dagegen hinter einen beschreibenden
# Text ("... — Automatischer Update-PR: https://..."), damit die Schwachstellen-Beschreibung
# im Board sichtbar bleibt. Ein einfacher Substring-Match statt eines strikten Prefix-Checks
# deckt beide Fälle ab, ohne die bestehende Konvention für die anderen Quellen zu ändern.
_URL_PATTERN = re.compile(r"https?://\S+")


def _tag_release_for_merged_ticket(
    project_slug: str, title: str, pr_url: str, existing_detail: str, github_agent: GitHubAgent,
) -> str:
    """
    Best effort: taggt ein neues Release für `project_slug` (core/release_manager.py, über
    DIESELBE github_agent-Instanz wie der Rest von check_merged_tickets() – wichtig für
    Tests, die eine gemockte Instanz übergeben, statt intern eine zweite, echte anzulegen)
    und hängt die Release-URL an das bestehende Ticket-`detail` an (der PR-Link bleibt darin
    erhalten – der Substring-Regex-Match oben findet ihn bei einer künftigen Prüfung weiterhin,
    egal ob er am Anfang oder in der Mitte steht). Kein project_slug (z.B. ein manuell
    angelegtes Ticket ohne Projektbezug) oder ein fehlgeschlagenes Tagging lassen `detail`
    unverändert – ein misslungenes Release-Tagging darf den Merge-Poll-Zyklus nie stoppen,
    das Ticket landet trotzdem korrekt auf "done".
    """
    if not project_slug:
        return existing_detail
    released, info = tag_release(project_slug, title, pr_url, github_agent=github_agent)
    if not released:
        return existing_detail
    return f"{existing_detail} — Release: {info}"[:300]


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
        url_match = _URL_PATTERN.search(ticket.detail)
        if not url_match:
            continue  # kein PR-Link im detail-Feld (z.B. manuell gesetzter Status) - nichts prüfbar

        pr_url = url_match.group(0)
        pr_state, _detail = github_agent.get_pr_status(pr_url)
        if pr_state == "merged":
            new_status = "done"
            new_detail = _tag_release_for_merged_ticket(ticket.project_slug, ticket.title, pr_url, ticket.detail, github_agent)
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
