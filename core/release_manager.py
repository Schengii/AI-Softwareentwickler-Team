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

Realer Fund: tag_release() erstellte bisher NUR ein GitHub-Release (Tag + Release-Notes) –
nur das Framework selbst hatte eine im Projekt selbst lesbare CHANGELOG.md, generierte
Projekte in workspace/ bekamen bei jedem Release-Tagging keine eigene Versionshistorie-Datei.
update_project_changelog() schließt diese Lücke über dieselbe "operiert auf dem Remote-Stand,
nicht dem lokalen Checkout"-Logik wie tag_release() selbst (GitHub-Contents-API statt lokalem
Commit+Push) – der lokale Checkout in BASE_DIR könnte gerade auf einem völlig anderen Branch
stehen (z. B. mitten in einem parallelen Lauf), ein lokaler Commit+Push wäre dort riskant.
"""

import base64
import json
import re
import subprocess
from datetime import date

from agents.github_agent import GitHubAgent
from config import BASE_DIR

_TAG_PATTERN = re.compile(r"^(.+)-v(\d+)\.(\d+)\.(\d+)$")

_CHANGELOG_HEADER = (
    "# Changelog\n"
    "\n"
    "Alle nennenswerten Änderungen an diesem Projekt werden hier dokumentiert, neueste zuerst.\n"
    "Automatisch gepflegt durch core/release_manager.py bei jedem gemergten Release.\n"
)


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

    # Best effort, wie das Release-Tagging selbst: ein fehlgeschlagenes CHANGELOG.md-Update
    # darf das bereits erfolgreich erstellte Release NIE nachträglich als Fehlschlag melden -
    # der Rückgabewert bleibt (True, Release-URL) unabhängig vom Ergebnis hier.
    update_project_changelog(project_slug, tag_name, ticket_title, pr_url, github_agent=github_agent)
    return True, last_line


def _changelog_repo_path(project_slug: str) -> str:
    return f"workspace/{project_slug}/CHANGELOG.md"


def _fetch_existing_changelog(repo_slug: str, path: str) -> tuple[str | None, str | None]:
    """
    Gibt (Inhalt, sha) der aktuellen CHANGELOG.md im Repo zurück (GitHub-Contents-API), oder
    (None, None), falls die Datei noch nicht existiert oder ein Lesefehler auftrat. Im
    Fehlerfall startet update_project_changelog() dann mit einer frischen Datei - das ist
    sicher, weil GitHub den nachfolgenden PUT OHNE sha ablehnt, falls die Datei tatsächlich
    bereits existiert (Konfliktprüfung der API selbst), statt sie stillschweigend zu
    überschreiben.
    """
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{repo_slug}/contents/{path}"],
            cwd=BASE_DIR, capture_output=True, text=True, timeout=15, encoding="utf-8",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, None
    if result.returncode != 0:
        return None, None
    try:
        data = json.loads(result.stdout)
        content = base64.b64decode(data["content"]).decode("utf-8")
        return content, data["sha"]
    except (json.JSONDecodeError, KeyError, ValueError, UnicodeDecodeError):
        return None, None


def update_project_changelog(
    project_slug: str, tag_name: str, ticket_title: str, pr_url: str = "",
    github_agent: GitHubAgent | None = None,
) -> tuple[bool, str]:
    """
    Pflegt eine echte CHANGELOG.md-Datei IM GENERIERTEN PROJEKT selbst
    (workspace/<project_slug>/CHANGELOG.md) über die GitHub-Contents-API (`gh api --method PUT`)
    – schreibt direkt gegen den Default-Branch des Repos, ohne den lokalen Checkout in
    BASE_DIR anzufassen (siehe Modul-Docstring). Neue Einträge werden direkt nach dem Header
    eingefügt (neueste zuerst, wie das Framework-eigene CHANGELOG.md). Erkennt die Datei
    NICHT als von dieser Funktion verwaltet (z. B. weil sie von Hand angelegt/verändert
    wurde), wird der neue Eintrag stattdessen einfach oben angehängt, statt den bestehenden
    Header zu überschreiben.

    Best effort wie tag_release(): jeder Fehlschlag (kein `gh`, kein Remote, API-Fehler)
    liefert (False, Grund) statt einer Exception.
    """
    github_agent = github_agent or GitHubAgent()
    repo_slug = github_agent.get_repo_slug()
    if not repo_slug:
        return False, "Kein GitHub-Remote gefunden oder `gh` nicht nutzbar/eingeloggt."

    path = _changelog_repo_path(project_slug)
    existing_content, sha = _fetch_existing_changelog(repo_slug, path)

    entry_lines = [f"## {tag_name} - {date.today().isoformat()}", f"- {ticket_title.strip()}"]
    if pr_url:
        entry_lines.append(f"  ([Pull Request]({pr_url}))")
    entry = "\n".join(entry_lines) + "\n"

    if existing_content and existing_content.startswith(_CHANGELOG_HEADER):
        new_content = _CHANGELOG_HEADER + "\n" + entry + "\n" + existing_content[len(_CHANGELOG_HEADER):]
    elif existing_content:
        new_content = entry + "\n" + existing_content
    else:
        new_content = _CHANGELOG_HEADER + "\n" + entry

    payload = {
        "message": f"docs({project_slug}): CHANGELOG für {tag_name}",
        "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
    }
    if sha:
        payload["sha"] = sha

    try:
        result = subprocess.run(
            ["gh", "api", "--method", "PUT", f"repos/{repo_slug}/contents/{path}", "--input", "-"],
            input=json.dumps(payload),
            cwd=BASE_DIR, capture_output=True, text=True, timeout=20, encoding="utf-8",
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)

    success = result.returncode == 0
    return success, "" if success else (result.stdout + result.stderr).strip()
