"""
agents/orchestrator.py – Der Hauptagent (Orchestrator)

Koordiniert das 30-köpfige KI-Softwareentwickler-Team mit mehrphasigem Workflow,
Live-Statusmeldungen pro Agent und Phase, iterativer Review-Schleife,
automatischer Projekt-Hygiene, Workspace-Dateisystem und abschließender Retrospektive.
"""

import asyncio
import time
from typing import Callable, Optional

from agents.base_agent import BaseAgent
from agents.team_lead_agent import TeamLeadAgent
from agents.product_owner_agent import ProductOwnerAgent
from agents.business_analyst_agent import BusinessAnalystAgent
from agents.web_research_agent import WebResearchAgent
from agents.architect_agent import ArchitectAgent
from agents.finops_agent import FinOpsAgent
from agents.frontend_agent import FrontendAgent
from agents.backend_agent import BackendAgent
from agents.database_agent import DatabaseAgent
from agents.api_integration_agent import ApiIntegrationAgent
from agents.data_engineer_agent import DataEngineerAgent
from agents.mobile_agent import MobileAgent
from agents.ml_agent import MLAgent
from agents.performance_agent import PerformanceAgent
from agents.image_generator_agent import ImageGeneratorAgent
from agents.copywriter_agent import CopywriterAgent
from agents.ui_ux_agent import UIUXAgent
from agents.i18n_agent import I18nAgent
from agents.documentation_agent import DocumentationAgent
from agents.devops_agent import DevOpsAgent
from agents.tester_agent import TesterAgent
from agents.security_agent import SecurityAgent
from agents.code_reviewer_agent import CodeReviewerAgent
from agents.refactoring_agent import RefactoringAgent
from agents.compliance_agent import ComplianceAgent
from agents.project_cleaner_agent import ProjectCleanerAgent
from agents.agent_trainer_agent import AgentTrainerAgent
from agents.retrospective_agent import RetrospectiveAgent
from agents.readme_agent import ReadmeAgent
from agents.github_agent import GitHubAgent

from core.task_manager import TaskManager
from core.result_aggregator import ResultAggregator
from core.message_bus import AgentResult, AgentTask
from core.workspace import WorkspaceManager
from memory.conversation_history import ConversationHistory
from config import ORCHESTRATOR_MODEL, MAX_REVIEW_ITERATIONS, AUTO_SAVE_WORKSPACE

StatusCallback = Callable[[str], None]

# Phasen-Einteilung der Agenten
PHASE_1_AGENTS = {"team_lead", "product_owner", "business_analyst", "web_research"}
PHASE_2_AGENTS = {"architect", "finops"}
PHASE_4_AGENTS = {"code_reviewer", "refactoring", "compliance", "project_cleaner", "agent_trainer"}

CODE_PRODUCING_AGENTS = {
    "frontend", "backend", "database", "api_integration",
    "data_engineer", "mobile", "ml", "devops", "tester", "performance", "i18n",
    "image_generator", "copywriter"
}


