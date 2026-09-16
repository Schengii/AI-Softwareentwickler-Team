"""
core/project_scaffold.py – Deterministisches Projektgerüst VOR der parallelen Entwicklung.

Die Laufdaten zeigten, dass ein großer Teil der Pre-Flight-Funde (bis zu 20 pro Lauf) nicht
aus fachlichen Fehlern, sondern aus fehlender gemeinsamer Struktur parallel arbeitender Agenten
entstand: fehlende `__init__.py`, `pytest.ini` ohne `pythonpath`, Test-Plugins ohne Manifest-
Eintrag, zwei Agenten, die `requirements.txt` jeweils neu anlegen.

`apply_scaffold()` legt nach der Planungsphase (Architekt hat `interface_contract.json`
geschrieben) und vor der Entwicklungsphase eine kleine, geprüfte Grundstruktur an:
- Paketordner + `__init__.py` für jedes im Schnittstellenvertrag genannte Python-Modul
- `pytest.ini` (pythonpath, testpaths, asyncio_mode)
- `requirements.txt` / `requirements-dev.txt` mit der Basis des erkannten Stacks
- `.env.example` für Konfigurationswerte

Grundsätze: Es wird NIE eine vorhandene Datei überschrieben, und es werden KEINE
Implementierungs-Stubs erzeugt (ein leerer `main.py`-Stub würde die Definition of Done
täuschen, obwohl nie echter Anwendungscode entstand).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from core.known_pitfalls import format_pitfalls_for_agents

logger = logging.getLogger(__name__)

STACK_FASTAPI = "fastapi"
STACK_PYTHON = "python"
STACK_UNKNOWN = "unknown"

_FASTAPI_RE = re.compile(r"\bfastapi\b|\brest[- ]?api\b|\bapi[- ]gateway\b|\bbackend\b|\bwebhook", re.IGNORECASE)
_PYTHON_RE = re.compile(r"\bpython\b|\bflask\b|\bdjango\b|\bpytest\b|\bcli\b", re.IGNORECASE)
_NODE_ONLY_RE = re.compile(r"\breact\b|\bvue\b|\bangular\b|\bnext\.js\b|\bcapacitor\b|\bnode\.?js\b|\btypescript\b", re.IGNORECASE)
_DATABASE_RE = re.compile(r"\bdatenbank\b|\bdatabase\b|\bsql(?:alchemy|ite)?\b|\bpostgres", re.IGNORECASE)
_AUTH_RE = re.compile(r"\bauth|\blogin\b|\bjwt\b|\btoken\b", re.IGNORECASE)

_PYTEST_INI = """[pytest]
pythonpath = .
testpaths = tests
asyncio_mode = auto
"""

_ENV_EXAMPLE = """# Vorlage - echte Werte gehören in eine lokale .env (nie committen)
APP_ENV=development
SECRET_KEY=change-me
DATABASE_URL=sqlite+aiosqlite:///./app.db
"""


@dataclass
class ScaffoldReport:
    stack: str
    created: list[str] = field(default_factory=list)
    skipped_existing: list[str] = field(default_factory=list)
    error: str = ""
    user_request: str = ""

    def format_for_agents(self) -> str:
        """Kontextabschnitt für die Entwicklungs-Agenten (Konventionen + angelegte Dateien)."""
        if self.stack == STACK_UNKNOWN:
            return ""
        lines = [
            "## 🧱 Projektgerüst (deterministisch angelegt, NICHT neu anlegen oder überschreiben)",
            f"Erkannter Stack: {self.stack}.",
        ]
        if self.created:
            lines.append("Bereits vorhanden: " + ", ".join(f"`{p}`" for p in self.created[:25]))
        lines += [
            "Konventionen:",
            "- Abhängigkeiten nur per `add_dependency` ergänzen (Laufzeit -> requirements.txt, Tests/Werkzeuge -> requirements-dev.txt).",
            "- `pytest.ini` existiert (pythonpath = ., asyncio_mode = auto) - keine zweite Pytest-Konfiguration anlegen.",
            "- Module exakt unter den Pfaden aus `interface_contract.json` anlegen; Re-Exporte in `__init__.py` erst, wenn das Zielmodul existiert.",
        ]
        # Volltext des Auftrags mitgeben, nicht nur das grobe Stack-Label ("fastapi"/
        # "python") - sonst aktiviert z. B. ein WebSocket-Dashboard-Auftrag nie die
        # "frontend"-Stolperfallen, weil das Wort "websocket" nirgends im Stack-Label steht.
        pitfalls = format_pitfalls_for_agents(f"{self.stack} {self.user_request}")
        if pitfalls:
            lines += ["", pitfalls]
        return "\n".join(lines)


def detect_stack(project_dir: str | Path, user_request: str = "") -> str:
    """Erkennt den Stack aus Auftrag und vorhandenen Dateien."""
    base = Path(project_dir)
    text = user_request or ""
    has_python_files = base.is_dir() and any(
        p for p in base.rglob("*.py") if ".ai_team_venv" not in p.parts and "node_modules" not in p.parts
    )
    if (base / "package.json").is_file() and not has_python_files and not _FASTAPI_RE.search(text):
        return STACK_UNKNOWN
    if _NODE_ONLY_RE.search(text) and not (_FASTAPI_RE.search(text) or _PYTHON_RE.search(text) or has_python_files):
        return STACK_UNKNOWN
    if re.search(r"\bfastapi\b", text, re.IGNORECASE) or _contract_mentions_fastapi(base):
        return STACK_FASTAPI
    if _FASTAPI_RE.search(text) and not re.search(r"\bflask\b|\bdjango\b|\bexpress\b", text, re.IGNORECASE):
        return STACK_FASTAPI
    if _PYTHON_RE.search(text) or has_python_files or _contract_python_modules(base):
        return STACK_PYTHON
    return STACK_UNKNOWN


def _contract_python_modules(base: Path) -> list[str]:
    path = base / "interface_contract.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    modules = data.get("modules", data) if isinstance(data, dict) else {}
    if not isinstance(modules, dict):
        return []
    result = []
    for key in modules:
        key = str(key).replace("\\", "/").strip("/")
        if not key or ".." in key.split("/"):
            continue
        result.append(key if key.endswith(".py") else key.replace(".", "/") + ".py")
    return result


def _contract_mentions_fastapi(base: Path) -> bool:
    path = base / "interface_contract.json"
    try:
        return path.is_file() and "fastapi" in path.read_text(encoding="utf-8").lower()
    except OSError:
        return False


def _baseline_requirements(stack: str, user_request: str) -> tuple[list[str], list[str]]:
    if stack == STACK_FASTAPI:
        runtime = ["fastapi", "uvicorn[standard]", "pydantic-settings"]
        if _DATABASE_RE.search(user_request or ""):
            runtime += ["sqlalchemy>=2.0", "aiosqlite", "greenlet"]
        if _AUTH_RE.search(user_request or ""):
            runtime += ["PyJWT", "python-multipart"]
        return runtime, ["pytest", "pytest-asyncio", "httpx"]
    if stack == STACK_PYTHON:
        return [], ["pytest"]
    return [], []


def _write_if_missing(base: Path, rel: str, content: str, report: ScaffoldReport) -> None:
    target = base / rel
    if target.exists():
        report.skipped_existing.append(rel)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    report.created.append(rel)


def _has_pytest_config(base: Path) -> bool:
    if (base / "pytest.ini").is_file():
        return True
    for name, marker in (("pyproject.toml", "[tool.pytest"), ("setup.cfg", "[tool:pytest]"), ("tox.ini", "[pytest]")):
        candidate = base / name
        try:
            if candidate.is_file() and marker in candidate.read_text(encoding="utf-8", errors="ignore"):
                return True
        except OSError:
            continue
    return False


_PACKAGE_ROOT_NAMES = frozenset({"app", "src"})


def is_safe_project_dir(project_dir: str | Path) -> bool:
    """Schreibende Autofixes nur in echten Zielprojekten - NIE im Framework-Repository selbst,
    in einem seiner Elternordner oder im gesamten `workspace/`-Sammelordner.

    Realer Fund bei der Einführung dieses Moduls: Tests rufen die Fachbereichs-Hierarchie mit
    `project_dir="."` (Framework-Root) auf - ohne diese Schranke legte das Gerüst leere
    `__init__.py` in fremden Workspace-Projekten an.
    """
    try:
        from config import BASE_DIR

        target = Path(project_dir).resolve()
        framework_root = Path(BASE_DIR).resolve()
    except (OSError, ImportError):
        return False
    if target == framework_root or target in framework_root.parents:
        return False
    if target == framework_root / "workspace":
        return False
    return not ((target / "agents").is_dir() and (target / "core").is_dir() and (target / "workspace").is_dir())


def ensure_package_inits(project_dir: str | Path, extra_modules: list[str] | None = None) -> list[str]:
    """Legt fehlende `__init__.py` in Python-Paketordnern an (deterministisch, kein LLM).

    Bewusst eng gefasst: nur Ordner unterhalb eines Paket-Roots - `app/`, `src/`, ein
    Top-Level-Ordner, der selbst bereits ein Paket ist (`__init__.py` vorhanden), oder ein
    Elternordner eines Moduls aus `interface_contract.json`. Beliebige Ordner mit `.py`-Dateien
    (Skripte, Beispiele, verschachtelte Fremdprojekte) werden nie zu Paketen gemacht.
    `tests/` bleibt unberührt. Im Framework-Repository selbst passiert nichts
    (`is_safe_project_dir`).
    """
    base = Path(project_dir)
    if not base.is_dir() or not is_safe_project_dir(base):
        return []
    skip = {".ai_team_venv", ".venv", "venv", "node_modules", "__pycache__", "tests", "test", "static",
            "templates", "docs", "migrations", "alembic", "scripts", ".ai_team_runs", ".git", "workspace"}

    def _is_package_root(name: str) -> bool:
        return name in _PACKAGE_ROOT_NAMES or (base / name / "__init__.py").is_file()

    package_dirs: set[Path] = set()
    for module in extra_modules or []:
        parts = Path(module).parts[:-1]
        if not parts or parts[0] in skip or ".." in parts:
            continue
        for i in range(1, len(parts) + 1):
            package_dirs.add(base.joinpath(*parts[:i]))
    for root_name in sorted(p.name for p in base.iterdir() if p.is_dir() and _is_package_root(p.name)):
        if root_name in skip:
            continue
        for py_file in (base / root_name).rglob("*.py"):
            rel_parts = py_file.relative_to(base).parts
            if any(p in skip or p.startswith(".") for p in rel_parts[:-1]):
                continue
            for i in range(1, len(rel_parts)):
                package_dirs.add(base.joinpath(*rel_parts[:i]))
    created: list[str] = []
    for directory in sorted(package_dirs):
        rel_parts = directory.relative_to(base).parts
        if not rel_parts or any(p in skip or p.startswith(".") for p in rel_parts):
            continue
        init_file = directory / "__init__.py"
        if init_file.exists():
            continue
        try:
            directory.mkdir(parents=True, exist_ok=True)
            init_file.write_text("", encoding="utf-8")
            created.append(init_file.relative_to(base).as_posix())
        except OSError as e:
            logger.warning("__init__.py konnte nicht angelegt werden (%s): %r", init_file, e)
    return created


def apply_scaffold(project_dir: str | Path, user_request: str = "") -> ScaffoldReport:
    """Legt das Gerüst an. Fehler werden im Report vermerkt, nie geworfen."""
    base = Path(project_dir)
    if not is_safe_project_dir(base):
        return ScaffoldReport(stack=STACK_UNKNOWN, error="Framework-Verzeichnis ist kein Zielprojekt - Gerüst übersprungen.")
    stack = detect_stack(base, user_request)
    report = ScaffoldReport(stack=stack, user_request=user_request)
    if stack == STACK_UNKNOWN:
        return report
    try:
        base.mkdir(parents=True, exist_ok=True)
        report.created += ensure_package_inits(base, _contract_python_modules(base))
        if not _has_pytest_config(base):
            _write_if_missing(base, "pytest.ini", _PYTEST_INI, report)
        runtime, dev = _baseline_requirements(stack, user_request)
        if runtime:
            _write_if_missing(base, "requirements.txt", "\n".join(runtime) + "\n", report)
        if dev:
            if runtime or (base / "requirements.txt").is_file():
                _write_if_missing(base, "requirements-dev.txt", "\n".join(dev) + "\n", report)
            else:
                _write_if_missing(base, "requirements.txt", "", report)
                _write_if_missing(base, "requirements-dev.txt", "\n".join(dev) + "\n", report)
        if stack == STACK_FASTAPI:
            _write_if_missing(base, ".env.example", _ENV_EXAMPLE, report)
    except OSError as e:
        report.error = str(e)
        logger.warning("Projektgerüst konnte nicht vollständig angelegt werden (%s): %r", base, e)
    return report
