"""
core/framework_release.py – Echtes Release-Management: SemVer-Tagging + GitHub-Releases

Realer Fund bei einer Bestandsaufnahme des eigenen Teams: CHANGELOG.md wird bei jedem PR
manuell um einen neuen Eintrag ergänzt, aber es gibt über die gesamte Projekthistorie keine
einzige Versionsnummer, keinen einzigen Git-Tag, keine einzige GitHub-Release – das README
zeigt "v4.3" nur als hart einprogrammierte Zeichenkette ohne jeden Bezug zu echten Commits
oder Tags. Ein professionelles Team markiert Meilensteine über echte, nachvollziehbare
Versionen statt eine Zahl von Hand im Text zu pflegen.

Nutzt die im Projekt bereits durchgängig etablierte Commit-Konvention (feat:/fix:/docs:/...,
siehe jeder bisherige PR-Commit) für eine automatische SemVer-Einstufung:
- "feat:"                                -> MINOR-Bump (neue Fähigkeit, abwärtskompatibel)
- "fix:"                                 -> PATCH-Bump (Fehlerbehebung)
- "!" direkt nach dem Typ ODER "BREAKING CHANGE" im Commit-Text -> MAJOR-Bump
- alle anderen Typen (docs/chore/test/refactor/...) tragen NICHT zur Einstufung bei, lösen
  aber bei fehlendem feat/fix/! trotzdem einen PATCH-Bump aus, sofern überhaupt Commits seit
  dem letzten Tag existieren – keine "leeren" Releases ohne jeden Grund.

Nicht zu verwechseln mit `core/release_manager.py`: das dort taggt automatisch generierte
Workspace-PROJEKTE (`workspace/<projekt>/`) beim Mergen ihres jeweiligen Tickets – ein völlig
anderer Anwendungsfall (viele kleine, unabhängige Projekt-Historien) als dieses Modul hier,
das die Versionsgeschichte des FRAMEWORKS selbst (dieses Repository) über den manuell
ausgelösten `/release`-Befehl pflegt.
"""

import re
import subprocess

from config import BASE_DIR
from core.git_runtime import GIT_NETWORK_TIMEOUT_SECONDS, run_git

_VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_BREAKING_MARKERS = ("BREAKING CHANGE", "BREAKING-CHANGE")
_CONVENTIONAL_TYPE_PATTERN = re.compile(r"^(\w+)(!)?(\([^)]*\))?:\s*(.*)$")


def _run_git(*args: str) -> tuple[bool, str]:
    # `git push --tags` u.ä. brauchen das Netzwerk-Timeout; lokale Kommandos sind weit darunter.
    result = run_git(args, cwd=BASE_DIR, timeout=GIT_NETWORK_TIMEOUT_SECONDS)
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def get_latest_tag() -> str | None:
    """Neuester erreichbare Tag von HEAD aus (`git describe`), oder None, wenn noch kein
    einziger Release-Tag existiert – dann ist JEDER Commit seit Projektbeginn "seit dem
    letzten Release"."""
    success, output = _run_git("describe", "--tags", "--abbrev=0")
    return output if success and output else None


def get_commits_since(tag: str | None) -> list[str]:
    """Commit-Subject-Zeilen (erste Zeile jeder Commit-Message) seit `tag`, neueste zuerst.
    `tag=None` liefert die GESAMTE Historie (noch nie ein Release erstellt)."""
    range_arg = f"{tag}..HEAD" if tag else "HEAD"
    success, output = _run_git("log", range_arg, "--pretty=format:%s")
    if not success or not output:
        return []
    return [line for line in output.splitlines() if line.strip()]


