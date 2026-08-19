"""
agents/orchestrator.py – Der Hauptagent (Orchestrator)

Der Orchestrator koordiniert das gesamte 23-köpfige KI-Softwareentwickler-Team
mit einem mehrphasigen Workflow, iterativer Review-Schleife und Workspace-Dateisystem.

WORKFLOW (5 Phasen mit iterativem Feedback-Loop):
  Phase 1: Planung & Anforderung (Product Owner, Business Analyst)
  Phase 2: Architektur & Kosten (Software-Architekt, Cost & FinOps)
  Phase 3: Spezialisten & Entwicklung (Frontend, Backend, Database, API, Data Eng, ML, Mobile, DevOps, QA, Security, Docs, i18n, Performance)
  Phase 4: Review, Refactoring & Compliance (Code-Reviewer, Refactoring, Legal & Compliance)
  Iterativer Fix-Loop: Automatische Nachbesserung bei kritischen Fehlern / Reviews
  Phase 5 / Synthese: Automatische Workspace-Dateierstellung & Zusammenfassung
"""

import asyncio
from typing import Callable, Optional

from agents.base_agent import BaseAgent
from agents.ui_ux_agent import UIUXAgent
from agents.frontend_agent import FrontendAgent
from agents.backend_agent import BackendAgent
from agents.database_agent import DatabaseAgent
from agents.api_integration_agent import ApiIntegrationAgent
from agents.data_engineer_agent import DataEngineerAgent
from agents.devops_agent import DevOpsAgent
from agents.tester_agent import TesterAgent
from agents.documentation_agent import DocumentationAgent
from agents.security_agent import SecurityAgent
from agents.readme_agent import ReadmeAgent
from agents.github_agent import GitHubAgent
from agents.architect_agent import ArchitectAgent
from agents.finops_agent import FinOpsAgent
from agents.code_reviewer_agent import CodeReviewerAgent
from agents.refactoring_agent import RefactoringAgent
from agents.compliance_agent import ComplianceAgent
from agents.business_analyst_agent import BusinessAnalystAgent
from agents.product_owner_agent import ProductOwnerAgent
from agents.mobile_agent import MobileAgent
from agents.ml_agent import MLAgent
from agents.performance_agent import PerformanceAgent
from agents.i18n_agent import I18nAgent

from core.task_manager import TaskManager
from core.result_aggregator import ResultAggregator
from core.message_bus import AgentResult, AgentTask
from core.workspace import WorkspaceManager
from core.code_sandbox import CodeSandbox
from memory.conversation_history import ConversationHistory
from config import ORCHESTRATOR_MODEL, MAX_REVIEW_ITERATIONS, AUTO_SAVE_WORKSPACE

# Typdefinition für Status-Callback (für Live-Updates in der CLI)
StatusCallback = Callable[[str], None]

# Phasen-Einteilung der Agenten
PHASE_1_AGENTS = {"business_analyst", "product_owner"}
PHASE_2_AGENTS = {"architect", "finops"}
PHASE_4_AGENTS = {"code_reviewer", "refactoring", "compliance"}

# Code-produzierende Agenten, die bei Beanstandungen im Review-Loop korrigiert werden können
CODE_PRODUCING_AGENTS = {
    "frontend", "backend", "database", "api_integration",
    "data_engineer", "mobile", "ml", "devops", "tester", "performance", "i18n"
}


