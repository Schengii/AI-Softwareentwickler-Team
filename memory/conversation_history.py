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

# ki_team_verbesserungsanalyse.md, Teil 5.5: `memory/history_default.json` wuchs auf 13,2 MB an,
# weil hier bisher KEINE Obergrenze existierte - jede einzelne Nutzer-/Assistenten-Nachricht
# jeder je geführten Sitzung wurde für immer angehängt, und JEDE add_*_message()-Aufruf schrieb
# die komplette (immer länger werdende) Liste neu auf die Platte. Dieselbe MAX_*_KEPT-Rotation
# wie memory/run_history.py (MAX_RUNS_KEPT=200) - `get_context_string()` liest ohnehin nur die
# letzten paar Nachrichten für den Prompt-Kontext, ältere Nachrichten hatten also schon vorher
# keinen funktionalen Nutzen mehr, nur ungenutztes Gewicht auf der Platte.
MAX_MESSAGES_KEPT = 200

# P6-3 (ROADMAP_TEMP.md): die 200-Nachrichten-Obergrenze allein begrenzte die Nachrichten-
# ANZAHL, nicht ihre GRÖSSE - memory/history_default.json lag bei 195 Nachrichten trotzdem bei
# 2 MB, weil eine assistant-Nachricht der komplette Abschlussbericht eines Laufs ist (bis zu
# ~50.000 Zeichen je Nachricht, real gemessen). Weder get_context_string() (kürzt auf 500
# Zeichen je Nachricht für den Prompt-Kontext) noch interface/cli.py._print_history() (kürzt
# auf 100 Zeichen für die Konsole) lesen je mehr als das - der volle gespeicherte Text hatte
# also bereits vorher keinen funktionalen Nutzen, nur ungenutztes Gewicht auf der Platte.
MAX_MESSAGE_CONTENT_CHARS = 4000


def _truncate_for_storage(content: str, max_chars: int = MAX_MESSAGE_CONTENT_CHARS) -> str:
    """Kürzt auf höchstens `max_chars`, an einer Zeilengrenze statt mitten im Wort - dasselbe
    Prinzip wie core/project_status.py.truncate_on_line_boundary()."""
    if len(content) <= max_chars:
        return content
    marker = "\n… (gekürzt für die Verlaufs-Historie)"
    budget = max(0, max_chars - len(marker))
    cut = content.rfind("\n", 0, budget)
    head = content[:cut] if cut > 0 else content[:budget]
    return head.rstrip() + marker


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
        self._messages.append(ChatMessage(role="user", content=_truncate_for_storage(content)))
        self._messages = self._messages[-MAX_MESSAGES_KEPT:]
        self._save_to_disk()

    def add_assistant_message(self, content: str) -> None:
        """Fügt eine Assistenten-Nachricht hinzu."""
        self._messages.append(ChatMessage(role="assistant", content=_truncate_for_storage(content)))
        self._messages = self._messages[-MAX_MESSAGES_KEPT:]
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
            # Kompaktiert eine bereits vor MAX_MESSAGES_KEPT gewachsene Datei EINMALIG beim
            # nächsten Laden, statt erst auf die nächste neue Nachricht zu warten - eine bereits
            # 13-MB-große Datei würde sonst noch beliebig lange geladen (und jedes Mal neu
            # geparst) werden, bevor die Obergrenze in add_*_message() überhaupt greift.
            needs_resave = len(self._messages) > MAX_MESSAGES_KEPT
            if needs_resave:
                self._messages = self._messages[-MAX_MESSAGES_KEPT:]
            # P6-3: dieselbe einmalige Nachverdichtung für bereits VOR MAX_MESSAGE_CONTENT_CHARS
            # gespeicherte, überlange Nachrichten (z.B. eine 2 MB große Altdatei aus 195
            # Nachrichten mit bis zu 50.000 Zeichen je Nachricht) - sonst bliebe sie bis zu
            # MAX_MESSAGES_KEPT weitere Nachrichten lang übergroß.
            for m in self._messages:
                truncated = _truncate_for_storage(m.content)
                if truncated != m.content:
                    m.content = truncated
                    needs_resave = True
            if needs_resave:
                self._save_to_disk()
        except Exception:
            self._messages = []
