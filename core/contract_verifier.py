"""
core/contract_verifier.py – API-Contract Lock & Schnittstellen-Validierung

Gleicht statisch die im Backend (FastAPI, Flask, Express) deklarierten REST-Endpunkte
mit den im Frontend (Vanilla JS, TypeScript, React, Vue) tatsächlich per fetch()/axios
aufgerufenen URLs ab. Verhindert, dass Frontend- und Backend-Agenten aneinander
vorbeientwickeln (z. B. abweichende Routen wie /api/notes vs. /api/v1/notes).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

_IGNORED_DIRS = {
    ".venv", "venv", ".ai_team_venv", "node_modules", "__pycache__",
    ".git", "dist", "build", ".pytest_cache", ".ruff_cache",
}

# Regex für FastAPI / Starlette: @app.get("/path"), @router.post("/path", ...), @api_router.delete(...)
_FASTAPI_ROUTE_PATTERN = re.compile(
    r'@(?:app|router|api|api_router)\.(get|post|put|delete|patch|options|head)\s*\(\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)

# Regex für Flask / Quart: @app.route("/path", methods=["GET", "POST"])
_FLASK_ROUTE_PATTERN = re.compile(
    r'@(?:app|api|blueprint)\.route\s*\(\s*["\']([^"\']+)["\'](?:\s*,\s*methods\s*=\s*\[([^\]]+)\])?',
    re.IGNORECASE,
)

# Regex für Express.js: app.get("/path", ...), router.post("/path", ...)
_EXPRESS_ROUTE_PATTERN = re.compile(
    r'(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)

# Regex für Frontend fetch() Aufrufe:
# fetch("/api/items", { method: "POST" }) oder fetch(`/api/items/${id}`)
_FETCH_CALL_PATTERN = re.compile(
    r'fetch\s*\(\s*(?:["\']([^"\']+)["\']|`([^`]+)`)(?:\s*,\s*\{([^}]+)\})?',
    re.DOTALL,
)

# Regex für Frontend axios Aufrufe:
# axios.get("/api/items"), axios.post("/api/items", ...), axios.delete(`/api/items/${id}`)
_AXIOS_CALL_PATTERN = re.compile(
    r'axios\.(get|post|put|delete|patch)\s*\(\s*(?:["\']([^"\']+)["\']|`([^`]+)`)',
    re.IGNORECASE,
)


@dataclass
class Endpoint:
    """Ein im Backend deklarierter Endpunkt."""
    method: str
    path: str
    source_file: str
    line_number: int = 0
    normalized_path: str = ""

    def __post_init__(self):
        self.method = self.method.upper()
        if not self.normalized_path:
            self.normalized_path = normalize_path(self.path)


@dataclass
class FrontendApiCall:
    """Ein im Frontend getätigter API-Aufruf."""
    method: str
    raw_path: str
    source_file: str
    line_number: int = 0
    normalized_path: str = ""

    def __post_init__(self):
        self.method = self.method.upper()
        if not self.normalized_path:
            self.normalized_path = normalize_path(self.raw_path)


@dataclass
class ContractMismatch:
    """Eine festgestellte Abweichung zwischen Frontend und Backend."""
    mismatch_type: Literal["MISSING_ENDPOINT", "METHOD_MISMATCH", "PARAM_MISMATCH"]
    frontend_call: FrontendApiCall
    details: str
    suggested_fix: str = ""


@dataclass
class ContractReport:
    """Ergebnis der API-Contract Prüfung."""
    passed: bool = True
    endpoints_found: int = 0
    frontend_calls_found: int = 0
    endpoints: list[Endpoint] = field(default_factory=list)
    frontend_calls: list[FrontendApiCall] = field(default_factory=list)
    mismatches: list[ContractMismatch] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def format_summary(self) -> str:
        """Formatiert das Ergebnis für Berichte und Logs."""
        if self.endpoints_found == 0 and self.frontend_calls_found == 0:
            return "ℹ️ Keine Backend-Routen oder Frontend-API-Aufrufe gefunden (kein Fullstack-Check nötig)."

        lines = [
            f"🤝 API-Contract Prüfung: {'✅ Bestanden' if self.passed else '❌ Mismatches gefunden'}",
            f"   Backend-Endpunkte: {self.endpoints_found} | Frontend-Aufrufe: {self.frontend_calls_found}",
        ]

        if self.mismatches:
            lines.append(f"   ⚠️ {len(self.mismatches)} Diskrepanz(en) erkannt:")
            for m in self.mismatches:
                lines.append(
                    f"     - [{m.mismatch_type}] {m.frontend_call.method} {m.frontend_call.raw_path} "
                    f"in {m.frontend_call.source_file}: {m.details}"
                )
                if m.suggested_fix:
                    lines.append(f"       👉 Tipp: {m.suggested_fix}")

        return "\n".join(lines)


def normalize_path(path: str) -> str:
    """Normalisiert Pfade für den robusten Vergleich.
    
    Wandelt Pfad-Parameter in ein einheitliches Format um:
    - /api/items/{item_id} -> /api/items/:param
    - /api/items/<int:id> -> /api/items/:param
    - /api/items/${id} -> /api/items/:param
    - Entfernt Query-Strings: /api/search?q=test -> /api/search
    - Entfernt führende/nachfolgende Slashes
    """
    # Query-Parameter abschneiden
    path = path.split("?")[0]

    # Template-Strings ${...} in JS ersetzen
    path = re.sub(r"\$\{[^}]+\}", ":param", path)

    # FastAPI / OpenAPI {param} ersetzen
    path = re.sub(r"\{[^}]+\}", ":param", path)

    # Flask <type:param> oder <param> ersetzen
    path = re.sub(r"<[^>]+>", ":param", path)

    # Mehrfache Slashes einebnen und trailing slash entfernen
    parts = [p for p in path.strip("/").split("/") if p]
    return "/" + "/".join(parts) if parts else "/"


def _extract_fetch_method(options_str: str | None) -> str:
    """Extrahiert die HTTP-Methode aus dem zweiten Argument von fetch()."""
    if not options_str:
        return "GET"
    match = re.search(r'method\s*:\s*["\']([A-Za-z]+)["\']', options_str, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return "GET"


def extract_backend_endpoints(project_dir: Path) -> list[Endpoint]:
    """Sucht in Python- und JS/TS-Dateien nach deklarierten Backend-Routen."""
    endpoints: list[Endpoint] = []

    # 1. Python-Dateien scannen (FastAPI, Flask)
    for py_file in project_dir.rglob("*.py"):
        if any(part in _IGNORED_DIRS for part in py_file.relative_to(project_dir).parts):
            continue

        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        rel_path = str(py_file.relative_to(project_dir)).replace("\\", "/")

        # FastAPI
        for line_no, line in enumerate(content.splitlines(), 1):
            for match in _FASTAPI_ROUTE_PATTERN.finditer(line):
                method = match.group(1).upper()
                route_path = match.group(2)
                endpoints.append(Endpoint(
                    method=method,
                    path=route_path,
                    source_file=rel_path,
                    line_number=line_no,
                ))

            # Flask
            for match in _FLASK_ROUTE_PATTERN.finditer(line):
                route_path = match.group(1)
                methods_str = match.group(2)
                if methods_str:
                    methods = [m.strip().strip("'\"").upper() for m in methods_str.split(",") if m.strip()]
                else:
                    methods = ["GET"]

                for m in methods:
                    endpoints.append(Endpoint(
                        method=m,
                        path=route_path,
                        source_file=rel_path,
                        line_number=line_no,
                    ))

    # 2. Node/Express-Dateien scannen
    for js_file in list(project_dir.rglob("*.js")) + list(project_dir.rglob("*.ts")):
        if any(part in _IGNORED_DIRS for part in js_file.relative_to(project_dir).parts):
            continue

        try:
            content = js_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        rel_path = str(js_file.relative_to(project_dir)).replace("\\", "/")
        for line_no, line in enumerate(content.splitlines(), 1):
            for match in _EXPRESS_ROUTE_PATTERN.finditer(line):
                method = match.group(1).upper()
                route_path = match.group(2)
                endpoints.append(Endpoint(
                    method=method,
                    path=route_path,
                    source_file=rel_path,
                    line_number=line_no,
                ))

    return endpoints


def extract_frontend_api_calls(project_dir: Path) -> list[FrontendApiCall]:
    """Sucht in Frontend-Dateien (HTML, JS, TS, Vue, Svelte) nach getätigten API-Aufrufen."""
    calls: list[FrontendApiCall] = []

    frontend_extensions = ("*.html", "*.js", "*.jsx", "*.ts", "*.tsx", "*.vue")
    frontend_files: list[Path] = []
    for ext in frontend_extensions:
        frontend_files.extend(project_dir.rglob(ext))

    for f in frontend_files:
        if any(part in _IGNORED_DIRS for part in f.relative_to(project_dir).parts):
            continue

        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        rel_path = str(f.relative_to(project_dir)).replace("\\", "/")

        # 1. fetch() Aufrufe (multiline-fähig)
        for match in re.finditer(r'fetch\s*\(\s*(?:["\']([^"\'\r\n]+)["\']|`([^`]+)`)([\s\S]*?)(?:\)|;|\n\s*\n)', content):
            raw_path = match.group(1) or match.group(2)
            if not raw_path:
                continue

            raw_path = raw_path.strip()
            # Externe URLs (http://, https://) ignorieren, nur interne APIs prüfen
            if raw_path.startswith(("http://", "https://", "//")):
                continue

            # Reine statische Asset-Loads ignorieren (z. B. fetch('./icon.svg'))
            if raw_path.endswith((".png", ".jpg", ".svg", ".css", ".ico", ".json")) and "/api" not in raw_path:
                continue

            options_block = match.group(3) or ""
            method = _extract_fetch_method(options_block)
            line_no = content[:match.start()].count("\n") + 1

            calls.append(FrontendApiCall(
                method=method,
                raw_path=raw_path,
                source_file=rel_path,
                line_number=line_no,
            ))

        # 2. axios Aufrufe (multiline-fähig)
        for match in re.finditer(r'axios\.(get|post|put|delete|patch)\s*\(\s*(?:["\']([^"\'\r\n]+)["\']|`([^`]+)`)', content, re.IGNORECASE):
            method = match.group(1).upper()
            raw_path = (match.group(2) or match.group(3) or "").strip()
            if not raw_path or raw_path.startswith(("http://", "https://", "//")):
                continue

            line_no = content[:match.start()].count("\n") + 1
            calls.append(FrontendApiCall(
                method=method,
                raw_path=raw_path,
                source_file=rel_path,
                line_number=line_no,
            ))

    return calls


def verify_api_contracts(project_dir: Path | str) -> ContractReport:
    """Führt den vollständigen statischen API-Contract-Check durch."""
    pdir = Path(project_dir).resolve()
    endpoints = extract_backend_endpoints(pdir)
    frontend_calls = extract_frontend_api_calls(pdir)

    report = ContractReport(
        passed=True,
        endpoints_found=len(endpoints),
        frontend_calls_found=len(frontend_calls),
        endpoints=endpoints,
        frontend_calls=frontend_calls,
    )

    if not endpoints or not frontend_calls:
        # Kein Fullstack-Projekt oder keine API-Aufrufe vorhanden
        return report

    # Indexiere Backend-Endpunkte für schnelles Nachschlagen:
    # Key: normalized_path -> Dict[method, Endpoint]
    backend_map: dict[str, dict[str, Endpoint]] = {}
    for ep in endpoints:
        if ep.normalized_path not in backend_map:
            backend_map[ep.normalized_path] = {}
        backend_map[ep.normalized_path][ep.method] = ep

    for fc in frontend_calls:
        target_norm = fc.normalized_path

        # 1. Prüfe ob der Pfad überhaupt im Backend existiert
        if target_norm not in backend_map:
            # Suche nach ähnlichen Routen für Hilfestellung
            candidates = [p for p in backend_map.keys() if p.split("/")[-1] == target_norm.split("/")[-1]]
            suggestion = f"Existierende Routen mit ähnlichem Namen: {', '.join(candidates)}" if candidates else ""
            report.mismatches.append(ContractMismatch(
                mismatch_type="MISSING_ENDPOINT",
                frontend_call=fc,
                details=f"Kein Backend-Endpunkt für Pfad '{fc.raw_path}' (normalisiert: {target_norm}) definiert.",
                suggested_fix=suggestion,
            ))
            report.passed = False
            continue

        # 2. Prüfe ob die HTTP-Methode übereinstimmt
        methods_for_path = backend_map[target_norm]
        if fc.method not in methods_for_path:
            available = ", ".join(methods_for_path.keys())
            report.mismatches.append(ContractMismatch(
                mismatch_type="METHOD_MISMATCH",
                frontend_call=fc,
                details=f"Frontend nutzt {fc.method}, Backend unterstützt für '{target_norm}' jedoch nur: [{available}].",
                suggested_fix=f"Ändere die Frontend-Methode zu {list(methods_for_path.keys())[0]} oder ergänze Backend-Route.",
            ))
            report.passed = False

    return report
