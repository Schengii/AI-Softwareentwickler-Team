"""
core/code_graph.py – AST-basierter Code-Knowledge-Graph & Symbol-Index

Erstellt einen strukturellen Graphen aller Symbole (Klassen, Funktionen, Methoden,
Variablen, Imports und Aufrufe) über das gesamte Projektverzeichnis hinweg.
Ermöglicht Agenten:
- Schnelles Auffinden von Symbol-Definitionen ohne ungenaues Volltext-Grep
- Exakte Referenz- und Aufrufer-Analyse (Call-Graph / Impact-Analysis) vor Refactorings
- Erkennen von abhängigen Dateien bei Signatur- oder Schnittstellenänderungen
"""

import ast
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SymbolNode:
    """Repräsentiert ein einzelnes Code-Symbol (Funktion, Klasse, Methode, Variable)."""
    name: str
    kind: str  # "class", "function", "method", "variable", "interface", "import"
    file_path: str
    line_number: int
    end_line_number: int
    docstring: str = ""
    args: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    inherits: list[str] = field(default_factory=list)
    signature: str = ""


@dataclass
class ImportNode:
    """Repräsentiert einen Import-Bezug zwischen Modulen/Dateien."""
    file_path: str
    imported_module: str
    imported_name: str
    alias: str = ""
    line_number: int = 1


@dataclass
class ImpactAnalysis:
    """Ergebnis einer Auswirkungsanalyse bei Änderungen an einem Symbol."""
    symbol_name: str
    defining_file: str
    referencing_files: list[str] = field(default_factory=list)
    calling_symbols: list[str] = field(default_factory=list)
    imported_in: list[str] = field(default_factory=list)


