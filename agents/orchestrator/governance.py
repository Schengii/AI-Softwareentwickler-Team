"""
agents/orchestrator/governance.py – GovernanceMixin: Fix-Schleifen für Review-Befunde und Rückfragen

Aus agents/orchestrator/verification.py ausgelagert (Team-Analyse 2026-09-15, Punkt 6: die Datei
hatte ~2.800 Zeilen). Enthält unverändert:
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
        Robuste Außenhülle um `_run_governance_fix_loop_impl()` (Fehleranalyse 2026-09-13,
        reale unbehandelte TypeErrors im Governance-Loop): egal was innerhalb der Schleife
        schiefgeht (z.B. ein nicht-String-`block` in `finding_from_critical_block()`, ein
        defektes Ticket-System o.ä.) - `process()` erwartet hier IMMER ein valides Tupel
        `(all_results, summary, budget_aborted, manually_cancelled)` und darf NIE mit einer
        durchgereichten Exception abstürzen. `all_results` wird dabei bewusst unverändert
        zurückgegeben (statt eines Teilzustands), da bei einem Absturz nicht sicher feststeht,
        wie weit die Schleife intern schon mutiert hat.
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

        Team-Optimierung (vollständige Umsetzung einer KI-Team-Retrospektive): bei "kein
        Fortschritt" (identische kritische Befunde nach einem Fixversuch) durchläuft diese
        Schleife jetzt dieselbe Eskalationsleiter wie _run_verification_loop unten, BEVOR ein
        Backlog-Ticket eröffnet wird - erst Fachbereichsleiter (geänderte Strategie), dann ein
        letzter Versuch mit HEAVY_MODEL für die stecken gebliebenen Agenten. Vorher gab diese
        Schleife nach GENAU EINEM erfolglosen Fixversuch auf; der spätere `--work-backlog`-
        Retry (core/backlog_worker.py) eskaliert zwar ebenfalls das Modell, aber erst Stunden/
        Tage später im nächsten Scheduler-Zyklus. Zusätzlich läuft check_completeness() (core/
        verifier/completeness.py) als harte, deterministische Gegenprobe zum finalen LLM-Re-
        Review - ein struktureller Neu-Bruch (z.B. ein durch den Fix selbst eingeführter
        `ImportError`, real beobachtet am event_relay-Lauf 2026-09-06) gilt damit als weiterhin
        kritisch, UNABHÄNGIG davon, ob der LLM-Reviewer ihn bemerkt.
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
        # Derselbe Zirkuit-Breaker wie in _run_verification_loop (Team-Retrospektive nach dem
        # taskpulse-Lauf): identische kritische Befunde nach einem Fixversuch bedeuten fast
        # immer, dass der Agent das Problem nicht lösen konnte - ein zweiter Fix-Dispatch UND
        # der anschließende verpflichtende Re-Review (siehe unten, "attempt ==
        # MAX_REVIEW_ITERATIONS") wären dann reine Tokens/Zeit-Verschwendung. Bricht in diesem
        # Fall direkt zur Ticket-Eröffnung durch, ohne den zweiten Fix-Dispatch zu versuchen.
        previous_findings_signature: frozenset[tuple[str, str]] | None = None
        # Team-Optimierung (vollständige Umsetzung einer KI-Team-Retrospektive): _run_verification_loop
        # unten eskaliert bei Stagnation bereits an den Fachbereichsleiter UND an ein stärkeres
        # Modell, BEVOR aufgegeben wird - diese Schleife hier brach bisher bei "kein Fortschritt"
        # nach genau EINEM Fixversuch direkt zum Ticket ab, ohne dieselbe Eskalationsleiter zu
        # durchlaufen (der spätere `--work-backlog`-Retry eskaliert zwar das Modell, aber erst
        # Stunden/Tage später im nächsten Scheduler-Zyklus, siehe core/backlog_worker.py). Diese
        # beiden Flags spiegeln escalation_attempted/model_escalation_attempted unten 1:1.
        escalation_attempted = False
        model_escalation_attempted = False
        # Dasselbe Cross-Run-Gedächtnis wie in _run_verification_loop (Team-Retrospektive nach
        # dem taskpulse-Lauf, zweite Runde).
        governance_ticket_id = f"unresolved-governance-critical-{self.last_project_slug}" if self.last_project_slug else None
        try:
            had_prior_governance_ticket = bool(governance_ticket_id and get_ticket(governance_ticket_id) is not None)
        except Exception:
            had_prior_governance_ticket = False

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
                        # Dieselbe Nur-Lese-Recheck-Logik wie beim regulären Zwischen-Versuch
                        # oben (attempt > 1) - prüft NACH der Eskalation, ob die Governance-
                        # Rollen jetzt noch etwas Kritisches melden, statt blind weiterzumachen.
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
                # Team-Optimierung (Retrospektive 2026-09-05): früher wurde dieselbe Zusammen-
                # fassung an 3 Stellen (Ticket, Lernprotokoll, Entscheidungslog) JEWEILS separat
                # auf 300 Zeichen gekürzt - für keine der drei existiert ein ungekürztes
                # Vollprotokoll wie .ai_team_status_full.log, ein hier gekürzter Governance-Fund
                # war also unwiederbringlich weg. Einmal ungekürzt berechnen, überall gleich
                # verwenden (log_decision() deckelt selbst noch auf core.decision_log.
                # MAX_DETAIL_CHARS, aber deutlich großzügiger als vorher).
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

            # Team-Retrospektive nach dem zeiterfassung_app-Lauf: dieselbe Fehlerklasse (fehlendes
            # lokales Modul/Paket, z.B. `app/routers/`) wurde hier vom LLM-Reviewer als Freitext-
            # Befund gemeldet UND wenig später vom rein statischen Vorab-Import-Check in
            # _run_verification_loop erneut gefunden - zwei getrennte, unkoordinierte Fix-Budgets
            # für denselben Defekt. Reichert den Freitext-Befund hier zusätzlich um die exakte,
            # dateigenaue Fundliste des statischen Checks an (Datei:Zeile + erwarteter Pfad statt
            # nur Prosa) - derselbe check_completeness()-Aufruf wie beim Vorab-Import-Check, hier
            # nur zusätzlich in den Fix-Prompt gemischt, läuft rein lokal (Millisekunden, kein
            # LLM-Aufruf) und kostet daher kein zusätzliches Budget.
            # Team-Optimierung (vollständige Umsetzung einer KI-Team-Retrospektive, echter Fund
            # am event_relay-Lauf 2026-09-06): dieser Filter nutzte bisher dieselbe fragile
            # Substring-Suche `"existierendes lokales" in message` wie der Vorab-Import-Check
            # unten - core/verifier/models.py.CompletenessIssue.kind ersetzt das durch ein
            # stabiles, maschinenlesbares Tag (siehe dessen Docstring für den vollen Kontext,
            # inkl. des `resilience`-Imports, den die alte Substring-Suche verpasste).
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

            # Proaktives Pro-Task-Budget (Punkt 2 einer Team-Retrospektive): ein einzelner
            # ausufernder Fix-Task konnte bisher unbemerkt einen unverhältnismäßig großen Teil
            # des GESAMTEN Lauf-Budgets verbrauchen, bevor spätere Fachbereiche überhaupt an der
            # Reihe waren. Kein Abbruch mitten im laufenden Aufruf (technisch nicht sauber
            # möglich), aber ein klares Warnsignal, das WEITERE Versuche für denselben Befund in
            # dieser Schleife stoppt, statt ungebremst weiterzueskalieren.
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
                # Verpflichtender Re-Review nach dem letzten Fix-Dispatch (Punkt 4 einer
                # Team-Retrospektive): bisher wurde der Fix im letzten erlaubten Versuch NIE mehr
                # gegengeprüft (nur Zwischen-Versuche liefen in eine erneute Runde mit Recheck
                # oben) - ein Fix im finalen Versuch galt damit unbesehen als erledigt, selbst bei
                # sicherheitskritischen Befunden. Ein einzelner, günstiger Nur-Lese-Recheck
                # derselben Rollen schließt diese Lücke; bleibt der Befund bestehen, wird ein
                # Backlog-Ticket für menschliche Prüfung eröffnet statt stillschweigend zu
                # akzeptieren.
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
                # Team-Optimierung (vollständige Umsetzung einer KI-Team-Retrospektive, echter
                # Fund am event_relay-Lauf 2026-09-06): der Re-Review oben verlässt sich AUSSCHLIESSLICH
                # auf die Einschätzung des LLM-Reviewers - genau das akzeptierte real einen Fix
                # als erledigt ("Resilience-Manager verdrahtet"), der dabei einen frischen,
                # garantierten `ImportError` einführte (`from app.resilience import resilience`,
                # obwohl die globale Instanz im selben Fix entfernt wurde). Der Bruch fiel erst im
                # NÄCHSTEN, unabhängigen Lauf per echtem pytest auf. check_completeness() erkennt
                # genau diese Fund-Klasse bereits rein lokal (kein LLM-Aufruf, keine zusätzlichen
                # Kosten) - läuft deshalb HIER zusätzlich als harte, deterministische Gegenprobe:
                # ein struktureller Neu-Bruch gilt als weiterhin kritisch, UNABHÄNGIG davon, ob
                # der LLM-Re-Review ihn bemerkt hat.
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

                # Team-Optimierung (Fortsetzung der Analyse 2026-09-06, echter Fund am
                # event_relay-Lauf): der `_no_progress()`-Zirkuit-Breaker oben eskaliert nur bei
                # EXAKT WIEDERHOLTEM Befund - real blieb ein Fixversuch beim zweiten Fund derselben
                # Ursache aber eine ANDERE Symptomatik zurück (Versuch 1: "ResilienceManager nicht
                # verdrahtet" → Versuch 2, nach dem Fix: "ImportError: `resilience` keine globale
                # Instanz mehr"), sodass `_no_progress()` NIE griff und der verpflichtende
                # Re-Review hier direkt ein Ticket eröffnete, OHNE je den Fachbereichsleiter mit
                # einer geänderten Strategie zu versuchen - dieselbe Eskalationsleiter wie oben,
                # nur ohne die Modell-Eskalation (die bräuchte einen echten Provider-Client, siehe
                # core/llm_factory.py.LLMFactory.create_for_model() - hier bewusst nicht riskiert,
                # das ist bereits über den Zirkuit-Breaker-Pfad oben abgedeckt).
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
                        # Dieselbe Absicherung wie bei `still_critical_detail` weiter unten - auch
                        # hier darf ein nicht-string-facher Eintrag in `still_critical` nicht mit
                        # einem TypeError abbrechen.
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
                    # Fehleranalyse 2026-09-13: `still_critical` mischt Freitext-Blöcke aus dem
                    # LLM-Re-Review mit den oben angehängten `structural_still_critical`-Strings -
                    # beide sind zwar in der Praxis immer `str`, ein zukünftiger, nicht-string-
                    # facher Eintrag (z.B. ein versehentlich durchgereichtes Exception-Objekt)
                    # riss hier bisher per TypeError in `finding_from_critical_block()` (erwartet
                    # `block: str`) die gesamte Governance-Fix-Schleife mit sich. `str(block)`
                    # statt eines harten Abbruchs bewahrt den Fund wenigstens als Text.
                    still_critical_detail = "\n\n".join(
                        b if isinstance(b, str) else str(b) for b in still_critical
                    ) + self._provider_exhaustion_ticket_note()
                    try:
                        # Team-Optimierung (KI-Team-Zustandsbericht 2026-09-08, echte PR-Review-
                        # Kommentare): dieselben still_critical-Blöcke, die gerade als Fließtext im
                        # Backlog-Ticket landen, werden hier ZUSÄTZLICH in ReviewFinding-Objekte
                        # (mit best-effort extrahiertem file_path) umgewandelt und am Orchestrator
                        # gespeichert - interface/cli.py._ask_for_git_push()/core/backlog_worker.py
                        # lesen dieses Attribut nach einem erfolgreichen create_pull_request() und
                        # hinterlassen echte, dateibezogene GitHub-Review-Kommentare am PR
                        # (agents/github_agent.py.post_pr_review()), statt den Befund nur im PR-Body
                        # zu verstecken, wo ihn ein menschlicher Reviewer leicht überliest.
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
                        # Robustheits-Netz (Fehleranalyse 2026-09-13): Ticket-Erstellung, Lern-
                        # protokoll und externe Benachrichtigung sind Nebenwirkungen der eigentlich
                        # bereits abgeschlossenen Fund-Ermittlung - ein Fehler hier (z.B. ein
                        # defektes Backlog-/Notify-Backend) darf den Governance-Fix-Lauf selbst
                        # nicht mit einer unbehandelten Exception zum Absturz bringen.
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
        Robuste Außenhülle um `_run_permission_blocked_clarification_fix_impl()` (Fehleranalyse
        2026-09-13, analog zu `_run_governance_fix_loop` oben) - garantiert, dass `process()`
        auch bei einem unerwarteten Fehler in dieser Klärungs-Schleife (z.B. beim Ticket- oder
        Lernprotokoll-Zugriff) IMMER ein valides Tupel erhält, statt mit einer durchgereichten
        Exception abzustürzen.
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
        Realer Fund (omnichat-Projekt): der security-Agent identifizierte ein echtes kritisches
        Problem (Pydantic-v2-Migration in `app/schemas.py`, CORS-Härtung in `app/main.py`), hatte
        in diesem Aufruf aber keine Schreibrechte und griff statt zu einem normalen, per
        `find_critical_findings` erkennbaren "Kritisch"-Bericht zu `ask_human_for_clarification`
        mit der Frage "Wie erhalte ich Schreibrechte...?". Diese Frage landete unbeantwortet in
        .ai_team_status.json (open_questions) und wurde NIE an einen schreibberechtigten Agenten
        weitergeroutet - anders als bei _run_governance_fix_loop oben blieb das Problem so über
        beliebig viele Läufe hinweg ungelöst liegen, obwohl der Fund selbst konkret und lösbar
        war. Läuft direkt NACH der Governance-Fix-Schleife (dieselbe Reihenfolge-Logik: vor der
        echten Testverifikation, damit die Testsuite den reparierten Stand prüft) und nutzt
        dieselbe core/review_gate.py.route_findings_to_owners()-Zuordnung wie dort - der
        Fund-Text ist hier die Rückfrage selbst statt eines Review-Abschnitts.

        Gibt (all_results, summary, budget_aborted, manually_cancelled) zurück - summary ist ""
        bei nichts zu tun (kein Rauschen im Normalfall).
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

            # Dasselbe Pro-Task-Budget-Warnsignal wie in _run_governance_fix_loop oben (Punkt 2
            # einer Team-Retrospektive) - auch hier kann ein einzelner Fix-Task ausufern.
            oversized = [r for r in fix_results if MAX_TASK_TOKENS > 0 and r.total_tokens > MAX_TASK_TOKENS]
            if oversized:
                names = ", ".join(sorted({r.agent_id for r in oversized}))
                notify(f"  🚫 [bold red]Pro-Task-Budget überschritten[/bold red] ({names}).")
                summary_lines.append(f"- 🚫 Pro-Task-Budget ({MAX_TASK_TOKENS:,} Tokens) von {names} überschritten.")

            # Behobene Fragen aus dem Abschlussbericht entfernen (open_questions), damit sie nicht
            # trotz erfolgtem Fix als unbeantwortet im Status/PROJECT_STATE.md landen - eine echte
            # fachliche Rückfrage im selben Ergebnis (falls vorhanden) bleibt davon unberührt.
            # `unrouted`-Einträge tragen dasselbe "[agent_id] text"-Format wie
            # route_findings_to_owners() sie selbst erzeugt (core/review_gate.py) - so lässt sich
            # ohne eigene Owner-Neuberechnung feststellen, welche der ursprünglichen Fragen
            # tatsächlich geroutet (= gerade gefixt) statt unrouted geblieben sind.
            unrouted_set = set(unrouted)
            fixed_raiser_ids: set[str] = set()
            for agent_id, q, res in blocked:
                if f"[{agent_id}] {q.strip()}" in unrouted_set:
                    continue
                if q in res.clarification_questions:
                    res.clarification_questions.remove(q)
                    fixed_raiser_ids.add(res.agent_id)

            # Verpflichtender Re-Review (Punkt 4 einer Team-Retrospektive, analog zum finalen
            # Recheck in _run_governance_fix_loop): der ursprünglich blockierte Agent (z.B.
            # security) prüft den nun schreibbaren Fix noch einmal read-only nach, statt den
            # Fix-Dispatch ungeprüft als erledigt zu behandeln - genau die Lücke, die im echten
            # omnichat-Fund dazu führte, dass niemand je bestätigte, ob CORS/Pydantic-v2
            # tatsächlich behoben wurden.
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
                    # Fehleranalyse 2026-09-13 / analog zur Schwester-Stelle in
                    # _run_governance_fix_loop_impl() oben: `str(block)` statt eines harten
                    # TypeError-Abbruchs, falls `still_critical` je einen Nicht-String enthält.
                    still_critical_detail = "\n\n".join(
                        b if isinstance(b, str) else str(b) for b in still_critical
                    ) + self._provider_exhaustion_ticket_note()
                    try:
                        # Team-Optimierung (KI-Team-Zustandsbericht 2026-09-08, echte PR-Review-
                        # Kommentare) - siehe die ausführliche Begründung bei der Schwester-Stelle in
                        # _run_governance_fix_loop_impl() oben.
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
                        # Robustheits-Netz (Fehleranalyse 2026-09-13): siehe Begründung bei der
                        # Schwester-Stelle in _run_governance_fix_loop_impl() oben.
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
        Realer Fund (incidentpilot-Projekt): der tester-Agent stellte eine echte fachliche
        Scope-Rückfrage ("Soll ich die Grundstruktur der Anwendung ... von Grund auf neu
        erstellen, da ich kein 'app/'-Verzeichnis sehe?") statt sie autonom zu beantworten und
        weiterzuarbeiten. Anders als eine Schreibrechte-Rückfrage (siehe
        _run_permission_blocked_clarification_fix oben) passt hier KEIN Muster von
        find_permission_blocked_questions() - die Frage blieb deshalb unbeantwortet in
        .ai_team_status.json (open_questions) stehen, und der Lauf endete mit
        verification_ok=False, OHNE dass die eigentliche Kernfunktion je gebaut wurde, obwohl
        Architektur/ADRs/OpenAPI-Spezifikation für das Projekt bereits vollständig vorlagen.

        Das Team hat keinen anwesenden Menschen, der eine solche Rückfrage in Echtzeit
        beantworten könnte - der einzig sinnvolle Default ist, dass der fragende Agent selbst
        die naheliegendste Annahme trifft (z.B. "ja, lege die fehlende Struktur selbst an") und
        die Aufgabe zu Ende bringt, statt den Lauf unbeantwortet stehen zu lassen. Läuft NACH
        der Schreibrechte-Fix-Schleife (die spezifischere, bereits behandelte Fälle vorher
        herausfiltert), aus demselben Grund wie dort: vor der echten Testverifikation, damit
        die Testsuite den vervollständigten Stand prüft.

        Nutzt bewusst find_structural_scope_questions() (eine enge ALLOWLIST, siehe deren
        Docstring in core/review_gate.py) statt "alles außer Schreibrechte-Fragen" - eine echte
        fachliche Unklarheit, die nur ein Mensch beantworten kann (z.B. "Welche Zahlungsanbieter
        sollen unterstützt werden?"), MUSS weiterhin unangetastet zur Mid-Task-Eskalation an
        einen Menschen führen (core/agent_toolbox.py.ask_human_for_clarification, siehe
        tests/test_clarification_escalation.py) - sonst würde diese Funktion genau die
        Eskalation unterlaufen, die sie eigentlich ergänzen soll.

        Gibt (all_results, summary, budget_aborted, manually_cancelled) zurück - summary ist ""
        bei nichts zu tun (kein Rauschen im Normalfall, in dem gar keine Rückfrage offen ist).
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

        # Je fragendem Agent EINE Sammel-Aufgabe (nicht pro Frage einzeln) - dieselbe Bündelung
        # wie route_findings_to_owners() bei Governance-Funden.
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

        # Beantwortete Rückfragen aus dem ursprünglichen Ergebnis entfernen, damit sie nicht
        # trotz Auto-Entscheid weiterhin als unbeantwortet im Abschlussbericht/PROJECT_STATE.md
        # auftauchen - dieselbe Bereinigung wie in _run_permission_blocked_clarification_fix.
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
