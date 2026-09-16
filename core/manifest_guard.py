"""
core/manifest_guard.py – Erkennt korrupte Dependency-Manifeste, bevor sie auf die Platte
geschrieben werden bzw. bevor die Verifikation sie als Installationsgrundlage benutzt.

Realer Fund (zeiterfassung_app-Projekt, 2026-09-04): `requirements.txt` enthielt wörtlich
    - fastapi
    - sqlalchemy
    + fastapi==0.110.2
    + sqlalchemy==2.0.30
    ...
Ein unverarbeiteter Diff-Hunk landete roh als Dateiinhalt auf der Platte (ein Agent hatte im
Freitext ein Diff zur Illustration seiner Änderung ausgegeben, das ungeprüft übernommen wurde).
Ergebnis: `pip install -r requirements.txt` schlug mit exit_code=1 fehl, wodurch die eigentliche
Testsuite gegen eine nicht aktualisierte Umgebung lief – "Tests bestanden" wurde dadurch
unzuverlässig, ohne dass irgendein bisheriger Check (Lint/SAST/Coverage/Completeness) das
erkannt hätte.

Dieses Modul stellt eine einzige Prüf-Funktion bereit, die an ALLEN Schreibpfaden für
Dependency-Manifeste verwendet wird:
- core/agent_toolbox.py (write_file/edit_file/patch_file-Werkzeuge der Agenten)
- core/workspace.py (Regex-Extraktion aus Freitext-Antworten, Legacy-Pfad)
- core/verifier/completeness.py (Nachträglicher Check bereits vorhandener Dateien, damit auch
  auf anderem Weg entstandene oder historisch gewachsene Korruption erkannt wird)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from core.known_pitfalls import TOXIC_DEPENDENCY_RULES, ToxicDependencyRule  # noqa: F401 - Re-Export

_PYTHON_REQUIREMENTS_MANIFESTS = {
    "requirements.txt", "requirements-dev.txt", "requirements-test.txt", "requirements-prod.txt",
}
_JSON_MANIFESTS = {"package.json", "composer.json"}
_DIFF_HUNK_LINE_PREFIXES = ("@@ ", "diff --git ", "index ")


def _looks_like_diff_line(line: str) -> bool:
    """Erkennt eine einzelne Zeile als typischen Unified-Diff-Rest.

    Echte pip-Kurzoptionen (`-e .`, `-r other.txt`, `-c constraints.txt`, `-i URL`) haben NIE ein
    Leerzeichen direkt nach dem Minus – das unterscheidet sie zuverlässig von einer entfernten
    Diff-Zeile wie `- fastapi`. Eine hinzugefügte Diff-Zeile (`+ fastapi==0.110.2`) hat in
    requirements.txt ohnehin keine gültige Bedeutung, ein führendes "+" kommt dort nie vor.
    """
    stripped = line.rstrip("\r\n")
    if not stripped.strip():
        return False
    if stripped.startswith("+++") or stripped.startswith("---"):
        return True
    if stripped.startswith("+ ") or stripped.startswith("- "):
        return True
    if any(stripped.startswith(prefix) for prefix in _DIFF_HUNK_LINE_PREFIXES):
        return True
    return False


def detect_corrupted_manifest(rel_path: str, content: str) -> str | None:
    """Prüft bekannte Dependency-Manifeste auf typische Schreib-/Merge-Korruption.

    Gibt eine deutschsprachige, handlungsanleitende Fehlermeldung zurück, wenn der Inhalt
    offensichtlich kaputt ist (z.B. ein roh übernommener Diff-Hunk statt der gemergten Datei
    oder ungültiges JSON in package.json), sonst None.
    """
    name = PurePosixPath(rel_path.replace("\\", "/")).name
    content = content or ""

    if name in _PYTHON_REQUIREMENTS_MANIFESTS:
        bad_lines = [
            (i, line) for i, line in enumerate(content.splitlines(), start=1)
            if _looks_like_diff_line(line)
        ]
        if bad_lines:
            examples = "; ".join(f"Zeile {i}: {line.strip()!r}" for i, line in bad_lines[:3])
            return (
                f"'{rel_path}' sieht nach einem unverarbeiteten Diff-Hunk statt einer echten "
                f"Requirements-Datei aus ({examples}). pip kann solche Zeilen nicht installieren "
                "(exit_code != 0). Gib den VOLLSTÄNDIGEN, bereits gemergten Dateiinhalt aus – "
                "jede Zeile ein gültiger Paketname/Versions-Spezifizierer, keine '+'/'-'-Diff-"
                "Präfixe."
            )

    if name in _JSON_MANIFESTS:
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            return (
                f"'{rel_path}' ist kein gültiges JSON ({e}) – vermutlich ein unvollständiger "
                "Diff/Merge statt der vollständigen Datei. Gib den vollständigen, gültigen "
                "JSON-Inhalt aus."
            )

    return None


# ── Toxische Paket-Kollisionen ──────────────────────────────────────────────────────────────
#
# Realer Fund (logipulse-Projekt, 2026-09-10, logs/verification/20260910_084833_logipulse.log):
# `requirements.txt` enthielt `pyjwt>=2.8.0` UND zusätzlich `jwt`. Das PyPI-Paket `jwt` ist ein
# veraltetes, unverwandtes Projekt, das denselben Import-Namespace `jwt` belegt und PyJWT beim
# Installieren überschreibt. Folge: `AttributeError: module 'jwt' has no attribute 'encode'` in
# JEDEM Auth-Test - syntaktisch ist das Manifest völlig gültig, pip meldet exit_code=0, deshalb
# griff keine bisherige Prüfung. Dieselbe Fehlerklasse existiert für `crypto` (unverwandtes
# CLI-Werkzeug), das auf case-insensitiven Dateisystemen (Windows) mit dem `Crypto`-Namespace
# von pycryptodome kollidiert und fast immer `cryptography`/`pycryptodome` meinte.
#
# Die Bereinigung ist deterministisch: Steht die legitime Alternative bereits im Manifest, wird
# der toxische Eintrag entfernt. Fehlt sie, wird er - sofern eindeutig - durch die Alternative
# ersetzt (`import jwt` + `jwt.encode` ist praktisch immer PyJWT), sonst ebenfalls entfernt
# (eine dann tatsächlich fehlende Abhängigkeit meldet completeness.py über
# _missing_known_packages_in_manifest separat).


@dataclass(frozen=True)
class ToxicDependencyFinding:
    """Ein konkreter toxischer Eintrag in einem Requirements-Manifest."""

    line_number: int
    line: str
    package: str
    action: str  # "remove" | "replace"
    replacement: str | None
    reason: str

    def describe(self) -> str:
        if self.action == "replace" and self.replacement:
            outcome = f"ersetzt durch `{self.replacement}`"
        else:
            outcome = "entfernt"
        return f"Zeile {self.line_number}: `{self.line.strip()}` {outcome} – {self.reason}"


# Regeln leben im zentralen Regelwerk core/known_pitfalls.py (hier re-exportiert).

_REQUIREMENT_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def normalize_package_name(name: str) -> str:
    """PEP-503-Normalisierung (`PyJWT`, `py_jwt`, `py.jwt` -> `pyjwt` bzw. `py-jwt`)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_package_name(line: str) -> str | None:
    """Normalisierter Paketname einer Requirements-Zeile - None für Kommentare, pip-Optionen
    (`-r`, `-e`, `--index-url`) und direkte URL-Referenzen."""
    stripped = line.split("#", 1)[0].strip()
    if not stripped or stripped.startswith("-") or "://" in stripped:
        return None
    match = _REQUIREMENT_NAME_RE.match(stripped)
    return normalize_package_name(match.group(1)) if match else None


