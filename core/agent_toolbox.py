"""
core/agent_toolbox.py – Echte, projektgebundene Werkzeuge für den agentischen Loop

Die AgentToolbox ist die operative Umsetzung des Werkzeug-Zugriffs (ein früheres,
nie tatsächlich aufgerufenes core/tool_registry.py mit rein statischen
Tool-Deklarationen wurde als toter Code entfernt): Jede Aufgabe mit gesetztem
AgentTask.project_dir bekommt
in agents/base_agent.py eine eigene AgentToolbox-Instanz, die der Agent während
seines Function-Calling-Loops tatsächlich verwendet, um:

- bestehenden Code wirklich zu lesen, bevor er ihn ändert (read_file, list_files)
- Änderungen direkt im Projektverzeichnis zu speichern (write_file, edit_file)
- den Code semantisch zu durchsuchen (search_code)
- Abhängigkeiten zu installieren und Tests wirklich auszuführen (run_command, run_tests)

Alle Datei-Operationen sind strikt auf project_dir beschränkt (kein Directory
Traversal), und run_command ist auf eine Sicherheits-Whitelist begrenzt.
"""

import ast
import fnmatch
import os
import shlex
import sys
from pathlib import Path
from typing import Any

from core.code_sandbox import CodeSandbox
from core.dependency_manifest import add_requirement, merge_preserving_requirements
from core.docker_sandbox import DockerSandbox
from core.failure_triage import is_local_module, is_test_file, module_to_file, read_module_interface
from core.write_guard import check_contract_preserved, check_write_scope, content_digest, file_versions

# Befehle, die Projektcode ausführen und deshalb bei aktiver Docker-Sandbox im Container laufen.
# ruff/mypy/flake8/black analysieren nur statisch und bleiben lokal.
_SANDBOXED_COMMAND_KINDS = {
    "pip": "python", "pip3": "python", "python": "python", "python3": "python", "pytest": "python",
    "npm": "node", "npx": "node", "node": "node",
}
SANDBOX_COMMAND_TIMEOUT_SECONDS = 300.0


