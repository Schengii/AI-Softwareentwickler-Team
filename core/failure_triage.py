"""
core/failure_triage.py – Deterministische Triage STRUKTURELLER Testfehler (Syntax-, Import-,
Collection- und Settings-Fehler) für den Fix-Loop in agents/orchestrator/verification.py.

Systemische Schwachstellen aus realen Läufen (u. a. workspace/vaultguard):
1. Interface-Drift: Architekt/Backend definieren `class EncryptionService` mit `encrypt()`, der
   Tester importiert `from app.core.encryption import encrypt`. pytest bricht schon beim
   Einsammeln ab. Die bisherige Regel "Owner des Zielmoduls ergänzt das Symbol" ließ den
   Backend-Agenten eine redundante freie Funktion nachrüsten - oder, wenn das Modul nicht als
   lokal erkannt wurde, den Refactoring-Agenten requirements.txt editieren.
2. Collection-Fehler kamen beim Fix-Agenten nur als letzte 800 Zeichen der Rohausgabe an; die
   eigentliche `E   ImportError`-Zeile fehlte dort oft.
3. Settings-Klassen ohne Dev-Defaults ließen App-Import und Tests ohne `.env` scheitern.

Entscheidungsregel "Wer weicht vom Vertrag ab?":
- `interface_contract.json` (vom Architekten geschrieben) ist die Quelle der Wahrheit.
- Ohne Vertrag entscheidet der reale Code des Anbieter-Moduls: Existiert das importierte Symbol
  dort in anderer Form (Methode einer Klasse, ähnlicher Name), ist der KONSUMENT zuständig.
  Fehlt es ersatzlos, ist der ANBIETER zuständig.

Rein regelbasiert (AST + Regex), kein LLM-Aufruf.
"""

from __future__ import annotations

import ast
import difflib
import json
import logging
import os
import re
from collections.abc import Collection, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Protocol, TypeVar

from core.verifier.models import VENV_DIRNAME

logger = logging.getLogger(__name__)

INTERFACE_CONTRACT_FILE = "interface_contract.json"

KIND_SYNTAX_ERROR = "syntax_error"
KIND_INTERFACE_DRIFT = "interface_drift"
KIND_MISSING_SYMBOL = "missing_symbol"
KIND_MISSING_LOCAL_MODULE = "missing_local_module"
KIND_TEST_IMPORT_PATH = "test_import_path"
KIND_SETTINGS_DEFAULTS = "settings_defaults"
KIND_ASYNC_SYNC_MISMATCH = "async_sync_mismatch"

MANIFEST_GUARD_NOTE = (
    "⛔ Strukturfehler im Code: Ändere KEINE Dependency-Manifeste (requirements*.txt, Pipfile) – "
    "sie sind nicht die Ursache, Änderungen daran werden in diesem Fix-Schritt automatisch "
    "zurückgesetzt."
)

_IGNORED_DIR_NAMES = frozenset({
    ".git", ".venv", "venv", VENV_DIRNAME, "node_modules", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "dist", "build", "site-packages",
})
_MAX_SCANNED_FILES = 2000

