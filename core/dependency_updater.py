"""
core/dependency_updater.py – Automatisches Anheben verwundbarer Python-Abhängigkeiten

Realer struktureller Fund: core/dependency_watch.py (--check-dependencies) fand bekannte
CVEs in Workspace-Projekten, meldete sie aber bisher NUR als blockiertes Ticket – ein echtes
Team hat einen Dependabot-/Renovate-artigen Mechanismus, der nicht nur warnt, sondern direkt
einen fertigen Update-PR öffnet, den ein Mensch nur noch reviewen/mergen muss.

Bewusst NUR für Python (requirements.txt via pip-audit) implementiert: pip-audit liefert pro
Schwachstelle bereits eine aufsteigend sortierte Liste kompatibler `fix_versions` direkt aus
der Advisory-Datenbank – ein einfacher, verlässlicher Versions-Ersatz in einer einzeiligen
Pin-Datei. npm audit liefert dagegen keine vergleichbar einfache "eine sichere Version"-Angabe
(oft ein ganzer Abhängigkeitsbaum-Umbau über `npm audit fix`, der selbst Breaking Changes
verursachen kann) – für Node/Rust/Go bleibt es daher bewusst bei der reinen Meldung, bis ein
ebenso robuster, eigenständiger Mechanismus dafür existiert.
"""

import re
from pathlib import Path

from core.verifier import DependencyAuditReport

# Paketname = alles vor dem ersten Versions-/Extras-/Marker-Zeichen einer requirements.txt-Zeile.
_PACKAGE_NAME_PATTERN = re.compile(r"^([A-Za-z0-9_.\-]+)(\[[^\]]*\])?")


def _normalize(name: str) -> str:
    """PEP 503-Normalisierung (grob): Groß-/Kleinschreibung und `_`/`-` sind austauschbar."""
    return name.lower().replace("_", "-")


def _bump_line(line: str, package_lower: str, fix_version: str) -> str | None:
    """
    Ersetzt eine einzelne requirements.txt-Zeile durch eine feste Pin-Version
    (`paket==fix_version`), FALLS die Zeile tatsächlich `package_lower` referenziert (bereits
    normalisiert) – PEP 508-Extras (`paket[extra]`) bleiben erhalten. Gibt None zurück, wenn
    die Zeile leer/ein Kommentar ist oder zu einem anderen Paket gehört; der Aufrufer lässt
    sie dann unverändert.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    match = _PACKAGE_NAME_PATTERN.match(stripped)
    if not match:
        return None
    name, extras = match.group(1), match.group(2) or ""
    if _normalize(name) != package_lower:
        return None
    return f"{name}{extras}=={fix_version}\n"


def apply_python_dependency_fixes(project_dir: Path, vulnerable_reports: list[DependencyAuditReport]) -> list[str]:
    """
    Hebt jedes Paket mit bekannter Schwachstelle UND mindestens einer von pip-audit
    gelieferten `fix_versions`-Angabe in `<project_dir>/requirements.txt` auf die erste
    (niedrigste sichere) Version an. Gibt eine Liste menschenlesbarer Änderungen zurück
    (`"paket: 1.0.0 -> 1.0.1"`) – leer, wenn nichts änderbar war (keine requirements.txt,
    kein pip-audit-Report dabei, keine fix_versions bekannt, kein Treffer beim Zeilen-Abgleich).
    Best effort: liest/schreibt nur diese eine Datei, wirft nie eine Exception – ein
    fehlgeschlagener Update-Versuch darf den restlichen Scan-Zyklus nie stoppen.
    """
    req_file = project_dir / "requirements.txt"
    if not req_file.exists():
        return []

    fixes: dict[str, str] = {}
    old_versions: dict[str, str] = {}
    for report in vulnerable_reports:
        if report.tool != "pip-audit":
            continue
        for vuln in report.vulnerabilities:
            key = _normalize(vuln.package)
            if vuln.fix_versions and key not in fixes:
                fixes[key] = vuln.fix_versions[0]
                old_versions[key] = vuln.version

    if not fixes:
        return []

    try:
        lines = req_file.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError:
        return []

    changed: list[str] = []
    new_lines: list[str] = []
    for line in lines:
        replaced = None
        for pkg_lower, fix_version in fixes.items():
            candidate = _bump_line(line, pkg_lower, fix_version)
            if candidate is not None:
                replaced = candidate
                changed.append(f"{pkg_lower}: {old_versions[pkg_lower]} -> {fix_version}")
                break
        new_lines.append(replaced if replaced is not None else line)

    if not changed:
        return []

    try:
        req_file.write_text("".join(new_lines), encoding="utf-8")
    except OSError:
        return []
    return changed
