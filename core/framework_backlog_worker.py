"""
core/framework_backlog_worker.py – Autonome Bearbeitung von Framework-Selbstverbesserungs-
Tickets (P1-1, ROADMAP_TEMP.md: "Root-Cause-Tickets werden erzeugt, aber nie bearbeitet")

core/root_cause_analyst.py legt `[framework]`-Befunde bewusst NICHT in core/backlog_worker.py.
_AUTONOMOUS_SOURCES ein - Framework-Änderungen verdienen menschliches Review. Real gemessen
nach ~3 Wochen: 5 offene + 1 blockiertes Root-Cause-Ticket lagen unbearbeitet, weil es keinen
strukturierten, sicheren Weg gab, sie überhaupt anzugehen - nur "von Hand" oder "gar nicht".

`python main.py --work-framework-backlog` greift genau diese Tickets auf, arbeitet IMMER in
einem isolierten Git-Worktree (core/git_isolation.py - das echte Framework-Arbeitsverzeichnis
des Nutzers bleibt während des gesamten Laufs unberührt) und liefert am Ende NUR einen Draft-PR,
NIE einen direkten Merge - der Mensch bleibt Gatekeeper, nur die Vorarbeit passiert autonom.

Pflichtschritte je Ticket:
1. `refactoring`-Agent bekommt das Ticket als Aufgabe (echter Tool-Zugriff auf den Worktree).
2. MECHANISCHER Beweis, dass ein neuer, ECHTER Regressionstest entstand: alle vom Agenten
   geänderten NICHT-Test-Dateien werden kurzzeitig auf ihren Vorher-Stand zurückgesetzt, der
   neue Test muss DANN fehlschlagen ("rot ohne Fix") - erst danach wird der volle Endstand
   wiederhergestellt und derselbe Test muss GRÜN sein. Kein Beweis, kein Commit.
3. `ruff check` auf allen geänderten Python-Dateien muss sauber sein.
4. Commit mit `Closes: <ticket-id>` (core/backlog_hygiene.py schließt das Ticket danach
   automatisch, siehe CLAUDE.md).
5. Push + Draft-PR (agents/github_agent.py, draft=True) - KEIN automatischer Merge.

Best-effort: jeder Fehlschlag lässt den Worktree für menschliche Inspektion stehen (kein
automatisches Aufräumen), das Ticket bleibt unverändert liegen, und der Lauf macht mit dem
nächsten Ticket weiter statt abzubrechen.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from config import BASE_DIR
from core.backlog_store import Ticket, list_tickets
from core.git_isolation import GitIsolationError, create_isolated_worktree
from core.git_runtime import GIT_COMMAND_TIMEOUT_SECONDS, run_git
from core.message_bus import AgentTask

logger = logging.getLogger(__name__)

TICKET_SOURCE = "root_cause_analysis"
PR_BASE_BRANCH = "main"
PYTEST_TIMEOUT_SECONDS = 120.0
RUFF_TIMEOUT_SECONDS = 60.0


def _is_test_file(rel_path: str) -> bool:
    name = rel_path.rsplit("/", 1)[-1]
    return rel_path.startswith(("tests/", "test/")) or "/tests/" in rel_path or name.startswith("test_") or name.endswith("_test.py")


@dataclass
class TicketAttemptResult:
    ticket_id: str
    success: bool
    reason: str = ""
    branch: str = ""
    pr_url: str = ""
    new_test_files: list[str] = field(default_factory=list)


def find_framework_tickets() -> list[Ticket]:
    """Offene/blockierte Root-Cause-Tickets, deren Detail den `[framework]`-Präfix trägt (siehe
    core/root_cause_analyst.py.record_findings_as_tickets() - `category == "framework"` landet
    als `[framework] Root Cause: ...` im `detail`-Feld)."""
    return [
        t for t in list_tickets()
        if t.source == TICKET_SOURCE and t.status in ("todo", "blocked") and t.detail.startswith("[framework]")
    ]


def _collect_changes(worktree_path: str) -> list[tuple[str, str]]:
    """[(status_code, rel_path)] aller Änderungen (getrackt + neu) im Worktree, dasselbe
    Vorgehen wie core/git_isolation.py.copy_worktree_changes_to_target()."""
    result = run_git(["status", "--porcelain", "--untracked-files=all"], cwd=worktree_path)
    if result.returncode != 0 or not result.stdout.strip():
        return []
    changes: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        code, rel = line[:2].strip(), line[3:].strip()
        if " -> " in rel:
            rel = rel.split(" -> ", 1)[1]
        changes.append((code, rel))
    return changes


def _head_blob(worktree_path: str, rel_path: str) -> bytes | None:
    """Inhalt von `rel_path` in HEAD, oder None, wenn die Datei dort nicht existiert (=neu)."""
    result = run_git(["show", f"HEAD:{rel_path}"], cwd=worktree_path)
    if result.returncode != 0:
        return None
    return result.stdout.encode("utf-8", errors="replace")


def _run_pytest(worktree_path: str, test_files: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["python", "-m", "pytest", "-q", *test_files],
            cwd=worktree_path, capture_output=True, text=True, timeout=PYTEST_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess([], 1, "", str(e))


def _verify_regression_test_proves_the_bug(
    worktree_path: str, changes: list[tuple[str, str]],
) -> tuple[bool, str, list[str]]:
    """Mechanischer Beweis statt Vertrauen in den Agenten-Bericht: der neue Test MUSS ohne den
    Fix rot sein und MIT dem Fix grün. Gibt (bewiesen, Grund-bei-Fehlschlag, neue Testdateien)
    zurück. Stellt am Ende IMMER den vollständigen Endstand des Agenten wieder her, unabhängig
    vom Ergebnis - ein Mensch, der den Worktree danach inspiziert, sieht den echten Versuch."""
    base = Path(worktree_path)
    new_test_files = [rel for code, rel in changes if _is_test_file(rel) and ("A" in code or "?" in code)]
    non_test_changed = [rel for _, rel in changes if not _is_test_file(rel)]

    if not new_test_files:
        return False, "Kein neuer Testdatei-Fund unter den geänderten Dateien - kein Regressionstest-Beweis möglich.", []

    # Vollständigen Endstand sichern, um ihn nach der Rot/Grün-Probe verlässlich wiederherzustellen.
    backup: dict[str, bytes | None] = {}
    for _, rel in changes:
        p = base / rel
        backup[rel] = p.read_bytes() if p.exists() else None

    try:
        # "Rot"-Phase: Produktivcode-Änderungen zurücksetzen, nur der neue Test bleibt.
        for rel in non_test_changed:
            p = base / rel
            head_content = _head_blob(worktree_path, rel)
            if head_content is not None:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(head_content)
            elif p.exists():
                p.unlink()

        red = _run_pytest(worktree_path, new_test_files)
        if red.returncode == 0:
            return (
                False,
                "Der neue Test schlägt schon OHNE den Fix nicht fehl - kein Beweis, dass er den "
                "gemeldeten Fehler tatsächlich reproduziert.",
                new_test_files,
            )
    finally:
        # "Grün"-Phase / Wiederherstellung: kompletter Endstand des Agenten, immer.
        for rel, content in backup.items():
            p = base / rel
            if content is None:
                if p.exists():
                    p.unlink()
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(content)

    green = _run_pytest(worktree_path, new_test_files)
    if green.returncode != 0:
        return False, f"Der neue Test ist nach dem Fix weiterhin rot:\n{green.stdout[-2000:]}", new_test_files
    return True, "", new_test_files


def _run_ruff(worktree_path: str, py_files: list[str]) -> tuple[bool, str]:
    if not py_files:
        return True, ""
    try:
        result = subprocess.run(
            ["ruff", "check", *py_files], cwd=worktree_path, capture_output=True, text=True, timeout=RUFF_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def _build_task_description(ticket: Ticket) -> str:
    return (
        "Dies ist ein Framework-Selbstverbesserungs-Auftrag (kein Zielprojekt-Code): behebe den "
        "folgenden, bereits durch eine Root-Cause-Analyse belegten Framework-Fehler DIREKT im "
        "Quellcode dieses Repositories. VERPFLICHTEND: schreibe ZUERST einen neuen, ECHTEN "
        "Regressionstest (unter tests/), der den Fehler reproduziert und OHNE deinen Fix "
        "fehlschlägt - erst danach implementierst du den Fix. Ändere nur, was für den Fix nötig "
        "ist, keine unabhängigen Aufräumarbeiten. Halte dich an den bestehenden Code-Stil "
        "(siehe CLAUDE.md, deutsche Docstrings, englische Bezeichner).\n\n"
        f"TICKET {ticket.id}:\n{ticket.title}\n\n{ticket.detail}"
    )


async def attempt_ticket(orchestrator, ticket: Ticket) -> TicketAttemptResult:
    """Bearbeitet EIN Framework-Ticket vollständig: isolierter Worktree → Agent → mechanischer
    Rot/Grün-Beweis → ruff → Commit → Push → Draft-PR. Wirft nie - jeder Fehlschlag kommt als
    `TicketAttemptResult(success=False, reason=...)` zurück, der Worktree bleibt für
    Inspektion stehen (kein Aufräumen bei Fehlschlag)."""
    try:
        worktree = create_isolated_worktree(BASE_DIR, f"framework-fix-{ticket.id}")
    except GitIsolationError as e:
        return TicketAttemptResult(ticket_id=ticket.id, success=False, reason=f"Worktree-Isolation fehlgeschlagen: {e}")

    task = AgentTask(
        task_id=f"framework_fix_{ticket.id}",
        agent_id="refactoring",
        description=_build_task_description(ticket),
        project_dir=worktree.path, allow_tools=True,
    )
    try:
        result = await orchestrator._run_single_agent(task)
    except Exception as e:
        return TicketAttemptResult(ticket_id=ticket.id, success=False, reason=f"Agenten-Aufruf fehlgeschlagen: {e}", branch=worktree.branch)

    if not result.success:
        return TicketAttemptResult(
            ticket_id=ticket.id, success=False,
            reason=f"Agent konnte den Fix nicht abschließen: {result.error or 'unbekannter Fehler'}",
            branch=worktree.branch,
        )

    changes = _collect_changes(worktree.path)
    if not changes:
        return TicketAttemptResult(ticket_id=ticket.id, success=False, reason="Agent hat keine Datei geändert.", branch=worktree.branch)

    proven, reason, new_test_files = _verify_regression_test_proves_the_bug(worktree.path, changes)
    if not proven:
        return TicketAttemptResult(ticket_id=ticket.id, success=False, reason=reason, branch=worktree.branch, new_test_files=new_test_files)

    py_files = [rel for _, rel in changes if rel.endswith(".py")]
    ruff_ok, ruff_output = _run_ruff(worktree.path, py_files)
    if not ruff_ok:
        return TicketAttemptResult(
            ticket_id=ticket.id, success=False, reason=f"ruff check fehlgeschlagen:\n{ruff_output[-2000:]}",
            branch=worktree.branch, new_test_files=new_test_files,
        )

    commit_message = (
        f"fix: {ticket.title}\n\n{ticket.detail[:1500]}\n\nCloses: {ticket.id}"
    )
    run_git(["add", "-A"], cwd=worktree.path)
    commit_result = run_git(["commit", "-m", commit_message], cwd=worktree.path, timeout=GIT_COMMAND_TIMEOUT_SECONDS)
    if commit_result.returncode != 0:
        return TicketAttemptResult(
            ticket_id=ticket.id, success=False,
            reason=f"Commit fehlgeschlagen: {(commit_result.stdout + commit_result.stderr).strip()}",
            branch=worktree.branch, new_test_files=new_test_files,
        )

    from agents.github_agent import GitHubAgent
    github = GitHubAgent()
    if not github.gh_ready():
        return TicketAttemptResult(
            ticket_id=ticket.id, success=False,
            reason="Fix committet, aber gh-CLI nicht verfügbar/eingeloggt - kein Push/PR möglich.",
            branch=worktree.branch, new_test_files=new_test_files,
        )

    # git push funktioniert über Refs, nicht über das aktuelle Arbeitsverzeichnis - ein
    # Worktree-Branch ist im geteilten .git-Objektspeicher auch von BASE_DIR aus sichtbar
    # (core/git_isolation.py-Moduldocstring).
    push_ok, push_output = github.push(branch=worktree.branch)
    if not push_ok:
        return TicketAttemptResult(
            ticket_id=ticket.id, success=False, reason=f"Push fehlgeschlagen: {push_output}",
            branch=worktree.branch, new_test_files=new_test_files,
        )

    pr_title = f"fix: {ticket.title}"
    pr_body = (
        f"Autonom erzeugter Fix für Root-Cause-Ticket `{ticket.id}` "
        f"(python main.py --work-framework-backlog, core/framework_backlog_worker.py).\n\n"
        f"**Neuer Regressionstest** (mechanisch geprüft: rot ohne Fix, grün mit Fix):\n"
        + "\n".join(f"- `{f}`" for f in new_test_files)
        + f"\n\n**Ticket-Detail:**\n{ticket.detail[:2000]}\n\n"
        "⚠️ Draft-PR - kein automatischer Merge. Bitte vor dem Merge menschlich reviewen.\n\n"
        f"Closes: {ticket.id}"
    )
    pr_ok, pr_output = github.create_pull_request(title=pr_title, body=pr_body, base=PR_BASE_BRANCH, head=worktree.branch, draft=True)
    if not pr_ok:
        return TicketAttemptResult(
            ticket_id=ticket.id, success=False, reason=f"Push erfolgreich, aber PR-Erstellung fehlgeschlagen: {pr_output}",
            branch=worktree.branch, new_test_files=new_test_files,
        )

    pr_url = pr_output.strip().splitlines()[-1] if pr_output.strip() else ""
    return TicketAttemptResult(
        ticket_id=ticket.id, success=True, branch=worktree.branch, pr_url=pr_url, new_test_files=new_test_files,
    )


async def work_framework_backlog(orchestrator, limit: int = 1) -> list[TicketAttemptResult]:
    """Bearbeitet bis zu `limit` offene/blockierte Framework-Root-Cause-Tickets nacheinander.
    Standard 1 (nicht "alle auf einmal") - jeder Versuch kostet echte LLM-Aufrufe UND erzeugt im
    Erfolgsfall einen eigenen Draft-PR; ein Mensch soll die Kadenz bewusst steuern (Cron/
    Taskplaner-Intervall), nicht der Worker selbst."""
    tickets = find_framework_tickets()
    results: list[TicketAttemptResult] = []
    for ticket in tickets[:max(0, limit)]:
        results.append(await attempt_ticket(orchestrator, ticket))
    return results


def format_results_for_humans(results: list[TicketAttemptResult]) -> str:
    if not results:
        return "Keine offenen Framework-Root-Cause-Tickets ([framework]-Präfix) gefunden."
    lines = []
    for r in results:
        if r.success:
            lines.append(f"✅ {r.ticket_id}: Draft-PR erstellt ({r.pr_url or r.branch}), Regressionstest: {', '.join(r.new_test_files)}")
        else:
            lines.append(f"❌ {r.ticket_id}: {r.reason} (Worktree-Branch `{r.branch}` bleibt für Inspektion stehen.)" if r.branch else f"❌ {r.ticket_id}: {r.reason}")
    return "\n".join(lines)