_IMPORT_NAME_RE = re.compile(r"ImportError: cannot import name ['\"](\w+)['\"] from ['\"]([\w.]+)['\"]")
_MODULE_NOT_FOUND_RE = re.compile(r"ModuleNotFoundError: No module named ['\"]([\w.]+)['\"]")
_TEST_MODULE_IMPORT_RE = re.compile(r"ImportError while (?:importing test module|loading conftest) ['\"]([^'\"]+)['\"]")
_COLLECTING_RE = re.compile(r"ERROR collecting (\S+)")
_SYNTAX_ERROR_RE = re.compile(r"^(?:E\s+)?(SyntaxError|IndentationError|TabError): (.*)$", re.MULTILINE)
_FILE_LINE_RE = re.compile(r'File "([^"]+)", line (\d+)')
_COMPILE_LOCATION_RE = re.compile(r"\(([^()\s]+\.py), line (\d+)\)")
_SETTINGS_VALIDATION_RE = re.compile(r"\d+ validation errors? for (\w+)")
_MISSING_FIELD_RE = re.compile(r"^(?:E\s+)?([A-Za-z_]\w*)[ \t]*\r?\n(?:E\s+)?\s+Field required", re.MULTILINE)
_COLLECTION_FAILURE_RE = re.compile(
    r"ERROR collecting|errors? during collection|ImportError while (?:importing test module|loading conftest)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StructuralTriage:
    """Ergebnis der Triage: WAS kaputt ist, WELCHE Datei korrigiert werden muss und eine
    konkrete Handlungsanweisung für den Fix-Agenten."""
    kind: str
    responsible_file: str | None
    fallback_agent: str
    diagnosis: str


@dataclass(frozen=True)
class ModuleInterface:
    """Öffentliche Oberfläche eines Python-Moduls laut AST."""
    exports: dict[str, str] = field(default_factory=dict)   # Name -> class|function|instance|constant|import
    methods: dict[str, str] = field(default_factory=dict)   # Methodenname -> Klassenname (erste Fundstelle)


class _FailureLike(Protocol):
    test_id: str
    message: str


_F = TypeVar("_F", bound=_FailureLike)


# ── Pfad-Helfer ────────────────────────────────────────────────────────────────────────────


def _norm(path: str) -> str:
    return path.replace("\\", "/").strip()


def is_test_file(path: str) -> bool:
    """True für Testcode (test_*.py, *_test.py, conftest.py, alles unter tests/)."""
    p = PurePosixPath(_norm(path))
    return (
        p.name.startswith("test_") or p.name.endswith("_test.py") or p.name == "conftest.py"
        or "tests" in p.parts[:-1]
    )


def _to_project_rel(raw: str, root: Path | None, known_files: Collection[str]) -> str | None:
    """Wandelt einen Traceback-Pfad in einen projektrelativen POSIX-Pfad um (None = außerhalb)."""
    norm = _norm(raw)
    if root is not None:
        try:
            candidate = Path(raw)
            absolute = candidate if candidate.is_absolute() else root / candidate
            return _norm(str(absolute.resolve().relative_to(root.resolve())))
        except (ValueError, OSError):
            pass
    lowered = norm.lower()
    best: str | None = None
    for known in known_files:
        k = known.lower()
        # Voller Pfad endet auf eine bekannte Datei ODER nur der Dateiname ist bekannt
        # (`SyntaxError: invalid syntax (auth.py, line 12)`).
        matches = lowered == k or lowered.endswith("/" + k) or ("/" not in lowered and k.endswith("/" + lowered))
        if matches and (best is None or len(known) > len(best)):
            best = known
    if best is not None:
        return best
    if PurePosixPath(norm).is_absolute() or re.match(r"^[A-Za-z]:/", norm):
        return None
    return norm


def _iter_project_py_files(root: Path) -> Iterator[Path]:
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _IGNORED_DIR_NAMES and not d.startswith(".")]
        for name in filenames:
            if name.endswith(".py"):
                count += 1
                if count > _MAX_SCANNED_FILES:
                    return
                yield Path(dirpath) / name


def _top_level_exists(top: str, root: Path | None, known_files: Collection[str]) -> bool:
    if any(k == f"{top}.py" or k.startswith(f"{top}/") for k in known_files):
        return True
    return root is not None and ((root / top).is_dir() or (root / f"{top}.py").is_file())