class Orchestrator:
    """
    Hauptagent, der das gesamte KI-Softwareentwickler-Team (23 Spezialisten) koordiniert.
    """

    def __init__(self):
        # Alle 23 Unteragenten registrieren
        self._agents: dict[str, BaseAgent] = {
            # Phase 1: Planung & Produkt
            "business_analyst":  BusinessAnalystAgent(),
            "product_owner":     ProductOwnerAgent(),

            # Phase 2: Architektur & FinOps
            "architect":         ArchitectAgent(),
            "finops":            FinOpsAgent(),

            # Phase 3: Kern-Entwicklung
            "ui_ux":             UIUXAgent(),
            "frontend":          FrontendAgent(),
            "backend":           BackendAgent(),
            "database":          DatabaseAgent(),
            "api_integration":   ApiIntegrationAgent(),
            "data_engineer":     DataEngineerAgent(),
            "mobile":            MobileAgent(),
            "ml":                MLAgent(),
            "performance":       PerformanceAgent(),
            "i18n":              I18nAgent(),

            # Phase 3: Infrastruktur & QA
            "devops":            DevOpsAgent(),
            "tester":            TesterAgent(),
            "documentation":     DocumentationAgent(),
            "security":          SecurityAgent(),

            # Phase 4: Review, Refactoring & Compliance
            "code_reviewer":     CodeReviewerAgent(),
            "refactoring":       RefactoringAgent(),
            "compliance":        ComplianceAgent(),

            # Utility
            "readme":            ReadmeAgent(),
            "github":            GitHubAgent(),
        }

        self._task_manager = TaskManager(model_name=ORCHESTRATOR_MODEL)
        self._result_aggregator = ResultAggregator(model_name=ORCHESTRATOR_MODEL)
        self._history = ConversationHistory()
        self._workspace = WorkspaceManager()

    # ──────────────────────────────────────────────────────
    # Öffentliche Schnittstelle
    # ──────────────────────────────────────────────────────

    async def process(
        self,
        user_request: str,
        status_callback: Optional[StatusCallback] = None,
    ) -> str:
        """
        Verarbeitet eine Nutzeranfrage komplett durch das Team (Mehrphasen-Workflow + Review-Loop + Workspace).
        """
        def notify(msg: str):
            if status_callback:
                status_callback(msg)

        # Anfrage im Verlauf speichern
        self._history.add_user_message(user_request)
        notify("🧠 Analysiere Aufgabe und erstelle Team-Plan...")

        # Aufgabe zerlegen
        context = self._history.get_context_string(max_messages=6)
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

        # Team-Plan ausgeben
        agent_names = [
            self._agents[t.agent_id].name
            for t in agent_tasks
            if t.agent_id in self._agents
        ]
        notify(f"📋 Plan: {task_summary}")
        notify(f"📁 Projektordner: workspace/{project_slug}/")
        notify(f"👥 Team ({len(agent_names)} Spezialisten): {', '.join(agent_names)}")

        # Mehrphasen-Ausführung inklusive Review- & Fix-Schleife
        results = await self._run_phased_execution(
            user_request=user_request,
            agent_tasks=agent_tasks,
            project_slug=project_slug,
            notify=notify,
        )

        # Automatische Workspace-Dateispeicherung
        if AUTO_SAVE_WORKSPACE:
            saved_files_count = 0
            for res in results:
                if res.success and res.content:
                    files = self._workspace.parse_and_save_files(
                        project_name=project_slug,
                        text_content=res.content,
                        agent_name=res.agent_name,
                    )
                    saved_files_count += len(files)

            if saved_files_count > 0:
                notify(f"💾 {saved_files_count} Projektdateien in 'workspace/{project_slug}/' gespeichert!")

        # Synthese
        notify("📝 Fasse alle Ergebnisse zusammen...")
        final_response = await self._result_aggregator.synthesize(
            user_request=user_request,
            task_summary=task_summary,
            results=results,
        )

        # Workspace-Hinweis anhängen falls Dateien erzeugt wurden
        project_files = self._workspace.list_project_files(project_slug)
        if project_files:
            file_tree_str = "\n".join([f"- `{f['path']}` ({f['size_bytes']} Bytes)" for f in project_files[:15]])
            if len(project_files) > 15:
                file_tree_str += f"\n- ... und {len(project_files) - 15} weitere Dateien"

            final_response += (
                f"\n\n---\n\n### 📁 Generierte Workspace-Dateien (`workspace/{project_slug}/`)\n"
                f"{file_tree_str}\n\n"
                f"*Tipp: Du kannst das gesamte Projekt mit `/export {project_slug}` als ZIP-Archiv exportieren.*"
            )

        self._history.add_assistant_message(final_response)
        return final_response

    def get_team_info(self) -> str:
        """Gibt eine Übersicht über das gesamte 23-köpfige Team zurück."""
        sections = {
            "🔵 Phase 1: Planung & Produkt": {
                "business_analyst", "product_owner"
            },
            "🟣 Phase 2: Architektur & FinOps": {
                "architect", "finops"
            },
            "🟢 Phase 3: Entwicklung & Spezialisten (parallel)": {
                "ui_ux", "frontend", "backend", "database",
                "api_integration", "data_engineer", "mobile", "ml", "performance", "i18n"
            },
            "🟡 Phase 3: Infrastruktur & Qualität (parallel)": {
                "devops", "tester", "documentation", "security"
            },
            "🔴 Phase 4: Review, Refactoring & Compliance (sequentiell)": {
                "code_reviewer", "refactoring", "compliance"
            },
            "⚪ Utility-Agenten": {
                "readme", "github"
            },
        }
        icons = {
            "business_analyst": "📋", "product_owner": "🎯", "architect": "🏛️", "finops": "💰",
            "ui_ux": "🎨", "frontend": "💻", "backend": "⚙️", "database": "🗄️",
            "api_integration": "🔌", "data_engineer": "🌊", "mobile": "📱", "ml": "🤖",
            "performance": "⚡", "i18n": "🌍", "devops": "🚀", "tester": "🧪",
            "documentation": "📚", "security": "🔒", "code_reviewer": "🔍",
            "refactoring": "🧹", "compliance": "⚖️", "readme": "📝", "github": "🔀",
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

    def get_workspace_manager(self) -> WorkspaceManager:
        return self._workspace

    # ──────────────────────────────────────────────────────
    # Mehrphasen-Orchestrierung mit iterativem Review-Loop
    # ──────────────────────────────────────────────────────

    async def _run_phased_execution(
        self,
        user_request: str,
        agent_tasks: list[AgentTask],
        project_slug: str,
        notify: Callable[[str], None],
    ) -> list[AgentResult]:
        """
        Führt alle Agenten in 4 Kernphasen aus, gefolgt von einem iterativen Fix-Loop:
        Phase 1: Planung (BA / PO)
        Phase 2: Architektur & FinOps
        Phase 3: Parallele Entwicklung & Infrastruktur
        Phase 4: Review, Refactoring & Compliance
        Iterativer Fix-Loop: Nachbesserung bei kritischen Review-Mängeln
        """
        all_results: list[AgentResult] = []
        phase1_context = ""
        phase2_context = ""

        # Aufgaben nach Phasen aufteilen
        phase1_tasks = [t for t in agent_tasks if t.agent_id in PHASE_1_AGENTS]
        phase2_tasks = [t for t in agent_tasks if t.agent_id in PHASE_2_AGENTS]
        phase4_tasks = [t for t in agent_tasks if t.agent_id in PHASE_4_AGENTS]
        parallel_tasks = [
            t for t in agent_tasks
            if t.agent_id not in PHASE_1_AGENTS
            and t.agent_id not in PHASE_2_AGENTS
            and t.agent_id not in PHASE_4_AGENTS
        ]

        # ── Phase 1: Planung & Produkt (sequentiell) ────────
        if phase1_tasks:
            notify(f"📋 Phase 1/4: {len(phase1_tasks)} Planungs-Agenten analysieren...")
            for task in phase1_tasks:
                result = await self._run_single_agent(task, notify)
                all_results.append(result)
                if result.success:
                    phase1_context += f"\n\n## {result.agent_name}\n{result.content[:2500]}"

        # ── Phase 2: Architektur & FinOps (sequentiell) ────
        if phase2_tasks:
            notify(f"🏛️  Phase 2/4: {len(phase2_tasks)} Architektur- & FinOps-Experten entwerfen das System...")
            for task in phase2_tasks:
                if phase1_context:
                    task.context += f"\n\n## Anforderungs- & Produktkontext\n{phase1_context[:3000]}"
                result = await self._run_single_agent(task, notify)
                all_results.append(result)
                if result.success:
                    phase2_context += f"\n\n## {result.agent_name}\n{result.content[:2500]}"

        # ── Phase 3: Parallele Implementierung ─────────────
        if parallel_tasks:
            count = len(parallel_tasks)
            notify(f"⚡ Phase 3/4: {count} Entwickler arbeiten parallel...")

            # Blueprint-Kontext an alle Entwickler weitergeben
            combined_blueprint = ""
            if phase2_context:
                combined_blueprint += f"\n\n## Architektur- & Kosten-Vorgaben:\n{phase2_context[:3000]}"
            if phase1_context:
                combined_blueprint += f"\n\n## Produkt- & Scope-Vorgaben:\n{phase1_context[:2000]}"

            if combined_blueprint:
                for task in parallel_tasks:
                    task.context += combined_blueprint

            parallel_results = await self._run_agents_parallel(parallel_tasks, notify)
            all_results.extend(parallel_results)

        # ── Phase 4: Review, Refactoring & Compliance ──────
        if phase4_tasks:
            notify(f"🔍 Phase 4/4: {len(phase4_tasks)} Audit- & Review-Agenten prüfen die Implementierung...")
            code_context = self._format_results_for_review(all_results)
            for task in phase4_tasks:
                task.description += (
                    f"\n\nBitte auditiere und überprüfe die folgenden Teamergebnisse:\n"
                    f"{code_context[:5000]}"
                )
                result = await self._run_single_agent(task, notify)
                all_results.append(result)

        # ── Iterativer Review- & Fix-Loop ───────────────────
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
        """
        Prüft den Review-Report auf kritische Mängel.
        Falls gravierende Fehler gemeldet wurden, werden die betroffenen Code-Agenten
        mit dem konkreten Fix-Auftrag erneut aufgerufen (bis zu MAX_REVIEW_ITERATIONS Zyklen).
        """
        # Finde Reviewer-Ergebnis
        reviewer_result = next((r for r in all_results if r.agent_id == "code_reviewer" and r.success), None)
        if not reviewer_result:
            return all_results

        # Prüfe ob kritische Mängel vorliegen
        rev_text = reviewer_result.content.lower()
        has_critical = (
            "🔴 kritische probleme" in rev_text
            or "kritischer fehler" in rev_text
            or "⭐⭐☆☆☆" in rev_text
            or "⭐☆☆☆☆" in rev_text
            or "müssen behoben werden" in rev_text
        )

        if not has_critical or MAX_REVIEW_ITERATIONS <= 0:
            return all_results

        notify("🔄 Kritische Punkte im Review erkannt – starte automatische Nachbesserung (Fix-Loop)...")

        for iteration in range(1, MAX_REVIEW_ITERATIONS + 1):
            notify(f"🛠️  Iterativer Fix-Zyklus {iteration}/{MAX_REVIEW_ITERATIONS}...")

            # Betroffene Entwickler-Tasks erneut aufrufen mit Review-Feedback
            tasks_to_fix = [t for t in agent_tasks if t.agent_id in CODE_PRODUCING_AGENTS]
            if not tasks_to_fix:
                break

            # Erstelle verfeinerte Tasks
            fix_tasks = []
            for t in tasks_to_fix:
                fix_tasks.append(
                    AgentTask(
                        task_id=f"{t.task_id}_fix_{iteration}",
                        agent_id=t.agent_id,
                        description=(
                            f"KORREKTUR-AUFTRAG basierend auf Code-Review:\n"
                            f"Bitte behebe alle kritischen Mängel und Inkonsistenzen in deiner Komponente!\n\n"
                            f"REVIEW-FEEDBACK:\n{reviewer_result.content[:3500]}\n\n"
                            f"ORIGINALE AUFGABE:\n{t.description}"
                        ),
                        context=user_request,
                    )
                )

            # Parallel nachbessern lassen
            fixed_results = await self._run_agents_parallel(fix_tasks, notify)

            # Aktualisiere/Ersetze die Ergebnisse im Gesamtpool
            fixed_agent_ids = {r.agent_id for r in fixed_results if r.success}
            all_results = [r for r in all_results if r.agent_id not in fixed_agent_ids]
            all_results.extend([r for r in fixed_results if r.success])

            notify(f"✅ Nachbesserungen für {len(fixed_agent_ids)} Komponenten erfolgreich integriert.")
            break  # Nach einem vollständigen Korrektur-Durchlauf abschließen

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
        """Formatiert alle Ergebnisse für den Code-Reviewer und die Audit-Agenten."""
        successful = [r for r in results if r.success]
        sections = []
        for result in successful:
            sections.append(
                f"### {result.agent_name}\n\n{result.content[:1500]}"
            )
        return "\n\n---\n\n".join(sections)