def determine_version_bump(commit_subjects: list[str]) -> str | None:
    """Gibt 'major'/'minor'/'patch' zurück, oder None, wenn es gar keine Commits gibt (dann
    hat ein Release keinen Sinn – es gäbe nichts zu berichten)."""
    if not commit_subjects:
        return None
    bump = "patch"  # Standard: irgendetwas hat sich geändert, auch wenn es kein feat/fix ist.
    for subject in commit_subjects:
        if any(marker in subject for marker in _BREAKING_MARKERS):
            return "major"  # Höchste Stufe – kein weiteres Commit kann das noch übertreffen.
        match = _CONVENTIONAL_TYPE_PATTERN.match(subject)
        if not match:
            continue
        commit_type, breaking_bang, _scope, _desc = match.groups()
        if breaking_bang:
            return "major"
        if commit_type == "feat" and bump == "patch":
            bump = "minor"
        # "fix" bestätigt nur den bereits patch-Standard, kein weiterer Vergleich nötig.
    return bump


def bump_version(current: str, bump: str) -> str:
    """Erhöht eine 'vX.Y.Z'-Versionsnummer um genau eine Stufe. Startet bei 'v0.1.0' für den
    allerersten Release (kein Tag existiert), NICHT bei 'v1.0.0' – ein Framework, das noch
    nie einen Release hatte, ist per Konvention vorab der 1.0-Reife."""
    match = _VERSION_PATTERN.match(current)
    if not match:
        major, minor, patch = 0, 0, 0
    else:
        major, minor, patch = (int(x) for x in match.groups())
    if bump == "major":
        return f"v{major + 1}.0.0"
    if bump == "minor":
        return f"v{major}.{minor + 1}.0"
    if match is None:
        return "v0.1.0"
    return f"v{major}.{minor}.{patch + 1}"


def build_release_notes(commit_subjects: list[str]) -> str:
    """Baut echte, kategorisierte Release-Notes aus den tatsächlichen Commit-Subjects –
    kein LLM-Text, der Änderungen erfindet oder umformuliert, sondern die realen
    Commit-Messages selbst, gruppiert nach ihrem Conventional-Commits-Typ."""
    categories: dict[str, list[str]] = {"feat": [], "fix": [], "other": []}
    for subject in commit_subjects:
        match = _CONVENTIONAL_TYPE_PATTERN.match(subject)
        if match and match.group(1) in ("feat", "fix"):
            categories[match.group(1)].append(match.group(4) or subject)
        else:
            categories["other"].append(subject)

    sections = []
    if categories["feat"]:
        sections.append("### ✨ Neue Funktionen\n" + "\n".join(f"- {s}" for s in categories["feat"]))
    if categories["fix"]:
        sections.append("### 🐛 Fehlerbehebungen\n" + "\n".join(f"- {s}" for s in categories["fix"]))
    if categories["other"]:
        sections.append("### 🔧 Weitere Änderungen\n" + "\n".join(f"- {s}" for s in categories["other"]))
    return "\n\n".join(sections) if sections else "Keine Änderungen seit dem letzten Release."


def create_release(version: str, notes: str) -> tuple[bool, str]:
    """
    Erstellt einen echten annotierten Git-Tag, pusht ihn UND erstellt eine echte
    GitHub-Release per `gh release create` – kein reiner Text-Vorschlag. Ein technischer
    Fehlschlag von `gh` (z.B. nicht eingeloggt) lässt den bereits erstellten/gepushten Tag
    bewusst stehen, statt ihn wieder zu löschen – der Tag selbst ist bereits ein echter,
    referenzierbarer Meilenstein, auch ohne GitHub-Release-Seite dazu.
    """
    success_tag, out_tag = _run_git("tag", "-a", version, "-m", f"Release {version}")
    if not success_tag:
        return False, f"Tag konnte nicht erstellt werden: {out_tag}"
    success_push, out_push = _run_git("push", "origin", version)
    if not success_push:
        return False, f"Tag wurde lokal erstellt, aber nicht gepusht: {out_push}"

    result = subprocess.run(
        ["gh", "release", "create", version, "--title", version, "--notes", notes],
        cwd=BASE_DIR, capture_output=True, text=True, timeout=30, encoding="utf-8",
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout).strip()
        return False, f"Tag {version} wurde erstellt und gepusht, GitHub-Release aber fehlgeschlagen: {err}"
    return True, (result.stdout or "").strip()
