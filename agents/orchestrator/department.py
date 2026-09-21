"""
agents/orchestrator/department.py – DepartmentMixin: Fachbereichs-Hierarchie mit ECHTER
Teamleiter-Delegation & -Konsolidierung (siehe agents/department_lead_agent.py). Führt alle
6 Fachbereichs-Phasen (PHASE_ORDER) aus, lässt den zuständigen Teamleiter per echtem
LLM-Aufruf delegieren, sein Fachteam parallel/sequenziell arbeiten und die Ergebnisse
anschließend per weiterem LLM-Aufruf konsolidieren.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path

from agents.department_lead_agent import DEPARTMENT_DEFINITIONS, DepartmentLeadAgent
from agents.orchestrator.constants import PHASE_ORDER
from config import (
    CRITICAL_AGENT_IDS,
    DEPARTMENT_LEAD_MIN_MEMBERS,
    ENABLE_DEPARTMENT_LEAD_EXECUTION,
    ENABLE_INTEGRATION_CHECKPOINT,
    ENABLE_LLM_DEPARTMENT_CONSOLIDATION,
    ENABLE_PROJECT_SCAFFOLD,
    ENABLE_TASK_COMPLEXITY_SCALING,
    ENABLE_TEAM_BOARD,
    ENABLE_TEST_FIRST,
    PROVIDER_EXHAUSTION_CONSECUTIVE_LIMIT,
)
from core.checkpoint import clear_checkpoint, load_checkpoint, save_phase_checkpoint
from core.definition_of_done import check_entrypoint_exists
from core.interface_contract import ensure_interface_contract
from core.message_bus import AgentResult, AgentTask
from core.model_capability import complex_run
from core.project_scaffold import is_safe_project_dir
from core.provider_exhaustion import FAILURE_CLASS_PROVIDER_EXHAUSTED
from core.task_manager import is_complex_task, is_micro_task
from core.token_guard import token_guard
from core.verifier import ProjectVerifier

# Nach welcher Phase der statische Einstiegspunkt-Pre-Flight läuft: "dev_lead" liegt direkt
# nach der Entwicklung, aber VOR den teuren Content-/QA-/Governance-Phasen.
_ENTRYPOINT_PREFLIGHT_PHASE_ID = "dev_lead"

# Nach welcher Phase der Sicherheits-Übergabe-Checkpoint läuft: "qa_lead" (Fachbereich 5/6)
# ist die einzige Phase, in der ein security-Agent tätig wird - siehe
# IntegrationMixin._run_security_requirements_checkpoint() für den realen Fund, den dieser
# späte Zeitpunkt behebt (der Integrations-Checkpoint oben lief bisher nur nach `dev_lead`,
# lange BEVOR security überhaupt etwas prüfen konnte).
_SECURITY_HANDOFF_CHECKPOINT_PHASE_ID = "qa_lead"

_TEST_FIRST_NOTE = '## 🧪 Test-First (du arbeitest PARALLEL zu den Entwicklern)\nSchreibe die Testsuite jetzt aus den Akzeptanzkriterien und `interface_contract.json` - nicht erst, wenn der Code fertig ist. Teste das vereinbarte Verhalten (Endpunkte, Klassen, Funktionen laut Vertrag), nicht Implementierungsdetails. Existiert Code bereits, führe `run_tests` aus. Scheitert ein Test, weil der Code vom Vertrag abweicht, ist das ein gültiger Befund für die Entwickler - passe den Test NICHT an falsches Verhalten an.'

# Realer Fund (synapsegate, ROADMAP_TEMP.md P4-4, 2026-09-20): Im Test-First-Modus schreibt
# `tester` seine Tests GEGEN `interface_contract.json`/die Akzeptanzkriterien, PARALLEL zu
# `backend` - der reale Code existiert zum Startzeitpunkt oft noch gar nicht. War
# `interface_contract.json` unvollständig oder fehlte (hier: reines Backend-Projekt ohne
# Frontend), erfand `tester` zwei nie deklarierte Routen (`POST /api/v1/events/`,
# `GET /api/v1/events/dlq`). `core/contract_verifier.py` prüft NUR Frontend<->Backend, ein
# Äquivalent für Tester<->Backend gab es nicht - der Mismatch wurde bisher erst spät vom
# AST-Completeness-Check am Laufende gefunden, NACHDEM bereits performance/readme/qa_lead/
# security/resilience_guard-Phasen auf dem fehlerhaften Stand weitergearbeitet hatten.
# `_test_requests_undeclared_routes()`/`_unwired_api_routers()` (core/verifier/completeness.py)
# sind rein statisch (kein LLM-Aufruf, keine Testausführung) - deshalb hier, direkt nach der
# Entwicklungsphase und VOR den teuren Folgephasen, wie schon beim Einstiegspunkt-Pre-Flight.
_TEST_ROUTE_MISMATCH_KINDS = frozenset({"test_route_mismatch", "unwired_api_router"})

# P2-3 (ROADMAP_TEMP.md): der database-Agent lief in 20 ausgewerteten Läufen nur 3×, obwohl
# SQLAlchemy-Fehler (konkurrierende Base-Definitionen, TypeError in Modell-Tests) zu den
# häufigsten echten Testfehlern gehören - der Planer entscheidet sich beim Zerlegen fast nie
# für die Rolle, obwohl das Backend tatsächlich ein ORM einsetzt. Option 2 ("Planer-Beschreibung
# schärfen") half bei anderen Rollen bereits, träfe hier aber das eigentliche Problem nicht: zum
# Planungszeitpunkt für ein NEUES Projekt steht der Tech-Stack oft noch gar nicht fest. Deshalb
# stattdessen (Option 1, aber erst NACH der Entwicklungsphase statt zur Planungszeit, wo der
# tatsächlich verwendete Stack schon feststeht) - siehe _run_database_review_preflight().
_ORM_MARKERS = ("sqlalchemy", "declarative_base(", "DeclarativeBase")


class DepartmentMixin:
    """Führt die Fachbereichs-Phasen mit echter Teamleiter-Delegation/-Konsolidierung aus."""

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
        enable_phase_checkpoint: bool = False,
    ) -> tuple[list[AgentResult], dict[str, str], bool, bool]:
        """Dünner Wrapper um _run_department_hierarchy_impl(): markiert den Lauf für seine
        gesamte Dauer (inkl. aller daraus gestarteten asyncio-Tasks) als anspruchsvoll oder
        nicht, siehe core/model_capability.complex_run() und config.get_model_for_agent(). Als
        eigene Methode, damit die Markierung per try/finally auch bei einer Exception irgendwo
        in der Hierarchie zuverlässig zurückgesetzt wird, ohne den kompletten (sehr langen)
        Hierarchie-Code dafür einrücken zu müssen."""
        task_is_complex = ENABLE_TASK_COMPLEXITY_SCALING and is_complex_task(agent_tasks)
        if task_is_complex:
            notify(
                "🧠 [dim]Anspruchsvolle Aufgabe erkannt – Selbstoptimierer darf Rollen für "
                "diesen Lauf nicht auf ein schwächeres Modell abstufen.[/dim]"
            )
        with complex_run(task_is_complex):
            return await self._run_department_hierarchy_impl(
                user_request=user_request,
                task_summary=task_summary,
                agent_tasks=agent_tasks,
                project_dir=project_dir,
                notify=notify,
                run_start_tokens=run_start_tokens,
                cancel_requested=cancel_requested,
                collision_sink=collision_sink,
                enable_phase_checkpoint=enable_phase_checkpoint,
            )

    async def _run_department_hierarchy_impl(
        self,
        user_request: str,
        task_summary: str,
        agent_tasks: list[AgentTask],
        project_dir: str,
        notify: Callable[[str], None],
        run_start_tokens: int | None = None,
        cancel_requested: Callable[[], bool] | None = None,
        collision_sink: list[dict] | None = None,
        enable_phase_checkpoint: bool = False,
    ) -> tuple[list[AgentResult], dict[str, str], bool, bool]:
        """
        Führt alle Fachbereichs-Phasen aus. Jede Phase lässt (sofern
        ENABLE_DEPARTMENT_LEAD_EXECUTION aktiv ist) den zuständigen Teamleiter per echtem
        LLM-Aufruf delegieren und konsolidieren.

        Gibt zusätzlich zurück, ob (1) das harte Lauf-Budget erreicht wurde
        (run_start_tokens=None -> keine Budget-Prüfung) und (2) ob der Lauf manuell
        abgebrochen wurde (cancel_requested=None -> kein Abbruch-Mechanismus). In beiden
        Fällen werden verbleibende Fachbereiche übersprungen, die bisherigen Ergebnisse aber
        ausgeliefert.

        collision_sink: Sammelt Datei-Kollisionen parallel laufender Mitglieder für den
        Abschlussbericht. None (Standard) = nur die Live-Warnung.

        enable_phase_checkpoint: Gibt .ai_team_checkpoint.json (core/checkpoint.py) frei.
        Standard False, nur der Produktionspfad process() setzt True - Tests rufen diese
        Methode mehrfach mit project_dir="." und unabhängigen Aufgaben auf, wo ein Checkpoint
        Phasen des jeweils nächsten Aufrufs fälschlich als erledigt überspringen würde.
        """
        all_results: list[AgentResult] = []
        file_owners: dict[str, str] = {}
        task_map = {t.agent_id: t for t in agent_tasks}
        running_context = ""  # Kompakter Kontext aus vorherigen Phasen (z.B. Planungsergebnisse)
        budget_aborted = False
        manually_cancelled = False

        # ── Checkpoint-Resume (core/checkpoint.py) ──────────────────────────────────────────
        # Wurde ein früherer Lauf für dasselbe project_dir abgebrochen (z.B. Circuit Breaker
        # unten), werden bereits abgeschlossene Phasen übersprungen und ihr running_context
        # übernommen - die Dateien liegen ohnehin schon da, nur die Delegations-/
        # Konsolidierungsarbeit würde doppelt anfallen.
        checkpoint = load_checkpoint(project_dir) if enable_phase_checkpoint else None
        completed_phase_ids: set[str] = set(checkpoint["completed_phases"]) if checkpoint else set()
        if checkpoint:
            running_context = str(checkpoint.get("running_context") or "")
            if completed_phase_ids:
                notify(
                    f"📌 [dim]Checkpoint gefunden: {len(completed_phase_ids)} Fachbereichs-Phase(n) "
                    f"aus einem vorherigen Lauf bereits abgeschlossen, werden übersprungen.[/dim]"
                )
        # Erspart trivialen Aufgaben die volle Teamleiter-Delegation+Konsolidierung je
        # Fachbereich. Einmalig aus dem bestehenden Plan berechnet, kein LLM-Aufruf.
        task_is_micro = ENABLE_TASK_COMPLEXITY_SCALING and is_micro_task(agent_tasks)

        # Test-First: der tester arbeitet in der Entwicklungsphase parallel zu den Entwicklern
        # (gegen Akzeptanzkriterien + interface_contract.json) statt erst in der QA-Phase auf
        # bereits fertigem Code.
        dev_member_ids = set(DEPARTMENT_DEFINITIONS["dev_lead"]["members"])
        test_first_active = (
            ENABLE_TEST_FIRST and "tester" in task_map and any(a in task_map for a in dev_member_ids)
        )
        scaffold_applied = False
        self.last_integration_checkpoint_lines = []
        # Schneller Circuit Breaker (PROVIDER_EXHAUSTION_CONSECUTIVE_LIMIT): zählt
        # provider_exhausted-Fehlschläge IN FOLGE über die gesamte Hierarchie hinweg, nicht nur
        # innerhalb einer einzelnen Phase/Welle.
        consecutive_provider_exhausted = 0

        def _register_result_for_breaker(res: AgentResult, *, is_lead: bool = False) -> bool:
            """Aktualisiert den Zähler und meldet True, sobald der Lauf SOFORT abgebrochen
            werden muss: entweder N Fehlschläge in Folge, oder bereits EIN Fehlschlag einer
            kritischen Rolle (CRITICAL_AGENT_IDS) - ohne sie entsteht ohnehin kein tragfähiges
            Fundament, ein Warten auf einen zweiten Fehlschlag verschwenkt nur weitere Tokens.

            is_lead=True (Delegation/Konsolidierung eines Department-Leads): zählt zum
            Multi-Fehlschlag-Muster mit, darf aber nie allein den Sofortabbruch auslösen. Der
            Ausfall eines rein koordinierenden Aufrufs ist kein Show-Stopper für die
            Fachteam-Arbeit - stattdessen greift skip_lead_layer weiter unten."""
            nonlocal consecutive_provider_exhausted
            if res.failure_class != FAILURE_CLASS_PROVIDER_EXHAUSTED:
                consecutive_provider_exhausted = 0
                return False
            consecutive_provider_exhausted += 1
            if is_lead:
                return consecutive_provider_exhausted >= PROVIDER_EXHAUSTION_CONSECUTIVE_LIMIT
            if res.agent_id in CRITICAL_AGENT_IDS:
                return True
            return consecutive_provider_exhausted >= PROVIDER_EXHAUSTION_CONSECUTIVE_LIMIT

        provider_exhausted_abort = False

        for dept_id, phase_label, icon, run_mode in PHASE_ORDER:
            # _generation_budget_exceeded statt _run_budget_exceeded: reserviert einen Anteil
            # von MAX_RUN_TOKENS exklusiv für die spätere Verifikations-/Fix-Phase
            # (agents/orchestrator/budget.py).
            if run_start_tokens is not None and (
                self._generation_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
            ):
                # Nur ein echter Hard-Abort (volles Lauf- ODER Projekt-Budget erschöpft) setzt
                # budget_aborted=True. Ist lediglich die Generierungsreserve aufgebraucht, endet
                # die Generierung hier, die Verifikation läuft aber mit dem Rest-Budget weiter.
                if self._generation_reserve_is_hard_abort(run_start_tokens):
                    budget_aborted = True
                    notify(
                        f"🚫 [bold red]{self._budget_exceeded_label(run_start_tokens)} erreicht:[/bold red] "
                        f"{self._tokens_used_since(run_start_tokens):,} Tokens in diesem Lauf verbraucht – "
                        f"überspringe verbleibende Fachbereiche ab '{phase_label}' und liefere die bisherigen "
                        "Ergebnisse aus."
                    )
                else:
                    self._generation_budget_reached_this_run = True
                    notify(
                        f"⏸️ [bold yellow]Generierungsreserve erreicht:[/bold yellow] "
                        f"{self._tokens_used_since(run_start_tokens):,} Tokens in diesem Lauf verbraucht – "
                        f"überspringe verbleibende Fachbereiche ab '{phase_label}', die Code-Generierung endet "
                        "hier. Die anschließende Verifikation läuft regulär mit dem verbleibenden Rest-Budget "
                        "weiter (kein Lauf-Abbruch)."
                    )
                break
            if cancel_requested and cancel_requested():
                manually_cancelled = True
                notify(
                    f"⏹️ [bold red]Lauf manuell abgebrochen[/bold red] – überspringe verbleibende "
                    f"Fachbereiche ab '{phase_label}' und liefere die bisherigen Ergebnisse aus."
                )
                break

            if dept_id in completed_phase_ids:
                notify(f"  ⏭️ [dim]{phase_label} bereits per Checkpoint abgeschlossen – übersprungen.[/dim]")
                continue

            member_ids = list(DEPARTMENT_DEFINITIONS[dept_id]["members"])
            if test_first_active and dept_id == "dev_lead":
                member_ids.append("tester")
            elif test_first_active and dept_id == "qa_lead":
                member_ids = [m for m in member_ids if m != "tester"]
            member_tasks = [task_map[aid] for aid in member_ids if aid in task_map]
            if not member_tasks:
                continue

            remaining_after_this = [d for d, _, _, _ in PHASE_ORDER if d not in completed_phase_ids and d != dept_id]
            if run_start_tokens is not None and not self._phase_budget_allows(dept_id, run_start_tokens, remaining_after_this):
                notify(
                    f"  ⏭️ [yellow]{phase_label} übersprungen:[/yellow] das verbleibende Generierungsbudget wird "
                    "für Entwicklung, QA und Review gebraucht (PHASE_TOKEN_SHARES)."
                )
                self._trace_event("phase_skipped", phase_id=dept_id, reason="phase_budget")
                continue

            # Deterministisches Gerüst unmittelbar vor der Entwicklung (core/project_scaffold.py).
            if dept_id == "dev_lead" and ENABLE_PROJECT_SCAFFOLD and enable_phase_checkpoint and not scaffold_applied and project_dir:
                scaffold_applied = True
                scaffold_context = self._apply_project_scaffold(project_dir, user_request, notify).format_for_agents()
                if scaffold_context:
                    for task in member_tasks:
                        task.context += f"\n\n{scaffold_context}"
            if test_first_active and dept_id == "dev_lead":
                for task in member_tasks:
                    if task.agent_id == "tester" and _TEST_FIRST_NOTE not in task.context:
                        task.context += f"\n\n{_TEST_FIRST_NOTE}"

            # P4-4: Projekt-Steckbrief für nachfolgende Phasen injizieren (deterministisch aus CodebaseGraph)
            if dept_id != "dev_lead" and project_dir:
                try:
                    from core.code_graph import generate_project_brief
                    brief = generate_project_brief(project_dir, max_chars=600)
                    if brief:
                        for task in member_tasks:
                            if brief not in task.context:
                                task.context += f"\n\n{brief}"
                except Exception:
                    pass

            phase_start_tokens = token_guard.get_summary()["grand_total_tokens"]
            phase_start_time = time.monotonic()
            self._trace_event("phase_started", phase_id=dept_id, agents=[t.agent_id for t in member_tasks])

            lead = self._dept_leads[dept_id]
            notify(f"{icon} [bold cyan]{phase_label}[/bold cyan] (Geleitet von: {lead.name})...")

            if running_context:
                for task in member_tasks:
                    task.context += f"\n\n## Kontext aus vorherigen Fachbereichen:\n{running_context[:2500]}"

            # Nur EIN Mitglied trägt hier die gesamte Fachbereichsarbeit - bei einer insgesamt
            # kleinen Aufgabe fehlt der Abstimmungsbedarf, den Delegation+Konsolidierung
            # eigentlich rechtfertigt (siehe task_is_micro oben). Fachbereiche mit mehreren
            # Mitgliedern behalten die Teamleiter-Koordination IMMER.
            # Der Test-First-tester arbeitet gegen den Vertrag und erzeugt keinen zusätzlichen
            # Koordinationsbedarf - er zählt für die Lead-Entscheidung nicht mit.
            coordinated_count = sum(
                1 for t in member_tasks if not (test_first_active and dept_id == "dev_lead" and t.agent_id == "tester")
            )
            skip_lead_layer = (task_is_micro and coordinated_count == 1) or coordinated_count < DEPARTMENT_LEAD_MIN_MEMBERS

            # ── Echte Delegation durch den Teamleiter ──
            if ENABLE_DEPARTMENT_LEAD_EXECUTION and not skip_lead_layer:
                delegation = await self._run_department_delegation(lead, task_summary, member_tasks, project_dir)
                all_results.append(delegation)
                # is_lead=True: siehe _register_result_for_breaker - dieser rein koordinierende
                # Aufruf löst nie allein den Sofortabbruch aus.
                if _register_result_for_breaker(delegation, is_lead=True):
                    provider_exhausted_abort = True
                    break
                if delegation.success and delegation.content:
                    notify(f"  📤 [cyan]{lead.name} delegiert:[/cyan] {self._first_line(delegation.content)}")
                    for task in member_tasks:
                        task.context += f"\n\n## Arbeitsauftrag von {lead.name}:\n{delegation.content[:1200]}"
                else:
                    # Graceful Degradation statt Abbruch: das Fachteam bekommt die Hauptaufgabe
                    # direkt (task_summary/ADRs stecken bereits im running_context), statt auf
                    # eine Anweisung zu warten, die nicht kommt. skip_lead_layer=True überspringt
                    # auch die Konsolidierung - dieselbe Fehlerursache träte dort erneut auf.
                    skip_lead_layer = True
                    notify(
                        f"  ⚠️ [yellow]{lead.name} konnte nicht delegieren ({delegation.error}) – "
                        "Fachteam startet direkt mit der Hauptaufgabe, Lead-Ebene für diese Phase "
                        "übersprungen.[/yellow]"
                    )
            elif skip_lead_layer:
                notify(f"  ℹ️ [dim]{len(member_tasks)} Mitglied(er) – Delegation/Konsolidierung durch {lead.name} übersprungen (kein Abstimmungsbedarf).[/dim]")

            # ── Fachteam arbeitet (parallel oder sequentiell, je nach Phase) ──
            # Bei 1-2 Mitgliedern sehen sich parallel gestartete Agenten nie gegenseitig (der
            # Dateibaum ist beim eigenen Start noch leer) und implementieren dieselbe Sache
            # doppelt. Der Latenzgewinn wäre hier gering, der Sichtbarkeitsgewinn durch
            # Sequenzialität groß - deshalb unabhängig von der Phasen-Präferenz nie parallel.
            effective_run_mode = "sequential" if len(member_tasks) <= 2 else run_mode
            if effective_run_mode == "parallel":
                for task in member_tasks:
                    notify(f"  ▶️ [yellow]Fachteam arbeitet:[/yellow] {self._agents[task.agent_id].name}...")

                def _budget_stop_reason() -> str | None:
                    """Vor JEDEM Start dieser Welle geprüft - siehe _run_agents_parallel().
                    Bei MAX_CONCURRENT_AGENTS=2 arbeitet eine größere Phase mehrere Blöcke
                    nacheinander ab; ohne diese Prüfung liefe der letzte Block auch dann noch,
                    wenn das Budget im ersten längst gerissen wurde."""
                    if run_start_tokens is None:
                        return None
                    if self._generation_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens):
                        if self._generation_reserve_is_hard_abort(run_start_tokens):
                            return self._budget_exceeded_label(run_start_tokens) + " erreicht"
                        return "Generierungsreserve erreicht"
                    return None

                member_results = await self._run_agents_parallel(
                    member_tasks, notify=notify, should_stop=_budget_stop_reason,
                )
                # Die Welle kann Aufrufe übersprungen haben - dann gilt dieselbe
                # Hard-Abort-/Reserve-Unterscheidung wie im sequenziellen Zweig unten, damit der
                # Lauf nicht mit der nächsten Phase weitermacht, als wäre nichts gewesen.
                if len(member_results) < len(member_tasks):
                    if run_start_tokens is not None and self._generation_reserve_is_hard_abort(run_start_tokens):
                        budget_aborted = True
                    else:
                        self._generation_budget_reached_this_run = True
                # Folge desselben Problems: parallele Agenten können dieselbe Datei schreiben
                # (z.B. requirements.txt), wobei der letzte Schreiber still gewinnt. Welche
                # Version richtig ist, lässt sich nicht automatisch entscheiden - der Fund wird
                # daher nur sichtbar gemacht (Live-Warnung + collision_sink), nicht geblockt.
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
                for res in member_results:
                    if _register_result_for_breaker(res):
                        provider_exhausted_abort = True
                        break
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

                    if _register_result_for_breaker(res):
                        provider_exhausted_abort = True
                        break

                    # Budget-Prüfung auch NACH jedem sequenziellen Mitglied: die Prüfung am
                    # Phasenkopf allein bemerkt eine Überschreitung erst nach der kompletten
                    # Phase. Im parallelen Zweig oben entfällt das, da ein Zwischenstopp mitten
                    # in asyncio.gather nicht sinnvoll möglich ist.
                    if run_start_tokens is not None and (
                        self._generation_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
                    ):
                        # Dieselbe Hard-Abort-/Reserve-Unterscheidung wie am Phasenkopf oben.
                        if self._generation_reserve_is_hard_abort(run_start_tokens):
                            budget_aborted = True
                            notify(
                                f"🚫 [bold red]{self._budget_exceeded_label(run_start_tokens)} erreicht:[/bold red] "
                                f"{self._tokens_used_since(run_start_tokens):,} Tokens in diesem Lauf verbraucht – "
                                f"überspringe verbleibende Mitglieder in '{phase_label}' und liefere die "
                                "bisherigen Ergebnisse aus."
                            )
                        else:
                            self._generation_budget_reached_this_run = True
                            notify(
                                f"⏸️ [bold yellow]Generierungsreserve erreicht:[/bold yellow] "
                                f"{self._tokens_used_since(run_start_tokens):,} Tokens in diesem Lauf verbraucht – "
                                f"überspringe verbleibende Mitglieder in '{phase_label}'. Die anschließende "
                                "Verifikation läuft regulär mit dem verbleibenden Rest-Budget weiter (kein "
                                "Lauf-Abbruch)."
                            )
                        break

            all_results.extend(member_results)
            self._update_file_owners(file_owners, member_results)
            # Auf die letzten ~3000 Zeichen begrenzen, damit der Kontext über 5 Phasen hinweg
            # nicht unbegrenzt wächst und jedem folgenden Agenten unnötig viele Tokens kostet.
            running_context = (running_context + self._format_results_for_review(member_results)[:2000])[-3000:]

            # ── Echte Konsolidierung durch den Teamleiter ──
            # Wurde gerade in der Mitglieder-Schleife oben das Budget (bzw. die Generierungs-
            # reserve) überschritten oder hat der Circuit Breaker ausgelöst, entfällt der
            # zusätzliche Konsolidierungs-Aufruf - konsistent zum Phasenkopf, der ab der
            # nächsten Iteration ohnehin überspringt.
            if (
                ENABLE_DEPARTMENT_LEAD_EXECUTION and not skip_lead_layer and not budget_aborted
                and not provider_exhausted_abort and not getattr(self, "_generation_budget_reached_this_run", False)
            ):
                consolidation = await self._run_department_consolidation(lead, member_results, project_dir)
                all_results.append(consolidation)
                if _register_result_for_breaker(consolidation, is_lead=True):
                    provider_exhausted_abort = True
                elif consolidation.success and consolidation.content:
                    notify(f"  📥 [bold green]{lead.name} konsolidiert:[/bold green] {self._first_line(consolidation.content)}")
                else:
                    notify(f"  ⚠️ [yellow]{lead.name} konnte den Bereich nicht konsolidieren ({consolidation.error}).[/yellow]")
            else:
                notify(f"  📥 [dim]{phase_label} abgeschlossen ({len(member_results)} Ergebnisse).[/dim]")

            # ── Statischer Einstiegspunkt-Pre-Flight ──
            # Nur nach der Entwicklungsphase und nur, wenn diese nicht vorzeitig endete: ein
            # gezielter Mini-Task VOR den teuren QA-/Governance-Phasen, statt den fehlenden
            # Einstiegspunkt erst am Ende über die Definition of Done zu bemerken.
            if (
                dept_id == _ENTRYPOINT_PREFLIGHT_PHASE_ID
                and not budget_aborted and not provider_exhausted_abort and not manually_cancelled
            ):
                await self._run_entrypoint_preflight(project_dir, member_ids, all_results, file_owners, notify)
                await self._run_static_import_preflight(project_dir, all_results, file_owners, notify)
                if test_first_active and "tester" in member_ids:
                    await self._run_test_route_mismatch_preflight(project_dir, all_results, file_owners, notify)
                # P4-4 (ROADMAP_TEMP.md): interface_contract.json entstand für Backend-only-
                # Projekte bisher oft gar nicht (architect-Anweisung ohne Garantie, siehe
                # core/interface_contract.py-Docstring) - Nachtrag NUR, wenn die Datei nach der
                # Entwicklungsphase noch fehlt, aus dem tatsächlich geschriebenen Code, damit
                # QA/Governance ab hier wenigstens einen echten Vertrag vorfinden.
                try:
                    if ensure_interface_contract(project_dir):
                        notify("  📜 [dim]interface_contract.json fehlte - deterministisch aus dem geschriebenen Code nachgetragen.[/dim]")
                except Exception as e:
                    notify(f"  ⚠️ [dim yellow]interface_contract.json konnte nicht nachgetragen werden: {e}[/dim yellow]")
                await self._run_database_review_preflight(project_dir, all_results, notify)
                if ENABLE_INTEGRATION_CHECKPOINT and enable_phase_checkpoint:
                    self.last_integration_checkpoint_lines = await self._run_integration_checkpoint(
                        project_dir, all_results, file_owners, notify, run_start_tokens=run_start_tokens,
                    )

            # ── Sicherheits-Übergabe-Checkpoint ──
            # Nach der QA-/Security-Phase, nicht (wie der Integrations-Checkpoint oben) direkt
            # nach der Entwicklung - der security-Agent hat bis hierher noch gar nicht gearbeitet.
            if (
                dept_id == _SECURITY_HANDOFF_CHECKPOINT_PHASE_ID
                and not budget_aborted and not provider_exhausted_abort and not manually_cancelled
                and "security" in self._agents
            ):
                await self._run_security_requirements_checkpoint(
                    project_dir, all_results, file_owners, notify, run_start_tokens=run_start_tokens,
                )

            self._trace_event(
                "phase_finished",
                phase_id=dept_id,
                tokens=token_guard.get_summary()["grand_total_tokens"] - phase_start_tokens,
                successes=sum(1 for r in member_results if r.success),
                failures=sum(1 for r in member_results if not r.success),
                duration_seconds=round(time.monotonic() - phase_start_time, 1),
                files_written=sorted({f for r in member_results for f in (r.files_written or [])}),
            )

            remaining_phase_ids = [d for d, _, _, _ in PHASE_ORDER if d not in completed_phase_ids and d != dept_id]

            if provider_exhausted_abort:
                # Fast Circuit Breaker: keine weiteren Phasen, wenn das Fundament mangels
                # Provider-Kapazität nicht erzeugt werden konnte. `budget_aborted=True`
                # wiederverwendet die vorhandenen Graceful-Degradation-Pfade des Aufrufers; die
                # beiden Flags machen zusätzlich sichtbar, dass eine Kontingent-Erschöpfung und
                # kein generisches Budgetlimit die Ursache war.
                self._provider_exhausted_this_run = True
                self._provider_breaker_tripped = True
                budget_aborted = True
                notify(
                    "🛑 [bold red]Sofortabbruch:[/bold red] mehrere Agenten in Folge (bzw. eine "
                    "kritische Rolle) scheiterten an einer API-Kontingent-Erschöpfung - kein "
                    "Provider hat noch Kapazität. Keine weiteren Fachbereiche werden mehr "
                    "aufgerufen, um nicht weiter sinnlos Tokens zu verbrauchen."
                )
                # Sichert nur die bereits ABGESCHLOSSENEN Phasen (die gerade abgebrochene zählt
                # nicht dazu), damit ein erneuter Lauf sie überspringen kann.
                if enable_phase_checkpoint:
                    save_phase_checkpoint(
                        project_dir,
                        completed_phases=sorted(completed_phase_ids),
                        successful_agents=[r.agent_id for r in all_results if r.success],
                        running_context=running_context,
                        remaining_phases=[dept_id, *remaining_phase_ids],
                        aborted=True,
                        abort_reason="provider_exhausted",
                    )
                break

            completed_phase_ids.add(dept_id)
            if enable_phase_checkpoint:
                save_phase_checkpoint(
                    project_dir,
                    completed_phases=sorted(completed_phase_ids),
                    successful_agents=[r.agent_id for r in all_results if r.success],
                    running_context=running_context,
                    remaining_phases=remaining_phase_ids,
                )

        if enable_phase_checkpoint and not provider_exhausted_abort and not budget_aborted and not manually_cancelled:
            # Alle Phasen durchgelaufen - ein späterer, unabhängiger Folgeauftrag im selben
            # Projektordner darf diesen Checkpoint nicht mehr wiederverwenden.
            clear_checkpoint(project_dir)

        return all_results, file_owners, budget_aborted, manually_cancelled

    def _pick_entrypoint_preflight_agent(self, project_dir: str, member_ids: list[str]) -> str | None:
        """Bestimmt, wer den fehlenden Einstiegspunkt nachbessern soll: `backend` für Python-
        lastige Projekte, sonst `frontend` für Web-Projekte - jeweils nur, wenn diese Rolle
        überhaupt in der aktuellen dev_lead-Phase mitarbeitet (member_ids). Gibt None zurück,
        wenn weder backend noch frontend in diesem Lauf beteiligt sind (z.B. ein reines
        Datenbank-/ML-Projekt ohne eigenen Anwendungs-Einstiegspunkt) - dann bleibt der Befund
        nur eine Live-Warnung ohne automatischen Zusatz-Task."""
        has_py_files = any(Path(project_dir).rglob("*.py"))
        if has_py_files and "backend" in member_ids:
            return "backend"
        if "frontend" in member_ids:
            return "frontend"
        if "backend" in member_ids:
            return "backend"
        return None

    async def _run_entrypoint_preflight(
        self,
        project_dir: str,
        member_ids: list[str],
        all_results: list[AgentResult],
        file_owners: dict[str, str],
        notify: Callable[[str], None],
    ) -> None:
        """Führt check_entrypoint_exists() aus und dispatcht bei Bedarf einen gezielten
        Mini-Task an den zuständigen Entwickler."""
        entrypoint_ok, reason = check_entrypoint_exists(project_dir)
        if entrypoint_ok:
            return

        responsible_id = self._pick_entrypoint_preflight_agent(project_dir, member_ids)
        if not responsible_id or responsible_id not in self._agents:
            notify(
                f"  ⚠️ [yellow]Statischer Pre-Flight-Befund:[/yellow] {reason} Kein zuständiger "
                "Entwickler-Agent in diesem Lauf verfügbar - Befund bleibt für die spätere "
                "Definition of Done bestehen."
            )
            return

        agent_name = self._agents[responsible_id].name
        notify(
            f"  🛫 [bold yellow]Statischer Pre-Flight-Befund:[/bold yellow] {reason} Beauftrage "
            f"{agent_name} gezielt, BEVOR QA und Reviews starten."
        )
        preflight_task = AgentTask(
            task_id="dev_lead_entrypoint_preflight",
            agent_id=responsible_id,
            description=(
                "Statischer Pre-Flight-Befund: Es existieren Quelldateien, aber noch kein "
                "Haupteinstiegspunkt (z.B. main.py / app/main.py bzw. index.html). Erstelle "
                "diesen Einstiegspunkt jetzt vollständig, bevor QA und Reviews starten."
            ),
            project_dir=project_dir,
            allow_tools=True,
        )
        start_t = time.monotonic()
        result = await self._run_single_agent(preflight_task)
        dur = time.monotonic() - start_t
        all_results.append(result)
        self._update_file_owners(file_owners, [result])
        notify(self._status_notify_line(
            "  ✅ [green]Einstiegspunkt nachgereicht[/green]",
            "  ❌ [red]Einstiegspunkt weiterhin fehlend[/red]",
            agent_name, dur, result.success, result.error,
        ))

    async def _run_test_route_mismatch_preflight(
        self,
        project_dir: str,
        all_results: list[AgentResult],
        file_owners: dict[str, str],
        notify: Callable[[str], None],
    ) -> None:
        """P4-4 (ROADMAP_TEMP.md, realer Fund synapsegate): fängt erfundene Test-Routen und tote
        (nie `include_router`te) API-Router direkt nach der Test-First-Entwicklungsphase ab -
        rein statisch, kein LLM-Aufruf, keine Testausführung (`check_completeness()` scannt nur
        Dateien). Läuft NUR im Test-First-Modus, denn nur dort können Tests entstehen, bevor der
        reale Code existiert; ohne Test-First liest `tester` beim Schreiben ohnehin schon den
        echten Backend-Code (QA-Phase, nach der Entwicklung)."""
        # Wie _run_integration_checkpoint(): Tests rufen die Fachbereichs-Hierarchie mit
        # project_dir="." (Framework-Root) auf - ohne diese Schranke würde check_completeness()
        # das gesamte Framework-Repository samt workspace/ (20+ generierte Projekte) scannen.
        if not is_safe_project_dir(project_dir):
            return
        try:
            report = await asyncio.to_thread(lambda: ProjectVerifier(project_dir).check_completeness())
        except Exception as e:
            notify(f"  ⚠️ [dim yellow]Statischer Routen-Abgleich übersprungen (Fehler: {e}).[/dim yellow]")
            return
        if not report.attempted:
            return
        mismatches = [i for i in report.issues if i.kind in _TEST_ROUTE_MISMATCH_KINDS]
        if not mismatches:
            return

        agents_to_fix: dict[str, list] = {}
        for issue in mismatches:
            owner = (
                "tester" if issue.kind == "test_route_mismatch"
                else file_owners.get(issue.file_path, "backend")
            )
            if owner in self._agents:
                agents_to_fix.setdefault(owner, []).append(issue)
        if not agents_to_fix:
            return

        notify(
            f"  🔀 [bold yellow]Statischer Routen-Abgleich:[/bold yellow] {len(mismatches)} "
            f"Fund(e) (Test gegen nicht-deklarierte Route / toter Router) - beauftrage "
            f"{', '.join(agents_to_fix.keys())} gezielt, BEVOR QA und Reviews auf dem "
            "fehlerhaften Stand weiterarbeiten."
        )
        fix_tasks = []
        for agent_id, issues in agents_to_fix.items():
            finding_text = "\n".join(f"- {i.file_path}:{i.line_number} – {i.message}" for i in issues[:10])
            fix_tasks.append(AgentTask(
                task_id=f"dev_lead_route_mismatch_{agent_id}",
                agent_id=agent_id,
                description=(
                    "Statischer Pre-Flight-Befund (Test-First-Modus): ein oder mehrere Tests "
                    "rufen eine Route auf, die im Backend nicht erreichbar ist - entweder nie "
                    "deklariert oder über einen nie mit `include_router(...)` verbundenen "
                    "Router. Prüfe per read_file den TATSÄCHLICHEN Backend-Code (nicht die "
                    "geplante Spezifikation) und behebe GENAU diese Fund(e): entweder den Test "
                    "auf die real existierende Route korrigieren, oder - falls die Route laut "
                    "Auftrag tatsächlich fehlt - den Router korrekt verbinden bzw. den "
                    f"Endpunkt ergänzen.\n\n{finding_text}"
                ),
                project_dir=project_dir,
                allow_tools=True,
            ))
        start_t = time.monotonic()
        results = await self._run_agents_parallel(fix_tasks, notify=notify)
        dur = time.monotonic() - start_t
        all_results.extend(results)
        self._update_file_owners(file_owners, results)
        for res, agent_id in zip(results, agents_to_fix.keys(), strict=False):
            notify(self._status_notify_line(
                f"  ✅ [green]{agent_id}: Routen-Abgleich behoben[/green]",
                f"  ❌ [red]{agent_id}: Routen-Abgleich weiterhin offen[/red]",
                agent_id, dur, res.success, res.error,
            ))

    async def _run_database_review_preflight(
        self,
        project_dir: str,
        all_results: list[AgentResult],
        notify: Callable[[str], None],
    ) -> None:
        """P2-3 (ROADMAP_TEMP.md): setzt den `database`-Agenten deterministisch ein, wenn das
        Backend tatsächlich ein ORM (SQLAlchemy) verwendet, statt darauf zu warten, dass der
        Planer ihn beim Zerlegen zufällig wählt - real gemessen: nur 3 von 20 Läufen, obwohl
        SQLAlchemy-Fehler zu den häufigsten echten Testfehlern gehören. Rein statisch (Text-
        Suche in bereits geschriebenen .py-Dateien), kein LLM-Aufruf. Läuft NUR, wenn `database`
        weder bereits an diesem Lauf beteiligt war noch überhaupt als Rolle verfügbar ist."""
        if not is_safe_project_dir(project_dir):
            return
        if "database" not in self._agents:
            return
        if any(r.agent_id == "database" for r in all_results):
            return  # bereits eingesetzt - keine erzwungene Doppelarbeit

        try:
            uses_orm = False
            for py_file in Path(project_dir).rglob("*.py"):
                if any(part in {".venv", "venv", "node_modules", "__pycache__", ".git"} for part in py_file.parts):
                    continue
                try:
                    text = py_file.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if any(marker in text for marker in _ORM_MARKERS):
                    uses_orm = True
                    break
        except OSError:
            return
        if not uses_orm:
            return

        notify(
            "  🗄️ [bold yellow]ORM erkannt (SQLAlchemy):[/bold yellow] `database`-Agent war an "
            "diesem Lauf noch nicht beteiligt - beauftrage ihn gezielt zur Schema-/Migrations-"
            "Überprüfung, bevor QA/Governance auf einem ungeprüften Datenmodell weiterarbeiten."
        )
        task = AgentTask(
            task_id="dev_lead_database_review",
            agent_id="database",
            description=(
                "Statischer Pre-Flight-Befund: dieses Projekt verwendet SQLAlchemy, aber der "
                "database-Agent war an diesem Lauf bisher nicht beteiligt. Prüfe per read_file "
                "das tatsächlich geschriebene Datenmodell (Base-Definitionen, Beziehungen, "
                "Migrationen falls vorhanden) auf reale, häufige Fehlerquellen - konkurrierende "
                "`Base`-Definitionen, fehlende/falsche Fremdschlüssel, fehlende Migrationen, "
                "Session-/Engine-Fehlkonfiguration. Behebe gefundene Probleme direkt per "
                "write_file/edit_file; findest du keine, bestätige das kurz im Bericht."
            ),
            project_dir=project_dir,
            allow_tools=True,
        )
        start_t = time.monotonic()
        results = await self._run_agents_parallel([task], notify=notify)
        dur = time.monotonic() - start_t
        all_results.extend(results)
        res = results[0] if results else None
        if res is not None:
            notify(self._status_notify_line(
                "  ✅ [green]database: Schema-Überprüfung abgeschlossen[/green]",
                "  ❌ [red]database: Schema-Überprüfung fehlgeschlagen[/red]",
                "database", dur, res.success, res.error,
            ))

    async def _run_static_import_preflight(
        self,
        project_dir: str,
        all_results: list[AgentResult],
        file_owners: dict[str, str],
        notify: Callable[[str], None],
    ) -> None:
        """Prüft direkt nach dev_lead rein statisch auf nicht-existierende lokale Imports
        (missing_local_import) - fängt ImportError-Fallen VOR QA, Security und Verifikation ab."""
        if not is_safe_project_dir(project_dir):
            return
        try:
            report = await asyncio.to_thread(lambda: ProjectVerifier(project_dir).check_completeness())
        except Exception as e:
            notify(f"  ⚠️ [dim yellow]Statischer Import-Check übersprungen (Fehler: {e}).[/dim yellow]")
            return
        if not report.attempted:
            return
        missing_imports = [i for i in report.issues if i.kind == "missing_local_import"]
        if not missing_imports:
            return

        agents_to_fix: dict[str, list] = {}
        for issue in missing_imports:
            owner = file_owners.get(issue.file_path, "backend")
            if owner in self._agents:
                agents_to_fix.setdefault(owner, []).append(issue)
        if not agents_to_fix:
            return

        notify(
            f"  📦 [bold yellow]Statischer Import-Pre-Flight:[/bold yellow] {len(missing_imports)} "
            f"ungültige(r) lokale(r) Import(e) entdeckt - beauftrage {', '.join(agents_to_fix.keys())} "
            "gezielt, BEVOR QA, Security und Verifikation starten."
        )
        fix_tasks = []
        for agent_id, issues in agents_to_fix.items():
            finding_text = "\n".join(f"- {i.file_path}:{i.line_number} – {i.message}" for i in issues[:10])
            fix_tasks.append(AgentTask(
                task_id=f"dev_lead_missing_import_{agent_id}",
                agent_id=agent_id,
                description=(
                    "Statischer Pre-Flight-Befund: Dein Code importiert lokale Module oder Symbole, "
                    "die im Dateisystem nicht existieren. Dies führt zu einem sofortigen ImportError. "
                    "Lege entweder die fehlende Datei/das Symbol an oder korrigiere den Import-Pfad:\n\n"
                    f"{finding_text}"
                ),
                project_dir=project_dir,
                allow_tools=True,
            ))
        start_t = time.monotonic()
        results = await self._run_agents_parallel(fix_tasks, notify=notify)
        dur = time.monotonic() - start_t
        all_results.extend(results)
        self._update_file_owners(file_owners, results)
        for res, agent_id in zip(results, agents_to_fix.keys(), strict=False):
            notify(self._status_notify_line(
                f"  ✅ [green]{agent_id}: Lokale Imports korrigiert[/green]",
                f"  ❌ [red]{agent_id}: Lokale Imports weiterhin ungelöst[/red]",
                agent_id, dur, res.success, res.error,
            ))

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
            # 3 Iterationen reichten in der Praxis nicht immer für eine finale Zusammenfassung;
            # 4 statt des vollen Entwickler-Budgets (6), da rein lesender Aufruf.
            max_tool_iterations=4,
        )
        return await self._execute_and_log(lead, task)

    def _deterministic_consolidation(
        self, lead: DepartmentLeadAgent, member_results: list[AgentResult], project_dir: str,
    ) -> AgentResult:
        """Fachbereichsbericht ohne LLM aus echten Ergebnissen und Team-Board-Übergaben - die
        LLM-Konsolidierung kostet je Lead ein Vielfaches und fasst im Wesentlichen zusammen,
        was als strukturierte Daten ohnehin vorliegt."""
        succeeded = [r for r in member_results if r.success]
        failed = [r for r in member_results if not r.success]
        files = sorted({f for r in member_results for f in r.files_written})
        open_issues: list[str] = []
        requires: list[str] = []
        unmet: list[tuple[str, str]] = []
        if ENABLE_TEAM_BOARD and project_dir:
            try:
                from core.team_board import load_board, unmet_requirements

                member_ids = {r.agent_id for r in member_results}
                for handoff in load_board(project_dir).handoffs:
                    if handoff.agent_id in member_ids:
                        open_issues += [f"{handoff.agent_id}: {issue}" for issue in handoff.open_issues]
                        requires += [f"{handoff.agent_id}: {req}" for req in handoff.requires]
                unmet = [(a, r) for a, r in unmet_requirements(project_dir) if a in member_ids]
            except Exception as e:  # noqa: BLE001 - Bericht bleibt auch ohne Board aussagekräftig
                logging.getLogger(__name__).warning("Team-Board für Konsolidierung nicht lesbar: %r", e)
        summary = (
            f"{len(succeeded)}/{len(member_results)} Mitglieder erfolgreich, {len(files)} Datei(en), "
            f"{len(open_issues)} offene Punkt(e), {len(unmet)} unerfüllte Anforderung(en)"
        )
        lines = [summary, "", f"### Fachbereichsbericht {lead.name} (deterministisch)"]
        lines += [f"- ❌ {r.agent_name}: {(r.error or 'ohne Fehlertext')[:240]}" for r in failed]
        if files:
            lines.append("- Dateien: " + ", ".join(f"`{f}`" for f in files[:25]))
        if requires:
            lines.append("- Bedarf zwischen Kollegen: " + "; ".join(requires[:8]))
        if unmet:
            lines.append("- ⚠️ Unerfüllt: " + "; ".join(f"{a}: {r}" for a, r in unmet[:8]))
        if open_issues:
            lines.append("- Offen: " + "; ".join(open_issues[:8]))
        return AgentResult(
            task_id=f"{lead.department_id}_consolidate",
            agent_id=lead.department_id,
            agent_name=lead.name,
            success=True,
            content="\n".join(lines),
            model_used="deterministisch",
        )

    async def _run_department_consolidation(
        self,
        lead: DepartmentLeadAgent,
        member_results: list[AgentResult],
        project_dir: str,
    ) -> AgentResult:
        """Lässt den Teamleiter die echten Ergebnisse seines Teams prüfen und konsolidieren."""
        if not ENABLE_LLM_DEPARTMENT_CONSOLIDATION:
            return self._deterministic_consolidation(lead, member_results, project_dir)
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
            # 5 statt 4, aus demselben Grund wie bei _run_department_delegation oben.
            max_tool_iterations=5,
        )
        return await self._execute_and_log(lead, task)
