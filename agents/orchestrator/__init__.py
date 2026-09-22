"""
agents/orchestrator/ – Der Hauptagent (Orchestrator) mit Fachbereichs-Teamleiter-Hierarchie.

Ablauf: Die Nutzeraufgabe wird zerlegt und auf 6 Fachbereichsleiter verteilt. Jeder Leiter
delegiert per echtem LLM-Aufruf an sein Fachteam (mit Datei-/Werkzeugzugriff, siehe
agents/base_agent.py) und konsolidiert die Ergebnisse zu einem Fachbereichsbericht. Danach
laufen echte Dependency-Installation und Testsuite (core/verifier.py); anhand der Tracebacks
bekommt gezielt der Agent den Fix-Auftrag, der die betroffene Datei geschrieben hat.
Abschließend werden alle Berichte zum Gesamtergebnis synthetisiert.

Die Logik ist auf Mixins verteilt (department, verification, dispatch, budget, retrospective,
reporting, constants ...), die diese Orchestrator-Klasse zusammensetzt. Alle bisherigen
Importpfade (`from agents.orchestrator import Orchestrator, ...`) bleiben nutzbar.
"""

import asyncio
import logging
import time
import traceback
import uuid
from collections.abc import Callable
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

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
from agents.orchestrator.budget import BudgetMixin
from agents.orchestrator.constants import PHASE_ORDER, REVIEW_ONLY_AGENT_IDS, PlanConfirmationCallback, StatusCallback
from agents.orchestrator.department import DepartmentMixin
from agents.orchestrator.dispatch import DispatchMixin
from agents.orchestrator.efficiency import EfficiencyMixin
from agents.orchestrator.governance import GovernanceMixin
from agents.orchestrator.integration import IntegrationMixin
from agents.orchestrator.reporting import ReportingMixin
from agents.orchestrator.retrospective import RetrospectiveMixin
from agents.orchestrator.team_communication import TeamCommunicationMixin
from agents.orchestrator.verification import VerificationMixin
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
    BASE_DIR,
    CAPACITY_GATE_MODE,
    ENABLE_ACCEPTANCE_CHECK,
    ENABLE_REVIEW_AFTER_VERIFICATION,
    HEAVY_MODEL,
    MIN_TEST_COVERAGE,
    ORCHESTRATOR_MODEL,
    PLAN_CONFIRMATION_MIN_TASKS,
)
from core.acceptance_check import extract_requirements, verify_acceptance
from core.adr import format_adr_summary_for_context
from core.backlog_store import get_ticket, upsert_ticket
from core.capacity_gate import assess_run_capacity, model_unreachable_reason
from core.decision_log import log_decision
from core.definition_of_done import build_definition_of_done, write_definition_of_done
from core.design_system import format_design_system_for_agents
from core.framework_revision import current_revision
from core.git_isolation import (
    GitIsolationError,
    create_isolated_worktree,
    find_git_root,
    has_uncommitted_changes,
)
from core.message_bus import AgentTask
from core.model_ab_trials import evaluate_trials, start_trials_from_report
from core.notifier import notify_external
from core.optimization_advisor import analyze as analyze_optimization_potential
from core.optimization_advisor import (
    apply_auto_tuning,
    close_resolved_unused_agent_tickets,
    record_suggestions_as_lessons,
    record_unused_agent_tickets,
)
from core.optimization_advisor import format_report_for_humans as format_optimization_report
from core.project_constitution import format_constitution_for_agents, get_max_project_tokens
from core.project_status import (
    MAX_FAILURE_DETAIL_CHARS,
    count_consecutive_failed_runs,
    format_context_for_agents,
    has_open_blocker_ticket,
    has_repeated_failure,
    has_repeated_lint_finding,
    read_status,
    save_project_checkpoint,
)
from core.quota_estimator import QuotaEstimator
from core.result_aggregator import ResultAggregator
from core.run_logger import RunLogger
from core.run_postmortem import generate_postmortem
from core.secret_scanner import scan_directory
from core.task_manager import TaskManager
from core.team_memory import auto_link_lessons_to_rules, format_team_lessons_for_agents, record_lesson
from core.token_guard import token_guard
from core.verification_outcome import VerificationOutcome
from core.workspace import WorkspaceManager
from memory.conversation_history import ConversationHistory
from memory.cost_history import record_run_usage
from memory.run_history import get_total_tokens_for_project
from memory.run_history import record_run as record_run_history

__all__ = [
    "Orchestrator",
    "StatusCallback",
    "PlanConfirmationCallback",
    "REVIEW_ONLY_AGENT_IDS",
    "PHASE_ORDER",
]

