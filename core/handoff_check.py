"""
core/handoff_check.py – Übergabe-Prüfung ("nur grün abgeben") für Code-schreibende Agenten.

In einem echten Team gibt ein Entwickler keinen Code ab, der sich nicht einmal importieren
lässt. Im KI-Team schrieben Entwickler-Agenten bisher Dateien und meldeten sofort Erfolg - die
statischen Fehler (Syntaxfehler, Import eines nicht existierenden lokalen Moduls, Re-Export vor
Anlage des Zielmoduls) fielen erst Phasen später im Pre-Flight-Check auf (bis zu 20 Funde pro
Lauf) und kosteten dort je einen zusätzlichen Fix-Agenten-Durchlauf.

`check_handoff()` prüft deterministisch (AST, kein LLM, Millisekunden) NUR die vom Agenten selbst
geschriebenen Dateien und liefert eine Liste konkreter Befunde, die der Agent noch INNERHALB
seiner Aufgabe behebt (agents/base_agent.py). Fehlende `__init__.py` werden direkt deterministisch
angelegt statt gemeldet.

Imports auf Module, die laut `interface_contract.json` ein ANDERES Teammitglied liefert, gelten
nicht als Befund - parallel arbeitende Kollegen dürfen noch nicht fertig sein.
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Rollen, deren Python-Code vor der Abgabe geprüft wird.
HANDOFF_GATE_AGENT_IDS: frozenset[str] = frozenset({
    "backend", "database", "api_integration", "data_engineer", "ml", "tester",
    "refactoring", "resilience_guard", "security", "performance", "prompt_engineer",
})

_MODULE_REF_RE = re.compile(r"\(`([^`]+)\.py`\)")


@dataclass
class HandoffReport:
    issues: list[str] = field(default_factory=list)
    auto_fixed: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.issues

    def format_for_agent(self) -> str:
        lines = [
            "ÜBERGABE-PRÜFUNG FEHLGESCHLAGEN: Deine geschriebenen Dateien sind noch nicht lauffähig. "
            "Behebe diese Befunde JETZT mit edit_file/write_file, bevor du abschließt:",
        ]
        lines += [f"- {issue}" for issue in self.issues[:15]]
        if len(self.issues) > 15:
            lines.append(f"- … und {len(self.issues) - 15} weitere")
        lines.append(
            "Wenn ein Import auf ein Modul zeigt, das du selbst anlegen solltest: lege es an. "
            "Wenn der Import falsch ist: korrigiere ihn. Führe danach run_tests aus, falls Tests existieren."
        )
        return "\n".join(lines)


def _contract_modules(project_dir: Path) -> set[str]:
    from core.failure_triage import load_interface_contract

    try:
        return {path.replace("\\", "/") for path in load_interface_contract(project_dir)}
    except Exception as e:  # noqa: BLE001 - defekter Vertrag darf die Übergabe nie blockieren
        logger.warning("Schnittstellenvertrag für Übergabe-Prüfung nicht lesbar: %r", e)
        return set()


def _references_planned_module(message: str, planned: set[str]) -> bool:
    match = _MODULE_REF_RE.search(message or "")
    if not match:
        return False
    referenced = match.group(1).replace("\\", "/").strip("/")
    return f"{referenced}.py" in planned or f"{referenced}/__init__.py" in planned or any(
        p.startswith(f"{referenced}/") for p in planned
    )


def check_handoff(project_dir: str | Path, files_written: list[str] | set[str]) -> HandoffReport:
    """Prüft die übergebenen (projektrelativen) Dateien statisch. Nie eine Exception."""
    from core.project_scaffold import ensure_package_inits, is_safe_project_dir
    from core.verifier import ProjectVerifier

    base = Path(project_dir)
    report = HandoffReport()
    python_files = sorted({f.replace("\\", "/") for f in files_written if f.endswith(".py")})
    if not is_safe_project_dir(base):
        return report
    if not python_files or not base.is_dir():
        return report

    for rel in python_files:
        path = base / rel
        try:
            ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=rel)
        except SyntaxError as e:
            report.issues.append(f"{rel}:{e.lineno or 0} – Syntaxfehler: {e.msg}")
        except OSError:
            continue

    try:
        report.auto_fixed = ensure_package_inits(base, python_files)
    except OSError as e:
        logger.warning("__init__.py-Autofix in Übergabe-Prüfung fehlgeschlagen: %r", e)

    planned = _contract_modules(base)
    written = set(python_files)
    try:
        completeness = ProjectVerifier(str(base)).check_completeness()
    except Exception as e:  # noqa: BLE001 - Prüfung ist Hilfe, kein Blocker
        logger.warning("Übergabe-Prüfung: Vollständigkeits-Check fehlgeschlagen: %r", e)
        return report
    for issue in getattr(completeness, "issues", []) or []:
        if getattr(issue, "kind", "") != "missing_local_import":
            continue
        if issue.file_path.replace("\\", "/") not in written:
            continue
        # Ein Paket-`__init__.py` mit Import auf ein noch fehlendes Modul bricht jeden Import des
        # Pakets - das ist nie "Kollege noch nicht fertig", sondern ein zu früher Re-Export.
        is_package_init = issue.file_path.replace("\\", "/").endswith("__init__.py")
        if not is_package_init and _references_planned_module(issue.message, planned - written):
            continue
        report.issues.append(f"{issue.file_path}:{issue.line_number} – {issue.message}")
    return report
