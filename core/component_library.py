"""
core/component_library.py – Cross-Projekt-Bibliothek verifizierter, wiederverwendbarer
Infrastruktur-Bausteine (Gesamtsystem-Analyse 2026-09-14, Punkt 3.2 "Wiederverwendung statt
Neuerfindung")

core/embedding_index.py/core/vector_store.py indizieren ausschließlich INNERHALB eines einzelnen
Projekts (workspace/<projekt>/.ai_team_rag/) - es gab bisher KEINE projektübergreifende
Bibliothek verifizierter, bereits getesteter Implementierungen wiederkehrender Infrastruktur-
Bausteine (CircuitBreaker, Rate-Limiter, JWT-Auth-Middleware, Repository-Basisklassen). Die
Konsequenz war konkret sichtbar: der `chronospulse`-Lauf lieferte einen 5-zeiligen
Kommentar-Stub statt eines echten `CircuitBreaker` (siehe `ki_team_schwachstellen_und_
fehleranalyse_chronospulse_20260913.md`, Schwachstelle 4) - exakt die Art Baustein, die in
einem reifen Team beim zweiten oder dritten Projekt nicht mehr neu geschrieben, sondern aus
einer geprüften internen Bibliothek gezogen würde.

Funktionsweise:
1. harvest_from_project() wird NUR nach einem ERFOLGREICH VERIFIZIERTEN Lauf aufgerufen
   (verification_ok=True - der Aufrufer in agents/orchestrator/__init__.py garantiert das,
   dieselbe Provenienz-Anforderung wie "aus echten, bestandenen Tests hervorgegangen").
   Durchsucht die generierten Quelldateien per Namens-Heuristik (_PATTERNS) nach bekannten
   Infrastruktur-Rollen und übernimmt jeden Treffer, der NICHT wie ein Stub aussieht
   (_is_stub() - dieselbe Sorte Fund, die genau NICHT in der Bibliothek landen soll, wie das
   chronospulse-Beispiel oben), mit Provenienz (Quellprojekt, Pfad, Zeitstempel) in
   memory/component_library/.
2. search() steht Agenten über ein neues, rein lesendes Werkzeug (core/agent_toolbox.py.
   _tool_search_component_library) zur Verfügung, mit einer Prompt-Regel (agents/team_
   directives.py.COMPONENT_LIBRARY_DIRECTIVE), zuerst dort nachzuschauen, bevor Standard-
   Infrastruktur komplett neu implementiert wird.

Bewusst NUR Vorschlag/Referenz, kein automatisches Einfügen: ein Agent liest einen Treffer über
das reguläre read_file-Werkzeug (Pfad kommt aus dem Suchergebnis) und entscheidet selbst, ob und
wie er ihn übernimmt/anpasst - dieselbe Zurückhaltung wie core/roadmap_advisor.py (Vorschlag,
keine automatische Umsetzung).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from config import MEMORY_DIR

LIBRARY_DIR = Path(MEMORY_DIR) / "component_library"
MANIFEST_FILE = LIBRARY_DIR / "manifest.json"

# Klassennamen-Heuristik je Kategorie - bewusst breit genug für Python/TS/JS-Konventionen
# (CamelCase-Klassennamen in allen drei Sprachen), aber auf die Bausteine beschränkt, die in den
# vorliegenden Analysen wiederholt als Stub/fehlerhaft auffielen (siehe Moduldocstring). Weitere
# Kategorien lassen sich hier einfach ergänzen, ohne harvest_from_project()/search() anzufassen.
# Folgeanalyse 2026-09-14, Befund 4: "(?:export\s+)?" allein erkannte NUR "export class X" -
# tatsächlich ausgeführter Test bestätigte, dass die real gängigen TypeScript-Konventionen
# "export default class X" (Standard bei genau einer Hauptklasse pro Datei) und
# "export abstract class X" (abstrakte Basisklassen) dabei NICHT erkannt wurden. Der Zusatz
# "(?:default\s+|abstract\s+)*" erlaubt beliebige Kombinationen dieser beiden Modifier
# zwischen "export" und "class" - deckt damit auch "export default abstract class" ab.
_EXPORT_PREFIX = r"(?:export\s+(?:default\s+|abstract\s+)*)?"
_PATTERNS: dict[str, re.Pattern] = {
    "circuit_breaker": re.compile(rf"^[ \t]*{_EXPORT_PREFIX}class\s+(\w*CircuitBreaker\w*)\b", re.MULTILINE),
    "rate_limiter": re.compile(
        rf"^[ \t]*{_EXPORT_PREFIX}class\s+(\w*(?:RateLimiter|TokenBucket|SlidingWindow)\w*)\b", re.MULTILINE,
    ),
    "retry_backoff": re.compile(
        rf"^[ \t]*{_EXPORT_PREFIX}class\s+(\w*(?:RetryPolicy|ExponentialBackoff|Backoff)\w*)\b", re.MULTILINE,
    ),
    "jwt_auth": re.compile(
        rf"^[ \t]*{_EXPORT_PREFIX}class\s+(\w*(?:JWTAuth|AuthMiddleware|TokenService)\w*)\b", re.MULTILINE,
    ),
    "repository_base": re.compile(rf"^[ \t]*{_EXPORT_PREFIX}class\s+(\w*Repository\w*)\b", re.MULTILINE),
}

_SOURCE_GLOBS = ("**/*.py", "**/*.ts", "**/*.js")
_SKIP_DIR_PARTS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build"}

# Ein Baustein mit weniger "echten" Codezeilen gilt als Stub - genau das Muster aus dem
# chronospulse-Fund (5 Zeilen Kommentar statt Implementierung), siehe Moduldocstring.
_MIN_MEANINGFUL_LINES = 8
_STUB_MARKERS = ("todo", "auszug aus", "nicht implementiert", "not implemented", "raise notimplementederror")

# Deckelung je Kategorie, damit die Bibliothek nicht unbegrenzt wächst und search() relevant
# bleibt (viele praktisch identische CircuitBreaker-Varianten helfen niemandem) - älteste
# Einträge werden zuerst entfernt (siehe _prune_manifest()).
MAX_LIBRARY_ENTRIES_PER_CATEGORY = 12


# Folgeanalyse 2026-09-14, Befund 3: core/backlog_store.py._save_raw() trägt einen
# dokumentierten, ECHT reproduzierten Datenverlust-Vorfall - ein gleichzeitiger Leser traf ein
# direktes write_text() mitten im Schreibvorgang, bekam kaputtes/abgeschnittenes JSON, und der
# nächste Schreibvorgang überschrieb dadurch den GESAMTEN vorherigen Stand. _save_manifest()
# nutzte bisher exakt dasselbe unsichere Muster (direktes write_text() auf MANIFEST_FILE) -
# reproduzierbar erreichbar, da interface/web_dashboard.py standardmäßig
# DASHBOARD_MAX_CONCURRENT_JOBS=2 parallele Läufe unterstützt und harvest_from_project() nach
# JEDEM erfolgreich verifizierten Lauf aufgerufen wird: zwei Projekte, die etwa gleichzeitig
# fertig werden, ernten dann potenziell gleichzeitig. Übernimmt deshalb dieselbe Lösung wie
# core/backlog_store.py: Schreiben in eine Temp-Datei im SELBEN Verzeichnis (garantiert
# dasselbe Dateisystem) + os.replace() (atomarer Rename auf POSIX UND Windows) - ein Leser
# sieht dadurch immer entweder den kompletten alten ODER den kompletten neuen Stand, nie etwas
# dazwischen. Der PermissionError-Retry deckt denselben Windows-spezifischen Fund ab wie dort
# (kurze Sharing-Violation, wenn ein anderer Thread die Zieldatei GENAU in diesem Moment offen
# hat - kein echter Dauerzustand).
def _load_manifest() -> list[dict]:
    if not MANIFEST_FILE.exists():
        return []
    max_attempts = 10
    for attempt in range(max_attempts):
        try:
            data = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []
        except PermissionError:
            if attempt == max_attempts - 1:
                return []
            time.sleep(0.05 * (attempt + 1))
        except OSError:
            return []
    return []


def _save_manifest(entries: list[dict]) -> None:
    try:
        LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    tmp_path = MANIFEST_FILE.with_suffix(f"{MANIFEST_FILE.suffix}.tmp-{os.getpid()}-{threading.get_ident()}")
    try:
        tmp_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return
    max_attempts = 10
    for attempt in range(max_attempts):
        try:
            os.replace(tmp_path, MANIFEST_FILE)
            return
        except PermissionError:
            if attempt == max_attempts - 1:
                return
            time.sleep(0.05 * (attempt + 1))
        except OSError:
            return


def _extract_block(text: str, start_idx: int) -> str:
    """Extrahiert den vollständigen Codeblock ab einer gefundenen Klassendefinition - bis zur
    nächsten Top-Level-Definition (Zeile ohne führende Einrückung, die mit class/def/export
    beginnt) oder Dateiende. Naiv (kein echter Parser je Sprache), aber für diese Heuristik
    ausreichend: eine Fehlklassifizierung kostet höchstens einen unsauber geschnittenen
    Bibliotheks-Eintrag, nie eine Änderung am generierten Projekt-Code selbst (rein additiv,
    liest nur)."""
    lines = text[start_idx:].splitlines()
    if not lines:
        return ""
    block = [lines[0]]
    for line in lines[1:]:
        if line and not line[0].isspace() and re.match(r"(class|def|export|async def)\b", line.strip()):
            break
        block.append(line)
    return "\n".join(block).rstrip()


_DECORATOR_LINE_RE = re.compile(r"^@\w")


def _leading_decorators(text: str, start_idx: int) -> str:
    """Folgeanalyse 2026-09-14, Befund 4: sammelt Decorator-/Annotations-Zeilen (Python
    `@dataclass`, TypeScript `@Injectable()`/`@Component(...)`) UNMITTELBAR vor einer
    Klassendefinition ein - _extract_block() beginnt erst BEI `match.start()` (der "class"-
    Zeile selbst) und ließ einen vorangehenden Decorator bisher aus dem geernteten Baustein
    herausfallen, obwohl er verhaltensrelevant sein kann (`@dataclass` generiert z.B.
    automatisch `__init__`/`__eq__` - ein Baustein ohne ihn wäre als Vorlage unvollständig).
    Scannt rückwärts über zusammenhängende Top-Level-Decorator-Zeilen (keine Einrückung, siehe
    _extract_block()-Konvention) und bricht bei der ersten Nicht-Decorator-Zeile ab (Leerzeile,
    Kommentar, Dateianfang) - mehrzeilige Decorator-AUFRUFE (z.B. `@Component({\n ...\n})`)
    werden dabei bewusst NICHT unterstützt (Heuristik, kein echter Parser, siehe
    _extract_block()-Docstring)."""
    collected: list[str] = []
    for line in reversed(text[:start_idx].splitlines()):
        if line[:1].isspace() or not _DECORATOR_LINE_RE.match(line.strip()):
            break
        collected.append(line)
    return "\n".join(reversed(collected))


def _is_stub(block: str) -> bool:
    """Erkennt genau die Sorte Fund, die NICHT in die Bibliothek soll (siehe Moduldocstring,
    chronospulse-Beispiel): zu wenige echte Codezeilen oder ein expliziter Platzhalter-Hinweis."""
    meaningful_lines = [
        ln for ln in block.splitlines()
        if ln.strip() and not ln.strip().startswith(("#", "//", "*", '"""', "'''"))
    ]
    if len(meaningful_lines) < _MIN_MEANINGFUL_LINES:
        return True
    lowered = block.lower()
    return any(marker in lowered for marker in _STUB_MARKERS)


