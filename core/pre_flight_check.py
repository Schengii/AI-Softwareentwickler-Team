"""
core/pre_flight_check.py - Deterministischer Vorab-Import-Check vor der Testsuite.

Realer Fund (Analyse 2026-09-06): Zirkulaere Imports und fehlende Module werden erst durch
die teure Verifikation entdeckt. Ein Projekt, das an einem ModuleNotFoundError scheitert,
benoetigt keinen vollstaendigen pytest-Lauf. ast.parse() erkennt das in Millisekunden ohne LLM.

Typische Probleme die dieser Check verhindert:
- ModuleNotFoundError: No module named app.kafka_client (fehlende Datei)
- Fehlende __init__.py in Unterordnern (relative Imports schlagen fehl)
- Drittanbieter-Paket in Code, aber nicht in requirements.txt
- Syntax-Fehler in Python-Dateien die den Testlauf sofort abwuergen

Bewusst kein zirkulaerer Import-Check via toposort: zirkulaere Imports sind subtil und
kontextabhaengig. Falsch-positive wuerden unnoetige Fix-Auftraege ausloesen. Der echte
Testlauf ist der korrekte Ort dafuer - dieser Check konzentriert sich auf simple,
eindeutige Faelle.
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Standardbibliothek-Module, die kein requirements.txt-Eintrag brauchen.
# sys.stdlib_module_names ist verfuegbar ab Python 3.10.
_STDLIB_MODULES: frozenset[str] = frozenset(
    getattr(sys, "stdlib_module_names", set()) or {
        "abc", "ast", "asyncio", "builtins", "collections", "contextlib", "copy",
        "dataclasses", "datetime", "enum", "functools", "gc", "hashlib", "http",
        "importlib", "inspect", "io", "itertools", "json", "logging", "math",
        "os", "pathlib", "pickle", "platform", "queue", "random", "re", "shutil",
        "signal", "socket", "sqlite3", "ssl", "string", "struct", "subprocess",
        "sys", "tempfile", "threading", "time", "traceback", "typing", "unittest",
        "urllib", "uuid", "warnings", "weakref", "xml", "zipfile",
        "pytest", "_pytest", "_thread", "_collections_abc",
    }
)

# Verzeichnisse, die beim Scan uebersprungen werden (generiert/kein Team-Code).
_SKIP_DIRS: frozenset[str] = frozenset({
    ".venv", "venv", "__pycache__", "node_modules", "dist", "build",
    ".git", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "htmlcov",
    "site-packages",
})

# Bekannte Import-zu-Paket-Mappings (haeufige Faelle wo Importname != Paketname)
_IMPORT_TO_PKG: dict[str, str] = {
    "cv2": "opencv_python",
    "PIL": "pillow",
    "sklearn": "scikit_learn",
    "bs4": "beautifulsoup4",
    "yaml": "pyyaml",
    "dotenv": "python_dotenv",
    "dateutil": "python_dateutil",
    "attr": "attrs",
    "jose": "python_jose",
    "passlib": "passlib",
    "multipart": "python_multipart",
}

# Team-Optimierung (Retrospektive 2026-09-07, aus 3 team_lessons-Eintraegen destilliert):
# diese drei Muster sind Laufzeit-Abhaengigkeiten, die eine reine Import-Analyse (oben)
# NIE findet, weil das Paket selbst nirgends direkt importiert wird - es wird erst
# TRANSITIV zur Laufzeit von einer Drittanbieter-Bibliothek nachgeladen und faellt dann
# nicht beim Start, sondern erst beim ECHTEN Aufruf des jeweiligen Codepfads auf:
#   - SQLAlchemy create_async_engine() braucht "greenlet" (SQLAlchemy importiert es lazy)
#   - FastAPI OAuth2PasswordRequestForm/Form(...) braucht "python-multipart" zum Parsen
#     von Formulardaten (FastAPI prueft das nur zur Laufzeit beim ersten Form-Request)
#   - passlib's CryptContext(schemes=["bcrypt"]) bricht mit bcrypt>=4.1 (bcrypt.__about__
#     wurde entfernt, passlibs interner Selbsttest schlaegt fehl)
# Jeweils ein (Signal-Regex im Quelltext, benoetigtes Paket, Meldung) - regex statt AST,
# weil das Signal (Klassenname/Funktionsaufruf) unabhaengig davon erkannt werden soll, WIE
# es importiert wurde (from-import, aliasiert, etc.).
_HIDDEN_RUNTIME_DEPENDENCIES: tuple[tuple[re.Pattern, str, str], ...] = (
    (
        re.compile(r"\bcreate_async_engine\s*\("),
        "greenlet",
        (
            "`create_async_engine(...)` wird verwendet, aber SQLAlchemy braucht "
            "`greenlet` zur Laufzeit dafuer (lazy import, KEIN direkter Code-Import) - "
            "fehlt es, schlaegt jede DB-Operation mit \"the greenlet library is "
            "required\" fehl."
        ),
    ),
    (
        re.compile(r"\bOAuth2PasswordRequestForm\b|\bForm\s*\("),
        "python_multipart",
        (
            "`OAuth2PasswordRequestForm`/`Form(...)` wird verwendet, aber FastAPI "
            "braucht `python-multipart` zur Laufzeit zum Parsen von Formulardaten - "
            "fehlt es, schlaegt der Endpunkt erst beim ECHTEN Aufruf fehl (kein "
            "Fehler beim Start)."
        ),
    ),
)


def _check_passlib_bcrypt_pin(project_dir: Path, sources_by_file: dict[str, str]) -> PreFlightIssue | None:
    """Prueft auf die bekannte passlib+bcrypt-Inkompatibilitaet (siehe
    _HIDDEN_RUNTIME_DEPENDENCIES-Docstring oben): CryptContext(schemes=[..."bcrypt"...])
    im Code, aber `bcrypt` in requirements.txt ohne oberes Versions-Limit - bcrypt>=4.1
    bricht passlibs internen Selbsttest. Separat von _HIDDEN_RUNTIME_DEPENDENCIES, weil
    hier NICHT das Fehlen eines Pakets das Problem ist, sondern eine fehlende Versions-
    Obergrenze eines bereits vorhandenen Pakets."""
    bcrypt_scheme_re = re.compile(r"CryptContext\s*\([^)]*bcrypt", re.DOTALL)
    hit_file = next((f for f, src in sources_by_file.items() if bcrypt_scheme_re.search(src)), None)
    if not hit_file:
        return None
    for req_name in ("requirements.txt", "requirements-dev.txt", "requirements_dev.txt"):
        req_file = project_dir / req_name
        if not req_file.exists():
            continue
        try:
            for line in req_file.read_text(encoding="utf-8", errors="replace").splitlines():
                stripped = line.strip().lower()
                if not stripped.startswith("bcrypt"):
                    continue
                # Irgendeine Obergrenze (<, <=, ==) gilt als abgesichert - nur ein
                # unbegrenztes "bcrypt" oder ein reines Untergrenzen-Pin (>=) ist riskant.
                if "<" in stripped or "==" in stripped:
                    return None
        except OSError:
            pass
    return PreFlightIssue(
        file=hit_file,
        line=0,
        issue_type="hidden_runtime_dependency",
        message=(
            "`CryptContext(..., schemes=[\"bcrypt\"])` (passlib) wird verwendet, aber "
            "`bcrypt` ist in requirements.txt nicht auf `<4.1` gedeckelt - bcrypt>=4.1 "
            "entfernt `bcrypt.__about__`, passlibs interner Selbsttest schlaegt fehl "
            "(\"password cannot be longer than 72 bytes\")."
        ),
        suggestion="Pinne `bcrypt<4.1` in requirements.txt.",
    )


@dataclass
class PreFlightIssue:
    """Ein einzelner gefundener Vorab-Import-Befund."""
    file: str
    line: int
    issue_type: str    # "missing_init" | "missing_dependency" | "syntax_error"
    message: str
    suggestion: str = ""


@dataclass
class PreFlightReport:
    """Ergebnis des Pre-Flight-Checks fuer ein Projektverzeichnis."""
    project_dir: str
    issues: list[PreFlightIssue] = field(default_factory=list)
    files_checked: int = 0
    error: str = ""

    @property
    def passed(self) -> bool:
        """True, wenn keine Befunde gefunden wurden."""
        return len(self.issues) == 0 and not self.error

    @property
    def has_blocking_issues(self) -> bool:
        """True, wenn Befunde vorliegen, die einen Testlauf mit hoher Wahrscheinlichkeit
        zum Scheitern bringen (missing_init, syntax_error)."""
        blocking_types = {"missing_init", "syntax_error"}
        return any(i.issue_type in blocking_types for i in self.issues)

    def format_for_agent(self) -> str:
        """Kompaktes, fuer den Fix-Agenten lesbares Format."""
        if self.error:
            return f"Pre-Flight-Check konnte nicht ausgefuehrt werden: {self.error}"
        if self.passed:
            return (
                f"Pre-Flight-Check bestanden "
                f"({self.files_checked} Python-Dateien geprueft, keine Befunde)."
            )
        lines = [
            f"Pre-Flight-Check: {len(self.issues)} Befund(e) in {self.files_checked} Dateien",
            "",
        ]
        for issue in self.issues:
            loc = f"{issue.file}:{issue.line}" if issue.line else issue.file
            lines.append(f"- [{issue.issue_type}] {loc}: {issue.message}")
            if issue.suggestion:
                lines.append(f"  Loesung: {issue.suggestion}")
        return "\n".join(lines)


def _collect_python_files(project_dir: Path) -> list[Path]:
    """Alle *.py im Projektordner, _SKIP_DIRS ausgeschlossen."""
    py_files: list[Path] = []
    try:
        for item in project_dir.rglob("*.py"):
            parts = item.relative_to(project_dir).parts[:-1]
            if any(part in _SKIP_DIRS for part in parts):
                continue
            py_files.append(item)
    except (OSError, PermissionError):
        pass
    return sorted(py_files)


def _parse_requirements(project_dir: Path) -> set[str]:
    """Gibt normalisierte Paketnamen aus requirements.txt zurueck.
    Leere Menge, wenn die Datei nicht existiert oder nicht lesbar ist."""
    packages: set[str] = set()
    for req_name in ("requirements.txt", "requirements-dev.txt", "requirements_dev.txt"):
        req_file = project_dir / req_name
        if not req_file.exists():
            continue
        try:
            for line in req_file.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-r"):
                    continue
                pkg = line.split("[")[0]
                for sep in (">=", "==", "<=", "!=", "~=", ">", "<"):
                    pkg = pkg.split(sep)[0]
                pkg = pkg.strip()
                if pkg and not pkg.startswith("-"):
                    packages.add(pkg.lower().replace("-", "_"))
                    packages.add(pkg.lower())
        except OSError:
            pass
    return packages


def _get_top_level_import(module: str) -> str:
    """Extrahiert den Top-Level-Modulnamen (z.B. 'os.path' -> 'os')."""
    return module.split(".")[0]


def _is_local_module(top: str, project_dir: Path) -> bool:
    """True, wenn der Top-Level-Name ein lokales Modul/Paket im Projektordner ist."""
    if (project_dir / top).is_dir():
        return True
    if (project_dir / f"{top}.py").is_file():
        return True
    for sub in ("app", "src"):
        sub_dir = project_dir / sub
        if sub_dir.is_dir():
            if (sub_dir / top).is_dir() or (sub_dir / f"{top}.py").is_file():
                return True
    return False


def _check_missing_init(
    module: str,
    line: int,
    rel_path: str,
    project_dir: Path,
) -> PreFlightIssue | None:
    """Prueft auf fehlende __init__.py in bekannten Paket-Ordnern."""
    parts = module.split(".")
    if len(parts) < 2:
        return None
    pkg_dir = project_dir / parts[0]
    if pkg_dir.is_dir() and not (pkg_dir / "__init__.py").exists():
        return PreFlightIssue(
            file=rel_path,
            line=line,
            issue_type="missing_init",
            message=(
                f"Paket `{parts[0]}/` hat keine `__init__.py`; "
                f"`import {module}` schlaegt fehl."
            ),
            suggestion=f"Lege `{parts[0]}/__init__.py` an (darf leer sein).",
        )
    return None


def run_pre_flight_check(project_dir: str | Path) -> PreFlightReport:
    """Fuehrt den deterministischen Vorab-Import-Check aus und gibt einen PreFlightReport zurueck.

    Sicher gegen jeden Projektinhalt: kein eval(), kein import - nur ast.parse() und
    Dateisystem-Checks. Kann nie durch fehlerhaften Projekt-Code crashen.
    Best-Effort: bei internem Fehler wird report.error gesetzt, nie eine Exception geworfen.
    """
    project_path = Path(project_dir)
    report = PreFlightReport(project_dir=str(project_dir))
    try:
        _run_checks(project_path, report)
    except Exception as exc:  # noqa: BLE001
        report.error = f"{type(exc).__name__}: {exc}"
    return report


def _run_checks(project_path: Path, report: PreFlightReport) -> None:
    """Interne Implementierung des Checks - wirft Exceptions, die run_pre_flight_check abfaengt."""
    if not project_path.exists() or not project_path.is_dir():
        report.error = f"Projektverzeichnis existiert nicht: {project_path}"
        return

    py_files = _collect_python_files(project_path)
    report.files_checked = len(py_files)
    if not py_files:
        return

    known_packages = _parse_requirements(project_path)
    # Installierte Pakete aus sys.modules als zusaetzliche bekannte Pakete akzeptieren
    try:
        for mod_name in list(sys.modules.keys()):
            top = _get_top_level_import(mod_name).lower().replace("-", "_")
            if top:
                known_packages.add(top)
    except Exception:  # noqa: BLE001
        pass

    # Deduplizierungs-Set: verhindert denselben Befund mehrfach (z.B. 10 Dateien importieren
    # dasselbe fehlende Paket - nur einmal melden, nicht 10 Mal).
    seen_issues: set[tuple[str, str, str]] = set()

    # Fuer die projektweiten Muster-Checks (_HIDDEN_RUNTIME_DEPENDENCIES, passlib+bcrypt
    # unten) muessen alle Quelltexte vorliegen, BEVOR diese Checks laufen - ein Signal
    # (z.B. create_async_engine) kann in einer anderen Datei stehen als requirements.txt
    # geprueft wird gegen.
    sources_by_file: dict[str, str] = {}

    for py_file in py_files:
        rel_path = str(py_file.relative_to(project_path)).replace("\\", "/")
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        sources_by_file[rel_path] = source

        # 1. Syntax-Check via ast.parse
        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError as se:
            key = (rel_path, "syntax_error", str(se.lineno))
            if key not in seen_issues:
                seen_issues.add(key)
                report.issues.append(PreFlightIssue(
                    file=rel_path,
                    line=se.lineno or 0,
                    issue_type="syntax_error",
                    message=f"Python-Syntaxfehler: {se.msg}",
                    suggestion=(
                        "Behebe den Syntaxfehler "
                        "(haeufig: fehlende Klammer, Einrueckung, Doppelpunkt)."
                    ),
                ))
            continue

        # 2. Import-Analyse
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            imp_line = node.lineno
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                # Relative Importe: from . import X, from .models import User,
                # from ..utils import helper -> node.level > 0
                # Auch bei from .models import User ist node.module = 'models' (ohne Punkt),
                # aber node.level = 1 - das MUSS ignoriert werden (kein Drittanbieter-Paket).
                if node.level and node.level > 0:
                    continue  # Alle relativen Importe ueberspringen
                if node.module is None:
                    continue
                modules = [node.module]

            for module in modules:
                top = _get_top_level_import(module)
                if not top or top.startswith("_"):
                    continue
                if top in _STDLIB_MODULES:
                    continue

                if _is_local_module(top, project_path):
                    # Lokales Modul: pruefe auf fehlende __init__.py
                    issue = _check_missing_init(module, imp_line, rel_path, project_path)
                    if issue:
                        key = ("any", issue.issue_type, issue.message[:80])
                        if key not in seen_issues:
                            seen_issues.add(key)
                            report.issues.append(issue)
                    continue

                # Drittanbieter-Paket: gegen requirements.txt pruefen
                top_norm = top.lower().replace("-", "_")
                canonical = _IMPORT_TO_PKG.get(top, _IMPORT_TO_PKG.get(top_norm, top_norm))
                if (
                    canonical not in known_packages
                    and top_norm not in known_packages
                    and top not in known_packages
                ):
                    key = ("dep", "missing_dependency", canonical)
                    if key not in seen_issues:
                        seen_issues.add(key)
                        report.issues.append(PreFlightIssue(
                            file=rel_path,
                            line=imp_line,
                            issue_type="missing_dependency",
                            message=(
                                f"Paket `{top}` wird importiert, "
                                f"fehlt aber in requirements.txt."
                            ),
                            suggestion=f"Fuege `{top}` zu requirements.txt hinzu.",
                        ))

    # Projektweite Muster-Checks fuer bekannte versteckte Laufzeit-Abhaengigkeiten
    # (siehe _HIDDEN_RUNTIME_DEPENDENCIES-Docstring): erst NACH der Datei-Schleife, weil
    # sie ueber alle gesammelten Quelltexte hinweg pruefen, nicht nur pro Datei.
    for pattern, required_pkg, message in _HIDDEN_RUNTIME_DEPENDENCIES:
        if required_pkg in known_packages:
            continue
        hit = next(
            ((f, src) for f, src in sources_by_file.items() if pattern.search(src)),
            None,
        )
        if not hit:
            continue
        hit_file, src = hit
        line = next((i + 1 for i, src_line in enumerate(src.splitlines()) if pattern.search(src_line)), 0)
        key = ("hidden_dep", required_pkg, hit_file)
        if key not in seen_issues:
            seen_issues.add(key)
            report.issues.append(PreFlightIssue(
                file=hit_file,
                line=line,
                issue_type="hidden_runtime_dependency",
                message=message,
                suggestion=f"Fuege `{required_pkg.replace('_', '-')}` zu requirements.txt hinzu.",
            ))

    bcrypt_issue = _check_passlib_bcrypt_pin(project_path, sources_by_file)
    if bcrypt_issue:
        key = ("hidden_dep", "bcrypt_pin", bcrypt_issue.file)
        if key not in seen_issues:
            seen_issues.add(key)
            report.issues.append(bcrypt_issue)


def format_pre_flight_issues_for_fix(report: PreFlightReport) -> str:
    """Formatiert die Befunde als kompakten Fix-Auftrag fuer den backend-Agenten."""
    if report.passed:
        return ""
    lines = [
        "Vorab-Import-Check hat Probleme gefunden (bevor Tests laufen koennen):",
        "",
    ]
    blocking = [i for i in report.issues if i.issue_type in {"missing_init", "syntax_error"}]
    deps = [i for i in report.issues if i.issue_type == "missing_dependency"]
    hidden_deps = [i for i in report.issues if i.issue_type == "hidden_runtime_dependency"]

    if blocking:
        lines.append("Blockierende Befunde (verhindern jeden Testlauf):")
        for issue in blocking[:10]:
            loc = f"{issue.file}:{issue.line}" if issue.line else issue.file
            lines.append(f"  - [{issue.issue_type}] {loc}: {issue.message}")
            if issue.suggestion:
                lines.append(f"    Loesung: {issue.suggestion}")

    if deps:
        lines.append("")
        lines.append("Fehlende Dependencies (requirements.txt):")
        for issue in deps[:10]:
            lines.append(f"  - {issue.message}")
            if issue.suggestion:
                lines.append(f"    Loesung: {issue.suggestion}")

    if hidden_deps:
        lines.append("")
        lines.append(
            "Versteckte Laufzeit-Abhaengigkeiten (schlagen erst beim ECHTEN Aufruf fehl, "
            "nicht beim Start - aus frueheren Team-Lektionen bekannt):"
        )
        for issue in hidden_deps[:10]:
            loc = f"{issue.file}:{issue.line}" if issue.line else issue.file
            lines.append(f"  - {loc}: {issue.message}")
            if issue.suggestion:
                lines.append(f"    Loesung: {issue.suggestion}")

    lines.append("")
    lines.append("Behebe AUSSCHLIESSLICH diese Befunde. Erstelle keine neuen Features.")
    return "\n".join(lines)