SELF_REFERENCE_REASON = (
    "verweist auf das Projekt selbst - ein solches Paket gibt es auf PyPI nicht, `pip install -r` "
    "bricht damit komplett ab (realer Fund ping_service, 2026-09-16: `ping-service` in requirements-dev.txt)"
)


def find_toxic_dependencies(
    rel_path: str, content: str, project_name: str | None = None,
) -> list[ToxicDependencyFinding]:
    """Findet bekannte toxische Paket-Kollisionen (siehe TOXIC_DEPENDENCY_RULES) sowie - mit
    `project_name` - Selbstreferenzen auf das eigene Projekt. Andere Dateien liefern immer eine
    leere Liste."""
    if PurePosixPath(rel_path.replace("\\", "/")).name not in _PYTHON_REQUIREMENTS_MANIFESTS:
        return []

    lines = (content or "").splitlines()
    declared = {name for line in lines if (name := _requirement_package_name(line))}
    own_package = normalize_package_name(project_name) if project_name else ""
    findings: list[ToxicDependencyFinding] = []
    for line_number, line in enumerate(lines, start=1):
        package = _requirement_package_name(line)
        if package and own_package and normalize_package_name(package) == own_package:
            findings.append(ToxicDependencyFinding(
                line_number=line_number, line=line, package=package, action="remove",
                replacement=None, reason=SELF_REFERENCE_REASON,
            ))
            continue
        rule = TOXIC_DEPENDENCY_RULES.get(package) if package else None
        if rule is None or package is None:
            continue
        has_legitimate = any(p in declared for p in rule.legitimate_packages)
        if has_legitimate or rule.replacement is None:
            action = "remove"
        else:
            action = "replace"
            # Ein zweiter toxischer Eintrag desselben Pakets darf die Alternative nicht doppelt anlegen.
            declared.add(normalize_package_name(rule.replacement))
        findings.append(ToxicDependencyFinding(
            line_number=line_number, line=line, package=package, action=action,
            replacement=rule.replacement if action == "replace" else None, reason=rule.reason,
        ))
    return findings


