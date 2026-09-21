"""
core/test_depth.py – Testtiefe: Werden die angebotenen API-Routen überhaupt getestet?

Analyse 2026-09-15: nexus_resilience_gateway (HMAC, Replay-Schutz, Circuit Breaker, DLQ, Dashboard)
galt mit 7 Tests in 2 Sekunden als "Testsuite bestanden". Eine grüne, aber flache Testsuite ist
kein Qualitätsnachweis.

`analyze_test_depth()` gleicht deterministisch die Backend-Routen (core/contract_verifier.py) mit
den in Testdateien verwendeten URL-Pfaden ab. Router-Präfixe werden toleriert: die Route
`/metrics` gilt als getestet, wenn ein Test `/api/metrics` aufruft; Pfad-Parameter passen auf
konkrete Werte (`/items/{id}` ↔ `/items/42`).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from core.contract_verifier import extract_backend_endpoints, normalize_path

_SKIP_DIRS = frozenset({".venv", "venv", ".ai_team_venv", "node_modules", ".git", "__pycache__", "dist", "build", ".ai_team_runs"})
_PATH_LITERAL_RE = re.compile(r"""[`"'](/[^`"'\s]*)[`"']""")
_PY_TEST_RE = re.compile(r"^\s*(?:async\s+)?def\s+test_\w+", re.MULTILINE)
_PY_TEST_NAME_RE = re.compile(r"^\s*(?:async\s+)?def\s+(test_\w+)", re.MULTILINE)
_JS_TEST_RE = re.compile(r"\b(?:it|test)\s*\(\s*[`'\"]")


@dataclass
class RouteRef:
    method: str
    path: str
    source_file: str

    def label(self) -> str:
        return f"{self.method} {self.path} ({self.source_file})"


@dataclass
class TestDepthReport:
    routes: list[RouteRef] = field(default_factory=list)
    untested_routes: list[RouteRef] = field(default_factory=list)
    test_count: int = 0
    min_ratio: float = 0.6

    @property
    def applicable(self) -> bool:
        return bool(self.routes)

    @property
    def tested_ratio(self) -> float:
        if not self.routes:
            return 1.0
        return (len(self.routes) - len(self.untested_routes)) / len(self.routes)

    @property
    def passed(self) -> bool:
        return not self.applicable or self.tested_ratio >= self.min_ratio

    def format_summary(self) -> str:
        if not self.applicable:
            return "Testtiefe: keine Backend-Routen gefunden – nicht anwendbar."
        tested = len(self.routes) - len(self.untested_routes)
        text = (
            f"Testtiefe: {tested}/{len(self.routes)} API-Routen in Tests aufgerufen "
            f"({self.tested_ratio:.0%}, Mindestwert {self.min_ratio:.0%}), {self.test_count} Testfunktionen"
        )
        if self.untested_routes:
            text += " – ungetestet: " + "; ".join(r.label() for r in self.untested_routes[:10])
            if len(self.untested_routes) > 10:
                text += f" … und {len(self.untested_routes) - 10} weitere"
        return text


def _is_test_file(rel_path: str) -> bool:
    name = rel_path.rsplit("/", 1)[-1]
    return (
        rel_path.startswith(("tests/", "test/", "__tests__/")) or "/tests/" in rel_path or "/__tests__/" in rel_path
        or name.startswith("test_") or name.endswith(("_test.py", ".test.ts", ".test.js", ".spec.ts", ".spec.js", ".test.tsx"))
    )


def _collect_test_sources(project_dir: Path) -> tuple[list[str], int]:
    literals: list[str] = []
    count = 0
    for dirpath, dirnames, filenames in os.walk(project_dir):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for filename in filenames:
            if not filename.endswith((".py", ".ts", ".tsx", ".js")):
                continue
            path = Path(dirpath) / filename
            rel = path.relative_to(project_dir).as_posix()
            if not _is_test_file(rel):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            count += len(_PY_TEST_RE.findall(text)) if filename.endswith(".py") else len(_JS_TEST_RE.findall(text))
            literals.extend(normalize_path(m) for m in _PATH_LITERAL_RE.findall(text))
    return literals, count


def collect_test_function_names(project_dir: str | Path) -> set[str]:
    """Sammelt die Namen aller Python-Testfunktionen (`test_*`) im Projekt.

    Analyse EventForge-Lauf (entwickle_eventforge_ein_webhook, 20260916_154524): Eine
    HEAVY_MODEL-Eskalation nach zwei erfolglosen Fixversuchen meldete "Testsuite bestanden" -
    tatsächlich hatte der Fix-Agent aber 3 der ursprünglich 7 Tests ERSATZLOS GELÖSCHT (u.a.
    `test_forwarding_worker_mock`, den einzigen Test für die Kernfunktion des Projekts) statt
    den zugrunde liegenden Fehler zu beheben. Eine grün werdende, aber schrumpfende Testsuite
    ist kein Erfolg - siehe `_test_names_lost()`/den Aufrufer in verification.py, der diese
    Funktion nutzt, um genau das zu erkennen, BEVOR ein Fix-Ergebnis als Erfolg gilt.
    """
    base = Path(project_dir)
    names: set[str] = set()
    if not base.is_dir():
        return names
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = Path(dirpath) / filename
            rel = path.relative_to(base).as_posix()
            if not _is_test_file(rel):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            names.update(_PY_TEST_NAME_RE.findall(text))
    return names


def snapshot_test_files(project_dir: str | Path) -> dict[str, str]:
    """Inhalt aller Python-Testdateien vor einem Fix-Versuch - Gegenstück zu
    `core.failure_triage.snapshot_dependency_manifests()`, aber für Testdateien statt
    Abhängigkeits-Manifeste. Wird von agents/orchestrator/verification.py genutzt, um eine per
    `collect_test_function_names()` erkannte Test-Schrumpfung (siehe Docstring oben) tatsächlich
    rückgängig zu machen, statt sie nur zu protokollieren."""
    base = Path(project_dir)
    snapshot: dict[str, str] = {}
    if not base.is_dir():
        return snapshot
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = Path(dirpath) / filename
            rel = path.relative_to(base).as_posix()
            if not _is_test_file(rel):
                continue
            try:
                snapshot[rel] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return snapshot


def restore_test_files(project_dir: str | Path, snapshot: dict[str, str]) -> list[str]:
    """Stellt den Stand aus snapshot_test_files() für Dateien wieder her, die seitdem
    Testfunktionen VERLOREN haben (per Namensabgleich, nicht nur Byte-Gleichheit - ein Fix darf
    weiterhin Tests umformulieren, nur nicht ersatzlos entfernen). Rückgabe: wiederhergestellte
    relative Pfade."""
    base = Path(project_dir)
    restored: list[str] = []
    for rel, before_text in snapshot.items():
        path = base / rel
        try:
            after_text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        except OSError:
            continue
        before_names = set(_PY_TEST_NAME_RE.findall(before_text))
        after_names = set(_PY_TEST_NAME_RE.findall(after_text))
        if before_names - after_names:
            try:
                path.write_text(before_text, encoding="utf-8")
                restored.append(rel)
            except OSError:
                continue
    return restored


def _route_regex(route_path: str) -> re.Pattern[str]:
    normalized = normalize_path(route_path)
    if normalized == "/":
        return re.compile(r"^/$")
    segments = [r"[^/]+" if seg == ":param" else re.escape(seg) for seg in normalized.strip("/").split("/")]
    return re.compile(r"(?:^|/)" + "/".join(segments) + r"$")


# P4-3 (ROADMAP_TEMP.md): Verzeichnisnamen, die typischerweise die eigentliche Fachlogik tragen
# (nicht Routing/Controller-Code). Bewusst grob - ein deterministisches, projektübergreifend
# funktionierendes Signal statt einer Stack-spezifischen Konvention.
_DOMAIN_DIR_MARKERS = frozenset({"core", "services", "domain", "logic"})


@dataclass
class DomainSymbolRef:
    name: str
    kind: str
    file_path: str

    def label(self) -> str:
        return f"{self.kind} {self.name} ({self.file_path})"


@dataclass
class DomainDepthReport:
    """Ergänzendes Signal zu TestDepthReport (siehe Moduldocstring, P4-3): misst nicht, ob
    API-Routen aufgerufen werden, sondern ob die dahinterliegende FACHLOGIK überhaupt in einem
    Test vorkommt - `cachegrid_proxy` (1 Route, 100% Routenabdeckung) blieb bei der Fachlogik
    (LRU-Eviction, TTL-Verfall) komplett ungetestet, ohne dass TestDepthReport das je sehen
    konnte."""
    symbols: list[DomainSymbolRef] = field(default_factory=list)
    untested_symbols: list[DomainSymbolRef] = field(default_factory=list)
    min_ratio: float = 0.5

    @property
    def applicable(self) -> bool:
        return bool(self.symbols)

    @property
    def tested_ratio(self) -> float:
        if not self.symbols:
            return 1.0
        return (len(self.symbols) - len(self.untested_symbols)) / len(self.symbols)

    @property
    def passed(self) -> bool:
        return not self.applicable or self.tested_ratio >= self.min_ratio

    def format_summary(self) -> str:
        if not self.applicable:
            return "Fachlogik-Testtiefe: keine Symbole in core/services/domain/logic-Verzeichnissen gefunden – nicht anwendbar."
        tested = len(self.symbols) - len(self.untested_symbols)
        text = (
            f"Fachlogik-Testtiefe: {tested}/{len(self.symbols)} öffentliche Funktionen/Klassen in "
            f"core/services/domain/logic in mindestens einem Test importiert UND aufgerufen "
            f"({self.tested_ratio:.0%}, Richtwert {self.min_ratio:.0%})"
        )
        if self.untested_symbols:
            text += " – ungetestet: " + "; ".join(r.label() for r in self.untested_symbols[:10])
            if len(self.untested_symbols) > 10:
                text += f" … und {len(self.untested_symbols) - 10} weitere"
        return text


def _is_domain_dir(rel_path: str) -> bool:
    parts = rel_path.split("/")[:-1]
    return any(p in _DOMAIN_DIR_MARKERS for p in parts)


def analyze_domain_logic_depth(project_dir: str | Path, min_ratio: float = 0.5) -> DomainDepthReport:
    """Deterministisches Zusatzsignal (kein LLM-Aufruf): baut auf core/code_graph.py auf, das
    Python/JS/TS/Go/Rust-Quellcode bereits per AST in Symbole (Funktionen/Klassen/Methoden),
    Imports und Aufrufe zerlegt. Ein Symbol gilt als getestet, wenn sein (unqualifizierter)
    Name in MINDESTENS EINER Testdatei sowohl importiert als auch aufgerufen wird - reiner
    Import (z.B. für einen ungenutzten Fixture-Parameter) reicht nicht, reines Aufrufen ohne
    erkennbaren Import ist bei dynamischen Importmustern ein zu unsicheres Signal.

    Bekannte Grenzen (deshalb bewusst NICHT blockierend, siehe config.ENABLE_DOMAIN_LOGIC_DEPTH_
    SIGNAL): Decorator-Aufrufe, Dependency-Injection-Container und dynamischer Dispatch zeigen
    sich im AST nicht als direkter Funktionsaufruf - ein echt getestetes Symbol kann dadurch
    fälschlich als ungetestet erscheinen. Symbole mit demselben Namen in mehreren Domain-Dateien
    werden dedupliziert (eine gemeinsame Testtiefen-Bilanz statt einer Datei-genauen)."""
    from core.code_graph import CodebaseGraph

    base = Path(project_dir)
    report = DomainDepthReport(min_ratio=min_ratio)
    if not base.is_dir():
        return report

    graph = CodebaseGraph(base)
    test_files = [f for f in graph.file_symbols if _is_test_file(f)]
    if not test_files:
        return report

    imported_in_tests: set[str] = set()
    called_in_tests: set[str] = set()
    for imp in graph.imports:
        if imp.file_path in test_files:
            imported_in_tests.add(imp.imported_name)
    for f in test_files:
        for sym in graph.file_symbols.get(f, []):
            called_in_tests.update(sym.calls)

    seen: set[str] = set()
    for file_path, symbols in graph.file_symbols.items():
        if not _is_domain_dir(file_path) or _is_test_file(file_path):
            continue
        for sym in symbols:
            if sym.kind not in ("function", "class", "method"):
                continue
            base_name = sym.name.split(".")[-1]
            if base_name.startswith("_") or base_name in seen:
                continue
            seen.add(base_name)
            ref = DomainSymbolRef(name=sym.name, kind=sym.kind, file_path=file_path)
            report.symbols.append(ref)
            if not (base_name in imported_in_tests and base_name in called_in_tests):
                report.untested_symbols.append(ref)
    return report


def analyze_test_depth(project_dir: str | Path, min_ratio: float = 0.6) -> TestDepthReport:
    base = Path(project_dir)
    report = TestDepthReport(min_ratio=min_ratio)
    if not base.is_dir():
        return report
    seen: set[tuple[str, str]] = set()
    for endpoint in extract_backend_endpoints(base):
        source = endpoint.source_file.replace("\\", "/")
        key = (endpoint.method.upper(), normalize_path(endpoint.path))
        if _is_test_file(source) or key in seen:
            continue
        seen.add(key)
        report.routes.append(RouteRef(endpoint.method.upper(), endpoint.path, source))
    literals, report.test_count = _collect_test_sources(base)
    for route in report.routes:
        pattern = _route_regex(route.path)
        if not any(pattern.search(literal) for literal in literals):
            report.untested_routes.append(route)
    return report
