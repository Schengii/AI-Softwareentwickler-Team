# src/agents/models.py
"""Datentypen für die Agent‑Definitionen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """
    Repräsentiert eine einzelne KI‑Agent‑Definition.

    Attributes
    ----------
    name: str
        Eindeutiger Name des Agents (z. B. ``weather_bot``).
    workspace: str
        Arbeitsbereich / Namespace, in dem der Agent aktiv ist.
    ki_model: str
        Bezeichnung des zu nutzenden KI‑Modells (z. B. ``gpt‑4o``).
    """
    name: str
    workspace: str
    ki_model: str


# Optional: Hilfstyp für die Rückgabe mehrerer Agenten
AgentDefinitionList = List[AgentDefinition]
