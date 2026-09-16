"""
core/agent_toolbox.py – Echte, projektgebundene Werkzeuge für den agentischen Loop

Jede Aufgabe mit gesetztem AgentTask.project_dir bekommt in agents/base_agent.py
eine eigene AgentToolbox-Instanz für ihren Function-Calling-Loop:

- Code lesen (read_file, list_files, search_code)
- Änderungen im Projektverzeichnis speichern (write_file, edit_file, patch_file)
- Abhängigkeiten installieren und Tests ausführen (run_command, run_tests)

Alle Datei-Operationen sind strikt auf project_dir beschränkt (kein Directory
Traversal), und run_command ist auf eine Sicherheits-Whitelist begrenzt.
"""

import ast
import fnmatch
import logging
import os
import shlex
import sys
import time
from pathlib import Path
from typing import Any

from core.code_sandbox import CodeSandbox
from core.dependency_manifest import add_requirement, merge_preserving_requirements
from core.docker_sandbox import DockerSandbox
from core.failure_triage import is_local_module, is_test_file, module_to_file, read_module_interface
from core.write_guard import (
    check_contract_preserved,
    check_path_plausible,
    check_write_scope,
    content_digest,
    file_versions,
)

# Befehle, die Projektcode ausführen und deshalb bei aktiver Docker-Sandbox im Container laufen.
# ruff/mypy/flake8/black analysieren nur statisch und bleiben lokal.
_SANDBOXED_COMMAND_KINDS = {
    "pip": "python", "pip3": "python", "python": "python", "python3": "python", "pytest": "python",
    "npm": "node", "npx": "node", "node": "node",
}
SANDBOX_COMMAND_TIMEOUT_SECONDS = 300.0