def is_local_module(module: str, project_dir: Path | str | None, known_files: Iterable[str] = ()) -> bool:
    """True, wenn der Top-Level-Name von `module` ein Projektmodul ist (Datei-Owner ODER
    Dateisystem) - dann ist ein Import-Fehler ein Code-, kein Dependency-Problem. Die frühere,
    rein auf file_owners gestützte Prüfung hielt Module aus früheren Läufen für Drittanbieter-
    Pakete und schickte den Refactoring-Agenten an requirements.txt."""
    top = module.split(".")[0]
    for rel in known_files:
        p = PurePosixPath(_norm(rel))
        if (p.suffix == ".py" and p.stem == top) or top in p.parts[:-1]:
            return True
    if project_dir is None:
        return False
    root = Path(project_dir)
    return any((base / top).is_dir() or (base / f"{top}.py").is_file() for base in (root, root / "src"))


def module_to_file(module: str, root: Path | None, known_files: Collection[str]) -> str | None:
    """Projektdatei eines Punkt-Modulnamens (auch Paket-__init__ und src-Layout)."""
    base = module.replace(".", "/")
    for candidate in (f"{base}.py", f"{base}/__init__.py", f"src/{base}.py", f"src/{base}/__init__.py"):
        if candidate in known_files or (root is not None and (root / candidate).is_file()):
            return candidate
    return None


# ── Modul-Oberfläche & Schnittstellen-Vertrag ──────────────────────────────────────────────


