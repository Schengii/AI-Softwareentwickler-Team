"""
core/interface_contract.py – Deterministischer Fallback für `interface_contract.json` (P4-4,
ROADMAP_TEMP.md, "Kein geteiltes Kurzzeitgedächtnis während der Entwicklungsphase")

`agents/team_directives.py.ARCHITECT_CONTRACT_DIRECTIVE` weist den architect-Agenten an, den
Schnittstellen-Vertrag per `write_file` anzulegen - das ist aber eine reine LLM-Anweisung, keine
Garantie. Realer Fund (`synapsegate`, Backend-only-Projekt): die Datei fehlte komplett, weil
entweder kein architect eingeplant war oder er den Schritt trotz Anweisung ausließ.
`core/failure_triage.py` (Vertragsbruch-Diagnose) und `agents/base_agent.py` (Prompt-Kontext für
alle code-schreibenden Rollen) verlassen sich beide auf diese Datei - ohne sie fehlt jeder
nachfolgenden Phase (qa_lead, governance_lead, spätere Fix-Runden) das geteilte Kurzzeitgedächtnis
komplett, nicht nur unvollständig.

`ensure_interface_contract()` füllt NUR die Lücke, LEGT NIE eine vom architect bereits
geschriebene Datei um: existiert `interface_contract.json` schon, passiert nichts. Fehlt sie,
wird sie aus dem TATSÄCHLICH GESCHRIEBENEN Code deterministisch synthetisiert (core/code_graph.py
- kein LLM-Aufruf), damit downstream-Konsumenten ab diesem Zeitpunkt wenigstens einen echten,
wenn auch gröberen Vertrag vorfinden statt gar keinen. Deckt bewusst nur `class`/`function` ab
(die beiden von core/code_graph.py sicher unterscheidbaren Symbolarten) - `instance`/`constant`
aus dem ursprünglichen, LLM-geschriebenen Schema lassen sich aus reiner AST-Analyse nicht
zuverlässig von einer beliebigen Modulvariable unterscheiden und werden deshalb ausgelassen."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from core.failure_triage import INTERFACE_CONTRACT_FILE

logger = logging.getLogger(__name__)

# Dieselbe Ausschlussliste wie core/code_graph.py._build_index() und core/test_depth.py -
# generierter/fremder Code und Testdateien gehören nie in den Schnittstellen-Vertrag.
_SKIP_DIRS = frozenset({".git", ".venv", "venv", ".ai_team_venv", "node_modules", "__pycache__", "dist", "build"})


def _is_test_file(rel_path: str) -> bool:
    name = rel_path.rsplit("/", 1)[-1]
    return rel_path.startswith(("tests/", "test/")) or "/tests/" in rel_path or name.startswith("test_") or name.endswith("_test.py")


def generate_interface_contract(project_dir: str | Path) -> dict:
    """Baut `{"modules": {"app/x.py": {"Name": "class"|"function"}}}` aus den tatsächlich im
    Projekt definierten Top-Level-Symbolen (keine Methoden, keine privaten Namen, keine
    Testdateien)."""
    from core.code_graph import CodebaseGraph

    base = Path(project_dir)
    modules: dict[str, dict[str, str]] = {}
    if not base.is_dir():
        return {"modules": modules}

    graph = CodebaseGraph(base)
    for file_path, symbols in graph.file_symbols.items():
        if not file_path.endswith(".py") or _is_test_file(file_path):
            continue
        entries: dict[str, str] = {}
        for sym in symbols:
            if sym.kind not in ("class", "function"):
                continue
            if sym.name.startswith("_") or "." in sym.name:  # "." = Methode, nicht Top-Level
                continue
            entries[sym.name] = sym.kind
        if entries:
            modules[file_path] = entries
    return {"modules": modules}


def ensure_interface_contract(project_dir: str | Path) -> bool:
    """Schreibt `interface_contract.json` NUR, wenn sie noch nicht existiert UND sich mindestens
    ein Modul aus dem Code ableiten lässt. Gibt True zurück, wenn eine Datei neu geschrieben
    wurde. Best-effort: ein Fehler hier darf einen sonst erfolgreichen Lauf nie gefährden.

    Realer Fund bei der Einführung dieses Moduls: ein Testlauf mit `project_dir="."` (siehe
    core/project_scaffold.py.is_safe_project_dir()-Docstring - dasselbe Muster) schrieb sonst
    eine `interface_contract.json` mit dem gesamten Framework-Quellcode direkt ins Repo-Root.
    Schreibende Autofixes deshalb NIE im Framework-Repository selbst/dessen Elternordnern/
    `workspace/` als Ganzes - nur in echten Zielprojekten."""
    from core.project_scaffold import is_safe_project_dir

    if not is_safe_project_dir(project_dir):
        return False
    path = Path(project_dir) / INTERFACE_CONTRACT_FILE
    if path.exists():
        return False
    try:
        contract = generate_interface_contract(project_dir)
        if not contract["modules"]:
            return False
        path.write_text(json.dumps(contract, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception as e:
        logger.warning("interface_contract.json konnte nicht deterministisch nachgetragen werden (%s): %r", path, e)
        return False