class Orchestrator:
    """
    Hauptagent, der das gesamte 30-köpfige KI-Entwickler-Team koordiniert.
    """

    def __init__(self):
        # Alle 30 Unteragenten registrieren
        self._agents: dict[str, BaseAgent] = {
            # Phase 1: Führung, Planung & Recherche
            "team_lead":         TeamLeadAgent(),
            "product_owner":     ProductOwnerAgent(),
            "business_analyst":  BusinessAnalystAgent(),
            "web_research":      WebResearchAgent(),

            # Phase 2: Architektur & FinOps
            "architect":         ArchitectAgent(),
            "finops":            FinOpsAgent(),

            # Phase 3: Kern-Entwicklung & Media/Design
            "frontend":          FrontendAgent(),
            "backend":           BackendAgent(),
            "database":          DatabaseAgent(),
            "api_integration":   ApiIntegrationAgent(),
            "data_engineer":     DataEngineerAgent(),
            "mobile":            MobileAgent(),
            "ml":                MLAgent(),
            "performance":       PerformanceAgent(),
            "image_generator":   ImageGeneratorAgent(),
            "copywriter":        CopywriterAgent(),
            "ui_ux":             UIUXAgent(),
            "i18n":              I18nAgent(),
            "documentation":     DocumentationAgent(),

            # Phase 3: Infrastruktur & QA
            "devops":            DevOpsAgent(),
            "tester":            TesterAgent(),
            "security":          SecurityAgent(),

            # Phase 4: Review, Refactoring, Compliance & Hygiene
            "code_reviewer":     CodeReviewerAgent(),
            "refactoring":       RefactoringAgent(),
            "compliance":        ComplianceAgent(),
            "project_cleaner":   ProjectCleanerAgent(),
            "agent_trainer":     AgentTrainerAgent(),

            # Abschluss & Utilities
            "retrospective":     RetrospectiveAgent(),
            "readme":            ReadmeAgent(),
            "github":            GitHubAgent(),
        }

        self._task_manager = TaskManager(model_name=ORCHESTRATOR_MODEL)
        self._result_aggregator = ResultAggregator(model_name=ORCHESTRATOR_MODEL)
        self._history = ConversationHistory()
        self._workspace = WorkspaceManager()

    async def process(
        self,
        user_request: str,
        status_callback: Optional[StatusCallback] = None,
    ) -> str:
        overall_start_time = time.monotonic()

        def notify(msg: str):
            if status_callback:
                status_callback(msg)

        notify("⚡ [bold cyan]Phase 0/5:[/bold cyan] KI-Team aktiviert: Analysiere und plane Aufgabenstellung...")
        self._history.add_user_message(user_request)

        context = self._history.get_context_string(max_messages=4)
        task_summary, project_slug, agent_tasks = await self._task_manager.decompose(
            user_request, conversation_context=context
        )

        if not agent_tasks:
            response = (
                "⚠️ Ich konnte keine passenden Aufgaben für das Team ableiten. "
                "Bitte beschreibe die Aufgabe genauer."
            )
            self._history.add_assistant_message(response)
            return response

        agent_names = [self._agents[t.agent_id].name for t in agent_tasks if t.agent_id in self._agents]
        notify(f"📋 [bold white]Plan:[/bold white] {task_summary}")
        notify(f"👥 [bold white]Eingesetzte Spezialisten ({len(agent_names)}):[/bold white] {', '.join(agent_names)}")

        # Phasen-Ausführung mit Live-Status pro Agent
        results = await self._run_phased_execution(
            user_request=user_request,
            agent_tasks=agent_tasks,
            project_slug=project_slug,
            notify=notify,
        )

        # Workspace Dateispeicherung
        saved_files_count = 0
        if AUTO_SAVE_WORKSPACE:
            for res in results:
                if res.success and res.content:
                    files = self._workspace.parse_and_save_files(
                        project_name=project_slug,
                        text_content=res.content,
                        agent_name=res.agent_name,
                    )
                    saved_files_count += len(files)

            if saved_files_count > 0:
                notify(f"💾 [green]Workspace:[/green] {saved_files_count} Projektdateien in `workspace/{project_slug}/` gespeichert.")

        # Synthese
        notify("🔍 [bold cyan]Phase 5/5:[/bold cyan] Hauptagent (Orchestrator) führt Gesamtergebnis zusammen...")
        final_solution, synth_tokens = await self._result_aggregator.synthesize(
            user_request=user_request,
            task_summary=task_summary,
            results=results,
        )

        # Retrospektive
        notify("📊 [bold cyan]Abschluss:[/bold cyan] Retrospektive-Agent erstellt Lessons Learned & Kennzahlen...")
        total_duration = time.monotonic() - overall_start_time

        retro_result = await self._run_retrospective(
            user_request=user_request,
            results=results,
            total_duration=total_duration,
        )

        stats_table = self._build_metrics_summary(
            results=results,
            synth_tokens=synth_tokens,
            total_duration=total_duration,
            project_slug=project_slug,
        )

        final_output = (
            f"{final_solution}\n\n"
            f"---\n\n"
            f"{retro_result.content if retro_result else ''}\n\n"
            f"---\n\n"
            f"{stats_table}"
        )

        self._history.add_assistant_message(final_output)
        notify("✅ [bold green]Fertig![/bold green] Alle Agenten haben ihre Arbeit erfolgreich beendet.")
        return final_output

    def get_team_info(self) -> str:
        """Gibt eine Übersicht über das gesamte 30-köpfige Team zurück."""
        sections = {
            "🔵 Phase 1: Führung, Planung & Recherche": {
                "team_lead", "product_owner", "business_analyst", "web_research"
            },
            "🟣 Phase 2: Architektur & FinOps": {
                "architect", "finops"
            },
            "🟢 Phase 3: Entwicklung, Media & Design (parallel)": {
                "frontend", "backend", "database", "api_integration", "data_engineer",
                "mobile", "ml", "performance", "image_generator", "copywriter", "ui_ux", "i18n"
            },
            "🟡 Phase 3: Infrastruktur & Qualität (parallel)": {
                "devops", "tester", "documentation", "security"
            },
            "🔴 Phase 4: Review, Refactoring, Compliance & Hygiene": {
                "code_reviewer", "refactoring", "compliance", "project_cleaner", "agent_trainer"
            },
            "⚪ Abschluss & Utility": {
                "retrospective", "readme", "github"
            },
        }
        icons = {
            "team_lead": "👔", "product_owner": "🎯", "business_analyst": "📋", "web_research": "🌐",
            "architect": "🏛️", "finops": "💰", "frontend": "💻", "backend": "⚙️", "database": "🗄️",
            "api_integration": "🔌", "data_engineer": "🌊", "mobile": "📱", "ml": "🤖",
            "performance": "⚡", "image_generator": "🎨", "copywriter": "✍️", "ui_ux": "📐",
            "i18n": "🌍", "devops": "🚀", "tester": "🧪", "documentation": "📚", "security": "🔒",
            "code_reviewer": "🔍", "refactoring": "🧹", "compliance": "⚖️", "project_cleaner": "🧽",
            "agent_trainer": "🎓", "retrospective": "📊", "readme": "📝", "github": "🔀",
        }
        lines = [f"## 👥 Dein KI-Team ({len(self._agents)} Spezialisten)\n"]
        for section, ids in sections.items():
            lines.append(f"\n### {section}")
            for aid, agent in self._agents.items():
                if aid in ids:
                    icon = icons.get(aid, "🤖")
                    model_badge = getattr(agent._llm, "model_name", "standard")
                    lines.append(f"- {icon} **{agent.name}** (`{aid}`) → *Modell: {model_badge}*")
        return "\n".join(lines)

    def get_history(self) -> ConversationHistory:
        return self._history

    def clear_history(self) -> None:
        self._history.clear()

    def get_workspace_manager(self) -> WorkspaceManager:
        return self._workspace

    async def _run_phased_execution(
        self,
        user_request: str,
        agent_tasks: list[AgentTask],
        project_slug: str,
        notify: Callable[[str], None],
    ) -> list[AgentResult]:
        all_results: list[AgentResult] = []
        phase1_context = ""
        phase2_context = ""

        phase1_tasks = [t for t in agent_tasks if t.agent_id in PHASE_1_AGENTS]
        phase2_tasks = [t for t in agent_tasks if t.agent_id in PHASE_2_AGENTS]
        phase4_tasks = [t for t in agent_tasks if t.agent_id in PHASE_4_AGENTS]
        parallel_tasks = [
            t for t in agent_tasks
            if t.agent_id not in PHASE_1_AGENTS
            and t.agent_id not in PHASE_2_AGENTS
            and t.agent_id not in PHASE_4_AGENTS
        ]

        # ── Phase 1: Führung, Planung & Recherche ──
        if phase1_tasks:
            notify(f"📋 [bold cyan]Phase 1/5: Planung & Führung[/bold cyan] ({len(phase1_tasks)} Agenten)...")
            for task in phase1_tasks:
                agent_name = self._agents[task.agent_id].name if task.agent_id in self._agents else task.agent_id
                notify(f"  ▶️ [yellow]Arbeitet:[/yellow] {agent_name}...")
                start_t = time.monotonic()
                result = await self._run_single_agent(task)
                dur = time.monotonic() - start_t
                all_results.append(result)
                status_ico = "✅ [green]Fertig[/green]" if result.success else "❌ [red]Fehler[/red]"
                notify(f"  {status_ico}: {agent_name} ({dur:.1f}s)")
                if result.success:
                    phase1_context += f"\n\n## {result.agent_name}\n{result.content[:2000]}"

        # ── Phase 2: Architektur & FinOps ──
        if phase2_tasks:
            notify(f"🏛️  [bold cyan]Phase 2/5: Architektur & FinOps[/bold cyan] ({len(phase2_tasks)} Agenten)...")
            for task in phase2_tasks:
                if phase1_context:
                    task.context += f"\n\n## Produkt- & Führungskontext\n{phase1_context[:2500]}"
                agent_name = self._agents[task.agent_id].name if task.agent_id in self._agents else task.agent_id
                notify(f"  ▶️ [yellow]Arbeitet:[/yellow] {agent_name}...")
                start_t = time.monotonic()
                result = await self._run_single_agent(task)
                dur = time.monotonic() - start_t
                all_results.append(result)
                status_ico = "✅ [green]Fertig[/green]" if result.success else "❌ [red]Fehler[/red]"
                notify(f"  {status_ico}: {agent_name} ({dur:.1f}s)")
                if result.success:
                    phase2_context += f"\n\n## {result.agent_name}\n{result.content[:2000]}"

        # ── Phase 3: Parallele Kern-Entwicklung ──
        if parallel_tasks:
            active_names = [self._agents[t.agent_id].name for t in parallel_tasks if t.agent_id in self._agents]
            notify(f"⚡ [bold cyan]Phase 3/5: Implementierung[/bold cyan] ({len(parallel_tasks)} Spezialisten parallel)...")
            for name in active_names:
                notify(f"  ▶️ [yellow]Arbeitet parallel:[/yellow] {name}")

            combined_blueprint = ""
            if phase2_context:
                combined_blueprint += f"\n\n## Architektur-Vorgaben:\n{phase2_context[:2000]}"
            if phase1_context:
                combined_blueprint += f"\n\n## Scope:\n{phase1_context[:1000]}"

            if combined_blueprint:
                for task in parallel_tasks:
                    task.context += combined_blueprint

            parallel_results = await self._run_agents_parallel(parallel_tasks, notify=notify)
            all_results.extend(parallel_results)

        # ── Phase 4: Review, Hygiene & Compliance ──
        if phase4_tasks:
            notify(f"🔍 [bold cyan]Phase 4/5: Review, Hygiene & Compliance[/bold cyan] ({len(phase4_tasks)} Agenten)...")
            code_context = self._format_results_for_review(all_results)
            for task in phase4_tasks:
                agent_name = self._agents[task.agent_id].name if task.agent_id in self._agents else task.agent_id
                notify(f"  ▶️ [yellow]Prüft Code & Struktur:[/yellow] {agent_name}...")
                task.description += f"\n\nPrüfe die folgenden Ergebnisse:\n{code_context[:3500]}"
                start_t = time.monotonic()
                result = await self._run_single_agent(task)
                dur = time.monotonic() - start_t
                all_results.append(result)
                status_ico = "✅ [green]Geprüft[/green]" if result.success else "❌ [red]Fehler[/red]"
                notify(f"  {status_ico}: {agent_name} ({dur:.1f}s)")

        all_results = await self._run_iterative_fix_loop(
            user_request=user_request,
            all_results=all_results,
            agent_tasks=agent_tasks,
            notify=notify,
        )

        return all_results

    async def _run_iterative_fix_loop(
        self,
        user_request: str,
        all_results: list[AgentResult],
        agent_tasks: list[AgentTask],
        notify: Callable[[str], None],
    ) -> list[AgentResult]:
        reviewer_res = next((r for r in all_results if r.agent_id == "code_reviewer" and r.success), None)
        if not reviewer_res:
            return all_results

        rev_text = reviewer_res.content.lower()
        has_critical = ("🔴 kritische probleme" in rev_text or "müssen behoben werden" in rev_text)

        if not has_critical or MAX_REVIEW_ITERATIONS <= 0:
            return all_results

        notify("🛠️  [yellow]Code-Reviewer meldet Nachbesserungsbedarf[/yellow] – starte automatische Fix-Schleife...")
        tasks_to_fix = [t for t in agent_tasks if t.agent_id in CODE_PRODUCING_AGENTS]

        if tasks_to_fix:
            fix_tasks = [
                AgentTask(
                    task_id=f"{t.task_id}_fix",
                    agent_id=t.agent_id,
                    description=f"KORRIGIERE gemeldete Fehler:\n{reviewer_res.content[:2000]}\nAufgabe:\n{t.description}",
                    context=user_request[:1000],
                )
                for t in tasks_to_fix
            ]
            fixed_results = await self._run_agents_parallel(fix_tasks, notify=notify)
            fixed_ids = {r.agent_id for r in fixed_results if r.success}
            all_results = [r for r in all_results if r.agent_id not in fixed_ids]
            all_results.extend([r for r in fixed_results if r.success])

        return all_results

    async def _run_single_agent(self, task: AgentTask) -> AgentResult:
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
        return await agent.execute(task)

    async def _run_agents_parallel(
        self,
        agent_tasks: list[AgentTask],
        notify: Optional[Callable[[str], None]] = None,
    ) -> list[AgentResult]:
        async def _wrapped(task: AgentTask) -> AgentResult:
            res = await self._run_single_agent(task)
            if notify:
                status_ico = "✅ [green]Abgeschlossen[/green]" if res.success else "❌ [red]Fehler[/red]"
                notify(f"  {status_ico}: {res.agent_name} ({res.duration_seconds:.1f}s)")
            return res

        results = await asyncio.gather(
            *[_wrapped(task) for task in agent_tasks],
            return_exceptions=False,
        )
        return list(results)

    async def _run_retrospective(
        self,
        user_request: str,
        results: list[AgentResult],
        total_duration: float,
    ) -> Optional[AgentResult]:
        retro_agent = self._agents.get("retrospective")
        if not retro_agent:
            return None

        retro_context = f"NUTZERAUFGABE: {user_request}\n\nTEAM-ERGEBNISSE:\n"
        for r in results:
            status = "Erfolgreich" if r.success else f"Fehler: {r.error}"
            retro_context += f"- {r.agent_name} ({r.agent_id}): {status} | Dauer: {r.duration_seconds:.1f}s | Tokens: {r.total_tokens}\n"
            if r.content:
                retro_context += f"  Auszug: {r.content[:250]}...\n"

        task = AgentTask(
            task_id="retro_task",
            agent_id="retrospective",
            description="Erstelle eine ehrliche und konstruktive Retrospektive für dieses Projekt.",
            context=retro_context,
        )
        return await retro_agent.execute(task)

    def _build_metrics_summary(
        self,
        results: list[AgentResult],
        synth_tokens: int,
        total_duration: float,
        project_slug: str,
    ) -> str:
        total_prompt_tokens = sum(r.prompt_tokens for r in results)
        total_completion_tokens = sum(r.completion_tokens for r in results) + synth_tokens
        grand_total_tokens = sum(r.total_tokens for r in results) + synth_tokens

        lines = [
            "### 📈 Projekt-Kennzahlen & Ressourcen-Verbrauch\n",
            f"- ⏱️ **Gesamtdauer:** `{total_duration:.2f} Sekunden`",
            f"- 🪙 **Gesamtverbrauch Tokens:** `{grand_total_tokens:,}` (Prompt: `{total_prompt_tokens:,}` | Completion: `{total_completion_tokens:,}`)",
            f"- 📁 **Projektverzeichnis:** `workspace/{project_slug}/`\n",
            "| KI-Agent | Rolle / Aufgabe | Modell | Dauer | Tokens | Status |",
            "|---|---|---|---|---|---|",
        ]

        for r in results:
            status_icon = "✅" if r.success else "❌"
            lines.append(
                f"| **{r.agent_name}** | `{r.agent_id}` | `{r.model_used or 'default'}` | {r.duration_seconds:.1f}s | {r.total_tokens:,} | {status_icon} |"
            )

        lines.append(
            f"| **🤖 Hauptagent (Synthese)** | `orchestrator` | `{ORCHESTRATOR_MODEL}` | - | {synth_tokens:,} | ✅ |"
        )

        return "\n".join(lines)

    def _format_results_for_review(self, results: list[AgentResult]) -> str:
        successful = [r for r in results if r.success]
        sections = []
        for result in successful:
            sections.append(f"### {result.agent_name}\n\n{result.content[:1200]}")
        return "\n\n---\n\n".join(sections)
