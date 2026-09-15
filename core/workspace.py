"""
core/workspace.py – Workspace & Projekt-Dateisystem-Engine

Ermöglicht dem KI-Team:
- Automatisches Parsen von Code- & Dateiblöcken aus Agenten-Antworten
- Sicheres Schreiben in Projektordner (workspace/<projekt_name>/)
- Strukturierte Übersicht über erstellte Projektdateien (Tree-View)
- Validierung von Pfaden zur Vermeidung von Directory Traversal
- Export als ZIP-Archiv
"""

import os
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from config import WORKSPACE_DIR
from core.code_sandbox import CodeSandbox

# Dieselben Muster wie WorkspaceManager.parse_and_save_files() (siehe deren Docstring) -
# hierher ausgelagert, damit _find_file_blocks()/text_has_extractable_file_blocks() unten UND
# parse_and_save_files() dieselbe, einmal geprüfte Erkennung teilen, statt sie zu duplizieren.
_PATTERN_FENCE_COLON = re.compile(
    r'```(?:[a-zA-Z0-9_\-]+)?:([a-zA-Z0-9_\-\./\\]+)\r?\n(.*?)```',
    re.DOTALL
)
_PATTERN_HEADER_FENCE = re.compile(
    r'(?:#{1,6}|\*\*)\s*(?:[^\n`\'"]*?)[`\'"]([a-zA-Z0-9_\-\./\\]+\.[a-zA-Z0-9]+)[`\'"][^\n]*?\r?\n\s*```(?:[a-zA-Z0-9_\-]+)?\r?\n(.*?)```',
    re.IGNORECASE | re.DOTALL
)
_PATTERN_EXPLICIT_FILE = re.compile(
    r'(?:###|\*\*|#)?\s*(?:Datei|File):\s*[`\'"]?([a-zA-Z0-9_\-\./\\]+)[`\'"]?\s*\r?\n\s*```(?:[a-zA-Z0-9_\-]+)?\r?\n(.*?)```',
    re.IGNORECASE | re.DOTALL
)
# Realer Fund im OmniQueue-Lauf: der tester-Agent lieferte eine vollständige Testsuite als
# reinen Fließtext-Codeblock im branchenüblichen Standardformat (erste Zeile im Fence ein
# Kommentar mit dem Dateipfad, z.B. "# tests/test_api.py"), das keines der drei obigen Muster
# abdeckte - weder Fence-Doppelpunkt-Syntax noch eine Überschrift/​"Datei:"-Zeile davor. Das
# Hard Delivery Gate schlug daraufhin zu, obwohl der vollständige, rettbare Code vorlag
# (46.643 Tokens verpufften). Dieses Muster erkennt genau diese erste-Zeile-Kommentar-Konvention:
# ein Fence, dessen allererste Zeile NUR aus "# pfad/zu/datei.ext" besteht.
_PATTERN_FIRST_LINE_COMMENT = re.compile(
    r'```(?:[a-zA-Z0-9_\-]+)?\r?\n(?=#\s*([a-zA-Z0-9_\-]+(?:[./\\][a-zA-Z0-9_\-]+)*\.[a-zA-Z0-9]+)\s*\r?\n)(.*?)```',
    re.DOTALL
)
# `/goal`-Auftrag ("Hard Delivery Gate"-Optimierung, echter Fund nexus_resilience_gateway-Lauf):
# der frontend-Agent lieferte fertigen HTML/JS-Code als Markdown-Codeblock, dessen Dateipfad
# NICHT im etablierten "Datei:"/"File:"-Format (_PATTERN_EXPLICIT_FILE) davorstand, sondern in
# den ebenfalls verbreiteten Konventionen `# Dateipfad: public/index.html`,
# `<!-- public/index.html -->` oder `// File: app/main.py` unmittelbar VOR dem Fence. Keines
# der bisherigen vier Muster erkannte das (_PATTERN_EXPLICIT_FILE verlangt zwingend das Wort
# "Datei"/"File" gefolgt von ":", "Dateipfad" und der Kommentar-/HTML-Kommentar-Syntax passen
# nicht). Dieses Muster deckt alle drei Header-Varianten in einer Regex ab.
_PATTERN_COMMENT_STYLE_PATH = re.compile(
    r'(?:^|\n)[ \t]*(?:#\s*Dateipfad:|//\s*File:|<!--\s*)\s*'
    r'([a-zA-Z0-9_\-\./\\]+\.[a-zA-Z0-9]+)\s*(?:-->)?[ \t]*\r?\n'
    r'[ \t]*```(?:[a-zA-Z0-9_\-]+)?\r?\n(.*?)```',
    re.IGNORECASE | re.DOTALL,
)


