"""
agents/orchestrator/ – Der Hauptagent (Orchestrator) mit Fachbereichs-Teamleiter-Hierarchie

Workflow:
1. Der Nutzer übergibt die Gesamtaufgabe an den Hauptagenten (Orchestrator).
2. Der Hauptagent teilt die Gesamtaufgabe in 6 Fachbereiche auf:
   - 🔵 Planung, Analyse & Architektur (geführt von Planning Lead)
   - 🎨 Vorab-Design, UI/UX & Media (geführt von Design Lead)
   - 🟢 Kern-Entwicklung (geführt von Dev Lead)
   - 📚 Content, Doku & Barrierefreiheit (geführt von Content & Doc Lead)
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

---

Struktur-Refactoring (dieses Paket ersetzt das frühere monolithische
agents/orchestrator.py, keine Verhaltensänderung): die Orchestrierungs-Logik ist nach
fachlichen Verantwortlichkeiten in Mixins aufgeteilt, die die Orchestrator-Klasse hier
zusammensetzt:

- department.py     – DepartmentMixin: Fachbereichs-Hierarchie (Delegation/Konsolidierung)
- verification.py   – VerificationMixin: Governance-Fix-Schleife & echte Test-/Deployment-Verifikation
- dispatch.py        – DispatchMixin: Agenten-Dispatch/Routing (einzeln & parallel)
- budget.py          – BudgetMixin: Budget-/Kosten-Tracking (Lauf- & Projekt-Budget)
- retrospective.py  – RetrospectiveMixin: Retrospektive & Agent-Trainer-Selbstoptimierung
- reporting.py       – ReportingMixin: deterministische Berichts-/Statusbausteine
- constants.py       – gemeinsame Modul-Konstanten (PHASE_ORDER, REVIEW_ONLY_AGENT_IDS, ...)

Alle bisherigen Importpfade (`from agents.orchestrator import Orchestrator, ...`) bleiben
unverändert nutzbar – siehe Re-Exports unten.
"""

