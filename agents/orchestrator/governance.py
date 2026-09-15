"""
agents/orchestrator/governance.py – GovernanceMixin: Fix-Schleifen für Review-Befunde und Rückfragen

- `_run_governance_fix_loop()` – gezielte Korrekturen für kritische Review-Befunde
  (code_reviewer/security/compliance) mit Re-Review, Eskalation und No-Progress-Breaker
- `_run_permission_blocked_clarification_fix()` – Rückfragen, die nur fehlende Freigaben betreffen
- `_run_scope_clarification_autofix()` – strukturelle Scope-Rückfragen autonom mit der
  naheliegendsten Annahme weiterbearbeiten
"""


import asyncio
import logging
from collections.abc import Callable

from agents.department_lead_agent import DEPARTMENT_DEFINITIONS
from agents.orchestrator.constants import REVIEW_ONLY_AGENT_IDS
from agents.orchestrator.failure_diagnosis import (
    _diagnose_import_failure,  # noqa: F401 - re-exportiert, siehe tests/test_import_name_error_learning.py
    _diagnose_no_tests_ran,  # noqa: F401 - re-exportiert, siehe tests/test_no_tests_ran_diagnosis.py
    _diagnose_runtime_failure,  # noqa: F401 - re-exportiert, siehe tests/test_runtime_failure_diagnosis.py
    _issue_signature,
    _no_progress,
    _prior_run_context,
)
from config import (
    ENABLE_GOVERNANCE_FIX_LOOP,
    MAX_REVIEW_ITERATIONS,
    MAX_TASK_TOKENS,
)
from core.backlog_store import get_ticket, upsert_ticket
from core.decision_log import log_decision
from core.message_bus import AgentResult, AgentTask
from core.notifier import notify_external
from core.review_gate import (
    find_critical_findings,
    find_permission_blocked_questions,
    find_structural_scope_questions,
    finding_from_critical_block,
    route_findings_to_owners,
)
from core.team_memory import record_lesson
from core.verifier import ProjectVerifier