# Realer Fund in HookSentinel: der security-Agent brachte in seiner Review-Ausgabe ein
# Markdown-Negativbeispiel ("# ❌ VORHER: Ungefilterte Eingaben ..." gefolgt von einem
# Codeblock mit "..."-Rumpf), das die Text-Fallback-Erkennung fälschlicherweise als zu
# speichernde Projektdatei einstufte und `app/api/endpoints.py` mit dem 4-Zeilen-Snippet
# überschrieb. Diese Marker + Stub-Erkennung verhindern das, indem sie genau solche
# "So NICHT"-Blöcke von der Übernahme in _find_file_blocks() ausschließen.
_NEGATIVE_EXAMPLE_HEADING_RE = re.compile(
    r'❌\s*VORHER|Vorher\s*:|Negativbeispiel', re.IGNORECASE
)


def _looks_like_stub_content(content: str) -> bool:
    """True, wenn der Blockinhalt nur aus Platzhaltern/Ellipsen (z.B. '...', 'pass') besteht,
    statt aus echtem, speicherwürdigem Code."""
    stripped_lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    if not stripped_lines:
        return True
    real_lines = [
        ln for ln in stripped_lines
        if ln not in ("...", "# ...", "pass", "…") and not re.fullmatch(r'\.{3,}', ln)
    ]
    return not real_lines


def _is_negative_example_block(text_content: str, match_start: int) -> bool:
    """True, wenn der Codeblock unmittelbar unter einer Überschrift wie '❌ VORHER',
    'Vorher:' oder 'Negativbeispiel' steht - also ein Reviewer-"So NICHT"-Beispiel statt einer
    tatsächlichen Projektdatei ist."""
    preceding_window = text_content[max(0, match_start - 200):match_start]
    preceding_lines = [ln for ln in preceding_window.splitlines() if ln.strip()]
    if not preceding_lines:
        return False
    return bool(_NEGATIVE_EXAMPLE_HEADING_RE.search(preceding_lines[-1]))


def _strip_path_comment_line(rel_path: str, content: str) -> str:
    """Inhalt ohne die führende `# pfad/zur/datei.py`-Zeile (_PATTERN_FIRST_LINE_COMMENT) - nur
    für die Stub-Prüfung. Der Pfad-Kommentar selbst ist KEIN echter Inhalt: ohne dieses
    Abstreifen hielte `_looks_like_stub_content()` einen reinen Platzhalter-Block
    ("# app/main.py" + "...") fälschlich für speicherwürdigen Code."""
    first_line, separator, rest = content.partition("\n")
    if separator and first_line.strip().lstrip("#").strip() == rel_path:
        return rest
    return content


def _find_file_blocks(text_content: str) -> dict[str, str]:
    """Rohe Rel-Pfad -> Inhalt-Treffer aller Text-Fallback-Muster, OHNE jede I/O oder
    Validierung (Syntax-/Manifest-Check passiert erst in parse_and_save_files() beim
    tatsächlichen Speichern) - reine, günstige Text-Erkennung für beide Aufrufer unten.
    Reviewer-Negativbeispiele (siehe _is_negative_example_block) und reine Stub-Blöcke
    (siehe _looks_like_stub_content) werden dabei bewusst nie als Datei-Treffer gewertet."""
    matches_found: dict[str, str] = {}
    for pattern in (
        _PATTERN_FENCE_COLON, _PATTERN_HEADER_FENCE, _PATTERN_EXPLICIT_FILE,
        _PATTERN_FIRST_LINE_COMMENT, _PATTERN_COMMENT_STYLE_PATH,
    ):
        for match in pattern.finditer(text_content):
            rel_path, content = match.group(1).strip(), match.group(2)
            if _is_negative_example_block(text_content, match.start()):
                continue
            if _looks_like_stub_content(_strip_path_comment_line(rel_path, content)):
                continue
            matches_found[rel_path] = content
    return matches_found


