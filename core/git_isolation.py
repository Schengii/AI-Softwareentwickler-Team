"""
core/git_isolation.py – Git-Worktree-Isolation für Selbstverbesserungsläufe

Realer Fund aus einem echten Lauf: Der backend-Agent überschrieb main.py UND
interface/cli.py im Framework-Root direkt mit syntaktisch kaputtem Inhalt – für die
Dauer des Laufs lag damit das ECHTE Arbeitsverzeichnis des Nutzers offen (core/agent_toolbox.py
verhindert seitdem zwar kaputtes *Python*, aber kein falsches Löschen, kein Überschreiben
sinnvollen Codes mit funktional falschem, aber syntaktisch validem Code, etc.).

Arbeitet ein Agenten-Team gegen das Framework-Root selbst, läuft der eigentliche Lauf
deshalb jetzt in einem ISOLIERTEN Git-Worktree: einem komplett separaten Verzeichnis auf
einem eigenen Branch, abgezweigt vom aktuellen HEAD. Das echte Arbeitsverzeichnis des
Nutzers wird während des GESAMTEN Laufs nicht berührt – der Mensch entscheidet danach
selbst per `git diff`/`git merge`, ob und wie die Änderungen übernommen werden (analog
zum bestehenden Git-Push-Bestätigungs-Gate in interface/cli.py).
"""

import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path


class GitIsolationError(Exception):
    """Kontrollierter Fehler bei der Worktree-Erstellung (z.B. kein Git-Repo, git fehlt)."""


@dataclass
class IsolatedWorktree:
    """Ein für einen einzelnen Lauf angelegter, isolierter Git-Worktree."""
    path: str
    branch: str
    base_dir: str


def _run_git(args: list[str], cwd: str, timeout: float = 30.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout,
    )


def _slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return (slug[:max_len] or "task").strip("-")


def is_git_repo(directory: str) -> bool:
    try:
        result = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=directory)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def create_isolated_worktree(base_dir: str, task_summary: str) -> IsolatedWorktree:
    """
    Legt einen neuen Git-Worktree für einen Selbstverbesserungslauf gegen base_dir an:
    eigenes Verzeichnis (Geschwister-Ordner von base_dir), eigener Branch vom aktuellen
    HEAD abgezweigt – das tatsächliche Arbeitsverzeichnis bleibt unangetastet.

    Wirft GitIsolationError bei jedem Fehlschlag (kein Git-Repo, git fehlt, worktree add
    schlägt fehl) – der Aufrufer MUSS diesen Fall behandeln (siehe agents/orchestrator.py:
    ein Selbstverbesserungslauf bricht bewusst lieber ab, als ohne Isolation direkt im
    echten Arbeitsverzeichnis zu schreiben).
    """
    if not is_git_repo(base_dir):
        raise GitIsolationError(f"'{base_dir}' ist kein Git-Repository – Worktree-Isolation nicht möglich.")

    slug = _slugify(task_summary)
    unique = uuid.uuid4().hex[:6]
    branch = f"ai-team/{slug}-{unique}"
    worktree_dir = str(Path(base_dir).resolve().parent / ".ai-team-worktrees" / f"{slug}-{unique}")
    Path(worktree_dir).parent.mkdir(parents=True, exist_ok=True)

    try:
        result = _run_git(["worktree", "add", "-b", branch, worktree_dir], cwd=base_dir, timeout=60.0)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GitIsolationError(f"git worktree add konnte nicht ausgeführt werden: {e}") from e

    if result.returncode != 0:
        raise GitIsolationError(
            f"git worktree add fehlgeschlagen: {(result.stderr or result.stdout).strip()}"
        )

    return IsolatedWorktree(path=worktree_dir, branch=branch, base_dir=base_dir)


def remove_worktree(worktree: IsolatedWorktree, force: bool = False) -> tuple[bool, str]:
    """Entfernt einen zuvor angelegten Worktree wieder (z.B. nach bewusstem Verwerfen)."""
    args = ["worktree", "remove", worktree.path]
    if force:
        args.append("--force")
    try:
        result = _run_git(args, cwd=worktree.base_dir, timeout=30.0)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return result.returncode == 0, (result.stderr or result.stdout).strip()
