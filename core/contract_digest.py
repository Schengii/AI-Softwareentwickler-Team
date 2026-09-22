"""
core/contract_digest.py – Deterministischer Backend-Vertrags-Auszug für den `tester`-Agenten.

Enthält drei unabhängige, rein AST-basierte Extraktoren (kein LLM-Aufruf):

1. Enum-Werte + Pydantic-Feldnamen (`build_backend_contract_digest`):
   Realer Fund (pulse_queue, 2026-09-22): Tester erfand `JobType.DATA_EXPORT` statt des
   deklarierten `JobType.data_export` und `job_type` statt `type`.

2. API-Routen-Präfixe + Response-Modelle (`build_route_prefix_digest`):
   Realer Fund (omnimetric_engine, Backlog root-cause-omnimetric_engine-tester-agent-*):
   Tester schrieb `GET /stats` obwohl der echte Pfad `GET /api/v1/stats` ist
   (APIRouter mit prefix="/api/v1" in app/routers/stats.py).
   Ergänzt um `response_model`-Extraktion: Tester nahm `{"id":...}` an, Backend gab
   `{"data":{"id":...}}` zurück – wäre mit dem deklarierten `response_model` erkennbar gewesen.

3. Router-Import-Prüfung (`check_router_imports`):
   Realer Fund (ecotrack_ai, Backlog root-cause-ecotrack_ai-backend-deklariert-*):
   Backend schrieb `from app.routers import xyz` in app/main.py, aber die Datei existierte
   nicht – der Fehler fiel erst beim Testlauf auf. `check_router_imports()` erkennt das
   deterministisch VOR dem Test und gibt die fehlenden Pfade zurück.
"""

from __future__ import annotations

import ast
import collections.abc
import os
from pathlib import Path

from core.failure_triage import _IGNORED_DIR_NAMES, is_test_file

_MAX_SCANNED_FILES = 400
_PYDANTIC_BASES = {"BaseModel", "BaseSettings", "Schema"}
_ENUM_BASES = {"Enum", "IntEnum", "StrEnum"}


def _base_names(node: ast.ClassDef) -> set[str]:
    return {b.id if isinstance(b, ast.Name) else getattr(b, "attr", "") for b in node.bases}


def _literal_value(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant):
        return repr(node.value)
    return None


def _describe_enum(node: ast.ClassDef) -> str | None:
    members = []
    for item in node.body:
        if isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name):
            name = item.targets[0].id
            value = _literal_value(item.value)
            members.append(f"{name}={value}" if value is not None else name)
    if not members:
        return None
    return f"`{node.name}` (Enum): " + ", ".join(members[:20])


def _annotation_str(node: ast.expr | None) -> str:
    if node is None:
        return "Any"
    try:
        return ast.unparse(node)
    except Exception:
        return "?"


def _describe_model(node: ast.ClassDef) -> str | None:
    fields = []
    for item in node.body:
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            if item.target.id == "model_config":
                continue
            fields.append(f"{item.target.id}: {_annotation_str(item.annotation)}")
    if not fields:
        return None
    return f"`{node.name}` (Modell): " + ", ".join(fields[:20])


def _describe_class(node: ast.ClassDef) -> str | None:
    bases = _base_names(node)
    if bases & _ENUM_BASES:
        return _describe_enum(node)
    if bases & _PYDANTIC_BASES:
        return _describe_model(node)
    return None


def _extract_router_prefixes(tree: ast.Module, rel: str) -> list[str]:
    """Extrahiert APIRouter(prefix=...) und app.include_router(..., prefix=...) Aufrufe."""
    results = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "APIRouter":
            for kw in node.keywords:
                if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                    results.append(f"- `{rel}`: APIRouter prefix=`{kw.value.value}`")
        elif isinstance(func, ast.Attribute) and func.attr == "include_router":
            prefix = next(
                (kw.value.value for kw in node.keywords
                 if kw.arg == "prefix" and isinstance(kw.value, ast.Constant)),
                None,
            )
            if prefix:
                results.append(f"- `{rel}`: include_router prefix=`{prefix}`")
    return results


def _extract_response_models(tree: ast.Module, rel: str) -> list[str]:
    """Extrahiert @router.METHOD(path, response_model=Schema) aus Routen-Dateien."""
    results = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            if not (isinstance(func, ast.Attribute) and func.attr in ("get", "post", "put", "delete", "patch")):
                continue
            path_val = dec.args[0].value if dec.args and isinstance(dec.args[0], ast.Constant) else "?"
            response_model = next(
                (ast.unparse(kw.value) for kw in dec.keywords if kw.arg == "response_model"),
                None,
            )
            if response_model:
                results.append(f"- `{rel}`: {func.attr.upper()} `{path_val}` → response_model=`{response_model}`")
    return results[:10]


