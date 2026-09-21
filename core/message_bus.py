"""
core/message_bus.py – Alias für core/agent_contracts.py (P6-6, ROADMAP_TEMP.md)

Eine echte Publish/Subscribe-Klasse (`MessageBus` mit asyncio-Queues) existierte hier
ursprünglich, wurde aber von keinem Modul je genutzt - die Kommunikation läuft direkt über
`agents/orchestrator/dispatch.py` und, für den Austausch zwischen Agenten, über
`core/team_board.py`. Übrig blieben nur zwei Dataclasses (`AgentTask`, `AgentResult`), für die
der Modulname irreführend war - sie leben jetzt in `core/agent_contracts.py`, ihrem eigentlichen
Inhalt entsprechend benannt. Dieses Modul bleibt als reiner Re-Export-Alias bestehen, weil über
60 Module `from core.message_bus import AgentTask, AgentResult` importieren - neue Importe
verwenden bitte `core.agent_contracts` direkt.
"""

from core.agent_contracts import AgentResult, AgentTask

__all__ = ["AgentResult", "AgentTask"]
