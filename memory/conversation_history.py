"""
memory/conversation_history.py – Verwaltet den Gesprächsverlauf

Speichert alle Nachrichten zwischen Nutzer und Hauptagent und
stellt Kontext für neue Anfragen bereit.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime

from config import MEMORY_DIR


@dataclass
class ChatMessage:
    """Eine einzelne Nachricht im Gesprächsverlauf."""
    role: str              # "user" oder "assistant"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class ConversationHistory:
    """
    Verwaltet den Gesprächsverlauf zwischen Nutzer und Hauptagent.
    Speichert Nachrichten im Arbeitsspeicher und optional auf Disk.
    """

    def __init__(self, session_id: str = "default"):
        self.session_id = session_id
        self._messages: list[ChatMessage] = []
        self._history_file = os.path.join(MEMORY_DIR, f"history_{session_id}.json")
        self._load_from_disk()

    def add_user_message(self, content: str) -> None:
        """Fügt eine Nutzer-Nachricht hinzu."""
        self._messages.append(ChatMessage(role="user", content=content))
        self._save_to_disk()

    def add_assistant_message(self, content: str) -> None:
        """Fügt eine Assistenten-Nachricht hinzu."""
        self._messages.append(ChatMessage(role="assistant", content=content))
        self._save_to_disk()

    def get_messages(self, max_messages: int = 20) -> list[ChatMessage]:
        """Gibt die letzten N Nachrichten zurück."""
        return self._messages[-max_messages:]

    def get_context_string(self, max_messages: int = 6) -> str:
        """
        Gibt den Gesprächsverlauf als formatierten String zurück.
        Wird als Kontext für neue Anfragen verwendet.
        """
        messages = self.get_messages(max_messages)
        if not messages:
            return ""

        lines = []
        for msg in messages:
            prefix = "Nutzer" if msg.role == "user" else "Assistent"
            # Lange Nachrichten kürzen für den Kontext
            content = msg.content[:500] + "..." if len(msg.content) > 500 else msg.content
            lines.append(f"{prefix}: {content}")

        return "\n".join(lines)

    def clear(self) -> None:
        """Löscht den gesamten Gesprächsverlauf."""
        self._messages.clear()
        if os.path.exists(self._history_file):
            os.remove(self._history_file)

    def __len__(self) -> int:
        return len(self._messages)

    # ──────────────────────────────────────────
    # Disk-Persistenz
    # ──────────────────────────────────────────

    def _save_to_disk(self) -> None:
        """Speichert den Verlauf als JSON-Datei."""
        try:
            os.makedirs(MEMORY_DIR, exist_ok=True)
            data = [
                {"role": m.role, "content": m.content, "timestamp": m.timestamp}
                for m in self._messages
            ]
            with open(self._history_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass  # Disk-Fehler ignorieren (Memory-only Betrieb)

    def _load_from_disk(self) -> None:
        """Lädt einen gespeicherten Verlauf vom Disk (falls vorhanden)."""
        if not os.path.exists(self._history_file):
            return
        try:
            with open(self._history_file, encoding="utf-8") as f:
                data = json.load(f)
            self._messages = [
                ChatMessage(
                    role=m["role"],
                    content=m["content"],
                    timestamp=m.get("timestamp", ""),
                )
                for m in data
            ]
        except Exception:
            self._messages = []
