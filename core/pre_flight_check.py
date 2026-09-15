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

from core.verifier.models import _SQLA_ASYNC_ENGINE_RE, _SQLA_SYNC_ENGINE_RE

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


def _check_conflicting_sqlalchemy_engines(sources_by_file: dict[str, str]) -> PreFlightIssue | None:
    """Team-Optimierung (`/goal`-Auftrag: Database Architecture Drift): dieselbe
    Sync/Async-SQLAlchemy-Konflikt-Erkennung wie `core/verifier/completeness.
    _conflicting_sqlalchemy_config()`, aber HIER als schneller, deterministischer
    Vorab-Check VOR der teuren Testsuite - ein Projekt, das `create_engine()` (sync) und
    `create_async_engine()` (async) gleichzeitig verwendet, hat mit hoher Wahrscheinlichkeit
    zwei parallele, inkompatible Engine-/Base-Registries (z.B. `app/database.py` async,
    `app/models.py` daneben eine eigene synchrone Engine) - das muss nicht erst per
    ImportError/OperationalError in der Testsuite auffallen. Dieselbe Alembic-Ausnahme wie
    dort: `alembic/env.py` verwendet idiomatisch eine synchrone Engine fuer Migrationen,
    selbst in einem sonst durchgehend async Projekt - das ist kein Bug."""
    relevant = {
        rel: text for rel, text in sources_by_file.items()
        if "alembic" not in Path(rel).parts and "migrations" not in Path(rel).parts
    }
    sync_files = sorted(rel for rel, text in relevant.items() if _SQLA_SYNC_ENGINE_RE.search(text))
    async_files = sorted(rel for rel, text in relevant.items() if _SQLA_ASYNC_ENGINE_RE.search(text))
    if not (sync_files and async_files):
        return None
    all_files = sorted(set(sync_files) | set(async_files))
    return PreFlightIssue(
        file=all_files[0],
        line=0,
        issue_type="conflicting_sqlalchemy_engines",
        message=(
            f"Projekt mischt synchrones SQLAlchemy (`create_engine()` in "
            f"{', '.join(sync_files)}) mit asynchronem (`create_async_engine()` in "
            f"{', '.join(async_files)}) - typischerweise zwei parallele, inkompatible "
            f"DB-Engines/Base-Registries statt einer konsistenten async- oder "
            f"sync-Anbindung."
        ),
        suggestion=(
            "Entscheide dich fuer GENAU eine DB-Anbindung (async: `create_async_engine` + "
            "`AsyncSession` + `async_sessionmaker` ueberall; sync: `create_engine` + "
            "`sessionmaker` ueberall) und definiere die `Base`-Klasse nur an EINER "
            "zentralen Stelle, die alle Modelle importieren."
        ),
    )


