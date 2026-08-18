"""
agents/orchestrator.py – Der Hauptagent (Orchestrator)

Der Orchestrator koordiniert das gesamte 17-köpfige KI-Softwareentwickler-Team.

WORKFLOW (4 Phasen):
  Phase 1: Business Analyst  → Anforderungen klären (optional)
  Phase 2: Software-Architekt → Systemarchitektur entwerfen (optional)
  Phase 3: Alle anderen Agenten parallel (immer)
  Phase 4: Code-Reviewer → Qualitätskontrolle (optional)
  Synthese: Orchestrator fasst alles zusammen
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
from agents.architect_agent import ArchitectAgent
from agents.code_reviewer_agent import CodeReviewerAgent
from agents.business_analyst_agent import BusinessAnalystAgent
from agents.mobile_agent import MobileAgent
from agents.ml_agent import MLAgent
from agents.performance_agent import PerformanceAgent
from agents.i18n_agent import I18nAgent

from core.task_manager import TaskManager
from core.result_aggregator import ResultAggregator
from core.message_bus import AgentResult, AgentTask
from memory.conversation_history import ConversationHistory
from config import ORCHESTRATOR_MODEL

# Typdefinition für Status-Callback (für Live-Updates in der CLI)
StatusCallback = Callable[[str], None]

# Phasen-Agenten: Diese werden sequentiell ausgeführt, nicht parallel
PHASE_1_AGENTS = {"business_analyst"}          # Vor allem anderen
PHASE_2_AGENTS = {"architect"}                  # Nach BA, vor Implementierung
PHASE_4_AGENTS = {"code_reviewer"}              # Nach allen anderen

# Code-produzierende Agenten (lösen Phase 2+4 aus)
CODE_AGENTS = {
    "frontend", "backend", "database", "mobile", "ml",
    "devops", "tester", "performance", "i18n"
}


class Orchestrator:
    """
    Hauptagent, der das gesamte KI-Softwareentwickler-Team (17 Agenten) koordiniert.

    Ausführungs-Phasen:
    1. Business Analyst  → klärt Anforderungen
    2. Software-Architekt → entwirft Systemarchitektur (Blueprint für alle anderen)
    3. Alle anderen       → arbeiten parallel mit Architektur-Kontext
    4. Code-Reviewer      → prüft alle Ergebnisse
    5. Synthese           → Orchestrator fasst alles zusammen
    """

    def __init__(self):
        # Alle 17 Unteragenten registrieren
        self._agents: dict[str, BaseAgent] = {
            # Kern-Entwicklungsteam
            "ui_ux":             UIUXAgent(),
            "frontend":          FrontendAgent(),
            "backend":           BackendAgent(),
            "database":          DatabaseAgent(),
            "devops":            DevOpsAgent(),
            "tester":            TesterAgent(),
            "documentation":     DocumentationAgent(),
            "security":          SecurityAgent(),
            # Neue Agenten (v1.1)
            "mobile":            MobileAgent(),
            "ml":                MLAgent(),
            "performance":       PerformanceAgent(),
            "i18n":              I18nAgent(),
            # Phasen-Agenten (sequentiell)
            "business_analyst":  BusinessAnalystAgent(),
            "architect":         ArchitectAgent(),
            "code_reviewer":     CodeReviewerAgent(),
            # Utility-Agenten
            "readme":            ReadmeAgent(),
            "github":            GitHubAgent(),
        }

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
        Verarbeitet eine Nutzeranfrage komplett durch das Team (4-Phasen-Workflow).
        """
        def notify(msg: str):
            if status_callback:
                status_callback(msg)

        # Anfrage im Verlauf speichern
        self._history.add_user_message(user_request)
        notify("🧠 Analysiere Aufgabe und erstelle Team-Plan...")

        # Aufgabe zerlegen
        context = self._history.get_context_string(max_messages=6)
        task_summary, agent_tasks = await self._task_manager.decompose(
            user_request, conversation_context=context
        )

        if not agent_tasks:
            response = (
                "⚠️ Ich konnte keine passenden Aufgaben für das Team ableiten. "
                "Bitte beschreibe die Aufgabe genauer."
            )
            self._history.add_assistant_message(response)
            return response

        # Team-Plan ausgeben
        agent_names = [
            self._agents[t.agent_id].name
            for t in agent_tasks
            if t.agent_id in self._agents
        ]
        notify(f"📋 Plan: {task_summary}")
        notify(f"👥 Team ({len(agent_names)}): {', '.join(agent_names)}")

        # 4-Phasen-Ausführung
        results = await self._run_phased_execution(
            user_request=user_request,
            agent_tasks=agent_tasks,
            notify=notify,
        )

        # Synthese
        notify("📝 Fasse alle Ergebnisse zusammen...")
        final_response = await self._result_aggregator.synthesize(
            user_request=user_request,
            task_summary=task_summary,
            results=results,
        )

        self._history.add_assistant_message(final_response)
        return final_response

    def get_team_info(self) -> str:
        """Gibt eine Übersicht über das verfügbare Team zurück."""
        sections = {
            "🔵 Phasen-Agenten (sequentiell)": {
                "business_analyst", "architect", "code_reviewer"
            },
            "🟢 Implementierungs-Agenten (parallel)": {
                "ui_ux", "frontend", "backend", "database",
                "mobile", "ml", "performance", "i18n"
            },
            "🟡 Infrastruktur & Qualität (parallel)": {
                "devops", "tester", "documentation", "security"
            },
            "⚪ Utility-Agenten": {
                "readme", "github"
            },
        }
        icons = {
            "business_analyst": "📋", "architect": "🏛️", "code_reviewer": "🔍",
            "ui_ux": "🎨", "frontend": "💻", "backend": "⚙️ ",
            "database": "🗄️ ", "mobile": "📱", "ml": "🤖",
            "performance": "⚡", "i18n": "🌍",
            "devops": "🚀", "tester": "🧪", "documentation": "📚",
            "security": "🔒", "readme": "📝", "github": "🔀",
        }
        lines = [f"## 👥 Dein KI-Team ({len(self._agents)} Spezialisten)\n"]
        for section, ids in sections.items():
            lines.append(f"\n### {section}")
            for aid, agent in self._agents.items():
                if aid in ids:
                    icon = icons.get(aid, "🤖")
                    lines.append(f"- {icon} **{agent.name}** (`{aid}`)")
        return "\n".join(lines)

    def get_history(self) -> ConversationHistory:
        return self._history

    def clear_history(self) -> None:
        self._history.clear()

    # ──────────────────────────────────────────────────────
    # 4-Phasen-Orchestrierung
    # ──────────────────────────────────────────────────────

    async def _run_phased_execution(
        self,
        user_request: str,
        agent_tasks: list[AgentTask],
        notify: Callable[[str], None],
    ) -> list[AgentResult]:
        """
        Führt alle Agenten in 4 Phasen aus:

        Phase 1: Business Analyst (sequentiell, optional)
        Phase 2: Software-Architekt (sequentiell, optional)
        Phase 3: Alle anderen parallel
        Phase 4: Code-Reviewer (sequentiell, optional)
        """
        all_results: list[AgentResult] = []
        requirements_context = ""
        architecture_context = ""

        # Aufgaben nach Phase aufteilen
        phase1_tasks = [t for t in agent_tasks if t.agent_id in PHASE_1_AGENTS]
        phase2_tasks = [t for t in agent_tasks if t.agent_id in PHASE_2_AGENTS]
        phase4_tasks = [t for t in agent_tasks if t.agent_id in PHASE_4_AGENTS]
        parallel_tasks = [
            t for t in agent_tasks
            if t.agent_id not in PHASE_1_AGENTS
            and t.agent_id not in PHASE_2_AGENTS
            and t.agent_id not in PHASE_4_AGENTS
        ]

        # ── Phase 1: Business Analyst ──────────────────────
        if phase1_tasks:
            notify("📋 Phase 1/4: Business Analyst klärt Anforderungen...")
            for task in phase1_tasks:
                result = await self._run_single_agent(task, notify)
                all_results.append(result)
                if result.success:
                    requirements_context = result.content

        # ── Phase 2: Software-Architekt ────────────────────
        if phase2_tasks:
            notify("🏛️  Phase 2/4: Software-Architekt entwirft Architektur...")
            for task in phase2_tasks:
                # Anforderungskontext an Architekten übergeben
                if requirements_context:
                    task.context += (
                        f"\n\n## Anforderungsanalyse (Business Analyst)\n"
                        f"{requirements_context[:3000]}"
                    )
                result = await self._run_single_agent(task, notify)
                all_results.append(result)
                if result.success:
                    architecture_context = result.content

        # ── Phase 3: Alle Agenten parallel ────────────────
        if parallel_tasks:
            count = len(parallel_tasks)
            notify(f"⚡ Phase 3/4: {count} Agenten arbeiten parallel...")

            # Architektur-Blueprint an alle Parallel-Agenten weitergeben
            if architecture_context:
                blueprint_summary = architecture_context[:2500]
                for task in parallel_tasks:
                    task.context += (
                        f"\n\n## Systemarchitektur-Blueprint (Software-Architekt)\n"
                        f"Halte dich strikt an diese Architektur:\n"
                        f"{blueprint_summary}"
                    )
            elif requirements_context:
                for task in parallel_tasks:
                    task.context += (
                        f"\n\n## Anforderungsanalyse\n{requirements_context[:2000]}"
                    )

            parallel_results = await self._run_agents_parallel(parallel_tasks, notify)
            all_results.extend(parallel_results)

        # ── Phase 4: Code-Reviewer ─────────────────────────
        if phase4_tasks:
            notify("🔍 Phase 4/4: Code-Reviewer prüft alle Ergebnisse...")
            # Alle bisherigen Ergebnisse als Kontext für den Reviewer
            code_context = self._format_results_for_review(all_results)
            for task in phase4_tasks:
                task.description += (
                    f"\n\nBitte reviewe die folgenden Ergebnisse des Teams:\n"
                    f"{code_context[:5000]}"
                )
                result = await self._run_single_agent(task, notify)
                all_results.append(result)

        return all_results

    async def _run_single_agent(
        self,
        task: AgentTask,
        notify: Callable[[str], None],
    ) -> AgentResult:
        """Führt einen einzelnen Agenten aus (für sequentielle Phasen)."""
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
        if result.success:
            notify(f"  ✅ {agent.name} fertig ({result.duration_seconds:.1f}s)")
        else:
            notify(f"  ❌ {agent.name} Fehler: {result.error}")
        return result

    async def _run_agents_parallel(
        self,
        agent_tasks: list[AgentTask],
        notify: Callable[[str], None],
    ) -> list[AgentResult]:
        """Führt alle Agenten-Aufgaben GLEICHZEITIG aus (asyncio.gather)."""
        async def run_single(task: AgentTask) -> AgentResult:
            return await self._run_single_agent(task, notify)

        results = await asyncio.gather(
            *[run_single(task) for task in agent_tasks],
            return_exceptions=False,
        )
        return list(results)

    def _format_results_for_review(self, results: list[AgentResult]) -> str:
        """Formatiert alle Ergebnisse für den Code-Reviewer."""
        successful = [r for r in results if r.success]
        sections = []
        for result in successful:
            sections.append(
                f"### {result.agent_name}\n\n{result.content[:1500]}"
            )
        return "\n\n---\n\n".join(sections)
