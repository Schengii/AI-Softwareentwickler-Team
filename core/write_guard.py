"""
core/write_guard.py – Schreibrechte pro Rolle, Schnittstellenschutz und Konflikterkennung

Drei reale Funde aus dem Lauf auditlog_sentinel (2026-09-10), alle ohne jede Warnung passiert:

1. **Rollengrenzen:** Der architect überschrieb `app/config.py`, der frontend-Agent
   `app/main.py`, der documentation-Agent `app/models.py`. Die Toolbox kannte nur „alles“ oder
   „nur lesen“ – kein CODEOWNERS-Prinzip wie in einem echten Team.
   → `check_write_scope()` mit config.AGENT_WRITE_SCOPES.

2. **Schnittstellen-Drift:** Die Neufassung von `app/config.py` entfernte `settings = Settings()`.
   `app/auth.py`, `app/database.py` und `app/security.py` importierten genau dieses Symbol –
   das Projekt war danach nicht mehr importierbar. Dasselbe Muster (`unresolved_governance_
   critical` wegen Import-/Signatur-Bruch) trat zuvor bei logipulse und vaultguard auf.
   → `check_contract_preserved()` lehnt eine Änderung ab, die ein von anderen Projektdateien
   importiertes Top-Level-Symbol entfernt.

3. **Parallele Überschreibungen:** Mehrere Agenten schrieben dieselbe Datei per `write_file`,
   der jeweils letzte gewann. → `file_versions` merkt sich, wer eine Datei zuletzt geschrieben
   hat; die Toolbox erlaubt ein Überschreiben nur, wenn der Agent den aktuellen Stand kennt.
"""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import os
import re
import threading
from pathlib import Path

_IGNORED_DIRS = frozenset({
    ".venv", "venv", ".ai_team_venv", "__pycache__", ".git", "node_modules", "dist", "build",
    ".ai_team_rag", ".pytest_cache", ".mypy_cache", ".ruff_cache",
})
MAX_IMPORTER_SCAN_FILES = 800


# ── 1. Schreibrechte pro Rolle ──────────────────────────────────────────────────────────────

def check_write_scope(agent_id: str, rel_path: str) -> str | None:
    """Fehlermeldung, falls `agent_id` `rel_path` laut config.AGENT_WRITE_SCOPES nicht schreiben
    darf – None bedeutet erlaubt. Rollen ohne Eintrag sind unbeschränkt (Entwicklungsrollen)."""
    from config import AGENT_WRITE_SCOPES, ENABLE_ROLE_WRITE_SCOPES

    if not ENABLE_ROLE_WRITE_SCOPES:
        return None
    scope = AGENT_WRITE_SCOPES.get(agent_id)
    if not scope:
        return None
    path = rel_path.replace("\\", "/").lstrip("/")
    lowered = path.lower()

    def _matches(patterns: tuple[str, ...]) -> bool:
        return any(fnmatch.fnmatch(lowered, pattern.lower()) for pattern in patterns)

    denied = _matches(scope.get("deny", ()))
    allowed = _matches(scope.get("allow", ()))
    if allowed and not denied:
        return None
    return (
        f"Schreibzugriff auf '{path}' für die Rolle `{agent_id}` abgelehnt – die Datei liegt außerhalb "
        f"deines Verantwortungsbereichs ({', '.join(scope.get('allow', ())[:8])}…). Ändere sie NICHT "
        "selbst, sondern beschreibe die nötige Änderung (Datei, Symbol, gewünschtes Verhalten) klar in "
        "deinem Bericht – der zuständige Fachagent setzt sie um."
    )


# ── 1b. Plausible Dateinamen ────────────────────────────────────────────────────────────────

# Analyse 2026-09-15: im Projekt-Root von nexus_resilience_gateway lag eine Datei `asyncio.Lock`
# mit Python-Code - ein Agent hatte einen Symbolnamen als Pfad übergeben. Solche Dateien werden
# nie importiert/ausgeführt, der Code fehlt dann dort, wo er gebraucht wird.
_ATTRIBUTE_LIKE_NAME = re.compile(r"^[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)*\.[A-Z][A-Za-z0-9_]*$")
_INVALID_PATH_CHARS = re.compile(r'[<>:"|?*]')


def check_path_plausible(rel_path: str) -> str | None:
    """Fehlermeldung für offensichtlich unsinnige Dateipfade – None bedeutet plausibel."""
    path = rel_path.replace("\\", "/").strip("/")
    if not path:
        return "Leerer Dateipfad – gib einen relativen Pfad wie `app/main.py` an."
    for part in path.split("/"):
        if part != part.strip() or part.endswith("."):
            return f"Ungültiger Pfadbestandteil '{part}' in '{path}' (Leerzeichen/Punkt am Rand)."
        if _INVALID_PATH_CHARS.search(part) or any(ord(ch) < 32 for ch in part):
            return f"Ungültige Zeichen im Dateipfad '{path}'."
    name = path.rsplit("/", 1)[-1]
    if _ATTRIBUTE_LIKE_NAME.match(name):
        return (
            f"'{name}' sieht wie ein Python-Symbol (Modul.Klasse) aus, nicht wie ein Dateiname. "
            "Schreibe den Code in eine echte Moduldatei, z. B. `app/core/metrics.py`."
        )
    return None