class _ModuleLevelEventLoopVisitor(ast.NodeVisitor):
    """Findet `asyncio.get_event_loop()`-Aufrufe (und darauf verkettete `.time()`-Aufrufe)
    AUSSERHALB jeder Funktion/Methode - siehe _check_module_level_event_loop_calls() unten
    fuer den vollen Kontext."""

    def __init__(self) -> None:
        self.func_depth = 0
        self.hits: list[int] = []

    def _enter_function_scope(self, node: ast.AST) -> None:
        self.func_depth += 1
        self.generic_visit(node)
        self.func_depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._enter_function_scope(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._enter_function_scope(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        self._enter_function_scope(node)

    @staticmethod
    def _is_get_event_loop_call(node: ast.Call) -> bool:
        return isinstance(node.func, ast.Attribute) and node.func.attr == "get_event_loop"

    @classmethod
    def _is_loop_time_call(cls, node: ast.Call) -> bool:
        # Erkennt gezielt `<...>.get_event_loop().time()`/`loop.time()` NUR, wenn der Empfaenger
        # selbst ein get_event_loop()-Aufruf ist - ein stinknormales `time.time()` (Stdlib-Modul
        # `time`, voellig unabhaengig vom Event-Loop) darf NIEMALS als Fund auftauchen.
        return (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "time"
            and isinstance(node.func.value, ast.Call)
            and cls._is_get_event_loop_call(node.func.value)
        )

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if self.func_depth == 0 and (self._is_get_event_loop_call(node) or self._is_loop_time_call(node)):
            self.hits.append(node.lineno)
        self.generic_visit(node)


def _check_module_level_event_loop_calls(sources_by_file: dict[str, str]) -> list[PreFlightIssue]:
    """Team-Optimierung (`/goal`-Auftrag, Schwachstelle 4 aus den Laeufen eventstream_zero/
    aethermesh/chronospulse/incident_pulse): `agents/team_directives.py._ASYNC_EVENT_LOOP_
    DIRECTIVE` verbietet `asyncio.get_event_loop()` auf Modulebene bereits per Prompt-Text -
    das ist aber nur eine Bitte an das LLM, kein Schutz. In Python 3.10+ existiert dort noch
    kein laufender Event-Loop; der Aufruf wirft beim Import durch pytest sofort
    `RuntimeError: There is no current event loop in thread 'MainThread'` und laesst die
    GESAMTE Testsuite schon in der Collection-Phase scheitern - ein bekanntes, mehrfach real
    beobachtetes Fehlerbild. Dieser Check erkennt es statisch per AST VOR dem teuren Testlauf,
    damit der betroffene Agent den Fund gezielt (Datei + Zeile) vorgelegt bekommt, statt erst
    ueber einen kryptischen pytest-Collection-Traceback."""
    issues: list[PreFlightIssue] = []
    for rel_path, source in sources_by_file.items():
        try:
            tree = ast.parse(source, filename=rel_path)
        except SyntaxError:
            continue  # Syntaxfehler werden bereits vom Haupt-Loop in _run_checks() gemeldet.
        visitor = _ModuleLevelEventLoopVisitor()
        visitor.visit(tree)
        for line in visitor.hits:
            issues.append(PreFlightIssue(
                file=rel_path,
                line=line,
                issue_type="module_level_event_loop_call",
                message=(
                    "`asyncio.get_event_loop()`/`.time()` darauf wird auf Modulebene (ausserhalb "
                    "einer Funktion/Methode) aufgerufen - in Python 3.10+ existiert dort noch kein "
                    "laufender Event-Loop, der Aufruf wirft beim Import durch pytest sofort "
                    "`RuntimeError: There is no current event loop in thread 'MainThread'` und "
                    "laesst die gesamte Testsuite schon in der Collection-Phase scheitern."
                ),
                suggestion=(
                    "Fuer Zeitmessungen/Cooldowns/TTLs/Timeouts IMMER `time.monotonic()` statt "
                    "`asyncio.get_event_loop().time()` verwenden. Globale Singletons (Circuit "
                    "Breaker, httpx.AsyncClient, ...) NIEMALS ungeschuetzt auf Modulebene "
                    "instanziieren - ausschliesslich im FastAPI-Lifespan oder einer asynchronen "
                    "Factory-Methode."
                ),
            ))
    return issues


def _resolve_module_file(project_dir: Path, importer_rel_path: str, module: str | None, level: int) -> Path | None:
    """Findet die tatsaechliche .py-Datei/das __init__.py hinter einem lokalen `from ... import`
    - Grundlage fuer _check_imported_names_exist() unten. Gibt None zurueck, wenn das Ziel nicht
    lokal aufloesbar ist (Drittanbieter-Paket, Stdlib, oder schlicht nicht gefunden) - solche
    Faelle sind bewusst kein Fund hier (Drittanbieter/Stdlib werden von den Checks oben bzw. gar
    nicht geprueft, ein nicht gefundenes lokales Modul faellt bereits durch den bestehenden
    Import-Analyse-Zweig oben als eigener Befund auf)."""
    if level and level > 0:
        # Relative Importe: "from . import X" (module=None) zielt auf das Package des
        # importierenden Moduls selbst, "from .foo import X" auf das Sibling-Modul/-Package
        # "foo" darin, "from ..foo import X" eine Ebene hoeher usw.
        base = (project_dir / importer_rel_path).parent
        for _ in range(level - 1):
            base = base.parent
        if not module:
            init_file = base / "__init__.py"
            return init_file if init_file.is_file() else None
        candidate = base
        for part in module.split("."):
            candidate = candidate / part
        return _existing_module_file(candidate)

    if not module:
        return None
    parts = module.split(".")
    for root in (project_dir, project_dir / "app", project_dir / "src"):
        candidate = root
        for part in parts:
            candidate = candidate / part
        resolved = _existing_module_file(candidate)
        if resolved is not None:
            return resolved
    return None


def _existing_module_file(candidate: Path) -> Path | None:
    """`candidate` ist ein Modul-Pfad OHNE Dateiendung (z.B. `app/middleware/rate_limit`) -
    gibt die zugehoerige .py-Datei zurueck, oder deren __init__.py, falls es ein Package ist."""
    py_file = candidate.with_suffix(".py")
    if py_file.is_file():
        return py_file
    init_file = candidate / "__init__.py"
    if init_file.is_file():
        return init_file
    return None


def _collect_defined_names(source: str) -> set[str] | None:
    """Sammelt alle auf Modulebene gebundenen Namen (Klassen, Funktionen, Variablen, Imports) -
    Grundlage fuer _check_imported_names_exist() unten. Gibt None zurueck, wenn das Modul einen
    Wildcard-Import (`from x import *`) enthaelt - in dem Fall lassen sich die tatsaechlich
    verfuegbaren Namen nicht mehr statisch bestimmen, ein Fund waere reines Rauschen."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
                elif isinstance(target, ast.Tuple):
                    names.update(elt.id for elt in target.elts if isinstance(elt, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Import):
            names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if any(alias.name == "*" for alias in node.names):
                return None
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def _check_imported_names_exist(
    project_path: Path, sources_by_file: dict[str, str], seen_issues: set[tuple[str, str, str]],
) -> list[PreFlightIssue]:
    """
    Team-Optimierung (KI-Team-Weiterentwicklung, echter wiederholter Fund: derselbe
    `ImportError: cannot import name 'RateLimitMiddleware' from 'app.middleware.rate_limit'`
    trat in memory/history_default.json an VERSCHIEDENEN Laeufen mehrfach identisch auf, weil
    die importierte Klasse im Zielmodul tatsaechlich anders hiess. Die bestehende Import-Analyse
    oben prueft nur, ob das MODUL existiert (_is_local_module/_check_missing_init) - nie, ob der
    konkret importierte NAME darin auch wirklich definiert ist. ast.parse() erkennt das ohne
    LLM-Aufruf, bevor ein teurer Testlauf denselben Fehler erst zur Laufzeit aufdeckt.

    Bewusst konservativ (lieber einen echten Fund verpassen als einen falschen melden):
    - Ueberspringt jedes Zielmodul mit einem Wildcard-Import (`from x import *`,
      _collect_defined_names() gibt dafuer None zurueck) - die tatsaechlich verfuegbaren Namen
      sind dann statisch nicht mehr bestimmbar.
    - Behandelt `from <package> import <submodul>` als gueltig, wenn `<submodul>.py` bzw.
      `<submodul>/` direkt im Package-Ordner existiert, UNABHAENGIG davon, ob __init__.py den
      Namen explizit importiert/exportiert - Python loest ein Submodul-Import so grundsaetzlich
      immer auf, auch ohne expliziten Re-Export im __init__.py.
    """
    issues: list[PreFlightIssue] = []
    for rel_path, source in sources_by_file.items():
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if any(alias.name == "*" for alias in node.names):
                continue
            target_file = _resolve_module_file(project_path, rel_path, node.module, node.level or 0)
            if target_file is None:
                continue
            try:
                target_rel = str(target_file.relative_to(project_path)).replace("\\", "/")
            except ValueError:
                continue
            target_source = sources_by_file.get(target_rel)
            if target_source is None:
                try:
                    target_source = target_file.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
            defined = _collect_defined_names(target_source)
            if defined is None:
                continue
            package_dir = target_file.parent if target_file.name == "__init__.py" else None
            for alias in node.names:
                imported_name = alias.name
                if imported_name in defined:
                    continue
                if package_dir is not None and (
                    (package_dir / f"{imported_name}.py").is_file() or (package_dir / imported_name).is_dir()
                ):
                    continue  # gueltiges Submodul-Import, siehe Docstring oben
                key = ("import_name", rel_path, imported_name, target_rel)
                if key in seen_issues:
                    continue
                seen_issues.add(key)
                dots = "." * (node.level or 0)
                issues.append(PreFlightIssue(
                    file=rel_path,
                    line=node.lineno,
                    issue_type="unresolved_import_name",
                    message=(
                        f"`from {dots}{node.module or ''} import {imported_name}` - `{imported_name}` "
                        f"ist in `{target_rel}` nicht definiert (weder Klasse, Funktion, Variable "
                        "noch Re-Export)."
                    ),
                    suggestion=(
                        f"Pruefe den tatsaechlichen Namen in `{target_rel}` (haeufige Ursache: "
                        "Klasse/Funktion wurde dort umbenannt, aber nicht alle Imports angepasst) "
                        "und korrigiere den Import."
                    ),
                ))
    return issues


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
        blocking_types = {
            "missing_init", "syntax_error", "unresolved_import_name",
            "conflicting_sqlalchemy_engines", "module_level_event_loop_call",
            "malformed_ini_section",
        }
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


def _check_empty_test_suite(project_path: Path, sources_by_file: dict[str, str]) -> PreFlightIssue | None:
    """
    Team-Optimierung (KI-Team-Zustandsbericht 2026-09-08, echter Fund: memory/backlog.json-
    Ticket `unresolved-governance-critical-feature_pilot_repair`): ein Projekt mit `tests/`-
    Verzeichnis UND `conftest.py`, aber OHNE eine einzige ausfuehrbare Testdatei, wurde bisher
    erst am Ende von Phase 6 (Governance) entdeckt - nachdem Dev-, Test- und Doku-Phase bereits
    vollstaendig (und teuer) gelaufen waren. Ein leeres `tests/`-Verzeichnis ist rein mechanisch
    erkennbar (Dateiname-Muster + `def test_`-Vorkommen zaehlen, kein LLM noetig) und gehoert
    wie die anderen Checks hier VOR die teuren Phasen, nicht als Nachlese danach.

    Bewusst NICHT blockierend (kein Eintrag in PreFlightReport.has_blocking_issues): anders als
    ein fehlender Import bricht ein leeres `tests/`-Verzeichnis den Testlauf nicht hart ab
    (pytest meldet nur "collected 0 items", exit_code 5) - der tester-Agent soll die Datei
    trotzdem schreiben koennen, der Fund ist ein frueher Hinweis, kein Show-Stopper.
    """
    test_dirs = [d for d in (project_path / "tests", project_path / "test") if d.is_dir()]
    if not test_dirs:
        return None
    has_real_test = any(
        re.search(r"^\s*(async\s+)?def\s+test_\w+", src, re.MULTILINE)
        for rel_path, src in sources_by_file.items()
        if any(rel_path.startswith(f"{d.name}/") for d in test_dirs)
    )
    if has_real_test:
        return None
    checked_dirs = ", ".join(f"`{d.name}/`" for d in test_dirs)
    return PreFlightIssue(
        file=f"{test_dirs[0].name}/",
        line=0,
        issue_type="empty_test_suite",
        message=(
            f"{checked_dirs} existiert, enthaelt aber keine einzige ausfuehrbare Testfunktion "
            "(`def test_...`) - die Testsuite ist aktuell funktionslos (pytest wuerde "
            "\"collected 0 items\" melden)."
        ),
        suggestion=(
            f"Lege in {checked_dirs} mindestens eine `test_*.py`-Datei mit echten "
            "`def test_...`-Funktionen an."
        ),
    )


_INDENTED_INI_SECTION_RE = re.compile(r"^[ \t]+\[[^\]]+\]\s*$")


def _check_ini_section_indentation(project_dir: Path) -> list[PreFlightIssue]:
    """
    Team-Optimierung (deterministic_check_suggestion aus team_lessons.jsonl, 2026-09-14):
    ein LLM-generiertes `pytest.ini`/`setup.cfg`/`tox.ini` enthielt gelegentlich eine
    eingerückte Sektionsüberschrift (z.B. `    [pytest]` statt `[pytest]`), typischerweise
    weil das Modell die Datei aus einem eingerückten Codeblock-Kontext heraus generiert hat.
    `configparser` behandelt eine eingerückte Zeile NICHT als neue Sektion, sondern als
    Fortsetzungszeile des vorherigen Werts - die Datei bleibt syntaktisch "gültig", aber
    `[pytest]` existiert dann schlicht nicht, wodurch pytest sämtliche dort gesetzten Optionen
    (z.B. `asyncio_mode = auto`) stillschweigend ignoriert. Das fällt nie als Parse-Fehler auf,
    nur als mysteriöses Testverhalten - genau der Fall, den ein deterministischer Vorab-Check
    (statt Testlauf-Nachlese) verhindern soll.
    """
    issues: list[PreFlightIssue] = []
    for ini_file in project_dir.glob("*.ini"):
        try:
            lines = ini_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, start=1):
            if _INDENTED_INI_SECTION_RE.match(line):
                rel_path = ini_file.name
                issues.append(PreFlightIssue(
                    file=rel_path,
                    line=lineno,
                    issue_type="malformed_ini_section",
                    message=(
                        f"Zeile {lineno} (`{line.strip()}`) ist eingerückt - configparser "
                        "interpretiert eine eingerückte `[section]`-Zeile NICHT als neue "
                        "Sektion, sondern als Fortsetzung des vorherigen Werts. Die Sektion "
                        "existiert dadurch effektiv nicht, alle darunter gesetzten Optionen "
                        "werden stillschweigend ignoriert."
                    ),
                    suggestion=f"Entferne die führenden Leerzeichen/Tabs vor `{line.strip()}` in {rel_path}.",
                ))
    return issues


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

    # Unabhängig von Python-Dateien: eine kaputte pytest.ini/tox.ini/setup.cfg ist bereits
    # ohne einen einzigen gescannten .py-Fund ein reales Problem - dieser Check läuft deshalb
    # VOR dem frühen Return unten, der sich auf die py-basierten Checks weiter unten bezieht.
    for ini_issue in _check_ini_section_indentation(project_path):
        report.issues.append(ini_issue)

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

    sqla_conflict_issue = _check_conflicting_sqlalchemy_engines(sources_by_file)
    if sqla_conflict_issue:
        key = ("conflicting_sqlalchemy_engines", "project_wide", "")
        if key not in seen_issues:
            seen_issues.add(key)
            report.issues.append(sqla_conflict_issue)

    for event_loop_issue in _check_module_level_event_loop_calls(sources_by_file):
        key = ("module_level_event_loop_call", event_loop_issue.file, str(event_loop_issue.line))
        if key not in seen_issues:
            seen_issues.add(key)
            report.issues.append(event_loop_issue)

    empty_test_issue = _check_empty_test_suite(project_path, sources_by_file)
    if empty_test_issue:
        key = ("empty_test_suite", empty_test_issue.file, "")
        if key not in seen_issues:
            seen_issues.add(key)
            report.issues.append(empty_test_issue)

    report.issues.extend(_check_imported_names_exist(project_path, sources_by_file, seen_issues))


def format_pre_flight_issues_for_fix(report: PreFlightReport) -> str:
    """Formatiert die Befunde als kompakten Fix-Auftrag fuer den backend-Agenten."""
    if report.passed:
        return ""
    lines = [
        "Vorab-Import-Check hat Probleme gefunden (bevor Tests laufen koennen):",
        "",
    ]
    # Team-Optimierung (echter Fund: `blocking` listete ursprünglich nur 3 fest verdrahtete
    # issue_types auf - jeder seither hinzugekommene Check (conflicting_sqlalchemy_engines,
    # module_level_event_loop_call, empty_test_suite, malformed_ini_section, ...) erzeugte zwar
    # einen Befund (report.passed wurde korrekt False), der aber NIE im an den Fix-Agenten
    # gesendeten Text auftauchte - der Agent bekam keinerlei Hinweis, was zu tun ist, und der
    # Fix-Loop drehte sich bis zum Kein-Fortschritt-Abbruch ergebnislos. Jetzt landet JEDER
    # Befund außer den beiden eigenen Dependency-Kategorien (die unten separat und ausführlicher
    # formatiert werden) in der "Blockierende Befunde"-Liste - neue Check-Typen erscheinen damit
    # automatisch, ohne dass diese Funktion jedes Mal manuell erweitert werden muss.
    _dependency_issue_types = {"missing_dependency", "hidden_runtime_dependency"}
    blocking = [i for i in report.issues if i.issue_type not in _dependency_issue_types]
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
