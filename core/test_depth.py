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


def _route_regex(route_path: str) -> re.Pattern[str]:
    normalized = normalize_path(route_path)
    if normalized == "/":
        return re.compile(r"^/$")
    segments = [r"[^/]+" if seg == ":param" else re.escape(seg) for seg in normalized.strip("/").split("/")]
    return re.compile(r"(?:^|/)" + "/".join(segments) + r"$")


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