def _prune_manifest(manifest: list[dict]) -> list[dict]:
    by_category: dict[str, list[dict]] = {}
    for entry in manifest:
        by_category.setdefault(entry.get("category", ""), []).append(entry)
    kept: list[dict] = []
    for entries in by_category.values():
        entries.sort(key=lambda e: e.get("added_at", ""))
        surplus = len(entries) - MAX_LIBRARY_ENTRIES_PER_CATEGORY
        if surplus > 0:
            for stale in entries[:surplus]:
                snippet_file = stale.get("snippet_file")
                if snippet_file:
                    try:
                        Path(snippet_file).unlink(missing_ok=True)
                    except OSError:
                        pass
            entries = entries[surplus:]
        kept.extend(entries)
    return kept


def harvest_from_project(project_dir: str | Path, project_slug: str) -> list[str]:
    """Durchsucht ein Projekt nach wiederkehrenden Infrastruktur-Bausteinen und übernimmt neue,
    nicht-triviale Treffer (mit Provenienz) in die Bibliothek. NUR für bereits erfolgreich
    verifizierte Projekte gedacht (siehe Moduldocstring) - dieses Modul erzwingt das selbst
    nicht (keine Abhängigkeit zum Orchestrator), der Aufrufer trägt die Verantwortung, dieselbe
    Aufteilung wie core/roadmap_advisor.py (auch dort entscheidet der Aufrufer, WANN read-only
    nachgedacht wird). Best-effort: ein Lesefehler an einer einzelnen Datei überspringt nur
    diese, bricht nie den ganzen Aufruf ab.

    Gibt die IDs der neu hinzugefügten Bibliotheks-Einträge zurück (leer, wenn nichts Neues
    gefunden wurde)."""
    project_dir = Path(project_dir)
    if not project_dir.exists():
        return []
    manifest = _load_manifest()
    known_ids = {e["id"] for e in manifest}
    added: list[str] = []

    for glob in _SOURCE_GLOBS:
        for path in project_dir.glob(glob):
            if _SKIP_DIR_PARTS.intersection(path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for category, pattern in _PATTERNS.items():
                for match in pattern.finditer(text):
                    class_name = match.group(1)
                    decorators = _leading_decorators(text, match.start())
                    block = _extract_block(text, match.start())
                    if decorators:
                        block = f"{decorators}\n{block}"
                    if _is_stub(block):
                        continue
                    content_hash = hashlib.sha256(block.encode("utf-8")).hexdigest()[:16]
                    entry_id = f"{category}-{class_name.lower()}-{content_hash[:8]}"
                    if entry_id in known_ids:
                        continue  # Bytegleicher Baustein bereits bekannt (evtl. aus einem anderen Projekt)
                    snippet_path = LIBRARY_DIR / category / f"{entry_id}{path.suffix}"
                    try:
                        snippet_path.parent.mkdir(parents=True, exist_ok=True)
                        snippet_path.write_text(block, encoding="utf-8")
                    except OSError:
                        continue
                    manifest.append({
                        "id": entry_id, "category": category, "class_name": class_name,
                        "source_project": project_slug,
                        "source_path": str(path.relative_to(project_dir)).replace("\\", "/"),
                        "language": path.suffix.lstrip("."),
                        "added_at": datetime.now(UTC).isoformat(),
                        "char_count": len(block), "content_hash": content_hash,
                        "preview": block[:300], "snippet_file": str(snippet_path),
                    })
                    known_ids.add(entry_id)
                    added.append(entry_id)

    if added:
        _save_manifest(_prune_manifest(manifest))
    return added


def search(query: str, category: str = "", limit: int = 5) -> list[dict]:
    """Einfache Wort-Überlappungs-Suche über Kategorie/Klassenname/Vorschau - die Bibliothek
    bleibt durch MAX_LIBRARY_ENTRIES_PER_CATEGORY klein genug, dass sich der schwerere
    Embedding-Index (core/embedding_index.py, dort projektintern) hierfür nicht lohnt."""
    manifest = _load_manifest()
    if category:
        manifest = [e for e in manifest if e.get("category") == category]
    terms = {t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2}
    if not terms:
        return manifest[:limit]
    scored = []
    for entry in manifest:
        haystack = f"{entry.get('category', '')} {entry.get('class_name', '')} {entry.get('preview', '')}".lower()
        score = sum(1 for t in terms if t in haystack)
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [e for _, e in scored[:limit]]


def get_snippet_content(entry_id: str, max_chars: int = 4000) -> str:
    """Liest den vollständigen Code eines Bibliotheks-Eintrags - Agenten rufen dies i.d.R. NICHT
    direkt auf, sondern nutzen den `source_path`/`snippet_file` aus einem search()-Treffer über
    das reguläre read_file-Werkzeug (siehe core/agent_toolbox.py._tool_search_component_library)."""
    manifest = _load_manifest()
    entry = next((e for e in manifest if e.get("id") == entry_id), None)
    if not entry:
        return ""
    try:
        return Path(entry["snippet_file"]).read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except (OSError, KeyError):
        return ""


@dataclass
class LibraryStats:
    total_entries: int
    by_category: dict[str, int]


def get_stats() -> LibraryStats:
    """Für Status-/Dashboard-Anzeigen (wie viele Bausteine sind bereits gesammelt)."""
    manifest = _load_manifest()
    by_category: dict[str, int] = {}
    for entry in manifest:
        cat = entry.get("category", "?")
        by_category[cat] = by_category.get(cat, 0) + 1
    return LibraryStats(total_entries=len(manifest), by_category=by_category)