def _top_level_statements(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    """Top-Level-Anweisungen inkl. der Rümpfe von if/try/with (z. B. optionale Imports)."""
    for node in body:
        if isinstance(node, (ast.If, ast.With)):
            yield from _top_level_statements(node.body)
            yield from _top_level_statements(getattr(node, "orelse", []))
        elif isinstance(node, ast.Try):
            for block in (node.body, node.orelse, node.finalbody, *[h.body for h in node.handlers]):
                yield from _top_level_statements(block)
        else:
            yield node


def parse_module_interface(source: str) -> ModuleInterface | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    exports: dict[str, str] = {}
    methods: dict[str, str] = {}
    for node in _top_level_statements(tree.body):
        if isinstance(node, ast.ClassDef):
            exports[node.name] = "class"
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not item.name.startswith("__"):
                    methods.setdefault(item.name, node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            exports[node.name] = "function"
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for name_node in ast.walk(target):
                    if isinstance(name_node, ast.Name):
                        exports[name_node.id] = "constant" if name_node.id.isupper() else "instance"
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name != "*":
                    exports.setdefault((alias.asname or alias.name).split(".")[0], "import")
    return ModuleInterface(exports=exports, methods=methods)


def read_module_interface(path: Path) -> ModuleInterface | None:
    try:
        return parse_module_interface(path.read_text(encoding="utf-8", errors="ignore"))
    except OSError as e:
        logger.warning("Modul %s konnte für die Fehler-Triage nicht gelesen werden: %s", path, e)
        return None


def load_interface_contract(project_dir: Path | str | None) -> dict[str, dict[str, str]]:
    """Liest `interface_contract.json` ({"modules": {"app/x.py": {"Name": "class"}}}). Modul-
    schlüssel dürfen Dateipfade oder Punkt-Modulnamen sein; ein kaputter Vertrag gilt als leer."""
    if project_dir is None:
        return {}
    path = Path(project_dir) / INTERFACE_CONTRACT_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("%s ist nicht lesbar und wird ignoriert: %s", path, e)
        return {}
    modules = data.get("modules", data) if isinstance(data, dict) else {}
    contract: dict[str, dict[str, str]] = {}
    if not isinstance(modules, dict):
        return contract
    for key, symbols in modules.items():
        if not isinstance(symbols, dict):
            continue
        key = _norm(str(key))
        file_key = key if key.endswith(".py") else key.replace(".", "/") + ".py"
        contract[file_key] = {str(name): str(kind).lower() for name, kind in symbols.items()}
    return contract


def _contract_entry(contract: dict[str, dict[str, str]], module_file: str) -> dict[str, str] | None:
    if module_file in contract:
        return contract[module_file]
    if module_file.endswith("/__init__.py"):
        return contract.get(module_file[: -len("/__init__.py")] + ".py")
    return contract.get(module_file[:-3] + "/__init__.py")


def find_contract_violations(project_dir: Path | str) -> list[str]:
    """Alle Abweichungen des Codes von `interface_contract.json` (leer ohne Vertrag)."""
    root = Path(project_dir)
    violations: list[str] = []
    for file_key, symbols in sorted(load_interface_contract(root).items()):
        path = root / file_key
        if not path.is_file():
            package_init = root / (file_key[:-3] + "/__init__.py")
            if not package_init.is_file():
                violations.append(f"`{file_key}` fehlt (vereinbart: {', '.join(sorted(symbols))})")
                continue
            path = package_init
        interface = read_module_interface(path)
        if interface is None:
            violations.append(f"`{file_key}` ist nicht parsebar (SyntaxError)")
            continue
        for name, kind in sorted(symbols.items()):
            actual = interface.exports.get(name)
            if actual is None:
                hint = f" – existiert nur als Methode von `{interface.methods[name]}`" if name in interface.methods else ""
                violations.append(f"`{file_key}`: `{name}` ({kind}) fehlt{hint}")
            elif kind in ("class", "function") and actual not in (kind, "import"):
                violations.append(f"`{file_key}`: `{name}` soll {kind} sein, ist aber {actual}")
    return violations


def _format_exports(exports: dict[str, str], limit: int = 12) -> str:
    public = [f"`{n}` ({k})" for n, k in exports.items() if k != "import" and not n.startswith("_")]
    return ", ".join(public[:limit]) + (" …" if len(public) > limit else "") if public else "keine öffentlichen Symbole"


def _contract_violation_note(root: Path | None) -> str:
    if root is None:
        return ""
    violations = find_contract_violations(root)
    if not violations:
        return ""
    listed = "\n".join(f"  - {v}" for v in violations[:6])
    more = f"\n  - … und {len(violations) - 6} weitere" if len(violations) > 6 else ""
    return f"\nWeitere Abweichungen vom Vertrag (`{INTERFACE_CONTRACT_FILE}`) gleich mit beheben:\n{listed}{more}"


# ── Triage ─────────────────────────────────────────────────────────────────────────────────


def _importer_of(provider: str | None, rel_files: Sequence[str], message: str,
                 root: Path | None, known: Collection[str]) -> str | None:
    """Direkt importierende Datei: letzter Traceback-Frame außerhalb des Anbieters, sonst das
    von pytest genannte Testmodul."""
    importer = next((f for f in reversed(rel_files) if f != provider), None)
    if importer is None:
        m = _TEST_MODULE_IMPORT_RE.search(message) or _COLLECTING_RE.search(message)
        if m:
            importer = _to_project_rel(m.group(1), root, known)
    return importer


def _drift(importer: str | None, detail: str, root: Path | None) -> StructuralTriage:
    target = f"`{importer}`" if importer else "der importierenden Datei"
    return StructuralTriage(
        kind=KIND_INTERFACE_DRIFT,
        responsible_file=importer,
        fallback_agent="tester" if importer and is_test_file(importer) else "backend",
        diagnosis=(
            f"⚠️ KONKRETE URSACHE (Schnittstellen-Drift): {detail} Korrigiere den Import und die "
            f"Aufrufe in {target} gegen die TATSÄCHLICHE Schnittstelle – ändere NICHT das "
            f"Anbieter-Modul, nur um einen falschen Import zu bedienen. {MANIFEST_GUARD_NOTE}"
            + _contract_violation_note(root)
        ),
    )


def _triage_syntax(message: str, root: Path | None, known: Collection[str], rel_files: Sequence[str]) -> StructuralTriage | None:
    m = _SYNTAX_ERROR_RE.search(message)
    if not m:
        return None
    locations = _FILE_LINE_RE.findall(message[: m.start()])
    raw_path, line = locations[-1] if locations else ("", "")
    if not raw_path and (cm := _COMPILE_LOCATION_RE.search(message[m.start():])):
        raw_path, line = cm.group(1), cm.group(2)
    rel = _to_project_rel(raw_path, root, known) if raw_path else None
    if rel is None and rel_files:
        rel = rel_files[-1]
    where = (f"`{rel}`" + (f" Zeile {line}" if line else "")) if rel else "der im Traceback genannten Datei"
    return StructuralTriage(
        kind=KIND_SYNTAX_ERROR,
        responsible_file=rel,
        fallback_agent="tester" if rel and is_test_file(rel) else "backend",
        diagnosis=(
            f"⚠️ KONKRETE URSACHE: `{m.group(1)}: {m.group(2).strip()}` in {where}. pytest bricht "
            "dadurch schon beim Einsammeln ab – alle übrigen Testergebnisse sind bis zur Korrektur "
            "wertlos. Repariere GENAU diese Stelle (Klammern, Einrückung, Anführungszeichen, "
            f"abgeschnittener Code) und prüfe mit run_tests. {MANIFEST_GUARD_NOTE}"
        ),
    )


def _find_settings_class(root: Path, class_name: str) -> tuple[str | None, list[str]]:
    """(Datei, Pflichtfelder ohne Default) der Settings-Klasse `class_name`."""
    needle = f"class {class_name}"
    for path in _iter_project_py_files(root):
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if needle not in source:
            continue
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ClassDef) and node.name == class_name):
                continue
            base_names = {b.id if isinstance(b, ast.Name) else getattr(b, "attr", "") for b in node.bases}
            if not any(name.endswith("Settings") for name in base_names):
                continue
            required = [
                item.target.id for item in node.body
                if isinstance(item, ast.AnnAssign) and item.value is None and isinstance(item.target, ast.Name)
                and item.target.id != "model_config" and "ClassVar" not in ast.unparse(item.annotation)
            ]
            return _norm(str(path.relative_to(root))), required
    return None, []


