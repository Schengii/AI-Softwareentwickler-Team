"""
core/contract_digest.py – Deterministischer Backend-Vertrags-Auszug (Enum-Werte, Pydantic-
Feldnamen) für den `tester`-Agenten.

Realer Fund (pulse_queue, 2026-09-22, FEHLERANALYSE_PULSE_QUEUE_20260922_TEMP.md, Problem 2):
Der Tester schrieb Tests gegen ERFUNDENE Enum-Werte (`JobType.DATA_EXPORT` statt der tatsächlich
deklarierten `JobType.data_export`) und einen erfundenen Feldnamen (`job_type` statt `type`),
obwohl der echte Backend-Code (`app/models/job.py`) zu diesem Zeitpunkt bereits im Workspace lag.
Der bisherige Kontext für den Tester bestand nur aus einer groben Projekt-Steckbrief-Kurzfassung
(core/code_graph.py.generate_project_brief(), ~600 Zeichen, listet Dateien/Symbole, nicht aber
Enum-MITGLIEDER oder Pydantic-FELDNAMEN) - der Tester musste sich exakte Werte selbst per
Tool-Aufruf erlesen und tat das nicht zuverlässig.

`build_backend_contract_digest()` extrahiert stattdessen MECHANISCH (AST, kein LLM-Aufruf) alle
Enum-Mitglieder und Pydantic-Modell-Felder aus dem Nicht-Test-Code und liefert sie als kompakten,
kopierfähigen Text - der Tester muss die Werte dann nur noch übernehmen statt sie zu raten.
"""

from __future__ import annotations

import ast
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


def build_backend_contract_digest(project_dir: str | Path, max_chars: int = 2000) -> str:
    """Extrahiert Enum-Werte und Pydantic-Feldnamen aus dem Nicht-Test-Code eines Projekts.

    Rein AST-basiert, kein LLM-Aufruf. Leerer String, wenn `project_dir` fehlt oder keine
    passenden Klassen gefunden wurden (dann bleibt der bisherige, allgemeine Projekt-Steckbrief
    die einzige Kontextquelle - kein Verhalten wird dadurch verschlechtert)."""
    root = Path(project_dir)
    if not root.is_dir():
        return ""
    entries: list[str] = []
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
                break
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except (SyntaxError, ValueError, OSError):
                continue
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    described = _describe_class(node)
                    if described:
                        entries.append(f"- `{rel}`: {described}")
        if scanned > _MAX_SCANNED_FILES:
            break
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