def sanitize_requirements(
    rel_path: str, content: str, project_name: str | None = None,
) -> tuple[str, list[ToxicDependencyFinding]]:
    """Entfernt/ersetzt toxische Einträge deterministisch. Gibt den bereinigten Inhalt und die
    angewendeten Funde zurück - ohne Funde bleibt `content` byte-identisch."""
    findings = find_toxic_dependencies(rel_path, content, project_name)
    if not findings:
        return content, []

    by_line = {f.line_number: f for f in findings}
    cleaned: list[str] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        finding = by_line.get(line_number)
        if finding is None:
            cleaned.append(line)
        elif finding.action == "replace" and finding.replacement:
            cleaned.append(finding.replacement)
    text = "\n".join(cleaned)
    if content.endswith("\n") and text:
        text += "\n"
    return text, findings


def describe_toxic_dependencies(rel_path: str, findings: list[ToxicDependencyFinding]) -> str:
    """Deutschsprachige Zusammenfassung für Agenten-Feedback und Verifikations-Reports."""
    details = "; ".join(f.describe() for f in findings)
    return (
        f"'{rel_path}' enthielt toxische Paket-Kollisionen, die einen fremden Import-Namespace "
        f"überschreiben ({details}). Trage NIE beide Varianten ein – nur das legitime Paket."
    )


def sanitize_requirements_file(path: Path) -> list[ToxicDependencyFinding]:
    """Bereinigt eine Requirements-Datei auf der Platte (vor `pip install`). Wirft OSError, wenn
    die Datei nicht gelesen oder geschrieben werden kann - der Aufrufer entscheidet, ob das den
    Lauf blockiert."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    sanitized, findings = sanitize_requirements(path.name, text, project_name=path.parent.name)
    if findings:
        path.write_text(sanitized, encoding="utf-8")
    return findings
