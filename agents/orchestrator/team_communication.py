"""
agents/orchestrator/team_communication.py – TeamCommunicationMixin: Team-Board und Fragen zwischen Agenten

Pro Lauf:
- `_start_team_board()` leert das Board des Projekts (core/team_board.py) und registriert, wie eine
  `ask_teammate`-Frage beantwortet wird.
- `_answer_teammate_question()` lässt den gefragten Kollegen in einem kurzen Nur-Lese-Aufruf
  antworten (keine Schreibrechte, kein eigenes `ask_teammate` → keine Frage-Kaskaden).
- `_stop_team_board()` meldet den Beantworter wieder ab.
"""

from __future__ import annotations

import logging
from pathlib import Path

from config import (
    ENABLE_ASK_TEAMMATE,
    ENABLE_TEAM_BOARD,
    TEAMMATE_ANSWER_TOOL_ITERATIONS,
)
from core import team_board
from core.message_bus import AgentTask

logger = logging.getLogger(__name__)

MAX_ANSWER_CHARS = 1200


class TeamCommunicationMixin:
    """Team-Board-Lebenszyklus und Beantwortung von Fragen zwischen Agenten."""

    def _start_team_board(self, project_dir: str, run_id: str) -> None:
        self._team_board_dir = None
        if not ENABLE_TEAM_BOARD:
            return
        try:
            team_board.begin_run(project_dir, run_id)
            self._team_board_dir = project_dir
            if ENABLE_ASK_TEAMMATE:
                team_board.register_teammate_responder(project_dir, self._answer_teammate_question)
        except Exception as e:  # noqa: BLE001 - Kommunikation ist Hilfe, kein Blocker für den Lauf
            logger.warning("Team-Board konnte nicht gestartet werden: %r", e)

    def _stop_team_board(self) -> None:
        project_dir = getattr(self, "_team_board_dir", None)
        if project_dir:
            team_board.unregister_teammate_responder(project_dir)
        self._team_board_dir = None

    def _team_member_ids(self) -> list[str]:
        return sorted(getattr(self, "_agents", {}).keys())

    async def _answer_teammate_question(self, asker: str, target: str, question: str, project_dir: str) -> str:
        agent = self._agents.get(target) or self._dept_leads.get(target)
        if agent is None:
            return f"Unbekannte Rolle '{target}'. Verfügbar: {', '.join(self._team_member_ids())}"
        task = AgentTask(
            task_id=f"teammate_answer_{target}_for_{asker}",
            agent_id=target,
            description=(
                f"Dein Teamkollege `{asker}` hat eine konkrete Frage an dich:\n\n{question}\n\n"
                "Antworte kurz (max. 150 Wörter) und präzise auf Basis des ECHTEN Projektstands - lies dafür "
                "bei Bedarf die relevanten Dateien. Nenne exakte Dateipfade, Symbolnamen, Routen, "
                "Feldnamen und Datentypen. Wenn etwas noch nicht existiert oder du es nicht weißt, sage das "
                "klar, statt zu raten. Keine Code-Blöcke über 15 Zeilen."
            ),
            project_dir=str(Path(project_dir)),
            allow_tools=True,
            tools_read_only=True,
            max_tool_iterations=TEAMMATE_ANSWER_TOOL_ITERATIONS,
        )
        result = await self._execute_and_log(agent, task)
        if not result.success:
            return f"`{target}` konnte nicht antworten: {result.error or 'unbekannter Fehler'}"
        return (result.content or "").strip()[:MAX_ANSWER_CHARS] or f"`{target}` hat keine Antwort geliefert."
