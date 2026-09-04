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
        """
        project_dir = self.get_project_dir(project_name)
        saved_files: list[WorkspaceFile] = []
        matches_found: dict[str, str] = {}

        # Muster 1: Code-Fence mit Doppelpunkt (```python:src/main.py)
        pattern_fence_colon = re.compile(
            r'```(?:[a-zA-Z0-9_\-]+)?:([a-zA-Z0-9_\-\./\\]+)\r?\n(.*?)```',
            re.DOTALL
        )
        for match in pattern_fence_colon.finditer(text_content):
            rel_path = match.group(1).strip()
            content = match.group(2)
            matches_found[rel_path] = content

        # Muster 2: Header-Deklaration gefolgt von Codeblock (### 📄 `requirements.txt` \n ```text\n...)
        pattern_header_fence = re.compile(
            r'(?:#{1,6}|\*\*)\s*(?:[^\n`\'"]*?)[`\'"]([a-zA-Z0-9_\-\./\\]+\.[a-zA-Z0-9]+)[`\'"][^\n]*?\r?\n\s*```(?:[a-zA-Z0-9_\-]+)?\r?\n(.*?)```',
            re.IGNORECASE | re.DOTALL
        )
        for match in pattern_header_fence.finditer(text_content):
            rel_path = match.group(1).strip()
            content = match.group(2)
            matches_found[rel_path] = content

        # Muster 3: Explizite Datei-Deklaration (Datei: `src/main.py`)
        pattern_explicit_file = re.compile(
            r'(?:###|\*\*|#)?\s*(?:Datei|File):\s*[`\'"]?([a-zA-Z0-9_\-\./\\]+)[`\'"]?\s*\r?\n\s*```(?:[a-zA-Z0-9_\-]+)?\r?\n(.*?)```',
            re.IGNORECASE | re.DOTALL
        )
        for match in pattern_explicit_file.finditer(text_content):
            rel_path = match.group(1).strip()
            content = match.group(2)
            matches_found[rel_path] = content

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
            from core.manifest_guard import detect_corrupted_manifest
            if detect_corrupted_manifest(clean_rel, content):
                continue

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
