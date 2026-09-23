from pathlib import Path
from typing import Any

import aiofiles

from app.core.markdown import parse_markdown, serialize_markdown


class VaultManager:
    def __init__(
        self,
        root_dir: str | None = None,
        vault_dir: str | None = None,
        vault_path: str | None = None,
    ):
        resolved_dir = vault_dir or vault_path or root_dir or "vault"
        self.root_path = Path(resolved_dir).resolve()
        self._ensure_root_exists()

    async def initialize_vault(self) -> None:
        """Explizite (asynchrone) Initialisierung der Vault-Ordnerstruktur und Standarddateien."""
        self._ensure_root_exists()

    def _ensure_root_exists(self) -> None:
        self.root_path.mkdir(parents=True, exist_ok=True)
        # Wenn Vault komplett leer ist, initialisiere Standard-Zettelkasten-Struktur
        standard_folders = ["01 Projects", "02 Areas", "03 Resources", "04 Archives"]
        for folder in standard_folders:
            (self.root_path / folder).mkdir(exist_ok=True)

        welcome_file = self.root_path / "01 Projects" / "Welcome.md"
        if not any(self.root_path.glob("**/*.md")):
            welcome_content = """---
title: Welcome to Smart Knowledge Hub
tags: [onboarding, zettelkasten, welcome]
created: 2026-09-22
type: permanent
---

# Welcome to Smart Knowledge Hub

Willkommen in deinem lokalen Zettelkasten & Wissensportal!

## Features
- **Hierarchische Notizen**: Organisiert in Ordnern wie `01 Projects`, `02 Areas`, `03 Resources`.
- **Bidirektionale Wikilinks**: Verknüpfe Notizen mit `[[Notiz Name]]`.
- **ADR-Generator**: Erstelle Architektur-Entscheidungen nach Nygard im Handumdrehen.
- **Semantische Suche**: Finde Notizen mit natürlicher Sprache und RAG-BM25 Index.

Siehe auch: [[Architecture Principles]] und [[Zettelkasten Methodik]].
"""
            welcome_file.write_text(welcome_content, encoding="utf-8")

            # Eine zweite Notiz für Wikilink-Graph
            arch_file = self.root_path / "03 Resources" / "Architecture Principles.md"
            arch_content = """---
title: Architecture Principles
tags: [architecture, principles, backend]
created: 2026-09-22
type: resource
---

# Architecture Principles

Kernprinzipien moderner Softwarearchitektur:
1. Lose Kopplung
2. Hohe Kohäsion
3. Contract-First API Design

Rückverweis zu: [[Welcome to Smart Knowledge Hub]].
"""
            arch_file.write_text(arch_content, encoding="utf-8")

    def _resolve_safe_path(self, relative_path: str) -> Path:
        """
        Validiert den relativen Pfad und stellt sicher, dass kein Path-Traversal
        außerhalb des Vaults möglich ist.
        """
        clean_rel = relative_path.strip().lstrip("/\\")
        target_path = (self.root_path / clean_rel).resolve()
        if not str(target_path).startswith(str(self.root_path)):
            raise ValueError(f"Ungültiger Pfad: Zugriff außerhalb des Vaults verweigert ({relative_path})")
        return target_path

    async def get_tree(self) -> dict[str, Any]:
        """
        Gibt eine rekursive Baumstruktur des Vaults zurück.
        """
        def build_node(current_path: Path) -> dict[str, Any]:
            rel_path = current_path.relative_to(self.root_path).as_posix()
            if current_path.is_dir():
                children = []
                for item in sorted(current_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                    if item.name.startswith("."):
                        continue
                    if item.is_dir() or item.suffix.lower() == ".md":
                        children.append(build_node(item))
                return {
                    "name": current_path.name if rel_path != "." else "Vault",
                    "path": rel_path if rel_path != "." else "",
                    "type": "directory",
                    "children": children
                }
            else:
                return {
                    "name": current_path.name,
                    "path": rel_path,
                    "type": "file",
                    "size": current_path.stat().st_size
                }

        return build_node(self.root_path)

    async def list_notes(self) -> list[dict[str, Any]]:
        """
        Listet alle Notizen mit relativen Pfaden und Metadaten auf.
        """
        notes: list[dict[str, Any]] = []
        for file_path in self.root_path.glob("**/*.md"):
            if any(part.startswith(".") for part in file_path.parts):
                continue
            rel_path = file_path.relative_to(self.root_path).as_posix()
            try:
                async with aiofiles.open(file_path, mode="r", encoding="utf-8") as f:
                    content = await f.read()
                parsed = parse_markdown(content, default_title=file_path.stem)
                notes.append({
                    "path": rel_path,
                    "title": parsed.title,
                    "tags": parsed.tags,
                    "wikilinks": parsed.wikilinks,
                    "frontmatter": parsed.frontmatter,
                    "modified": file_path.stat().st_mtime
                })
            except Exception:  # noqa: BLE001 - Ignoriere unlesbare Notizen beim Listen
                continue
        return sorted(notes, key=lambda n: n["path"].lower())

    async def get_note(self, relative_path: str) -> dict[str, Any]:
        """
        Liest eine Notiz ein und parst Markdown und Frontmatter.
        """
        if not relative_path.endswith(".md"):
            relative_path = f"{relative_path}.md"
        target_path = self._resolve_safe_path(relative_path)
        if not target_path.exists() or not target_path.is_file():
            raise FileNotFoundError(f"Notiz nicht gefunden: {relative_path}")

        async with aiofiles.open(target_path, mode="r", encoding="utf-8") as f:
            raw_content = await f.read()

        parsed = parse_markdown(raw_content, default_title=target_path.stem)
        return {
            "path": target_path.relative_to(self.root_path).as_posix(),
            "name": target_path.name,
            "title": parsed.title,
            "content": parsed.content,
            "raw_content": raw_content,
            "frontmatter": parsed.frontmatter,
            "wikilinks": parsed.wikilinks,
            "tags": parsed.tags,
            "modified": target_path.stat().st_mtime
        }

    async def save_note(
        self,
        relative_path: str,
        content: str,
        frontmatter: dict[str, Any] | None = None,
        raw_content: str | None = None
    ) -> dict[str, Any]:
        """
        Erstellt oder aktualisiert eine Notiz. Schreibt physisch auf die Festplatte.
        """
        if not relative_path.endswith(".md"):
            relative_path = f"{relative_path}.md"
        target_path = self._resolve_safe_path(relative_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if raw_content is not None:
            final_text = raw_content
        else:
            final_text = serialize_markdown(content, frontmatter)

        async with aiofiles.open(target_path, mode="w", encoding="utf-8") as f:
            await f.write(final_text)

        parsed = parse_markdown(final_text, default_title=target_path.stem)
        return {
            "path": target_path.relative_to(self.root_path).as_posix(),
            "name": target_path.name,
            "title": parsed.title,
            "content": parsed.content,
            "raw_content": final_text,
            "frontmatter": parsed.frontmatter,
            "wikilinks": parsed.wikilinks,
            "tags": parsed.tags,
            "modified": target_path.stat().st_mtime
        }

    async def delete_note(self, relative_path: str) -> bool:
        """
        Löscht eine Notiz.
        """
        target_path = self._resolve_safe_path(relative_path)
        if not target_path.exists():
            raise FileNotFoundError(f"Notiz nicht gefunden: {relative_path}")
        target_path.unlink()
        return True


vault_manager = VaultManager()

