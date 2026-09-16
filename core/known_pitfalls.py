"""
core/known_pitfalls.py – Zentrales, deklaratives Regelwerk bekannter Stolperfallen.

Bisher waren Wissen über Importnamen, toxische Pakete und versteckte Laufzeit-Abhängigkeiten
über mehrere Module verteilt (`core/pre_flight_check.py`, `core/verifier/models.py`,
`core/manifest_guard.py`) – mit auseinanderlaufenden Kopien. Folge: `import jwt` wurde in der
einen Tabelle korrekt zu `PyJWT` aufgelöst, in der anderen nicht; der Pre-Flight-Check trug
daraufhin das toxische Paket `jwt` in `requirements.txt` ein, das der Manifest-Guard direkt
danach wieder entfernte.

Dieses Modul ist die EINZIGE Quelle für:
- `IMPORT_TO_PACKAGE`: Importname -> PyPI-Paketname
- `TRANSITIVE_PROVIDES`: Pakete, die weitere Import-Namespaces zuverlässig mitinstallieren
- `DEV_ONLY_PACKAGES`: Pakete, die nur für Tests/Werkzeuge gebraucht werden
- `TOXIC_DEPENDENCY_RULES`: Pakete, die einen fremden Namespace überschreiben
- `HIDDEN_RUNTIME_DEPENDENCIES`: Laufzeit-Abhängigkeiten ohne direkten Import
- `PITFALL_CATALOG`: menschen- und agentenlesbare Beschreibung aller Regeln

Neue Erkenntnisse aus Team-Lektionen werden hier als Regel ergänzt (mit Test in
`tests/test_known_pitfalls.py`), nicht als Sonderfall im jeweiligen Prüfmodul.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


def normalize_package_name(name: str) -> str:
    """PEP 503: Groß-/Kleinschreibung und `-`/`_`/`.` sind gleichwertig."""
    return re.sub(r"[-_.]+", "-", name or "").lower()


# ── Importname -> PyPI-Paket ────────────────────────────────────────────────────────────────
IMPORT_TO_PACKAGE: dict[str, str] = {
    "attr": "attrs",
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "jose": "python-jose",
    "jwt": "PyJWT",
    "multipart": "python-multipart",
    "PIL": "pillow",
    "pydantic_settings": "pydantic-settings",
    "pytest_asyncio": "pytest-asyncio",
    "pytest_cov": "pytest-cov",
    "pytest_mock": "pytest-mock",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
    "magic": "python-magic",
    "Crypto": "pycryptodome",
    "OpenSSL": "pyopenssl",
    "serial": "pyserial",
    "socketio": "python-socketio",
    "engineio": "python-engineio",
    "slugify": "python-slugify",
    "docx": "python-docx",
    "telegram": "python-telegram-bot",
}


def package_for_import(import_name: str) -> str:
    """PyPI-Paketname für einen Top-Level-Importnamen (Fallback: der Importname selbst)."""
    top = (import_name or "").split(".")[0]
    if top in IMPORT_TO_PACKAGE:
        return IMPORT_TO_PACKAGE[top]
    lowered = {k.lower(): v for k, v in IMPORT_TO_PACKAGE.items()}
    return lowered.get(top.lower(), top.replace("_", "-"))


# ── Transitive Import-Namespaces ────────────────────────────────────────────────────────────
# Direkte Importe dieser Namespaces sind ohne eigenen Manifest-Eintrag unkritisch, sobald das
# Trägerpaket gelistet ist (`pip install fastapi` installiert immer starlette und pydantic).
TRANSITIVE_PROVIDES: dict[str, frozenset[str]] = {
    "fastapi": frozenset({"starlette", "pydantic", "pydantic_core", "anyio", "typing_extensions", "annotated_types"}),
    "pydantic": frozenset({"pydantic_core", "typing_extensions", "annotated_types"}),
    "pydantic-settings": frozenset({"pydantic", "pydantic_core", "dotenv"}),
    "uvicorn": frozenset({"click", "h11"}),
    "flask": frozenset({"jinja2", "werkzeug", "click", "itsdangerous", "markupsafe", "blinker"}),
    "requests": frozenset({"urllib3", "idna", "certifi", "charset_normalizer"}),
    "httpx": frozenset({"anyio", "httpcore", "certifi", "idna", "sniffio", "h11"}),
    "celery": frozenset({"kombu", "billiard", "vine", "click"}),
    "typer": frozenset({"click", "rich", "typing_extensions"}),
    "pytest": frozenset({"pluggy", "iniconfig", "_pytest"}),
    "python-jose": frozenset({"ecdsa", "rsa", "pyasn1"}),
    "sqlalchemy": frozenset({"typing_extensions"}),
    "alembic": frozenset({"sqlalchemy", "mako"}),
    "aiohttp": frozenset({"multidict", "yarl", "aiosignal", "frozenlist", "attr"}),
    "jinja2": frozenset({"markupsafe"}),
    "pandas": frozenset({"numpy", "dateutil", "pytz"}),
}


def provided_import_names(declared_packages: set[str]) -> set[str]:
    """Alle Import-Namespaces, die durch die deklarierten Pakete transitiv verfügbar sind
    (normalisiert: Kleinschreibung, `_` statt `-`)."""
    provided: set[str] = set()
    normalized = {normalize_package_name(p) for p in declared_packages}
    for carrier, names in TRANSITIVE_PROVIDES.items():
        if normalize_package_name(carrier) in normalized:
            provided.update(n.lower().replace("-", "_") for n in names)
    return provided


# ── Nur für Entwicklung/Tests ───────────────────────────────────────────────────────────────
DEV_ONLY_PACKAGES: frozenset[str] = frozenset({
    "pytest", "pytest-asyncio", "pytest-cov", "pytest-mock", "pytest-xdist", "pytest-httpx",
    "coverage", "locust", "faker", "factory-boy", "respx", "freezegun", "hypothesis",
    "ruff", "black", "mypy", "flake8", "isort", "pylint", "bandit", "pip-audit", "pre-commit",
})


def is_dev_only_package(package: str) -> bool:
    return normalize_package_name(package) in {normalize_package_name(p) for p in DEV_ONLY_PACKAGES}


_TEST_PATH_RE = re.compile(r"(^|/)(tests?|__tests__)(/|$)|(^|/)(test_[^/]+|[^/]+_test|conftest)\.py$")


def is_test_path(rel_path: str) -> bool:
    """True für Dateien in `tests/`-Ordnern bzw. `test_*.py`/`*_test.py`/`conftest.py`."""
    return bool(_TEST_PATH_RE.search((rel_path or "").replace("\\", "/")))


# ── Toxische Paket-Kollisionen ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ToxicDependencyRule:
    """Ein bekanntes Paket, das einen fremden Import-Namespace überschreibt."""

    legitimate_packages: tuple[str, ...]
    replacement: str | None
    reason: str


TOXIC_DEPENDENCY_RULES: dict[str, ToxicDependencyRule] = {
    "jwt": ToxicDependencyRule(
        legitimate_packages=("pyjwt",),
        replacement="PyJWT",
        reason=(
            "das veraltete PyPI-Paket `jwt` überschreibt den Namespace von PyJWT "
            "(`AttributeError: module 'jwt' has no attribute 'encode'`)"
        ),
    ),
    "crypto": ToxicDependencyRule(
        legitimate_packages=("cryptography", "pycryptodome", "pycryptodomex"),
        replacement=None,
        reason=(
            "das PyPI-Paket `crypto` ist ein unverwandtes CLI-Werkzeug und kollidiert mit dem "
            "`Crypto`-Namespace von pycryptodome – gemeint ist `cryptography` oder `pycryptodome`"
        ),
    ),
}


# ── Versteckte Laufzeit-Abhängigkeiten ──────────────────────────────────────────────────────
# (Signal-Regex im Quelltext, benötigtes Paket in Unterstrich-Normalform, Meldung)
HIDDEN_RUNTIME_DEPENDENCIES: tuple[tuple[re.Pattern, str, str], ...] = (
    (
        re.compile(r"\bcreate_async_engine\s*\("),
        "greenlet",
        (
            "`create_async_engine(...)` wird verwendet, aber SQLAlchemy braucht "
            "`greenlet` zur Laufzeit dafuer (lazy import, KEIN direkter Code-Import) - "
            "fehlt es, schlaegt jede DB-Operation mit \"the greenlet library is "
            "required\" fehl."
        ),
    ),
    (
        re.compile(r"\bOAuth2PasswordRequestForm\b|\bForm\s*\("),
        "python_multipart",
        (
            "`OAuth2PasswordRequestForm`/`Form(...)` wird verwendet, aber FastAPI "
            "braucht `python-multipart` zur Laufzeit zum Parsen von Formulardaten - "
            "fehlt es, schlaegt der Endpunkt erst beim ECHTEN Aufruf fehl (kein "
            "Fehler beim Start)."
        ),
    ),
)


# ── Katalog für Agenten & Dokumentation ─────────────────────────────────────────────────────
@dataclass(frozen=True)
class PitfallRule:
    """Eine bekannte Stolperfalle mit Erkennung und korrekter Lösung."""

    rule_id: str
    stacks: tuple[str, ...]
    symptom: str
    fix: str
    enforced_by: str
    # ALLE Begriffe müssen (Groß/Klein egal) in einer Lektion vorkommen, damit sie als durch diese
    # Regel abgedeckt gilt (core/team_memory.auto_link_lessons_to_rules) - bewusst explizit statt
    # Wortüberlappung, die "HTTP-Statuscodes" fälschlich einer Dependency-Regel zuordnete.
    match_keywords: tuple[str, ...] = ()


PITFALL_CATALOG: tuple[PitfallRule, ...] = (
    PitfallRule(
        "pyjwt-not-jwt", ("python", "fastapi"),
        "`jwt` in requirements.txt überschreibt PyJWT (`module 'jwt' has no attribute 'encode'`).",
        "Immer `PyJWT` eintragen, nie `jwt`.",
        "core/manifest_guard.py (sanitize_requirements), core/pre_flight_check.py",
        match_keywords=('jwt', 'pyjwt'),
    ),
    PitfallRule(
        "async-engine-greenlet", ("python", "sqlalchemy"),
        "`create_async_engine` ohne `greenlet` scheitert erst bei der ersten DB-Operation.",
        "`greenlet` und den passenden Async-Treiber (`aiosqlite`/`asyncpg`) eintragen.",
        "core/pre_flight_check.py (HIDDEN_RUNTIME_DEPENDENCIES)",
        match_keywords=('greenlet',),
    ),
    PitfallRule(
        "fastapi-form-multipart", ("python", "fastapi"),
        "`OAuth2PasswordRequestForm`/`Form(...)` ohne `python-multipart` scheitert beim Aufruf.",
        "`python-multipart` eintragen.",
        "core/pre_flight_check.py (HIDDEN_RUNTIME_DEPENDENCIES)",
        match_keywords=('multipart',),
    ),
    PitfallRule(
        "passlib-bcrypt-pin", ("python",),
        "passlib + bcrypt>=4.1 bricht den passlib-Selbsttest.",
        "`bcrypt<4.1` pinnen oder direkt `bcrypt` ohne passlib nutzen.",
        "core/pre_flight_check.py (_check_passlib_bcrypt_pin)",
        match_keywords=('passlib', 'bcrypt'),
    ),
    PitfallRule(
        "pytest-asyncio-plugin", ("python", "pytest"),
        "`async def test_…`/`@pytest.mark.asyncio` ohne `pytest-asyncio` schlägt fehl.",
        "`pytest-asyncio` in requirements-dev.txt und `asyncio_mode = auto` in pytest.ini.",
        "core/verifier/completeness.py, core/verifier/environment.py",
        match_keywords=('pytest-asyncio',),
    ),
    PitfallRule(
        "pytest-pythonpath", ("python", "pytest"),
        "`ModuleNotFoundError: No module named 'app'` in Tests.",
        "`pythonpath = .` in pytest.ini (Sektionen ohne führende Leerzeichen).",
        "core/project_scaffold.py (Vorlage), agents/tester_agent.py",
        match_keywords=('pythonpath',),
    ),
    PitfallRule(
        "single-declarative-base", ("python", "sqlalchemy"),
        "Mehrere `DeclarativeBase`/`declarative_base()` erzeugen getrennte Metadaten.",
        "Genau eine Basisklasse in `app/db/base.py`, alle Modelle importieren sie.",
        "core/verifier/completeness.py",
        match_keywords=('declarativebase',),
    ),
    PitfallRule(
        "package-init-files", ("python",),
        "Unterordner mit `.py`-Dateien ohne `__init__.py` brechen Importe/Testsammlung.",
        "Jeder Paketordner bekommt eine (ggf. leere) `__init__.py`.",
        "core/pre_flight_check.py (missing_init), core/project_scaffold.py",
        match_keywords=('__init__.py', 'unterordner'),
    ),
    PitfallRule(
        "router-prefix-duplication", ("python", "fastapi"),
        "`APIRouter(prefix=…)` plus `include_router(prefix=…)` verdoppelt den Pfad.",
        "Den Präfix nur an EINER Stelle setzen.",
        "core/contract_verifier.py",
        match_keywords=('prefix', 'include_router'),
    ),
    PitfallRule(
        "reexport-before-module", ("python",),
        "Re-Export in `__init__.py` vor Anlage des Zielmoduls erzeugt ImportError-Kaskaden.",
        "Erst das Modul schreiben, dann den Re-Export ergänzen.",
        "agents/base_agent.py (Übergabe-Prüfung)",
        match_keywords=('re-export', '__init__'),
    ),
    PitfallRule(
        "dev-deps-separated", ("python",),
        "Test-/Lastwerkzeuge (pytest, locust) in requirements.txt blähen das Produktionsimage auf.",
        "Test-/Werkzeugpakete in requirements-dev.txt eintragen.",
        "agents/orchestrator/verification.py (deterministische Dependency-Ergänzung)",
        match_keywords=('requirements-dev',),
    ),
    PitfallRule(
        "websocket-native-client", ("fastapi", "frontend"),
        "Socket.IO-Client gegen FastAPI-WebSocket: `'Connection' header is missing`.",
        "Im Browser das native `WebSocket`-API nutzen oder serverseitig python-socketio einsetzen.",
        "agents/orchestrator/verification.py (_classify_browser_failure_owner)",
        match_keywords=('websocket', 'connection'),
    ),
    PitfallRule(
        "code-via-write-file", ("all",),
        "Code nur im Antworttext statt per `write_file` wird nicht ausgeliefert.",
        "Jede Datei über `write_file`/`edit_file` schreiben.",
        "agents/base_agent.py (Hard Delivery Gate)",
        match_keywords=('write_file',),
    ),
)


def format_pitfalls_for_agents(stack_hints: str = "", limit: int = 8) -> str:
    """Kompakter Prompt-Abschnitt mit den für den Auftrag relevanten Stolperfallen."""
    hints = (stack_hints or "").lower()
    stack_keywords = {
        "fastapi": ("fastapi", "api", "backend", "rest"),
        "sqlalchemy": ("sqlalchemy", "datenbank", "database", "sql", "postgres", "sqlite"),
        "pytest": ("test", "pytest"),
        "frontend": ("dashboard", "frontend", "ui", "websocket", "html"),
        "python": ("python", "fastapi", "flask", "django", "api", "backend"),
    }
    active = {"all"} | {s for s, kws in stack_keywords.items() if any(k in hints for k in kws)}
    relevant = [r for r in PITFALL_CATALOG if active.intersection(r.stacks)]
    if not relevant:
        return ""
    # Fast jede Python-Regel trifft auf "python"/"all" zu und würde bei einem harten
    # Catalog-Reihenfolge-Cut die spezifischeren, für diesen Auftrag eigentlich
    # relevanten Regeln (z. B. "frontend"-Stolperfallen) aus dem `limit` verdrängen.
    # Deshalb zuerst die Regeln zeigen, die auf einen SPEZIFISCHEN aktiven Stack
    # (nicht nur "python"/"all") passen; stabile Sortierung erhält sonst die Reihenfolge.
    def specificity(rule: PitfallRule) -> int:
        return 0 if active.intersection(rule.stacks) - {"python", "all"} else 1

    relevant = sorted(relevant, key=specificity)
    lines = ["### ⚠️ Bekannte Stolperfallen (aus früheren Läufen gelernt)"]
    lines += [f"- {r.symptom} → {r.fix}" for r in relevant[:limit]]
    return "\n".join(lines)
