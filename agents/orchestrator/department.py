"""
agents/orchestrator/department.py – DepartmentMixin: Fachbereichs-Hierarchie mit ECHTER
Teamleiter-Delegation & -Konsolidierung (siehe agents/department_lead_agent.py). Führt alle
6 Fachbereichs-Phasen (PHASE_ORDER) aus, lässt den zuständigen Teamleiter per echtem
LLM-Aufruf delegieren, sein Fachteam parallel/sequenziell arbeiten und die Ergebnisse
anschließend per weiterem LLM-Aufruf konsolidieren.
"""

import time
from collections.abc import Callable

from agents.department_lead_agent import DEPARTMENT_DEFINITIONS, DepartmentLeadAgent
from agents.orchestrator.constants import PHASE_ORDER
from config import ENABLE_DEPARTMENT_LEAD_EXECUTION, ENABLE_TASK_COMPLEXITY_SCALING
from core.message_bus import AgentResult, AgentTask
from core.task_manager import is_micro_task


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
            # _generation_budget_exceeded statt _run_budget_exceeded: reserviert einen Anteil
            # von MAX_RUN_TOKENS (VERIFICATION_TOKEN_RESERVE_RATIO, config.py) exklusiv für die
            # spätere Verifikations-/Fix-Phase, die Autonomie erst beweist - siehe deren
            # Docstring (agents/orchestrator/budget.py) für den realen Fund (incidentpilot), der
            # das motiviert hat.
            if run_start_tokens is not None and (
                self._generation_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
            ):
                budget_aborted = True
                notify(
                    f"🚫 [bold red]{self._budget_exceeded_label(run_start_tokens)} erreicht:[/bold red] "
                    f"{self._tokens_used_since(run_start_tokens):,} Tokens in diesem Lauf verbraucht – "
                    f"überspringe verbleibende Fachbereiche ab '{phase_label}' und liefere die bisherigen "
                    "Ergebnisse aus (Rest-Budget bleibt für die Verifikation reserviert)."
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

                    # Realer Fund: die Budget-Prüfung lief bisher NUR einmal am Anfang jeder
                    # Fachbereichs-Phase (siehe Schleifenkopf oben) - bei mehreren SEQUENZIELL
                    # laufenden Mitgliedern (z.B. Governance: Code-Reviewer -> Compliance ->
                    # Projekt-Hygiene) konnte ein Lauf dadurch erst NACH der kompletten Phase
                    # bemerkt werden, dass MAX_RUN_TOKENS bereits deutlich überschritten war
                    # (beobachtet: 383.143 von 300.000 Tokens, +27%). Zusätzliche Prüfung NACH
                    # jedem einzelnen sequenziellen Mitglied (nicht im parallelen Zweig oben -
                    # dort läuft bereits alles gleichzeitig, ein Zwischenstopp mitten in
                    # asyncio.gather ist nicht sinnvoll möglich) - bricht die Phase ggf. vorzeitig
                    # ab, die äußere Schleife überspringt beim nächsten Phasenkopf dann wie gehabt
                    # alle verbleibenden Fachbereiche.
                    if run_start_tokens is not None and (
                        self._generation_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
                    ):
                        budget_aborted = True
                        notify(
                            f"🚫 [bold red]{self._budget_exceeded_label(run_start_tokens)} erreicht:[/bold red] "
                            f"{self._tokens_used_since(run_start_tokens):,} Tokens in diesem Lauf verbraucht – "
                            f"überspringe verbleibende Mitglieder in '{phase_label}' und liefere die bisherigen "
                            "Ergebnisse aus (Rest-Budget bleibt für die Verifikation reserviert)."
                        )
                        break

            all_results.extend(member_results)
            self._update_file_owners(file_owners, member_results)
            # Auf die letzten ~3000 Zeichen begrenzen, damit der Kontext über 5 Phasen hinweg
            # nicht unbegrenzt wächst und jedem folgenden Agenten unnötig viele Tokens kostet.
            running_context = (running_context + self._format_results_for_review(member_results)[:2000])[-3000:]

            # ── Echte Konsolidierung durch den Teamleiter ──
            # "and not budget_aborted": wurde das Budget gerade eben MITTEN in der sequenziellen
            # Mitglieder-Schleife oben überschritten, spart der zusätzliche Konsolidierungs-
            # Aufruf hier den letzten möglichen Tokenverbrauch dieser Phase ein - konsistent
            # mit dem äußeren Phasenkopf, der ab der NÄCHSTEN Iteration ohnehin komplett
            # überspringt.
            if ENABLE_DEPARTMENT_LEAD_EXECUTION and not skip_lead_layer and not budget_aborted:
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