def _walk_non_test_py_files(
    root: Path,
) -> collections.abc.Iterator[tuple[Path, str, ast.Module]]:
    """Hilfsgenerator: iteriert über alle Nicht-Test-Python-Dateien unterhalb von `root`."""
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _IGNORED_DIR_NAMES and not d.startswith(".")]
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            path = Path(dirpath) / filename
            rel = str(path.relative_to(root)).replace("\\", "/")
            if is_test_file(rel):
                continue
            scanned += 1
            if scanned > _MAX_SCANNED_FILES:
                return
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except (SyntaxError, ValueError, OSError):
                continue
            yield path, rel, tree
        if scanned > _MAX_SCANNED_FILES:
            return


def build_backend_contract_digest(project_dir: str | Path, max_chars: int = 2000) -> str:
    """Extrahiert Enum-Werte und Pydantic-Feldnamen aus dem Nicht-Test-Code eines Projekts.

    Rein AST-basiert, kein LLM-Aufruf. Leerer String, wenn `project_dir` fehlt oder keine
    passenden Klassen gefunden wurden (dann bleibt der bisherige, allgemeine Projekt-Steckbrief
    die einzige Kontextquelle - kein Verhalten wird dadurch verschlechtert)."""
    root = Path(project_dir)
    if not root.is_dir():
        return ""
    entries: list[str] = []
    for _path, rel, tree in _walk_non_test_py_files(root):
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                described = _describe_class(node)
                if described:
                    entries.append(f"- `{rel}`: {described}")
    if not entries:
        return ""
    header = (
        "## 📐 Backend-Vertrag (deterministisch per AST extrahiert - NICHT erfinden, "
        "GENAU diese Namen/Werte verwenden)\n"
    )
    body = "\n".join(entries)
    text = header + body
    if len(text) > max_chars:
        text = text[:max_chars] + "\n- … (gekürzt, bei Bedarf die Datei selbst lesen)"
    return text


def build_route_prefix_digest(project_dir: str | Path, max_chars: int = 1200) -> str:
    """Extrahiert API-Routen-Präfixe und Response-Modelle aus dem Backend-Code.

    Reale Funde (omnimetric_engine, eventforge_ein_webhook): Tester schrieb `GET /stats`
    statt `GET /api/v1/stats` und nahm falsche Response-Struktur an. Beide Fehler wären mit
    diesen deterministisch extrahierten Daten vermeidbar gewesen."""
    root = Path(project_dir)
    if not root.is_dir():
        return ""
    prefix_entries: list[str] = []
    response_entries: list[str] = []
    for _path, rel, tree in _walk_non_test_py_files(root):
        prefix_entries.extend(_extract_router_prefixes(tree, rel))
        response_entries.extend(_extract_response_models(tree, rel))
    parts = []
    if prefix_entries:
        parts.append(
            "## 🔗 API-Routen-Präfixe (exakt diese Pfade in Tests verwenden, NICHT erfinden)\n"
            + "\n".join(prefix_entries[:20])
        )
    if response_entries:
        parts.append(
            "## 📤 API-Response-Modelle (exakt diese Typen erwarten, nicht raten)\n"
            + "\n".join(response_entries[:20])
        )
    if not parts:
        return ""
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n- … (gekürzt)"
    return text


def check_router_imports(project_dir: str | Path) -> list[str]:
    """Prüft, ob alle in app/main.py deklarierten Router-Module tatsächlich existieren.

    Gibt Liste fehlender Modul-Pfade zurück (relativ zu `project_dir`).
    Realer Fund (ecotrack_ai, Backlog root-cause-ecotrack_ai-backend-deklariert-*):
    Backend schrieb `from app.routers import xyz` in app/main.py, aber app/routers/xyz.py
    fehlte. Der Fehler trat erst beim Testlauf als ImportError auf."""
    root = Path(project_dir)
    main_py = root / "app" / "main.py"
    if not main_py.is_file():
        return []
    try:
        tree = ast.parse(main_py.read_text(encoding="utf-8", errors="ignore"))
    except (SyntaxError, ValueError, OSError):
        return []
    missing = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if not node.module or not node.module.startswith("app."):
            continue
        module_path = node.module.replace(".", "/") + ".py"
        if (root / module_path).is_file():
            continue
        init_path = node.module.replace(".", "/") + "/__init__.py"
        if (root / init_path).is_file():
            continue
        missing.append(module_path)
    return missing