class GovernanceMixin:
    """Governance-Fix-Schleife und autonome Behandlung von Rückfragen."""

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
        Robuste Außenhülle um `_run_governance_fix_loop_impl()`: `process()` erwartet IMMER ein
        valides Tupel `(all_results, summary, budget_aborted, manually_cancelled)`, nie eine
        Exception. `all_results` bleibt bei einem Absturz unverändert, da unklar ist, wie weit
        die Schleife intern schon mutiert hat.
        """
        try:
            return await self._run_governance_fix_loop_impl(
                project_dir, all_results, file_owners, notify,
                run_start_tokens=run_start_tokens, cancel_requested=cancel_requested,
            )
        except Exception as e:
            logging.getLogger(__name__).warning("Governance-Fix-Schleife abgebrochen (unerwarteter Fehler): %s", e, exc_info=True)
            notify(f"⚠️ [bold yellow]Governance-Fix-Schleife wegen eines unerwarteten Fehlers übersprungen:[/bold yellow] {e}")
            return all_results, "", False, False

    async def _run_governance_fix_loop_impl(
        self,
        project_dir: str,
        all_results: list[AgentResult],
        file_owners: dict[str, str],
        notify: Callable[[str], None],
        run_start_tokens: int | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> tuple[list[AgentResult], str, bool, bool]:
        """
        Behandelt als "Kritisch" markierte Befunde der Review-Rollen (REVIEW_ONLY_AGENT_IDS) als
        Blocker und routet sie per core/review_gate.py-Heuristik an die Datei-Owner zur Korrektur.

        Läuft nach der Governance-Phase und VOR der Testverifikation, damit die Testsuite den
        reparierten Stand prüft. Bei "kein Fortschritt" (identische Befunde) wird erst an den
        Fachbereichsleiter, dann an HEAVY_MODEL eskaliert, bevor ein Backlog-Ticket entsteht.
        check_completeness() dient als deterministische Gegenprobe zum LLM-Re-Review, damit ein
        vom Fix eingeführter Import-Bruch nicht übersehen wird.

        Gibt (all_results, summary, budget_aborted, manually_cancelled) zurück; summary ist "",
        wenn nichts zu tun war.
        """
        if not ENABLE_GOVERNANCE_FIX_LOOP:
            return all_results, "", False, False

        review_agent_ids = {
            r.agent_id for r in all_results
            if r.agent_id in REVIEW_ONLY_AGENT_IDS and r.success and r.content
        }
        if not review_agent_ids:
            # Keine Review-Rolle im Plan (z.B. kleine Aufgabe ohne QA/Governance).
            return all_results, "", False, False

        summary_lines: list[str] = []
        budget_aborted = False
        manually_cancelled = False
        # Zirkuit-Breaker: identische kritische Befunde nach einem Fixversuch bedeuten, dass der
        # Agent das Problem nicht lösen kann - ein weiterer Fix-Dispatch wäre Verschwendung.
        previous_findings_signature: frozenset[tuple[str, str]] | None = None
        # Eskalationsleiter wie in _run_verification_loop: erst Fachbereichsleiter, dann stärkeres Modell.
        escalation_attempted = False
        model_escalation_attempted = False
        # Cross-Run-Gedächtnis: ein Ticket aus einem früheren Lauf wird bei Erfolg geschlossen.
        governance_ticket_id = f"unresolved-governance-critical-{self.last_project_slug}" if self.last_project_slug else None
        try:
            had_prior_governance_ticket = bool(governance_ticket_id and get_ticket(governance_ticket_id) is not None)
        except Exception:
            had_prior_governance_ticket = False

        def _latest_review_results() -> list[AgentResult]:
            # Neuestes Ergebnis je Rolle - ein Re-Check überschreibt das ursprüngliche.
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
                # Nur bei MAX_REVIEW_ITERATIONS > 1: Review-Rollen prüfen den Stand nach dem letzten Fix erneut.
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
                if had_prior_governance_ticket and governance_ticket_id:
                    try:
                        upsert_ticket(
                            ticket_id=governance_ticket_id,
                            title=f"Ungelöster kritischer Governance-Befund: {self.last_project_slug}",
                            source="orchestrator", status="done", project_slug=self.last_project_slug,
                            detail="In einem späteren Lauf behoben - keine kritischen Befunde mehr.",
                        )
                        notify("  🎫 [dim]Ticket für vorherigen Governance-Befund als gelöst geschlossen.[/dim]")
                    except Exception as e:
                        notify(f"⚠️ [dim yellow]Ticket konnte nicht geschlossen werden: {e}[/dim yellow]")
                break

            current_findings_signature = _issue_signature(findings, lambda f: (f[0], f[1][:300]))
            if _no_progress(previous_findings_signature, current_findings_signature):
                escalated_and_resolved = False
                if not escalation_attempted and not (
                    run_start_tokens is not None and (
                        self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
                    )
                ):
                    escalation_attempted = True
                    stuck_agents_to_fix, _ = route_findings_to_owners(findings, file_owners)
                    stuck_owner_ids = set(stuck_agents_to_fix.keys()) & set(self._agents.keys())
                    lead_targets = {
                        dept_id for dept_id, defn in DEPARTMENT_DEFINITIONS.items()
                        if stuck_owner_ids & set(defn["members"]) and dept_id in self._dept_leads
                    }
                    findings_text = "\n\n".join(block for _agent_id, block in findings)[:3000]

                    async def _rerun_review_agents(task_prefix: str) -> list[tuple[str, str]]:
                        # Nur-Lese-Recheck nach der Eskalation, statt blind weiterzumachen.
                        tasks = [
                            AgentTask(
                                task_id=f"{task_prefix}_{agent_id}",
                                agent_id=agent_id,
                                description=(
                                    "Prüfe AUSSCHLIESSLICH, ob das zuvor gemeldete kritische Problem "
                                    "jetzt tatsächlich behoben ist. Melde erneut mit klarer "
                                    "Schweregrad-Markierung (\"Kritisch\"), falls es weiterhin besteht."
                                ),
                                context="", project_dir=project_dir, allow_tools=True, tools_read_only=True,
                            )
                            for agent_id in sorted(review_agent_ids)
                        ]
                        results = await self._run_agents_parallel(tasks, notify=notify)
                        all_results.extend(results)
                        return [
                            (res.agent_id, block) for res in results if res.success and res.content
                            for block in find_critical_findings(res.content)
                        ]

                    if lead_targets:
                        notify(
                            f"  🔀 [bold yellow]Strategiewechsel (Eskalation):[/bold yellow] Derselbe kritische "
                            f"Governance-Befund nach einem wirkungslosen Fixversuch – ziehe Fachbereichsleiter "
                            f"({', '.join(sorted(lead_targets))}) statt derselben Wiederholung hinzu..."
                        )
                        escalation_tasks = [
                            AgentTask(
                                task_id=f"governance_escalation_{dept_id}_{attempt}",
                                agent_id=dept_id,
                                description=(
                                    "Ein vorheriger, gezielter Fixversuch deines Fachbereichs hat den folgenden "
                                    "KRITISCHEN Governance-Befund NICHT behoben (identisch vor und nach dem "
                                    "Versuch) - derselbe Ansatz hat also erkennbar nicht funktioniert. "
                                    "Analysiere das Problem aus einer anderen Perspektive und weise dein Team "
                                    f"mit einer GEÄNDERTEN Strategie an, statt denselben Fix zu wiederholen.\n\n{findings_text}"
                                ),
                                context="", project_dir=project_dir,
                            )
                            for dept_id in lead_targets
                        ]
                        fix_results = await self._run_agents_parallel(escalation_tasks, notify=notify)
                        self._update_file_owners(file_owners, fix_results)
                        all_results.extend(fix_results)
                        summary_lines.append(
                            f"- 🔀 Versuch {attempt}: kein Fortschritt beim vorherigen Fix → Eskalation an "
                            f"Fachbereichsleiter ({', '.join(sorted(lead_targets))}) mit geänderter Strategie."
                        )
                        findings = await _rerun_review_agents(f"governance_escalation_recheck_{attempt}")
                        if not findings:
                            notify("  ✅ [bold green]Eskalation erfolgreich:[/bold green] keine kritischen Governance-Befunde mehr.")
                            summary_lines.append("- ✅ Eskalation an Fachbereichsleiter behob den Befund – keine kritischen Governance-Funde mehr.")
                            if had_prior_governance_ticket and governance_ticket_id:
                                try:
                                    upsert_ticket(
                                        ticket_id=governance_ticket_id,
                                        title=f"Ungelöster kritischer Governance-Befund: {self.last_project_slug}",
                                        source="orchestrator", status="done", project_slug=self.last_project_slug,
                                        detail="In einem späteren Lauf behoben - keine kritischen Befunde mehr.",
                                    )
                                except Exception as e:
                                    notify(f"⚠️ [dim yellow]Ticket konnte nicht geschlossen werden: {e}[/dim yellow]")
                            break
                        escalated_and_resolved = True  # Eskalation lief, aber weiterhin kritisch - ggf. Modell-Eskalation unten.
                        current_findings_signature = _issue_signature(findings, lambda f: (f[0], f[1][:300]))

                    if not model_escalation_attempted and stuck_owner_ids:
                        model_escalation_attempted = True
                        escalated_agent_ids = self._escalate_agent_models(stuck_owner_ids)
                        if escalated_agent_ids:
                            notify(
                                f"  ⬆️ [bold yellow]Letzter Versuch mit stärkerem Modell:[/bold yellow] "
                                f"{', '.join(sorted(escalated_agent_ids))} laufen für diesen Governance-Fix "
                                "auf HEAVY_MODEL, statt direkt aufzugeben."
                            )
                            findings_text = "\n\n".join(block for _agent_id, block in findings)[:3000]
                            model_escalation_tasks = [
                                AgentTask(
                                    task_id=f"governance_model_escalation_{owner}_{attempt}",
                                    agent_id=owner,
                                    description=(
                                        "Dein vorheriger, gezielter Fixversuch UND die Eskalation an deinen "
                                        "Fachbereichsleiter haben den folgenden KRITISCHEN Governance-Befund "
                                        "NICHT behoben - du bekommst jetzt für diesen letzten Versuch ein "
                                        f"stärkeres Modell.\n\n{findings_text}"
                                    ),
                                    context="", project_dir=project_dir,
                                )
                                for owner in sorted(escalated_agent_ids)
                            ]
                            fix_results = await self._run_agents_parallel(model_escalation_tasks, notify=notify)
                            self._update_file_owners(file_owners, fix_results)
                            all_results.extend(fix_results)
                            summary_lines.append(
                                f"- ⬆️ Versuch {attempt}: kein Fortschritt auch nach Eskalation an den "
                                f"Fachbereichsleiter → letzter Versuch mit HEAVY_MODEL für {', '.join(sorted(escalated_agent_ids))}."
                            )
                            findings = await _rerun_review_agents(f"governance_model_escalation_recheck_{attempt}")
                            if not findings:
                                notify("  ✅ [bold green]Modell-Eskalation erfolgreich:[/bold green] keine kritischen Governance-Befunde mehr.")
                                summary_lines.append("- ✅ Fix mit HEAVY_MODEL behob den Befund – keine kritischen Governance-Funde mehr.")
                                if had_prior_governance_ticket and governance_ticket_id:
                                    try:
                                        upsert_ticket(
                                            ticket_id=governance_ticket_id,
                                            title=f"Ungelöster kritischer Governance-Befund: {self.last_project_slug}",
                                            source="orchestrator", status="done", project_slug=self.last_project_slug,
                                            detail="In einem späteren Lauf behoben - keine kritischen Befunde mehr.",
                                        )
                                    except Exception as e:
                                        notify(f"⚠️ [dim yellow]Ticket konnte nicht geschlossen werden: {e}[/dim yellow]")
                                break
                            escalated_and_resolved = True

                notify(
                    "  🛑 [bold red]Kein Fortschritt:[/bold red] identische kritische Befunde wie vor dem letzten "
                    f"Fixversuch{' (auch nach Eskalation an den Fachbereichsleiter/stärkeres Modell)' if escalated_and_resolved else ''} "
                    "– eröffne Backlog-Ticket, statt unverändert weiterzumachen."
                )
                summary_lines.append(
                    f"- 🛑 Versuch {attempt}: dieselben {len(findings)} kritische(n) Befund(e) wie nach dem vorherigen "
                    "Fixversuch (keine Veränderung)" + (" - auch nach Eskalation" if escalated_and_resolved else "") +
                    " – weiterer Fix-Dispatch übersprungen, Backlog-Ticket direkt eröffnet."
                )
                # Einmal ungekürzt berechnen und überall verwenden - Ticket, Lernprotokoll und
                # Entscheidungslog haben kein Vollprotokoll, gekürzte Funde wären verloren.
                unresolved_detail = "\n\n".join(block for _agent_id, block in findings) + self._provider_exhaustion_ticket_note()
                try:
                    upsert_ticket(
                        ticket_id=f"unresolved-governance-critical-{getattr(self, 'last_project_slug', 'project')}",
                        title=f"Ungelöster kritischer Governance-Befund: {getattr(self, 'last_project_slug', 'project')}",
                        source="orchestrator", status="blocked",
                        project_slug=getattr(self, "last_project_slug", "project"),
                        detail=unresolved_detail,
                    )
                except Exception as e:
                    notify(f"⚠️ [dim yellow]Ticket für ungelösten Governance-Befund konnte nicht angelegt werden: {e}[/dim yellow]")
                record_lesson(
                    project_slug=getattr(self, "last_project_slug", "project"),
                    category="unresolved_governance_critical",
                    detail=unresolved_detail,
                )
                log_decision(project_dir, "unresolved_governance_critical_ticket_opened", unresolved_detail)
                await asyncio.to_thread(
                    notify_external, "Ungelöster kritischer Governance-Befund",
                    f"{getattr(self, 'last_project_slug', 'project')}: {unresolved_detail[:300]}",
                )
                break
            previous_findings_signature = current_findings_signature

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

            # Reichert den Freitext-Befund um die dateigenaue Fundliste des statischen Import-Checks
            # an, damit Review und Vorab-Import-Check denselben Defekt nicht getrennt fixen.
            # Rein lokal (kein LLM-Aufruf); CompletenessIssue.kind ist ein stabiles Tag.
            try:
                structural_report = ProjectVerifier(project_dir).check_completeness()
                structural_import_issues = [
                    i for i in structural_report.issues if i.kind == "missing_local_import"
                ] if structural_report.attempted else []
            except Exception:
                structural_import_issues = []

            fix_tasks = []
            for agent_id, texts in agents_to_fix.items():
                finding_text = "\n\n".join(texts)[:3000]
                owned_import_issues = [
                    i for i in structural_import_issues if file_owners.get(i.file_path) == agent_id
                ] or structural_import_issues
                structural_addendum = ""
                if owned_import_issues:
                    exact_list = "\n".join(
                        f"- {i.file_path}:{i.line_number} – {i.message}" for i in owned_import_issues[:10]
                    )
                    structural_addendum = (
                        "\n\nZUSÄTZLICH ein statischer Check derselben Fehlerklasse (fehlendes "
                        "lokales Modul/Paket) mit der EXAKTEN Datei-Liste - lege GENAU diese "
                        f"Dateien/Symbole an, nicht nur sinngemäß:\n{exact_list}"
                    )
                fix_tasks.append(AgentTask(
                    task_id=f"governance_fix_{agent_id}_{attempt}",
                    agent_id=agent_id,
                    description=(
                        f"Das Governance-Review (code_reviewer/security/compliance) hat ein "
                        f"KRITISCHES Problem in deinem Code gefunden. Nutze read_file, um die "
                        f"betroffene(n) Datei(en) zu prüfen, und edit_file/write_file, um das "
                        f"Problem zu beheben.\n\n{finding_text}{structural_addendum}"
                        + (_prior_run_context(governance_ticket_id) if attempt == 1 and governance_ticket_id else "")
                    ),
                    context="", project_dir=project_dir,
                ))

            notify(f"  🛠️ [bold yellow]Governance-Fix:[/bold yellow] Beauftrage {', '.join(agents_to_fix.keys())} mit {len(findings)} kritischem/kritischen Befund(en)...")
            log_decision(
                project_dir, "governance_fix_dispatched",
                f"Versuch {attempt}: {len(findings)} kritische(r) Befund(e) → {', '.join(agents_to_fix.keys())}",
            )
            fix_results = await self._run_agents_parallel(fix_tasks, notify=notify)
            self._update_file_owners(file_owners, fix_results)
            all_results.extend(fix_results)
            summary_lines.append(
                f"- 🛠️ Versuch {attempt}: {len(findings)} kritische(r) Governance-Befund(e) → gezielt "
                f"zur Korrektur an {', '.join(agents_to_fix.keys())} zurückgespielt (der Fix wird NICHT "
                f"erneut vom Reviewer bestätigt – das übernimmt für automatisiert testbares Verhalten "
                f"nur die anschließende echte Testverifikation, nicht die qualitative Review-Aussage selbst)."
            )

            # Pro-Task-Budget: ein laufender Aufruf lässt sich nicht sauber abbrechen, aber ein
            # ausufernder Fix-Task stoppt weitere Versuche für denselben Befund.
            oversized = [r for r in fix_results if MAX_TASK_TOKENS > 0 and r.total_tokens > MAX_TASK_TOKENS]
            if oversized:
                names = ", ".join(sorted({r.agent_id for r in oversized}))
                notify(f"  🚫 [bold red]Pro-Task-Budget überschritten[/bold red] ({names}) – weitere Governance-Fixversuche für diesen Befund werden übersprungen.")
                summary_lines.append(
                    f"- 🚫 Pro-Task-Budget ({MAX_TASK_TOKENS:,} Tokens) von {names} überschritten – "
                    f"Governance-Fix-Schleife nach Versuch {attempt} beendet, statt unbegrenzt weiter zu eskalieren."
                )
                break

            if attempt == MAX_REVIEW_ITERATIONS:
                # Verpflichtender Re-Review nach dem letzten Fix-Dispatch - sonst gälte ein Fix im
                # finalen Versuch ungeprüft als erledigt. Bleibt der Befund, folgt ein Backlog-Ticket.
                notify(f"  🔍 [yellow]Verpflichtender Re-Review nach Versuch {attempt}:[/yellow] prüft, ob der Fix tatsächlich griff...")
                final_recheck_tasks = [
                    AgentTask(
                        task_id=f"governance_final_recheck_{agent_id}",
                        agent_id=agent_id,
                        description=(
                            "Prüfe AUSSCHLIESSLICH, ob das zuvor gemeldete kritische Problem jetzt "
                            "tatsächlich behoben ist. Melde erneut mit klarer Schweregrad-Markierung "
                            "(\"Kritisch\"), falls es weiterhin besteht."
                        ),
                        context="", project_dir=project_dir, allow_tools=True, tools_read_only=True,
                    )
                    for agent_id in sorted(agents_to_fix.keys() & review_agent_ids)
                ] or [
                    AgentTask(
                        task_id=f"governance_final_recheck_{agent_id}",
                        agent_id=agent_id,
                        description="Prüfe den aktuellen Stand des Projekts erneut auf kritische Probleme.",
                        context="", project_dir=project_dir, allow_tools=True, tools_read_only=True,
                    )
                    for agent_id in sorted(review_agent_ids)
                ]
                final_recheck_results = await self._run_agents_parallel(final_recheck_tasks, notify=notify)
                all_results.extend(final_recheck_results)
                still_critical = [
                    block for res in final_recheck_results if res.success and res.content
                    for block in find_critical_findings(res.content)
                ]
                # Deterministische Gegenprobe zum LLM-Re-Review: ein vom Fix eingeführter, nicht
                # auflösbarer lokaler Import gilt als weiterhin kritisch, auch wenn der Reviewer ihn übersieht.
                try:
                    structural_recheck = ProjectVerifier(project_dir).check_completeness()
                    structural_still_critical = [
                        f"Statischer Check (ohne LLM-Bewertung): {i.file_path}:{i.line_number} – {i.message}"
                        for i in structural_recheck.issues if i.kind == "missing_local_import"
                    ] if structural_recheck.attempted else []
                except Exception:
                    structural_still_critical = []
                if structural_still_critical:
                    notify(f"  🧩 [bold red]Struktureller Neu-Bruch:[/bold red] {len(structural_still_critical)} lokale(r) Import(e) nach dem Fix nicht auflösbar - unabhängig vom LLM-Re-Review als weiterhin kritisch gewertet.")
                still_critical = still_critical + structural_still_critical

                # _no_progress() greift nur bei exakt wiederholtem Befund; eine andere Symptomatik
                # derselben Ursache soll trotzdem vor dem Ticket an den Fachbereichsleiter eskalieren.
                # Modell-Eskalation hier bewusst nicht (deckt der Breaker-Pfad oben ab).
                if still_critical and not escalation_attempted and not (
                    run_start_tokens is not None and (
                        self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
                    )
                ):
                    escalation_attempted = True
                    stuck_owner_ids = set(agents_to_fix.keys()) & set(self._agents.keys())
                    lead_targets = {
                        dept_id for dept_id, defn in DEPARTMENT_DEFINITIONS.items()
                        if stuck_owner_ids & set(defn["members"]) and dept_id in self._dept_leads
                    }
                    if lead_targets:
                        # Nicht-String-Einträge in still_critical dürfen keinen TypeError auslösen.
                        still_critical_text = "\n\n".join(
                            b if isinstance(b, str) else str(b) for b in still_critical
                        )[:3000]
                        notify(
                            f"  🔀 [bold yellow]Strategiewechsel (Eskalation):[/bold yellow] Der "
                            f"verpflichtende Re-Review meldet nach dem letzten Fixversuch weiterhin "
                            f"ein kritisches Problem (ggf. eine andere Symptomatik derselben Ursache) "
                            f"– ziehe Fachbereichsleiter ({', '.join(sorted(lead_targets))}) hinzu, "
                            "statt direkt ein Ticket zu eröffnen..."
                        )
                        escalation_tasks = [
                            AgentTask(
                                task_id=f"governance_final_escalation_{dept_id}",
                                agent_id=dept_id,
                                description=(
                                    "Der verpflichtende Abschluss-Review meldet nach dem letzten "
                                    "Fixversuch deines Fachbereichs WEITERHIN ein kritisches Problem "
                                    "(ggf. eine andere Symptomatik derselben Ursache, statt exakt "
                                    "desselben Befunds) - derselbe Ansatz hat also erkennbar nicht "
                                    "ausgereicht. Analysiere das Problem aus einer anderen "
                                    "Perspektive und weise dein Team mit einer GEÄNDERTEN Strategie "
                                    f"an.\n\n{still_critical_text}"
                                ),
                                context="", project_dir=project_dir,
                            )
                            for dept_id in lead_targets
                        ]
                        fix_results = await self._run_agents_parallel(escalation_tasks, notify=notify)
                        self._update_file_owners(file_owners, fix_results)
                        all_results.extend(fix_results)
                        summary_lines.append(
                            f"- 🔀 Nach {MAX_REVIEW_ITERATIONS} Versuch(en) weiterhin kritisch (andere "
                            f"Symptomatik) → Eskalation an Fachbereichsleiter "
                            f"({', '.join(sorted(lead_targets))}) vor der Ticket-Eröffnung."
                        )
                        escalation_recheck_agents = sorted(set(agents_to_fix.keys()) & review_agent_ids) or sorted(review_agent_ids)
                        escalation_recheck_tasks = [
                            AgentTask(
                                task_id=f"governance_final_escalation_recheck_{agent_id}",
                                agent_id=agent_id,
                                description=(
                                    "Prüfe AUSSCHLIESSLICH, ob das zuvor gemeldete kritische Problem "
                                    "jetzt tatsächlich behoben ist. Melde erneut mit klarer "
                                    "Schweregrad-Markierung (\"Kritisch\"), falls es weiterhin besteht."
                                ),
                                context="", project_dir=project_dir, allow_tools=True, tools_read_only=True,
                            )
                            for agent_id in escalation_recheck_agents
                        ]
                        escalation_recheck_results = await self._run_agents_parallel(escalation_recheck_tasks, notify=notify)
                        all_results.extend(escalation_recheck_results)
                        still_critical = [
                            block for res in escalation_recheck_results if res.success and res.content
                            for block in find_critical_findings(res.content)
                        ]
                        try:
                            structural_after_escalation = ProjectVerifier(project_dir).check_completeness()
                            still_critical += [
                                f"Statischer Check (ohne LLM-Bewertung): {i.file_path}:{i.line_number} – {i.message}"
                                for i in structural_after_escalation.issues if i.kind == "missing_local_import"
                            ] if structural_after_escalation.attempted else []
                        except Exception:
                            pass
                        if still_critical:
                            summary_lines.append(
                                "- 🛑 Eskalation an Fachbereichsleiter behob den Befund NICHT – "
                                "weiterhin kritisch."
                            )
                        else:
                            notify("  ✅ [bold green]Eskalation erfolgreich:[/bold green] keine kritischen Governance-Befunde mehr.")
                            summary_lines.append("- ✅ Eskalation an Fachbereichsleiter (nach dem verpflichtenden Re-Review) behob den Befund – keine kritischen Governance-Funde mehr.")

                if still_critical:
                    notify("  🛑 [bold red]Fix nicht bestätigt:[/bold red] Re-Review meldet weiterhin kritische Befunde – Backlog-Ticket für menschliche Prüfung eröffnet.")
                    summary_lines.append(
                        f"- 🛑 Nach {MAX_REVIEW_ITERATIONS} Versuch(en) bestätigt der Re-Review WEITERHIN "
                        f"{len(still_critical)} kritische(n) Befund(e) – Backlog-Ticket eröffnet statt "
                        "stillschweigend zu übernehmen."
                    )
                    # str(block) statt TypeError, falls still_critical je einen Nicht-String enthält
                    # (finding_from_critical_block() erwartet str) - der Fund bleibt als Text erhalten.
                    still_critical_detail = "\n\n".join(
                        b if isinstance(b, str) else str(b) for b in still_critical
                    ) + self._provider_exhaustion_ticket_note()
                    try:
                        # Zusätzlich als ReviewFinding speichern: CLI/backlog_worker posten diese nach
                        # create_pull_request() als dateibezogene PR-Review-Kommentare.
                        self.last_unresolved_review_findings.extend(
                            finding_from_critical_block(block if isinstance(block, str) else str(block))
                            for block in still_critical
                        )
                        try:
                            upsert_ticket(
                                ticket_id=f"unresolved-governance-critical-{getattr(self, 'last_project_slug', 'project')}",
                                title=f"Ungelöster kritischer Governance-Befund: {getattr(self, 'last_project_slug', 'project')}",
                                source="orchestrator", status="blocked",
                                project_slug=getattr(self, "last_project_slug", "project"),
                                detail=still_critical_detail,
                            )
                        except Exception as e:
                            notify(f"⚠️ [dim yellow]Ticket für ungelösten Governance-Befund konnte nicht angelegt werden: {e}[/dim yellow]")
                        record_lesson(
                            project_slug=getattr(self, "last_project_slug", "project"),
                            category="unresolved_governance_critical",
                            detail=still_critical_detail,
                        )
                        log_decision(project_dir, "unresolved_governance_critical_ticket_opened", still_critical_detail)
                        await asyncio.to_thread(
                            notify_external, "Ungelöster kritischer Governance-Befund",
                            f"{getattr(self, 'last_project_slug', 'project')}: {still_critical_detail[:300]}",
                        )
                    except Exception as e:
                        # Ticket/Lernprotokoll/Benachrichtigung sind Nebenwirkungen - ein defektes
                        # Backend darf den Governance-Fix-Lauf nicht abstürzen lassen.
                        notify(f"⚠️ [dim yellow]Nachbearbeitung des ungelösten Governance-Befunds fehlgeschlagen: {e}[/dim yellow]")
                else:
                    summary_lines.append(f"- ✅ Re-Review nach Versuch {attempt} bestätigt: keine kritischen Befunde mehr.")

        summary = (
            "### 🔍 Governance-Fix-Protokoll (kritische Review-Befunde)\n" + "\n".join(summary_lines)
            if summary_lines else ""
        )
        return all_results, summary, budget_aborted, manually_cancelled

    async def _run_permission_blocked_clarification_fix(
        self,
        project_dir: str,
        all_results: list[AgentResult],
        file_owners: dict[str, str],
        notify: Callable[[str], None],
        run_start_tokens: int | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> tuple[list[AgentResult], str, bool, bool]:
        """
        Robuste Außenhülle um `_run_permission_blocked_clarification_fix_impl()` - garantiert wie
        bei `_run_governance_fix_loop` IMMER ein valides Tupel statt einer Exception.
        """
        try:
            return await self._run_permission_blocked_clarification_fix_impl(
                project_dir, all_results, file_owners, notify,
                run_start_tokens=run_start_tokens, cancel_requested=cancel_requested,
            )
        except Exception as e:
            logging.getLogger(__name__).warning(
                "Fix-Schleife für schreibgeschützt blockierte Rückfragen abgebrochen (unerwarteter Fehler): %s",
                e, exc_info=True,
            )
            notify(f"⚠️ [bold yellow]Fix für schreibgeschützt blockierte Rückfragen wegen eines unerwarteten Fehlers übersprungen:[/bold yellow] {e}")
            return all_results, "", False, False

    async def _run_permission_blocked_clarification_fix_impl(
        self,
        project_dir: str,
        all_results: list[AgentResult],
        file_owners: dict[str, str],
        notify: Callable[[str], None],
        run_start_tokens: int | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> tuple[list[AgentResult], str, bool, bool]:
        """
        Routet Rückfragen, die nur an fehlenden Schreibrechten scheitern (z.B. ein read-only
        security-Agent mit konkretem Fund), an einen schreibberechtigten Datei-Owner - sonst
        bliebe ein lösbares Problem über beliebig viele Läufe unbeantwortet liegen.

        Läuft nach der Governance-Fix-Schleife und vor der Testverifikation; nutzt dieselbe
        route_findings_to_owners()-Zuordnung, mit der Rückfrage als Fund-Text.

        Gibt (all_results, summary, budget_aborted, manually_cancelled) zurück; summary ist ""
        bei nichts zu tun.
        """
        blocked: list[tuple[str, str, AgentResult]] = []
        for res in all_results:
            if not res.clarification_questions:
                continue
            for q in find_permission_blocked_questions(res.clarification_questions):
                blocked.append((res.agent_id, q, res))

        if not blocked:
            return all_results, "", False, False

        if run_start_tokens is not None and (
            self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
        ):
            notify("  🚫 [bold red]Budget erreicht[/bold red] – Fix für schreibgeschützt blockierte Rückfragen übersprungen.")
            return all_results, "", True, False
        if cancel_requested and cancel_requested():
            notify("  ⏹️ [bold red]Lauf manuell abgebrochen[/bold red] – Fix für schreibgeschützt blockierte Rückfragen übersprungen.")
            return all_results, "", False, True

        findings = [(agent_id, q) for agent_id, q, _res in blocked]
        agents_to_fix, unrouted = route_findings_to_owners(findings, file_owners)

        summary_lines: list[str] = []
        if unrouted:
            shown = "; ".join(u[:150] for u in unrouted[:3])
            more = f" … und {len(unrouted) - 3} weitere" if len(unrouted) > 3 else ""
            summary_lines.append(
                f"- ⚠️ {len(unrouted)} schreibgeschützt blockierte Rückfrage(n) ohne eindeutigen "
                f"Datei-Bezug – braucht manuelle Prüfung: {shown}{more}"
            )

        if agents_to_fix:
            fix_tasks = []
            for agent_id, texts in agents_to_fix.items():
                finding_text = "\n\n".join(texts)[:3000]
                fix_tasks.append(AgentTask(
                    task_id=f"permission_blocked_fix_{agent_id}",
                    agent_id=agent_id,
                    description=(
                        f"Ein anderer Agent hat ein konkretes Problem identifiziert, konnte es aber wegen "
                        f"fehlender Schreibrechte NICHT selbst beheben. Nutze read_file, um die betroffene(n) "
                        f"Datei(en) zu prüfen, und edit_file/write_file, um das Problem wirklich zu "
                        f"beheben.\n\n{finding_text}"
                    ),
                    context="", project_dir=project_dir,
                ))
            notify(f"  🛠️ [bold yellow]Schreibgeschützt blockierte Rückfrage(n):[/bold yellow] Beauftrage {', '.join(agents_to_fix.keys())} mit {len(agents_to_fix)} Fund(en)...")
            log_decision(
                project_dir, "permission_blocked_fix_dispatched",
                f"{len(agents_to_fix)} blockierte Rückfrage(n) → {', '.join(agents_to_fix.keys())}",
            )
            fix_results = await self._run_agents_parallel(fix_tasks, notify=notify)
            self._update_file_owners(file_owners, fix_results)
            all_results.extend(fix_results)
            summary_lines.append(
                f"- 🛠️ {len(blocked) - len(unrouted)} schreibgeschützt blockierte Rückfrage(n) → gezielt "
                f"zur Korrektur an {', '.join(agents_to_fix.keys())} zurückgespielt (keine unbeantwortete "
                f"Rückfrage mehr im Abschlussbericht)."
            )

            # Pro-Task-Budget-Warnsignal wie in _run_governance_fix_loop.
            oversized = [r for r in fix_results if MAX_TASK_TOKENS > 0 and r.total_tokens > MAX_TASK_TOKENS]
            if oversized:
                names = ", ".join(sorted({r.agent_id for r in oversized}))
                notify(f"  🚫 [bold red]Pro-Task-Budget überschritten[/bold red] ({names}).")
                summary_lines.append(f"- 🚫 Pro-Task-Budget ({MAX_TASK_TOKENS:,} Tokens) von {names} überschritten.")

            # Behobene Fragen aus open_questions entfernen. `unrouted` nutzt dasselbe "[agent_id] text"-
            # Format wie route_findings_to_owners(), daran erkennt man die gerouteten Fragen.
            unrouted_set = set(unrouted)
            fixed_raiser_ids: set[str] = set()
            for agent_id, q, res in blocked:
                if f"[{agent_id}] {q.strip()}" in unrouted_set:
                    continue
                if q in res.clarification_questions:
                    res.clarification_questions.remove(q)
                    fixed_raiser_ids.add(res.agent_id)

            # Verpflichtender Re-Review: der ursprünglich blockierte Agent prüft den Fix read-only nach,
            # statt den Fix-Dispatch ungeprüft als erledigt zu behandeln.
            if fixed_raiser_ids and not oversized:
                notify(f"  🔍 [yellow]Verpflichtender Re-Review:[/yellow] {', '.join(sorted(fixed_raiser_ids))} prüft den Fix nach...")
                recheck_tasks = [
                    AgentTask(
                        task_id=f"permission_blocked_recheck_{raiser_id}",
                        agent_id=raiser_id,
                        description=(
                            "Prüfe, ob das von dir zuvor gemeldete Problem (das du mangels "
                            "Schreibrechten nicht selbst beheben konntest) jetzt tatsächlich behoben "
                            "ist. Melde mit klarer Schweregrad-Markierung (\"Kritisch\"), falls nicht."
                        ),
                        context="", project_dir=project_dir, allow_tools=True, tools_read_only=True,
                    )
                    for raiser_id in sorted(fixed_raiser_ids)
                    if raiser_id in self._agents or raiser_id in self._dept_leads
                ]
                recheck_results = await self._run_agents_parallel(recheck_tasks, notify=notify)
                all_results.extend(recheck_results)
                still_critical = [
                    block for res in recheck_results if res.success and res.content
                    for block in find_critical_findings(res.content)
                ]
                if still_critical:
                    notify("  🛑 [bold red]Fix nicht bestätigt:[/bold red] Re-Review meldet weiterhin ein kritisches Problem – Backlog-Ticket eröffnet.")
                    summary_lines.append(
                        f"- 🛑 Re-Review bestätigt den Fix NICHT – {len(still_critical)} weiterhin kritische(r) "
                        "Befund(e). Backlog-Ticket für menschliche Prüfung eröffnet."
                    )
                    # str(block) statt TypeError bei Nicht-Strings (wie in _run_governance_fix_loop_impl).
                    still_critical_detail = "\n\n".join(
                        b if isinstance(b, str) else str(b) for b in still_critical
                    ) + self._provider_exhaustion_ticket_note()
                    try:
                        # Als ReviewFinding für PR-Review-Kommentare speichern (wie in _run_governance_fix_loop_impl).
                        self.last_unresolved_review_findings.extend(
                            finding_from_critical_block(block if isinstance(block, str) else str(block))
                            for block in still_critical
                        )
                        try:
                            upsert_ticket(
                                ticket_id=f"unresolved-permission-blocked-{getattr(self, 'last_project_slug', 'project')}",
                                title=f"Ungelöster, zuvor schreibgeschützt blockierter Befund: {getattr(self, 'last_project_slug', 'project')}",
                                source="orchestrator", status="blocked",
                                project_slug=getattr(self, "last_project_slug", "project"),
                                detail=still_critical_detail,
                            )
                        except Exception as e:
                            notify(f"⚠️ [dim yellow]Ticket konnte nicht angelegt werden: {e}[/dim yellow]")
                        record_lesson(
                            project_slug=getattr(self, "last_project_slug", "project"),
                            category="unresolved_permission_blocked_fix",
                            detail=still_critical_detail,
                        )
                        log_decision(project_dir, "unresolved_permission_blocked_fix_ticket_opened", still_critical_detail)
                        await asyncio.to_thread(
                            notify_external, "Ungelöster, zuvor schreibgeschützt blockierter Befund",
                            f"{getattr(self, 'last_project_slug', 'project')}: {still_critical_detail[:300]}",
                        )
                    except Exception as e:
                        # Nebenwirkungen dürfen den Lauf nicht abstürzen lassen (wie in _run_governance_fix_loop_impl).
                        notify(f"⚠️ [dim yellow]Nachbearbeitung des ungelösten, schreibgeschützt blockierten Befunds fehlgeschlagen: {e}[/dim yellow]")
                else:
                    summary_lines.append("- ✅ Re-Review bestätigt: Fix erfolgreich.")

        summary = (
            "### 🔓 Fix-Protokoll (schreibgeschützt blockierte Rückfragen)\n" + "\n".join(summary_lines)
            if summary_lines else ""
        )
        return all_results, summary, False, False

    async def _run_scope_clarification_autofix(
        self,
        project_dir: str,
        all_results: list[AgentResult],
        file_owners: dict[str, str],
        notify: Callable[[str], None],
        run_start_tokens: int | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> tuple[list[AgentResult], str, bool, bool]:
        """
        Lässt Agenten strukturelle Scope-Rückfragen (z.B. "Soll ich die fehlende app/-Struktur
        anlegen?") autonom mit der naheliegendsten Annahme beantworten und weiterbauen - es gibt
        keinen anwesenden Menschen, sonst endet der Lauf ohne Kernfunktion.

        Läuft nach der Schreibrechte-Fix-Schleife und vor der Testverifikation. Nutzt bewusst
        die enge Allowlist find_structural_scope_questions(): echte fachliche Unklarheiten
        (z.B. "Welche Zahlungsanbieter?") müssen weiter zur Eskalation an einen Menschen führen.

        Gibt (all_results, summary, budget_aborted, manually_cancelled) zurück; summary ist ""
        bei nichts zu tun.
        """
        remaining: list[tuple[str, str, AgentResult]] = []
        for res in all_results:
            if not res.clarification_questions:
                continue
            in_scope = set(find_structural_scope_questions(res.clarification_questions))
            for q in res.clarification_questions:
                if q in in_scope:
                    remaining.append((res.agent_id, q, res))

        if not remaining:
            return all_results, "", False, False

        if run_start_tokens is not None and (
            self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
        ):
            notify("  🚫 [bold red]Budget erreicht[/bold red] – Auto-Entscheid für offene Rückfragen übersprungen.")
            return all_results, "", True, False
        if cancel_requested and cancel_requested():
            notify("  ⏹️ [bold red]Lauf manuell abgebrochen[/bold red] – Auto-Entscheid für offene Rückfragen übersprungen.")
            return all_results, "", False, True

        # Je fragendem Agent EINE Sammel-Aufgabe statt einer pro Frage.
        by_agent: dict[str, list[str]] = {}
        for agent_id, q, _res in remaining:
            if agent_id in self._agents or agent_id in self._dept_leads:
                by_agent.setdefault(agent_id, []).append(q.strip())

        if not by_agent:
            return all_results, "", False, False

        fix_tasks = [
            AgentTask(
                task_id=f"scope_clarification_autofix_{agent_id}",
                agent_id=agent_id,
                description=(
                    "Du hast zuvor eine offene fachliche Rückfrage gestellt, statt direkt "
                    "weiterzuarbeiten. Es ist KEIN Mensch verfügbar, der diese Rückfrage in "
                    "Echtzeit beantworten kann - das Team arbeitet autonom. Triff selbst die "
                    "naheliegendste, sinnvollste Annahme (z.B.: fehlende Grundstruktur/Dateien "
                    "einfach selbst anlegen, statt zu fragen, ob du das darfst) und setze die "
                    "Aufgabe VOLLSTÄNDIG um. Dokumentiere die getroffene Annahme kurz als "
                    "Kommentar im Code oder in einer README-Sektion.\n\n"
                    "Deine offene(n) Rückfrage(n):\n" + "\n".join(f"- {q}" for q in questions)
                ),
                context="", project_dir=project_dir,
            )
            for agent_id, questions in by_agent.items()
        ]

        notify(
            f"  🧭 [bold yellow]Offene Scope-Rückfrage(n):[/bold yellow] Kein Mensch verfügbar – "
            f"{', '.join(by_agent.keys())} entscheidet/entscheiden autonom und baut/bauen weiter..."
        )
        log_decision(
            project_dir, "scope_clarification_autofix_dispatched",
            f"{len(remaining)} offene Rückfrage(n) → {', '.join(by_agent.keys())}",
        )
        fix_results = await self._run_agents_parallel(fix_tasks, notify=notify)
        self._update_file_owners(file_owners, fix_results)
        all_results.extend(fix_results)

        # Beantwortete Rückfragen entfernen, damit sie nicht weiter als offen im Bericht erscheinen.
        resolved_agent_ids = set(by_agent.keys())
        for agent_id, q, res in remaining:
            if agent_id in resolved_agent_ids and q in res.clarification_questions:
                res.clarification_questions.remove(q)

        summary = (
            "### 🧭 Auto-Entscheid-Protokoll (offene Scope-Rückfragen ohne verfügbaren Menschen)\n"
            f"- 🧭 {len(remaining)} offene fachliche Rückfrage(n) von {', '.join(sorted(resolved_agent_ids))} "
            f"autonom mit der naheliegendsten Annahme weiterbearbeitet, statt den Lauf unbeantwortet enden zu lassen."
        )
        return all_results, summary, False, False
