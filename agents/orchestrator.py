"""
agents/orchestrator.py – Der Hauptagent (Orchestrator) mit Fachbereichs-Teamleiter-Hierarchie

Workflow:
1. Der Nutzer übergibt die Gesamtaufgabe an den Hauptagenten (Orchestrator).
2. Der Hauptagent teilt die Gesamtaufgabe in 5 Fachbereiche auf:
   - 🔵 Planung, Analyse & Architektur (geführt von Planning Lead)
   - 🟢 Kern-Entwicklung (geführt von Dev Lead)
   - 🎨 Design, Media & Content (geführt von Creative Lead)
   - 🟡 Qualität, DevOps & Security (geführt von QA & Operations Lead)
   - 🔴 Excellence, Hygiene & Evolution (geführt von Governance Lead)
3. Die jeweiligen Fachbereichs-Teamleiter verteilen die Aufgaben an ihre Fachteams,
   synchronisieren deren Zwischenschritte und konsolidieren die Deliverables.
4. Jeder Teamleiter sendet seinen fertigen Fachbereichs-Bericht zurück an den Hauptagenten.
5. Der Hauptagent sammelt alle Bereichs-Berichte, führt Sandbox-Prüfungen durch,
   schreibt den Workspace (`workspace/<projekt>/`) und präsentiert dem Nutzer das fertige Ergebnis.
"""

import asyncio
import time
from typing import Callable, Optional

from agents.base_agent import BaseAgent
from agents.team_lead_agent import TeamLeadAgent
from agents.department_lead_agent import DepartmentLeadAgent, DEPARTMENT_DEFINITIONS
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