def split_command_line(command: str, *, windows: bool | None = None) -> list[str]:
    """Zerlegt eine Agenten-Befehlszeile in Argumente, ohne Windows-Pfade zu zerstören.

    `shlex.split()` behandelt im POSIX-Modus `\\` als Escape-Zeichen, wodurch Windows-Pfade
    wie `tests\\test_auth.py` zu `teststest_auth.py` verstümmelt werden. Auf Windows deshalb
    `posix=False` und nur umschließende Anführungszeichen entfernen.
    """
    if windows is None:
        windows = os.name == "nt"
    if not windows:
        return shlex.split(command)
    parts = shlex.split(command, posix=False)
    return [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts]

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "read_file",
        "description": (
            "Liest den vollständigen Inhalt einer Datei im Projektverzeichnis. Nutze dies IMMER, "
            "bevor du eine bestehende Datei änderst. Wurde dieselbe Datei in dieser Sitzung bereits "
            "unverändert gelesen, liefert ein erneuter voller read_file-Aufruf nur einen kompakten "
            "Cache-Hinweis statt des kompletten Inhalts erneut - nutze dann line_start/line_end für "
            "einen gezielten Abschnitt oder force=true, um den vollen Inhalt trotzdem zu erhalten."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relativer Pfad zur Datei, z.B. 'app/main.py'"},
                "line_start": {"type": "integer", "description": "Optional: erste zu lesende Zeile (1-basiert) für einen gezielten Ausschnitt"},
                "line_end": {"type": "integer", "description": "Optional: letzte zu lesende Zeile (1-basiert, inklusive) für einen gezielten Ausschnitt"},
                "force": {"type": "boolean", "description": "Optional: true erzwingt den vollen Inhalt, auch wenn dieselbe Datei bereits unverändert gelesen wurde"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_files",
        "description": "Listet alle Dateien im Projektverzeichnis auf (optional gefiltert nach Unterordner). Nutze dies, um dir einen Überblick über bestehenden Code zu verschaffen.",
        "parameters": {
            "type": "object",
            "properties": {"subdir": {"type": "string", "description": "Optionaler Unterordner, leer = gesamtes Projekt"}},
            "required": [],
        },
    },
    {
        "name": "write_file",
        "description": "Erstellt eine neue Datei oder überschreibt eine bestehende Datei VOLLSTÄNDIG mit neuem Inhalt. Nutze dies für neue Dateien; für punktuelle Änderungen an bestehenden Dateien nutze stattdessen edit_file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relativer Zielpfad, z.B. 'app/main.py'"},
                "content": {"type": "string", "description": "Vollständiger neuer Dateiinhalt"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Ersetzt einen exakten, eindeutigen Textabschnitt in einer bestehenden Datei durch neuen Text (präziser Patch statt vollständiger Neuerstellung). 'old_text' muss exakt und GENAU EINMAL in der Datei vorkommen – lies die Datei vorher mit read_file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relativer Pfad zur bestehenden Datei"},
                "old_text": {"type": "string", "description": "Exakt zu ersetzender bestehender Textabschnitt"},
                "new_text": {"type": "string", "description": "Neuer Text als Ersatz für old_text"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    {
        "name": "patch_file",
        "description": "Wendet einen Unified-Diff (@@ ... @@) oder SEARCH/REPLACE-Patch chirurgisch auf eine bestehende Datei an. Ideal für Refactorings und Erweiterungen (spart bis zu 70% Tokens).",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relativer Pfad zur bestehenden Datei"},
                "patch": {"type": "string", "description": "Unified-Diff oder SEARCH/REPLACE Block"},
            },
            "required": ["path", "patch"],
        },
    },
    {
        "name": "add_dependency",
        "description": "Trägt ein Python-Paket idempotent in requirements.txt ein, OHNE die Datei zu überschreiben. Nutze dies statt write_file/edit_file auf requirements*.txt – parallel arbeitende Agenten überschreiben sich so nicht gegenseitig.",
        "parameters": {
            "type": "object",
            "properties": {
                "package": {"type": "string", "description": "Paket mit optionaler Version, z.B. 'alembic' oder 'sqlalchemy>=2.0'"},
                "manifest": {"type": "string", "description": "Relativer Pfad zum Manifest, Standard 'requirements.txt'"},
            },
            "required": ["package"],
        },
    },

    {
        "name": "search_code",
        "description": "Durchsucht den Code des aktuellen Projekts per BM25-Relevanz nach einem Suchbegriff (Funktions-/Klassennamen, Konzepte). Hilfreich, um relevante Stellen zu finden, ohne jede Datei einzeln zu lesen.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Suchbegriff, z.B. 'JWT Authentifizierung' oder 'UserRepository'"},
                "top_k": {"type": "integer", "description": "Maximale Trefferanzahl (Standard 5)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_component_library",
        "description": (
            "Durchsucht die PROJEKTÜBERGREIFENDE Bibliothek bereits verifizierter, "
            "wiederverwendbarer Infrastruktur-Bausteine (Circuit Breaker, Rate-Limiter, "
            "Retry/Backoff, JWT-Auth-Middleware, Repository-Basisklassen) aus FRÜHEREN, "
            "erfolgreich getesteten Projekten. Nutze dies VOR der Implementierung von "
            "Standard-Infrastruktur, um sie nicht fehleranfällig neu zu erfinden - ein Treffer "
            "liefert den vollständigen Code direkt mit, den du als Vorlage (an dieses Projekt "
            "angepasst) übernehmen kannst."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Suchbegriff, z.B. 'circuit breaker' oder 'JWT auth middleware'"},
                "category": {
                    "type": "string",
                    "description": "Optional: 'circuit_breaker'|'rate_limiter'|'retry_backoff'|'jwt_auth'|'repository_base' zur Eingrenzung",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "run_command",
        "description": (
            "Führt ein Terminal-Kommando im Projektverzeichnis aus (Timeout 60s). Nur eine begrenzte, sichere "
            "Auswahl ist erlaubt: pip install, pytest, python -m unittest, npm/npx/node, ruff, mypy, flake8, black --check."
        ),
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "Vollständiger Befehl, z.B. 'pip install -r requirements.txt' oder 'pytest -q'"}},
            "required": ["command"],
        },
    },
    {
        "name": "run_tests",
        "description": "Führt die echte Testsuite des Projekts aus (pytest falls installiert, sonst unittest discover) und gibt das tatsächliche Ergebnis (exit_code, stdout, stderr) zurück. Nutze dies, um deine Änderungen zu verifizieren, bevor du die Aufgabe als abgeschlossen meldest.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "record_architecture_decision",
        "description": (
            "Dokumentiert EINE getroffene Architektur-Entscheidung mit echtem Trade-off "
            "(z.B. 'REST statt GraphQL', 'PostgreSQL statt MongoDB', 'Monolith statt "
            "Microservices') als nummeriertes Architecture Decision Record (ADR) unter "
            "docs/adr/ im Projekt. Nutze dies bei jeder Entscheidung, bei der es plausible "
            "Alternativen gab und du dich bewusst für eine entschieden hast – NICHT für "
            "Routine-Implementierungsdetails ohne echte Alternative. Künftige Läufe an "
            "diesem Projekt sehen bereits getroffene Entscheidungen automatisch und "
            "widersprechen ihnen dadurch nicht unbemerkt."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Kurzer Titel der Entscheidung, z.B. 'PostgreSQL statt MongoDB für Nutzerdaten'"},
                "context": {"type": "string", "description": "Welches Problem/welche Anforderung führte zu dieser Entscheidung? Welche Optionen standen zur Wahl?"},
                "decision": {"type": "string", "description": "Wofür wurde sich entschieden und warum (die eigentliche Begründung)?"},
                "consequences": {"type": "string", "description": "Was folgt daraus - Vor-/Nachteile, künftige Einschränkungen, worauf spätere Änderungen achten müssen"},
            },
            "required": ["title", "context", "decision", "consequences"],
        },
    },
    {
        "name": "ask_human_for_clarification",
        "description": (
            "Meldet, dass ein echter, für die Aufgabe ENTSCHEIDENDER Punkt unklar ist, den nur ein Mensch "
            "sinnvoll beantworten kann (z.B. eine Geschäftsregel, die im Auftrag fehlt, oder ein Widerspruch "
            "zwischen Anforderung und bestehendem Code). NICHT für Dinge, die du selbst sinnvoll entscheiden "
            "kannst (übliche technische Defaults, Namenskonventionen) - dafür entscheide selbst und dokumentiere "
            "es ggf. über record_architecture_decision. Nutze dies SELTEN, nur bei echter Blockade. Nach dem "
            "Aufruf beendest du deine Antwort trotzdem mit einer ehrlichen Zusammenfassung: was du bereits "
            "erledigt hast und was durch diese Rückfrage offen bleibt - kein stilles Abbrechen."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Die konkrete Frage an den Menschen, präzise genug, um sie ohne Rückfrage beantworten zu können"},
                "context": {"type": "string", "description": "Warum diese Frage die Aufgabe blockiert und was du bereits versucht/angenommen hast"},
            },
            "required": ["question"],
        },
    },
    {
        "name": "ask_teammate",
        "description": (
            "Stellt einem Teamkollegen (anderer Agent) eine konkrete fachliche Frage und liefert seine Antwort "
            "direkt zurück - z.B. frontend an backend: 'Wie heißt die WebSocket-Route und welches JSON-Format "
            "sendet sie?', tester an database: 'Welche Pflichtfelder hat das Modell Webhook?'. Nutze es, BEVOR "
            "du eine Schnittstelle rätst, die ein anderer liefert. Kurz und präzise fragen; pro Aufgabe nur "
            "wenige Fragen möglich. Rollen u.a.: architect, backend, frontend, database, api_integration, "
            "devops, tester, security, ui_ux."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Rolle des Kollegen, z.B. 'backend'"},
                "question": {"type": "string", "description": "Konkrete Frage mit Bezug (Datei, Route, Symbol)"},
            },
            "required": ["agent_id", "question"],
        },
    },
    {
        "name": "find_symbol_definition",
        "description": "Findet die exakte AST-Definition (Klasse, Funktion, Methode) eines Code-Symbols im gesamten Projektverzeichnis.",
        "parameters": {
            "type": "object",
            "properties": {"symbol_name": {"type": "string", "description": "Name der gesuchten Klasse/Funktion/Methode, z.B. 'User' oder 'get_user'"}},
            "required": ["symbol_name"],
        },
    },
    {
        "name": "find_symbol_references",
        "description": "Findet alle Aufrufe, Imports, Verwendungen und Ableitungen eines Symbols über alle Dateien des Projekts hinweg.",
        "parameters": {
            "type": "object",
            "properties": {"symbol_name": {"type": "string", "description": "Name des Symbols"}},
            "required": ["symbol_name"],
        },
    },
    {
        "name": "analyze_code_impact",
        "description": "Führt eine Auswirkungsanalyse durch: Zeigt welche Dateien, Aufrufer und Module von einer Änderung an 'symbol_name' betroffen sind.",
        "parameters": {
            "type": "object",
            "properties": {"symbol_name": {"type": "string", "description": "Name des zu modifizierenden Symbols"}},
            "required": ["symbol_name"],
        },
    },
]

READ_ONLY_TOOL_NAMES = {
    "read_file", "list_files", "search_code",
    "find_symbol_definition", "find_symbol_references", "analyze_code_impact",
    # Reine Aufzeichnung ohne Dateisystem-Zugriff - auch ein Nur-Lese-Agent muss auf eine
    # echte Blockade hinweisen können.
    "ask_human_for_clarification",
    # Liest ausschließlich memory/component_library/, also außerhalb von project_dir.
    "search_component_library",
}


class ToolExecutionError(Exception):
    """Kontrollierter Fehler bei der Werkzeug-Ausführung (wird als {'error': ...} zurückgegeben, kein Crash)."""


