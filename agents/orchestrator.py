"""
agents/orchestrator.py – Der Hauptagent (Orchestrator)

Der Orchestrator ist das Herzstück des Systems:
1. Empfängt Aufgaben vom Nutzer
2. Analysiert und zerlegt Aufgaben (via TaskManager)
3. Verteilt Teilaufgaben an spezialisierte Unteragenten
4. Wartet auf ALLE Ergebnisse (parallel via asyncio)
5. Fasst alle Ergebnisse zusammen (via ResultAggregator)
6. Gibt die finale Antwort an den Nutzer zurück
"""

import asyncio
from typing import Callable, Optional
from agents.base_agent import BaseAgent
from agents.ui_ux_agent import UIUXAgent
from agents.frontend_agent import FrontendAgent
from agents.backend_agent import BackendAgent
from agents.database_agent import DatabaseAgent
from agents.devops_agent import DevOpsAgent
from agents.tester_agent import TesterAgent
from agents.documentation_agent import DocumentationAgent
from agents.security_agent import SecurityAgent
from agents.readme_agent import ReadmeAgent
from agents.github_agent import GitHubAgent
from core.task_manager import TaskManager
from core.result_aggregator import ResultAggregator
from core.message_bus import AgentResult, AgentTask
from memory.conversation_history import ConversationHistory
from config import ORCHESTRATOR_MODEL


# Typdefinition für Status-Callback (für Live-Updates in der CLI)
StatusCallback = Callable[[str], None]


class Orchestrator:
    """
    Hauptagent, der das gesamte KI-Softwareentwickler-Team koordiniert.
    
    Der Orchestrator kommuniziert mit dem Nutzer und delegiert Aufgaben
    an die richtigen Unteragenten basierend auf deren Expertise.
    """

    def __init__(self):
        # Alle verfügbaren Unteragenten registrieren
        self._agents: dict[str, BaseAgent] = {
            "ui_ux":         UIUXAgent(),
            "frontend":      FrontendAgent(),
            "backend":       BackendAgent(),
            "database":      DatabaseAgent(),
            "devops":        DevOpsAgent(),
            "tester":        TesterAgent(),
            "documentation": DocumentationAgent(),
            "security":      SecurityAgent(),
            "readme":        ReadmeAgent(),
            "github":        GitHubAgent(),
        }

        # Hilfssysteme
        self._task_manager = TaskManager(model_name=ORCHESTRATOR_MODEL)
        self._result_aggregator = ResultAggregator(model_name=ORCHESTRATOR_MODEL)
        self._history = ConversationHistory()

    # ──────────────────────────────────────────────────────
    # Öffentliche Schnittstelle
    # ──────────────────────────────────────────────────────

    async def process(
        self,
        user_request: str,
        status_callback: Optional[StatusCallback] = None,
    ) -> str:
        """
        Verarbeitet eine Nutzeranfrage komplett durch das Team.

        Args:
            user_request: Die Aufgabe/Anfrage des Nutzers
            status_callback: Optionale Funktion für Live-Status-Updates

        Returns:
            Die fertige, zusammengefasste Antwort des Teams
        """
        def notify(msg: str):
            if status_callback:
                status_callback(msg)

        # Schritt 1: Anfrage im Gesprächsverlauf speichern
        self._history.add_user_message(user_request)
        notify("🧠 Analysiere Aufgabe und erstelle Team-Plan...")

        # Schritt 2: Aufgabe zerlegen
        context = self._history.get_context_string(max_messages=6)
        task_summary, agent_tasks = await self._task_manager.decompose(
            user_request, conversation_context=context
        )

        if not agent_tasks:
            response = "⚠️ Ich konnte keine passenden Aufgaben für das Team ableiten. Bitte beschreibe die Aufgabe genauer."
            self._history.add_assistant_message(response)
            return response

        # Schritt 3: Team informieren
        agent_names = [
            self._agents[t.agent_id].name
            for t in agent_tasks
            if t.agent_id in self._agents
        ]
        notify(
            f"📋 Plan: {task_summary}\n"
            f"👥 Team: {', '.join(agent_names)}"
        )

        # Schritt 4: Alle Agenten PARALLEL starten
        notify(f"⚡ {len(agent_tasks)} Agenten arbeiten parallel...")
        results = await self._run_agents_parallel(agent_tasks, notify)

        # Schritt 5: Ergebnisse zusammenfassen
        notify("📝 Fasse alle Ergebnisse zusammen...")
        final_response = await self._result_aggregator.synthesize(
            user_request=user_request,
            task_summary=task_summary,
            results=results,
        )

        # Schritt 6: Antwort speichern und zurückgeben
        self._history.add_assistant_message(final_response)
        return final_response

    def get_team_info(self) -> str:
        """Gibt eine Übersicht über das verfügbare Team zurück."""
        lines = ["## 👥 Dein KI-Softwareentwickler-Team\n"]
        icons = {
            "ui_ux":         "🎨",
            "frontend":      "💻",
            "backend":       "⚙️ ",
            "database":      "🗄️ ",
            "devops":        "🚀",
            "tester":        "🧪",
            "documentation": "📚",
            "security":      "🔒",
        }
        for agent_id, agent in self._agents.items():
            icon = icons.get(agent_id, "🤖")
            lines.append(f"- {icon} **{agent.name}** (`{agent_id}`)")
        return "\n".join(lines)

    def get_history(self) -> ConversationHistory:
        """Gibt den Gesprächsverlauf zurück."""
        return self._history

    def clear_history(self) -> None:
        """Löscht den Gesprächsverlauf."""
        self._history.clear()

    # ──────────────────────────────────────────────────────
    # Interne Methoden
    # ──────────────────────────────────────────────────────

    async def _run_agents_parallel(
        self,
        agent_tasks: list[AgentTask],
        notify: Callable[[str], None],
    ) -> list[AgentResult]:
        """
        Führt alle Agenten-Aufgaben GLEICHZEITIG aus (asyncio.gather).
        Benachrichtigt per Callback wenn ein Agent fertig ist.
        """
        async def run_single(task: AgentTask) -> AgentResult:
            agent = self._agents.get(task.agent_id)
            if not agent:
                return AgentResult(
                    task_id=task.task_id,
                    agent_id=task.agent_id,
                    agent_name=task.agent_id,
                    success=False,
                    content="",
                    error=f"Unbekannter Agent: '{task.agent_id}'",
                )

            result = await agent.execute(task)

            # Status nach Abschluss melden
            if result.success:
                notify(f"  ✅ {agent.name} fertig ({result.duration_seconds:.1f}s)")
            else:
                notify(f"  ❌ {agent.name} Fehler: {result.error}")

            return result

        # Alle Agenten gleichzeitig starten und auf alle warten
        results = await asyncio.gather(
            *[run_single(task) for task in agent_tasks],
            return_exceptions=False,
        )

        return list(results)