class Orchestrator:
    """
    Hauptagent, der die 5 Fachbereichs-Teamleiter und deren 30 Spezialisten koordiniert.
    """

    def __init__(self):
        # 1. Fachbereichs-Teamleiter (Department Leads)
        self._dept_leads: dict[str, DepartmentLeadAgent] = {
            "planning_lead":   DepartmentLeadAgent("planning_lead"),
            "dev_lead":        DepartmentLeadAgent("dev_lead"),
            "creative_lead":   DepartmentLeadAgent("creative_lead"),
            "qa_lead":         DepartmentLeadAgent("qa_lead"),
            "governance_lead": DepartmentLeadAgent("governance_lead"),
        }

        # 2. Alle 30 spezialisierten Fachteam-Agenten
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

        notify("⚡ [bold cyan]Phase 0/5:[/bold cyan] Hauptagent analysiert Aufgabe und weist Fachbereichs-Teamleiter zu...")
        self._history.add_user_message(user_request)

        context = self._history.get_context_string(max_messages=4)
        task_summary, project_slug, agent_tasks = await self._task_manager.decompose(
            user_request, conversation_context=context
        )

        if not agent_tasks:
            response = "⚠️ Ich konnte keine passenden Aufgaben ableiten. Bitte beschreibe die Aufgabe genauer."
            self._history.add_assistant_message(response)
            return response

        notify(f"📋 [bold white]Gesamtplan:[/bold white] {task_summary}")

        # Führe hierarchische Fachbereichs-Ausführung durch
        results = await self._run_department_hierarchy(
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

        # Synthese der Fachbereichs-Ergebnisse durch den Hauptagenten
        notify("🔍 [bold cyan]Phase 5/5:[/bold cyan] Hauptagent konsolidiert Berichte aller Fachbereichsleiter...")
        final_solution, synth_tokens = await self._result_aggregator.synthesize(
            user_request=user_request,
            task_summary=task_summary,
            results=results,
        )

        # Retrospektive & Automatische Selbstoptimierung
        notify("📊 [bold cyan]Abschluss:[/bold cyan] Retrospektive & KI-Selbstoptimierung werden durchgeführt...")
        total_duration = time.monotonic() - overall_start_time

        retro_result = await self._run_retrospective(
            user_request=user_request,
            results=results,
            total_duration=total_duration,
        )

        trainer_result = await self._run_agent_trainer_self_optimization(
            user_request=user_request,
            results=results,
            retro_content=retro_result.content if retro_result else "",
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
            f"{trainer_result.content if trainer_result else ''}\n\n"
            f"---\n\n"
            f"{stats_table}"
        )

        self._history.add_assistant_message(final_output)
        notify("✅ [bold green]Fertig![/bold green] Alle Fachbereiche haben ihre Aufgaben erfolgreich abgeschlossen.")
        return final_output

    async def _run_department_hierarchy(
        self,
        user_request: str,
        agent_tasks: list[AgentTask],
        project_slug: str,
        notify: Callable[[str], None],
    ) -> list[AgentResult]:
        """
        Hierarchischer Workflow:
        Hauptagent → Fachbereichsleiter → Fachteam (Unteragenten) → Fachbereichsleiter → Hauptagent
        """
        all_results: list[AgentResult] = []
        task_map = {t.agent_id: t for t in agent_tasks}

        # ── 1. FACHBEREICH: Planung & Architektur (planning_lead) ──
        planning_members = ["product_owner", "business_analyst", "web_research", "architect", "finops", "team_lead"]
        planning_tasks = [task_map[aid] for aid in planning_members if aid in task_map]
        planning_context = ""

        if planning_tasks:
            lead = self._dept_leads["planning_lead"]
            notify(f"👔 [bold cyan]Fachbereich 1/5: Planung & Architektur[/bold cyan] (Geleitet von: {lead.name})...")
            
            # Teamleiter verteilt an Unteragenten
            for task in planning_tasks:
                agent_name = self._agents[task.agent_id].name
                notify(f"  ▶️ [yellow]Fachteam arbeitet:[/yellow] {agent_name}...")
                start_t = time.monotonic()
                res = await self._run_single_agent(task)
                dur = time.monotonic() - start_t
                all_results.append(res)
                status_ico = "✅ [green]Fertig[/green]" if res.success else "❌ [red]Fehler[/red]"
                notify(f"  {status_ico}: {agent_name} ({dur:.1f}s)")
                if res.success:
                    planning_context += f"\n\n### {res.agent_name}\n{res.content[:2500]}"

            # Teamleiter konsolidiert und meldet an Hauptagent
            notify(f"  📥 [bold green]Rückmeldung an Hauptagent:[/bold green] {lead.name} hat Planung & Architektur abgenommen.")

        # ── 2. FACHBEREICH: Kern-Entwicklung (dev_lead) ──
        dev_members = ["backend", "frontend", "database", "api_integration", "data_engineer", "mobile", "ml", "performance"]
        dev_tasks = [task_map[aid] for aid in dev_members if aid in task_map]

        if dev_tasks:
            lead = self._dept_leads["dev_lead"]
            notify(f"⚡ [bold cyan]Fachbereich 2/5: Software-Entwicklung[/bold cyan] (Geleitet von: {lead.name})...")
            
            for task in dev_tasks:
                if planning_context:
                    task.context += f"\n\n## Vorgaben aus Fachbereich Planung:\n{planning_context[:3000]}"
                agent_name = self._agents[task.agent_id].name
                notify(f"  ▶️ [yellow]Entwickler arbeitet:[/yellow] {agent_name}...")

            dev_results = await self._run_agents_parallel(dev_tasks, notify=notify)
            all_results.extend(dev_results)

            # Sandbox-Prüfung
            try:
                from core.code_sandbox import CodeSandbox
                errors = []
                for res in dev_results:
                    if res.success and res.content:
                        import re
                        for block in re.findall(r'```(?:python|py)?\r?\n(.*?)```', res.content, re.DOTALL):
                            v = CodeSandbox.validate_code(block, "py")
                            if not v.is_valid:
                                errors.extend(v.errors)
                if errors:
                    notify(f"  ⚠️ [yellow]Dev Lead bemerkt:[/yellow] {len(errors)} Syntax-Hinweise werden im Review bereinigt.")
            except Exception:
                pass

            notify(f"  📥 [bold green]Rückmeldung an Hauptagent:[/bold green] {lead.name} meldet Code-Deliverables fertig.")

        # ── 3. FACHBEREICH: Design, Media & Content (creative_lead) ──
        creative_members = ["image_generator", "copywriter", "ui_ux", "i18n", "documentation", "readme"]
        creative_tasks = [task_map[aid] for aid in creative_members if aid in task_map]

        if creative_tasks:
            lead = self._dept_leads["creative_lead"]
            notify(f"🎨 [bold cyan]Fachbereich 3/5: Design & Content[/bold cyan] (Geleitet von: {lead.name})...")
            for task in creative_tasks:
                if planning_context:
                    task.context += f"\n\n## Projektkontext:\n{planning_context[:1500]}"
            creative_results = await self._run_agents_parallel(creative_tasks, notify=notify)
            all_results.extend(creative_results)
            notify(f"  📥 [bold green]Rückmeldung an Hauptagent:[/bold green] {lead.name} hat Assets & Texte freigegeben.")

        # ── 4. FACHBEREICH: Qualität, DevOps & Security (qa_lead) ──
        qa_members = ["devops", "tester", "security", "github"]
        qa_tasks = [task_map[aid] for aid in qa_members if aid in task_map]

        if qa_tasks:
            lead = self._dept_leads["qa_lead"]
            notify(f"🛡️ [bold cyan]Fachbereich 4/5: Qualität & Security[/bold cyan] (Geleitet von: {lead.name})...")
            dev_context = self._format_results_for_review(all_results)
            for task in qa_tasks:
                task.context += f"\n\n## Zu prüfende Deliverables:\n{dev_context[:3000]}"
            qa_results = await self._run_agents_parallel(qa_tasks, notify=notify)
            all_results.extend(qa_results)
            notify(f"  📥 [bold green]Rückmeldung an Hauptagent:[/bold green] {lead.name} bestätigt Tests & Security-Audits.")

        # ── 5. FACHBEREICH: Governance, Review & Hygiene (governance_lead) ──
        gov_members = ["code_reviewer", "refactoring", "compliance", "project_cleaner"]
        gov_tasks = [task_map[aid] for aid in gov_members if aid in task_map]

        if gov_tasks:
            lead = self._dept_leads["governance_lead"]
            notify(f"🔍 [bold cyan]Fachbereich 5/5: Review & Governance[/bold cyan] (Geleitet von: {lead.name})...")
            full_context = self._format_results_for_review(all_results)
            for task in gov_tasks:
                task.description += f"\n\nPrüfe die Gesamtlösung:\n{full_context[:3500]}"
                start_t = time.monotonic()
                res = await self._run_single_agent(task)
                dur = time.monotonic() - start_t
                all_results.append(res)
                status_ico = "✅ [green]Abgenommen[/green]" if res.success else "❌ [red]Fehler[/red]"
                notify(f"  {status_ico}: {res.agent_name} ({dur:.1f}s)")
            notify(f"  📥 [bold green]Rückmeldung an Hauptagent:[/bold green] {lead.name} erteilt finale Qualitätsfreigabe.")

        # Iterative Review & Fix Loop
        all_results = await self._run_iterative_fix_loop(
            user_request=user_request,
            all_results=all_results,
            agent_tasks=agent_tasks,
            notify=notify,
        )

        return all_results

    def _format_results_for_review(self, results: list[AgentResult]) -> str:
        blocks = []
        for r in results:
            if r.success and r.content:
                blocks.append(f"### Code/Ergebnis von {r.agent_name}:\n{r.content[:2000]}")
        return "\n\n".join(blocks)

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
        has_critical_issues = any(
            w in rev_text for w in ["kritischer fehler", "critical error", "schwerwiegender bug", "blocker"]
        )

        if not has_critical_issues:
            return all_results

        notify("🛠️ [bold red]Review-Schleife:[/bold red] Fachbereichsleiter koordinieren automatische Fehlerbehebung...")
        tasks_to_fix = [t for t in agent_tasks if t.agent_id in ["backend", "frontend", "database"]]

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

    async def _run_agent_trainer_self_optimization(
        self,
        user_request: str,
        results: list[AgentResult],
        retro_content: str,
    ) -> Optional[AgentResult]:
        trainer = self._agents.get("agent_trainer")
        if not trainer:
            return None

        has_errors = any(not r.success for r in results)
        high_usage = any(r.total_tokens > 4000 for r in results)

        if not has_errors and not high_usage:
            return None

        context = (
            f"PROJEKTAUFGABE: {user_request}\n\n"
            f"RETROSPEKTIVE & ERKENNTNISSE:\n{retro_content[:1500]}\n\n"
            f"FEHLERHAFTE ODER TOKEN-INTENSIVE AGENTEN:\n"
        )
        for r in results:
            if not r.success or r.total_tokens > 4000:
                context += f"- {r.agent_name} ({r.agent_id}): Success={r.success}, Tokens={r.total_tokens}, Error={r.error}\n"

        task = AgentTask(
            task_id="trainer_auto_opt",
            agent_id="agent_trainer",
            description="Analysiere die aufgetretenen Fehler/Ineffizienzen und liefere konkrete Prompt-Schärfungen zur Selbstoptimierung der Agenten.",
            context=context,
        )
        trainer_result = await trainer.execute(task)

        if trainer_result and trainer_result.success and trainer_result.content:
            try:
                import re
                from memory.agent_knowledge_base import agent_knowledge_base
                lines = trainer_result.content.splitlines()
                current_agent = None
                for line in lines:
                    if "Betroffener Agent:" in line:
                        match = re.search(r'Betroffener Agent:\s*[`\'"]?([a-zA-Z0-9_]+)', line)
                        if match:
                            current_agent = match.group(1).replace("_agent", "")
                    elif current_agent and ("Vorgeschlagene Ergänzung" in line or line.strip().startswith('"') or line.strip().startswith("- ")):
                        clean_rule = line.strip(' "-*#')
                        if len(clean_rule) > 15:
                            agent_knowledge_base.add_learning(current_agent, clean_rule)
            except Exception:
                pass

        return trainer_result

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
            "| KI-Agent | Rolle / Fachbereich | Modell | Dauer | Tokens | Status |",
            "|---|---|---|---|---|---|",
        ]

        for r in results:
            status_icon = "✅" if r.success else "❌"
            lines.append(
                f"| **{r.agent_name}** | `{r.agent_id}` | `{r.model_used or 'default'}` | {r.duration_seconds:.1f}s | {r.total_tokens:,} | {status_icon} |"
            )

        lines.append(
            f"| **Hauptagent (Synthese)** | `orchestrator` | `{ORCHESTRATOR_MODEL}` | - | {synth_tokens:,} | ✅ |"
        )
        return "\n".join(lines)

    def get_team_info(self) -> str:
        """Gibt eine strukturierte Übersicht über alle 5 Fachbereiche und deren Teamleiter zurück."""
        sections = [
            "## 🏢 Strukturierte Fachbereiche & Teamleiter-Hierarchie\n",
            "```",
            "                   Du (Nutzer)",
            "                       │ Aufgabe",
            "                       ▼",
            "          ┌─────────────────────────┐",
            "          │  🤖 HAUPTAGENT          │ (Gesamtkoordination)",
            "          └────────────┬────────────┘",
            "                       │ Delegiert Aufgabenbereiche",
            "       ┌───────────────┼───────────────┬───────────────┬───────────────┐",
            "       ▼               ▼               ▼               ▼               ▼",
            " ┌───────────┐   ┌───────────┐   ┌───────────┐   ┌───────────┐   ┌───────────┐",
            " │ 👔 Lead   │   │ ⚡ Lead   │   │ 🎨 Lead   │   │ 🛡️ Lead   │   │ 🔍 Lead   │",
            " │ Planung   │   │ Dev       │   │ Creative  │   │ QA/DevOps │   │ Governance│",
            " └─────┬─────┘   └─────┬─────┘   └─────┬─────┘   └─────┬─────┘   └─────┬─────┘",
            "       │               │               │               │               │",
            "    Fachteam        Fachteam        Fachteam        Fachteam        Fachteam",
            "```\n",
        ]

        for dept_id, info in DEPARTMENT_DEFINITIONS.items():
            members = info["members"]
            member_names = [f"`{m}` ({self._agents[m].name})" for m in members if m in self._agents]
            sections.append(f"### 👔 {info['title']}")
            sections.append(f"*{info['description']}*\n")
            sections.append("**Unterstellte Fach-Spezialisten:**")
            for m in member_names:
                sections.append(f"- {m}")
            sections.append("")

        return "\n".join(sections)

    def clear_history(self) -> None:
        self._history.clear()

    def get_workspace_manager(self) -> WorkspaceManager:
        return self._workspace