class Orchestrator(
    DepartmentMixin,
    IntegrationMixin,
    VerificationMixin,
    GovernanceMixin,
    DispatchMixin,
    BudgetMixin,
    RetrospectiveMixin,
    ReportingMixin,
    TeamCommunicationMixin,
    EfficiencyMixin,
):
    """
    Hauptagent, der die 6 Fachbereichs-Teamleiter und deren 33 Spezialisten koordiniert.
    """

    def __init__(self, escalate_models: bool = False):
        """
        escalate_models: Von core/backlog_worker.py ab dem ZWEITEN automatischen Versuch eines
        Governance-/Verifikations-Retry-Tickets gesetzt. Ohne das würde der Retry mit exakt
        demselben Agenten/Modell erneut scheitern. Siehe _escalate_agent_models().
        """
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
        if escalate_models:
            self._escalate_agent_models()

        self._task_manager = TaskManager(model_name=ORCHESTRATOR_MODEL)
        self._result_aggregator = ResultAggregator(model_name=ORCHESTRATOR_MODEL)
        self._history = ConversationHistory()
        self._workspace = WorkspaceManager()

        # Vom TaskManager erzeugte Kurzfassung der letzten Aufgabe (nicht die rohe
        # Nutzereingabe) – von interface/cli.py als Commit-Message genutzt.
        self.last_task_summary: str = ""
        # Sanitisierter Projekt-Slug des letzten Laufs – Commit-Message-Fallback, falls
        # last_task_summary doch nur ein Echo der rohen Nutzereingabe ist.
        self.last_project_slug: str = ""
        # Zuletzt angelegter isolierter Git-Worktree (core/git_isolation.py). Wird NICHT
        # automatisch entfernt; der Mensch reviewt/merged/löscht ihn bewusst selbst.
        self.last_isolated_worktree = None
        # ReviewFinding-Objekte (core/review_gate.py), die auch nach Fix-Loop und Re-Review
        # noch bestehen. interface/cli.py bzw. core/backlog_worker.py machen daraus nach einem
        # erfolgreichen PR echte, dateibezogene GitHub-Review-Kommentare, statt den Befund nur
        # im PR-Body zu verstecken. Leer im Normalfall.
        self.last_unresolved_review_findings: list = []
        # True NUR, wenn die echte Testsuite des letzten Laufs gelaufen UND bestanden ist –
        # interface/cli.py warnt damit vor dem Git-Push-Gate.
        self.last_verification_ok: bool = False
        # Vollständiges Verifikations-Protokoll des letzten Laufs. interface/cli.py bettet es
        # in den PR-Body ein, damit ein Reviewer ohne Terminal-Session erkennt, ob die
        # Testsuite je bestätigt bestanden hat.
        self.last_verification_summary: str = ""
        # True, wenn eine Fachrolle `ask_human_for_clarification` genutzt hat. Bewusst getrennt
        # von last_verification_ok: eine offene Rückfrage ist ein anderer Grund zum Misstrauen
        # als ein Testfehler und verdient eigenen Klartext im Push-Gate.
        self.last_needs_human_input: bool = False
        self.last_clarification_questions: list[str] = []
        # True, wenn MAX_RUN_TOKENS oder das Pro-Projekt-Budget überschritten wurde und deshalb
        # Fachbereiche übersprungen wurden – interface/cli.py macht das im PR genauso sichtbar
        # wie eine fehlgeschlagene Verifikation.
        self.last_budget_aborted: bool = False
        # Strukturiertes Lauf-Protokoll (core/run_logger.py). Erst in process() gesetzt, sobald
        # der Projektname feststeht - Aufrufer müssen defensiv auf None prüfen.
        self._run_logger: RunLogger | None = None
        # Pro process()-Lauf zurückgesetzt, hier zusätzlich vorbelegt: dispatch.py kann auch
        # von Aufrufern genutzt werden, die nicht über process() gehen (core/backlog_worker.py).
        self._provider_exhausted_this_run: bool = False
        self._provider_breaker_tripped: bool = False
        # Speicher hinter DispatchMixin._infra_results_this_run (laufweite Breaker-Quote).
        self._infra_results_store: list = []
        # True, wenn department.py die Generierungsphase NUR wegen der
        # VERIFICATION_TOKEN_RESERVE_RATIO-Reserve gestoppt hat, nicht wegen des vollen
        # Budgets. Dieses Flag darf die Verifikation NICHT überspringen lassen - genau dafür
        # wurde die Reserve freigehalten.
        self._generation_budget_reached_this_run: bool = False
        # Maschinenlesbares Ergebnis der Fertigstellungs-Pruefung (core/definition_of_done.py) -
        # belastbare Quelle, statt den Zustand aus Berichtstext zu raten.
        self.last_definition_of_done = None
        # Pro-Projekt-Kostenbudget (core/project_constitution.py) über ALLE Läufe hinweg -
        # unabhängig von MAX_RUN_TOKENS, das nur einen einzelnen Lauf begrenzt. 0 = inaktiv.
        # _project_tokens_before_run ist die bereits in früheren Läufen verbrauchte Summe.
        self._project_token_budget: int = 0
        self._project_tokens_before_run: int = 0

    def _escalate_agent_models(self, agent_ids: set[str] | None = None) -> set[str]:
        """
        Stuft jeden Fachagenten, der nicht ohnehin schon auf HEAVY_MODEL läuft, hoch.
        Best-effort: ein Agent, dessen Modell-Erstellung fehlschlägt (z.B. fehlender API-Key),
        behält sein bisheriges Modell statt den Lauf zu verhindern.

        agent_ids: None eskaliert ALLE Fachagenten (so nutzt es core/backlog_worker.py beim
        Retry). Eine konkrete Menge eskaliert nur diese - innerhalb EINES Laufs ist bereits
        bekannt, welche Agenten an der steckenden Datei hängen; alle 33 hochzustufen wäre
        unnötiger Mehrverbrauch.

        Gibt die IDs der tatsächlich hochgestuften Agenten zurück - eine leere Menge, wenn
        HEAVY_MODEL gerade nachweislich nicht erreichbar ist (kein Key oder Kontingent auf
        Cooldown). Der Aufrufer sieht daran, dass eine Modell-Eskalation sinnlos wäre, BEVOR er
        einen kompletten Agenten-Aufruf dafür verbrennt: `LLMFactory.create_for_model()` würde
        auch für ein erschöpftes Modell erfolgreich ein Client-Objekt liefern, der Aufruf fiele
        dann aber intern auf ein schwächeres Modell zurück als das, mit dem der Fix zuvor schon
        gescheitert ist (realer Fund aetherqueue/eventforge_core, siehe
        core/capacity_gate.py.model_unreachable_reason()).
        """
        import config
        from core.capacity_gate import model_unreachable_reason
        from core.llm_factory import LLMFactory, is_same_model
        heavy_model = config.HEAVY_MODEL
        self.last_model_escalation_blocked_reason = model_unreachable_reason(heavy_model)
        if self.last_model_escalation_blocked_reason:
            return set()
        targets = self._agents.items() if agent_ids is None else (
            (aid, self._agents[aid]) for aid in agent_ids if aid in self._agents
        )
        escalated: set[str] = set()
        for agent_id, agent in targets:
            # Kanonischer Vergleich statt `==`: Client-Wrapper entfernen das Provider-Präfix
            # ("groq:openai/gpt-oss-120b" -> "openai/gpt-oss-120b"), ein direkter Vergleich
            # hielte bereits hochgestufte Agenten fälschlich für nicht hochgestuft.
            if is_same_model(agent._llm.model_name, heavy_model):
                continue
            try:
                agent._llm = LLMFactory.create_for_model(heavy_model)
                escalated.add(agent_id)
            except Exception:
                continue
        return escalated

    async def process(
        self,
        user_request: str,
        status_callback: StatusCallback | None = None,
        forced_project_dir: str | None = None,
        plan_confirmation_callback: PlanConfirmationCallback | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> str:
        """Führt einen Lauf aus (siehe _process_impl) und garantiert, dass sein Lauf-Log IMMER mit
        `run_closed` endet - sonst fehlen früh abgebrochene oder abgestürzte Läufe in jeder
        Auswertung. Der Logger wird vorab zurückgesetzt, damit frühe Agenten-Aufrufe nicht in das
        Log des VORHERIGEN Laufs derselben Orchestrator-Instanz geschrieben werden."""
        self._run_logger = None
        self._begin_efficiency_tracking()
        try:
            return await self._process_impl(
                user_request, status_callback, forced_project_dir, plan_confirmation_callback, cancel_requested,
            )
        except BaseException as exc:
            # Der reine Exception-Klassenname ("exception:TypeError") ist ohne Zeile, Modul und
            # Nachricht nicht diagnostizierbar. Deshalb der volle Traceback - auf die letzten
            # 1000 Zeichen gedeckelt, dort stehen Fehlermeldung und tiefste Stack-Frames -
            # sowohl im Lauf-Log (für core/root_cause_analyst.py) als auch als eigenes Ticket.
            # Dieses Ticket ist bewusst NICHT autonom (siehe _AUTONOMOUS_SOURCES in
            # core/backlog_worker.py): ein Crash hat potenziell eine Framework-Ursache und ist
            # kein Programmierauftrag.
            tb = traceback.format_exc()[-1000:]
            self._close_unfinished_run_log(f"exception:{type(exc).__name__}", traceback_text=tb)
            self._record_crash_ticket(exc, tb)
            raise
        finally:
            self._stop_team_board()
            self._close_unfinished_run_log("returned_without_close")

    def _close_unfinished_run_log(self, reason: str, *, traceback_text: str = "") -> None:
        """Schließt ein noch offenes Lauf-Log als abgebrochen - No-Op, wenn bereits geschlossen."""
        run_logger = self._run_logger
        if run_logger is None or run_logger.closed:
            return
        try:
            close_fields: dict = {"verification_ok": False, "aborted": True, "abort_reason": reason}
            if traceback_text:
                close_fields["traceback"] = traceback_text
            run_logger.close(**close_fields)
        except Exception as e:
            logging.getLogger(__name__).warning("Lauf-Log konnte nicht abgeschlossen werden: %s", e)

    def _record_crash_ticket(self, exc: BaseException, tb: str) -> None:
        """Legt bei einem unbehandelten Absturz von process() ein Backlog-Ticket mit gedeckeltem
        Traceback an - best-effort, ein Fehler hier darf den Absturz-Pfad nicht verschlimmern."""
        try:
            slug = self.last_project_slug or "unbekannt"
            # Stabile, zeitstempelfreie ticket_id (Exception-Klasse + Slug): dedupliziert
            # wiederholte Abstürze derselben Ursache zu EINEM Ticket.
            ticket_id = f"orchestrator-crash-{type(exc).__name__}-{slug}"
            upsert_ticket(
                ticket_id=ticket_id,
                title=f"Orchestrator-Absturz ({type(exc).__name__}) bei {slug}",
                source="orchestrator_crash",
                status="blocked",
                project_slug=slug,
                detail=f"{exc}\n\n{tb}"[:1200],
            )
        except Exception as e:
            logging.getLogger(__name__).warning("Absturz-Ticket konnte nicht angelegt werden: %s", e)

    async def _process_impl(
        self,
        user_request: str,
        status_callback: StatusCallback | None = None,
        forced_project_dir: str | None = None,
        plan_confirmation_callback: PlanConfirmationCallback | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> str:
        """
        plan_confirmation_callback: Wird NACH der Zerlegung, aber VOR jeder Ausführung
        aufgerufen, sofern der Plan mindestens PLAN_CONFIRMATION_MIN_TASKS Teilaufgaben umfasst
        (kleine Aufgaben laufen ohne Rückfrage durch). Bei Ablehnung bricht der Lauf ab, ohne
        dass ein Agent gestartet wurde.

        cancel_requested: Wird vor jeder Fachbereichs-Phase und jedem Verifikations-/Fixversuch
        abgefragt (dieselben Prüfpunkte wie das MAX_RUN_TOKENS-Budget). Bei True wird graceful
        beendet: verbleibende Arbeit übersprungen, bereits Erarbeitetes trotzdem synthetisiert.
        None = kein Abbruch-Mechanismus (nur CLI/Dashboard reichen einen echten Callback durch).

        forced_project_dir: Von interface/cli.py nach `/load <projekt>` befüllt - der Lauf
        arbeitet dann IMMER in diesem Verzeichnis statt in einem frisch geratenen project_slug.
        Ohne das landete jede Chat-Nachricht trotz `/load` in einem neuen Workspace-Ordner.
        """
        overall_start_time = time.monotonic()
        # Reset gegen Datenleck aus einem VORHERIGEN process()-Aufruf derselben Instanz: sonst
        # trüge ein erfolgreicher Lauf noch die unbehobenen Befunde des letzten Laufs, falls er
        # die entsprechende Fix-Schleife gar nicht durchläuft.
        self.last_unresolved_review_findings = []
        # Schnappschuss des GLOBALEN Tokenzählers (core/token_guard.py), nicht der Zähler selbst:
        # ein Prozess teilt sich mehrere Läufe. Der Verbrauch DIESES Laufs ist die Differenz
        # (_tokens_used_since()) und Grundlage des harten MAX_RUN_TOKENS-Budgets.
        run_start_tokens = token_guard.get_summary()["grand_total_tokens"]
        # Zusätzlich die Pro-Modell-Aufschlüsselung sichern – Basis für die sitzungsübergreifende
        # Kosten-Historie (memory/cost_history.py), die pro Modell/Provider mitschreibt.
        run_start_model_stats = token_guard.get_summary()["models"]

        def notify(msg: str):
            if status_callback:
                status_callback(msg)

        notify("⚡ [bold cyan]Phase 0/5:[/bold cyan] Hauptagent analysiert Aufgabe und weist Fachbereichs-Teamleiter zu...")
        self._history.add_user_message(user_request)

        existing_projects = self._workspace.list_projects()
        context = self._history.get_context_string(max_messages=4)
        task_summary, project_slug, agent_tasks = await self._task_manager.decompose(
            user_request, conversation_context=context, existing_projects=existing_projects
        )
        # Für die Commit-Message-Vorschau in interface/cli.py. Bei einem Abbruch unten (keine
        # Aufgaben ableitbar) bewusst nicht überschrieben.
        if agent_tasks:
            self.last_task_summary = task_summary

        if not agent_tasks:
            # task_summary enthaelt bei Provider-Ausfall ("⚠️") oder Rueckfrage zu unklarer
            # Aufgabe ("❓", TaskManager.decompose()) bereits den Grund - sonst Fallback.
            response = task_summary if task_summary.startswith(("⚠️", "❓")) else (
                "⚠️ Ich konnte keine passenden Aufgaben ableiten. Bitte beschreibe die Aufgabe genauer."
            )
            self._history.add_assistant_message(response)
            return response

        notify(f"📋 [bold white]Gesamtplan:[/bold white] {task_summary}")

        # Plan-Freigabe-Gate: NACH der Zerlegung, VOR jeder Ausführung - bis hier hat kein Agent
        # einen Token verbraucht. Erst ab PLAN_CONFIRMATION_MIN_TASKS, damit kleine Aufgaben
        # ohne Rückfrage durchlaufen.
        if plan_confirmation_callback and len(agent_tasks) >= PLAN_CONFIRMATION_MIN_TASKS:
            approved = await plan_confirmation_callback(task_summary, project_slug, agent_tasks)
            if not approved:
                response = (
                    "↩️ Abgebrochen – der geplante Aufgaben-Umfang wurde nicht bestätigt. "
                    "Beschreibe die Aufgabe bei Bedarf enger, dann versuche ich es erneut."
                )
                self._history.add_assistant_message(response)
                return response

        if forced_project_dir:
            # Per /load geladenes Projekt: der geratene project_slug wird bewusst ignoriert –
            # der Mensch hat das Zielverzeichnis selbst gewählt.
            candidate_dir = forced_project_dir
            notify(f"📂 [dim]Arbeite im geladenen Projekt: {candidate_dir}[/dim]")
        else:
            existing_projects = self._workspace.list_projects()
            # Automatische Erkennung bestehender Projekte (verhindert _repair-Duplikate)
            matched_project = self._match_existing_project(project_slug, user_request, existing_projects)
            if matched_project and matched_project != project_slug:
                notify(
                    f"🎯 [bold cyan]Bestehendes Projekt erkannt:[/bold cyan] `{matched_project}` existiert bereits "
                    f"und passt zur Anfrage – arbeite direkt darin statt neuen Ordner `{project_slug}` anzulegen."
                )
                project_slug = matched_project

            # Frühwarnung vor stillschweigend doppelter Arbeit: project_slug wird pro Lauf neu
            # geraten und unterscheidet sich oft, obwohl die Aufgabe dieselbe ist - so entstanden
            # mehrfach zwei komplette, separat bezahlte Läufe für dieselbe Anwendung. Rein
            # informativ (kein LLM-Aufruf); der Mensch entscheidet über `/load <name>`.
            if project_slug not in existing_projects and existing_projects:
                # Zeigt zusätzlich den zuletzt protokollierten Status jedes vorhandenen Projekts:
                # die reine Namensliste macht nicht sichtbar, dass ein vorhandenes Projekt beim
                # letzten Lauf nicht verifiziert werden konnte - ein neuer Versuch wirkt dadurch
                # günstiger, als er ist.
                def _last_status_icon(name: str) -> str:
                    history = read_status(str(self._workspace.get_project_dir(name)))
                    if not history:
                        return ""
                    last = history[0]
                    if last.get("verification_ok"):
                        return " ✅"
                    if last.get("cancelled"):
                        return " ⏹️"
                    if last.get("budget_aborted"):
                        return " 🚫"
                    return " ⚠️"

                shown = ", ".join(f"{name}{_last_status_icon(name)}" for name in existing_projects[:10])
                more = f" (+{len(existing_projects) - 10} weitere)" if len(existing_projects) > 10 else ""
                # Eigene, vorangestellte Zeile für das Projekt DIESER Sitzung: bei mehreren
                # kurz aufeinanderfolgenden Läufen (z.B. eine beim Einfügen zerrissene Eingabe)
                # ging der Hinweis sonst in der Liste älterer Projekte unter.
                same_session_hint = ""
                if self.last_project_slug and self.last_project_slug != project_slug:
                    same_session_hint = (
                        f"🕒 [dim]Hinweis: In DIESER Sitzung wurde zuletzt an `{self.last_project_slug}` "
                        f"gearbeitet – falls die aktuelle Anfrage eigentlich eine Fortsetzung davon ist "
                        f"(z.B. weil eine längere Eingabe in mehrere Nachrichten zerrissen ankam), "
                        f"lieber abbrechen und stattdessen `/load {self.last_project_slug}` nutzen.[/dim]\n"
                    )
                # Eigener Hinweis bei einem Nahezu-Duplikat (Unterstrich/Bindestrich/Groß-
                # Kleinschreibung ignoriert): so ein fast identischer Name fällt in der
                # generischen "Bereits vorhanden"-Liste nicht auf.
                near_duplicate = self._find_near_duplicate_slug(project_slug, existing_projects)
                near_duplicate_hint = ""
                if near_duplicate:
                    near_duplicate_hint = (
                        f"❗ [yellow]Achtung: `{near_duplicate}` existiert bereits im Workspace und "
                        f"unterscheidet sich vom neuen Slug `{project_slug}` nur durch Schreibweise "
                        f"(Unterstrich/Bindestrich/Groß-Kleinschreibung) – vermutlich dieselbe Aufgabe. "
                        f"Falls ja, lieber abbrechen und `/load {near_duplicate}` nutzen.[/yellow]\n"
                    )
                notify(
                    f"{same_session_hint}"
                    f"{near_duplicate_hint}"
                    f"🗂️ [dim]Neues Projekt '{project_slug}' wird angelegt. Bereits vorhanden: "
                    f"{shown}{more} (letzter Lauf: ✅ verifiziert / ⚠️ nicht verifiziert / "
                    f"🚫 Budget erreicht / ⏹️ abgebrochen, ohne Symbol = noch kein Lauf protokolliert) "
                    f"– falls du an einem davon weiterarbeiten wolltest, nutze stattdessen "
                    f"`/load <name>`.[/dim]"
                )

            # get_project_dir() legt das Verzeichnis bei Bedarf leer an (mkdir) - die
            # Isolationsentscheidung unten prüft trotzdem korrekt auf "bereits vorhandenen
            # Inhalt", da ein frisch angelegtes Verzeichnis dabei leer bleibt.
            candidate_dir = str(self._workspace.get_project_dir(project_slug))

        # Ab hier hat jede Teilaufgabe echten Schreibzugriff auf das Projektverzeichnis
        # (agents/base_agent.py). _resolve_project_isolation() isoliert deshalb IMMER, wenn am
        # Zielort bereits echter Inhalt existiert; ein leeres, neues Projekt hat nichts zu
        # verlieren und wird ohne Worktree-Overhead direkt geschrieben.
        project_dir, abort_response = await self._resolve_project_isolation(candidate_dir, task_summary, notify)
        if abort_response:
            self._history.add_assistant_message(abort_response)
            return abort_response

        # Der TATSÄCHLICH verwendete Ordnername (nicht der bei forced_project_dir verworfene
        # project_slug) – zuverlässiger Commit-Message-Fallback.
        self.last_project_slug = Path(project_dir).name

        # Erst jetzt ist der Projektname für einen sprechenden Log-Dateinamen bekannt. Rein
        # additiv: schlägt das Anlegen fehl, läuft der Lauf ohne Protokoll weiter.
        try:
            self._run_logger = RunLogger(project_slug=self.last_project_slug, project_dir=project_dir)
            # Codeversion im Log (core/framework_revision.py): sonst lässt sich nachträglich
            # nicht belegen, welcher Framework-Stand den Lauf ausgeführt hat.
            revision = current_revision()
            self._run_logger.log_event(
                "run_started",
                task_summary=task_summary,
                user_request=user_request[:2000],
                project_dir=str(project_dir),
                framework_commit=revision.commit,
                framework_dirty=revision.dirty,
            )
        except Exception as e:
            logging.getLogger(__name__).warning("Lauf-Log konnte nicht angelegt werden – Lauf ohne Protokoll: %r", e)
            self._run_logger = None

        # Team-Board für diesen Lauf (core/team_board.py): Übergaben, Datei-Owner, Fragen im Team.
        self._start_team_board(
            project_dir, getattr(self._run_logger, "stamp", None) or datetime.now().strftime("%Y%m%d_%H%M%S"),
        )

        # Abnahme-Phase 1/2 (P4-2, core/acceptance_check.py): Anforderungsliste AUS DEM
        # AUFTRAGSTEXT destillieren, BEVOR irgendein Fachbereich zu arbeiten beginnt - Phase 2
        # (Abgleich gegen den tatsächlichen Code) läuft erst nach der Entwicklung/Verifikation
        # weiter unten. Best-effort: ein Fehler hier blockiert den Lauf nie.
        self.last_acceptance_requirements: list[str] = []
        if ENABLE_ACCEPTANCE_CHECK and "product_owner" in self._agents:
            try:
                self.last_acceptance_requirements = await extract_requirements(self, user_request, project_dir)
            except Exception as e:
                notify(f"⚠️ [dim yellow]Anforderungs-Extraktion für die Abnahme konnte nicht laufen: {e}[/dim yellow]")

        # Ab der dritten Runde ohne bestandene Verifikation in Folge wird die Warnung deutlich
        # direkter und nennt konkrete Handlungsoptionen - "einfach nochmal versuchen" wirkt
        # sonst jedes Mal günstiger, als es ist. Bewusst KEIN automatisches Eingreifen: der
        # Mensch entscheidet, der Lauf wird nicht blockiert.
        consecutive_failures = count_consecutive_failed_runs(project_dir)
        if consecutive_failures >= 2:
            notify(
                f"🔁 [bold yellow]Wiederholtes Scheitern:[/bold yellow] Die letzten "
                f"{consecutive_failures} Läufe an `{self.last_project_slug}` endeten OHNE "
                f"bestandene Verifikation (siehe `.ai_team_status.json`). Bevor ein weiterer "
                f"kompletter Lauf startet, lieber prüfen: (1) Aufgabe in kleinere Schritte "
                f"zerlegen statt alles auf einmal zu verlangen, (2) `/constitution` – reicht "
                f"das Projekt-Budget für die tatsächliche Komplexität, (3) den letzten "
                f"Verifikations-Bericht lesen – wiederholt sich derselbe Fehler?"
            )

            # Härteres Gate als der reine Hinweis oben: eine Prompt-Warnung allein verhindert
            # nicht, dass dieselben Fachbereiche denselben Ansatz wiederholen. Ab 2 Fehlschlägen
            # in Folge wird architect deshalb DETERMINISTISCH als erste Teilaufgabe eingeplant
            # (falls nicht ohnehin im Plan) und bekommt den letzten Fehler direkt mit.
            if agent_tasks and "architect" not in {t.agent_id for t in agent_tasks}:
                last_detail = next(
                    (e.get("failure_detail") for e in read_status(project_dir) if e.get("failure_detail")), ""
                )
                notify(
                    "  🧭 [bold yellow]architect wird zusätzlich eingeplant[/bold yellow] – nach wiederholtem "
                    "Scheitern reicht ein weiterer Versuch derselben Fachbereiche nicht: architect prüft "
                    "zuerst gezielt die Ursache, bevor der Rest des Teams erneut denselben Ansatz wiederholt."
                )
                agent_tasks.insert(0, AgentTask(
                    task_id=str(uuid.uuid4())[:8],
                    agent_id="architect",
                    description=(
                        "Wiederholtes Scheitern an diesem Projekt (mindestens 2 Läufe in Folge ohne "
                        "bestandene Verifikation). Analysiere GEZIELT die Ursache des letzten "
                        "Fehlschlags und liefere eine konkrete technische Root-Cause-Einschätzung samt "
                        "empfohlener Architektur-/Vorgehensänderung, BEVOR die übrigen Fachbereiche "
                        "erneut denselben Ansatz wiederholen."
                        + (f"\n\nLetzter dokumentierter Fehler:\n```\n{last_detail}\n```" if last_detail else "")
                    ),
                    context=user_request[:1500],
                ))
                log_decision(
                    project_dir, "architect_forced_reescalation",
                    f"{consecutive_failures} Läufe in Folge ohne bestandene Verifikation – architect zusätzlich eingeplant.",
                )
                # Mindestens 2 komplette Läufe sind ohne Erfolg verpufft - genau der Moment, in
                # dem ein Mensch informiert werden sollte, statt nur das Entscheidungslog.
                await asyncio.to_thread(
                    notify_external, "Wiederholtes Scheitern – architect zusätzlich eingeplant",
                    f"{self.last_project_slug}: {consecutive_failures} Läufe in Folge ohne bestandene "
                    "Verifikation.",
                )

        # Alle drei Flags pro Lauf zurücksetzen (nicht nur im Konstruktor), sonst würde ein
        # früherer Lauf mit Provider-Erschöpfung bzw. erreichter Generierungsreserve auch
        # diesen neuen Lauf fälschlich als betroffen kennzeichnen.
        self._provider_exhausted_this_run = False
        self._provider_breaker_tripped = False
        self._infra_results_store = []
        self._generation_budget_reached_this_run = False

        # Pro-Projekt-Kostenbudget (siehe __init__), bereits VOR dem ersten Agenten-Aufruf
        # geprüft: ein erschöpftes Projekt-Budget bricht den Lauf ab, ohne einen Token dafür zu
        # verbrauchen - derselbe Grundsatz wie beim Plan-Bestätigungs-Abbruch oben.
        self._project_token_budget = get_max_project_tokens(project_dir)
        self._project_tokens_before_run = 0
        if self._project_token_budget > 0:
            self._project_tokens_before_run = get_total_tokens_for_project(self.last_project_slug)
            if self._project_tokens_before_run >= self._project_token_budget:
                response = (
                    f"🚫 Projekt-Budget erschöpft: `{self._project_tokens_before_run:,}` von "
                    f"`{self._project_token_budget:,}` erlaubten Tokens für Projekt "
                    f"`{self.last_project_slug}` bereits über frühere Läufe verbraucht (siehe "
                    "`/constitution`). Kein Agent wurde für diesen Lauf gestartet – setze das "
                    "Limit höher oder starte ein neues Projekt."
                )
                self._history.add_assistant_message(response)
                self._close_unfinished_run_log("project_budget_exhausted")
                return response

        # core/token_guard.py schaltet erst REAKTIV auf ein Fallback-Modell um (nach einem
        # echten 429). Diese Warnung kommt proaktiv vor dem ersten Tokenverbrauch und nutzt
        # bewusst die TAGES- statt der Sitzungs-Variante: hier zählt der kumulierte Verbrauch
        # des Kalendertags über alle Sitzungen, nicht der junge Zähler dieses Prozesses. Rein
        # informativ, blockiert den Lauf NICHT.
        for warning in QuotaEstimator.get_proactive_daily_budget_warnings():
            self._history.add_assistant_message(warning)

        # P5-1 Punkt 1 (ROADMAP_TEMP.md): ehrlicher Degraded-Mode. Ist config.HEAVY_MODEL - die
        # letzte Rettung jeder Fix-Schleife - bereits beim Lauf-Start nicht erreichbar (kein Key
        # oder Kontingent auf Cooldown), kann dieser Lauf strukturell nie die volle Modellstärke
        # nutzen. Das wird jetzt explizit festgehalten (Trace, Abschlussbericht, run_history),
        # statt stillschweigend mit schwächeren Modellen weiterzumachen - und speist P2-2s
        # Modell-Qualitätsstatistik bewusst NICHT (memory/run_history.py.get_agent_model_
        # performance()), damit ein reiner Kontingent-Engpass nie als Qualitätsmangel eines
        # Modells fehlinterpretiert wird.
        self.last_run_degraded_reason = model_unreachable_reason(HEAVY_MODEL)
        if self.last_run_degraded_reason:
            notify(
                f"[bold yellow]⚠️ Degradierter Lauf:[/bold yellow] HEAVY_MODEL ist gerade nicht "
                f"erreichbar ({self.last_run_degraded_reason}) - dieser Lauf kann die volle "
                "Modellstärke an keiner Stelle nutzen, auch nicht als letzte Eskalationsstufe "
                "einer Fix-Schleife."
            )
            self._trace_event("run_degraded_mode", reason=self.last_run_degraded_reason)

        # Kapazitätsprüfung (core/capacity_gate.py): die Tageswarnung oben ist nur informativ,
        # ein Lauf mit erschöpften Anbietern startete trotzdem und verbrannte Tokens. Hier wird
        # VOR dem ersten Agenten-Aufruf geprüft, ob jede eingeplante kritische Rolle noch ein
        # Modell oberhalb ihrer Mindeststufe erreicht.
        if CAPACITY_GATE_MODE != "off" and agent_tasks:
            try:
                capacity = assess_run_capacity([t.agent_id for t in agent_tasks])
            except Exception as e:
                logging.getLogger(__name__).warning("Kapazitätsprüfung übersprungen: %r", e)
                capacity = None
            if capacity is not None:
                for warning in capacity.warnings:
                    notify(f"[yellow]{warning}[/yellow]")
                    self._history.add_assistant_message(warning)
                if capacity.blocked:
                    blocked_ids = ", ".join(r.agent_id for r in capacity.blocked_roles)
                    if CAPACITY_GATE_MODE == "block":
                        response = capacity.format_block_message()
                        log_decision(project_dir, "capacity_gate_blocked", f"Keine ausreichende Modell-Kapazität für: {blocked_ids}")
                        self._history.add_assistant_message(response)
                        self._close_unfinished_run_log("capacity_insufficient")
                        return response
                    notify(f"[bold yellow]⚠️ Kapazität unzureichend für {blocked_ids} – Lauf startet trotzdem (CAPACITY_GATE_MODE=warn).[/bold yellow]")
                # P5-1 Punkt 3: mindestens die Hälfte der eingeplanten Rollen würde mit einem
                # herabgestuften Modell starten (die Warnung dazu ist bereits oben ausgegeben) -
                # zusätzlich aktiv nachfragen, ob der Lauf trotzdem starten soll, statt nur zu
                # warnen und stillschweigend weiterzumachen. Nutzt DASSELBE Bestätigungs-Gate
                # wie die reguläre Plan-Freigabe oben (kein eigenes UI nötig) - kein Callback
                # (z.B. unbeaufsichtigte Läufe wie --work-backlog) heißt: Warnung genügt, der
                # Lauf startet wie bisher.
                if capacity.mostly_downgraded and plan_confirmation_callback:
                    approved = await plan_confirmation_callback(task_summary, project_slug, agent_tasks)
                    if not approved:
                        response = (
                            "↩️ Abgebrochen – der Lauf würde größtenteils mit herabgestuften Modellen "
                            "starten und wurde deshalb nicht bestätigt. Kontingent-Reset abwarten oder "
                            "bewusst erneut starten."
                        )
                        log_decision(project_dir, "capacity_gate_downgrade_declined", capacity.format_downgrade_warning())
                        self._history.add_assistant_message(response)
                        self._close_unfinished_run_log("capacity_downgrade_declined")
                        return response

        # Die folgenden Kontext-Bausteine werden unten in den Kontext jeder Teilaufgabe
        # injiziert. Alle sind leer, wenn nichts vorliegt (kein unnötiger Prompt-Text).

        # Lauf-Historie DIESES Projekts (core/project_status.py): eine neue Sitzung hat keinen
        # Zugriff auf die sitzungsgebundene conversation_history, sähe also z.B. nicht, dass
        # der letzte Lauf am Budget abbrach.
        project_history_context = format_context_for_agents(project_dir)

        # Projektübergreifendes Lessons-Learned-Gedächtnis (core/team_memory.py): Muster aus
        # Vorfällen an BELIEBIGEN Projekten - ein neues Projekt profitiert so von Fehlern
        # früherer, völlig anderer Projekte.
        team_lessons_context = format_team_lessons_for_agents(prioritize_slug=project_slug)

        # Projekt-Konstitution (core/project_constitution.py): per /constitution festgelegte
        # Tech-Stack-Präferenzen - sonst würde die Architektur pro Lauf neu geraten, selbst am
        # selben Projekt.
        constitution_context = format_constitution_for_agents(project_dir)

        # Design-System (core/design_system.py): das Pendant zur Konstitution für visuelle
        # Präferenzen - sonst könnte ein zweiter Lauf am selben Projekt eine andere
        # Primärfarbe/Schriftart wählen, ohne dass die Anfrage das je erwähnt hätte.
        design_system_context = format_design_system_for_agents(project_dir)

        # Architecture Decision Records (core/adr.py): das WARUM hinter getroffenen
        # Entscheidungen (die Konstitution hält nur das WAS fest) - sonst könnten spätere Läufe
        # unbemerkt gegen frühere, bewusste Entscheidungen arbeiten.
        adr_context = format_adr_summary_for_context(project_dir)

        for t in agent_tasks:
            t.project_dir = project_dir
            t.max_tool_iterations = AGENT_MAX_TOOL_ITERATIONS.get(t.agent_id)  # None = config.MAX_AGENT_TOOL_ITERATIONS
            if t.agent_id in REVIEW_ONLY_AGENT_IDS:
                t.tools_read_only = True
            if constitution_context:
                t.context += f"\n\n{constitution_context}"
            if design_system_context:
                t.context += f"\n\n{design_system_context}"
            if project_history_context:
                t.context += f"\n\n{project_history_context}"
            # Nach Relevanz je Agent sortiert statt einer für alle identischen Liste
            # (core/team_memory.rank_lessons_by_relevance).
            task_lessons_context = format_team_lessons_for_agents(
                prioritize_slug=project_slug,
                context=f"{t.agent_id} {t.description} {user_request[:600]}",
            ) if team_lessons_context else ""
            if task_lessons_context:
                t.context += f"\n\n{task_lessons_context}"
            if adr_context:
                t.context += f"\n\n{adr_context}"

        # Reihenfolge wie in einer echten CI (ENABLE_REVIEW_AFTER_VERIFICATION): Review-/Governance-
        # Rollen laufen erst NACH der echten Verifikation - vorher bewerteten sie Code, der sich oft
        # nicht einmal importieren ließ, und verbrauchten das Budget, das danach für Tests fehlte.
        review_after_verification = ENABLE_REVIEW_AFTER_VERIFICATION
        governance_member_ids = set(DEPARTMENT_DEFINITIONS["governance_lead"]["members"])
        deferred_review_tasks = (
            [t for t in agent_tasks if t.agent_id in governance_member_ids] if review_after_verification else []
        )
        hierarchy_tasks = [t for t in agent_tasks if t not in deferred_review_tasks]

        # Führe hierarchische Fachbereichs-Ausführung durch
        file_collisions: list[dict] = []
        results, file_owners, budget_aborted, manually_cancelled = await self._run_department_hierarchy(
            user_request=user_request,
            task_summary=task_summary,
            agent_tasks=hierarchy_tasks,
            project_dir=project_dir,
            run_start_tokens=run_start_tokens,
            notify=notify,
            cancel_requested=cancel_requested,
            collision_sink=file_collisions,
            enable_phase_checkpoint=True,
        )

        # Fallback-Dateispeicherung: Falls ein Agent trotz Werkzeug-Zugriff Code nur im
        # Antworttext statt über write_file/edit_file geliefert hat, wird er zusätzlich
        # per Regex geparst – ohne bereits über Tools geschriebene Dateien zu überschreiben.
        saved_files_count = 0
        # Macht die so gespeicherten Pfade im Abschlussbericht NAMENTLICH sichtbar (statt nur
        # als Anzahl): eine aus freiem Antworttext geparste Datei ist fehleranfälliger als ein
        # natives write_file-Argument - Syntaxfehler fängt parse_and_save_files() ab, semantisch
        # unvollständige Fragmente aber nicht. So ist ein späterer Lint-/Testfehler sofort
        # zuordenbar.
        text_fallback_paths: list[str] = []
        if AUTO_SAVE_WORKSPACE:
            for res in results:
                if res.success and res.content:
                    # project_dir (nicht project_slug!): der tatsächlich verwendete, absolute
                    # Zielordner. get_project_dir() akzeptiert absolute Pfade direkt, so landen
                    # die Dateien garantiert dort, wo auch der Werkzeug-Loop geschrieben hat,
                    # statt in einem zweiten Ordner unter dem geratenen Slug.
                    files = self._workspace.parse_and_save_files(
                        project_name=project_dir,
                        text_content=res.content,
                        agent_name=res.agent_name,
                    )
                    new_files = [f for f in files if f.relative_path not in file_owners]
                    saved_files_count += len(new_files)
                    text_fallback_paths.extend(f.relative_path for f in new_files)
                    for f in new_files:
                        file_owners[f.relative_path] = res.agent_id

            if saved_files_count > 0:
                shown_paths = ", ".join(f"`{p}`" for p in text_fallback_paths[:10])
                more_paths = f" (+{len(text_fallback_paths) - 10} weitere)" if len(text_fallback_paths) > 10 else ""
                notify(
                    f"💾 [green]Workspace:[/green] {saved_files_count} zusätzliche Projektdateien (Text-Fallback) "
                    f"in `{project_dir}` gespeichert: {shown_paths}{more_paths}."
                )

        # Governance-Fix-Schleife: kritische Befunde aus code_reviewer/security/compliance
        # (REVIEW_ONLY_AGENT_IDS) gezielt an den zuständigen Datei-Owner zur Korrektur
        # zurückspielen, BEVOR die echte Testsuite läuft (siehe core/review_gate.py). Bei
        # bereits während der Fachbereichs-Phasen überschrittenem Lauf-Budget ODER manuellem
        # Abbruch wird sie komplett übersprungen, wie die anschließende Verifikation auch.
        governance_fix_summary = ""
        permission_blocked_fix_summary = ""
        scope_clarification_summary = ""
        if budget_aborted or manually_cancelled:
            governance_fix_summary = ""
        else:
            if not review_after_verification:
                results, governance_fix_summary, budget_aborted, manually_cancelled = await self._run_governance_fix_loop(
                    project_dir=project_dir,
                    all_results=results,
                    file_owners=file_owners,
                    run_start_tokens=run_start_tokens,
                    notify=notify,
                    cancel_requested=cancel_requested,
                )

            # Rückfragen, in denen ein Agent kein fachliches Problem hat, sondern nur fehlende
            # Schreibrechte meldete (core/review_gate.py.find_permission_blocked_questions) -
            # ebenfalls VOR der Testverifikation, damit die Testsuite den reparierten Stand prüft.
            if not (budget_aborted or manually_cancelled):
                results, permission_blocked_fix_summary, budget_aborted, manually_cancelled = (
                    await self._run_permission_blocked_clarification_fix(
                        project_dir=project_dir,
                        all_results=results,
                        file_owners=file_owners,
                        run_start_tokens=run_start_tokens,
                        notify=notify,
                        cancel_requested=cancel_requested,
                    )
                )

            # Verbleibende, ECHTE fachliche Rückfragen: kein Mensch ist anwesend, also
            # entscheidet der fragende Agent selbst mit der naheliegendsten Annahme, statt den
            # Lauf unbeantwortet enden zu lassen. Ebenfalls vor der Testverifikation.
            if not (budget_aborted or manually_cancelled):
                results, scope_clarification_summary, budget_aborted, manually_cancelled = (
                    await self._run_scope_clarification_autofix(
                        project_dir=project_dir,
                        all_results=results,
                        file_owners=file_owners,
                        run_start_tokens=run_start_tokens,
                        notify=notify,
                        cancel_requested=cancel_requested,
                    )
                )

        # Echte Verifikation: Abhängigkeiten installieren, Tests wirklich ausführen,
        # bei Fehlschlägen gezielt den verantwortlichen Agenten korrigieren lassen.
        # Bei bereits während der Fachbereichs-Phasen ODER der Governance-Fix-Schleife
        # überschrittenem Lauf-Budget ODER manuellem Abbruch wird die (potenziell token-/
        # zeitintensive) Fix-Schleife komplett übersprungen.
        if getattr(self, "_provider_breaker_tripped", False):
            # Circuit Breaker (dispatch.py bzw. der sequenzielle Breaker in department.py):
            # Scheitern fast alle Agenten an erschöpften Kontingenten und schreiben keine Datei,
            # erzeugte die Verifikation daraus einen Fix-Auftrag für "keine Tests gefunden" -
            # ein Problem, das es nicht gab. Sie wird deshalb übersprungen.
            #
            # WICHTIG: Dieser Zweig muss VOR der generischen budget_aborted-Prüfung stehen - der
            # Fast Circuit Breaker setzt zusätzlich budget_aborted=True, sonst wäre diese
            # genauere, provider-spezifische Meldung toter Code und der Nutzer sähe irreführend
            # "Lauf-Budget erreicht", obwohl nur ein API-Kontingent erschöpft war.
            reason = (
                "Der Lauf wurde abgebrochen, weil der überwiegende Teil der Agenten-Aufrufe an "
                "erschöpften API-Kontingenten bzw. fehlenden API-Schlüsseln scheiterte - nicht "
                "an einem inhaltlichen Problem. Ein erneuter Versuch mit wieder verfügbarem "
                "Kontingent (oder nach Hinterlegen des fehlenden Schlüssels) sollte genügen."
            )
            verification_summary = (
                "### 🧪 Verifikations-Protokoll (echte Dependency-Installation & Testausführung)\n"
                f"- 🛑 Übersprungen: {reason}"
            )
            verification_ok = False
            self.last_verification_outcome = VerificationOutcome(skipped_reason=reason)
            budget_aborted = True  # nutzt die bestehenden Abbruch-Pfade (kein "✅ Fertig!")
            log_decision(project_dir, "provider_exhaustion_breaker_tripped", reason)
            notify(f"🛑 [red]{reason}[/red]")
        elif budget_aborted and not manually_cancelled and any(r.files_written for r in results):
            # Ein Budget-Abbruch in der Generierung darf die Verifikation nicht komplett
            # verhindern: ein Testlauf kostet 0 LLM-Tokens. Die Schleife beauftragt bei
            # erschöpftem Budget keine Fix-Agenten mehr, liefert aber ein ehrliches Ergebnis.
            notify("🧪 [yellow]Budget erreicht – führe trotzdem die kostenlose Verifikation (ohne Fix-Agenten) aus.[/yellow]")
            results, verification_summary, _v_budget_aborted, manually_cancelled, verification_ok = await self._run_verification_loop(
                project_dir=project_dir,
                all_results=results,
                file_owners=file_owners,
                run_start_tokens=run_start_tokens,
                notify=notify,
                cancel_requested=cancel_requested,
            )
            verification_summary = verification_summary.rstrip() + (
                "\n- ℹ️ Die Code-Generierung wurde vorher wegen des Budgets beendet - das Ergebnis bewertet den "
                "bis dahin erzeugten Stand, Fix-Agenten wurden nicht mehr beauftragt."
            )
            log_decision(project_dir, "verification_after_budget_abort", f"verification_ok={verification_ok}")
        elif budget_aborted or manually_cancelled:
            reason = self._budget_or_cancel_reason(
                budget_aborted, manually_cancelled,
                "während der Fachbereichs-Phasen oder der Governance-Fix-Schleife",
                start_tokens=run_start_tokens,
            )
            verification_summary = (
                "### 🧪 Verifikations-Protokoll (echte Dependency-Installation & Testausführung)\n"
                f"- 🚫 Übersprungen: {reason}."
            )
            verification_ok = False
            self.last_verification_outcome = VerificationOutcome(skipped_reason=reason)
            log_decision(project_dir, "budget_or_cancel_aborted", reason)
        else:
            results, verification_summary, budget_aborted, manually_cancelled, verification_ok = await self._run_verification_loop(
                project_dir=project_dir,
                all_results=results,
                file_owners=file_owners,
                run_start_tokens=run_start_tokens,
                notify=notify,
                cancel_requested=cancel_requested,
            )
        integration_lines = getattr(self, "last_integration_checkpoint_lines", None) or []
        if integration_lines:
            verification_summary = verification_summary.rstrip() + "\n" + "\n".join(integration_lines)

        if (
            review_after_verification
            and not (budget_aborted or manually_cancelled)
            and not getattr(self, "_provider_breaker_tripped", False)
        ):
            (
                results, verification_ok, verification_summary, governance_fix_summary,
                budget_aborted, manually_cancelled,
            ) = await self._run_review_after_verification(
                user_request=user_request,
                task_summary=task_summary,
                review_tasks=deferred_review_tasks,
                project_dir=project_dir,
                results=results,
                file_owners=file_owners,
                verification_ok=verification_ok,
                verification_summary=verification_summary,
                run_start_tokens=run_start_tokens,
                notify=notify,
                cancel_requested=cancel_requested,
            )

        # Von interface/cli.py vor dem Git-Push-Gate abgefragt (siehe _ask_for_git_push) - eine
        # klare Warnung statt eines unbedingten "alles ok", wenn Code committet werden soll,
        # dessen Tests nie bestätigt bestanden haben.
        self.last_verification_ok = verification_ok
        self.last_verification_summary = verification_summary
        # core/backlog_worker.py braucht die vollständige Ergebnisliste, um zu erkennen, ob ein
        # Lauf AUSSCHLIESSLICH an API-Kontingent-Erschöpfung scheiterte - dann soll kein PR mit
        # bloßen Status-Datei-Änderungen eröffnet werden.
        self.last_agent_results = results

        # Härteres Gate gegen wiederholtes, blindes Scheitern: die Prompt-Warnung oben setzt
        # voraus, dass ein Agent sie liest UND befolgt. Hier wird deterministisch geprüft, ob
        # dieser Lauf erneut nicht verifiziert ist UND der vorherige Fehlertext dem neuen stark
        # ähnelt (SequenceMatcher) - also derselbe Fehler wiederholt wurde, nicht nur zufällig
        # wieder gescheitert. Dann ein Backlog-Ticket für menschliche Prüfung statt weiterer
        # automatischer Retrys.
        if not verification_ok and has_repeated_failure(project_dir):
            previous_history = read_status(project_dir)
            previous_failure_detail = next((e.get("failure_detail") for e in previous_history if e.get("failure_detail")), "")
            # Beide Seiten symmetrisch auf MAX_FAILURE_DETAIL_CHARS kürzen: previous_failure_
            # detail ist beim Speichern bereits gekürzt, und SequenceMatcher.ratio() ist durch
            # 2·min(len)/(len+len) gedeckelt - ein Vergleich gegen die ungekürzte Summary fiel
            # bei langen Fehlerberichten selbst bei identischem Fehler unter die Schwelle.
            similarity = (
                SequenceMatcher(None, previous_failure_detail, verification_summary.strip()[:MAX_FAILURE_DETAIL_CHARS]).ratio()
                if previous_failure_detail else 0.0
            )
            if similarity >= 0.55:
                notify(
                    "🛑 [bold red]Wiederkehrender Fehler erkannt:[/bold red] Dieser Lauf ist erneut mit einem "
                    "sehr ähnlichen Fehler wie die vorherigen Läufe gescheitert. Ein Backlog-Ticket für "
                    "menschliche Prüfung wurde eröffnet, statt automatisch weiterzuversuchen."
                )
                # Einmal ungekürzt berechnen und in Ticket, Lernprotokoll und Entscheidungslog
                # identisch verwenden - separate Kürzungen schnitten den eigentlichen Grund
                # überall mitten im Satz ab, ohne dass irgendwo eine Vollversion blieb.
                recurring_failure_detail = verification_summary.strip() + self._provider_exhaustion_ticket_note()
                try:
                    upsert_ticket(
                        ticket_id=f"recurring-failure-{self.last_project_slug}",
                        title=f"Wiederkehrender Verifikations-Fehler: {self.last_project_slug}",
                        source="orchestrator", status="blocked", project_slug=self.last_project_slug,
                        detail=recurring_failure_detail,
                    )
                except Exception as e:
                    notify(f"⚠️ [dim yellow]Ticket für wiederkehrenden Fehler konnte nicht angelegt werden: {e}[/dim yellow]")
                # Derselbe Moment, der ein Ticket auslöst, ist ein starkes Signal für ein Muster,
                # das auch an ANDEREN Projekten auftreten kann (core/team_memory.py).
                record_lesson(
                    project_slug=self.last_project_slug, category="recurring_failure",
                    detail=recurring_failure_detail,
                )
                log_decision(project_dir, "recurring_failure_ticket_opened", recurring_failure_detail)
                # Ein wiederkehrender Fehler, der die Verifikations-Schleife endgültig aufgeben
                # lässt, ist ein ebenso starkes Eingriffs-Signal wie ein Budget-Abbruch.
                await asyncio.to_thread(
                    notify_external, "Wiederkehrender Verifikations-Fehler",
                    f"{self.last_project_slug}: {recurring_failure_detail[:300]}",
                )

        # Analog zur "wiederholtes Scheitern"-Eskalation oben, aber für Lint-Funde: ein
        # Lint-Fund setzt verification_ok bewusst NIE zurück, has_repeated_failure() griff
        # deshalb nie - derselbe Fund konnte über viele Läufe bestehen bleiben. Triviale Fälle
        # behebt `ruff check --fix` schon vorher; dieser Check fängt den Rest ab.
        lint_signature = getattr(self, "last_lint_signature", [])
        lint_ticket_id = f"recurring-lint-{self.last_project_slug}" if self.last_project_slug else None
        if lint_signature and has_repeated_lint_finding(project_dir):
            notify(
                "🎨 [bold yellow]Wiederkehrender Lint-Fund erkannt:[/bold yellow] Derselbe Lint-Fund "
                "besteht unverändert über mehrere Läufe. Ein Backlog-Ticket für menschliche Prüfung "
                "wurde eröffnet."
            )
            try:
                # lint_signature trägt einen Eintrag JE FUND-INSTANZ - ohne set() listete das
                # Ticket dieselbe Regel/Datei-Kombination mehrfach identisch auf, statt bis zu
                # 10 wirklich unterschiedliche Funde zu zeigen.
                upsert_ticket(
                    ticket_id=lint_ticket_id,
                    title=f"Wiederkehrender Lint-Fund: {self.last_project_slug}",
                    source="orchestrator", status="blocked", project_slug=self.last_project_slug,
                    detail="; ".join(sorted(set(lint_signature))[:10]),
                )
                await asyncio.to_thread(
                    notify_external, "Wiederkehrender Lint-Fund",
                    f"{self.last_project_slug}: {'; '.join(sorted(set(lint_signature))[:10])}",
                )
            except Exception as e:
                notify(f"⚠️ [dim yellow]Ticket für wiederkehrenden Lint-Fund konnte nicht angelegt werden: {e}[/dim yellow]")
        elif lint_ticket_id and not lint_signature and getattr(self, "last_lint_attempted", False):
            # Gegenstück zum Öffnen oben: dieser Lauf hatte KEINEN Lint-Fund, ein zuvor offenes
            # Ticket für dasselbe Projekt gilt damit als erledigt. Ohne das blieb ein
            # "recurring-lint-"-Ticket für immer "blocked" im Backlog stehen.
            try:
                existing_lint_ticket = get_ticket(lint_ticket_id)
                if existing_lint_ticket is not None and existing_lint_ticket.status == "blocked":
                    upsert_ticket(
                        ticket_id=lint_ticket_id, title=existing_lint_ticket.title,
                        source="orchestrator", status="done", project_slug=self.last_project_slug,
                        detail="In einem späteren Lauf behoben - keine Lint-Funde mehr.",
                    )
                    notify("  🎫 [dim]Ticket für wiederkehrenden Lint-Fund als gelöst geschlossen.[/dim]")
            except Exception as e:
                notify(f"⚠️ [dim yellow]Ticket für wiederkehrenden Lint-Fund konnte nicht geschlossen werden: {e}[/dim yellow]")

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
        # Bewusst VOR der Synthese gezählt (nicht erst bei der Definition of Done), damit
        # no_implementation_files als Anti-Halluzinations-Schutz an synthesize() gehen kann
        # (NO_IMPLEMENTATION_GUARD_INSTRUCTION in core/result_aggregator.py).
        geschriebene_dateien = len({f for r in results for f in (r.files_written or [])})
        final_solution, synth_tokens = await self._result_aggregator.synthesize(
            user_request=user_request,
            task_summary=task_summary,
            results=results,
            no_implementation_files=geschriebene_dateien == 0,
        )

        # Retrospektive & Automatische Selbstoptimierung – werden bei überschrittenem
        # Lauf-Budget ODER manuellem Abbruch ausgelassen, da sie selbst weitere
        # (nicht-kritische) LLM-Aufrufe kosten.
        total_duration = time.monotonic() - overall_start_time
        retro_result = None
        trainer_result = None
        self.last_budget_aborted = budget_aborted

        # Abnahme-Phase 2/2 (P4-2, core/acceptance_check.py): die in Phase 1 destillierten
        # Anforderungen jetzt read-only GEGEN DEN TATSÄCHLICHEN CODE prüfen - nur, wenn
        # überhaupt Code geschrieben wurde und der Lauf nicht schon vorher abgebrochen ist.
        self.last_acceptance_result = None
        if (
            ENABLE_ACCEPTANCE_CHECK and self.last_acceptance_requirements
            and geschriebene_dateien > 0 and not (budget_aborted or manually_cancelled)
        ):
            try:
                self.last_acceptance_result = await verify_acceptance(
                    self, project_dir, self.last_acceptance_requirements,
                )
                if self.last_acceptance_result.parsed and self.last_acceptance_result.missing:
                    notify(
                        f"📋 [bold yellow]Abnahme:[/bold yellow] {len(self.last_acceptance_result.missing)} von "
                        f"{len(self.last_acceptance_requirements)} Anforderung(en) aus dem Auftrag fehlen noch: "
                        + "; ".join(self.last_acceptance_result.missing[:3])
                    )
            except Exception as e:
                notify(f"⚠️ [dim yellow]Abnahme-Prüfung konnte nicht laufen: {e}[/dim yellow]")

        # Maschinenlesbare "Definition of Done" (core/definition_of_done.py): ein Prosa-Status
        # kann "fast fertig", "gar nicht angefangen" und "an der Infrastruktur gescheitert"
        # nicht unterscheiden. Rein additiv - ein Fehler hier darf den Lauf nicht kippen.
        try:
            # Strukturierte Einzelergebnisse statt Textsuche im Markdown-Protokoll
            # (core/verification_outcome.py) - der frühere String-Abgleich traf nie zu.
            _outcome = getattr(self, "last_verification_outcome", None)
            if not isinstance(_outcome, VerificationOutcome):
                _outcome = VerificationOutcome()
            _secrets_clean: bool | None = None
            if geschriebene_dateien > 0:
                try:
                    _secrets_clean = not scan_directory(project_dir)
                except Exception:
                    _secrets_clean = None
            self.last_definition_of_done = build_definition_of_done(
                project_slug=self.last_project_slug,
                project_dir=project_dir,
                files_written=geschriebene_dateien,
                # tests_ran/tests_passed hängen bewusst am Testsuite-Einzelergebnis, nicht am
                # Gesamt-verification_ok: ein nachgelagerter Check (z.B. Browser-UI) kippt
                # verification_ok und ließ eine bestandene Unit-Testsuite als "nie gelaufen"
                # erscheinen.
                tests_ran=_outcome.ran("tests"),
                tests_passed=_outcome.status("tests") is True,
                deps_installable=_outcome.status("deps_install"),
                app_starts=_outcome.status("smoke"),
                secrets_clean=_secrets_clean,
                lint_clean=_outcome.status("lint"),
                ui_ok=_outcome.status("browser_ui"),
                build_passes=_outcome.status("frontend_build"),
                test_depth_ok=_outcome.status("test_depth"),
                coverage_percent=getattr(self, "last_coverage_percent", None),
                min_coverage=float(MIN_TEST_COVERAGE),
                verification_ok=verification_ok,
                # Nur die BLOCKIERENDEN Fehlschläge: `lint` & Co. sind informativ und
                # beeinflussen `verification_ok` nie (siehe INFORMATIONAL_CHECK_KEYS).
                # Mit `failed_checks` nannte die Definition of Done bei cachegrid_proxy
                # "fehlgeschlagene Prüfungen: lint, pre_flight", obwohl allein `pre_flight`
                # blockierte - eine irreführende Angabe genau an der Stelle, an der jede
                # spätere Analyse nach dem Grund sucht.
                failed_checks=_outcome.blocking_failed_checks,
                verification_skipped=bool(budget_aborted or manually_cancelled),
                # Die Verifikations-Pipeline lief hier immer (`_outcome` stammt aus ihr).
                # Damit gilt ein fehlender Messwert bei einer Pflichtprüfung als Blocker statt
                # als "nicht relevant" - siehe build_definition_of_done().
                verification_ran=True,
                user_request=user_request,
                task_summary=task_summary,
                # Macht das dateibasierte "missing_frontend_ui"-Kriterium nur verpflichtend,
                # wenn ein frontend-Agent eingeplant war - unabhängig von dessen Erfolg, denn
                # gerade ein gescheitertes Hard Delivery Gate soll hier sichtbar werden.
                frontend_planned=any(r.agent_id == "frontend" for r in results),
                requirements_met=(
                    self.last_acceptance_result.requirements_met if self.last_acceptance_result else None
                ),
                missing_requirements=(
                    self.last_acceptance_result.missing if self.last_acceptance_result else None
                ),
            )
            write_definition_of_done(project_dir, self.last_definition_of_done)
            if self._run_logger is not None:
                self._run_logger.log_event(
                    "definition_of_done",
                    is_done=self.last_definition_of_done.is_done,
                    blocking=[c.key for c in self.last_definition_of_done.blocking_criteria],
                )
        except Exception as e:
            notify(f"⚠️ [dim yellow]Definition of Done konnte nicht geschrieben werden: {e}[/dim yellow]")

        if budget_aborted:
            notify(f"🚫 [bold red]{self._budget_exceeded_label(run_start_tokens)} erreicht:[/bold red] Retrospektive & Selbstoptimierung werden übersprungen ({self._tokens_used_since(run_start_tokens):,} Tokens in diesem Lauf).")
            # EIN zentraler Benachrichtigungs-Ort statt an jeder Stelle, an der budget_aborted
            # gesetzt werden kann (no-op ohne NOTIFY_WEBHOOK_URL) - relevant v.a. für
            # unbeaufsichtigte Läufe, wo sonst niemand den vorzeitigen Abbruch bemerkt.
            await asyncio.to_thread(
                notify_external, "Budget erreicht",
                f"{task_summary[:150]}: {self._budget_exceeded_label(run_start_tokens)} erreicht "
                f"({self._tokens_used_since(run_start_tokens):,} Tokens in diesem Lauf verbraucht).",
            )
            if getattr(self, "_provider_exhausted_this_run", False):
                # Ein Sofortabbruch durch den Fast Circuit Breaker ist ein INFRASTRUKTUR-Blocker,
                # kein Qualitätsmangel eines Agenten - sonst stufen optimization_advisor/
                # team_retro die betroffenen Agenten fälschlich als "schlecht performend" ein.
                record_lesson(
                    project_slug=self.last_project_slug,
                    category="infrastructure_blocker",
                    detail=(
                        "Lauf durch Fast Circuit Breaker sofort abgebrochen (PROVIDER_EXHAUSTION_"
                        "CONSECUTIVE_LIMIT, config.py): mehrere Agenten in Folge bzw. eine "
                        "kritische Rolle scheiterten an provider_exhausted, weil KEIN "
                        "konfigurierter Provider mehr Kapazität/Guthaben hatte. Kein Agenten- "
                        "oder Code-Defekt - vor dem nächsten Lauf Kontingent/Guthaben prüfen "
                        "(core/capacity_gate.py verhindert einen erneuten Fehlstart bereits vor "
                        "dem Loslegen)."
                    ),
                )
            elif self._root_cause_analysis_worthwhile_despite_budget_abort(
                provider_exhausted_this_run=getattr(self, "_provider_exhausted_this_run", False),
                verification_summary=verification_summary,
                verification_ok=verification_ok,
            ):
                # Siehe _root_cause_analysis_worthwhile_despite_budget_abort()-Docstring
                # (agents/orchestrator/retrospective.py): ein Budget-Abbruch NACH echten
                # Testfehlern (statt Provider-Erschöpfung) verdient trotzdem die sonst nur im
                # `else`-Zweig laufende Tiefenanalyse.
                await self._maybe_run_root_cause_analysis(
                    user_request=user_request,
                    verification_ok=verification_ok,
                    verification_summary=verification_summary,
                    files_written=geschriebene_dateien,
                    project_dir=project_dir,
                    notify=notify,
                )
        elif manually_cancelled:
            notify("⏹️ [bold red]Lauf manuell abgebrochen:[/bold red] Retrospektive & Selbstoptimierung werden übersprungen.")
        else:
            notify("📊 [bold cyan]Abschluss:[/bold cyan] Retrospektive & KI-Selbstoptimierung werden durchgeführt...")
            retro_result = await self._run_retrospective(
                user_request=user_request,
                results=results,
                total_duration=total_duration,
            )
            trainer_result = await self._run_agent_trainer_self_optimization(
                user_request=user_request,
                results=results,
                retro_content=retro_result.content if retro_result else "",
                verification_ok=verification_ok,
                verification_summary=verification_summary,
                definition_of_done=self.last_definition_of_done,
            )
            # Zusätzlich zum werkzeuglosen Trainer-Aufruf oben: bei einem echten Warnsignal eine
            # Tiefenanalyse MIT Tool-Zugriff (core/root_cause_analyst.py).
            await self._maybe_run_root_cause_analysis(
                user_request=user_request,
                verification_ok=verification_ok,
                verification_summary=verification_summary,
                files_written=geschriebene_dateien,
                project_dir=project_dir,
                notify=notify,
            )
            # Nur bei tatsächlich bestandener Verifikation - siehe
            # _maybe_harvest_reusable_components-Docstring.
            self._maybe_harvest_reusable_components(
                verification_ok=verification_ok,
                project_dir=project_dir,
                project_slug=self.last_project_slug,
                notify=notify,
            )

        # Projekt-Abschlussbericht (P3-1): rein additiv, kein LLM-Aufruf, deshalb für JEDEN Lauf
        # geschrieben - auch für budget-abgebrochene/manuell abgebrochene, damit auch dort
        # nachvollziehbar bleibt, wie weit der Lauf kam und wofür die Tokens draufgingen.
        try:
            generate_postmortem(
                project_dir=project_dir,
                project_slug=self.last_project_slug,
                results=results,
                planned_agent_ids=[t.agent_id for t in agent_tasks],
                total_duration=total_duration,
                verification_ok=verification_ok,
                outcome=getattr(self, "last_verification_outcome", None),
            )
        except Exception as e:
            notify(f"⚠️ [dim yellow]Abschlussbericht konnte nicht geschrieben werden: {e}[/dim yellow]")

        stats_table = self._build_metrics_summary(
            results=results,
            synth_tokens=synth_tokens,
            total_duration=total_duration,
            project_dir=project_dir,
            run_start_tokens=run_start_tokens,
            text_fallback_paths=text_fallback_paths,
        )
        if budget_aborted:
            stats_table += (
                f"\n\n> 🚫 **{self._budget_exceeded_label(run_start_tokens)} erreicht:** Dieser Lauf wurde nach "
                f"`{self._tokens_used_since(run_start_tokens):,}` Tokens vorzeitig beendet. Restliche "
                "Fachbereiche, Verifikations-Fixversuche und/oder Retrospektive/Selbstoptimierung wurden "
                "übersprungen; die bis dahin erarbeiteten Ergebnisse wurden trotzdem oben zusammengefasst."
            )
        elif manually_cancelled:
            stats_table += (
                "\n\n> ⏹️ **Manuell abgebrochen:** Dieser Lauf wurde auf Nutzerwunsch vorzeitig beendet. "
                "Restliche Fachbereiche, Verifikations-Fixversuche und/oder Retrospektive/Selbstoptimierung "
                "wurden übersprungen; die bis dahin erarbeiteten Ergebnisse wurden trotzdem oben zusammengefasst."
            )
        if getattr(self, "last_run_degraded_reason", ""):
            stats_table += (
                f"\n\n> ⚠️ **Degradierter Lauf (P5-1):** HEAVY_MODEL war beim Start nicht erreichbar "
                f"({self.last_run_degraded_reason}) - dieser Lauf konnte an keiner Stelle, auch nicht als "
                "letzte Fix-Eskalation, die volle Modellstärke nutzen. Ergebnisse mit Vorsicht bewerten; "
                "die automatische Modell-Qualitätsstatistik (P2-2) berücksichtigt diesen Lauf bewusst nicht."
            )

        # Liest die WIRKLICH geschriebenen Dateien direkt von der Platte (kein LLM-Aufruf, daher
        # exakt): die Synthese oben paraphrasierte Code aus den Agenten-Berichten und wich damit
        # von den tatsächlichen Dateien ab - ein Vertrauensproblem für alle, die nur den
        # Chat-Output lesen.
        real_files_section = self._build_real_files_section(project_dir, file_owners)
        collision_section = self._build_file_collision_section(file_collisions)
        clarification_section = self._build_clarification_section(results)
        self.last_needs_human_input = bool(clarification_section)
        self.last_clarification_questions = [q for r in results for q in r.clarification_questions]

        # Datenbasierte Selbstoptimierungs-Vorschläge (core/optimization_advisor.py):
        # deterministische Auswertung der bestehenden, projektübergreifenden Lauf-Historie, kein
        # zusätzlicher LLM-Aufruf. Standardmäßig nur ein Vorschlag, keine automatische Änderung.
        # apply_auto_tuning() schließt den Kreislauf für Nutzer mit
        # config.ENABLE_AUTO_MODEL_TUNING - sonst bleibt eine Empfehlung wirkungslos, solange
        # niemand den Abschlussbericht liest (autonome --work-backlog/Cron-Läufe). No-Op,
        # solange das Flag aus ist.
        optimization_report = analyze_optimization_potential()
        auto_tuned_agents = apply_auto_tuning(optimization_report)
        # Modell-Vorschläge als kontrollierte A/B-Tests starten und laufende Tests auswerten
        # (core/model_ab_trials.py) - statt sie nur als Lektion zu notieren.
        try:
            started_trials = start_trials_from_report(optimization_report)
            trial_outcome = evaluate_trials()
            if started_trials:
                notify(f"🧪 [dim]Modell-A/B-Test gestartet für: {', '.join(started_trials)}[/dim]")
            for label, agents in (("übernommen", trial_outcome["promoted"]), ("verworfen", trial_outcome["rejected"]), ("zurückgenommen", trial_outcome["rolled_back"])):
                if agents:
                    notify(f"🧪 [bold]Modell-A/B-Test {label}:[/bold] {', '.join(agents)}")
        except Exception as e:  # noqa: BLE001 - Selbstoptimierung darf den Lauf nie gefährden
            logging.getLogger(__name__).warning("Modell-A/B-Tests fehlgeschlagen: %r", e)
        # Schreibt Modell-/Underperformer-Funde ins teamweite Lektionen-Gedächtnis
        # (core/team_memory.py) - so bleiben sie sichtbar, auch wenn ENABLE_AUTO_MODEL_TUNING
        # aus ist und niemand diesen Abschlussbericht liest. record_lesson() dedupliziert
        # intern, ein wiederholter Fund bläht die Historie also nicht auf.
        record_suggestions_as_lessons(optimization_report)
        # Lektionen, die das zentrale Regelwerk (core/known_pitfalls.py) inzwischen abdeckt, als
        # umgesetzt markieren - sie belegen dann keine Prompt-Plätze mehr, öffnen sich aber
        # automatisch wieder, falls der Fehler erneut auftritt.
        try:
            linked = auto_link_lessons_to_rules()
            if linked:
                notify(f"🧠 [dim]{len(linked)} Team-Lektion(en) als durch das Regelwerk abgedeckt markiert.[/dim]")
        except Exception as e:  # noqa: BLE001 - Lernpflege darf den Lauf nie gefährden
            logging.getLogger(__name__).warning("Lektionen-Verknüpfung fehlgeschlagen: %r", e)
        # Öffnet je betroffener Rolle ein verfolgbares Backlog-Ticket: als bloße Zeile in
        # team_lessons.jsonl teilen sich unused_agent-Funde die knappen MAX_LESSONS_SHOWN-Plätze
        # und gingen unter. source="optimization_advisor" ist bewusst nicht in
        # _AUTONOMOUS_SOURCES - Rollen-Konsolidierung ist eine menschliche Abwägung.
        unused_agent_tickets = record_unused_agent_tickets(optimization_report)
        # Kehrseite dazu: schließt ein offenes `unused-agent-<id>`-Ticket automatisch, sobald
        # die Rolle in einem späteren Lauf wieder gewählt wurde.
        resolved_unused_agent_tickets = close_resolved_unused_agent_tickets(optimization_report)
        optimization_section = format_optimization_report(optimization_report)
        if unused_agent_tickets:
            notify(
                f"  💤 [dim yellow]Ungenutzte Rollen als Backlog-Ticket vermerkt:[/dim yellow] "
                f"{', '.join(t.removeprefix('unused-agent-') for t in unused_agent_tickets)}."
            )
        if resolved_unused_agent_tickets:
            notify(
                f"  ✅ [dim green]Rollen wieder aktiv, Ticket geschlossen:[/dim green] "
                f"{', '.join(t.removeprefix('unused-agent-') for t in resolved_unused_agent_tickets)}."
            )
        if auto_tuned_agents:
            notify(
                f"  🔧 [bold cyan]Selbstoptimierung angewendet:[/bold cyan] {', '.join(auto_tuned_agents)} "
                "auf empirisch besseres Modell umgestellt (memory/auto_tuned_models.json)."
            )
            optimization_section += (
                f"\n\n✅ **Automatisch angewendet** (ENABLE_AUTO_MODEL_TUNING aktiv): "
                f"{', '.join(auto_tuned_agents)} laufen ab dem nächsten Aufruf mit dem "
                "empfohlenen Modell."
            )

        provider_exhaustion_section = self._build_provider_exhaustion_report()
        efficiency_section = self._build_efficiency_section(results)
        incomplete_project_banner = self._build_incomplete_project_banner(self.last_definition_of_done)

        final_output = (
            (f"{incomplete_project_banner}\n\n---\n\n" if incomplete_project_banner else "")
            + f"{final_solution}\n\n"
            f"---\n\n"
            + (f"{provider_exhaustion_section}\n\n---\n\n" if provider_exhaustion_section else "")
            + (f"{real_files_section}\n\n---\n\n" if real_files_section else "")
            + (f"{clarification_section}\n\n---\n\n" if clarification_section else "")
            + (f"{collision_section}\n\n---\n\n" if collision_section else "")
            + (f"{governance_fix_summary}\n\n---\n\n" if governance_fix_summary else "")
            + (f"{permission_blocked_fix_summary}\n\n---\n\n" if permission_blocked_fix_summary else "")
            + (f"{scope_clarification_summary}\n\n---\n\n" if scope_clarification_summary else "")
            + f"{verification_summary}\n\n"
            f"---\n\n"
            f"{retro_result.content if retro_result else ''}\n\n"
            f"---\n\n"
            f"{trainer_result.content if trainer_result else ''}\n\n"
            f"---\n\n"
            + (f"{optimization_section}\n\n---\n\n" if optimization_section else "")
            + (f"{efficiency_section}\n\n---\n\n" if efficiency_section else "")
            + f"{stats_table}"
        )

        self._history.add_assistant_message(final_output)

        # Die drei Telemetrie-Aufrufe unten sind rein additiv und JEWEILS einzeln in try/except
        # gekapselt (nicht in einem gemeinsamen Block), damit ein Fehler in einem die anderen
        # beiden nicht verhindert. Ein unbehandelter Fehler hier ließ früher den bereits fertig
        # synthetisierten final_output für den Nutzer komplett verloren gehen, obwohl die
        # eigentliche Team-Arbeit erfolgreich abgeschlossen war.
        try:
            # Projekt-Kontinuität über mehrere Sitzungen hinweg & automatischer State-Checkpoint (core/project_status.py)
            all_written_files = sorted({f for r in results for f in r.files_written})
            save_project_checkpoint(
                project_dir=project_dir,
                task_summary=task_summary,
                verification_ok=verification_ok,
                budget_aborted=budget_aborted,
                cancelled=manually_cancelled,
                files_written_count=len(all_written_files),
                files_written=all_written_files,
                verification_summary=verification_summary,
                clarification_questions=self.last_clarification_questions,
                lint_signature=getattr(self, "last_lint_signature", []),
                provider_exhausted=bool(getattr(self, "_provider_exhausted_this_run", False)),
                verification_outcome=(
                    self.last_verification_outcome.to_dict()
                    if isinstance(getattr(self, "last_verification_outcome", None), VerificationOutcome) else None
                ),
                run_stamp=getattr(self._run_logger, "stamp", None),
            )
        except Exception as e:
            notify(f"⚠️ [dim yellow]Projekt-Historie / State-Checkpoint (save_project_checkpoint) konnte nicht aktualisiert werden: {e}[/dim yellow]")

        try:
            # Kumulierte, neustartfeste Kosten-Historie (memory/cost_history.py; token_guard ist
            # nur ein In-Memory-Zähler). Nutzt den Pro-Modell-DELTA seit Laufbeginn - sonst
            # zählte ein zweiter Lauf derselben Sitzung den ersten erneut mit.
            record_run_usage(self._model_usage_deltas(run_start_model_stats))
        except Exception as e:
            notify(f"⚠️ [dim yellow]Kosten-Historie (record_run_usage) konnte nicht aktualisiert werden: {e}[/dim yellow]")

        try:
            # Projektübergreifende Lauf-Historie: project_status speichert nur pro Projekt,
            # cost_history nur Summen pro Modell - keines zeigt, welche Agenten über die Zeit
            # häufiger scheitern (Grundlage der Observability-Ansicht im Dashboard).
            record_run_history(
                project_slug=self.last_project_slug,
                task_summary=task_summary,
                verification_ok=verification_ok,
                total_tokens=sum(r.total_tokens for r in results),
                duration_seconds=total_duration,
                agent_results=[
                    {
                        "agent_id": r.agent_id,
                        "success": r.success,
                        "total_tokens": r.total_tokens,
                        "model_used": r.model_used,
                        # Unterscheidet echten Fehler von erschöpftem Tageskontingent -
                        # memory/run_history.py rechnet Infrastruktur-Ausfälle aus den
                        # Erfolgsquoten heraus.
                        "failure_class": r.failure_class,
                    }
                    for r in results
                ],
                degraded=bool(getattr(self, "last_run_degraded_reason", "")),
            )
        except Exception as e:
            notify(f"⚠️ [dim yellow]Lauf-Historie (record_run_history) konnte nicht aktualisiert werden: {e}[/dim yellow]")

        # Lauf-Log abschließen (schreibt die Abschlusszeile und räumt alte Logs auf).
        try:
            if self._run_logger is not None:
                self._run_logger.close(
                    verification_ok=verification_ok,
                    total_tokens=sum(r.total_tokens for r in results),
                    # P6-7: len(results) zählte nur Fachbereichs-Ergebnisse, nicht Delegation/
                    # Konsolidierung/Retrospektive/Trainer - self._run_logger.agent_call_count
                    # zählt JEDEN tatsächlich geloggten Agenten-Aufruf (siehe core/run_logger.py).
                    agent_calls=self._run_logger.agent_call_count,
                    failed_agent_calls=self._run_logger.failed_agent_call_count,
                    provider_exhausted=bool(getattr(self, "_provider_exhausted_this_run", False)),
                    budget_aborted=self.last_budget_aborted,
                    **self._efficiency_snapshot(results),
                )
        except Exception:
            pass

        # Der allerletzte Status wird am ehesten wahrgenommen und muss deshalb differenzieren,
        # statt immer "✅ Fertig!" zu melden: unbestätigte Verifikation, manueller Abbruch und
        # offene Rückfrage sind je ein eigener Status, denn sie bedeuten Verschiedenes.
        # Ein offenes Governance-/Verifikations-Ticket (_BLOCKER_TICKET_PREFIXES) wird VOR
        # verification_ok geprüft - ein ungelöster kritischer Befund wiegt schwerer als eine
        # grüne Testsuite.
        try:
            open_blocker = has_open_blocker_ticket(project_dir, verification_ok=verification_ok)
        except Exception:
            open_blocker = False

        if manually_cancelled:
            notify(
                "⏹️ [bold yellow]Manuell abgebrochen.[/bold yellow] Die bis dahin erarbeiteten Ergebnisse "
                "wurden zusammengefasst – prüfe das Ergebnis, es ist mit hoher Wahrscheinlichkeit unvollständig."
            )
        elif open_blocker:
            notify(
                "🔴 [bold red]Fertig, aber NICHT einsatzbereit![/bold red] Ein kritischer Governance-/"
                "Verifikations-Befund blieb trotz Fixversuchen ungelöst und liegt als offenes Backlog-"
                "Ticket vor (siehe PROJECT_STATE.md) – das gilt unabhängig davon, ob die Testsuite "
                "bestanden hat."
            )
        elif self.last_needs_human_input:
            # Eine offene Rückfrage ist kein Testfehler, sondern die bewusste Entscheidung eines
            # Agenten, NICHT zu raten - deshalb ein eigener Status.
            notify(
                f"❓ [bold cyan]Fertig, aber mit {len(self.last_clarification_questions)} offener "
                f"Rückfrage(n)![/bold cyan] Siehe Abschnitt 'Offene Rückfragen' oben – bitte beantworten, "
                "bevor das Ergebnis unverändert übernommen wird."
            )
        elif verification_ok:
            notify("✅ [bold green]Fertig![/bold green] Alle Fachbereiche haben ihre Aufgaben erfolgreich abgeschlossen.")
        else:
            notify(
                "⚠️ [bold yellow]Fertig, aber NICHT verifiziert![/bold yellow] Die echte Testsuite hat den "
                "Code nicht bestätigt (siehe Verifikations-Protokoll oben) – prüfe das Ergebnis, bevor du es übernimmst."
            )
        return final_output

    @staticmethod
    def _normalize_slug(slug: str) -> str:
        """Ignoriert Schreibvarianten, die für einen Menschen identisch aussehen:
        Groß-/Kleinschreibung sowie "_" vs. "-" - häufige Ursache doppelter Läufe."""
        return slug.lower().replace("-", "_")

    @classmethod
    def _find_near_duplicate_slug(cls, project_slug: str, existing_projects: list[str]) -> str | None:
        """Findet ein vorhandenes Projekt, dessen normalisierter Name mit dem neuen project_slug
        übereinstimmt, obwohl die Roh-Slugs sich unterscheiden ("api_health_monitor" vs.
        "api-health-monitor"). None, wenn keines passt oder der Slug exakt existiert (dann greift
        die reguläre Fortsetzungs-Logik)."""
        normalized_new = cls._normalize_slug(project_slug)
        for existing in existing_projects:
            if existing != project_slug and cls._normalize_slug(existing) == normalized_new:
                return existing
        return None

    @classmethod
    def _match_existing_project(cls, project_slug: str, user_request: str, existing_projects: list[str]) -> str | None:
        """Erkennt, ob ein Lauf sich auf ein bereits existierendes Projekt bezieht,
        selbst wenn der generierte project_slug Suffixe/Präfixe wie _repair oder _fix trägt,
        oder der Nutzer 'workspace/<name>' im Prompt erwähnt hat."""
        import re

        # 1. Explizite Pfadangabe wie "workspace/feature_pilot" oder "workspace\feature_pilot"
        for proj in existing_projects:
            if re.search(rf"(?:workspace[/\\]){re.escape(proj)}\b", user_request, re.IGNORECASE):
                return proj

        # 2. Suffix- oder Präfix-Ableitung: z.B. feature_pilot_repair, feature_pilot_fix, fix_feature_pilot
        norm_slug = cls._normalize_slug(project_slug)
        for proj in existing_projects:
            norm_proj = cls._normalize_slug(proj)
            for sfx in ("_repair", "_fix", "_patch", "_update", "_refactor", "_test"):
                if norm_slug.endswith(sfx) and norm_slug[:-len(sfx)] == norm_proj:
                    return proj
            for pfx in ("repair_", "fix_", "patch_", "update_", "refactor_", "test_"):
                if norm_slug.startswith(pfx) and norm_slug[len(pfx):] == norm_proj:
                    return proj

        # 3. Direkte Erwähnung des Slugs als ganzes Wort im Prompt
        for proj in existing_projects:
            if len(proj) >= 4 and re.search(rf"\b{re.escape(proj)}\b", user_request, re.IGNORECASE):
                return proj

        return None

    async def _resolve_project_isolation(
        self, candidate_dir: str, task_summary: str, notify: Callable[[str], None],
    ) -> tuple[str, str | None]:
        """
        Entscheidet, ob candidate_dir isoliert (Git-Worktree) oder direkt verwendet wird.

        Gibt (project_dir, abort_response) zurück: project_dir ist bei einem Abbruch
        bedeutungslos ("") – der Aufrufer MUSS abort_response (falls nicht None) direkt an
        den Nutzer zurückgeben, statt fortzufahren.

        Isoliert wird IMMER, wenn am Zielort echter Inhalt existiert (Framework-Root zählt
        immer dazu); ein leeres, neues Projekt hat nichts zu verlieren und wird ohne
        Worktree-Overhead direkt geschrieben. Bei unkommittierten Änderungen am Zielort wird
        NICHT isoliert (ein frischer Worktree basiert auf dem letzten COMMIT und würde sie
        unsichtbar machen), sondern direkt geschrieben – mit klarer Warnung. Nur beim
        Framework-Root führt ein Scheitern der Isolation zum Abbruch statt zum Fallback: dort
        ist das Risiko am größten.
        """
        resolved = Path(candidate_dir).resolve()
        is_self_targeting = str(resolved) == str(Path(BASE_DIR).resolve())
        has_content = is_self_targeting or (resolved.exists() and any(resolved.iterdir()))

        if not has_content:
            return candidate_dir, None

        git_root = find_git_root(candidate_dir)
        if git_root is None:
            if is_self_targeting:
                return "", (
                    "⚠️ Selbstverbesserungslauf abgebrochen: Framework-Root ist kein "
                    "Git-Repository – Isolation nicht möglich. Aus Sicherheitsgründen wird "
                    "NICHT direkt im echten Arbeitsverzeichnis geschrieben."
                )
            notify(
                f"⚠️ [yellow]Kein Git-Repo für `{candidate_dir}` gefunden – Isolation nicht "
                "möglich, Änderungen werden direkt geschrieben.[/yellow]"
            )
            return candidate_dir, None

        if has_uncommitted_changes(git_root, candidate_dir):
            notify(
                f"⚠️ [yellow]`{candidate_dir}` hat unkommittete Änderungen – ein isolierter "
                "Worktree (basiert auf dem letzten Commit) würde diese nicht sehen. Änderungen "
                "werden direkt geschrieben.[/yellow]"
            )
            return candidate_dir, None

        try:
            worktree = create_isolated_worktree(git_root, task_summary)
        except GitIsolationError as e:
            if is_self_targeting:
                return "", (
                    f"⚠️ Selbstverbesserungslauf abgebrochen: Isolierter Git-Worktree konnte "
                    f"nicht angelegt werden ({e}). Aus Sicherheitsgründen wird NICHT direkt im "
                    "echten Arbeitsverzeichnis geschrieben."
                )
            notify(f"⚠️ [yellow]Isolierter Git-Worktree konnte nicht angelegt werden ({e}) – Änderungen werden direkt geschrieben.[/yellow]")
            return candidate_dir, None

        self.last_isolated_worktree = worktree
        git_root_resolved = Path(git_root).resolve()
        if resolved == git_root_resolved:
            project_dir = worktree.path
        else:
            project_dir = str(Path(worktree.path) / resolved.relative_to(git_root_resolved))
            Path(project_dir).mkdir(parents=True, exist_ok=True)

        notify(
            f"🌳 [bold cyan]Isolierter Git-Worktree:[/bold cyan] `{project_dir}` "
            f"(Branch `{worktree.branch}`) – dein echtes Arbeitsverzeichnis bleibt "
            "während des gesamten Laufs unberührt."
        )
        return project_dir, None

    def get_team_info(self) -> str:
        """Gibt eine strukturierte Übersicht über alle 6 Fachbereiche und deren Teamleiter zurück."""
        sections = [
            "## 🏢 Strukturierte Fachbereiche & Teamleiter-Hierarchie\n",
            "```",
            "                                     Du (Nutzer)",
            "                                         │ Aufgabe",
            "                                         ▼",
            "                            ┌─────────────────────────┐",
            "                            │  🤖 HAUPTAGENT          │ (Gesamtkoordination)",
            "                            └────────────┬────────────┘",
            "                                         │ Delegiert Aufgabenbereiche",
            "       ┌─────────────────┬───────────────┼───────────────┬─────────────────┬───────────────┐",
            "       ▼                 ▼               ▼               ▼                 ▼               ▼",
            " ┌───────────┐     ┌───────────┐   ┌───────────┐   ┌───────────┐     ┌───────────┐   ┌───────────┐",
            " │ 👔 Lead   │     │ 🎨 Lead   │   │ ⚡ Lead   │   │ 📚 Lead   │     │ 🛡️ Lead   │   │ 🔍 Lead   │",
            " │ Planung   │ ──► │ Design    │──►│ Dev       │──►│ Content   │ ──► │ QA/DevOps │──►│ Governance│",
            " └─────┬─────┘     └─────┬─────┘   └─────┬─────┘   └─────┬─────┘     └─────┬─────┘   └─────┬─────┘",
            "       │                 │               │               │                 │               │",
            "    Fachteam          Fachteam        Fachteam        Fachteam          Fachteam        Fachteam",
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
