"""
core/message_bus.py – Interner Nachrichtenbus für die Agentenkommunikation

Ermöglicht asynchrone, entkoppelte Kommunikation zwischen Agenten und Metriken-Tracking.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class MessageType(Enum):
    TASK_ASSIGNED    = "task_assigned"      # Orchestrator → Unteragent
    TASK_COMPLETED   = "task_completed"     # Unteragent → Orchestrator
    TASK_FAILED      = "task_failed"        # Unteragent → Orchestrator (Fehler)
    STATUS_UPDATE    = "status_update"      # Statusmeldung
    LOG              = "log"                # Protokoll-Eintrag


@dataclass
class Message:
    """Eine Nachricht im System."""
    type: MessageType
    sender: str                          # Agent-ID des Absenders
    recipient: str                       # Agent-ID des Empfängers
    content: Any                         # Nachrichteninhalt
    task_id: str | None = None        # Zugehörige Task-ID
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)


@dataclass
class AgentTask:
    """Eine Aufgabe, die an einen Agenten vergeben wird."""
    task_id: str
    agent_id: str
    description: str                     # Aufgabenbeschreibung für den Agenten
    context: str = ""                    # Zusätzlicher Kontext (z.B. Nutzer-Anfrage)
    priority: int = 1                    # 1 = hoch, 2 = mittel, 3 = niedrig
    project_dir: str | None = None    # Projektverzeichnis für den agentischen Werkzeug-Loop (None = kein Datei-/Tool-Zugriff)
    allow_tools: bool = True             # Ob der Agent (bei gesetztem project_dir) Werkzeuge nutzen darf
    tools_read_only: bool = False        # True = nur read_file/list_files/search_code/run_tests (kein write_file/edit_file/run_command)
    max_tool_iterations: int | None = None  # Überschreibt config.MAX_AGENT_TOOL_ITERATIONS für diese Aufgabe


@dataclass
class AgentResult:
    """Das Ergebnis einer Agenten-Aufgabe inklusive Token- und Modellmetriken."""
    task_id: str
    agent_id: str
    agent_name: str
    success: bool
    content: str                         # Das eigentliche Ergebnis
    error: str | None = None          # Fehlermeldung falls success=False
    duration_seconds: float = 0.0        # Wie lange die Aufgabe dauerte
    model_used: str = ""                 # Welches KI-Modell genutzt wurde
    prompt_tokens: int = 0               # Verbrauchte Prompt-Tokens
    completion_tokens: int = 0           # Verbrauchte Completion-Tokens
    total_tokens: int = 0                # Gesamt-Tokens für diese Teilaufgabe
    files_written: list[str] = field(default_factory=list)  # Relative Pfade, die der Agent selbst via Tools geschrieben/geändert hat
    tool_calls_count: int = 0            # Anzahl der Werkzeug-Aufrufe während der Ausführung
    # Realer Fund: Rückfragen (core/task_manager.py needs_clarification) passierten bisher NUR
    # VOR dem Start, wenn die Gesamtaufgabe zu vage war - sobald Agenten liefen, gab es kein
    # "Moment, das ist wirklich mehrdeutig" mehr, nur Weiterarbeiten mit einer geratenen
    # Annahme. Das `ask_human_for_clarification`-Werkzeug (core/agent_toolbox.py) füllt diese
    # beiden Felder, wenn ein Agent MITTEN in der Aufgabe auf eine echte, für die Aufgabe
    # entscheidende Unklarheit trifft - success bleibt dabei True (der Agent liefert trotzdem
    # eine ehrliche Teil-Zusammenfassung), aber agents/orchestrator.py behandelt einen solchen
    # Lauf NICHT als abgeschlossen "Fertig!".
    needs_human_input: bool = False
    clarification_questions: list[str] = field(default_factory=list)
    # Fehler-Klassifikation (core/provider_exhaustion.py.classify_failure), gesetzt von
    # agents/base_agent.py bei success=False. Trennt echte, dem Agenten zurechenbare Fehler
    # ("agent_error"/"timeout") von reinen Infrastruktur-Ausfällen ("provider_exhausted"/
    # "provider_unavailable"). Realer Fund: ohne diese Trennung wurden 160 Kontingent-Ausfälle
    # als Qualitätsmängel der Agenten gewertet und flossen in die Selbstoptimierung ein.
    failure_class: str = ""
    # Zeichen, die core/context_compaction.py im Werkzeug-Loop dieser Aufgabe eingespart hat.
    context_chars_compacted: int = 0


class MessageBus:
    """
    Zentraler Nachrichtenbus für das Agentensystem.
    Verwaltet die Kommunikation zwischen Orchestrator und Unteragenten.
    """

    def __init__(self):
        self._log: list[Message] = []
        self._listeners: list[asyncio.Queue] = []

    def send(self, message: Message) -> None:
        """Sendet eine Nachricht und benachrichtigt alle Listener."""
        self._log.append(message)
        for queue in self._listeners:
            queue.put_nowait(message)

    def subscribe(self) -> asyncio.Queue:
        """Abonniert den Nachrichtenbus und gibt eine Queue zurück."""
        queue: asyncio.Queue = asyncio.Queue()
        self._listeners.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Kündigt ein Abonnement."""
        if queue in self._listeners:
            self._listeners.remove(queue)

    def get_log(self) -> list[Message]:
        """Gibt alle Nachrichten zurück."""
        return list(self._log)

    def clear_log(self) -> None:
        """Löscht das Nachrichtenprotokoll."""
        self._log.clear()


# Globale Singleton-Instanz
message_bus = MessageBus()
