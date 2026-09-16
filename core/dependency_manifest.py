"""
core/dependency_manifest.py – Deterministische, konfliktfreie Pflege von requirements.txt

Realer Fund (Analyse auditlog_sentinel, 2026-09-10): `requirements.txt` wurde innerhalb von
73 Sekunden von performance, backend, tester, security, backend und tester PARALLEL per
`write_file` überschrieben – die jeweils letzte Fassung gewann. Der Vollständigkeits-Check
meldete danach weiterhin „Projekt importiert `alembic`, aber kein Manifest listet es“, obwohl
genau dieses eine fehlende Paket bekannt und der Fix trivial war.

Dieses Modul ergänzt EINE Anforderung idempotent (Namensvergleich nach PEP 503), statt die
Datei neu zu schreiben – genutzt vom Agenten-Werkzeug `add_dependency` und vom
deterministischen Auto-Fix der Verifikation (kein LLM-Aufruf nötig).
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_VERSION_CLAUSE = r"\s*(?:===|==|>=|<=|~=|!=|<|>)\s*[A-Za-z0-9.*+!_-]+"
_SPEC_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*"
    r"(?:\[[A-Za-z0-9._,\s-]+\])?"
    rf"(?:{_VERSION_CLAUSE}(?:\s*,{_VERSION_CLAUSE})*)?"
    r"(?:\s*;\s*[A-Za-z0-9_.\s'\"<>=!~()-]+)?$"
)
_write_lock = threading.Lock()


def normalize_package_name(name: str) -> str:
    """PEP 503: Groß-/Kleinschreibung und `-`/`_`/`.` sind gleichwertig."""
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_name(line: str) -> str | None:
    """Paketname einer requirements.txt-Zeile oder None (Kommentar, Option, Leerzeile, URL)."""
    text = line.split("#", 1)[0].strip()
    if not text or text.startswith("-") or "://" in text:
        return None
    match = _NAME_RE.match(text)
    return normalize_package_name(match.group(1)) if match else None


def is_valid_requirement_spec(spec: str) -> bool:
    return bool(_SPEC_RE.match((spec or "").strip()))


def listed_requirements(manifest: Path) -> set[str]:
    if not manifest.is_file():
        return set()
    lines = manifest.read_text(encoding="utf-8", errors="ignore").splitlines()
    return {name for line in lines if (name := requirement_name(line))}


# Formulierungen der Verifier-Befunde, die das fehlende PyPI-Paket bereits exakt benennen
# (core/verifier/completeness.py, core/pre_flight_check.py hidden_runtime_dependency).
_PACKAGE_HINT_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"erwartetes PyPI-Paket\s+`([^`]+)`"),
    re.compile(r"benötigte Paket\s+`([^`]+)`"),
    re.compile(r"Manifest listet\s+`([^`]+)`\s+auf"),
    re.compile(r"^Fuege\s+`([^`]+)`\s+zu requirements\.txt hinzu\.?$"),
)


_PIP_INSTALL_HINT_RE = re.compile(r"(?:\$\s*)?pip3?\s+install\s+([A-Za-z][A-Za-z0-9._-]{1,48})")


def packages_from_install_hints(text: str) -> list[str]:
    """Pakete aus expliziten `pip install <paket>`-Hinweisen in einer Fehlerausgabe.

    Realer Fund (ping_service, 2026-09-16): Starlette meldet beim TestClient-Import
    "requires the httpx2 package ... $ pip install httpx2". Kein ModuleNotFoundError, also griff
    keine der bestehenden Heuristiken - die Testsuite blieb rot, bis ein LLM-Agent es erriet.
    """
    seen: list[str] = []
    for match in _PIP_INSTALL_HINT_RE.finditer(text or ""):
        package = match.group(1).strip().strip(".,;:'\"")
        if package.lower() in ("-r", "pip", "requirements.txt") or package in seen:
            continue
        seen.append(package)
    return seen


def package_from_finding(text: str) -> str | None:
    """Exakt benanntes PyPI-Paket aus einem Verifier-Befund, sonst None (dann entscheidet ein Agent)."""
    for pattern in _PACKAGE_HINT_RES:
        match = pattern.search(text or "")
        if match and is_valid_requirement_spec(match.group(1)):
            return match.group(1).strip()
    return None


DEV_MANIFEST_NAME = "requirements-dev.txt"


def manifest_for_package(project_dir: Path, package: str, importing_file: str = "") -> Path | None:
    """Ziel-Manifest für ein fehlendes Paket: Test-/Werkzeugpakete (siehe
    core/known_pitfalls.DEV_ONLY_PACKAGES) und Pakete, die nur aus Testdateien importiert werden,
    landen in `requirements-dev.txt` statt in den Produktions-Abhängigkeiten.

    None, wenn das Projekt gar keine `requirements.txt` hat (dann wird nichts angelegt).
    """
    from core.known_pitfalls import is_dev_only_package, is_test_path

    primary = primary_python_manifest(project_dir)
    if primary is None:
        return None
    name = requirement_name(package) or package
    if is_dev_only_package(name) or (importing_file and is_test_path(importing_file)):
        return Path(project_dir) / DEV_MANIFEST_NAME
    return primary


def primary_python_manifest(project_dir: Path) -> Path | None:
    """requirements.txt im Projekt-Root, falls vorhanden – niemals neu angelegt (ein Projekt mit
    pyproject.toml/Poetry soll nicht still ein zweites Manifest bekommen)."""
    candidate = Path(project_dir) / "requirements.txt"
    return candidate if candidate.is_file() else None


def merge_preserving_requirements(current: str, new: str) -> tuple[str, list[str]]:
    """Union-Merge zweier requirements-Inhalte: `new` gewinnt, aber Pakete, die NUR in `current`
    stehen, bleiben mit ihrer Originalzeile erhalten.

    Realer Fund (OmniQueue-Lauf 12.09.2026, Befund 3): `backend` und `database` fühlten sich
    beide für `requirements.txt` zuständig. `database` schrieb das Manifest komplett neu und
    kannte `starlette` nicht - das von `backend` eingetragene Paket verschwand still und musste
    erst in der Verifikationsphase mühsam deterministisch nachgetragen werden. Ein reiner
    Warnhinweis (Kollisionserkennung in agents/orchestrator.py) kam dafür zu spät: der
    Datenverlust war zu diesem Zeitpunkt bereits auf der Festplatte.

    Returns:
        (zusammengeführter Inhalt, Liste der geretteten Originalzeilen).
    """
    current_lines = current.splitlines()
    new_names = {name for line in new.splitlines() if (name := requirement_name(line))}
    seen: set[str] = set()
    preserved: list[str] = []
    for line in current_lines:
        name = requirement_name(line)
        if name is None or name in new_names or name in seen:
            continue
        seen.add(name)
        preserved.append(line.strip())
    if not preserved:
        return new, []
    separator = "" if not new or new.endswith("\n") else "\n"
    merged = f"{new}{separator}" + "\n".join(preserved) + "\n"
    return merged, preserved


def add_requirement(manifest: Path, spec: str) -> bool:
    """Trägt `spec` in `manifest` ein. True = hinzugefügt, False = Paket war schon gelistet.

    Raises:
        ValueError: `spec` ist keine gültige Anforderung (z. B. Shell-Syntax oder Leerstring).
    """
    spec = (spec or "").strip()
    if not is_valid_requirement_spec(spec):
        raise ValueError(f"Ungültige Paketangabe: {spec!r} (erwartet z. B. 'alembic' oder 'sqlalchemy>=2.0').")
    name = requirement_name(spec)
    if name is None:
        raise ValueError(f"Ungültige Paketangabe: {spec!r}.")
    # Das Projekt selbst ist kein PyPI-Paket - ein solcher Eintrag lässt `pip install -r` scheitern.
    from core.known_pitfalls import normalize_package_name
    if normalize_package_name(name) == normalize_package_name(manifest.parent.name):
        return False
    with _write_lock:
        existing = manifest.read_text(encoding="utf-8", errors="ignore") if manifest.is_file() else ""
        if name in {n for line in existing.splitlines() if (n := requirement_name(line))}:
            return False
        separator = "" if not existing or existing.endswith("\n") else "\n"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(f"{existing}{separator}{spec}\n", encoding="utf-8")
    return True
