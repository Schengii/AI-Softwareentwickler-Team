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
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Branch-Präfix, an dem isolierte Selbstverbesserungs-Worktrees erkannt werden (siehe
# create_isolated_worktree). Zentral definiert, damit prune_stale_worktrees() garantiert
# dasselbe Muster nutzt wie die Erstellung – keine zwei Stellen, die auseinanderlaufen können.
WORKTREE_BRANCH_PREFIX = "ai-team/"

# Standard-"Alter" (Tage seit letztem Commit auf dem Worktree-Branch), ab dem ein NICHT
# gemergter Worktree als "stale" gilt und zur Entfernung vorgeschlagen wird. Gemergte
# Worktrees gelten unabhängig vom Alter sofort als stale (der Branch ist bereits in main).
DEFAULT_STALE_DAYS = 7


@dataclass
class WorktreePruneAction:
    """Eine einzelne Aktion/Entscheidung von prune_stale_worktrees – zur Anzeige durch den Aufrufer."""
    path: str
    branch: str
    action: str  # "removed" | "skipped"
    reason: str


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


def slugify(text: str, max_len: int = 40) -> str:
    """
    Wandelt einen beliebigen Text in einen git-branch-tauglichen Slug um (nur
    Kleinbuchstaben/Ziffern/Bindestriche). Bewusst PUBLIC (kein führender Unterstrich) –
    wird sowohl hier für isolierte Selbstverbesserungs-Worktrees als auch von
    agents/github_agent.py für normale Feature-Branch-Namen im PR-Workflow genutzt, statt
    dieselbe Slugify-Logik ein zweites Mal zu duplizieren.
    """
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return (slug[:max_len] or "task").strip("-")


def is_git_repo(directory: str) -> bool:
    try:
        result = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=directory)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def find_git_root(directory: str) -> str | None:
    """
    Ermittelt das Root-Verzeichnis des Git-Repos, zu dem `directory` gehört – auch wenn
    `directory` selbst noch nicht existiert (z.B. ein noch nicht angelegtes, brandneues
    Workspace-Projekt): dann wird beim nächsten existierenden Elternverzeichnis angesetzt.
    None, wenn weder `directory` noch einer seiner Elternordner zu einem Git-Repo gehört.

    Genutzt, um Worktree-Isolation auch für /load-geladene externe Projekte (nicht nur das
    Framework-Root selbst) zu ermöglichen – unabhängig davon, in WELCHEM Repo sich das
    Zielverzeichnis befindet.
    """
    probe = Path(directory).resolve()
    while not probe.exists():
        if probe.parent == probe:
            return None
        probe = probe.parent
    try:
        result = _run_git(["rev-parse", "--show-toplevel"], cwd=str(probe))
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return str(Path(result.stdout.strip()).resolve())


def has_uncommitted_changes(git_root: str, target_path: str) -> bool:
    """
    Prüft per `git status --short`, ob es am Zielpfad unkommittete Änderungen gibt. Ein
    frisch angelegter Worktree basiert auf dem letzten COMMIT – unkommittete Änderungen
    wären darin unsichtbar, das Team würde also mit einem veralteten Stand arbeiten und
    eigene sowie fremde Änderungen könnten beim späteren manuellen Merge kollidieren.
    """
    try:
        relative = str(Path(target_path).resolve().relative_to(Path(git_root).resolve()))
    except ValueError:
        relative = "."
    try:
        result = _run_git(["status", "--short", "--", relative], cwd=git_root)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return bool(result.stdout.strip())


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

    slug = slugify(task_summary)
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


def _list_worktrees_porcelain(base_dir: str) -> list[dict[str, str]]:
    """
    Parst `git worktree list --porcelain` in eine Liste von {"path", "branch", "head"}-Dicts.
    Der porcelain-Output besteht aus durch Leerzeilen getrennten Blöcken je Worktree, z.B.:

        worktree /pfad/zum/repo
        HEAD abcdef...
        branch refs/heads/main

        worktree /pfad/zum/anderen
        HEAD 123456...
        branch refs/heads/ai-team/foo-bar-a1b2c3
    """
    try:
        result = _run_git(["worktree", "list", "--porcelain"], cwd=base_dir, timeout=30.0)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []

    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if not line.strip():
            if current:
                entries.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            current["path"] = line[len("worktree "):].strip()
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD "):].strip()
        elif line.startswith("branch "):
            ref = line[len("branch "):].strip()
            current["branch"] = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
    if current:
        entries.append(current)
    return entries


def _is_branch_merged(base_dir: str, branch: str, target: str = "main") -> bool:
    """Prüft, ob `branch` bereits vollständig in `target` gemerged ist (git branch --merged)."""
    try:
        result = _run_git(["branch", "--merged", target], cwd=base_dir, timeout=30.0)
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    # Führende "* " (aktueller Branch) oder "+ " (in einem ANDEREN Worktree ausgecheckt -
    # genau der Fall hier, da branch im Ziel-Worktree checked out ist) entfernen.
    merged = {line.strip().lstrip("*+ ").strip() for line in result.stdout.splitlines()}
    return branch in merged


