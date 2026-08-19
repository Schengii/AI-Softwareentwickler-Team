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
3. Jeder Fachbereichs-Teamleiter delegiert per ECHTEM LLM-Aufruf konkrete
   Arbeitsanweisungen an sein Fachteam, lässt es arbeiten (die Mitglieder haben
   dabei echten Datei-/Werkzeugzugriff auf das Projektverzeichnis – siehe
   agents/base_agent.py) und konsolidiert die Ergebnisse anschließend per
   weiterem echten LLM-Aufruf zu einem geprüften Fachbereichsbericht.
4. Nach der QA-Phase installiert der Hauptagent Abhängigkeiten in einer
   isolierten Umgebung und führt die ECHTE Testsuite aus (core/verifier.py).
   Bei Fehlschlägen wird anhand der realen Tracebacks ermittelt, welcher
   Agent die betroffene Datei geschrieben hat – nur dieser bekommt den
   gezielten Korrekturauftrag (statt blind alle Dev-Agenten neu zu starten).
5. Der Hauptagent sammelt alle Fachbereichsberichte und präsentiert dem
   Nutzer das geprüfte Gesamtergebnis.
"""

import asyncio
import time
from collections.abc import Callable

from agents.accessibility_agent import AccessibilityAgent
from agents.agent_trainer_agent import AgentTrainerAgent
from agents.api_integration_agent import ApiIntegrationAgent
from agents.architect_agent import ArchitectAgent
from agents.backend_agent import BackendAgent
from agents.base_agent import BaseAgent
from agents.business_analyst_agent import BusinessAnalystAgent
from agents.code_reviewer_agent import CodeReviewerAgent
from agents.compliance_agent import ComplianceAgent
from agents.copywriter_agent import CopywriterAgent
from agents.data_engineer_agent import DataEngineerAgent
from agents.database_agent import DatabaseAgent
from agents.department_lead_agent import DEPARTMENT_DEFINITIONS, DepartmentLeadAgent
from agents.devops_agent import DevOpsAgent
from agents.documentation_agent import DocumentationAgent
from agents.finops_agent import FinOpsAgent
from agents.frontend_agent import FrontendAgent
from agents.github_agent import GitHubAgent
from agents.i18n_agent import I18nAgent
from agents.image_generator_agent import ImageGeneratorAgent
from agents.ml_agent import MLAgent
from agents.mobile_agent import MobileAgent
from agents.performance_agent import PerformanceAgent
from agents.product_owner_agent import ProductOwnerAgent
from agents.project_cleaner_agent import ProjectCleanerAgent
from agents.prompt_engineer_agent import PromptEngineerAgent
from agents.readme_agent import ReadmeAgent
from agents.refactoring_agent import RefactoringAgent
from agents.resilience_guard_agent import ResilienceGuardAgent
from agents.retrospective_agent import RetrospectiveAgent
from agents.security_agent import SecurityAgent
from agents.team_lead_agent import TeamLeadAgent
from agents.tester_agent import TesterAgent
from agents.ui_ux_agent import UIUXAgent
from agents.web_research_agent import WebResearchAgent
from config import (
    AGENT_MAX_TOOL_ITERATIONS,
    AUTO_SAVE_WORKSPACE,
    ENABLE_DEPARTMENT_LEAD_EXECUTION,
    MAX_VERIFICATION_ITERATIONS,
    ORCHESTRATOR_MODEL,
)
from core.message_bus import AgentResult, AgentTask
from core.result_aggregator import ResultAggregator
from core.task_manager import TaskManager
from core.verifier import ProjectVerifier
from core.workspace import WorkspaceManager
from memory.conversation_history import ConversationHistory

# Reine Prüf-/Berichts-Agenten: sollen bestehenden Code LESEN und bewerten, aber nicht
# selbst umschreiben (das ist Aufgabe von refactoring/backend/etc.) – spart nebenbei auch
# Tokens, da ihnen ein kleineres Werkzeug-Set (kein write_file/edit_file/run_command) angeboten wird.
REVIEW_ONLY_AGENT_IDS = {"code_reviewer", "compliance", "project_cleaner"}

StatusCallback = Callable[[str], None]

# Reihenfolge & Anzeige der 5 Fachbereichs-Phasen. Die Mitgliederlisten stammen
# zentral aus DEPARTMENT_DEFINITIONS (agents/department_lead_agent.py), damit
# Orchestrator und Teamleiter-Prompts nie auseinanderlaufen können.
PHASE_ORDER = [
    ("planning_lead", "Fachbereich 1/5: Planung & Architektur", "👔", "sequential"),
    ("dev_lead", "Fachbereich 2/5: Software-Entwicklung", "⚡", "parallel"),
    ("creative_lead", "Fachbereich 3/5: Design & Content", "🎨", "parallel"),
    ("qa_lead", "Fachbereich 4/5: Qualität & Security", "🛡️", "parallel"),
    ("governance_lead", "Fachbereich 5/5: Review & Governance", "🔍", "sequential"),
]


class Orchestrator:
    """
    Hauptagent, der die 5 Fachbereichs-Teamleiter und deren 33 Spezialisten koordiniert.
    """

    def __init__(self):
        # 1. Fachbereichs-Teamleiter (Department Leads)
        self._dept_leads: dict[str, DepartmentLeadAgent] = {
            dept_id: DepartmentLeadAgent(dept_id) for dept_id in DEPARTMENT_DEFINITIONS
        }

        # 2. Alle 33 spezialisierten Fachteam-Agenten
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
            "prompt_engineer":   PromptEngineerAgent(),
            "performance":       PerformanceAgent(),
            "image_generator":   ImageGeneratorAgent(),
            "copywriter":        CopywriterAgent(),
            "ui_ux":             UIUXAgent(),
            "accessibility":     AccessibilityAgent(),
            "i18n":              I18nAgent(),
            "documentation":     DocumentationAgent(),

            # Phase 3: Infrastruktur & QA
            "devops":            DevOpsAgent(),
            "tester":            TesterAgent(),
            "security":          SecurityAgent(),
            "resilience_guard":  ResilienceGuardAgent(),

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
        status_callback: StatusCallback | None = None,
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
            # task_summary enthaelt bei einem echten Provider-Ausfall bereits den konkreten
            # Grund (siehe TaskManager.decompose()) statt nur "keine Aufgaben abgeleitet".
            response = task_summary if task_summary.startswith("⚠️") else (
                "⚠️ Ich konnte keine passenden Aufgaben ableiten. Bitte beschreibe die Aufgabe genauer."
            )
            self._history.add_assistant_message(response)
            return response

        notify(f"📋 [bold white]Gesamtplan:[/bold white] {task_summary}")

        # Jede Teilaufgabe bekommt ab hier echten Zugriff auf das Projektverzeichnis
        # (read_file/write_file/edit_file/run_command/run_tests via agents/base_agent.py).
        project_dir = str(self._workspace.get_project_dir(project_slug))
        for t in agent_tasks:
            t.project_dir = project_dir
            t.max_tool_iterations = AGENT_MAX_TOOL_ITERATIONS.get(t.agent_id)  # None = config.MAX_AGENT_TOOL_ITERATIONS
            if t.agent_id in REVIEW_ONLY_AGENT_IDS:
                t.tools_read_only = True

        # Führe hierarchische Fachbereichs-Ausführung durch
        results, file_owners = await self._run_department_hierarchy(
            user_request=user_request,
            task_summary=task_summary,
            agent_tasks=agent_tasks,
            project_dir=project_dir,
            notify=notify,
        )

        # Fallback-Dateispeicherung: Falls ein Agent trotz Werkzeug-Zugriff Code nur im
        # Antworttext statt über write_file/edit_file geliefert hat, wird er zusätzlich
        # per Regex geparst – ohne bereits über Tools geschriebene Dateien zu überschreiben.
        saved_files_count = 0
        if AUTO_SAVE_WORKSPACE:
            for res in results:
                if res.success and res.content:
                    files = self._workspace.parse_and_save_files(
                        project_name=project_slug,
                        text_content=res.content,
                        agent_name=res.agent_name,
                    )
                    new_files = [f for f in files if f.relative_path not in file_owners]
                    saved_files_count += len(new_files)
                    for f in new_files:
                        file_owners[f.relative_path] = res.agent_id

            if saved_files_count > 0:
                notify(f"💾 [green]Workspace:[/green] {saved_files_count} zusätzliche Projektdateien (Text-Fallback) in `workspace/{project_slug}/` gespeichert.")

        # Echte Verifikation: Abhängigkeiten installieren, Tests wirklich ausführen,
        # bei Fehlschlägen gezielt den verantwortlichen Agenten korrigieren lassen.
        results, verification_summary = await self._run_verification_loop(
            project_dir=project_dir,
            all_results=results,
            file_owners=file_owners,
            notify=notify,
        )

        # Projekt-Hygiene: automatisch regenerierbare Caches (__pycache__, .pytest_cache, …),
        # die die echte Testausführung gerade erzeugt hat, physisch entfernen. Bewusst OHNE
        # Bestätigungs-Gate, da ausschließlich sicher regenerierbare Verzeichnisse betroffen
        # sind (siehe project_cleaner_agent.SAFE_CACHE_DIR_NAMES) – nie Quellcode.
        cleaner = self._agents.get("project_cleaner")
        if cleaner and hasattr(cleaner, "clean_orphaned_files"):
            removed_caches = cleaner.clean_orphaned_files(project_dir)
            if removed_caches:
                notify(f"🧹 [dim]Projekt-Hygiene:[/dim] {len(removed_caches)} Cache-Verzeichnis(se) entfernt ({', '.join(removed_caches[:3])}{'…' if len(removed_caches) > 3 else ''}).")

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
            f"{verification_summary}\n\n"
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

    # ──────────────────────────────────────────────────────────────
    # Fachbereichs-Hierarchie mit ECHTER Teamleiter-Delegation & -Konsolidierung
    # ──────────────────────────────────────────────────────────────

    async def _run_department_hierarchy(
        self,
        user_request: str,
        task_summary: str,
        agent_tasks: list[AgentTask],
        project_dir: str,
        notify: Callable[[str], None],
    ) -> tuple[list[AgentResult], dict[str, str]]:
        """
        Führt alle 5 Fachbereichs-Phasen aus. Jede Phase lässt (sofern
        ENABLE_DEPARTMENT_LEAD_EXECUTION aktiv ist) den zuständigen Teamleiter
        per echtem LLM-Aufruf delegieren und konsolidieren – keine simulierten
        Statusmeldungen mehr, sondern echte Leitungs-Ergebnisse im Report.
        """
        all_results: list[AgentResult] = []
        file_owners: dict[str, str] = {}
        task_map = {t.agent_id: t for t in agent_tasks}
        running_context = ""  # Kompakter Kontext aus vorherigen Phasen (z.B. Planungsergebnisse)

        for dept_id, phase_label, icon, run_mode in PHASE_ORDER:
            member_ids = DEPARTMENT_DEFINITIONS[dept_id]["members"]
            member_tasks = [task_map[aid] for aid in member_ids if aid in task_map]
            if not member_tasks:
                continue

            lead = self._dept_leads[dept_id]
            notify(f"{icon} [bold cyan]{phase_label}[/bold cyan] (Geleitet von: {lead.name})...")

            if running_context:
                for task in member_tasks:
                    task.context += f"\n\n## Kontext aus vorherigen Fachbereichen:\n{running_context[:2500]}"

            # ── Echte Delegation durch den Teamleiter ──
            if ENABLE_DEPARTMENT_LEAD_EXECUTION:
                delegation = await self._run_department_delegation(lead, task_summary, member_tasks, project_dir)
                all_results.append(delegation)
                if delegation.success and delegation.content:
                    notify(f"  📤 [cyan]{lead.name} delegiert:[/cyan] {self._first_line(delegation.content)}")
                    for task in member_tasks:
                        task.context += f"\n\n## Arbeitsauftrag von {lead.name}:\n{delegation.content[:1200]}"
                else:
                    notify(f"  ⚠️ [yellow]{lead.name} konnte nicht delegieren ({delegation.error}) – Fachteam startet ohne Zusatzanweisung.[/yellow]")

            # ── Fachteam arbeitet (parallel oder sequentiell, je nach Phase) ──
            if run_mode == "parallel":
                for task in member_tasks:
                    notify(f"  ▶️ [yellow]Fachteam arbeitet:[/yellow] {self._agents[task.agent_id].name}...")
                member_results = await self._run_agents_parallel(member_tasks, notify=notify)
            else:
                member_results = []
                for task in member_tasks:
                    agent_name = self._agents[task.agent_id].name
                    notify(f"  ▶️ [yellow]Fachteam arbeitet:[/yellow] {agent_name}...")
                    start_t = time.monotonic()
                    res = await self._run_single_agent(task)
                    dur = time.monotonic() - start_t
                    member_results.append(res)
                    status_ico = "✅ [green]Fertig[/green]" if res.success else "❌ [red]Fehler[/red]"
                    notify(f"  {status_ico}: {agent_name} ({dur:.1f}s)")

            all_results.extend(member_results)
            self._update_file_owners(file_owners, member_results)
            # Auf die letzten ~3000 Zeichen begrenzen, damit der Kontext über 5 Phasen hinweg
            # nicht unbegrenzt wächst und jedem folgenden Agenten unnötig viele Tokens kostet.
            running_context = (running_context + self._format_results_for_review(member_results)[:2000])[-3000:]

            # ── Echte Konsolidierung durch den Teamleiter ──
            if ENABLE_DEPARTMENT_LEAD_EXECUTION:
                consolidation = await self._run_department_consolidation(lead, member_results, project_dir)
                all_results.append(consolidation)
                if consolidation.success and consolidation.content:
                    notify(f"  📥 [bold green]{lead.name} konsolidiert:[/bold green] {self._first_line(consolidation.content)}")
                else:
                    notify(f"  ⚠️ [yellow]{lead.name} konnte den Bereich nicht konsolidieren ({consolidation.error}).[/yellow]")
            else:
                notify(f"  📥 [dim]{phase_label} abgeschlossen ({len(member_results)} Ergebnisse).[/dim]")

        return all_results, file_owners

    async def _run_department_delegation(
        self,
        lead: DepartmentLeadAgent,
        task_summary: str,
        member_tasks: list[AgentTask],
        project_dir: str,
    ) -> AgentResult:
        """Lässt den Teamleiter per echtem LLM-Aufruf konkrete Arbeitsanweisungen für sein Team erstellen."""
        members_overview = "\n".join(f"- `{t.agent_id}`: {t.description}" for t in member_tasks)
        task = AgentTask(
            task_id=f"{lead.department_id}_delegate",
            agent_id=lead.department_id,
            description=(
                f"Der Hauptagent hat folgenden Ausschnitt der Gesamtaufgabe deinem Fachbereich zugewiesen:\n"
                f"{task_summary}\n\nGeplante Einzelaufgaben deines Teams für diese Runde:\n{members_overview}\n\n"
                f"Gib klare, priorisierte Arbeitsanweisungen für dein Team (max. ca. 100 Wörter je Mitglied). "
                f"Weise auf Schnittstellen zwischen den Mitgliedern hin, falls relevant."
            ),
            context="",
            project_dir=project_dir,
            allow_tools=True,
            tools_read_only=True,  # Delegation darf bestehenden Code lesen, aber nicht verändern
            max_tool_iterations=3,
        )
        return await lead.execute(task)

    async def _run_department_consolidation(
        self,
        lead: DepartmentLeadAgent,
        member_results: list[AgentResult],
        project_dir: str,
    ) -> AgentResult:
        """Lässt den Teamleiter die echten Ergebnisse seines Teams prüfen und konsolidieren."""
        results_text = self._format_results_for_review(member_results)
        task = AgentTask(
            task_id=f"{lead.department_id}_consolidate",
            agent_id=lead.department_id,
            description=(
                f"Deine Fachteam-Mitglieder haben folgende Ergebnisse geliefert:\n{results_text[:4000]}\n\n"
                f"Prüfe sie auf Vollständigkeit und Konsistenz (bei Bedarf über list_files/read_file gegen "
                f"den tatsächlichen Projektstand) und erstelle deinen offiziellen Fachbereichsbericht gemäß "
                f"deinem vorgegebenen Ausgabeformat."
            ),
            context="",
            project_dir=project_dir,
            allow_tools=True,
            tools_read_only=True,  # Konsolidierung prüft und berichtet, ändert keinen Code
            max_tool_iterations=4,
        )
        return await lead.execute(task)

    @staticmethod
    def _first_line(text: str, max_chars: int = 160) -> str:
        first = next((line.strip() for line in text.splitlines() if line.strip()), "")
        return (first[:max_chars] + "…") if len(first) > max_chars else first

    @staticmethod
    def _update_file_owners(file_owners: dict[str, str], results: list[AgentResult]) -> None:
        """Merkt sich, welcher Agent welche Datei tatsächlich geschrieben hat (für die Verifikationsschleife)."""
        for res in results:
            for rel_path in res.files_written:
                file_owners[rel_path] = res.agent_id

    def _format_results_for_review(self, results: list[AgentResult]) -> str:
        blocks = []
        for r in results:
            if r.success and r.content:
                files_note = f" (Dateien: {', '.join(r.files_written)})" if r.files_written else ""
                blocks.append(f"### Ergebnis von {r.agent_name}{files_note}:\n{r.content[:2000]}")
        return "\n\n".join(blocks)

    # ──────────────────────────────────────────────────────────────
    # Echte Verifikation: Dependency-Installation + tatsächliche Testausführung
    # ──────────────────────────────────────────────────────────────

    async def _run_verification_loop(
        self,
        project_dir: str,
        all_results: list[AgentResult],
        file_owners: dict[str, str],
        notify: Callable[[str], None],
    ) -> tuple[list[AgentResult], str]:
        """
        Ersetzt die alte Keyword-basierte Fix-Schleife. Installiert Abhängigkeiten
        in einer isolierten Umgebung, führt die echte Testsuite aus und schickt bei
        Fehlschlägen einen GEZIELTEN Korrekturauftrag an genau die Agenten, deren
        Dateien laut echtem Traceback betroffen sind.
        """
        verifier = ProjectVerifier(project_dir)
        summary_lines: list[str] = []

        notify("🧪 [bold cyan]Verifikation:[/bold cyan] Installiere Abhängigkeiten in isolierter Umgebung...")
        install_log = await asyncio.to_thread(verifier.ensure_environment)
        if install_log:
            notify(f"  📦 {install_log.splitlines()[0]}")
            summary_lines.append(f"- 📦 {install_log.splitlines()[0]}")

        for attempt in range(1, MAX_VERIFICATION_ITERATIONS + 1):
            notify(f"  🧪 [yellow]Testlauf {attempt}/{MAX_VERIFICATION_ITERATIONS}:[/yellow] Führe echte Tests aus...")
            report = await asyncio.to_thread(verifier.run_tests)

            if not report.ran:
                notify(f"  ℹ️ [dim]{report.reason_skipped}[/dim]")
                summary_lines.append(f"- ℹ️ {report.reason_skipped}")
                break

            if report.passed:
                notify(f"  ✅ [bold green]Alle Tests bestanden[/bold green] (Versuch {attempt}, {report.duration_seconds:.1f}s).")
                summary_lines.append(f"- ✅ Echte Testsuite bestanden nach {attempt} Durchlauf/Durchläufen ({report.duration_seconds:.1f}s).")
                break

            notify(f"  ❌ [bold red]{len(report.failures)} Testfehler[/bold red] – ermittle betroffene Agenten aus dem echten Traceback...")

            agents_to_fix: dict[str, list] = {}
            for failure in report.failures:
                owners = {file_owners[f] for f in failure.files if f in file_owners}
                if not owners and any(r.agent_id == "tester" for r in all_results):
                    owners = {"tester"}
                for owner in owners:
                    if owner in self._agents:
                        agents_to_fix.setdefault(owner, []).append(failure)

            if not agents_to_fix:
                notify("  ⚠️ [yellow]Testfehler konnten keinem Agenten eindeutig zugeordnet werden – Auto-Fix abgebrochen.[/yellow]")
                summary_lines.append(f"- ⚠️ Versuch {attempt}: {len(report.failures)} Testfehler blieben ungelöst (keine eindeutige Dateizuordnung im Traceback).")
                break

            fix_tasks = []
            for agent_id, fails in agents_to_fix.items():
                failure_text = "\n\n".join(
                    f"Test: {f.test_id}\nFehlermeldung: {f.message}\nBetroffene Dateien: {', '.join(f.files) or 'unbekannt'}"
                    for f in fails
                )
                fix_tasks.append(AgentTask(
                    task_id=f"verify_fix_{agent_id}_{attempt}",
                    agent_id=agent_id,
                    description=(
                        f"Die ECHTE automatische Testsuite ist fehlgeschlagen (kein Schätzwert, sondern realer "
                        f"pytest/unittest-Output). Nutze read_file, um die betroffene(n) Datei(en) zu prüfen, und "
                        f"edit_file/write_file, um den Fehler zu beheben. Verifiziere deinen Fix danach mit run_tests.\n\n"
                        f"{failure_text}"
                    ),
                    context="",
                    project_dir=project_dir,
                ))

            notify(f"  🛠️ [bold yellow]Gezielter Auto-Fix:[/bold yellow] Beauftrage {', '.join(agents_to_fix.keys())} (nicht blind alle Dev-Agenten)...")
            fix_results = await self._run_agents_parallel(fix_tasks, notify=notify)
            self._update_file_owners(file_owners, fix_results)
            all_results.extend(fix_results)
            summary_lines.append(f"- 🛠️ Versuch {attempt}: {len(report.failures)} echte Testfehler → gezielt zur Korrektur an {', '.join(agents_to_fix.keys())} zurückgespielt.")

            if attempt == MAX_VERIFICATION_ITERATIONS:
                notify("  ⚠️ [yellow]Maximale Verifikations-Iterationen erreicht – letzter Stand wird übernommen.[/yellow]")
                summary_lines.append(f"- ⚠️ Nach {MAX_VERIFICATION_ITERATIONS} Versuchen nicht vollständig grün – letzter Stand wurde übernommen.")

        verification_summary = "### 🧪 Verifikations-Protokoll (echte Dependency-Installation & Testausführung)\n" + (
            "\n".join(summary_lines) if summary_lines else "- Keine Verifikation durchgeführt."
        )
        return all_results, verification_summary

    # ──────────────────────────────────────────────────────────────
    # Ausführungs-Helfer
    # ──────────────────────────────────────────────────────────────

    async def _run_single_agent(self, task: AgentTask) -> AgentResult:
        agent = self._agents.get(task.agent_id) or self._dept_leads.get(task.agent_id)
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
        notify: Callable[[str], None] | None = None,
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
    ) -> AgentResult | None:
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
    ) -> AgentResult | None:
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
        total_tool_calls = sum(r.tool_calls_count for r in results)
        total_files_written = len({f for r in results for f in r.files_written})

        lines = [
            "### 📈 Projekt-Kennzahlen & Ressourcen-Verbrauch\n",
            f"- ⏱️ **Gesamtdauer:** `{total_duration:.2f} Sekunden`",
            f"- 🪙 **Gesamtverbrauch Tokens:** `{grand_total_tokens:,}` (Prompt: `{total_prompt_tokens:,}` | Completion: `{total_completion_tokens:,}`)",
            f"- 🛠️ **Werkzeug-Aufrufe (echte Datei-/Testoperationen):** `{total_tool_calls:,}` | **Dateien geschrieben/geändert:** `{total_files_written}`",
            f"- 📁 **Projektverzeichnis:** `workspace/{project_slug}/`\n",
            "| KI-Agent | Rolle / Fachbereich | Modell | Dauer | Tokens | Tool-Calls | Status |",
            "|---|---|---|---|---|---|---|",
        ]

        for r in results:
            status_icon = "✅" if r.success else "❌"
            lines.append(
                f"| **{r.agent_name}** | `{r.agent_id}` | `{r.model_used or 'default'}` | {r.duration_seconds:.1f}s | {r.total_tokens:,} | {r.tool_calls_count} | {status_icon} |"
            )

        lines.append(
            f"| **Hauptagent (Synthese)** | `orchestrator` | `{ORCHESTRATOR_MODEL}` | - | {synth_tokens:,} | - | ✅ |"
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

        for info in DEPARTMENT_DEFINITIONS.values():
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

    def get_history(self) -> ConversationHistory:
        return self._history

    def get_workspace_manager(self) -> WorkspaceManager:
        return self._workspace