def text_has_extractable_file_blocks(text_content: str) -> bool:
    """
    True, wenn `text_content` mindestens einen Codeblock enthält, den parse_and_save_files()
    als Datei erkennen und (Text-Fallback) speichern WÜRDE - ohne selbst etwas zu speichern.

    Bugfix (bei der KI-Team-Gesamtanalyse gefunden): agents/base_agent.py's "Hard Delivery
    Gate" wertete bisher JEDEN Abschluss eines Code-schreibenden Agenten ohne write_file/
    edit_file-Tool-Aufruf als Fehlschlag - unabhängig davon, ob der Antworttext tatsächlich
    einen für core/workspace.py.parse_and_save_files() (Text-Fallback) erkennbaren Codeblock
    enthielt. Genau DAFÜR wurde der Text-Fallback-Mechanismus aber gebaut: ein Agent liefert
    Code im Antworttext statt über ein Werkzeug, der Orchestrator rettet die Datei trotzdem
    (agents/orchestrator/__init__.py._run_department_hierarchy, `AUTO_SAVE_WORKSPACE`). Da
    dieser Rettungspfad NUR für `res.success and res.content` greift (siehe dort), erstickte
    das Hard Delivery Gate ihn faktisch, indem es den Agenten schon VOR dem Text-Fallback als
    gescheitert markierte - real reproduziert: tests/test_text_fallback_report_visibility.py
    (dieselbe Fixture, die Text-Fallback ursprünglich absichern sollte, schlug dadurch selbst
    fehl). Das Gate nutzt diese Funktion jetzt, um einen Abschluss OHNE Werkzeug-Aufruf, der
    trotzdem einen rettbaren Codeblock enthält, NICHT als Fehlschlag zu werten.
    """
    return bool(_find_file_blocks(text_content))


def extract_file_blocks(text_content: str) -> dict[str, str]:
    """
    Öffentlicher Zugriff auf die rohen Rel-Pfad -> Inhalt-Treffer aus `_find_file_blocks()`, für
    Aufrufer, die den tatsächlichen Pfad+Inhalt brauchen (nicht nur das bool von
    `text_has_extractable_file_blocks()`).

    `/goal`-Auftrag ("Hard Delivery Gate"-Optimierung): agents/base_agent.py nutzt dies für den
    Auto-Recovery-Parser, der einen erkannten Codeblock SOFORT über den validierten
    write_file-Pfad speichert, statt den Turn nur als "theoretisch rettbar" zu markieren und die
    tatsächliche Speicherung dem viel späteren, orchestrator-weiten Text-Fallback
    (agents/orchestrator/__init__.py, AUTO_SAVE_WORKSPACE) zu überlassen.
    """
    return dict(_find_file_blocks(text_content))


@dataclass
class WorkspaceFile:
    """Repräsentiert eine im Workspace erstellte oder geänderte Datei."""
    relative_path: str
    absolute_path: str
    size_bytes: int
    created_by_agent: str
    timestamp: datetime = field(default_factory=datetime.now)


