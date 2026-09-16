"""
core/message_bus.py – Gemeinsame Datenstrukturen der Agentenkommunikation

Definiert die beiden Datenklassen, über die Orchestrator und Unteragenten Aufgaben und
Ergebnisse austauschen: `AgentTask` (Auftrag hinein) und `AgentResult` (Ergebnis inklusive
Token-, Modell- und Fehlermetriken heraus).

Hinweis zum Namen: Eine echte Publish/Subscribe-Klasse (`MessageBus` mit asyncio-Queues)
existierte hier ursprünglich, wurde aber von keinem Modul je genutzt - die Kommunikation läuft
direkt über `agents/orchestrator/dispatch.py` und, für den Austausch zwischen Agenten, über
`core/team_board.py`. Sie wurde deshalb entfernt; der Modulname bleibt vorerst bestehen, weil
über 60 Module `from core.message_bus import AgentTask, AgentResult` importieren.
"""

from dataclasses import dataclass, field


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
    # eine ehrliche Teil-Zusammenfassung), aber agents/orchestrator/ behandelt einen solchen
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
    # Eingriffe des Agenten-Watchdogs (core/agent_watchdog.py) während dieser Aufgabe.
    watchdog_events: list[str] = field(default_factory=list)

