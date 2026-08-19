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
from typing import Optional

from config import WORKSPACE_DIR


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

    def __init__(self, base_workspace_dir: Optional[str] = None):
        self.base_dir = Path(base_workspace_dir or WORKSPACE_DIR).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_project_dir(self, project_name: str) -> Path:
        """Gibt den sicheren Pfad zum Projektverzeichnis zurück."""
        # Bereinige Projektnamen gegen Directory-Traversal
        clean_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', project_name).strip('_') or "default_project"
        project_path = (self.base_dir / clean_name).resolve()
        
        # Sicherheitscheck: Muss innerhalb des Workspace-Verzeichnisses liegen
        if not str(project_path).startswith(str(self.base_dir)):
            raise ValueError(f"Ungültiger Projektpfad: {project_name}")

        project_path.mkdir(parents=True, exist_ok=True)
        return project_path

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
           ... code ...
           ```
        2. ```yaml:docker-compose.yml
           ... code ...
           ```
        3. ### Datei: `src/utils/helpers.py`
           ```python
           ... code ...
           ```
        """
        project_dir = self.get_project_dir(project_name)
        saved_files: list[WorkspaceFile] = []

        # Muster 1: Code-Fence mit Doppelpunkt (z. B. ```python:path/to/file.ext oder ```:path/to/file.ext)
        pattern_fence_colon = re.compile(
            r'```(?:[a-zA-Z0-9_\-]+)?:([a-zA-Z0-9_\-\./\\]+)\r?\n(.*?)```',
            re.DOTALL
        )

        # Muster 2: Header-Deklaration gefolgt von Codeblock: ### Datei: `path/to/file` \n ```...
        pattern_header_fence = re.compile(
            r'(?:###|\*\*|#)?\s*(?:Datei|File):\s*[`\'"]?([a-zA-Z0-9_\-\./\\]+)[`\'"]?\s*\r?\n\s*```(?:[a-zA-Z0-9_\-]+)?\r?\n(.*?)```',
            re.IGNORECASE | re.DOTALL
        )

        matches_found: dict[str, str] = {}

        # Scan nach Muster 1
        for match in pattern_fence_colon.finditer(text_content):
            rel_path = match.group(1).strip()
            content = match.group(2)
            matches_found[rel_path] = content

        # Scan nach Muster 2
        for match in pattern_header_fence.finditer(text_content):
            rel_path = match.group(1).strip()
            content = match.group(2)
            matches_found[rel_path] = content

        # Speichere alle gefundenen Dateien ab
        for rel_path, content in matches_found.items():
            # Bereinige relative Pfadangabe
            clean_rel = rel_path.replace("\\", "/").lstrip("/")
            # Vermeide .. im Pfad
            clean_rel = re.sub(r'\.\./', '', clean_rel)

            target_file = (project_dir / clean_rel).resolve()

            # Sicherheitscheck: Datei muss im project_dir liegen
            if not str(target_file).startswith(str(project_dir)):
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

    def create_project_zip(self, project_name: str, target_zip_path: Optional[str] = None) -> str:
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