class WorkspaceManager:
    """
    Verwaltet das Projektdateisystem für das KI-Entwickler-Team.
    """

    def __init__(self, base_workspace_dir: str | None = None):
        self.base_dir = Path(base_workspace_dir or WORKSPACE_DIR).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _canonical_key(name: str) -> str:
        """
        Vergleichs-Schlüssel für "meinen zwei Namen dasselbe Projekt?" - NUR zum Vergleichen
        gedacht, nie als tatsächlicher Ordnername (siehe get_project_dir unten für die
        sichtbare Normalisierung). Lowercased und entfernt JEDES Nicht-Alphanumerische
        komplett (statt es wie clean_name in "_" umzuwandeln), damit "WebhookShield",
        "webhook_shield" und "Webhook Shield" auf denselben Schlüssel abbilden.
        """
        return re.sub(r'[^a-z0-9]', '', name.lower())

    def get_project_dir(self, project_name: str) -> Path:
        """
        Gibt den sicheren Pfad zum Projektverzeichnis zurück (unterstützt auch absolute Pfade).

        Team-Retrospektive (Verbesserungsvorschlag "Projekt-Namens-Kanonisierung"): ein realer
        Lauf bekam den Auftrag "WebhookShield reparieren", der Orchestrator legte aber
        `workspace/webhookshield/` an, weil der eigentliche Code bereits unter
        `workspace/webhook_shield/` lag (aus einem früheren Lauf mit Leerzeichen im Namen -
        die alte Normalisierung unten wandelte Leerzeichen in "_", aber unterschied nicht
        Groß-/Kleinschreibung). Der Agent fand ein leeres Verzeichnis, hielt es für ein
        gelöschtes/kaputtes Projekt und fragte drei Mal nach, statt zu bauen - ein kompletter
        Lauf verpuffte fast folgenlos (nur README.md + requirements.txt). Bevor ein NEUES
        Verzeichnis angelegt wird, prüft diese Methode jetzt per `_canonical_key`, ob unter den
        bereits vorhandenen `base_dir`-Ordnern einer denselben kanonischen Schlüssel hat - wenn
        ja, wird DIESER bestehende Ordner zurückgegeben statt ein leerer Zwilling angelegt.
        """
        # Wenn ein absoluter Pfad (z.B. C:\Projekte\App) übergeben wurde
        if os.path.isabs(project_name):
            path_candidate = Path(project_name).resolve()
            path_candidate.mkdir(parents=True, exist_ok=True)
            return path_candidate

        clean_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', project_name).strip('_') or "default_project"
        clean_name = clean_name.lower()
        project_path = (self.base_dir / clean_name).resolve()

        if not project_path.exists():
            target_key = self._canonical_key(project_name)
            try:
                existing_dirs = [p for p in self.base_dir.iterdir() if p.is_dir()]
            except OSError:
                existing_dirs = []
            for existing in existing_dirs:
                if existing.name == clean_name:
                    continue
                if self._canonical_key(existing.name) == target_key:
                    # Bestehendes Projekt mit demselben kanonischen Namen gefunden - dieses
                    # wiederverwenden statt einen leeren Zwilling anzulegen. Nur, wenn es
                    # tatsächlich Inhalt hat (ein ebenfalls leerer gleichnamiger Ordner bringt
                    # keinen Vorteil gegenüber dem neuen clean_name-Pfad).
                    try:
                        has_content = any(existing.iterdir())
                    except OSError:
                        has_content = False
                    if has_content:
                        return existing

        project_path.mkdir(parents=True, exist_ok=True)
        return project_path

    def read_existing_project_context(self, project_name: str, query: str | None = None, max_chars: int = 12000) -> str:
        """
        Liest bestehende Projektdateien ein.
        Unterstützt automatisches RAG-Indexing & BM25-Recherche für große Repositories.
        """
        project_dir = self.get_project_dir(project_name)
        if not project_dir.exists():
            return ""

        valid_extensions = {".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json", ".sql", ".md", ".txt", ".yml", ".yaml"}
        file_map: dict[str, str] = {}

        for file_path in project_dir.rglob("*"):
            if file_path.is_file() and file_path.suffix in valid_extensions:
                parts = file_path.parts
                if any(p in (".venv", "venv", ".git", "__pycache__", "node_modules", "dist", "build") for p in parts):
                    continue
                try:
                    rel_path = str(file_path.relative_to(project_dir))
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    file_map[rel_path] = content
                except Exception:
                    pass

        if not file_map:
            return ""

        # Wenn RAG Query übergeben wurde oder das Projekt viele Dateien hat, nutze semantische Suche
        # (echte Gemini-Embeddings mit persistentem Cache, Fallback auf BM25 – core/embedding_index.py)
        if query and len(file_map) > 5:
            from core.embedding_index import semantic_search
            top_chunks = semantic_search(project_dir, query, top_k=6)
            context_lines = [f"### 🔍 RAG-RELEVANTER CODE AUS ({project_dir.name}) FÜR '{query}':\n"]
            for chunk in top_chunks:
                context_lines.append(f"--- DATEI: {chunk['file']} (Zeile {chunk['line_start']}) ---\n{chunk['chunk']}\n\n")
            return "\n".join(context_lines)

        context_lines = [f"### 📂 DATEIEN IM BESTEHENDEN PROJEKT ({project_dir.name}):\n"]
        total_len = 0
        for rel_path, content in file_map.items():
            if len(content) > 3000:
                content = content[:3000] + "\n... [gekürzt] ..."
            snippet = f"--- DATEI: {rel_path} ---\n{content}\n\n"
            if total_len + len(snippet) > max_chars:
                break
            context_lines.append(snippet)
            total_len += len(snippet)

        return "\n".join(context_lines)

    def parse_and_save_files(
        self,
        project_name: str,
        text_content: str,
        agent_name: str = "agent",
    ) -> list[WorkspaceFile]:
        """
        Scannt den Text eines Agenten nach Codeblöcken mit Dateipfaden und speichert sie ab.

        Unterstützte Muster:
        1. ```python:src/main.py
        2. ### `src/main.py` \n ```python
        3. #### `app.py` \n ```python
        4. ### 📄 `requirements.txt` \n ```text
        5. Datei: src/main.py \n ```python
        6. ```python \n # tests/test_api.py  (Pfad als alleinige erste Fence-Zeile)
        """
        project_dir = self.get_project_dir(project_name)
        saved_files: list[WorkspaceFile] = []
        matches_found = _find_file_blocks(text_content)

        # Speichere alle gefundenen Dateien ab
        for rel_path, content in matches_found.items():
            clean_rel = rel_path.replace("\\", "/").lstrip("/")
            clean_rel = re.sub(r'\.\./', '', clean_rel)

            target_file = (project_dir / clean_rel).resolve()

            if not str(target_file).startswith(str(project_dir)):
                continue

            # Wie core/agent_toolbox.py._tool_write_file(): niemals syntaktisch kaputtes Python
            # unbemerkt auf die Platte schreiben. Diese Regex-basierte Extraktion aus dem freien
            # Antworttext ist fehleranfälliger als ein natives write_file-Tool-Argument (z.B. bei
            # unsauber geschlossenen Codeblöcken) - lieber gar nicht speichern als eine Datei mit
            # kaputtem Inhalt zu überschreiben.
            if clean_rel.lower().endswith(".py") and not CodeSandbox.validate_code(content, "py").is_valid:
                continue

            # Dieselbe Manifest-Korruptions-Prüfung wie core/agent_toolbox.py._tool_write_file():
            # ein roh übernommener Diff-Hunk statt einer echten requirements.txt/package.json
            # darf nicht unbemerkt auf die Platte gelangen (siehe core/manifest_guard.py).
            from core.manifest_guard import detect_corrupted_manifest, sanitize_requirements
            if detect_corrupted_manifest(clean_rel, content):
                continue
            content, _toxic = sanitize_requirements(clean_rel, content)

            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(content, encoding="utf-8")

            saved_files.append(
                WorkspaceFile(
                    relative_path=clean_rel,
                    absolute_path=str(target_file),
                    size_bytes=len(content.encode("utf-8")),
                    created_by_agent=agent_name,
                )
            )

        return saved_files

    def list_projects(self) -> list[str]:
        """Gibt die Namen aller vorhandenen Projektordner im Workspace zurück (sortiert)."""
        if not self.base_dir.exists():
            return []
        return sorted(p.name for p in self.base_dir.iterdir() if p.is_dir())

    def list_project_files(self, project_name: str) -> list[dict]:
        """Gibt eine Liste aller Dateien im Projektordner zurück."""
        project_dir = self.get_project_dir(project_name)
        file_list = []

        for path in project_dir.rglob("*"):
            if path.is_file():
                rel = path.relative_to(project_dir)
                file_list.append({
                    "path": str(rel).replace("\\", "/"),
                    "size_bytes": path.stat().st_size,
                    "absolute_path": str(path),
                })
        return sorted(file_list, key=lambda x: x["path"])

    def create_project_zip(self, project_name: str, target_zip_path: str | None = None) -> str:
        """Packt das gesamte Projektverzeichnis in ein ZIP-Archiv."""
        project_dir = self.get_project_dir(project_name)
        if target_zip_path is None:
            zip_dest = project_dir.parent / f"{project_dir.name}_export.zip"
        else:
            zip_dest = Path(target_zip_path).resolve()

        with zipfile.ZipFile(zip_dest, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path in project_dir.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(project_dir)
                    zipf.write(file_path, arcname)

        return str(zip_dest)

    def clean_project(self, project_name: str) -> bool:
        """Löscht ein Projektverzeichnis."""
        project_dir = self.get_project_dir(project_name)
        if project_dir.exists():
            shutil.rmtree(project_dir)
            return True
        return False
