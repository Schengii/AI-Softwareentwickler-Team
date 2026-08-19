"""
agents/base_agent.py – Abstrakte Basisklasse für alle Unteragenten

Jeder spezialisierte Agent erbt von dieser Klasse und misst präzise
seinen Tokenverbrauch und seine Laufzeit.
"""

import time
from abc import ABC, abstractmethod
from typing import Optional
from core.llm_factory import LLMFactory, GeminiClient
from core.message_bus import AgentTask, AgentResult


class BaseAgent(ABC):
    """
    Abstrakte Basisklasse für alle Unteragenten des KI-Teams.
    """

    def __init__(self, agent_id: str, name: str, model_name: Optional[str] = None):
        self.agent_id = agent_id
        self.name = name
        self._llm: GeminiClient = LLMFactory.create_for_agent(agent_id) if not model_name \
            else LLMFactory.create_gemini(model_name)

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Der spezialisierte System-Prompt für diesen Agenten."""
        ...

    async def execute(self, task: AgentTask) -> AgentResult:
        """
        Führt die zugewiesene Aufgabe aus und gibt das Ergebnis samt Tokenmetriken zurück.
        """
        start_time = time.monotonic()

        try:
            prompt = self._build_prompt(task)
            response = await self._llm.generate_with_usage(prompt, self.system_prompt)
            duration = time.monotonic() - start_time

            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                agent_name=self.name,
                success=True,
                content=response.text,
                duration_seconds=duration,
                model_used=response.model_name,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                total_tokens=response.total_tokens,
            )

        except Exception as e:
            duration = time.monotonic() - start_time
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                agent_name=self.name,
                success=False,
                content="",
                error=str(e),
                duration_seconds=duration,
                model_used=self._llm.model_name,
            )

    def _build_prompt(self, task: AgentTask) -> str:
        """Baut den finalen Prompt token-effizient zusammen."""
        prompt_parts = [f"**DEINE AUFGABE:**\n{task.description}"]

        if task.context:
            prompt_parts.insert(0, f"**PROJEKT-KONTEXT:**\n{task.context}\n")

        return "\n\n".join(prompt_parts)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id='{self.agent_id}', name='{self.name}', model='{self._llm.model_name}')"
