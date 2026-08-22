"""
core/pr_review_watcher.py – Verarbeitet menschliches Feedback & Review-Kommentare aus GitHub PRs

Ermöglicht einen echten kollaborativen Feedback-Loop zwischen Entwickler und KI-Team:
- Liest offene Pull Requests und Inline-Review-Kommentare über die `gh`-CLI aus
- Extrahiert betroffene Dateien, Zeilennummern und Änderungswünsche aus PR-Kommentaren
- Erstellt strukturierte Backlog-Tickets (`status="todo"`) für den zuständigen Spezialisten
- Schließt den Kreis zwischen menschlichem PR-Review und automatisierter Branch-Überarbeitung
"""

import asyncio
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field

from core.backlog_store import list_tickets, upsert_ticket
from core.notifier import notify_external

StatusCallback = Callable[[str], None]


@dataclass
class PRReviewComment:
    """Ein einzelner Review-Kommentar in einem Pull Request."""
    pr_number: int
    pr_title: str
    branch_name: str
    author: str
    body: str
    path: str = ""
    line: int = 0
    comment_id: str = ""


@dataclass
class PRReviewPollResult:
    """Ergebnis eines Scan-Durchlaufs nach offenen PR-Review-Kommentaren."""
    gh_available: bool = True
    scanned_prs: int = 0
    new_comments_count: int = 0
    comments: list[PRReviewComment] = field(default_factory=list)
    created_ticket_ids: list[str] = field(default_factory=list)


def _run_gh(args: list[str], timeout: float = 20.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *args],
        capture_output=True, text=True, timeout=timeout,
    )


def is_gh_cli_available() -> bool:
    """Prüft, ob die GitHub-CLI `gh` installiert und authentifiziert ist."""
    try:
        res = _run_gh(["auth", "status"], timeout=10.0)
        return res.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def get_open_pull_requests() -> list[dict]:
    """Holt alle offenen PRs des aktuellen Repositories per `gh pr list`."""
    try:
        res = _run_gh(["pr", "list", "--state", "open", "--json", "number,title,headRefName,url"])
        if res.returncode != 0:
            return []
        return json.loads(res.stdout or "[]")
    except Exception:
        return []


def get_pr_review_comments(pr_number: int) -> list[dict]:
    """Holt alle Kommentare und Review-Feedback zu einem bestimmten PR."""
    try:
        res = _run_gh(["api", f"repos/:owner/:repo/pulls/{pr_number}/comments"])
        if res.returncode != 0:
            return []
        return json.loads(res.stdout or "[]")
    except Exception:
        return []


async def run_pr_review_cycle(status_callback: StatusCallback | None = None) -> PRReviewPollResult:
    """
    Führt einen Durchlauf zur Überprüfung aller offenen PRs auf neues Review-Feedback durch.
    Wird z.B. per Cron oder `--check-pr-reviews` getriggert.
    """
    if not await asyncio.to_thread(is_gh_cli_available):
        return PRReviewPollResult(gh_available=False)

    report = PRReviewPollResult(gh_available=True)
    prs = await asyncio.to_thread(get_open_pull_requests)
    report.scanned_prs = len(prs)

    existing_ticket_ids = {t.id for t in list_tickets()}

    for pr in prs:
        pr_num = pr.get("number")
        pr_title = pr.get("title", "")
        branch = pr.get("headRefName", "")

        if status_callback:
            status_callback(f"🔍 Prüfe PR #{pr_num} ('{pr_title}') auf Review-Kommentare...")

        raw_comments = await asyncio.to_thread(get_pr_review_comments, pr_num)
        for c in raw_comments:
            c_id = str(c.get("id", ""))
            ticket_id = f"pr-review-{pr_num}-{c_id}"
            body = (c.get("body") or "").strip()
            path = c.get("path") or ""
            line = c.get("line") or c.get("original_line") or 0
            author = (c.get("user") or {}).get("login", "unknown")

            # Ignoriere Bot-eigene Kommentare
            if "bot" in author.lower() or not body:
                continue

            comment_obj = PRReviewComment(
                pr_number=pr_num,
                pr_title=pr_title,
                branch_name=branch,
                author=author,
                body=body,
                path=path,
                line=line,
                comment_id=c_id,
            )
            report.comments.append(comment_obj)

            if ticket_id not in existing_ticket_ids:
                loc = f" in `{path}:{line}`" if path else ""
                title = f"PR #{pr_num} Feedback von @{author}{loc}"
                detail = f"Branch: {branch}\nKommentar: {body}\nDatei: {path} (Zeile {line})"

                upsert_ticket(
                    ticket_id=ticket_id,
                    title=title[:80],
                    source="pr_review",
                    status="todo",
                    detail=detail,
                    project_slug=branch,
                )
                report.created_ticket_ids.append(ticket_id)
                report.new_comments_count += 1

                await asyncio.to_thread(
                    notify_external,
                    f"Neues PR-Review Feedback (#{pr_num})",
                    f"@{author}: {body[:200]} ({path})",
                )

    return report