def _triage_settings(message: str, root: Path | None, known: Collection[str]) -> StructuralTriage | None:
    m = _SETTINGS_VALIDATION_RE.search(message)
    if not m:
        return None
    class_name = m.group(1)
    defining_file, required = _find_settings_class(root, class_name) if root is not None else (None, [])
    if defining_file is None:
        if not class_name.endswith(("Settings", "Config")):
            return None  # gewöhnliche Pydantic-Validierung eines Request-/Domänenmodells
        defining_file = next(
            (k for k in sorted(known) if PurePosixPath(k).name in ("config.py", "settings.py") and not is_test_file(k)),
            None,
        )
    fields = list(dict.fromkeys(_MISSING_FIELD_RE.findall(message))) or required
    return StructuralTriage(
        kind=KIND_SETTINGS_DEFAULTS,
        responsible_file=defining_file,
        fallback_agent="backend",
        diagnosis=(
            f"⚠️ KONKRETE URSACHE: `ValidationError` der Settings-Klasse `{class_name}`"
            + (f" in `{defining_file}`" if defining_file else "")
            + (f" – Pflichtfelder ohne Default: {', '.join(f'`{f}`' for f in fields)}" if fields else "")
            + ". App-Import und Tests laufen ohne `.env`, deshalb braucht JEDES Feld einen lauffähigen "
            "Dev-Default (z. B. `DATABASE_URL: str = \"sqlite:///./dev.db\"`, `SECRET_KEY: str = "
            "Field(default_factory=lambda: secrets.token_urlsafe(32))`) sowie `model_config = "
            "SettingsConfigDict(env_file=\".env\", extra=\"ignore\")`. Mache Tests NICHT von einer "
            f"`.env` abhängig. {MANIFEST_GUARD_NOTE}"
        ),
    )