# ── 2. Schnittstellenschutz ─────────────────────────────────────────────────────────────────

class _StarImport(Exception):
    """`from x import *` – der Symbolumfang ist statisch nicht bestimmbar."""


def _target_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for element in target.elts:
            names |= _target_names(element)
        return names
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    return set()


def _collect_symbols(body: list[ast.stmt], names: set[str]) -> None:
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names |= _target_names(target)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            names |= _target_names(node.target)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    raise _StarImport
                names.add(alias.asname or alias.name)
        elif isinstance(node, ast.If):
            _collect_symbols(node.body, names)
            _collect_symbols(node.orelse, names)
        elif isinstance(node, (ast.Try, ast.TryStar)):
            _collect_symbols(node.body, names)
            for handler in node.handlers:
                _collect_symbols(handler.body, names)
            _collect_symbols(node.orelse, names)
            _collect_symbols(node.finalbody, names)
        elif isinstance(node, ast.With):
            _collect_symbols(node.body, names)


def top_level_symbols(source: str) -> set[str] | None:
    """Alle auf Modulebene definierten/importierten Namen, oder None (Syntaxfehler, Stern-Import)."""
    try:
        tree = ast.parse(source or "")
        names: set[str] = set()
        _collect_symbols(tree.body, names)
    except (SyntaxError, ValueError, _StarImport):
        return None
    return names


def _module_names_for(rel_path: str) -> set[str]:
    """Importpfade, unter denen eine Projektdatei erreichbar ist (inkl. `src/`-Layout)."""
    stem = rel_path[:-3] if rel_path.endswith(".py") else rel_path
    if stem.endswith("/__init__"):
        stem = stem[: -len("/__init__")]
    dotted = stem.replace("/", ".")
    names = {dotted}
    if dotted.startswith("src."):
        names.add(dotted[len("src."):])
    return names


def _resolve_import_module(importer_rel: str, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    package_parts = importer_rel.split("/")[:-1]
    up = node.level - 1
    if up > len(package_parts):
        return None
    base = package_parts[: len(package_parts) - up]
    return ".".join(base + ([node.module] if node.module else []))


def _iter_project_python_files(project_dir: Path):
    count = 0
    for dirpath, dirnames, filenames in os.walk(project_dir):
        dirnames[:] = [d for d in dirnames if d not in _IGNORED_DIRS]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            count += 1
            if count > MAX_IMPORTER_SCAN_FILES:
                return
            yield Path(dirpath) / filename


def find_importers_of(project_dir: Path, rel_path: str, symbols: set[str]) -> list[tuple[str, str]]:
    """(importierende Datei, Symbol) für jedes `from <modul> import <symbol>` auf `rel_path`."""
    targets = _module_names_for(rel_path)
    hits: list[tuple[str, str]] = []
    for path in _iter_project_python_files(project_dir):
        importer_rel = path.relative_to(project_dir).as_posix()
        if importer_rel == rel_path:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except (SyntaxError, ValueError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and _resolve_import_module(importer_rel, node) in targets:
                hits.extend((importer_rel, alias.name) for alias in node.names if alias.name in symbols)
    return sorted(set(hits))


def check_contract_preserved(project_dir: Path, rel_path: str, old_source: str, new_source: str) -> str | None:
    """Fehlermeldung, falls die Änderung ein Symbol entfernt, das andere Projektdateien importieren."""
    if not rel_path.endswith(".py"):
        return None
    old_symbols = top_level_symbols(old_source)
    new_symbols = top_level_symbols(new_source)
    if old_symbols is None or new_symbols is None:
        return None
    removed = old_symbols - new_symbols
    if not removed:
        return None
    hits = find_importers_of(project_dir, rel_path, removed)
    if not hits:
        return None
    listing = "; ".join(f"`{importer}` importiert `{symbol}`" for importer, symbol in hits[:8])
    more = f" … und {len(hits) - 8} weitere" if len(hits) > 8 else ""
    return (
        f"Änderung an '{rel_path}' abgelehnt (Schnittstellenschutz): sie entfernt Symbol(e), die andere "
        f"Projektdateien noch importieren – {listing}{more}. Das würde beim Start einen ImportError "
        "auslösen. Behalte das Symbol (ggf. als Alias/Re-Export) ODER passe ZUERST alle importierenden "
        "Dateien an und entferne es erst danach."
    )


# ── 3. Konflikterkennung paralleler Schreibzugriffe ─────────────────────────────────────────

def content_digest(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="surrogatepass")).hexdigest()


class FileVersionRegistry:
    """Prozessweit: welcher Agent hat eine Datei zuletzt über ein Werkzeug geschrieben?"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_writer: dict[str, str] = {}

    @staticmethod
    def _key(path: Path) -> str:
        return os.path.normcase(str(path))

    def record_write(self, path: Path, agent_id: str) -> None:
        with self._lock:
            self._last_writer[self._key(path)] = agent_id

    def last_writer(self, path: Path) -> str | None:
        with self._lock:
            return self._last_writer.get(self._key(path))

    def clear(self) -> None:
        with self._lock:
            self._last_writer.clear()


file_versions = FileVersionRegistry()