class AgentToolbox:
    """
    An ein Projektverzeichnis und eine Agenten-ID gebundene Werkzeugsammlung
    für den agentischen Werkzeug-Loop in agents/base_agent.py.
    """

    ALLOWED_COMMAND_PREFIXES = (
        "pip ", "pip3 ", "pip freeze",
        "pytest", "python -m pytest", "python -m unittest", "python3 -m pytest", "python3 -m unittest",
        "npm ", "npx ", "node ",
        "ruff", "mypy", "flake8", "black --check",
    )
    # Werkzeug-Ergebnisse werden bei jeder weiteren Loop-Iteration erneut mitgesendet (kein
    # serverseitiger State bei den LLM-APIs) - der Wert multipliziert sich also mit der Zahl
    # der Iterationen. 8.000 Zeichen (~2.000 Tokens) reichen für die meisten Quelldateien.
    MAX_TOOL_RESULT_CHARS = 8_000
    MAX_LISTED_FILES = 300
    # Fenster, in dem ein erneuter voller read_file-Aufruf auf unveränderten Inhalt als
    # Wiederholung gilt: groß genug für einen Fix-Loop, aber kein Sitzungs-Cache.
    READ_CACHE_REPEAT_WINDOW_SECONDS = 300.0

    # project_dir kann (z.B. bei /audit-projekt) auch auf das Framework-Root mit echtem .env
    # zeigen. Die Sperre gilt deshalb immer, nicht nur im Nur-Lese-Modus, und blockiert Lesen
    # wie Schreiben gleichermaßen.
    SENSITIVE_NAME_PATTERNS = (
        ".env", ".env.*", "*.pem", "*.key", "id_rsa*", "id_ed25519*", "*credentials*", "*secret*",
    )

    @classmethod
    def _is_sensitive_name(cls, filename: str) -> bool:
        if filename == ".env.example":  # enthaelt bewusst keine echten Werte
            return False
        return any(fnmatch.fnmatch(filename.lower(), pat) for pat in cls.SENSITIVE_NAME_PATTERNS)

    def __init__(self, project_dir: str | Path, agent_id: str, read_only: bool = False):
        self.project_dir = Path(project_dir).resolve()
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.agent_id = agent_id
        self.read_only = read_only
        self.files_written: set[str] = set()
        self.call_count = 0
        # Von agents/base_agent.py gepflegt: eingesparte Zeichen durch Kontext-Verdichtung.
        self.context_chars_compacted = 0
        self.watchdog_events: list[str] = []
        self.call_log: list[dict[str, Any]] = []
        # agents/base_agent.py liest das nach dem Loop-Ende in
        # AgentResult.clarification_questions zurück (wie files_written oben).
        self.clarification_requests: list[str] = []
        # Normalisierter absoluter Pfad -> Inhalts-Hash des zuletzt von DIESEM Agenten gesehenen
        # Stands (gelesen oder selbst geschrieben), Grundlage für _reject_if_stale().
        self._seen_digests: dict[str, str] = {}
        # Normalisierter absoluter Pfad -> (Inhalts-Hash, monotone Zeit) des zuletzt VOLLSTÄNDIG
        # gelesenen Stands; Grundlage für den Cache-Hinweis in _tool_read_file(), damit derselbe
        # unveränderte Dateiinhalt nicht mehrfach den Loop-Kontext aufbläht. Der Inhalts-Hash
        # (nicht der Pfad) entscheidet über "unverändert" - ein write_file/edit_file invalidiert
        # den Eintrag dadurch automatisch.
        self._read_history: dict[str, tuple[str, float]] = {}

    async def list_files_snapshot(self, subdir: str = "") -> list[str]:
        """Wie `list_files`, aber ohne call_count/call_log zu erhöhen - dieser Blick auf den
        Dateibaum kommt vom Harness, nicht vom Agenten, und darf die Kennzahlen nicht verzerren."""
        result = await self._tool_list_files(subdir=subdir)
        return result.get("files") or []

    def tool_specs(self) -> list[dict[str, Any]]:
        if self.read_only:
            return [t for t in TOOL_SPECS if t["name"] in READ_ONLY_TOOL_NAMES or t["name"] == "run_tests"]
        from config import ENABLE_ASK_TEAMMATE
        if not ENABLE_ASK_TEAMMATE:
            return [t for t in TOOL_SPECS if t["name"] != "ask_teammate"]
        return TOOL_SPECS

    def _normalize_relative_path(self, clean: str) -> str:
        """Entfernt redundante Präfixe wie 'workspace/<projekt>/' oder '<projekt>/', die Agenten
        versehentlich voranstellen - sonst landen Dateien doppelt verschachtelt."""
        proj_name = self.project_dir.name
        if clean.startswith(f"workspace/{proj_name}/"):
            return clean[len(f"workspace/{proj_name}/"):]
        if clean.startswith(f"{proj_name}/"):
            return clean[len(f"{proj_name}/"):]
        if clean.startswith("workspace/"):
            parts = clean.split("/")
            if len(parts) > 1:
                norm_part = parts[1].lower().replace("-", "_")
                norm_proj = proj_name.lower().replace("-", "_")
                if norm_part in norm_proj or norm_proj in norm_part:
                    return "/".join(parts[2:]) if len(parts) > 2 else ""
                if parts[1] in ("app", "src", "tests", "docs", "static", "public", "api", "routers", "core", "models"):
                    return "/".join(parts[1:])
        return clean

    def _resolve(self, rel_path: str) -> Path:
        if not rel_path:
            raise ToolExecutionError("Es wurde kein Pfad angegeben.")
        clean = rel_path.replace("\\", "/").lstrip("/")
        clean = self._normalize_relative_path(clean)
        target = (self.project_dir / clean).resolve()
        if target != self.project_dir and self.project_dir not in target.parents:
            raise ToolExecutionError(f"Pfad '{rel_path}' liegt außerhalb des Projektverzeichnisses – abgelehnt.")
        if self._is_sensitive_name(target.name):
            raise ToolExecutionError(f"'{rel_path}' enthält vermutlich Zugangsdaten/Secrets und ist für Agenten-Werkzeuge gesperrt.")
        return target

    async def dispatch(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Führt einen Werkzeug-Aufruf aus und gibt IMMER ein serialisierbares dict zurück (nie eine Exception)."""
        self.call_count += 1
        self.call_log.append({"tool": name, "arguments": arguments})

        if self.read_only and name not in READ_ONLY_TOOL_NAMES and name != "run_tests":
            return {"error": f"Werkzeug '{name}' ist in diesem Kontext (Nur-Lese-Modus) nicht verfügbar."}

        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return {"error": f"Unbekanntes Werkzeug: '{name}'."}

        try:
            result = await handler(**(arguments or {}))
        except ToolExecutionError as e:
            return {"error": str(e)}
        except TypeError as e:
            return {"error": f"Ungültige Argumente für '{name}': {e}"}
        except Exception as e:
            return {"error": f"Unerwarteter Fehler bei Ausführung von '{name}': {e}"}

        return self._truncate(result)

    def _truncate(self, result: dict[str, Any]) -> dict[str, Any]:
        for key in ("content", "stdout", "stderr"):
            if key in result and isinstance(result[key], str) and len(result[key]) > self.MAX_TOOL_RESULT_CHARS:
                result[key] = result[key][: self.MAX_TOOL_RESULT_CHARS] + f"\n... [gekürzt, {len(result[key])} Zeichen gesamt] ..."
        return result

    # ── Datei-Werkzeuge ──────────────────────────────────────────────

    async def _tool_read_file(
        self, path: str, line_start: int | None = None, line_end: int | None = None, force: bool = False,
    ) -> dict:
        target = self._resolve(path)
        if not target.exists():
            return {"error": f"Datei '{path}' existiert nicht. Nutze list_files, um vorhandene Dateien zu sehen."}
        if not target.is_file():
            return {"error": f"'{path}' ist keine Datei (evtl. ein Verzeichnis)."}
        try:
            content = target.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            return {"error": f"Konnte '{path}' nicht lesen: {e}"}
        self._remember_content(target, content)

        targeted = line_start is not None or line_end is not None
        if not targeted and not force:
            cache_hit = self._check_read_cache(target, content)
            if cache_hit is not None:
                return cache_hit
        self._read_history[self._digest_key(target)] = (content_digest(content), time.monotonic())

        if targeted:
            lines = content.splitlines()
            start_idx = max((line_start or 1) - 1, 0)
            end_idx = line_end if line_end is not None else len(lines)
            snippet = "\n".join(lines[start_idx:end_idx])
            return {
                "path": path,
                "content": snippet,
                "line_start": line_start or 1,
                "line_end": line_end if line_end is not None else len(lines),
            }
        return {"path": path, "content": content}

    def _check_read_cache(self, target: Path, content: str) -> dict | None:
        """Gibt einen kompakten Cache-Hinweis zurück, wenn DIESELBE Datei mit demselben Inhalt
        bereits vor wenigen Iterationen (READ_CACHE_REPEAT_WINDOW_SECONDS) vollständig gelesen
        wurde - sonst None (normaler Lesevorgang). Siehe _read_history in __init__."""
        cached = self._read_history.get(self._digest_key(target))
        if cached is None:
            return None
        cached_digest, cached_at = cached
        if cached_digest != content_digest(content):
            return None  # Datei wurde seitdem geändert (write_file/edit_file) - kein Cache-Treffer
        if (time.monotonic() - cached_at) >= self.READ_CACHE_REPEAT_WINDOW_SECONDS:
            return None
        return {
            "path": self._relative(target),
            "cached": True,
            "notice": (
                "Dateiinhalt wurde in diesem Aufruf bereits unverändert übergeben. Nutze die "
                "vorherige Ausgabe oder spezifiziere line_start/line_end für gezielte Abschnitte."
            ),
        }

    async def _tool_list_files(self, subdir: str = "") -> dict:
        base = self._resolve(subdir) if subdir else self.project_dir
        if not base.exists():
            return {"files": [], "note": f"Verzeichnis '{subdir}' existiert noch nicht."}
        ignored_parts = {".venv", "venv", ".ai_team_venv", "__pycache__", ".git", "node_modules", "dist", "build"}
        files = sorted(
            str(p.relative_to(self.project_dir)).replace("\\", "/")
            for p in base.rglob("*")
            if p.is_file() and not any(part in ignored_parts for part in p.parts) and not self._is_sensitive_name(p.name)
        )
        if len(files) > self.MAX_LISTED_FILES:
            return {
                "files": files[: self.MAX_LISTED_FILES],
                "note": f"Gekürzt auf die ersten {self.MAX_LISTED_FILES} von {len(files)} Dateien – nutze subdir, um gezielter zu filtern.",
            }
        return {"files": files}

    @staticmethod
    def _reject_if_invalid_python(path: str, content: str) -> str | None:
        """Gibt eine Fehlermeldung zurück (statt None), wenn `path` auf .py endet und `content`
        kein gültiges Python ist – None bedeutet "in Ordnung, schreiben erlaubt".

        Fängt insbesondere doppelt serialisierten Modell-Output ab (alle Zeilenumbrüche als
        literale `\\n`), der sonst unbemerkt auf der Platte landet und erst Minuten später
        über einen Testfehlschlag auffällt. Nutzt dieselbe ast.parse()-Validierung wie
        core/code_sandbox.py.
        """
        if not path.lower().endswith(".py"):
            return None
        result = CodeSandbox.validate_code(content or "", "py")
        if result.is_valid:
            return None
        return (
            f"Syntax-Fehler in '{path}' – Datei wurde NICHT gespeichert: {'; '.join(result.errors)}. "
            "Prüfe insbesondere, ob Zeilenumbrüche/Anführungszeichen versehentlich als literale "
            "Zeichen ('\\\\n', '\\\\\"') statt als echte Escape-Sequenzen im Inhalt gelandet sind."
        )

    def _local_module_exists(self, dotted: str) -> bool | None:
        """True/False für ein Projektmodul, None wenn der Import kein lokales Modul betrifft."""
        parts = [p for p in dotted.split(".") if p]
        if not parts:
            return None
        for root in (self.project_dir, self.project_dir / "src"):
            top = root / parts[0]
            if not (top.is_dir() or top.with_suffix(".py").is_file()):
                continue
            module = root.joinpath(*parts)
            return module.with_suffix(".py").is_file() or (module / "__init__.py").is_file() or module.is_dir()
        return None

    def _reject_if_premature_reexport(self, clean_rel: str, content: str) -> str | None:
        """Lehnt `__init__.py`-Re-Exporte aus noch nicht existierenden Projektmodulen ab.

        Ein Re-Export auf ein noch fehlendes Modul bricht JEDEN Import des Pakets und kostet
        mehrere Reparaturrunden.
        """
        if not clean_rel.endswith("__init__.py"):
            return None
        try:
            tree = ast.parse(content or "")
        except SyntaxError:
            return None
        from core.write_guard import _resolve_import_module
        missing: list[str] = []
        for node in tree.body:
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            dotted = _resolve_import_module(clean_rel, node)
            if dotted and self._local_module_exists(dotted) is False:
                missing.append(dotted)
        if not missing:
            return None
        return (
            f"'{clean_rel}' re-exportiert aus Modul(en), die noch nicht existieren: {', '.join(sorted(set(missing)))}. "
            "Ein Paket-`__init__.py` mit fehlendem Import bricht JEDEN Import des Pakets. Lege zuerst das "
            "Zielmodul an (oder frage den zuständigen Kollegen per ask_teammate) und ergänze den Re-Export danach."
        )

    def _check_test_import_phantoms(self, path: str, content: str) -> str | None:
        """Warnt (ohne zu blockieren), wenn eine Testdatei ein Symbol importiert, das das lokale
        Modul laut AST gar nicht exportiert - z.B. eine Methode, die als Modulfunktion importiert
        wird. Nutzt dieselbe Oberflächen-Analyse wie der Fix-Loop (core/failure_triage.py), aber
        proaktiv vor dem Speichern. Bewusst nur eine Warnung: False Positives (bedingte
        Re-Exports, dynamisch gesetzte Attribute) dürfen das Speichern nicht verhindern."""
        if not path.lower().endswith(".py") or not is_test_file(path):
            return None
        try:
            tree = ast.parse(content or "")
        except (SyntaxError, ValueError):
            return None  # eigenständige Syntaxprüfung übernimmt bereits _reject_if_invalid_python
        problems: list[str] = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ImportFrom) and node.module and node.level == 0):
                continue
            module = node.module
            if not is_local_module(module, self.project_dir):
                continue
            provider = module_to_file(module, self.project_dir, set())
            if provider is None:
                continue
            interface = read_module_interface(self.project_dir / provider)
            if interface is None:
                continue
            for alias in node.names:
                name = alias.name
                if name == "*" or name in interface.exports:
                    continue
                if name in interface.methods:
                    problems.append(
                        f"'{name}' ist in '{provider}' keine Modulfunktion, sondern eine Methode "
                        f"von '{interface.methods[name]}' - importiere die Klasse und rufe die Methode "
                        "auf einer Instanz auf."
                    )
                else:
                    known = ", ".join(sorted(n for n in interface.exports if not n.startswith("_"))[:8])
                    problems.append(f"'{name}' existiert nicht in '{provider}' (vorhanden: {known or 'nichts Öffentliches'})")
        if not problems:
            return None
        return "⚠️ Mögliches Phantomsymbol – prüfe mit read_file, ob der Import zur echten Schnittstelle passt: " + "; ".join(problems)

    # Endungen ohne eingebauten Parser, der literale `\n`-Ketten als Syntaxfehler erkennt
    # (.py deckt bereits _reject_if_invalid_python über ast.parse ab).
    _LITERAL_NEWLINE_CHECK_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".json", ".html", ".css")
    _MIN_LITERAL_NEWLINE_HITS = 3

    @classmethod
    def _reject_if_literal_newline_corruption(cls, path: str, content: str) -> str | None:
        """Gibt eine Fehlermeldung zurück, wenn `content` literale `\\n`-Zeichen statt echter
        Zeilenumbrüche enthält und die Endung keinen eigenen Parser hat, der das abfangen würde.

        Heuristik bewusst konservativ, damit normaler Code mit echten Escape-Sequenzen in
        String-Literalen (z.B. `console.log("a\\nb")`) nicht abgelehnt wird: nur eine Datei aus
        praktisch einer einzigen physischen Zeile MIT mehreren literalen `\\n` gilt als
        flachgeklopfter, doppelt serialisierter Output."""
        if not content or not path.lower().endswith(cls._LITERAL_NEWLINE_CHECK_EXTENSIONS):
            return None
        real_newlines = content.count("\n")
        literal_hits = content.count("\\n")
        if real_newlines > 1 or literal_hits < cls._MIN_LITERAL_NEWLINE_HITS:
            return None
        return (
            f"'{path}' wurde NICHT gespeichert: der Inhalt besteht praktisch aus einer einzigen "
            f"Zeile, enthält aber {literal_hits}x die literale Zeichenfolge '\\n' statt echter "
            "Zeilenumbrüche (typisches Muster einer doppelt serialisierten/kaputten Ausgabe). "
            "Prüfe den Inhalt und schreibe ihn mit echten Zeilenumbrüchen erneut."
        )

    @staticmethod
    def _reject_if_corrupted_manifest(path: str, content: str) -> str | None:
        """Gibt eine Fehlermeldung zurück, wenn `path` ein Dependency-Manifest (requirements.txt,
        package.json, ...) ist und `content` typische Merge-/Diff-Korruption zeigt (z.B. ein roh
        übernommener Diff-Hunk) – None bedeutet "in Ordnung, schreiben erlaubt"."""
        from core.manifest_guard import detect_corrupted_manifest

        return detect_corrupted_manifest(path, content)

    @staticmethod
    def _sanitize_toxic_dependencies(path: str, content: str, project_name: str = "") -> tuple[str, str | None]:
        """Entfernt toxische Paket-Kollisionen (z.B. `jwt` neben `pyjwt`, siehe
        core/manifest_guard.py) deterministisch VOR dem Schreiben, statt die Datei abzulehnen -
        ein Agent auf einem schwachen Modell würde sonst oft dieselbe Kollision erneut schreiben.
        Gibt den (ggf. bereinigten) Inhalt und einen Hinweis für den Agenten zurück."""
        from core.manifest_guard import describe_toxic_dependencies, sanitize_requirements

        sanitized, findings = sanitize_requirements(path, content or "", project_name=project_name or None)
        if not findings:
            return content, None
        return sanitized, describe_toxic_dependencies(path, findings) + " Automatisch bereinigt."

    # ── Schreibschutz (core/write_guard.py) ──────────────────────────

    def _relative(self, target: Path) -> str:
        return str(target.relative_to(self.project_dir)).replace("\\", "/")

    @staticmethod
    def _digest_key(target: Path) -> str:
        return os.path.normcase(str(target))

    def _remember_content(self, target: Path, content: str) -> None:
        self._seen_digests[self._digest_key(target)] = content_digest(content)

    def _remember_write(self, target: Path, clean_rel: str, content: str) -> str | None:
        """Merkt sich den Schreibvorgang und meldet zurück, falls die Datei einer anderen Rolle gehört."""
        self._remember_content(target, content)
        file_versions.record_write(target, self.agent_id)
        self.files_written.add(clean_rel)
        from config import ENABLE_TEAM_BOARD
        if not ENABLE_TEAM_BOARD:
            return None
        try:
            from core.team_board import claim_file
            owner = claim_file(self.project_dir, clean_rel, self.agent_id)
        except Exception as e:  # noqa: BLE001 - Board ist Kommunikationshilfe, kein Schreibblocker
            logging.getLogger(__name__).warning("Datei-Owner für %s nicht registrierbar: %r", clean_rel, e)
            return None
        if owner:
            return (
                f"Hinweis: '{clean_rel}' gehört `{owner}`. Deine Änderung ist auf dem Team-Board vermerkt - "
                f"begründe sie in deiner Übergabe oder kläre sie per ask_teammate mit `{owner}`."
            )
        return None

    def _reject_if_stale(self, target: Path, clean_rel: str, current: str) -> str | None:
        """Ein vollständiges Überschreiben ist nur erlaubt, wenn dieser Agent den AKTUELLEN Stand
        der Datei kennt (gelesen oder selbst geschrieben) – sonst gewinnt bei parallel
        arbeitenden Agenten still der letzte Schreiber."""
        key = self._digest_key(target)
        seen = self._seen_digests.get(key)
        if seen == content_digest(current):
            return None
        writer = file_versions.last_writer(target)
        by_writer = f" von `{writer}`" if writer and writer != self.agent_id else ""
        if seen is None:
            return (
                f"'{clean_rel}' existiert bereits (zuletzt geschrieben{by_writer or ' von einem anderen Schritt'}). "
                "Lies die Datei zuerst mit read_file und übernimm deren Inhalt, statt sie blind zu "
                "überschreiben – für punktuelle Änderungen nutze edit_file, für Abhängigkeiten add_dependency."
            )
        return (
            f"'{clean_rel}' wurde seit deinem letzten Lesen{by_writer} geändert. Lies sie erneut mit "
            "read_file und setze deine Änderung auf dem aktuellen Stand um, sonst überschreibst du fremde Arbeit."
        )

    def _preserve_foreign_dependencies(
        self, target: Path, clean_rel: str, current: str, new_content: str,
    ) -> tuple[str, str | None]:
        """Union-Merge für requirements*.txt: Pakete, die ein anderer Agent bereits eingetragen
        hat und die im neuen Inhalt fehlen, werden automatisch beibehalten statt still gelöscht.

        Die bestehende Kollisionserkennung meldet so etwas erst NACH dem Datenverlust; dieser
        Merge verhindert ihn deterministisch und ohne zusätzliche LLM-Iteration.
        """
        if not (target.name.lower().startswith("requirements") and target.suffix.lower() == ".txt"):
            return new_content, None
        merged, preserved = merge_preserving_requirements(current, new_content)
        if not preserved:
            return new_content, None
        return merged, (
            f"{len(preserved)} bereits vorhandene Abhängigkeit(en) in '{clean_rel}' automatisch "
            f"beibehalten, die dein Inhalt nicht enthielt: {', '.join(preserved)}."
        )

    async def _tool_write_file(self, path: str, content: str) -> dict:
        rejection = self._reject_if_invalid_python(path, content)
        if rejection:
            return {"error": rejection}
        rejection = self._reject_if_literal_newline_corruption(path, content)
        if rejection:
            return {"error": rejection}
        rejection = self._reject_if_corrupted_manifest(path, content)
        if rejection:
            return {"error": rejection}
        content, sanitize_note = self._sanitize_toxic_dependencies(path, content, self.project_dir.name)
        new_content = content if content is not None else ""

        target = self._resolve(path)
        clean_rel = self._relative(target)
        rejection = (
            check_path_plausible(clean_rel)
            or check_write_scope(self.agent_id, clean_rel)
            or self._reject_if_premature_reexport(clean_rel, new_content)
        )
        if rejection:
            return {"error": rejection}
        merge_note = None
        if target.is_file():
            current = target.read_text(encoding="utf-8", errors="ignore")
            if current != new_content:
                rejection = self._reject_if_stale(target, clean_rel, current) or check_contract_preserved(
                    self.project_dir, clean_rel, current, new_content,
                )
                if rejection:
                    return {"error": rejection}
                new_content, merge_note = self._preserve_foreign_dependencies(
                    target, clean_rel, current, new_content,
                )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_content, encoding="utf-8")
        ownership_note = self._remember_write(target, clean_rel, new_content)
        result = {"path": clean_rel, "bytes_written": len(new_content.encode("utf-8")), "status": "ok"}
        phantom_note = self._check_test_import_phantoms(clean_rel, new_content)
        warning = " ".join(w for w in (sanitize_note, merge_note, phantom_note, ownership_note) if w)
        if warning:
            result["warning"] = warning
        return result

    async def _tool_add_dependency(self, package: str, manifest: str = "requirements.txt") -> dict:
        """Ergänzt genau EIN Paket idempotent (core/dependency_manifest.py), statt das Manifest
        neu zu schreiben – parallele Agenten überschreiben sich dadurch nicht mehr gegenseitig."""
        from core.manifest_guard import sanitize_requirements

        target = self._resolve(manifest or "requirements.txt")
        clean_rel = self._relative(target)
        if not (target.name.lower().startswith("requirements") and target.suffix.lower() == ".txt"):
            return {"error": "add_dependency unterstützt nur requirements*.txt – für package.json/pyproject.toml nutze edit_file."}
        rejection = check_write_scope(self.agent_id, clean_rel)
        if rejection:
            return {"error": rejection}
        try:
            added = add_requirement(target, package)
        except ValueError as e:
            return {"error": str(e)}
        except OSError as e:
            return {"error": f"Konnte '{clean_rel}' nicht schreiben: {e}"}
        content = target.read_text(encoding="utf-8", errors="ignore")
        warning = None
        if added:
            sanitized, findings = sanitize_requirements(clean_rel, content)
            if findings and sanitized != content:
                target.write_text(sanitized, encoding="utf-8")
                content = sanitized
                warning = "Toxische Paket-Kollision automatisch bereinigt."
            self._remember_write(target, clean_rel, content)
        else:
            self._remember_content(target, content)
        result = {"path": clean_rel, "package": package.strip(), "status": "added" if added else "already_present"}
        if warning:
            result["warning"] = warning
        return result

    async def _tool_edit_file(self, path: str, old_text: str, new_text: str) -> dict:
        target = self._resolve(path)
        if not target.exists():
            return {"error": f"Datei '{path}' existiert nicht – nutze write_file, um sie neu anzulegen."}
        rejection = check_write_scope(self.agent_id, self._relative(target))
        if rejection:
            return {"error": rejection}
        try:
            current = target.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            return {"error": f"Konnte '{path}' nicht lesen: {e}"}

        if not old_text:
            return {"error": "'old_text' darf nicht leer sein."}

        occurrences = current.count(old_text)
        if occurrences == 0:
            return {"error": f"'old_text' wurde in '{path}' nicht gefunden. Lies die Datei erneut mit read_file und prüfe die exakte Formatierung."}
        if occurrences > 1:
            return {"error": f"'old_text' kommt {occurrences}-mal in '{path}' vor – füge mehr umgebenden Kontext hinzu, damit die Stelle eindeutig ist."}

        updated = current.replace(old_text, new_text, 1)
        rejection = self._reject_if_invalid_python(path, updated)
        if rejection:
            return {"error": rejection}
        rejection = self._reject_if_literal_newline_corruption(path, updated)
        if rejection:
            return {"error": rejection}
        rejection = self._reject_if_corrupted_manifest(path, updated)
        if rejection:
            return {"error": rejection}
        updated, sanitize_note = self._sanitize_toxic_dependencies(path, updated, self.project_dir.name)
        clean_rel = self._relative(target)
        rejection = self._reject_if_premature_reexport(clean_rel, updated) or check_contract_preserved(
            self.project_dir, clean_rel, current, updated,
        )
        if rejection:
            return {"error": rejection}

        target.write_text(updated, encoding="utf-8")
        ownership_note = self._remember_write(target, clean_rel, updated)
        result = {"path": clean_rel, "status": "ok"}
        phantom_note = self._check_test_import_phantoms(clean_rel, updated)
        warning = " ".join(w for w in (sanitize_note, phantom_note, ownership_note) if w)
        if warning:
            result["warning"] = warning
        return result

    async def _tool_patch_file(self, path: str, patch: str) -> dict:
        from core.diff_patcher import patch_content

        target = self._resolve(path)
        if not target.exists():
            return {"error": f"Datei '{path}' existiert nicht."}
        if not target.is_file():
            return {"error": f"'{path}' ist keine reguläre Datei."}
        clean_rel = self._relative(target)
        rejection = check_write_scope(self.agent_id, clean_rel)
        if rejection:
            return {"error": rejection}

        try:
            current_content = target.read_text(encoding="utf-8")
        except Exception as e:
            return {"error": f"Konnte '{path}' nicht lesen: {e}"}

        success, new_content, msg = patch_content(current_content, patch)
        if not success:
            return {"error": f"Patch fehlgeschlagen: {msg}"}

        # Syntax-Validierung für Python
        py_err = self._reject_if_invalid_python(path, new_content)
        if py_err:
            return {"error": py_err}
        manifest_err = self._reject_if_corrupted_manifest(path, new_content)
        if manifest_err:
            return {"error": manifest_err}
        new_content, sanitize_note = self._sanitize_toxic_dependencies(path, new_content, self.project_dir.name)
        rejection = check_contract_preserved(self.project_dir, clean_rel, current_content, new_content)
        if rejection:
            return {"error": rejection}

        try:
            target.write_text(new_content, encoding="utf-8")
        except Exception as e:
            return {"error": f"Konnte '{path}' nicht schreiben: {e}"}

        self._remember_write(target, clean_rel, new_content)
        result = {"path": clean_rel, "status": "ok", "message": msg}
        if sanitize_note:
            result["warning"] = sanitize_note
        return result

    # ── Such-Werkzeug ────────────────────────────────────────────────


    async def _tool_search_code(self, query: str, top_k: int = 5) -> dict:
        import asyncio

        from core.embedding_index import semantic_search

        # semantic_search nutzt Embeddings (persistenter Cache pro Projekt) und faellt auf BM25
        # zurueck. In einen Thread ausgelagert, da es blockierende Datei-I/O + API-Aufrufe macht
        # und sonst den Event-Loop paralleler Agenten blockiert.
        results = await asyncio.to_thread(semantic_search, self.project_dir, query, max(1, min(top_k, 15)))
        if not results:
            return {"results": [], "note": "Keine relevanten Treffer (oder noch keine durchsuchbaren Dateien im Projekt)."}
        return {"results": [{"file": r["file"], "line_start": r["line_start"], "chunk": r["chunk"][:1500]} for r in results]}

    async def _tool_search_component_library(self, query: str, category: str = "") -> dict:
        """Sucht in der projektübergreifenden Bibliothek (memory/component_library/) statt im
        aktuellen Projekt, siehe core/component_library.py.

        Liefert den (gedeckelten) Code direkt mit, statt nur einen Pfad zu nennen: _resolve()
        beschränkt read_file strikt auf self.project_dir, die Bibliothek liegt außerhalb und
        wäre so gar nicht erreichbar."""
        from core.component_library import get_snippet_content
        from core.component_library import search as search_library

        results = search_library(query, category=category)
        if not results:
            return {
                "results": [],
                "note": "Kein passender Baustein in der Bibliothek gefunden - implementiere regulär selbst.",
            }
        return {
            # max_chars=1500 je Treffer - dieselbe Obergrenze wie search_code darüber, damit ein
            # voller Ergebnissatz den Loop-Kontext nicht aufbläht (siehe MAX_TOOL_RESULT_CHARS).
            "results": [
                {
                    "category": r["category"], "class_name": r["class_name"],
                    "source_project": r["source_project"],
                    "code": get_snippet_content(r["id"], max_chars=1500),
                }
                for r in results
            ],
            "hinweis": "Als Vorlage verwendbar - an die konkreten Anforderungen dieses Projekts anpassen, nicht blind kopieren.",
        }

    # ── Ausführungs-Werkzeuge ────────────────────────────────────────

    async def _tool_run_command(self, command: str) -> dict:
        cmd_stripped = (command or "").strip()
        if not cmd_stripped:
            return {"error": "Kein Befehl angegeben."}
        if not any(cmd_stripped.startswith(prefix) for prefix in self.ALLOWED_COMMAND_PREFIXES):
            return {
                "error": (
                    f"Befehl '{cmd_stripped.split()[0]}' ist nicht auf der Sicherheits-Whitelist. "
                    f"Erlaubt sind nur: pip, pytest, python -m unittest, npm, npx, node, ruff, mypy, flake8, black --check."
                )
            }

        import asyncio

        argv = split_command_line(cmd_stripped)
        sandbox_kind = _SANDBOXED_COMMAND_KINDS.get(argv[0]) if argv else None
        if sandbox_kind and await asyncio.to_thread(DockerSandbox.is_active):
            if sandbox_kind == "python":
                sandboxed = await asyncio.to_thread(
                    DockerSandbox.run_python, argv, self.project_dir, SANDBOX_COMMAND_TIMEOUT_SECONDS,
                )
            else:
                sandboxed = await asyncio.to_thread(
                    DockerSandbox.run_node, argv, self.project_dir, self.project_dir, SANDBOX_COMMAND_TIMEOUT_SECONDS,
                )
            return {
                "exit_code": sandboxed.exit_code, "stdout": sandboxed.stdout, "stderr": sandboxed.stderr,
                "timed_out": sandboxed.timed_out, "sandbox": "docker",
            }

        # In einem Thread: das erstmalige Anlegen der Projekt-venv (siehe _project_python) dauert
        # mehrere Sekunden und darf die Event-Loop paralleler Agenten nicht blockieren.
        parts = await asyncio.to_thread(self._split_command, cmd_stripped)
        result = await asyncio.to_thread(CodeSandbox.run_command, parts, self.project_dir, 60.0)
        return {"exit_code": result.exit_code, "stdout": result.stdout, "stderr": result.stderr, "timed_out": result.timed_out}

    async def _tool_run_tests(self) -> dict:
        import asyncio

        from core.verifier import ProjectVerifier

        verifier = ProjectVerifier(self.project_dir)
        report = await asyncio.to_thread(verifier.run_tests)
        return {
            "ran": report.ran,
            "passed": report.passed,
            "exit_code": report.exit_code,
            "stdout": report.stdout,
            "stderr": report.stderr,
            "reason_skipped": report.reason_skipped,
        }

    # ── Eskalations-Werkzeug ──────────────────────────────────────────

    async def _tool_ask_human_for_clarification(self, question: str, context: str = "") -> dict:
        if not (question or "").strip():
            return {"error": "'question' darf nicht leer sein."}
        entry = question.strip() if not context.strip() else f"{question.strip()} (Kontext: {context.strip()})"
        self.clarification_requests.append(entry)
        return {
            "status": "recorded",
            "note": (
                "Rückfrage aufgezeichnet - ein Mensch sieht sie, sobald dieser Lauf abgeschlossen ist. "
                "Beende deine Antwort JETZT mit einer ehrlichen, kurzen Zusammenfassung: was bereits "
                "erledigt ist und was durch diese Frage offen bleibt."
            ),
        }

    async def _tool_ask_teammate(self, agent_id: str, question: str) -> dict:
        from config import ENABLE_ASK_TEAMMATE, TEAMMATE_QUESTIONS_PER_AGENT, TEAMMATE_QUESTIONS_PER_RUN
        from core import team_board

        if not ENABLE_ASK_TEAMMATE:
            return {"error": "ask_teammate ist deaktiviert (ENABLE_ASK_TEAMMATE=false)."}
        target = (agent_id or "").strip()
        text = (question or "").strip()
        if not target or not text:
            return {"error": "'agent_id' und 'question' dürfen nicht leer sein."}
        if target == self.agent_id:
            return {"error": "Du kannst dir nicht selbst eine Frage stellen."}
        responder = team_board.get_teammate_responder(self.project_dir)
        if responder is None:
            return {"error": "In diesem Kontext ist kein Team erreichbar – entscheide selbst und dokumentiere die Annahme."}
        if team_board.count_questions(self.project_dir) >= TEAMMATE_QUESTIONS_PER_RUN:
            return {"error": f"Fragen-Limit für diesen Lauf erreicht ({TEAMMATE_QUESTIONS_PER_RUN}) – entscheide selbst."}
        if team_board.count_questions(self.project_dir, asker=self.agent_id) >= TEAMMATE_QUESTIONS_PER_AGENT:
            return {"error": f"Du hast bereits {TEAMMATE_QUESTIONS_PER_AGENT} Fragen gestellt – arbeite mit den Antworten weiter."}
        try:
            answer = await responder(self.agent_id, target, text[:1000], str(self.project_dir))
        except Exception as e:  # noqa: BLE001 - eine gescheiterte Rückfrage darf die Aufgabe nicht abbrechen
            logging.getLogger(__name__).warning("ask_teammate %s -> %s fehlgeschlagen: %r", self.agent_id, target, e)
            answer = f"Keine Antwort von `{target}` ({e})."
        team_board.record_question(
            self.project_dir, team_board.TeammateQuestion(asker=self.agent_id, target=target, question=text[:1000], answer=answer),
        )
        return {"status": "answered", "from": target, "answer": answer}

    # ── Dokumentations-Werkzeug ──────────────────────────────────────

    async def _tool_record_architecture_decision(
        self, title: str, context: str, decision: str, consequences: str,
    ) -> dict:
        from core.adr import find_near_duplicate_adr, write_adr

        if not (title or "").strip():
            return {"error": "'title' darf nicht leer sein."}

        duplicate = find_near_duplicate_adr(self.project_dir, title)
        if duplicate is not None:
            return {
                "error": (
                    f"ADR-{duplicate.number:04d} ('{duplicate.title}') dokumentiert bereits eine sehr "
                    f"ähnliche Entscheidung - lies sie per read_file('{duplicate.path.relative_to(self.project_dir)}') "
                    "und ergänze/aktualisiere diese ADR statt eine neue, fast identische anzulegen. Falls es "
                    "wirklich eine andere Entscheidung ist, wähle einen klar unterscheidbaren Titel."
                ),
            }

        path = write_adr(self.project_dir, title=title, context=context, decision=decision, consequences=consequences)
        clean_rel = str(path.relative_to(self.project_dir)).replace("\\", "/")
        self.files_written.add(clean_rel)
        return {"path": clean_rel, "status": "ok"}

    # ── Code-Knowledge-Graph Werkzeuge ───────────────────────────────

    async def _tool_find_symbol_definition(self, symbol_name: str) -> dict:
        import asyncio

        from core.code_graph import CodebaseGraph

        graph = await asyncio.to_thread(CodebaseGraph, self.project_dir)
        nodes = graph.find_definition(symbol_name)
        if not nodes:
            return {"found": False, "note": f"Symbol '{symbol_name}' nicht im Projekt-Index gefunden."}
        return {
            "found": True,
            "definitions": [
                {
                    "name": n.name,
                    "kind": n.kind,
                    "file_path": n.file_path,
                    "line_number": n.line_number,
                    "signature": n.signature,
                    "docstring": n.docstring[:200] if n.docstring else "",
                }
                for n in nodes
            ],
        }

    async def _tool_find_symbol_references(self, symbol_name: str) -> dict:
        import asyncio

        from core.code_graph import CodebaseGraph

        graph = await asyncio.to_thread(CodebaseGraph, self.project_dir)
        refs = graph.find_references(symbol_name)
        return {"symbol": symbol_name, "references_count": len(refs), "references": refs[:25]}

    async def _tool_analyze_code_impact(self, symbol_name: str) -> dict:
        import asyncio

        from core.code_graph import CodebaseGraph

        graph = await asyncio.to_thread(CodebaseGraph, self.project_dir)
        impact = graph.analyze_impact(symbol_name)
        return {
            "symbol": impact.symbol_name,
            "defining_file": impact.defining_file,
            "referencing_files": impact.referencing_files,
            "calling_symbols": impact.calling_symbols,
            "imported_in": impact.imported_in,
        }

    def _split_command(self, command: str) -> list[str]:
        """Zerlegt den Befehl und bindet `python`/`pip` an die Projekt-venv - sonst landet jedes
        `pip install` eines Agenten im Interpreter des Frameworks.
        """
        parts = split_command_line(command)
        if not parts:
            return parts
        if parts[0] in ("pip", "pip3"):
            return [str(self._project_python(create=True)), "-m", "pip", *parts[1:]]
        if parts[0] in ("python", "python3"):
            parts[0] = str(self._project_python(create=False))
        return parts

    def _project_python(self, create: bool) -> Path:
        """Interpreter der Projekt-venv. Mit `create=True` (Paketinstallation) wird dieselbe venv
        wie von der Verifikation (VENV_DIRNAME) angelegt und NIE auf den Framework-Interpreter
        ausgewichen; ohne `create` (reiner Skript-/Testaufruf) bleibt `sys.executable` Fallback."""
        from core.verifier.models import VENV_DIRNAME

        venv = CodeSandbox.get_project_venv(self.project_dir)
        if venv is None and create:
            venv = self.project_dir / VENV_DIRNAME
            result = CodeSandbox.run_command(
                [sys.executable, "-m", "venv", str(venv)], cwd=self.project_dir, timeout_seconds=180.0,
            )
            if result.exit_code != 0:
                raise ToolExecutionError(
                    "Projekt-venv konnte nicht angelegt werden – Paketinstallation abgebrochen, statt in "
                    f"den Framework-Interpreter zu installieren: {(result.stderr or result.stdout)[:300]}"
                )
        if venv is None:
            return Path(sys.executable)
        python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        if python.is_file():
            return python
        if create:
            raise ToolExecutionError(
                f"Projekt-venv '{venv.name}' ist unvollständig (kein Interpreter unter {python}) – "
                "Paketinstallation abgebrochen. Lösche die venv oder führe run_tests aus, um sie neu anzulegen."
            )
        return Path(sys.executable)