def _last_commit_age_days(base_dir: str, branch: str) -> float | None:
    """Alter (in Tagen) des letzten Commits auf `branch`, oder None wenn nicht ermittelbar."""
    try:
        result = _run_git(
            ["log", "-1", "--format=%ct", branch], cwd=base_dir, timeout=30.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        commit_ts = int(result.stdout.strip())
    except ValueError:
        return None
    commit_time = datetime.fromtimestamp(commit_ts, tz=UTC)
    age = datetime.now(tz=UTC) - commit_time
    return age / timedelta(days=1)


def prune_stale_worktrees(
    base_dir: str,
    target_branch: str = "main",
    stale_days: float = DEFAULT_STALE_DAYS,
) -> list[WorktreePruneAction]:
    """
    Räumt verwaiste, vom KI-Team angelegte Git-Worktrees (Branch-Präfix `ai-team/`, siehe
    create_isolated_worktree) auf, die entweder bereits nach `target_branch` gemergt sind
    ODER seit mindestens `stale_days` Tagen keinen neuen Commit mehr hatten.

    Rührt NIEMALS den aktuell aktiven/eingecheckten Worktree an (den `git worktree list`
    als erstes / mit `bare`-losem Haupteintrag führt – hier zusätzlich über den Vergleich
    mit `base_dir` abgesichert) und NIEMALS einen Worktree mit unkommittierten/ungemergten
    Änderungen, außer der Branch ist bereits vollständig gemergt (dann ist `--force` sicher,
    weil kein Datenverlust droht – der Inhalt steckt vollständig in `target_branch`).

    Gibt eine Liste von WorktreePruneAction zurück (nie nur ins Log geschrieben) – der
    Aufrufer (z.B. die CLI) MUSS das Ergebnis dem Nutzer anzeigen.
    """
    actions: list[WorktreePruneAction] = []

    if not is_git_repo(base_dir):
        return actions

    resolved_base = str(Path(base_dir).resolve())
    entries = _list_worktrees_porcelain(base_dir)

    for entry in entries:
        path = entry.get("path", "")
        branch = entry.get("branch", "")
        if not path or not branch:
            continue

        resolved_path = str(Path(path).resolve())

        # Der aktuell aktive Worktree (der, in dem dieser Befehl selbst läuft) wird NIE
        # angefasst - unabhängig vom Branch-Namen.
        if resolved_path == resolved_base:
            continue

        # Nur vom KI-Team angelegte Worktrees anfassen - alles andere (z.B. manuell vom
        # Nutzer angelegte Worktrees) bleibt komplett unberührt.
        if not branch.startswith(WORKTREE_BRANCH_PREFIX):
            continue

        merged = _is_branch_merged(base_dir, branch, target_branch)
        # WICHTIG: dirty wird direkt IM Worktree-Verzeichnis geprüft, nicht über
        # has_uncommitted_changes(base_dir, ...) - diese Funktion ist auf einen Unterpfad
        # DESSELBEN Arbeitsverzeichnisses ausgelegt. Ein Worktree ist aber ein komplett
        # eigenständiges Arbeitsverzeichnis außerhalb von base_dir; `git status` müsste dort
        # laufen, sonst würde faktisch der Status von base_dir selbst geprüft.
        dirty = has_uncommitted_changes(resolved_path, resolved_path)

        if not merged:
            age_days = _last_commit_age_days(base_dir, branch)
            if age_days is None or age_days < stale_days:
                actions.append(WorktreePruneAction(
                    path=resolved_path, branch=branch, action="skipped",
                    reason=(
                        f"nicht gemergt nach '{target_branch}' und jünger als {stale_days} Tage - "
                        "könnte ungesicherte Arbeit enthalten"
                    ),
                ))
                continue
            if dirty:
                actions.append(WorktreePruneAction(
                    path=resolved_path, branch=branch, action="skipped",
                    reason="nicht gemergt UND unkommittierte Änderungen - niemals force-entfernt",
                ))
                continue
            # Alt, nicht gemergt, aber sauber (keine unkommittierten Änderungen) - der
            # Branch selbst bleibt bestehen (nur der Worktree wird entfernt), damit die
            # Commits nicht verloren gehen; der Nutzer kann den Branch bei Bedarf selbst
            # aufräumen.
            ok, msg = remove_worktree(IsolatedWorktree(path=resolved_path, branch=branch, base_dir=base_dir))
            if ok:
                actions.append(WorktreePruneAction(
                    path=resolved_path, branch=branch, action="removed",
                    reason=f"seit {stale_days}+ Tagen inaktiv, sauber (Branch '{branch}' bleibt erhalten)",
                ))
            else:
                actions.append(WorktreePruneAction(
                    path=resolved_path, branch=branch, action="skipped",
                    reason=f"Entfernen fehlgeschlagen: {msg}",
                ))
            continue

        # Branch ist bereits vollständig in target_branch gemerged - der Worktree-Inhalt ist
        # damit garantiert nicht verloren, auch bei unkommittierten Änderungen (die wären
        # ohnehin nur lokale Artefakte, keine committeten, ungemergten Daten). --force nur
        # hier, weil die Sicherheitsbedingung ("bereits gemergt") erfüllt ist.
        ok, msg = remove_worktree(
            IsolatedWorktree(path=resolved_path, branch=branch, base_dir=base_dir), force=dirty,
        )
        if not ok:
            actions.append(WorktreePruneAction(
                path=resolved_path, branch=branch, action="skipped",
                reason=f"Entfernen fehlgeschlagen: {msg}",
            ))
            continue

        actions.append(WorktreePruneAction(
            path=resolved_path, branch=branch, action="removed",
            reason=f"bereits nach '{target_branch}' gemergt",
        ))

        branch_result = _run_git(["branch", "-d", branch], cwd=base_dir, timeout=30.0)
        if branch_result.returncode != 0:
            actions.append(WorktreePruneAction(
                path=resolved_path, branch=branch, action="skipped",
                reason=(
                    f"Worktree entfernt, aber Branch-Löschung fehlgeschlagen: "
                    f"{(branch_result.stderr or branch_result.stdout).strip()}"
                ),
            ))

    return actions
