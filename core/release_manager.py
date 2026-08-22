"""
core/release_manager.py – Automatisches Release-Tagging für generierte Projekte

Realer struktureller Fund: der PR-Workflow (agents/github_agent.py) deckt Feature-Branch ->
Pull Request -> Merge vollständig ab – danach passierte bisher NICHTS mehr. Ein echtes Team
markiert einen gemergten Meilenstein als Release (Versions-Tag + Release-Notes), damit sich
"welcher Stand ist aktuell freigegeben" zweifelsfrei beantworten lässt. Nur das Framework
selbst hatte bisher ein gepflegtes CHANGELOG.md – generierte Projekte in workspace/ bekamen nie
eine eigene Versionshistorie.

Hook: core/merge_watcher.py.check_merged_tickets() ruft tag_release() GENAU dann auf, wenn ein
Ticket von "review" auf "done" wechselt (der zugehörige PR also wirklich gemerged wurde) UND
`project_slug` gesetzt ist – derselbe Zeitpunkt, an dem ein echtes Team einen Release schneiden
würde. workspace/<projekt> liegt im selben Repo wie das Framework selbst (kein eigenes
Projekt-Repo), Tags/Releases sind daher repo-weit und werden mit einem projektspezifischen
Präfix (`<project_slug>-vX.Y.Z`) disambiguiert.
"""

import json
import re
import subprocess

from agents.github_agent import GitHubAgent
from config import BASE_DIR

_TAG_PATTERN = re.compile(r"^(.+)-v(\d+)\.(\d+)\.(\d+)$")


def _next_version(project_slug: str) -> tuple[int, int, int]:
    """
    Ermittelt die nächste Patch-Version für `project_slug` aus den auf GitHub tatsächlich
    vorhandenen Releases (`gh release list` – bewusst NICHT lokale `git tag`-Einträge, die
    ohne vorherigen `git fetch --tags` veraltet/unvollständig sein könnten und so denselben
    Versions-Tag ein zweites Mal vergeben würden). Erstes Release für ein Projekt ohne
    vorhandenen passenden Tag: 0.1.0. `gh` nicht bereit/Befehl schlägt fehl -> ebenfalls 0.1.0
    (best effort – ein fehlschlagender `gh release create` mit bereits vergebenem Tag ist die
    sichere Fehlerart, keine stille Verwechslung).
    """
    try:
        result = subprocess.run(
            ["gh", "release", "list", "--json", "tagName", "--limit", "1000"],
            cwd=BASE_DIR, capture_output=True, text=True, timeout=20, encoding="utf-8",
        )
    except (OSError, subprocess.TimeoutExpired):
        return (0, 1, 0)
    if result.returncode != 0:
        return (0, 1, 0)

    try:
        releases = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return (0, 1, 0)

    versions: list[tuple[int, int, int]] = []
    for release in releases:
        match = _TAG_PATTERN.match((release.get("tagName") or "").strip())
        if match and match.group(1) == project_slug:
            versions.append((int(match.group(2)), int(match.group(3)), int(match.group(4))))

    if not versions:
        return (0, 1, 0)
    major, minor, patch = max(versions)
    return (major, minor, patch + 1)


def tag_release(
    project_slug: str, ticket_title: str, pr_url: str = "", github_agent: GitHubAgent | None = None,
) -> tuple[bool, str]:
    """
    Erstellt ein neues GitHub-Release (`gh release create` legt den Tag dabei automatisch mit
    an, gegen den aktuellen Stand des Default-Branches auf GitHub – kein lokal veralteter
    Checkout-Stand relevant) mit fortlaufender Patch-Version für `project_slug`.

    Best effort: `gh` nicht bereit/installiert, kein GitHub-Remote oder der Befehl schlägt
    fehl (z.B. Tag existiert bereits) liefern (False, Grund) statt einer Exception – ein
    fehlgeschlagenes Release-Tagging darf den aufrufenden Merge-Poll-Zyklus nie stoppen, das
    Ticket bleibt trotzdem korrekt auf "done" (siehe core/merge_watcher.py).

    Gibt bei Erfolg (True, Release-URL) zurück (letzte Zeile der `gh`-Ausgabe, wie bei
    agents/github_agent.py.create_pull_request()).
    """
    github_agent = github_agent or GitHubAgent()
    if not github_agent.gh_ready():
        return False, "`gh`-CLI nicht installiert/nicht eingeloggt."

    major, minor, patch = _next_version(project_slug)
    tag_name = f"{project_slug}-v{major}.{minor}.{patch}"
    notes = f"Automatisches Release nach Merge.\n\nTicket: {ticket_title}"
    if pr_url:
        notes += f"\nPull Request: {pr_url}"

    try:
        result = subprocess.run(
            ["gh", "release", "create", tag_name, "--title", tag_name, "--notes", notes],
            cwd=BASE_DIR, capture_output=True, text=True, timeout=30, encoding="utf-8",
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)

    success = result.returncode == 0
    output = (result.stdout + result.stderr).strip()
    if not success:
        return False, output
    last_line = output.splitlines()[-1] if output else tag_name
    return True, last_line
