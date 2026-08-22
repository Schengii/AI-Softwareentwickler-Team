"""
agents/orchestrator.py – Der Hauptagent (Orchestrator) mit Fachbereichs-Teamleiter-Hierarchie

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
"""

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from agents.accessibility_agent import AccessibilityAgent
from agents.agent_trainer_agent import AgentTrainerAgent
from agents.api_integration_agent import ApiIntegrationAgent
from agents.architect_agent import ArchitectAgent
from agents.backend_agent import BackendAgent
from agents.base_agent import CODE_WRITING_AGENT_IDS, BaseAgent
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
    BASE_DIR,
    ENABLE_DEPARTMENT_LEAD_EXECUTION,
    ENABLE_GOVERNANCE_FIX_LOOP,
    ENABLE_TASK_COMPLEXITY_SCALING,
    MAX_REVIEW_ITERATIONS,
    MAX_RUN_TOKENS,
    MAX_VERIFICATION_ITERATIONS,
    MIN_TEST_COVERAGE,
    ORCHESTRATOR_MODEL,
    PLAN_CONFIRMATION_MIN_TASKS,
)
from core.adr import format_adr_summary_for_context
from core.git_isolation import (
    GitIsolationError,
    create_isolated_worktree,
    find_git_root,
    has_uncommitted_changes,
)
from core.message_bus import AgentResult, AgentTask
from core.notifier import notify_external
from core.project_constitution import format_constitution_for_agents, get_max_project_tokens
from core.project_status import format_context_for_agents, record_run
from core.result_aggregator import ResultAggregator
from core.review_gate import find_critical_findings, route_findings_to_owners
from core.task_manager import TaskManager, is_micro_task
from core.token_guard import token_guard
from core.verifier import ProjectVerifier, VerificationReport
from core.workspace import WorkspaceManager
from memory.conversation_history import ConversationHistory
from memory.cost_history import record_run_usage
from memory.run_history import get_total_tokens_for_project
from memory.run_history import record_run as record_run_history

# Reine Prüf-/Berichts-Agenten: sollen bestehenden Code LESEN und bewerten, aber nicht
# selbst umschreiben (das ist Aufgabe von refactoring/backend/etc.) – spart nebenbei auch
# Tokens, da ihnen ein kleineres Werkzeug-Set (kein write_file/edit_file/run_command) angeboten wird.
REVIEW_ONLY_AGENT_IDS = {"code_reviewer", "compliance", "project_cleaner"}

StatusCallback = Callable[[str], None]

# Optionaler Aufrufer-Hook: bekommt den zerlegten Plan (Zusammenfassung, Projekt-Ordnername,
# vollständige Teilaufgaben-Liste) NACH TaskManager.decompose(), aber VOR jeder Ausführung
# (kein Agent hat zu diesem Zeitpunkt bereits Tokens verbraucht) und entscheidet per Rückgabe-
# wert, ob der Lauf fortgesetzt wird. None (Standard) = kein Gate, unverändertes Verhalten -
# nur interface/cli.py reicht aktuell einen echten Callback durch (Dashboard/MCP bleiben
# dadurch bewusst nicht-interaktiv, siehe config.ENABLE_PLAN_CONFIRMATION).
PlanConfirmationCallback = Callable[[str, str, list[AgentTask]], Awaitable[bool]]

# Reihenfolge & Anzeige der 6 Fachbereichs-Phasen. Die Mitgliederlisten stammen
# zentral aus DEPARTMENT_DEFINITIONS (agents/department_lead_agent.py), damit
# Orchestrator und Teamleiter-Prompts nie auseinanderlaufen können.
#
# Design-vor-Dev: UI/UX, Design-Tokens und visuelle Assets (design_lead) werden
# VOR der Software-Entwicklung (dev_lead) erstellt, damit Entwickler diese direkt
# einbinden können. Dokumentation, i18n und Barrierefreiheit (content_lead) laufen
# NACH der Entwicklung auf dem tatsächlich erzeugten Code.
PHASE_ORDER = [
    ("planning_lead",   "Fachbereich 1/6: Planung & Architektur", "👔", "sequential"),
    ("design_lead",     "Fachbereich 2/6: UI/UX, Design & Media", "🎨", "parallel"),
    ("dev_lead",        "Fachbereich 3/6: Software-Entwicklung", "⚡", "parallel"),
    ("content_lead",    "Fachbereich 4/6: Content, Doku & Barrierefreiheit", "📚", "parallel"),
    ("qa_lead",         "Fachbereich 5/6: Qualität & Security", "🛡️", "parallel"),
    ("governance_lead", "Fachbereich 6/6: Review & Governance", "🔍", "sequential"),
]


