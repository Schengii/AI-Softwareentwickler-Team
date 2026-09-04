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
from pathlib import PurePosixPath

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