import asyncio
import time
from collections.abc import Callable
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
from agents.orchestrator.reporting import ReportingMixin
from agents.orchestrator.retrospective import RetrospectiveMixin
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
    ORCHESTRATOR_MODEL,
    PLAN_CONFIRMATION_MIN_TASKS,
)
from core.adr import format_adr_summary_for_context
from core.backlog_store import upsert_ticket
from core.design_system import format_design_system_for_agents
from core.git_isolation import (
    GitIsolationError,
    create_isolated_worktree,
    find_git_root,
    has_uncommitted_changes,
)
from core.notifier import notify_external
from core.optimization_advisor import analyze as analyze_optimization_potential
from core.optimization_advisor import format_report_for_humans as format_optimization_report
from core.project_constitution import format_constitution_for_agents, get_max_project_tokens
from core.project_status import (
    MAX_FAILURE_DETAIL_CHARS,
    count_consecutive_failed_runs,
    format_context_for_agents,
    has_repeated_failure,
    read_status,
    save_project_checkpoint,
)
from core.result_aggregator import ResultAggregator
from core.task_manager import TaskManager
from core.token_guard import token_guard
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
    VerificationMixin,
    DispatchMixin,
    BudgetMixin,
    RetrospectiveMixin,
    ReportingMixin,
):
    """
    Hauptagent, der die 6 Fachbereichs-Teamleiter und deren 33 Spezialisten koordiniert.
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

        # Vom TaskManager erzeugte, kurze Zusammenfassung der zuletzt verarbeiteten Aufgabe
        # (nicht die rohe Nutzereingabe) – von interface/cli.py für die Commit-Message
        # verwendet, siehe _ask_for_git_push(). Leer, solange noch kein Lauf abgeschlossen ist.
        self.last_task_summary: str = ""
        # Kurzer, garantiert saniertes Projekt-Slug (siehe core/workspace.py) des letzten Laufs -
        # zuverlässiger Fallback fuer die Commit-Message, falls last_task_summary trotz
        # verschärftem DECOMPOSE_SYSTEM_PROMPT (core/task_manager.py) doch nur ein Echo der
        # rohen, oft konversationellen Nutzereingabe ist (real beobachtet, z.B. "Ich möchte
        # das ihr ein neues Projekt erstellt. Es" als Commit-Betreff).
        self.last_project_slug: str = ""
        # Zuletzt für einen Selbstverbesserungslauf angelegter, isolierter Git-Worktree (siehe
        # core/git_isolation.py) – None, solange noch kein solcher Lauf stattfand. Wird NICHT
        # automatisch entfernt; der Mensch reviewt/merged/löscht ihn bewusst selbst.
        self.last_isolated_worktree = None
        # True NUR, wenn die echte Testsuite des letzten Laufs tatsächlich gelaufen UND
        # bestanden ist (siehe _run_verification_loop) – von interface/cli.py genutzt, um vor
        # dem Git-Push-Gate zu warnen, statt unkommentiert "fertig" wirken zu lassen.
        self.last_verification_ok: bool = False
        # Das vollständige Verifikations-Protokoll des letzten Laufs (dieselbe Markdown-Sektion,
        # die auch final_output/den Chat-Verlauf ergänzt) - realer Fund am Pong-Projekt:
        # last_verification_ok allein warnte zwar VOR dem Push im Terminal, aber der
        # tatsächlich auf GitHub erstellte Pull Request trug KEINE dieser Information - ein
        # Reviewer, der nur den PR sieht (nicht die Terminal-Session, in der er entstand),
        # hatte keine Chance zu erkennen, dass die echte Testsuite nie bestätigt bestanden
        # hatte. interface/cli.py._ask_for_git_push() bettet das jetzt direkt in den PR-Body ein.
        self.last_verification_summary: str = ""
        # True, wenn mindestens eine Fachrolle im letzten Lauf `ask_human_for_clarification`
        # genutzt hat (core/agent_toolbox.py) - eine echte, für die Aufgabe entscheidende
        # Unklarheit, die NICHT geraten wurde. Getrennt von last_verification_ok: eine
        # fehlgeschlagene Testsuite und eine offene Rückfrage sind verschiedene Gründe, einem
        # Ergebnis nicht blind zu vertrauen, und verdienen unterschiedlichen Klartext im
        # Push-Gate (interface/cli.py) bzw. in autonomen Läufen (core/backlog_worker.py).
        self.last_needs_human_input: bool = False
        self.last_clarification_questions: list[str] = []
        # True, wenn MAX_RUN_TOKENS oder das Pro-Projekt-Budget (/constitution) im letzten Lauf
        # überschritten wurde und deshalb verbleibende Fachbereiche/Mitglieder übersprungen
        # wurden (siehe process(), lokale budget_aborted-Variable) - von interface/cli.py
        # genutzt, um einen so vorzeitig beendeten Lauf im PR (Titel/Label/Body) genauso
        # unübersehbar zu machen wie eine fehlgeschlagene Verifikation, statt dass nur
        # .ai_team_status.json davon weiß.
        self.last_budget_aborted: bool = False
        # Pro-Projekt-Kostenbudget (core/project_constitution.py `max_project_tokens`,
        # /constitution) - unabhängig vom globalen MAX_RUN_TOKENS (das begrenzt nur EINEN
        # einzelnen Lauf). Bei jedem process()-Aufruf frisch aus der Konstitution des jeweils
        # bearbeiteten Projekts gesetzt; 0 = kein Projekt-Budget aktiv (Standard, Verhalten
        # unverändert). _project_tokens_before_run ist die bereits über frühere Läufe an
        # DIESEM Projekt verbrauchte Summe (memory/run_history.py) - der aktuelle Lauf zählt on
        # top über den bestehenden _tokens_used_since()-Mechanismus.
        self._project_token_budget: int = 0
        self._project_tokens_before_run: int = 0

    async def process(
        self,
        user_request: str,
        status_callback: StatusCallback | None = None,
        forced_project_dir: str | None = None,
        plan_confirmation_callback: PlanConfirmationCallback | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> str:
        """
        plan_confirmation_callback: Wenn gesetzt, wird NACH der Aufgaben-Zerlegung, aber VOR
        jeder Ausführung aufgerufen, WENN der Plan mindestens PLAN_CONFIRMATION_MIN_TASKS
        Teilaufgaben umfasst (kleine, klar umrissene Aufgaben laufen ohne Rückfrage durch) -
        lehnt der Callback ab, bricht der Lauf sauber ab, OHNE dass auch nur ein Agent
        gestartet wurde (kein Tokenverbrauch für einen möglicherweise zu groß geratenen Plan).

        cancel_requested: Wenn gesetzt, wird VOR jeder Fachbereichs-Phase und VOR jedem
        Verifikations-/Fixversuch abgefragt (dieselben Prüfpunkte wie das bestehende
        MAX_RUN_TOKENS-Budget) – liefert er zu einem dieser Zeitpunkte True, wird der Lauf
        wie beim Budget graceful beendet: verbleibende Arbeit übersprungen, bereits
        Erarbeitetes trotzdem synthetisiert und ausgeliefert (kein bereits investierter
        Tokenverbrauch verpufft ungenutzt). None (Standard) = kein Abbruch-Mechanismus
        verfügbar – nur interface/cli.py (Strg+C) und interface/web_dashboard.py
        (Job-Cancel-Endpunkt) reichen aktuell einen echten Callback durch.

        forced_project_dir: Wenn gesetzt (von interface/cli.py nach `/load <projekt>` befüllt),
        arbeitet dieser Lauf IMMER in diesem Verzeichnis statt in einem frisch vom Modell
        geratenen project_slug. Behebt einen realen Fund: `/load` setzte bisher zwar
        `_loaded_project_dir`, das aber nirgends an process() durchgereicht wurde – jede
        Chat-Nachricht landete trotz vorherigem `/load` in einem NEUEN Workspace-Ordner, statt
        das geladene Projekt tatsächlich weiterzuentwickeln (Ursache mehrerer beobachteter
        Duplikate wie `calculator_service`/`simple_calculator`).
        """
        overall_start_time = time.monotonic()
        # Schnappschuss des GLOBALEN Tokenzählers (core/token_guard.py) vor diesem Lauf – nicht
        # der Zähler selbst, da der Prozess (CLI-Sitzung/Dashboard-Worker) mehrere Läufe teilt.
        # Der Verbrauch DIESES Laufs ergibt sich aus der Differenz zum aktuellen Stand (siehe
        # _tokens_used_since()) und ist die Grundlage für das harte MAX_RUN_TOKENS-Budget.
        run_start_tokens = token_guard.get_summary()["grand_total_tokens"]
        # Zusätzlich die Pro-Modell-Aufschlüsselung sichern (nicht nur den Gesamtwert) – Basis
        # für die persistente, sitzungsübergreifende Kosten-Historie (memory/cost_history.py),
        # die pro Modell/Provider mitschreibt, nicht nur einen einzelnen Gesamtwert.
        run_start_model_stats = token_guard.get_summary()["models"]

        def notify(msg: str):
            if status_callback:
                status_callback(msg)

        notify("⚡ [bold cyan]Phase 0/5:[/bold cyan] Hauptagent analysiert Aufgabe und weist Fachbereichs-Teamleiter zu...")
        self._history.add_user_message(user_request)

        context = self._history.get_context_string(max_messages=4)
        task_summary, project_slug, agent_tasks = await self._task_manager.decompose(
            user_request, conversation_context=context
        )
        # Für die Commit-Message-Vorschau in interface/cli.py: eine ECHTE, vom Modell erstellte
        # Kurzfassung statt der rohen (oft konversationellen) Nutzereingabe. Wird auch bei einem
        # Abbruch unten (keine Aufgaben ableitbar) nicht überschrieben, bleibt dann leer/alt.
        if agent_tasks:
            self.last_task_summary = task_summary

        if not agent_tasks:
            # task_summary enthaelt bei einem echten Provider-Ausfall ("⚠️") oder einer
            # Rueckfrage bei zu unklarer Aufgabe ("❓", siehe TaskManager.decompose()) bereits
            # den konkreten Grund/die Fragen - sonst generischer Fallback.
            response = task_summary if task_summary.startswith(("⚠️", "❓")) else (
                "⚠️ Ich konnte keine passenden Aufgaben ableiten. Bitte beschreibe die Aufgabe genauer."
            )
            self._history.add_assistant_message(response)
            return response

        notify(f"📋 [bold white]Gesamtplan:[/bold white] {task_summary}")

        # Plan-Freigabe-Gate: NACH der Zerlegung, aber VOR jeder Ausführung - noch kein Agent
        # hat zu diesem Zeitpunkt auch nur einen Token verbraucht. Nur ab einer gewissen
        # Plangröße (PLAN_CONFIRMATION_MIN_TASKS), damit kleine, klar umrissene Aufgaben
        # weiterhin ohne Rückfrage durchlaufen - dieselbe "kein Overhead im Alltagsfall"-
        # Abwägung wie bei der sequenziellen Ausführung kleiner Fachbereiche.
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
            # Explizit per /load geladenes (externes/Workspace-)Projekt: project_slug (vom
            # Modell geraten) wird bewusst ignoriert – der Mensch hat das Zielverzeichnis
            # bereits selbst gewählt.
            candidate_dir = forced_project_dir
            notify(f"📂 [dim]Arbeite im geladenen Projekt: {candidate_dir}[/dim]")
        else:
            # Frühwarnung vor stillschweigend doppelter Arbeit: project_slug wird pro Lauf neu vom
            # Modell geraten und unterscheidet sich oft, selbst wenn die Aufgabe inhaltlich dieselbe
            # ist wie ein früherer Lauf – real beobachtet u.a. bei "calculator_service" vs.
            # "simple_calculator" und "notes_tasks_api" vs. "personal_notes_tasks": zwei komplette,
            # separat bezahlte Läufe für praktisch dieselbe Anwendung. Rein informativ (keine
            # Heuristik/kein LLM-Aufruf, also kostenlos) – der Mensch entscheidet, ob `/load <name>`
            # statt eines neuen Projekts die bessere Wahl gewesen wäre.
            existing_projects = self._workspace.list_projects()
            if project_slug not in existing_projects and existing_projects:
                # Realer Fund (Retrospektive zu vier separaten Läufen an praktisch derselben
                # Aufgabe - "fastapi-task-mgmt", "fastapi_task_websocket", "kanban_board",
                # "kanban_task_manager"): die reine Namensliste allein macht nicht sichtbar,
                # dass ein bereits vorhandenes Projekt beim letzten Lauf gar nicht verifiziert
                # werden konnte - ein weiterer, komplett neuer Versuch wirkt dadurch günstiger,
                # als er ist. Zeigt zusätzlich den zuletzt protokollierten Status jedes
                # vorhandenen Projekts an, weiterhin rein informativ (kein LLM-Aufruf).
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
                # Realer Fund: bei mehreren, kurz aufeinanderfolgenden Läufen INNERHALB
                # derselben Sitzung (z.B. durch eine beim Einfügen zerrissene Nutzereingabe,
                # die als mehrere separate Prompts ankam) sprang project_slug zwischen völlig
                # unterschiedlichen Ordnernamen für dieselbe eigentliche Aufgabe hin und her -
                # die generische Liste "Bereits vorhanden: ..." ging dabei im Rauschen älterer
                # Projekte unter, obwohl DIESE Sitzung erst Sekunden zuvor schon an einem
                # Projekt gearbeitet hatte. self.last_project_slug (von genau DIESEM
                # Orchestrator-Objekt, also nur innerhalb der aktuellen Sitzung gesetzt, siehe
                # __init__) bekommt deshalb eine eigene, vorangestellte Zeile - weiterhin rein
                # informativ, der Mensch entscheidet nach wie vor selbst über `/load <name>`.
                same_session_hint = ""
                if self.last_project_slug and self.last_project_slug != project_slug:
                    same_session_hint = (
                        f"🕒 [dim]Hinweis: In DIESER Sitzung wurde zuletzt an `{self.last_project_slug}` "
                        f"gearbeitet – falls die aktuelle Anfrage eigentlich eine Fortsetzung davon ist "
                        f"(z.B. weil eine längere Eingabe in mehrere Nachrichten zerrissen ankam), "
                        f"lieber abbrechen und stattdessen `/load {self.last_project_slug}` nutzen.[/dim]\n"
                    )
                # Realer Fund (Workspace-Audit): "calculator_service" und "modular_calculator_gui"
                # blieben nicht die einzigen Fälle - auch "api_health_monitor" vs. "api-health-monitor"
                # entstand als zwei komplette, separat bezahlte Läufe für dieselbe Aufgabe, obwohl
                # sich der Slug nur durch "_" statt "-" unterschied. Die generische "Bereits
                # vorhanden: ..."-Liste allein hebt so einen fast identischen Namen nicht gezielt
                # hervor - ein eigener, direkter Hinweis bei einem naheliegenden Nahezu-Duplikat
                # (Unterstrich/Bindestrich/Groß-Kleinschreibung ignoriert) macht das jetzt sichtbar.
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

        # Jede Teilaufgabe bekommt ab hier echten Zugriff auf das Projektverzeichnis
        # (read_file/write_file/edit_file/run_command/run_tests via agents/base_agent.py).
        # Realer Fund: ein Selbstverbesserungslauf schrieb früher direkt im echten
        # Arbeitsverzeichnis – dieselbe Gefahr besteht bei JEDEM Lauf gegen bereits
        # vorhandenen Inhalt (z.B. ein per /load geladenes bestehendes Projekt), nicht nur
        # beim Framework selbst. _resolve_project_isolation() isoliert deshalb IMMER, wenn am
        # Zielort bereits echter Inhalt existiert – ein brandneues, leeres Projekt hat nichts
        # zu verlieren und wird bewusst direkt geschrieben (kein Worktree-Overhead für den
        # Alltagsfall "neues Projekt erstellen").
        project_dir, abort_response = await self._resolve_project_isolation(candidate_dir, task_summary, notify)
        if abort_response:
            self._history.add_assistant_message(abort_response)
            return abort_response

        # Der TATSÄCHLICH verwendete Ordnername (nicht der u.U. verworfene project_slug bei
        # forced_project_dir) – zuverlässiger Commit-Message-Fallback, siehe last_project_slug oben.
        self.last_project_slug = Path(project_dir).name

        # Realer Fund (vier separate Läufe an praktisch derselben Aufgabe, alle mit
        # verification_ok=false): der rein informative Duplikat-Hinweis oben wird beim
        # WIEDERHOLTEN Scheitern DESSELBEN Projekts leicht überlesen - "einfach nochmal
        # versuchen" wirkt jedes Mal aufs Neue günstiger, als es tatsächlich ist. Ab der
        # dritten Runde OHNE bestandene Verifikation in Folge (2 bereits erfolgte + der gerade
        # startende) wird die Warnung deshalb deutlich direkter, MIT einer konkreten
        # Handlungsempfehlung (Aufgabe kleiner zerlegen / Budget prüfen) statt nur "informativ".
        # Bewusst weiterhin KEIN automatisches Eingreifen (keine automatische Aufgaben-
        # Zerlegung, keine automatische Budget-Erhöhung) - der Mensch entscheidet nach wie vor
        # selbst, der Lauf wird dadurch nicht blockiert.
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

        # Pro-Projekt-Kostenbudget (siehe __init__): MAX_RUN_TOKENS begrenzt nur DIESEN einen
        # Lauf - ein Projekt mit vielen aufeinanderfolgenden Läufen (z.B. für einen externen
        # Auftraggeber mit festem Kostenrahmen) hatte bisher kein Limit über ALLE Läufe hinweg.
        # Bereits VOR dem ersten Agenten-Aufruf geprüft: ein schon erschöpftes Projekt-Budget
        # bricht den Lauf ab, ohne auch nur einen Token dafür zu verbrauchen (derselbe
        # Grundsatz wie beim Plan-Bestätigungs-Abbruch oben).
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
                return response

        # Projekt-Kontinuität über mehrere Sitzungen hinweg (core/project_status.py): eine
        # neue Sitzung (neues Terminal) hat KEINEN Zugriff auf memory/conversation_history.py
        # (sitzungsgebunden) – die persistente Lauf-Historie DIESES Projekts wird deshalb
        # direkt in den Kontext jeder Teilaufgabe injiziert, damit das Team z.B. sofort sieht,
        # dass der letzte Lauf am Lauf-Budget abgebrochen wurde, statt das nur aus den rohen
        # Quelldateien zu erraten. Leer für ein brandneues Projekt (kein unnötiger Prompt-Text).
        project_history_context = format_context_for_agents(project_dir)

        # Projekt-Konstitution (core/project_constitution.py): feste Tech-Stack-Präferenzen,
        # die der Nutzer einmal per /constitution festlegt (Sprache, Framework, Test-Framework,
        # Code-Stil, Deployment-Ziel) - sonst würde project_slug/Architektur pro Lauf neu vom
        # Modell geraten, selbst am selben Projekt. Leer für Projekte ohne Konstitution (kein
        # unnötiger Prompt-Text für die Mehrheit der Projekte).
        constitution_context = format_constitution_for_agents(project_dir)

        # Projekt-Design-System (core/design_system.py): feste visuelle Präferenzen
        # (Farbpalette, Typografie, Spacing-Skala, Komponenten-Namenskonvention, Tonalität),
        # die der Nutzer einmal per /design-system festlegt - das Pendant zur Konstitution
        # oben, nur für Design statt Tech-Stack. Ohne das würde ein zweiter Lauf am selben
        # Projekt eine andere Primärfarbe/Schriftart wählen können, ohne dass die
        # Nutzeranfrage das je erwähnt hätte. Leer für Projekte ohne Design-System (kein
        # unnötiger Prompt-Text für die Mehrheit der Projekte).
        design_system_context = format_design_system_for_agents(project_dir)

        # Architecture Decision Records (core/adr.py): das WARUM hinter bereits getroffenen
        # Architektur-Entscheidungen (die Konstitution oben hält nur das WAS fest). Ohne das
        # könnten spätere Läufe unbemerkt gegen frühere, bewusst getroffene Entscheidungen
        # arbeiten. Leer für Projekte ohne bisherige ADRs (kein unnötiger Prompt-Text).
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
            if adr_context:
                t.context += f"\n\n{adr_context}"

        # Führe hierarchische Fachbereichs-Ausführung durch
        file_collisions: list[dict] = []
        results, file_owners, budget_aborted, manually_cancelled = await self._run_department_hierarchy(
            user_request=user_request,
            task_summary=task_summary,
            agent_tasks=agent_tasks,
            project_dir=project_dir,
            run_start_tokens=run_start_tokens,
            notify=notify,
            cancel_requested=cancel_requested,
            collision_sink=file_collisions,
        )

        # Fallback-Dateispeicherung: Falls ein Agent trotz Werkzeug-Zugriff Code nur im
        # Antworttext statt über write_file/edit_file geliefert hat, wird er zusätzlich
        # per Regex geparst – ohne bereits über Tools geschriebene Dateien zu überschreiben.
        saved_files_count = 0
        # Realer Fund: bisher zählte der Abschlussbericht nur DIE ANZAHL der so gespeicherten
        # Dateien, nicht WELCHE - eine per Regex aus freiem Antworttext geparste Datei ist
        # fehleranfälliger als ein natives write_file-Tool-Argument (z.B. wenn der Agent nur
        # einen Diff-/Integrations-Ausschnitt statt einer vollständigen Datei geliefert hat,
        # real beobachtet: eine so gespeicherte main.py bestand nur aus einem Patch-Kommentar
        # + drei Zeilen, ohne die dafür nötigen Imports). Python-Syntaxfehler fängt bereits
        # core/workspace.py.parse_and_save_files() ab (CodeSandbox.validate_code), semantisch
        # unvollständige, aber syntaktisch gültige Fragmente wie im realen Fund oben nicht -
        # dafür bleibt core/verifier.py.check_lint() (läuft später) die zuständige Instanz.
        # Diese Liste macht die betroffenen Pfade im Abschlussbericht NAMENTLICH sichtbar,
        # damit ein Lint-/Testfehler an genau dieser Stelle sofort zuordenbar ist, statt in
        # einer anonymen Zahl unterzugehen.
        text_fallback_paths: list[str] = []
        if AUTO_SAVE_WORKSPACE:
            for res in results:
                if res.success and res.content:
                    # project_dir (nicht project_slug!) verwenden: project_dir ist bereits der
                    # tatsächlich verwendete, absolute Zielordner (bei /load der geladene Pfad,
                    # sonst workspace/<slug>/) – get_project_dir() akzeptiert absolute Pfade
                    # direkt (siehe core/workspace.py), landet also garantiert am selben Ort wie
                    # die per Werkzeug-Loop geschriebenen Dateien, statt versehentlich einen
                    # zweiten Ordner unter dem geratenen project_slug anzulegen.
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
        if budget_aborted or manually_cancelled:
            governance_fix_summary = ""
        else:
            results, governance_fix_summary, budget_aborted, manually_cancelled = await self._run_governance_fix_loop(
                project_dir=project_dir,
                all_results=results,
                file_owners=file_owners,
                run_start_tokens=run_start_tokens,
                notify=notify,
                cancel_requested=cancel_requested,
            )

        # Echte Verifikation: Abhängigkeiten installieren, Tests wirklich ausführen,
        # bei Fehlschlägen gezielt den verantwortlichen Agenten korrigieren lassen.
        # Bei bereits während der Fachbereichs-Phasen ODER der Governance-Fix-Schleife
        # überschrittenem Lauf-Budget ODER manuellem Abbruch wird die (potenziell token-/
        # zeitintensive) Fix-Schleife komplett übersprungen.
        if budget_aborted or manually_cancelled:
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
        else:
            results, verification_summary, budget_aborted, manually_cancelled, verification_ok = await self._run_verification_loop(
                project_dir=project_dir,
                all_results=results,
                file_owners=file_owners,
                run_start_tokens=run_start_tokens,
                notify=notify,
                cancel_requested=cancel_requested,
            )
        # Von interface/cli.py vor dem Git-Push-Gate abgefragt (siehe _ask_for_git_push) - eine
        # klare Warnung statt eines unbedingten "alles ok", wenn Code committet werden soll,
        # dessen Tests nie bestätigt bestanden haben.
        self.last_verification_ok = verification_ok
        self.last_verification_summary = verification_summary

        # Härteres Gate gegen wiederholtes, blindes Scheitern (Punkt 4 einer Team-Retrospektive):
        # die reine Prompt-Warnung in format_context_for_agents() (project_history_context oben)
        # verlässt sich darauf, dass ein Agent sie liest UND befolgt - kein hartes Garant. Hier
        # wird deterministisch (kein LLM-Aufruf) geprüft, ob DIESER Lauf erneut nicht verifiziert
        # ist UND der vorherige Fehlertext dem NEUEN stark ähnelt (SequenceMatcher) - d.h. der
        # Agent hat tatsächlich denselben Fehler wiederholt, nicht nur zufällig wieder gescheitert.
        # In diesem Fall wird ein Backlog-Ticket für menschliche Prüfung eröffnet (dieselbe
        # upsert_ticket-Mechanik wie core/workspace_audit.py) statt sich weiter auf einen
        # automatischen Retry zu verlassen - ein sichtbares, system-erzeugtes Signal statt nur
        # eines Prompt-Hinweises, den der nächste Lauf erneut ignorieren könnte.
        if not verification_ok and has_repeated_failure(project_dir):
            previous_history = read_status(project_dir)
            previous_failure_detail = next((e.get("failure_detail") for e in previous_history if e.get("failure_detail")), "")
            # Bugfix (Ultrareview-Fund): previous_failure_detail ist beim Speichern bereits auf
            # MAX_FAILURE_DETAIL_CHARS gekürzt (core/project_status.py.record_run) - wurde hier
            # aber gegen die UNGEKÜRZTE aktuelle verification_summary verglichen. SequenceMatcher.
            # ratio() ist durch 2·min(len(a),len(b))/(len(a)+len(b)) gedeckelt - bei langen,
            # mehrzeiligen Fehlerberichten (mehrere Testfehler + Installationslog) fiel die Quote
            # dadurch systematisch unter die 0.55-Schwelle, selbst bei identischem Fehler. Beide
            # Seiten jetzt symmetrisch auf dieselbe Länge gekürzt.
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
                try:
                    upsert_ticket(
                        ticket_id=f"recurring-failure-{self.last_project_slug}",
                        title=f"Wiederkehrender Verifikations-Fehler: {self.last_project_slug}",
                        source="orchestrator", status="blocked", project_slug=self.last_project_slug,
                        detail=verification_summary.strip()[:300],
                    )
                except Exception as e:
                    notify(f"⚠️ [dim yellow]Ticket für wiederkehrenden Fehler konnte nicht angelegt werden: {e}[/dim yellow]")

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

        # Retrospektive & Automatische Selbstoptimierung – werden bei überschrittenem
        # Lauf-Budget ODER manuellem Abbruch ausgelassen, da sie selbst weitere
        # (nicht-kritische) LLM-Aufrufe kosten.
        total_duration = time.monotonic() - overall_start_time
        retro_result = None
        trainer_result = None
        self.last_budget_aborted = budget_aborted

        if budget_aborted:
            notify(f"🚫 [bold red]{self._budget_exceeded_label(run_start_tokens)} erreicht:[/bold red] Retrospektive & Selbstoptimierung werden übersprungen ({self._tokens_used_since(run_start_tokens):,} Tokens in diesem Lauf).")
            # EIN zentraler Benachrichtigungs-Ort statt an jeder der drei Stellen, an denen
            # budget_aborted innerhalb der Fachbereichs-/Governance-Fix-/Verifikations-Schleifen
            # gesetzt werden kann (core/notifier.py, no-op ohne NOTIFY_WEBHOOK_URL) - relevant
            # v.a. für unbeaufsichtigte Läufe (Dashboard-Job, Issue-Watcher), wo sonst niemand
            # aktiv zusieht, dass ein Lauf vorzeitig beendet wurde.
            await asyncio.to_thread(
                notify_external, "Budget erreicht",
                f"{task_summary[:150]}: {self._budget_exceeded_label(run_start_tokens)} erreicht "
                f"({self._tokens_used_since(run_start_tokens):,} Tokens in diesem Lauf verbraucht).",
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
            )

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

        # Realer Fund: final_solution (die LLM-Synthese oben) reproduzierte in einem echten
        # Lauf Code, der NICHT mit der tatsächlich geschriebenen Datei übereinstimmte (das
        # Modell paraphrasierte aus den Agenten-Berichten statt wortgetreu zu übernehmen) -
        # ein echtes Vertrauensproblem für jeden, der nur den Chat-Output liest, statt die
        # Dateien selbst zu prüfen. Dieser Abschnitt liest die WIRKLICH geschriebenen Dateien
        # direkt von der Platte (kein LLM-Aufruf, daher immer exakt korrekt) - siehe auch die
        # entsprechend angepasste SYNTHESIZE_SYSTEM_PROMPT-Anweisung, keinen vollständigen
        # Code mehr zu reproduzieren.
        real_files_section = self._build_real_files_section(project_dir, file_owners)
        collision_section = self._build_file_collision_section(file_collisions)
        clarification_section = self._build_clarification_section(results)
        self.last_needs_human_input = bool(clarification_section)
        self.last_clarification_questions = [q for r in results for q in r.clarification_questions]

        # Datenbasierte Selbstoptimierungs-Vorschläge (core/optimization_advisor.py) - rein
        # deterministische Auswertung der BEREITS BESTEHENDEN, projektübergreifenden
        # Lauf-Historie (kein zusätzlicher LLM-Aufruf nötig, anders als retrospective/
        # agent_trainer direkt darunter). Bewusst NUR ein Vorschlag, keine automatische
        # Änderung an config.py (siehe Modul-Docstring) - leer für die Mehrheit der Läufe ohne
        # statistisch aussagekräftigen Befund, kein unnötiger Abschnitt im Bericht.
        optimization_section = format_optimization_report(analyze_optimization_potential())

        final_output = (
            f"{final_solution}\n\n"
            f"---\n\n"
            + (f"{real_files_section}\n\n---\n\n" if real_files_section else "")
            + (f"{clarification_section}\n\n---\n\n" if clarification_section else "")
            + (f"{collision_section}\n\n---\n\n" if collision_section else "")
            + (f"{governance_fix_summary}\n\n---\n\n" if governance_fix_summary else "")
            + f"{verification_summary}\n\n"
            f"---\n\n"
            f"{retro_result.content if retro_result else ''}\n\n"
            f"---\n\n"
            f"{trainer_result.content if trainer_result else ''}\n\n"
            f"---\n\n"
            + (f"{optimization_section}\n\n---\n\n" if optimization_section else "")
            + f"{stats_table}"
        )

        self._history.add_assistant_message(final_output)

        # Realer Fund aus einem echten Lauf: alle drei Telemetrie-Aufrufe unten (record_run/
        # record_run_usage/record_run_history) sind laut ihren eigenen Kommentaren/Docstrings
        # als "rein additiv, darf einen sonst erfolgreichen Lauf niemals zum Scheitern bringen"
        # gedacht - waren das bisher aber nur GEGEN I/O-Fehler (record_run() fängt die
        # ausdrücklich ab). Ein KeyError('cache_read_tokens') schlug hier unbehandelt durch bis
        # zum CLI-Top-Level-Handler (interface/cli.py) - der bereits fertig SYNTHETISIERTE, in
        # self._history bereits gespeicherte final_output ging dadurch für den Nutzer komplett
        # verloren, der Lauf landete als "blocked" im Backlog, obwohl die eigentliche
        # Team-Arbeit längst erfolgreich abgeschlossen war. Ursache war zunächst fälschlich als
        # SDK-Eigenheit vermutet - tatsächlich ein simples Schema-Migrations-Loch in
        # memory/cost_history.py.record_run_usage() (siehe dort: setdefault() füllte fehlende
        # Schlüssel nur bei einem komplett NEUEN Modell-Eintrag, nicht bei einem bereits
        # vorhandenen Eintrag aus der Zeit vor cache_read_tokens/cache_write_tokens - seitdem
        # behoben). Jeder der drei Aufrufe unten bleibt trotzdem einzeln in ein eigenes
        # try/except gekapselt (nicht ein gemeinsamer Block), damit
        # ein Fehler in EINEM Telemetrie-Aufruf die anderen beiden nicht auch noch verhindert.
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
            )
        except Exception as e:
            notify(f"⚠️ [dim yellow]Projekt-Historie / State-Checkpoint (save_project_checkpoint) konnte nicht aktualisiert werden: {e}[/dim yellow]")

        try:
            # Kumulierte, sitzungsübergreifende Kosten-Historie (memory/cost_history.py) - anders
            # als core/token_guard.py (reiner In-Memory-Zähler, bei jedem Neustart wieder bei
            # Null) bleibt das über JEDEN künftigen Prozess-Neustart erhalten. Nutzt den
            # Pro-Modell-DELTA seit Laufbeginn, nicht den Gesamtzähler des Prozesses - sonst
            # würde ein zweiter Lauf in derselben Sitzung den ersten erneut mitzählen.
            record_run_usage(self._model_usage_deltas(run_start_model_stats))
        except Exception as e:
            notify(f"⚠️ [dim yellow]Kosten-Historie (record_run_usage) konnte nicht aktualisiert werden: {e}[/dim yellow]")

        try:
            # Realer Fund bei einer Bestandsaufnahme des eigenen Teams: core/project_status.py
            # speichert Historie NUR pro Projekt, memory/cost_history.py NUR kumulierte Summen
            # pro Modell - es gab keine Möglichkeit zu sehen, welche Agenten über die Zeit
            # häufiger scheitern oder wie sich Tokenverbrauch/Dauer PROJEKTÜBERGREIFEND
            # entwickeln (Grundlage für die Observability-Ansicht im Dashboard).
            record_run_history(
                project_slug=self.last_project_slug,
                task_summary=task_summary,
                verification_ok=verification_ok,
                total_tokens=sum(r.total_tokens for r in results),
                duration_seconds=total_duration,
                agent_results=[
                    {"agent_id": r.agent_id, "success": r.success, "total_tokens": r.total_tokens, "model_used": r.model_used}
                    for r in results
                ],
            )
        except Exception as e:
            notify(f"⚠️ [dim yellow]Lauf-Historie (record_run_history) konnte nicht aktualisiert werden: {e}[/dim yellow]")

        # Realer Fund: bisher endete JEDER Lauf mit demselben uneingeschränkten "✅ Fertig!",
        # auch wenn die Verifikation nie bestätigt werden konnte (keine Tests gefunden,
        # Testfehler blieben ungelöst, Budget während der Fixversuche erreicht) - nicht zu
        # unterscheiden von einem echten, verifizierten Erfolg. verification_ok macht das jetzt
        # im allerletzten, am ehesten wahrgenommenen Status sichtbar statt nur im Kleingedruckten
        # des Verifikations-Protokolls weiter oben. manually_cancelled bekommt einen eigenen,
        # dritten Status statt in "NICHT verifiziert" mitzulaufen – der Nutzer hat den Lauf
        # bewusst gestoppt, das ist etwas anderes als ein fehlgeschlagener Test.
        if manually_cancelled:
            notify(
                "⏹️ [bold yellow]Manuell abgebrochen.[/bold yellow] Die bis dahin erarbeiteten Ergebnisse "
                "wurden zusammengefasst – prüfe das Ergebnis, es ist mit hoher Wahrscheinlichkeit unvollständig."
            )
        elif self.last_needs_human_input:
            # Eigener, vierter Status statt nur unter "NICHT verifiziert" mitzulaufen: eine
            # offene Rückfrage ist kein Testfehler, sondern eine bewusste Entscheidung eines
            # Agenten, NICHT zu raten - verdient eigene Sichtbarkeit (siehe
            # _build_clarification_section oben).
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
        """Ignoriert Schreibvarianten, die für einen Menschen praktisch identisch aussehen:
        Groß-/Kleinschreibung sowie "_" vs. "-" (real beobachtete Ursache doppelter Läufe)."""
        return slug.lower().replace("-", "_")

    @classmethod
    def _find_near_duplicate_slug(cls, project_slug: str, existing_projects: list[str]) -> str | None:
        """Findet ein bereits vorhandenes Projekt, dessen normalisierter Name mit dem neuen
        project_slug übereinstimmt, obwohl die Roh-Slugs sich unterscheiden (z.B.
        "api_health_monitor" vs. "api-health-monitor"). Gibt None zurück, wenn keines passt oder
        der Slug ohnehin exakt existiert (dann greift bereits die reguläre Fortsetzungs-Logik)."""
        normalized_new = cls._normalize_slug(project_slug)
        for existing in existing_projects:
            if existing != project_slug and cls._normalize_slug(existing) == normalized_new:
                return existing
        return None

    async def _resolve_project_isolation(
        self, candidate_dir: str, task_summary: str, notify: Callable[[str], None],
    ) -> tuple[str, str | None]:
        """
        Entscheidet, ob candidate_dir isoliert (Git-Worktree) oder direkt verwendet wird.

        Gibt (project_dir, abort_response) zurück: project_dir ist bei einem Abbruch
        bedeutungslos ("") – der Aufrufer MUSS abort_response (falls nicht None) direkt an
        den Nutzer zurückgeben, statt fortzufahren.

        Isoliert wird IMMER, wenn am Zielort bereits echter Inhalt existiert (Framework-Root
        selbst zählt immer dazu) – ein brandneues, leeres Projekt hat nichts zu verlieren und
        wird bewusst direkt geschrieben (kein Worktree-Overhead im Alltagsfall). Kann isoliert
        werden, aber es liegen unkommittete Änderungen am Zielort vor, wird NICHT isoliert
        (ein frischer Worktree basiert auf dem letzten COMMIT und würde diese Änderungen
        unsichtbar machen) – stattdessen wird direkt geschrieben, mit klarer Warnung. Nur beim
        Framework-Root selbst (Selbstverbesserungslauf) führt ein generelles Scheitern der
        Isolation (kein Git-Repo, `git` fehlt) zum Abbruch statt zu einem Fallback auf direktes
        Schreiben – dort ist das Risiko am größten.
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
