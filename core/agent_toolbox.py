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

import fnmatch
import shlex
import sys
from pathlib import Path
from typing import Any

from core.code_sandbox import CodeSandbox

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

    def _resolve(self, rel_path: str) -> Path:
        if not rel_path:
            raise ToolExecutionError("Es wurde kein Pfad angegeben.")
        clean = rel_path.replace("\\", "/").lstrip("/")
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

    async def _tool_write_file(self, path: str, content: str) -> dict:
        rejection = self._reject_if_invalid_python(path, content)
        if rejection:
            return {"error": rejection}

        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content if content is not None else "", encoding="utf-8")
        clean_rel = str(target.relative_to(self.project_dir)).replace("\\", "/")
        self.files_written.add(clean_rel)
        return {"path": clean_rel, "bytes_written": len((content or "").encode("utf-8")), "status": "ok"}

    async def _tool_edit_file(self, path: str, old_text: str, new_text: str) -> dict:
        target = self._resolve(path)
        if not target.exists():
            return {"error": f"Datei '{path}' existiert nicht – nutze write_file, um sie neu anzulegen."}
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

        target.write_text(updated, encoding="utf-8")
        clean_rel = str(target.relative_to(self.project_dir)).replace("\\", "/")
        self.files_written.add(clean_rel)
        return {"path": clean_rel, "status": "ok"}

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
        parts = self._split_command(cmd_stripped)
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
        from core.adr import write_adr

        if not (title or "").strip():
            return {"error": "'title' darf nicht leer sein."}

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

    @staticmethod
    def _split_command(command: str) -> list[str]:
        parts = shlex.split(command)
        if not parts:
            return parts
        # 'python'/'pip' generisch auf den aktuell laufenden Interpreter mappen,
        # damit im richtigen (venv-)Environment ausgeführt wird.
        if parts[0] in ("python", "python3"):
            parts[0] = sys.executable
        elif parts[0] in ("pip", "pip3"):
            parts = [sys.executable, "-m", "pip"] + parts[1:]
        return parts