def _triage_import_name(message: str, root: Path | None, known: Collection[str], rel_files: Sequence[str]) -> StructuralTriage | None:
    m = _IMPORT_NAME_RE.search(message)
    if not m:
        return None
    name, module = m.group(1), m.group(2)
    provider = module_to_file(module, root, known)
    if provider is None:
        return None  # Drittanbieter-Modul oder unbekannt -> reguläres Routing
    importer = _importer_of(provider, rel_files, message, root, known)
    contract_entry = _contract_entry(load_interface_contract(root), provider)
    interface = read_module_interface(root / provider) if root is not None and (root / provider).is_file() else None

    if contract_entry is not None and name in contract_entry:
        return StructuralTriage(
            kind=KIND_MISSING_SYMBOL,
            responsible_file=provider,
            fallback_agent="backend",
            diagnosis=(
                f"⚠️ KONKRETE URSACHE (Vertragsbruch beim Anbieter): Laut `{INTERFACE_CONTRACT_FILE}` "
                f"muss `{provider}` das Symbol `{name}` ({contract_entry[name]}) exportieren, es fehlt "
                f"aber. Ergänze `{name}` exakt in dieser Form auf Modulebene in `{provider}`. "
                f"{MANIFEST_GUARD_NOTE}" + _contract_violation_note(root)
            ),
        )
    if contract_entry is not None:
        return _drift(
            importer,
            f"`{name}` ist in `{INTERFACE_CONTRACT_FILE}` für `{provider}` nicht vorgesehen. "
            f"Vertraglich exportiert: {_format_exports(contract_entry)}.",
            root,
        )
    if interface is None:
        return None
    if name in interface.methods:
        cls = interface.methods[name]
        return _drift(
            importer,
            f"`{name}` ist in `{provider}` KEINE Modulfunktion, sondern eine Methode der Klasse "
            f"`{cls}`. Importiere `{cls}` (bzw. eine dort exportierte Instanz) und rufe "
            f"`{cls}(...).{name}(...)` auf, statt eine freie Funktion anzunehmen.",
            root,
        )
    close = difflib.get_close_matches(name, [n for n, k in interface.exports.items() if k != "import"], n=3, cutoff=0.75)
    if close:
        return _drift(
            importer,
            f"`{name}` existiert nicht in `{provider}`, dort gibt es aber {', '.join(f'`{c}`' for c in close)}.",
            root,
        )
    return StructuralTriage(
        kind=KIND_MISSING_SYMBOL,
        responsible_file=provider,
        fallback_agent="backend",
        diagnosis=(
            f"⚠️ KONKRETE URSACHE: `{name}` fehlt ersatzlos in `{provider}` (vorhanden: "
            f"{_format_exports(interface.exports)}). Ergänze `{name}` dort auf Modulebene, statt die "
            f"importierende Datei umzubauen. {MANIFEST_GUARD_NOTE}"
        ),
    )


def _similar_modules(module: str, root: Path | None, known: Collection[str]) -> list[str]:
    parent, _, leaf = module.rpartition(".")
    parent_dir = parent.replace(".", "/")
    names: set[str] = set()
    for k in known:
        p = PurePosixPath(k)
        if str(p.parent) == (parent_dir or "."):
            names.add(p.stem if p.suffix == ".py" else p.name)
    if root is not None and (root / parent_dir).is_dir():
        for child in (root / parent_dir).iterdir():
            if child.suffix == ".py" or (child.is_dir() and (child / "__init__.py").is_file()):
                names.add(child.stem)
    names.discard("__init__")
    matches = difflib.get_close_matches(leaf, sorted(names), n=2, cutoff=0.7)
    return [f"{parent}.{m}" if parent else m for m in matches]