def split_command_line(command: str, *, windows: bool | None = None) -> list[str]:
    """Zerlegt eine Agenten-Befehlszeile in Argumente, ohne Windows-Pfade zu zerstören.

    Realer Fund (Framework-Analyse 2026-09-10): `shlex.split()` im POSIX-Modus behandelt `\\`
    als Escape-Zeichen - `pytest tests\\test_auth.py` wurde auf Windows zu `teststest_auth.py`,
    der Agent bekam ein irreführendes "file not found". Auf Windows deshalb `posix=False` und
    nur umschließende Anführungszeichen entfernen.
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
        "description": "Liest den vollständigen Inhalt einer Datei im Projektverzeichnis. Nutze dies IMMER, bevor du eine bestehende Datei änderst.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Relativer Pfad zur Datei, z.B. 'app/main.py'"}},
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
    # ask_human_for_clarification verändert kein Projekt-Dateisystem (reine Aufzeichnung, siehe
    # _tool_ask_human_for_clarification) - auch ein NUR-LESE-Agent (z.B. eine reine Review-
    # Rolle) muss auf eine echte Blockade hinweisen können, nicht nur schreibende Rollen.
    "ask_human_for_clarification",
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
    # Werkzeug-Ergebnisse werden bei JEDER weiteren Loop-Iteration erneut an das Modell
    # mitgesendet (kein serverseitiger State bei den LLM-APIs) – ein zu hoher Wert hier
    # multipliziert sich also mit der Anzahl der Iterationen. 8.000 Zeichen (~2.000 Tokens)
    # reichen für die meisten Quelldateien, ohne den Kontext unnötig aufzublähen.
    MAX_TOOL_RESULT_CHARS = 8_000
    MAX_LISTED_FILES = 300

    # project_dir zeigt normalerweise auf einen generierten Sandbox-Ordner unter workspace/,
    # der strukturell nie Secrets enthält. Seit /audit-projekt kann project_dir aber auch auf
    # das Framework-Root selbst zeigen (echtes .env mit echten API-Keys!) – diese Sperre gilt
    # deshalb IMMER, nicht nur im Nur-Lese-Modus, und blockiert read_file/write_file/edit_file
    # gleichermaßen (verhindert nebenbei auch ein versehentliches Überschreiben von .env).
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
        self.call_log: list[dict[str, Any]] = []
        # Gefüllt von _tool_ask_human_for_clarification() - agents/base_agent.py liest das nach
        # dem Loop-Ende zurück in AgentResult.clarification_questions (dasselbe Muster wie
        # files_written oben).
        self.clarification_requests: list[str] = []
        # Normalisierter absoluter Pfad -> Inhalts-Hash des zuletzt von DIESEM Agenten gesehenen
        # Stands (gelesen oder selbst geschrieben), Grundlage für _reject_if_stale().
        self._seen_digests: dict[str, str] = {}

    async def list_files_snapshot(self, subdir: str = "") -> list[str]:
        """Wie das `list_files`-Werkzeug, aber OHNE call_count/call_log zu erhöhen – für einen
        harness-seitigen Blick auf den Dateibaum (siehe agents/base_agent.py), der nicht als
        vom Agenten selbst initiierter Werkzeug-Aufruf in den Kennzahlen auftauchen soll."""
        result = await self._tool_list_files(subdir=subdir)
        return result.get("files") or []

    def tool_specs(self) -> list[dict[str, Any]]:
        if self.read_only:
            return [t for t in TOOL_SPECS if t["name"] in READ_ONLY_TOOL_NAMES or t["name"] == "run_tests"]
        return TOOL_SPECS

    def _normalize_relative_path(self, clean: str) -> str:
        """Entfernt redundante Präfixe, die Agenten versehentlich voranstellen.
        Realer Fund: Agenten riefen write_file mit 'workspace/feature_pilot/app/main.py'
        oder 'feature_pilot/app/main.py' auf, wodurch Dateien in doppelt verschachtelten
        Ordnern (z.B. feature_pilot/workspace/feature_pilot/...) landeten."""
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

    async def _tool_read_file(self, path: str) -> dict:
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
        return {"path": path, "content": content}

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

        Realer Fund aus einem echten Lauf: ein Agent überschrieb main.py per write_file mit
        Inhalt, der versehentlich ALLE Zeilenumbrüche/Anführungszeichen als literale `\\n`/`\\"`
        statt echter Escape-Sequenzen enthielt (vermutlich doppelt JSON-serialisiert) - eine
        einzige, syntaktisch komplett kaputte Zeile. Die Datei landete unbemerkt auf der Platte,
        der komplette Rest des Frameworks (main.py + interface/cli.py) war danach nicht mehr
        lauffähig, bis die eigentliche Testverifikation (Minuten später, nach mehreren weiteren
        Werkzeug-Aufrufen) das erst über einen Test-Fehlschlag bemerkte. Diese Prüfung fängt es
        SOFORT am Werkzeug selbst ab, bevor überhaupt etwas auf die Platte geschrieben wird -
        nutzt dieselbe ast.parse()-Validierung wie core/code_sandbox.py (Sandbox-Validierung).
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

    def _check_test_import_phantoms(self, path: str, content: str) -> str | None:
        """Gibt eine Warnung zurück (kein Schreibschutz), wenn eine gerade geschriebene Testdatei
        ein Symbol aus einem lokalen Projektmodul importiert, das dort laut echtem Code gar nicht
        exportiert wird - realer Fund (vaultguard-Projekt): der tester-Agent erfand
        `from app.core.encryption import encrypt`, obwohl das Modul nur `EncryptionService.encrypt()`
        als Methode anbot; pytest brach beim Einsammeln mit ImportError ab. Nutzt dieselbe AST-
        Modul-Oberflächen-Analyse wie der Fix-Loop (core/failure_triage.py), aber PROAKTIV vor dem
        Speichern statt erst nach einem roten Testlauf. Bewusst nur eine Warnung im Ergebnis-Dict
        (kein "error"): False Positives (z. B. bedingte Re-Exports über `__init__.py`, dynamisch
        gesetzte Attribute) dürfen den Tester nicht am Speichern hindern, nur darauf hinweisen."""
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

    # Endungen, für die es (anders als .py mit ast.parse in _reject_if_invalid_python) keinen
    # eingebauten Parser gibt, der literale `\n`-Ketten zuverlässig als Syntaxfehler erkennt -
    # siehe _reject_if_literal_newline_corruption() für den vollen Kontext des realen Funds.
    _LITERAL_NEWLINE_CHECK_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".json", ".html", ".css")
    _MIN_LITERAL_NEWLINE_HITS = 3

    @classmethod
    def _reject_if_literal_newline_corruption(cls, path: str, content: str) -> str | None:
        """Gibt eine Fehlermeldung zurück, wenn `content` erkennbar der in
        `_reject_if_invalid_python()` beschriebenen Korruption entspricht (literale `\\n`-Zeichen
        statt echter Zeilenumbrüche), aber die Endung KEINEN eigenen Parser hat, der das schon
        als Syntaxfehler abfangen würde (.py läuft bereits über ast.parse, JSON-Dateien über
        `_reject_if_corrupted_manifest`/den eigentlichen JSON-Parser an anderer Stelle - hier
        zusätzlich als Netz, falls eine solche Datei kein gültiges JSON sein muss).

        Heuristik bewusst konservativ, um normale Quelldateien mit vereinzelten, ECHTEN
        Escape-Sequenzen in String-Literalen (z.B. `console.log("a\\nb")`) nicht fälschlich
        abzulehnen: nur wenn die Datei praktisch NUR aus einer einzigen physischen Zeile besteht
        (kein oder kaum ein echter Zeilenumbruch) UND gleichzeitig mehrfach die literale
        Zwei-Zeichen-Folge `\\n` enthält, deutet das auf eine komplett flachgeklopfte Datei hin -
        genau das reale Muster (vermutlich doppelt JSON-serialisierter LLM-Output), nicht auf
        normalen, mehrzeiligen Code mit ein paar Escape-Sequenzen darin."""
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
        package.json, ...) ist und `content` typische Merge-/Diff-Korruption zeigt – None bedeutet
        "in Ordnung, schreiben erlaubt". Siehe core/manifest_guard.py für den realen Fund, der
        diese Prüfung ausgelöst hat (roh übernommener Diff-Hunk statt gemergter requirements.txt,
        pip install schlug dadurch fehl)."""
        from core.manifest_guard import detect_corrupted_manifest

        return detect_corrupted_manifest(path, content)

    @staticmethod
    def _sanitize_toxic_dependencies(path: str, content: str) -> tuple[str, str | None]:
        """Entfernt toxische Paket-Kollisionen (z.B. `jwt` neben `pyjwt`, siehe
        core/manifest_guard.py) deterministisch VOR dem Schreiben, statt die Datei abzulehnen -
        ein Agent auf einem schwachen Modell würde sonst oft dieselbe Kollision erneut schreiben.
        Gibt den (ggf. bereinigten) Inhalt und einen Hinweis für den Agenten zurück."""
        from core.manifest_guard import describe_toxic_dependencies, sanitize_requirements

        sanitized, findings = sanitize_requirements(path, content or "")
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

    def _remember_write(self, target: Path, clean_rel: str, content: str) -> None:
        self._remember_content(target, content)
        file_versions.record_write(target, self.agent_id)
        self.files_written.add(clean_rel)

    def _reject_if_stale(self, target: Path, clean_rel: str, current: str) -> str | None:
        """Ein vollständiges Überschreiben ist nur erlaubt, wenn dieser Agent den AKTUELLEN Stand
        der Datei kennt (gelesen oder selbst geschrieben) – sonst gewinnt still der letzte von
        mehreren parallelen Agenten (realer Fund: requirements.txt, 6 Überschreibungen in 73 s)."""
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

        Realer Fund (OmniQueue-Lauf 12.09.2026, Befund 3): `backend` und `database` schrieben
        beide `requirements.txt`; der zweite Schreibvorgang kannte `starlette` nicht und löschte
        es. Die bestehende Kollisionserkennung (agents/orchestrator.py) meldet so etwas zwar,
        aber erst NACH dem Datenverlust - dieser Merge verhindert ihn deterministisch und ohne
        eine zusätzliche LLM-Iteration.
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
        content, sanitize_note = self._sanitize_toxic_dependencies(path, content)
        new_content = content if content is not None else ""

        target = self._resolve(path)
        clean_rel = self._relative(target)
        rejection = check_write_scope(self.agent_id, clean_rel)
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
        self._remember_write(target, clean_rel, new_content)
        result = {"path": clean_rel, "bytes_written": len(new_content.encode("utf-8")), "status": "ok"}
        phantom_note = self._check_test_import_phantoms(clean_rel, new_content)
        warning = " ".join(w for w in (sanitize_note, merge_note, phantom_note) if w)
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
        updated, sanitize_note = self._sanitize_toxic_dependencies(path, updated)
        clean_rel = self._relative(target)
        rejection = check_contract_preserved(self.project_dir, clean_rel, current, updated)
        if rejection:
            return {"error": rejection}

        target.write_text(updated, encoding="utf-8")
        self._remember_write(target, clean_rel, updated)
        result = {"path": clean_rel, "status": "ok"}
        phantom_note = self._check_test_import_phantoms(clean_rel, updated)
        warning = " ".join(w for w in (sanitize_note, phantom_note) if w)
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
        new_content, sanitize_note = self._sanitize_toxic_dependencies(path, new_content)
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

        # semantic_search versucht echte Gemini-Embeddings (persistenter Cache pro Projekt,
        # embeddet nur geänderte Dateien neu) und faellt automatisch auf BM25 zurueck.
        # In einen Thread ausgelagert, da sync() blockierende Datei-I/O + API-Aufrufe macht
        # und dieser Aufruf sonst den Event-Loop waehrend parallel laufender Agenten blockiert.
        results = await asyncio.to_thread(semantic_search, self.project_dir, query, max(1, min(top_k, 15)))
        if not results:
            return {"results": [], "note": "Keine relevanten Treffer (oder noch keine durchsuchbaren Dateien im Projekt)."}
        return {"results": [{"file": r["file"], "line_start": r["line_start"], "chunk": r["chunk"][:1500]} for r in results]}

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
        """Zerlegt den Befehl und bindet `python`/`pip` an die Projekt-venv.

        Realer Fund (Framework-Analyse 2026-09-10): `pip`/`python` wurden bisher auf
        `sys.executable` gemappt - den Interpreter des FRAMEWORKS. CodeSandbox.run_command()
        übernimmt einen absoluten Pfad unverändert, die venv-Auflösung griff also nie: jedes
        `pip install` eines Agenten landete in der globalen Python-Installation des Nutzers.
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