class CodebaseGraph:
    """
    AST-basierter Index für ein gesamtes Projektverzeichnis.
    Analysiert Python- und JavaScript/TypeScript-Quelldateien.
    """

    def __init__(self, project_dir: str | Path):
        self.project_dir = Path(project_dir).resolve()
        self.symbols: dict[str, list[SymbolNode]] = {}  # symbol_name -> list[SymbolNode]
        self.imports: list[ImportNode] = []
        self.file_symbols: dict[str, list[SymbolNode]] = {}  # file_path -> list[SymbolNode]
        self.indexed_files_count: int = 0
        self._build_index()

    def _build_index(self) -> None:
        """Scannt und indexiert alle Quellcode-Dateien im Projektverzeichnis."""
        self.symbols.clear()
        self.imports.clear()
        self.file_symbols.clear()
        self.indexed_files_count = 0

        ignored_dirs = {".git", ".venv", "venv", ".ai_team_venv", "__pycache__", "node_modules", "dist", "build"}

        if not self.project_dir.exists():
            return

        for root, dirs, files in os.walk(self.project_dir):
            dirs[:] = [d for d in dirs if d not in ignored_dirs and not d.startswith(".")]
            for file in files:
                full_path = Path(root) / file
                rel_path = str(full_path.relative_to(self.project_dir)).replace("\\", "/")

                if file.endswith(".py"):
                    self._index_python_file(full_path, rel_path)
                    self.indexed_files_count += 1
                elif file.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")):
                    self._index_js_file(full_path, rel_path)
                    self.indexed_files_count += 1
                elif file.endswith(".go"):
                    self._index_go_file(full_path, rel_path)
                    self.indexed_files_count += 1
                elif file.endswith(".rs"):
                    self._index_rust_file(full_path, rel_path)
                    self.indexed_files_count += 1

    def _index_python_file(self, full_path: Path, rel_path: str) -> None:
        """Parst eine Python-Datei per `ast`-Modul in präzise AST-Symbole."""
        try:
            content = full_path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(content, filename=str(full_path))
        except Exception:
            return

        file_nodes: list[SymbolNode] = []

        class PyVisitor(ast.NodeVisitor):
            def __init__(self, outer):
                self.outer = outer
                self.current_class: str | None = None

            def visit_Import(self, node: ast.Import):
                for alias in node.names:
                    imp = ImportNode(
                        file_path=rel_path,
                        imported_module=alias.name,
                        imported_name="*",
                        alias=alias.asname or "",
                        line_number=node.lineno,
                    )
                    self.outer.imports.append(imp)
                self.generic_visit(node)

            def visit_ImportFrom(self, node: ast.ImportFrom):
                mod = node.module or ""
                for alias in node.names:
                    imp = ImportNode(
                        file_path=rel_path,
                        imported_module=mod,
                        imported_name=alias.name,
                        alias=alias.asname or "",
                        line_number=node.lineno,
                    )
                    self.outer.imports.append(imp)
                self.generic_visit(node)

            def visit_ClassDef(self, node: ast.ClassDef):
                inherits = [ast.unparse(b) for b in node.bases if hasattr(ast, "unparse")]
                doc = ast.get_docstring(node) or ""
                sym = SymbolNode(
                    name=node.name,
                    kind="class",
                    file_path=rel_path,
                    line_number=node.lineno,
                    end_line_number=getattr(node, "end_lineno", node.lineno),
                    docstring=doc,
                    inherits=inherits,
                    signature=f"class {node.name}({', '.join(inherits)})",
                )
                file_nodes.append(sym)
                self.outer._add_symbol(sym)

                prev_class = self.current_class
                self.current_class = node.name
                self.generic_visit(node)
                self.current_class = prev_class

            def visit_FunctionDef(self, node: ast.FunctionDef):
                self._handle_func(node, is_async=False)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
                self._handle_func(node, is_async=True)

            def _handle_func(self, node, is_async: bool):
                args = [a.arg for a in node.args.args]
                calls = []
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Name):
                            calls.append(child.func.id)
                        elif isinstance(child.func, ast.Attribute):
                            calls.append(child.func.attr)

                kind = "method" if self.current_class else "function"
                prefix = "async def " if is_async else "def "
                sig = f"{prefix}{node.name}({', '.join(args)})"
                doc = ast.get_docstring(node) or ""

                sym = SymbolNode(
                    name=node.name if not self.current_class else f"{self.current_class}.{node.name}",
                    kind=kind,
                    file_path=rel_path,
                    line_number=node.lineno,
                    end_line_number=getattr(node, "end_lineno", node.lineno),
                    docstring=doc,
                    args=args,
                    calls=list(set(calls)),
                    signature=sig,
                )
                file_nodes.append(sym)
                self.outer._add_symbol(sym)
                self.generic_visit(node)

        visitor = PyVisitor(self)
        visitor.visit(tree)
        self.file_symbols[rel_path] = file_nodes

    def _index_js_file(self, full_path: Path, rel_path: str) -> None:
        """Extrahiert Symbole, Interfaces und Imports aus JavaScript/TypeScript-Dateien."""
        try:
            content = full_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return

        file_nodes: list[SymbolNode] = []
        lines = content.splitlines()

        # Imports: import { a, b } from './module' oder const x = require('x')
        import_pat = re.compile(r"""(?:import\s+(?:(?:\*\s+as\s+(\w+)|([\w,\s{}]+))\s+from\s+)?['"]([^'"]+)['"]|const\s+([\w,\s{}]+)\s*=\s*require\(['"]([^'"]+)['"]\))""")
        for idx, line in enumerate(lines, 1):
            m = import_pat.search(line)
            if m:
                names = m.group(1) or m.group(2) or m.group(4) or "*"
                mod = m.group(3) or m.group(5) or ""
                self.imports.append(ImportNode(
                    file_path=rel_path, imported_module=mod, imported_name=names.strip(), line_number=idx,
                ))

        # Klassen & Interfaces: class Foo extends Bar, interface User
        class_pat = re.compile(r"(?:export\s+)?(?:default\s+)?(class|interface|type)\s+([A-Za-z0-9_]+)(?:\s+(?:extends|implements)\s+([A-Za-z0-9_,\s]+))?")
        for idx, line in enumerate(lines, 1):
            m = class_pat.search(line)
            if m:
                kind_str = m.group(1)
                cname = m.group(2)
                parents_raw = m.group(3) or ""
                parents = [p.strip() for p in parents_raw.split(",") if p.strip()]
                sym = SymbolNode(
                    name=cname,
                    kind=kind_str,
                    file_path=rel_path,
                    line_number=idx,
                    end_line_number=idx,
                    inherits=parents,
                    signature=line.strip()[:100],
                )
                file_nodes.append(sym)
                self._add_symbol(sym)

        # Funktionen: function foo(x, y), export async function foo(x, y), const foo = (x, y) =>
        func_pat = re.compile(r"(?:(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)|(?:const|let|var)\s+([A-Za-z0-9_]+)\s*=\s*(?:async\s*)?(?:\(([^)]*)\)|([A-Za-z0-9_]+))\s*=>)")
        for idx, line in enumerate(lines, 1):
            m = func_pat.search(line)
            if m:
                fname = m.group(1) or m.group(3)
                raw_args = m.group(2) or m.group(4) or m.group(5) or ""
                args = [a.strip().split(":")[0] for a in raw_args.split(",") if a.strip()]
                sym = SymbolNode(
                    name=fname,
                    kind="function",
                    file_path=rel_path,
                    line_number=idx,
                    end_line_number=idx,
                    args=args,
                    signature=line.strip()[:100],
                )
                file_nodes.append(sym)
                self._add_symbol(sym)

        self.file_symbols[rel_path] = file_nodes

    def _index_go_file(self, full_path: Path, rel_path: str) -> None:
        """Extrahiert Structs, Interfaces, Funktionen, Methoden und Imports aus Go-Dateien."""
        try:
            content = full_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return

        file_nodes: list[SymbolNode] = []
        lines = content.splitlines()

        # Imports: import "fmt" oder import ( "strings" )
        in_import_block = False
        import_single_pat = re.compile(r"""import\s+['"]([^'"]+)['"]""")
        type_pat = re.compile(r"type\s+([A-Za-z0-9_]+)\s+(struct|interface)")
        func_pat = re.compile(r"func\s+(?:\(([A-Za-z0-9_*\s]+)\)\s+)?([A-Za-z0-9_]+)\s*\(([^)]*)\)")

        for idx, line in enumerate(lines, 1):
            s_line = line.strip()
            if s_line.startswith("import ("):
                in_import_block = True
                continue
            elif in_import_block:
                if s_line == ")":
                    in_import_block = False
                else:
                    m_imp = re.search(r"""['"]([^'"]+)['"]""", s_line)
                    if m_imp:
                        self.imports.append(ImportNode(
                            file_path=rel_path, imported_module=m_imp.group(1), imported_name="*", line_number=idx,
                        ))
                continue

            m_single = import_single_pat.match(s_line)
            if m_single:
                self.imports.append(ImportNode(
                    file_path=rel_path, imported_module=m_single.group(1), imported_name="*", line_number=idx,
                ))

            # Structs & Interfaces
            m_type = type_pat.search(s_line)
            if m_type:
                tname = m_type.group(1)
                kind = m_type.group(2)  # struct | interface
                sym = SymbolNode(
                    name=tname,
                    kind=kind,
                    file_path=rel_path,
                    line_number=idx,
                    end_line_number=idx,
                    signature=s_line[:100],
                )
                file_nodes.append(sym)
                self._add_symbol(sym)

            # Functions & Methods
            m_func = func_pat.search(s_line)
            if m_func:
                receiver = m_func.group(1)
                fname = m_func.group(2)
                raw_args = m_func.group(3) or ""
                args = [a.strip().split(" ")[0] for a in raw_args.split(",") if a.strip()]

                if receiver:
                    clean_rec = receiver.replace("*", "").strip().split(" ")[-1]
                    sym_name = f"{clean_rec}.{fname}"
                    kind = "method"
                else:
                    sym_name = fname
                    kind = "function"

                sym = SymbolNode(
                    name=sym_name,
                    kind=kind,
                    file_path=rel_path,
                    line_number=idx,
                    end_line_number=idx,
                    args=args,
                    signature=s_line[:100],
                )
                file_nodes.append(sym)
                self._add_symbol(sym)

        self.file_symbols[rel_path] = file_nodes

    def _index_rust_file(self, full_path: Path, rel_path: str) -> None:
        """Extrahiert Structs, Enums, Traits, Funktionen, Methoden und Uses aus Rust-Dateien."""
        try:
            content = full_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return

        file_nodes: list[SymbolNode] = []
        lines = content.splitlines()

        use_pat = re.compile(r"use\s+([A-Za-z0-9_:]+(?:\{[^}]+\})?);")
        type_pat = re.compile(r"(?:pub\s+)?(struct|enum|trait)\s+([A-Za-z0-9_]+)")
        impl_pat = re.compile(r"impl(?:\s+[A-Za-z0-9_]+)?\s+for\s+([A-Za-z0-9_]+)|impl\s+([A-Za-z0-9_]+)")
        fn_pat = re.compile(r"(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)")

        current_impl: str | None = None

        for idx, line in enumerate(lines, 1):
            s_line = line.strip()

            # Uses
            m_use = use_pat.search(s_line)
            if m_use:
                mod_path = m_use.group(1)
                self.imports.append(ImportNode(
                    file_path=rel_path, imported_module=mod_path, imported_name="*", line_number=idx,
                ))

            # Structs, Enums, Traits
            m_type = type_pat.search(s_line)
            if m_type:
                kind = m_type.group(1)
                tname = m_type.group(2)
                sym = SymbolNode(
                    name=tname,
                    kind=kind,
                    file_path=rel_path,
                    line_number=idx,
                    end_line_number=idx,
                    signature=s_line[:100],
                )
                file_nodes.append(sym)
                self._add_symbol(sym)

            # Impl Block
            m_impl = impl_pat.search(s_line)
            if m_impl:
                current_impl = m_impl.group(1) or m_impl.group(2)

            if s_line.startswith("}") and current_impl:
                # Naive impl closing
                pass

            # Functions & Methods
            m_fn = fn_pat.search(s_line)
            if m_fn:
                fname = m_fn.group(1)
                raw_args = m_fn.group(2) or ""
                args = [a.strip().split(":")[0] for a in raw_args.split(",") if a.strip()]
                is_method = "&self" in raw_args or "self" in args or bool(current_impl)
                sym_name = f"{current_impl}.{fname}" if (current_impl and is_method) else fname

                sym = SymbolNode(
                    name=sym_name,
                    kind="method" if is_method else "function",
                    file_path=rel_path,
                    line_number=idx,
                    end_line_number=idx,
                    args=args,
                    signature=s_line[:100],
                )
                file_nodes.append(sym)
                self._add_symbol(sym)

        self.file_symbols[rel_path] = file_nodes

    def _add_symbol(self, sym: SymbolNode) -> None:
        base_name = sym.name.split(".")[-1]
        self.symbols.setdefault(sym.name, []).append(sym)
        if base_name != sym.name:
            self.symbols.setdefault(base_name, []).append(sym)

    def find_definition(self, symbol_name: str) -> list[SymbolNode]:
        """Findet alle Definitionen eines Symbols im gesamten Projekt."""
        return self.symbols.get(symbol_name, [])

    def find_references(self, symbol_name: str) -> list[dict]:
        """
        Findet alle Vorkommen und Referenzen auf ein Symbol über alle Dateien hinweg.
        """
        references = []
        for file_path, syms in self.file_symbols.items():
            for s in syms:
                if symbol_name in s.calls or symbol_name in s.inherits:
                    references.append({
                        "file_path": file_path,
                        "line_number": s.line_number,
                        "caller_symbol": s.name,
                        "kind": s.kind,
                    })

        for imp in self.imports:
            if symbol_name in imp.imported_name or symbol_name == imp.imported_module:
                references.append({
                    "file_path": imp.file_path,
                    "line_number": imp.line_number,
                    "caller_symbol": "<import>",
                    "kind": "import",
                })

        return references

    def analyze_impact(self, symbol_name: str) -> ImpactAnalysis:
        """
        Führt eine detaillierte Auswirkungsanalyse durch: Welche Dateien und Symbole
        sind betroffen, wenn `symbol_name` geändert oder umbenannt wird?
        """
        definitions = self.find_definition(symbol_name)
        def_file = definitions[0].file_path if definitions else ""

        refs = self.find_references(symbol_name)
        ref_files = sorted({r["file_path"] for r in refs if r["file_path"] != def_file})
        calling_syms = sorted({r["caller_symbol"] for r in refs if r["caller_symbol"] != "<import>"})
        imported_in = sorted({r["file_path"] for r in refs if r["kind"] == "import"})

        return ImpactAnalysis(
            symbol_name=symbol_name,
            defining_file=def_file,
            referencing_files=ref_files,
            calling_symbols=calling_syms,
            imported_in=imported_in,
        )

    def get_summary(self) -> str:
        """Erzeugt eine kompakte Übersicht des Code-Graphen für den Agenten-Kontext."""
        total_symbols = sum(len(nodes) for nodes in self.file_symbols.values())
        classes_count = sum(1 for nodes in self.symbols.values() for n in nodes if n.kind == "class")
        funcs_count = sum(1 for nodes in self.symbols.values() for n in nodes if n.kind in ("function", "method"))

        lines = [
            f"Codebase-Graph: {self.indexed_files_count} Datei(en) indexiert | {total_symbols} Symbole ({classes_count} Klassen, {funcs_count} Funktionen/Methoden) | {len(self.imports)} Imports.",
        ]
        top_files = sorted(self.file_symbols.items(), key=lambda kv: len(kv[1]), reverse=True)[:5]
        if top_files:
            file_summaries = [f"`{fp}` ({len(syms)} Symbole)" for fp, syms in top_files]
            lines.append("Haupt-Module: " + ", ".join(file_summaries))

        return "\n".join(lines)