def _triage_module_not_found(message: str, root: Path | None, known: Collection[str], rel_files: Sequence[str]) -> StructuralTriage | None:
    m = _MODULE_NOT_FOUND_RE.search(message)
    if not m:
        return None
    module = m.group(1)
    if not is_local_module(module, root, known):
        return None  # Drittanbieter-Paket -> Dependency-Routing bleibt zuständig
    top = module.split(".")[0]
    if "." not in module and _top_level_exists(top, root, known):
        config_file = next((c for c in ("pytest.ini", "pyproject.toml", "setup.cfg", "tests/conftest.py", "conftest.py") if c in known), None)
        return StructuralTriage(
            kind=KIND_TEST_IMPORT_PATH,
            responsible_file=config_file,
            fallback_agent="tester",
            diagnosis=(
                f"⚠️ KONKRETE URSACHE: `{top}` existiert im Projekt, ist beim Testlauf aber nicht "
                "importierbar – der Import-Pfad fehlt. Setze in `pytest.ini` `pythonpath = .` (bzw. "
                "`[tool.pytest.ini_options] pythonpath = [\".\"]`) oder ergänze das fehlende "
                f"`{top}/__init__.py`. Das ist KEIN fehlendes PyPI-Paket. {MANIFEST_GUARD_NOTE}"
            ),
        )
    expected = module.replace(".", "/") + ".py"
    importer = _importer_of(None, rel_files, message, root, known)
    if _contract_entry(load_interface_contract(root), expected) is None and importer:
        similar = _similar_modules(module, root, known)
        if similar:
            return _drift(
                importer,
                f"Das Projektmodul `{module}` gibt es nicht, wohl aber {', '.join(f'`{s}`' for s in similar)}.",
                root,
            )
    return StructuralTriage(
        kind=KIND_MISSING_LOCAL_MODULE,
        responsible_file=None,
        fallback_agent="backend",
        diagnosis=(
            f"⚠️ KONKRETE URSACHE: Das Projektmodul `{module}` fehlt (`{expected}` bzw. "
            f"`{expected[:-3]}/__init__.py`). Lege GENAU diese Datei mit den importierten Symbolen an "
            f"– ein PyPI-Paket dieses Namens ist NICHT gemeint. {MANIFEST_GUARD_NOTE}"
            + _contract_violation_note(root)
        ),
    )


# Realer Fund (auditlog_sentinel, 2026-09-10): `AttributeError: 'AsyncEngine' object has no
# attribute '_run_ddl_visitor'` beim Einsammeln der Tests – `Base.metadata.create_all(bind=engine)`
# lief synchron auf einer `create_async_engine()`-Engine. Der Fehler ging zweimal an security
# (letzter Schreiber von app/main.py) statt an die fachlich zuständige database-Rolle.
_ASYNC_SYNC_MISMATCH_RE = re.compile(
    r"'Async(?:Engine|Connection|Session)' object has no attribute"
    r"|MissingGreenlet|greenlet_spawn has not been called",
    re.IGNORECASE,
)
_SYNC_CREATE_ALL_RE = re.compile(r"metadata\.create_all\(\s*(?:bind\s*=\s*)?\w*engine")


def _triage_async_sync_mismatch(message: str, root: Path | None, known: Collection[str]) -> StructuralTriage | None:
    if not _ASYNC_SYNC_MISMATCH_RE.search(message):
        return None
    culprit: str | None = None
    if root is not None:
        for rel in sorted(known):
            if not rel.endswith(".py") or is_test_file(rel):
                continue
            try:
                text = (root / rel).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if _SYNC_CREATE_ALL_RE.search(text) and "run_sync" not in text:
                culprit = rel
                break
    return StructuralTriage(
        kind=KIND_ASYNC_SYNC_MISMATCH,
        # Bewusst None: Der Datei-Owner (z.B. security für app/main.py) ist hier gerade NICHT
        # zuständig - die Ursache ist DB-Fachwissen, deshalb greift der Fallback database.
        responsible_file=None,
        fallback_agent="database",
        diagnosis=(
            "⚠️ KONKRETE URSACHE: Eine asynchrone SQLAlchemy-Engine (`create_async_engine`) wird "
            "synchron benutzt – typischerweise `Base.metadata.create_all(bind=engine)` auf Modulebene. "
            "Mit einer AsyncEngine muss das in einer async-Funktion laufen: `async with engine.begin() "
            "as conn: await conn.run_sync(Base.metadata.create_all)` (FastAPI: im lifespan-Handler), "
            "niemals beim Import."
            + (f" Betroffene Datei: `{culprit}`." if culprit else "")
            + f" {MANIFEST_GUARD_NOTE}"
        ),
    )


