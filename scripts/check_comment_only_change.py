"""
scripts/check_comment_only_change.py – Beweist, dass eine Änderung nur Kommentare/Docstrings betrifft

Vergleicht den AST jeder angegebenen Python-Datei mit dem Stand einer Git-Referenz (Standard: HEAD),
nachdem Docstrings entfernt wurden. Kommentare stehen ohnehin nicht im AST. Weicht irgendetwas
anderes ab (Code, Strings, Reihenfolge), endet das Skript mit Exit-Code 1.

    python scripts/check_comment_only_change.py agents/base_agent.py core/agent_toolbox.py
    python scripts/check_comment_only_change.py --ref main agents/orchestrator/department.py
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                node.body = body[1:] or [ast.Pass()]
    return tree


def _normalized_dump(source: str) -> str:
    return ast.dump(_strip_docstrings(ast.parse(source)), include_attributes=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+")
    parser.add_argument("--ref", default="HEAD")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows-Konsole (cp1252) kann keine Emojis
    failed = False
    for file in args.files:
        rel = Path(file).as_posix()
        try:
            old = subprocess.run(
                ["git", "show", f"{args.ref}:{rel}"], capture_output=True, text=True, encoding="utf-8", check=True,
            ).stdout
        except subprocess.CalledProcessError as e:
            print(f"❌ {rel}: nicht in {args.ref} lesbar ({e.stderr.strip()})")
            failed = True
            continue
        new = Path(file).read_text(encoding="utf-8")
        if _normalized_dump(old) == _normalized_dump(new):
            saved = len(old.splitlines()) - len(new.splitlines())
            print(f"✅ {rel}: nur Kommentare/Docstrings geändert ({saved:+d} Zeilen eingespart)")
        else:
            print(f"❌ {rel}: Code weicht ab - nicht nur Kommentare/Docstrings geändert")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