class Orchestrator:
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
                shown = ", ".join(existing_projects[:10])
                more = f" (+{len(existing_projects) - 10} weitere)" if len(existing_projects) > 10 else ""
                notify(
                    f"🗂️ [dim]Neues Projekt '{project_slug}' wird angelegt. Bereits vorhanden: "
                    f"{shown}{more} – falls du an einem davon weiterarbeiten wolltest, nutze "
                    f"stattdessen `/load <name>`.[/dim]"
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
                    for f in new_files:
                        file_owners[f.relative_path] = res.agent_id

            if saved_files_count > 0:
                notify(f"💾 [green]Workspace:[/green] {saved_files_count} zusätzliche Projektdateien (Text-Fallback) in `{project_dir}` gespeichert.")

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

        final_output = (
            f"{final_solution}\n\n"
            f"---\n\n"
            + (f"{real_files_section}\n\n---\n\n" if real_files_section else "")
            + (f"{collision_section}\n\n---\n\n" if collision_section else "")
            + (f"{governance_fix_summary}\n\n---\n\n" if governance_fix_summary else "")
            + f"{verification_summary}\n\n"
            f"---\n\n"
            f"{retro_result.content if retro_result else ''}\n\n"
            f"---\n\n"
            f"{trainer_result.content if trainer_result else ''}\n\n"
            f"---\n\n"
            f"{stats_table}"
        )

        self._history.add_assistant_message(final_output)

        # Projekt-Kontinuität über mehrere Sitzungen hinweg (core/project_status.py) - siehe
        # Injektion weiter oben. record_run() ist rein additiv (I/O-Fehler werden dort
        # verschluckt), darf also niemals einen sonst erfolgreichen Lauf zum Scheitern bringen.
        record_run(
            project_dir=project_dir,
            task_summary=task_summary,
            verification_ok=verification_ok,
            budget_aborted=budget_aborted,
            cancelled=manually_cancelled,
            files_written_count=len({f for r in results for f in r.files_written}),
        )

        # Kumulierte, sitzungsübergreifende Kosten-Historie (memory/cost_history.py) - anders
        # als core/token_guard.py (reiner In-Memory-Zähler, bei jedem Neustart wieder bei
        # Null) bleibt das über JEDEN künftigen Prozess-Neustart erhalten. Rein additiv wie
        # record_run() oben, darf also niemals einen sonst erfolgreichen Lauf zum Scheitern
        # bringen. Nutzt den Pro-Modell-DELTA seit Laufbeginn, nicht den Gesamtzähler des
        # Prozesses - sonst würde ein zweiter Lauf in derselben Sitzung den ersten erneut
        # mitzählen.
        record_run_usage(self._model_usage_deltas(run_start_model_stats))

        # Realer Fund bei einer Bestandsaufnahme des eigenen Teams: core/project_status.py
        # speichert Historie NUR pro Projekt, memory/cost_history.py NUR kumulierte Summen
        # pro Modell - es gab keine Möglichkeit zu sehen, welche Agenten über die Zeit
        # häufiger scheitern oder wie sich Tokenverbrauch/Dauer PROJEKTÜBERGREIFEND
        # entwickeln (Grundlage für die Observability-Ansicht im Dashboard). Rein additiv
        # wie record_run()/record_run_usage() oben, darf einen sonst erfolgreichen Lauf
        # niemals zum Scheitern bringen.
        record_run_history(
            project_slug=self.last_project_slug,
            task_summary=task_summary,
            verification_ok=verification_ok,
            total_tokens=sum(r.total_tokens for r in results),
            duration_seconds=total_duration,
            agent_results=[{"agent_id": r.agent_id, "success": r.success, "total_tokens": r.total_tokens} for r in results],
        )

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
        elif verification_ok:
            notify("✅ [bold green]Fertig![/bold green] Alle Fachbereiche haben ihre Aufgaben erfolgreich abgeschlossen.")
        else:
            notify(
                "⚠️ [bold yellow]Fertig, aber NICHT verifiziert![/bold yellow] Die echte Testsuite hat den "
                "Code nicht bestätigt (siehe Verifikations-Protokoll oben) – prüfe das Ergebnis, bevor du es übernimmst."
            )
        return final_output

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
        run_start_tokens: int | None = None,
        cancel_requested: Callable[[], bool] | None = None,
        collision_sink: list[dict] | None = None,
    ) -> tuple[list[AgentResult], dict[str, str], bool, bool]:
        """
        Führt alle 5 Fachbereichs-Phasen aus. Jede Phase lässt (sofern
        ENABLE_DEPARTMENT_LEAD_EXECUTION aktiv ist) den zuständigen Teamleiter
        per echtem LLM-Aufruf delegieren und konsolidieren – keine simulierten
        Statusmeldungen mehr, sondern echte Leitungs-Ergebnisse im Report.

        Gibt zusätzlich zurück, ob (1) das harte Lauf-Budget (MAX_RUN_TOKENS) erreicht wurde
        (run_start_tokens=None -> Budget-Prüfung deaktiviert, z.B. für bestehende Aufrufer/
        Tests ohne Budget-Bezug) und (2) ob der Lauf manuell abgebrochen wurde
        (cancel_requested=None -> kein Abbruch-Mechanismus verfügbar) – in beiden Fällen
        werden verbleibende Fachbereiche übersprungen, die bisherigen Ergebnisse aber
        trotzdem ausgeliefert (dieselbe Graceful-Degradation, nur mit unterschiedlichem, für
        den Nutzer ehrlich benanntem Grund).

        collision_sink: Wenn gesetzt, sammelt process() hier gefundene Datei-Kollisionen
        zwischen parallel laufenden Fachteam-Mitgliedern ein (siehe
        _detect_file_write_collisions) für den deterministischen Abschnitt im Abschlussbericht
        (_build_file_collision_section). None (Standard) = nur die Live-Warnung, keine
        Sammlung – bestehende Aufrufer/Tests ohne Interesse an diesem Detail bleiben
        unverändert.
        """
        all_results: list[AgentResult] = []
        file_owners: dict[str, str] = {}
        task_map = {t.agent_id: t for t in agent_tasks}
        running_context = ""  # Kompakter Kontext aus vorherigen Phasen (z.B. Planungsergebnisse)
        budget_aborted = False
        manually_cancelled = False
        # Realer Fund: eine triviale Ein-Endpunkt-Aufgabe verbrauchte 66.000 Tokens, weil
        # jeder Fachbereich mit nur EINEM Mitglied trotzdem die volle Teamleiter-Delegation+
        # Konsolidierung durchlief (siehe ENABLE_TASK_COMPLEXITY_SCALING in config.py für
        # Details). Einmalig aus dem bereits erstellten Plan berechnet, kein zusätzlicher
        # LLM-Aufruf.
        task_is_micro = ENABLE_TASK_COMPLEXITY_SCALING and is_micro_task(agent_tasks)

        for dept_id, phase_label, icon, run_mode in PHASE_ORDER:
            if run_start_tokens is not None and (
                self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
            ):
                budget_aborted = True
                notify(
                    f"🚫 [bold red]{self._budget_exceeded_label(run_start_tokens)} erreicht:[/bold red] "
                    f"{self._tokens_used_since(run_start_tokens):,} Tokens in diesem Lauf verbraucht – "
                    f"überspringe verbleibende Fachbereiche ab '{phase_label}' und liefere die bisherigen "
                    "Ergebnisse aus."
                )
                break
            if cancel_requested and cancel_requested():
                manually_cancelled = True
                notify(
                    f"⏹️ [bold red]Lauf manuell abgebrochen[/bold red] – überspringe verbleibende "
                    f"Fachbereiche ab '{phase_label}' und liefere die bisherigen Ergebnisse aus."
                )
                break

            member_ids = DEPARTMENT_DEFINITIONS[dept_id]["members"]
            member_tasks = [task_map[aid] for aid in member_ids if aid in task_map]
            if not member_tasks:
                continue

            lead = self._dept_leads[dept_id]
            notify(f"{icon} [bold cyan]{phase_label}[/bold cyan] (Geleitet von: {lead.name})...")

            if running_context:
                for task in member_tasks:
                    task.context += f"\n\n## Kontext aus vorherigen Fachbereichen:\n{running_context[:2500]}"

            # Nur EIN Mitglied trägt hier die gesamte Fachbereichsarbeit - bei einer insgesamt
            # kleinen Aufgabe fehlt der Abstimmungsbedarf, den Delegation+Konsolidierung
            # eigentlich rechtfertigt (siehe task_is_micro oben). Fachbereiche mit mehreren
            # Mitgliedern behalten die Teamleiter-Koordination IMMER.
            skip_lead_layer = task_is_micro and len(member_tasks) == 1

            # ── Echte Delegation durch den Teamleiter ──
            if ENABLE_DEPARTMENT_LEAD_EXECUTION and not skip_lead_layer:
                delegation = await self._run_department_delegation(lead, task_summary, member_tasks, project_dir)
                all_results.append(delegation)
                if delegation.success and delegation.content:
                    notify(f"  📤 [cyan]{lead.name} delegiert:[/cyan] {self._first_line(delegation.content)}")
                    for task in member_tasks:
                        task.context += f"\n\n## Arbeitsauftrag von {lead.name}:\n{delegation.content[:1200]}"
                else:
                    notify(f"  ⚠️ [yellow]{lead.name} konnte nicht delegieren ({delegation.error}) – Fachteam startet ohne Zusatzanweisung.[/yellow]")
            elif skip_lead_layer:
                notify(f"  ℹ️ [dim]Kleine Aufgabe, einziges Mitglied – Delegation/Konsolidierung durch {lead.name} übersprungen.[/dim]")

            # ── Fachteam arbeitet (parallel oder sequentiell, je nach Phase) ──
            # Realer Fund: bei nur 1-2 Mitgliedern eines eigentlich "parallelen" Fachbereichs
            # (typisch für klar umrissene Aufgaben) sahen sich die Agenten NIE gegenseitig, weil
            # beide fast zeitgleich starten und der Dateibaum beim jeweils eigenen Start noch
            # leer war (agents/base_agent.py._run_agentic_loop() zeigt zwar IMMER den aktuellen
            # Dateibaum, aber eben nur den zum eigenen Startzeitpunkt) – das produzierte real
            # zwei parallele Implementierungen derselben Sache (app.py/test_app.py UND separat
            # main.py/test_main.py für denselben Health-Check-Endpoint). Bei so wenigen
            # Mitgliedern ist der Latenzgewinn durch Parallelität gering, der Sichtbarkeitsgewinn
            # durch echte Sequenzialität aber groß – deshalb wird hier bewusst NIE parallelisiert,
            # unabhängig von der für den Fachbereich generell hinterlegten Präferenz.
            effective_run_mode = "sequential" if len(member_tasks) <= 2 else run_mode
            if effective_run_mode == "parallel":
                for task in member_tasks:
                    notify(f"  ▶️ [yellow]Fachteam arbeitet:[/yellow] {self._agents[task.agent_id].name}...")
                member_results = await self._run_agents_parallel(member_tasks, notify=notify)
                # Direkte Folge desselben strukturellen Problems wie im Kommentar oben: sehen
                # sich parallel laufende Agenten nie gegenseitig, kann das auch dazu führen,
                # dass ZWEI von ihnen dieselbe Datei schreiben (z.B. requirements.txt,
                # README.md) - core/agent_toolbox.py._tool_write_file() überschreibt dabei
                # blind, KEIN Lock/Merge. _update_file_owners() unten würde den zuerst
                # geschriebenen Stand dann still verwerfen (nur der laut Ergebnis-Reihenfolge
                # letzte Schreiber gewinnt als "Owner"). Da automatisch nicht entscheidbar ist,
                # welche Version die richtige ist, wird der Fund hier NUR sichtbar gemacht
                # (Live-Warnung + Eintrag in collision_sink für den Abschlussbericht) statt
                # geblockt - dieselbe "melden statt raten"-Philosophie wie bei fehlgeschlagener
                # Verifikation.
                collisions = self._detect_file_write_collisions(member_results)
                if collisions:
                    collision_desc = "; ".join(
                        f"`{path}` ({', '.join(agents)})" for path, agents in collisions.items()
                    )
                    notify(
                        f"  ⚠️ [bold yellow]Datei-Kollision:[/bold yellow] mehrere gleichzeitig "
                        f"arbeitende Fachteam-Mitglieder haben dieselbe Datei geschrieben – die "
                        f"zuerst geschriebene Version könnte überschrieben worden sein: {collision_desc}"
                    )
                    if collision_sink is not None:
                        for path, agents in collisions.items():
                            collision_sink.append({"phase": phase_label, "path": path, "agents": agents})
            else:
                member_results = []
                for task in member_tasks:
                    agent_name = self._agents[task.agent_id].name
                    notify(f"  ▶️ [yellow]Fachteam arbeitet:[/yellow] {agent_name}...")
                    start_t = time.monotonic()
                    res = await self._run_single_agent(task)
                    dur = time.monotonic() - start_t
                    member_results.append(res)
                    notify(self._status_notify_line("✅ [green]Fertig[/green]", "❌ [red]Fehler[/red]", agent_name, dur, res.success, res.error))

            all_results.extend(member_results)
            self._update_file_owners(file_owners, member_results)
            # Auf die letzten ~3000 Zeichen begrenzen, damit der Kontext über 5 Phasen hinweg
            # nicht unbegrenzt wächst und jedem folgenden Agenten unnötig viele Tokens kostet.
            running_context = (running_context + self._format_results_for_review(member_results)[:2000])[-3000:]

            # ── Echte Konsolidierung durch den Teamleiter ──
            if ENABLE_DEPARTMENT_LEAD_EXECUTION and not skip_lead_layer:
                consolidation = await self._run_department_consolidation(lead, member_results, project_dir)
                all_results.append(consolidation)
                if consolidation.success and consolidation.content:
                    notify(f"  📥 [bold green]{lead.name} konsolidiert:[/bold green] {self._first_line(consolidation.content)}")
                else:
                    notify(f"  ⚠️ [yellow]{lead.name} konnte den Bereich nicht konsolidieren ({consolidation.error}).[/yellow]")
            else:
                notify(f"  📥 [dim]{phase_label} abgeschlossen ({len(member_results)} Ergebnisse).[/dim]")

        return all_results, file_owners, budget_aborted, manually_cancelled

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
            # Realer Fund: 3 Iterationen wurden in einem echten Lauf tatsächlich ausgeschöpft,
            # bevor eine finale Zusammenfassung entstand (siehe agents/base_agent.py für die
            # begleitende "letzte Gelegenheit"-Aufforderung, die dasselbe Problem zusätzlich
            # abmildert) - moderat auf 4 angehoben, ohne die Rolle mit vollem Entwickler-Budget
            # (Standard 6) auszustatten, da es sich weiterhin um einen rein lesenden Aufruf handelt.
            max_tool_iterations=4,
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
            # Realer Fund: 4 Iterationen wurden in einem echten Lauf tatsächlich ausgeschöpft,
            # bevor eine finale Zusammenfassung entstand - moderat auf 5 angehoben (siehe
            # dieselbe Begründung wie bei _run_department_delegation oben).
            max_tool_iterations=5,
        )
        return await lead.execute(task)

    @staticmethod
    def _status_notify_line(icon_success: str, icon_failure: str, agent_name: str, duration: float, success: bool, error: str | None) -> str:
        """
        Baut die Live-Statuszeile für einen abgeschlossenen Agenten-Aufruf. Realer Fund aus
        einem echten Lauf: Bei einem Fehlschlag zeigte diese Zeile bisher NUR "❌ Fehler:
        <Agent> (61.7s)" ohne jeden Hinweis auf die Ursache – der reale Fehlertext (AgentResult.error)
        landete nirgends beim Nutzer, weder live noch im Endergebnis, nur (verkürzt/paraphrasiert)
        in der von einem LLM verfassten Retrospektive. Jetzt wird der rohe Fehlertext direkt mitgeliefert.
        """
        icon = icon_success if success else icon_failure
        error_note = f" — {error[:200]}" if not success and error else ""
        return f"  {icon}: {agent_name} ({duration:.1f}s){error_note}"

    @staticmethod
    def _first_line(text: str, max_chars: int = 160) -> str:
        first = next((line.strip() for line in text.splitlines() if line.strip()), "")
        return (first[:max_chars] + "…") if len(first) > max_chars else first

    @staticmethod
    def _tokens_used_since(start_tokens: int) -> int:
        """Tokenverbrauch SEIT dem Schnappschuss start_tokens (nicht der globale Gesamtzähler)."""
        return token_guard.get_summary()["grand_total_tokens"] - start_tokens

    @staticmethod
    def _model_usage_deltas(start_model_stats: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
        """
        Pro-Modell-Verbrauch SEIT dem Schnappschuss start_model_stats (Pendant zu
        _tokens_used_since(), nur pro Modell statt als einzelner Gesamtwert) – Grundlage für
        memory/cost_history.py.record_run_usage(). Ein Modell, das erst WÄHREND dieses Laufs
        zum ersten Mal genutzt wurde, hatte in start_model_stats naturgemäß noch keinen
        Eintrag (Delta = voller aktueller Wert, nicht 0).
        """
        end_stats = token_guard.get_summary()["models"]
        deltas: dict[str, dict[str, int]] = {}
        for model_name, end_stat in end_stats.items():
            start_stat = start_model_stats.get(model_name, {})
            deltas[model_name] = {
                key: end_stat.get(key, 0) - start_stat.get(key, 0)
                for key in ("total_calls", "prompt_tokens", "completion_tokens", "total_tokens")
            }
        return deltas

    @classmethod
    def _run_budget_exceeded(cls, start_tokens: int) -> bool:
        """MAX_RUN_TOKENS<=0 deaktiviert das harte Budget (Standard) – siehe config.py."""
        if MAX_RUN_TOKENS <= 0:
            return False
        return cls._tokens_used_since(start_tokens) >= MAX_RUN_TOKENS

    def _project_budget_exceeded(self, start_tokens: int) -> bool:
        """
        Pro-Projekt-Kostenbudget (`/constitution` `max_project_tokens`) – unabhängig vom
        globalen MAX_RUN_TOKENS oben, das nur EINEN einzelnen Lauf begrenzt.
        self._project_token_budget<=0 (Standard, kein Feld in der Konstitution gesetzt)
        deaktiviert diese Prüfung vollständig.
        """
        if self._project_token_budget <= 0:
            return False
        total_for_project = self._project_tokens_before_run + self._tokens_used_since(start_tokens)
        return total_for_project >= self._project_token_budget

    def _budget_exceeded_label(self, start_tokens: int) -> str:
        """
        Menschlich lesbare Kennzeichnung, WELCHES der beiden unabhängigen Budgets (Lauf oder
        Projekt) eine Abbruch-Meldung ausgelöst hat – für ehrliche Kommunikation statt
        pauschal auf MAX_RUN_TOKENS zu verweisen, wenn tatsächlich das (u.U. strengere)
        Projekt-Budget bindend war. Nur sinnvoll aufrufbar, wenn mindestens eines von beiden
        tatsächlich überschritten ist.
        """
        if self._project_budget_exceeded(start_tokens):
            return f"Projekt-Budget (`/constitution`, `{self._project_token_budget:,}` Tokens für `{self.last_project_slug}`)"
        return f"Lauf-Budget (`MAX_RUN_TOKENS={MAX_RUN_TOKENS:,}`)"

    def _budget_or_cancel_reason(
        self, budget_aborted: bool, manually_cancelled: bool, stage: str, start_tokens: int | None = None,
    ) -> str:
        """
        Begründungstext für einen übersprungenen nachfolgenden Schritt (Governance-Fix-Schleife/
        Verifikation) – EIN gebündelter Ort statt der Budget-vs.-Abbruch-Fallunterscheidung
        mehrfach inline zu duplizieren. Nur sinnvoll aufrufbar, wenn budget_aborted ODER
        manually_cancelled bereits True ist (siehe process()).
        """
        if budget_aborted:
            label = self._budget_exceeded_label(start_tokens) if start_tokens is not None else f"Lauf-Budget (`MAX_RUN_TOKENS={MAX_RUN_TOKENS:,}`)"
            return f"{label} wurde bereits {stage} erreicht"
        assert manually_cancelled, "aufrufbar nur wenn budget_aborted ODER manually_cancelled True ist"
        return f"Lauf wurde bereits {stage} manuell abgebrochen"

    @staticmethod
    def _update_file_owners(file_owners: dict[str, str], results: list[AgentResult]) -> None:
        """Merkt sich, welcher Agent welche Datei tatsächlich geschrieben hat (für die Verifikationsschleife)."""
        for res in results:
            for rel_path in res.files_written:
                file_owners[rel_path] = res.agent_id

    @staticmethod
    def _detect_file_write_collisions(member_results: list[AgentResult]) -> dict[str, list[str]]:
        """
        Erkennt, ob innerhalb EINES parallelen Ausführungs-Batches (mehrere Fachteam-
        Mitglieder gleichzeitig per asyncio.gather, siehe _run_agents_parallel) mehr als ein
        Agent dieselbe Datei geschrieben hat. Nur für parallele Batches relevant: bei
        sequenzieller Ausführung sieht ein späterer Agent den Stand des früheren bereits auf
        der Platte, ein Überschreiben dort ist eine informierte Entscheidung, keine blinde
        Kollision. Gibt {rel_path: [agent_id, ...]} nur für tatsächlich betroffene Pfade
        zurück (mind. 2 unterschiedliche Schreiber), in stabiler Reihenfolge nach erstem
        Auftreten.
        """
        writers: dict[str, list[str]] = {}
        for res in member_results:
            for rel_path in res.files_written:
                agents = writers.setdefault(rel_path, [])
                if res.agent_id not in agents:
                    agents.append(res.agent_id)
        return {path: agents for path, agents in writers.items() if len(agents) > 1}

    @staticmethod
    def _build_file_collision_section(collisions: list[dict]) -> str:
        """Deterministischer Abschnitt im Abschlussbericht (kein LLM-Aufruf) – siehe collision_sink."""
        if not collisions:
            return ""
        lines = [
            "### ⚠️ Datei-Kollisionen bei paralleler Fachteam-Arbeit",
            "Mehrere gleichzeitig arbeitende Fachteam-Mitglieder haben dieselbe Datei "
            "geschrieben – die jeweils zuerst geschriebene Version könnte überschrieben "
            "worden sein. Bitte die betroffene(n) Datei(en) vor der Weiterverwendung prüfen:",
        ]
        for entry in collisions:
            lines.append(f"- `{entry['path']}` in {entry['phase']}: {', '.join(entry['agents'])}")
        return "\n".join(lines)

    def _format_results_for_review(self, results: list[AgentResult]) -> str:
        blocks = []
        for r in results:
            if r.success and r.content:
                files_note = f" (Dateien: {', '.join(r.files_written)})" if r.files_written else ""
                blocks.append(f"### Ergebnis von {r.agent_name}{files_note}:\n{r.content[:2000]}")
        return "\n\n".join(blocks)

    # ──────────────────────────────────────────────────────────────
    # Governance-Fix-Schleife: kritische Review-Befunde -> gezielter Korrekturauftrag
    # ──────────────────────────────────────────────────────────────

    async def _run_governance_fix_loop(
        self,
        project_dir: str,
        all_results: list[AgentResult],
        file_owners: dict[str, str],
        notify: Callable[[str], None],
        run_start_tokens: int | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> tuple[list[AgentResult], str, bool, bool]:
        """
        Realer Fund bei einer Bestandsaufnahme des eigenen Teams: code_reviewer/security/
        compliance (REVIEW_ONLY_AGENT_IDS) kategorisieren Befunde in ihren Reports selbst nach
        Schweregrad ("Kritisch") - das löste bisher NIE einen Korrekturauftrag aus, nur ein
        echter Testfehler tat das (siehe _run_verification_loop unten). Ein "Kritisch" im
        Code-Review ist bei einem echten Team ein Blocker, kein FYI im Abschlussbericht.

        Läuft NACH der Fachbereichs-Hierarchie (die Governance-Phase ist bereits gelaufen,
        all_results enthält also schon die individuellen Review-Ergebnisse) und VOR der echten
        Testverifikation - Kritisch-Fixes zuerst, damit die anschließende Testsuite den
        reparierten Stand prüft. core/review_gate.py liefert die (bewusst als Best-Effort
        dokumentierte) Text-Heuristik zur Fund-Erkennung/-Zuordnung, kein LLM-Aufruf dafür nötig.

        Gibt (all_results, summary, budget_aborted, manually_cancelled) zurück - summary ist
        "", wenn nichts zu tun war (kein Rauschen im Normalfall, siehe process()).
        """
        if not ENABLE_GOVERNANCE_FIX_LOOP:
            return all_results, "", False, False

        review_agent_ids = {
            r.agent_id for r in all_results
            if r.agent_id in REVIEW_ONLY_AGENT_IDS and r.success and r.content
        }
        if not review_agent_ids:
            # Keine der Review-Rollen war Teil dieses Plans (z.B. eine kleine Aufgabe ohne
            # QA/Governance) - kein Verhaltensunterschied zu vor dieser Erweiterung.
            return all_results, "", False, False

        summary_lines: list[str] = []
        budget_aborted = False
        manually_cancelled = False

        def _latest_review_results() -> list[AgentResult]:
            # Neuestes Ergebnis JE Rolle - bei einem Re-Check ab Versuch 2 überschreibt das
            # frische Ergebnis das ursprüngliche für die Fund-Extraktion.
            latest: dict[str, AgentResult] = {}
            for r in all_results:
                if r.agent_id in review_agent_ids and r.success and r.content:
                    latest[r.agent_id] = r
            return list(latest.values())

        for attempt in range(1, MAX_REVIEW_ITERATIONS + 1):
            if run_start_tokens is not None and (
                self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
            ):
                budget_aborted = True
                notify("  🚫 [bold red]Budget erreicht[/bold red] – weitere Governance-Fixversuche werden übersprungen.")
                summary_lines.append(f"- 🚫 {self._budget_exceeded_label(run_start_tokens)} erreicht – Governance-Fix-Schleife nach Versuch {attempt - 1} abgebrochen.")
                break
            if cancel_requested and cancel_requested():
                manually_cancelled = True
                notify("  ⏹️ [bold red]Lauf manuell abgebrochen[/bold red] – weitere Governance-Fixversuche werden übersprungen.")
                summary_lines.append(f"- ⏹️ Manuell abgebrochen – Governance-Fix-Schleife nach Versuch {attempt - 1} beendet.")
                break

            if attempt == 1:
                review_results = _latest_review_results()
            else:
                # Nur relevant, wenn MAX_REVIEW_ITERATIONS per .env erhöht wurde (Standard 1
                # macht diesen Zweig nie sichtbar) - ruft dieselben Review-Rollen frisch auf,
                # um zu prüfen, ob nach dem letzten Fix-Versuch noch kritische Befunde bestehen.
                notify(f"  🔍 [yellow]Versuch {attempt}/{MAX_REVIEW_ITERATIONS}:[/yellow] Governance-Rollen prüfen den aktuellen Stand erneut...")
                recheck_tasks = [
                    AgentTask(
                        task_id=f"governance_recheck_{agent_id}_{attempt}",
                        agent_id=agent_id,
                        description=(
                            f"Prüfe den AKTUELLEN Stand des Projekts erneut auf kritische Probleme "
                            f"(Versuch {attempt}) - vorherige kritische Befunde wurden inzwischen zur "
                            f"Korrektur an die zuständigen Agenten zurückgespielt."
                        ),
                        context="", project_dir=project_dir, allow_tools=True, tools_read_only=True,
                    )
                    for agent_id in sorted(review_agent_ids)
                ]
                recheck_results = await self._run_agents_parallel(recheck_tasks, notify=notify)
                all_results.extend(recheck_results)
                review_results = [r for r in recheck_results if r.success and r.content]

            findings: list[tuple[str, str]] = [
                (res.agent_id, block)
                for res in review_results
                for block in find_critical_findings(res.content)
            ]

            if not findings:
                notify("  ✅ [bold green]Keine kritischen Governance-Befunde.[/bold green]")
                summary_lines.append(
                    f"- ✅ Keine kritischen Befunde in den Governance-Reports"
                    f"{f' (Versuch {attempt})' if attempt > 1 else ''}."
                )
                break

            agents_to_fix, unrouted = route_findings_to_owners(findings, file_owners)

            if unrouted:
                shown = "; ".join(u[:150] for u in unrouted[:3])
                more = f" … und {len(unrouted) - 3} weitere" if len(unrouted) > 3 else ""
                summary_lines.append(
                    f"- ⚠️ {len(unrouted)} kritische(r) Befund(e) ohne eindeutigen Datei-Bezug "
                    f"– braucht manuelle Prüfung: {shown}{more}"
                )

            if not agents_to_fix:
                notify("  ⚠️ [yellow]Kritische Governance-Befunde konnten keinem Agenten eindeutig zugeordnet werden – Auto-Fix übersprungen.[/yellow]")
                break

            fix_tasks = []
            for agent_id, texts in agents_to_fix.items():
                finding_text = "\n\n".join(texts)[:3000]
                fix_tasks.append(AgentTask(
                    task_id=f"governance_fix_{agent_id}_{attempt}",
                    agent_id=agent_id,
                    description=(
                        f"Das Governance-Review (code_reviewer/security/compliance) hat ein "
                        f"KRITISCHES Problem in deinem Code gefunden. Nutze read_file, um die "
                        f"betroffene(n) Datei(en) zu prüfen, und edit_file/write_file, um das "
                        f"Problem zu beheben.\n\n{finding_text}"
                    ),
                    context="", project_dir=project_dir,
                ))

            notify(f"  🛠️ [bold yellow]Governance-Fix:[/bold yellow] Beauftrage {', '.join(agents_to_fix.keys())} mit {len(findings)} kritischem/kritischen Befund(en)...")
            fix_results = await self._run_agents_parallel(fix_tasks, notify=notify)
            self._update_file_owners(file_owners, fix_results)
            all_results.extend(fix_results)
            summary_lines.append(
                f"- 🛠️ Versuch {attempt}: {len(findings)} kritische(r) Governance-Befund(e) → gezielt "
                f"zur Korrektur an {', '.join(agents_to_fix.keys())} zurückgespielt (der Fix wird NICHT "
                f"erneut vom Reviewer bestätigt – das übernimmt für automatisiert testbares Verhalten "
                f"nur die anschließende echte Testverifikation, nicht die qualitative Review-Aussage selbst)."
            )

            if attempt == MAX_REVIEW_ITERATIONS:
                summary_lines.append(f"- ℹ️ Nach {MAX_REVIEW_ITERATIONS} Versuch(en) letzter Stand übernommen.")

        summary = (
            "### 🔍 Governance-Fix-Protokoll (kritische Review-Befunde)\n" + "\n".join(summary_lines)
            if summary_lines else ""
        )
        return all_results, summary, budget_aborted, manually_cancelled

    # ──────────────────────────────────────────────────────────────
    # Echte Verifikation: Dependency-Installation + tatsächliche Testausführung
    # ──────────────────────────────────────────────────────────────

    async def _run_verification_loop(
        self,
        project_dir: str,
        all_results: list[AgentResult],
        file_owners: dict[str, str],
        notify: Callable[[str], None],
        run_start_tokens: int | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> tuple[list[AgentResult], str, bool, bool, bool]:
        """
        Ersetzt die alte Keyword-basierte Fix-Schleife. Installiert Abhängigkeiten
        in einer isolierten Umgebung, führt die echte Testsuite aus und schickt bei
        Fehlschlägen einen GEZIELTEN Korrekturauftrag an genau die Agenten, deren
        Dateien laut echtem Traceback betroffen sind.

        Gibt zusätzlich zurück, ob das harte Lauf-Budget (MAX_RUN_TOKENS) während der
        Fixversuche erreicht wurde bzw. der Lauf manuell abgebrochen wurde
        (run_start_tokens/cancel_requested=None -> jeweiliger Mechanismus deaktiviert),
        sowie verification_ok: True NUR, wenn die echte Testsuite tatsächlich gelaufen UND
        bestanden ist – False bei jedem anderen Ausgang (keine Tests gefunden, Testfehler
        blieben ungelöst, Budget während der Fixversuche erreicht, manuell abgebrochen).
        Realer Fund: bisher endete JEDER Lauf mit einem uneingeschränkten "✅ Fertig!", selbst
        wenn die Verifikation nie bestätigt werden konnte – verification_ok macht diesen
        Unterschied jetzt im finalen Status sichtbar (siehe process()) statt ihn im
        Kleingedruckten des Verifikations-Protokolls zu verstecken.
        """
        verifier = ProjectVerifier(project_dir)
        summary_lines: list[str] = []
        budget_aborted = False
        manually_cancelled = False
        verification_ok = False
        # Bleibt None, wenn die Schleife unten (z.B. MAX_VERIFICATION_ITERATIONS<=0) nie
        # durchläuft - der Coverage-Check danach prüft explizit auf None, statt sich auf eine
        # garantierte Zuweisung zu verlassen.
        report: VerificationReport | None = None

        notify("🧪 [bold cyan]Verifikation:[/bold cyan] Installiere Abhängigkeiten in isolierter Umgebung...")
        install_log = await asyncio.to_thread(verifier.ensure_environment)
        if install_log:
            notify(f"  📦 {install_log.splitlines()[0]}")
            summary_lines.append(f"- 📦 {install_log.splitlines()[0]}")

        for attempt in range(1, MAX_VERIFICATION_ITERATIONS + 1):
            if run_start_tokens is not None and (
                self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
            ):
                budget_aborted = True
                notify("  🚫 [bold red]Budget erreicht[/bold red] – weitere Verifikations-/Fixversuche werden übersprungen.")
                summary_lines.append(f"- 🚫 {self._budget_exceeded_label(run_start_tokens)} erreicht – Verifikation nach Versuch {attempt - 1} abgebrochen.")
                break
            if cancel_requested and cancel_requested():
                manually_cancelled = True
                notify("  ⏹️ [bold red]Lauf manuell abgebrochen[/bold red] – weitere Verifikations-/Fixversuche werden übersprungen.")
                summary_lines.append(f"- ⏹️ Manuell abgebrochen – Verifikation nach Versuch {attempt - 1} beendet.")
                break

            notify(f"  🧪 [yellow]Testlauf {attempt}/{MAX_VERIFICATION_ITERATIONS}:[/yellow] Führe echte Tests aus...")
            report = await asyncio.to_thread(verifier.run_tests)

            if not report.ran:
                # Bewusst ⚠️ statt ℹ️: "keine Tests gefunden" bedeutet, dass generierter Code
                # UNGEPRÜFT ausgeliefert wird – real beobachtet an einem Taschenrechner-Projekt
                # ohne jeden Test, dessen "+"-Button sofort mit TypeError abstürzte (Add.execute()
                # verlangte zwei Argumente, die GUI übergab nur eines). Reine Sichtbarkeit, kein
                # automatischer Abbruch – DECOMPOSE_SYSTEM_PROMPT (core/task_manager.py) weist das
                # Modell inzwischen an, den tester-Agenten bei echter Programmlogik einzubeziehen.
                notify(f"  ⚠️ [yellow]{report.reason_skipped}[/yellow]")
                summary_lines.append(f"- ⚠️ {report.reason_skipped} Generierter Code wurde NICHT automatisch verifiziert.")
                break

            if report.passed:
                notify(f"  ✅ [bold green]Alle Tests bestanden[/bold green] (Versuch {attempt}, {report.duration_seconds:.1f}s).")
                summary_lines.append(f"- ✅ Echte Testsuite bestanden nach {attempt} Durchlauf/Durchläufen ({report.duration_seconds:.1f}s).")
                verification_ok = True
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

        # Echtes Deployment beginnt damit, dass das Projekt sich überhaupt containerisieren
        # lässt: ein generiertes Dockerfile, das nie tatsächlich baut, bringt niemanden näher
        # an ein echtes Ausrollen. Baut NIE `docker run`/einen echten Push/Deploy aus (würde
        # eine konkrete Ziel-Infrastruktur voraussetzen, die dieses Framework nicht kennt) -
        # nur die Build-Fähigkeit wird geprüft. Übersprungen bei Budget-Abbruch (kostet zwar
        # keine LLM-Tokens, aber echte Zeit) und generell kein Fehler, wenn kein Dockerfile
        # existiert oder Docker lokal nicht verfügbar ist (siehe DockerBuildReport).
        if not (budget_aborted or manually_cancelled):
            docker_report = await asyncio.to_thread(verifier.check_docker_build)
            if docker_report.attempted:
                if docker_report.success:
                    notify("  🐳 [bold green]Docker-Image baut erfolgreich.[/bold green]")
                    summary_lines.append("- 🐳 Docker-Image baut erfolgreich (echter `docker build`).")
                else:
                    notify("  🐳 [bold red]Docker-Build fehlgeschlagen.[/bold red]")
                    summary_lines.append(f"- 🐳 ❌ Docker-Build fehlgeschlagen: {docker_report.output[:500]}")

        # Ersetzt die rein LLM-basierte Einschätzung des security-Agenten zu Abhängigkeits-
        # Risiken durch einen echten Abgleich gegen eine öffentliche Advisory-Datenbank
        # (pip-audit/npm audit) – kein Raten mehr, ob eine gepinnte Paketversion bekannte
        # CVEs hat. Ein technischer Fehlschlag des Scans (Tool fehlt, kein Netzwerk zur
        # Advisory-Datenbank) ist NIE ein Fehler, nur nicht prüfbar (attempted=False) und
        # wird deshalb bewusst NICHT als "keine Schwachstellen" ausgegeben.
        if not (budget_aborted or manually_cancelled):
            audit_reports = await asyncio.to_thread(verifier.check_dependency_vulnerabilities)
            for audit in audit_reports:
                if not audit.attempted:
                    continue
                if audit.vulnerable:
                    top = "; ".join(
                        f"{v.package} {v.version} ({v.vulnerability_id})" for v in audit.vulnerabilities[:5]
                    )
                    if len(audit.vulnerabilities) > 5:
                        top += f" … und {len(audit.vulnerabilities) - 5} weitere"
                    notify(f"  🔓 [bold red]{audit.tool}: {len(audit.vulnerabilities)} bekannte Schwachstelle(n) in Abhängigkeiten.[/bold red]")
                    summary_lines.append(f"- 🔓 ❌ {audit.tool}: {len(audit.vulnerabilities)} bekannte Schwachstelle(n) in Abhängigkeiten: {top}")
                else:
                    notify(f"  🔒 [bold green]{audit.tool}: keine bekannten Schwachstellen in Abhängigkeiten.[/bold green]")
                    summary_lines.append(f"- 🔒 {audit.tool}: keine bekannten Schwachstellen in Abhängigkeiten gefunden.")

        # Erstmals überhaupt eine automatische Stil-/Fehlerprüfung für generierten Code -
        # ruff.toml lief bisher NUR gegen den Framework-Code selbst (workspace/ dort bewusst
        # ausgeschlossen). Python wird immer geprüft (ruff braucht keine Projekt-Konfiguration),
        # ESLint/tsc nur, wenn das Projekt sie selbst bereits mitbringt (keine ungefragte
        # Meinungsänderung an einem Projekt, das sich nie dafür entschieden hat). Rein
        # informativ, beeinflusst verification_ok nicht - anders als ein Testfehler hat ein
        # Lint-Fund oft keine unmittelbare Ein-Zeilen-Lösung.
        if not (budget_aborted or manually_cancelled):
            lint_reports = await asyncio.to_thread(verifier.check_lint)
            for lint in lint_reports:
                if not lint.attempted:
                    continue
                if not lint.passed:
                    top = "; ".join(
                        f"{i.file_path}:{i.line_number} [{i.rule}]" for i in lint.issues[:5]
                    )
                    if len(lint.issues) > 5:
                        top += f" … und {len(lint.issues) - 5} weitere"
                    notify(f"  🎨 [bold yellow]{lint.tool}: {len(lint.issues)} Lint-Fund(e).[/bold yellow]")
                    summary_lines.append(f"- 🎨 ⚠️ {lint.tool}: {len(lint.issues)} Lint-Fund(e): {top}")
                else:
                    notify(f"  🎨 [bold green]{lint.tool}: keine Lint-Funde.[/bold green]")
                    summary_lines.append(f"- 🎨 {lint.tool}: keine Lint-Funde.")

        # Realer Fund bei einer Bestandsaufnahme des eigenen Teams: die Verifikation misst
        # bisher nur Pass/Fail, keine Abdeckung - ein Projekt mit 3 bestandenen Tests bei 500
        # Zeilen ungetestetem Code gilt genauso als "verifiziert" wie eines mit echter
        # Abdeckung. Opt-in über MIN_TEST_COVERAGE (Standard 0 = deaktiviert, siehe config.py) -
        # nur sinnvoll, wenn die Testsuite überhaupt gelaufen UND bestanden ist (report kann
        # None sein, wenn die Schleife oben nie durchlief, z.B. MAX_VERIFICATION_ITERATIONS<=0).
        if not (budget_aborted or manually_cancelled) and MIN_TEST_COVERAGE > 0 and report is not None and report.ran and report.passed:
            coverage_report = await asyncio.to_thread(verifier.check_coverage)
            if coverage_report.attempted:
                if coverage_report.percent >= MIN_TEST_COVERAGE:
                    notify(f"  📊 [bold green]Testabdeckung: {coverage_report.percent}%[/bold green] (Schwelle: {MIN_TEST_COVERAGE}%).")
                    summary_lines.append(f"- 📊 Testabdeckung: {coverage_report.percent}% (Schwelle von {MIN_TEST_COVERAGE}% erreicht).")
                else:
                    # Anders als ein Lint-Fund (rein informativ) ist eine EXPLIZIT konfigurierte
                    # Schwelle als echte Anforderung gemeint - verification_ok wird deshalb
                    # tatsächlich zurückgesetzt, nicht nur protokolliert.
                    notify(f"  📊 [bold red]Testabdeckung {coverage_report.percent}% UNTER der Schwelle von {MIN_TEST_COVERAGE}%.[/bold red]")
                    summary_lines.append(f"- 📊 ❌ Testabdeckung {coverage_report.percent}% UNTER der konfigurierten Schwelle (`MIN_TEST_COVERAGE={MIN_TEST_COVERAGE}%`).")
                    verification_ok = False

        # Runtime Smoke-Check: Prüft, ob die generierte App tatsächlich hochfährt / antwortet (Tests grün != App startet)
        if not (budget_aborted or manually_cancelled) and report is not None and report.ran and report.passed:
            smoke_report = await asyncio.to_thread(verifier.check_runtime_smoke)
            if smoke_report.attempted:
                if smoke_report.passed:
                    code_info = f" (HTTP {smoke_report.status_code})" if smoke_report.status_code else ""
                    notify(f"  🚀 [bold green]Runtime-Smoke-Test erfolgreich:[/bold green] `{smoke_report.entrypoint}` [{smoke_report.app_type}]{code_info}.")
                    summary_lines.append(f"- 🚀 Runtime-Smoke-Test: `{smoke_report.entrypoint}` [{smoke_report.app_type}] startet fehlerfrei{code_info}.")
                else:
                    # Bugfix (Code-Review-Fund): dieser Zweig baute bisher nur eine `err`-Variable,
                    # rief aber weder notify() noch summary_lines.append() auf und setzte
                    # verification_ok nicht zurück - ein fehlgeschlagener Smoke-Test (App startet
                    # nicht) blieb dadurch komplett unsichtbar UND unblockiert, obwohl genau das
                    # der Sinn dieses Checks ist ("Tests grün != App startet", siehe Kommentar
                    # oben). Analog zur Testabdeckungs-Schwelle: eine tatsächlich geprüfte, aber
                    # nicht startende App ist eine echte Anforderungsverletzung, kein reiner
                    # Stil-Hinweis wie ein Lint-Fund.
                    err = f": {smoke_report.output[:150]}" if smoke_report.output else ""
                    notify(f"  🚀 [bold red]Runtime-Smoke-Test fehlgeschlagen:[/bold red] `{smoke_report.entrypoint}` [{smoke_report.app_type}]{err}.")
                    summary_lines.append(f"- 🚀 ❌ Runtime-Smoke-Test fehlgeschlagen: `{smoke_report.entrypoint}` [{smoke_report.app_type}] startet nicht{err}.")
                    verification_ok = False
        # Browser / Frontend UI-Check: Prüft statische Assets, Rendering und JS-Konsolenfehler
        if not (budget_aborted or manually_cancelled):
            browser_report = await asyncio.to_thread(verifier.check_browser_ui)
            if browser_report.attempted:
                if browser_report.passed:
                    engine_info = f" [{browser_report.engine}]"
                    notify(f"  🌐 [bold green]Frontend/UI-Check erfolgreich:[/bold green] `{browser_report.tested_url}`{engine_info}.")
                    summary_lines.append(f"- 🌐 Frontend/UI-Check: `{browser_report.tested_url}`{engine_info} fehlerfrei.")
                else:
                    err_details = "; ".join(browser_report.missing_assets + browser_report.console_errors)[:150]
                    notify(f"  🌐 [bold red]Frontend/UI-Check Warnung:[/bold red] {err_details}.")
                    summary_lines.append(f"- 🌐 ⚠️ Frontend/UI-Check: {err_details}.")

        verification_summary = "### 🧪 Verifikations-Protokoll (echte Dependency-Installation & Testausführung)\n" + (
            "\n".join(summary_lines) if summary_lines else "- Keine Verifikation durchgeführt."
        )
        return all_results, verification_summary, budget_aborted, manually_cancelled, verification_ok

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
                notify(self._status_notify_line("✅ [green]Abgeschlossen[/green]", "❌ [red]Fehler[/red]", res.agent_name, res.duration_seconds, res.success, res.error))
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
            self._extract_and_store_learnings(trainer_result.content)

        return trainer_result

    def _extract_and_store_learnings(self, report_text: str) -> None:
        """
        Speichert die Lern-Regeln aus dem Trainer-Report persistent (memory/agent_learnings.json),
        damit ALLE Agenten aus vergangenen Fehlern/Läufen lernen (BaseAgent.execute() reichert
        jeden System-Prompt automatisch mit den gespeicherten Regeln des jeweiligen Agenten an).

        Primär über den maschinenlesbaren ```json-Block (robust, siehe AgentTrainerAgent),
        mit Fallback auf die alte text-musterbasierte Extraktion, falls das Modell den
        JSON-Block einmal nicht liefert. Jede agent_id wird gegen die echten Agenten/Leads
        validiert, damit keine erfundene oder falsch geschriebene Rolle in der Wissensbasis landet.
        """
        from memory.agent_knowledge_base import agent_knowledge_base

        valid_agent_ids = set(self._agents.keys()) | set(self._dept_leads.keys())
        learnings = self._parse_structured_learnings(report_text) or self._parse_legacy_text_learnings(report_text)

        for entry in learnings:
            agent_id = entry.get("agent_id", "")
            rule = (entry.get("rule") or "").strip()
            if agent_id in valid_agent_ids and len(rule) > 15:
                agent_knowledge_base.add_learning(agent_id, rule)

    @staticmethod
    def _parse_structured_learnings(report_text: str) -> list[dict]:
        """
        Sucht NICHT nur den ersten ```json-Block, sondern den ersten, der wirklich einen
        "learnings"-Schlüssel enthält. Realer Fund aus einem echten Lauf: Der Trainer-Bericht
        enthält in seinen Prompt-Diff-Beispielen (Abschnitt "Konkrete Prompt-Verbesserungen")
        selbst oft ein illustratives ```json-Snippet VOR dem eigentlichen Lern-Block am Ende –
        ein reines "ersten Treffer nehmen" ignoriert dann den echten Block komplett und lässt
        alle Lern-Regeln des Laufs stillschweigend verloren gehen (kein Fehler, kein Log).
        """
        for match in re.finditer(r"```json\s*\n(.*?)```", report_text, re.DOTALL):
            try:
                data = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            learnings = data.get("learnings") if isinstance(data, dict) else None
            if isinstance(learnings, list):
                return learnings
        return []

    @staticmethod
    def _parse_legacy_text_learnings(report_text: str) -> list[dict]:
        """Fallback, falls der Trainer (entgegen der Anweisung) keinen gültigen JSON-Block liefert."""
        learnings: list[dict] = []
        current_agent: str | None = None
        for line in report_text.splitlines():
            if "Betroffener Agent:" in line:
                # \**: toleriert Markdown-Fettschrift ("**Betroffener Agent:**"), die reale
                # Modell-Ausgaben durchgehend verwenden – ohne das schlug dieses Muster in
                # der Praxis nie an (bei einem echten Testlauf entdeckt).
                match = re.search(r'Betroffener Agent:\**\s*[`\'"]?([a-zA-Z0-9_]+)', line)
                if match:
                    current_agent = match.group(1).replace("_agent", "")
            elif current_agent and ("Vorgeschlagene Ergänzung" in line or line.strip().startswith('"') or line.strip().startswith("- ")):
                clean_rule = line.strip(' "-*#')
                if len(clean_rule) > 15:
                    learnings.append({"agent_id": current_agent, "rule": clean_rule})
        return learnings

    # Caps analog zu ResultAggregator.MAX_CONTENT_CHARS_PER_RESULT - verhindert, dass ein
    # Projekt mit vielen/großen Dateien die finale Antwort unbegrenzt aufbläht. Vollständiger
    # Inhalt liegt immer im Workspace-Verzeichnis, unabhängig von dieser Kürzung.
    MAX_CHARS_PER_REAL_FILE = 3000
    MAX_TOTAL_REAL_FILES_CHARS = 20000
    _LANG_BY_EXTENSION = {
        ".py": "python", ".js": "javascript", ".jsx": "jsx", ".ts": "typescript",
        ".tsx": "tsx", ".json": "json", ".md": "markdown", ".html": "html",
        ".css": "css", ".yml": "yaml", ".yaml": "yaml", ".toml": "toml",
        ".sh": "bash", ".sql": "sql", ".txt": "",
    }

    def _build_real_files_section(self, project_dir: str, file_owners: dict[str, str]) -> str:
        """
        Liest die TATSÄCHLICH geschriebenen Dateien direkt von der Platte (kein LLM-Aufruf,
        daher immer exakt korrekt) – Gegenstück zur LLM-Synthese oben, die Code nur
        beschreiben, nicht mehr reproduzieren soll (siehe SYNTHESIZE_SYSTEM_PROMPT). Leer,
        wenn keine Dateien geschrieben wurden (z.B. ein reiner Planungs-/Analyse-Lauf).
        """
        if not file_owners:
            return ""

        blocks = ["### 📁 Tatsächlich geschriebene Dateien (direkt von der Platte gelesen, nicht vom LLM reproduziert)"]
        total_chars = 0
        for rel_path in sorted(file_owners):
            if total_chars >= self.MAX_TOTAL_REAL_FILES_CHARS:
                blocks.append(f"\n… weitere Dateien gekürzt (Gesamtlänge begrenzt) – vollständig im Workspace unter `{project_dir}`.")
                break
            try:
                content = (Path(project_dir) / rel_path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue  # z.B. Binärdatei oder zwischenzeitlich gelöscht - kein Fehler, einfach übersprungen
            truncated = content[: self.MAX_CHARS_PER_REAL_FILE]
            note = "" if len(content) <= self.MAX_CHARS_PER_REAL_FILE else "\n… [gekürzt, vollständiger Inhalt im Workspace] …"
            lang = self._LANG_BY_EXTENSION.get(Path(rel_path).suffix, "")
            blocks.append(f"\n**`{rel_path}`**\n```{lang}\n{truncated}{note}\n```")
            total_chars += len(truncated)

        return "\n".join(blocks)

    def _build_metrics_summary(
        self,
        results: list[AgentResult],
        synth_tokens: int,
        total_duration: float,
        project_dir: str,
        run_start_tokens: int | None = None,
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
        ]

        # Nur anzeigen, wenn ein hartes Lauf-Budget konfiguriert ist (config.MAX_RUN_TOKENS) –
        # nutzt den GLOBALEN Token-Guard-Zähler (inkl. aller Fallback-Hops), nicht nur die Summe
        # der einzelnen AgentResult.total_tokens, da diese Fehlschläge vor Ergebnis nicht erfasst.
        if MAX_RUN_TOKENS > 0 and run_start_tokens is not None:
            used = self._tokens_used_since(run_start_tokens)
            pct = min(100, round(used / MAX_RUN_TOKENS * 100))
            budget_icon = "🚨" if used >= MAX_RUN_TOKENS else "🪙"
            lines.append(f"- {budget_icon} **Lauf-Budget:** `{used:,} / {MAX_RUN_TOKENS:,}` Tokens (`{pct}%`)")
        if self._project_token_budget > 0 and run_start_tokens is not None:
            # Kumuliert über ALLE bisherigen Läufe an diesem Projekt (nicht nur diesen einen
            # Lauf, siehe _project_budget_exceeded) - eigene Zeile statt in die Lauf-Budget-
            # Zeile oben gemischt, da beide Budgets unabhängig konfiguriert/erschöpft sein können.
            project_used = self._project_tokens_before_run + self._tokens_used_since(run_start_tokens)
            project_pct = min(100, round(project_used / self._project_token_budget * 100))
            project_icon = "🚨" if project_used >= self._project_token_budget else "🪙"
            lines.append(
                f"- {project_icon} **Projekt-Budget** (`/constitution`, über alle Läufe): "
                f"`{project_used:,} / {self._project_token_budget:,}` Tokens (`{project_pct}%`)"
            )

        lines += [
            f"- 🛠️ **Werkzeug-Aufrufe (echte Datei-/Testoperationen):** `{total_tool_calls:,}` | **Dateien geschrieben/geändert:** `{total_files_written}`",
            f"- 📁 **Projektverzeichnis:** `{project_dir}`\n",
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

        # Rohe Fehlertexte GARANTIERT sichtbar machen – nicht nur (verkürzt/paraphrasiert) über
        # die Retrospektive, die als eigener LLM-Aufruf den Fehler frei zusammenfasst und dabei
        # auch ungenau werden kann. Realer Fund: Ohne dies verschwand die einzige Fehlerursache
        # eines gescheiterten Laufs komplett aus dem Nutzer-sichtbaren Ergebnis.
        failed = [r for r in results if not r.success and r.error]
        if failed:
            lines.append("\n### ❌ Rohe Fehlermeldungen (ungefiltert, nicht vom LLM zusammengefasst)\n")
            for r in failed:
                lines.append(f"- **{r.agent_name}** (`{r.agent_id}`): `{r.error[:500]}`")

        # "Erfolgreich", aber real NICHTS im Projekt verändert: eine Rolle mit eindeutigem
        # Artefakt-Auftrag (CODE_WRITING_AGENT_IDS) hat Werkzeuge genutzt (tool_calls_count > 0,
        # war also im agentischen Loop) und trotzdem 0 Dateien geschrieben – der komplette
        # Tokenverbrauch dieses Agenten ging vermutlich in reinen Antworttext statt in echte
        # write_file/edit_file-Aufrufe. Siehe CODE_WRITING_AGENT_IDS oben für den realen Fund.
        silent_no_write = [
            r for r in results
            if r.success and r.agent_id in CODE_WRITING_AGENT_IDS and r.tool_calls_count > 0 and not r.files_written
        ]
        if silent_no_write:
            lines.append(
                "\n### ⚠️ Erfolg gemeldet, aber keine Datei geschrieben (vermutlich verpuffter Tokenverbrauch)\n"
            )
            for r in silent_no_write:
                lines.append(
                    f"- **{r.agent_name}** (`{r.agent_id}`): {r.tool_calls_count} Werkzeug-Aufruf(e), "
                    f"{r.total_tokens:,} Tokens, aber 0 Dateien geschrieben. Prüfe `content` dieses "
                    "Agenten manuell – der Code steckt wahrscheinlich nur im Antworttext."
                )

        return "\n".join(lines)

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