def triage_structural_failure(
    message: str,
    files: Iterable[str],
    file_owners: dict[str, str],
    project_dir: Path | str | None = None,
) -> StructuralTriage | None:
    """Klassifiziert einen strukturellen Testfehler; None für alle übrigen Fehlerbilder
    (Assertion, Laufzeitfehler, Drittanbieter-Dependency), die das reguläre Routing behandelt."""
    root = Path(project_dir) if project_dir else None
    known = {_norm(k) for k in file_owners}
    rel_files = [rel for f in files if (rel := _to_project_rel(f, root, known))]
    return (
        _triage_syntax(message, root, known, rel_files)
        or _triage_async_sync_mismatch(message, root, known)
        or _triage_settings(message, root, known)
        or _triage_import_name(message, root, known, rel_files)
        or _triage_module_not_found(message, root, known, rel_files)
    )


def resolve_triage_owner(triage: StructuralTriage, file_owners: dict[str, str], available_agents: Collection[str]) -> str | None:
    """Owner der verantwortlichen Datei, sonst der fachliche Fallback-Agent."""
    owners = {_norm(k): v for k, v in file_owners.items()}
    file_owner = owners.get(triage.responsible_file) if triage.responsible_file else None
    for candidate in (file_owner, triage.fallback_agent):
        if candidate and candidate in available_agents:
            return candidate
    return None


# ── Fix-Loop-Steuerung ─────────────────────────────────────────────────────────────────────


def is_collection_failure(message: str) -> bool:
    """True für Fehler, die pytest schon beim Einsammeln abbrechen lassen."""
    return bool(_COLLECTION_FAILURE_RE.search(message) or _SYNTAX_ERROR_RE.search(message))


def blocking_failures_first(failures: Sequence[_F]) -> list[_F]:
    """Solange Collection-/Syntaxfehler existieren, sind alle anderen Fehlschläge Folgefehler
    oder nicht aussagekräftig - der Fix-Loop bearbeitet dann NUR die blockierenden."""
    blocking = [f for f in failures if is_collection_failure(f.message)]
    return blocking or list(failures)


def _manifest_paths(root: Path) -> list[Path]:
    return sorted({*root.glob("requirements*.txt"), *([root / "Pipfile"] if (root / "Pipfile").is_file() else [])})


def snapshot_dependency_manifests(project_dir: Path | str) -> dict[str, bytes]:
    """Inhalt aller Dependency-Manifeste im Projekt-Root vor einem Fix-Schritt."""
    snapshot: dict[str, bytes] = {}
    for path in _manifest_paths(Path(project_dir)):
        try:
            snapshot[path.name] = path.read_bytes()
        except OSError as e:
            logger.warning("Manifest %s konnte nicht gesichert werden: %s", path, e)
    return snapshot


def restore_dependency_manifests(project_dir: Path | str, snapshot: dict[str, bytes]) -> list[str]:
    """Stellt den Stand aus snapshot_dependency_manifests() wieder her (auch neu angelegte
    Manifeste werden entfernt). Rückgabe: Namen der zurückgesetzten Dateien."""
    root = Path(project_dir)
    restored: list[str] = []
    for name in sorted({p.name for p in _manifest_paths(root)} | set(snapshot)):
        path = root / name
        before = snapshot.get(name)
        try:
            if before is None:
                path.unlink()
            elif not path.is_file() or path.read_bytes() != before:
                path.write_bytes(before)
            else:
                continue
            restored.append(name)
        except OSError as e:
            logger.warning("Manifest %s konnte nicht zurückgesetzt werden: %s", path, e)
    return restored
