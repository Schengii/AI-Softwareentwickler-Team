"""
Zentrales Sicherheitsmodul für Smart Knowledge Hub.
Bietet Path-Traversal-Schutz mit is_relative_to, Endungsvalidierung und Input-Sanitizing.
"""

from __future__ import annotations
import re
from pathlib import Path
from typing import Sequence


def validate_safe_vault_path(
    root_path: Path,
    relative_path: str,
    allowed_extensions: Sequence[str] = (".md",)
) -> Path:
    """
    Validiert einen relativen Pfad gegen das Vault-Wurzelverzeichnis.
    Verhindert Path-Traversal via is_relative_to, Null-Byte-Injections und beschränkt
    die Dateiendungen auf eine Whitelist.
    """
    if not relative_path or not isinstance(relative_path, str):
        raise ValueError("Pfad darf nicht leer sein.")

    # Schutz gegen Null-Byte Injection
    if "\0" in relative_path:
        raise ValueError("Null-Bytes im Pfad sind verboten.")

    # Normalisierung und Bereinigung führender Slashes / Backslashes
    clean_rel = relative_path.strip().lstrip("/\\")
    if not clean_rel:
        raise ValueError("Ungültiger Pfad nach Bereinigung.")

    resolved_root = root_path.resolve()
    target_path = (resolved_root / clean_rel).resolve()

    # Robuste Path-Traversal-Prüfung mittels Path.is_relative_to (Python 3.9+)
    if not target_path.is_relative_to(resolved_root):
        raise ValueError(
            f"Zugriff verweigert: Pfad '{relative_path}' liegt außerhalb des Vaults."
        )

    # Dateiendungsprüfung falls eine Datei referenziert wird
    if allowed_extensions:
        # Falls keine Endung angegeben wurde und .md erlaubt ist
        if not target_path.suffix and ".md" in allowed_extensions:
            target_path = target_path.with_suffix(".md")
            if not target_path.is_relative_to(resolved_root):
                raise ValueError("Ungültiger Pfad nach Anhängen der Dateiendung.")
        
        # Strikte Prüfung der Dateiendung
        if target_path.suffix.lower() not in [ext.lower() for ext in allowed_extensions]:
            raise ValueError(
                f"Ungültige Dateiendung '{target_path.suffix}'. Erlaubt sind: {', '.join(allowed_extensions)}"
            )

    return target_path


def sanitize_markdown_html(content: str) -> str:
    """
    Entfernt gefährliche Script-Tags, Event-Handler und potenziell bösartige HTML-Konstrukte
    aus Notizinhalten zum Schutz vor Stored XSS.
    """
    if not content:
        return ""

    # Entfernt <script>...</script> (case-insensitive, auch über mehrere Zeilen)
    cleaned = re.sub(r"(?is)<\s*script[^>]*>.*?<\s*/\s*script\s*>", "", content)
    # Entfernt alleinstehende öffnende oder schließende script-Tags
    cleaned = re.sub(r"(?is)<\s*/?\s*script[^>]*>", "", cleaned)
    # Entfernt gefährliche iframe, object, embed, applet Tags
    cleaned = re.sub(r"(?is)<\s*/?\s*(?:iframe|object|embed|applet|meta)[^>]*>", "", cleaned)
    # Entfernt event handler wie onload=, onerror=, onclick=
    cleaned = re.sub(r"(?i)\s+on[a-z]+\s*=\s*(?:'[^']*'|\"[^\"]*\"|[^\s>]+)", "", cleaned)
    # Entfernt javascript: URIs in Attributen
    cleaned = re.sub(r"(?i)href\s*=\s*[\"']javascript:[^\"']*[\"']", "href=\"#\"", cleaned)
    cleaned = re.sub(r"(?i)src\s*=\s*[\"']javascript:[^\"']*[\"']", "src=\"#\"", cleaned)

    return cleaned
