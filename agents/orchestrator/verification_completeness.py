"""
agents/orchestrator/verification_completeness.py – VerificationCompletenessMixin (P6-5,
ROADMAP_TEMP.md): aus agents/orchestrator/verification.py extrahiert, Teil der physischen
Aufteilung des zuvor 2589 Zeilen langen VerificationMixin nach Verantwortlichkeiten - dieselbe
Aufteilung, die zuvor bereits für interface/cli.py (P6-5 Teil 1) und core/llm_factory.py
(P6-5 Teil 2) durchgeführt wurde.

Enthält NUR den Vollständigkeits-Check (Stub-/Platzhalter-Code, fehlende README-referenzierte
Dateien) - eine eigenständige, in sich geschlossene Fixschleife mit eigenem
Zirkuit-Breaker-Zustand, siehe _run_completeness_check_loop()-Docstring.

`MAX_VERIFICATION_ITERATIONS` wird hier NICHT direkt importiert, sondern über
`import agents.orchestrator.verification as _v; _v.MAX_VERIFICATION_ITERATIONS` gelesen -
Testdateien patchen diesen Namen über `@patch("agents.orchestrator.verification.
MAX_VERIFICATION_ITERATIONS", ...)`. Ein direkter `from config import MAX_VERIFICATION_
ITERATIONS`-Import hier würde eine unabhängige Kopie binden, die ein solcher Patch nie träfe
(stiller No-Op statt Importfehler) - siehe core/llm_providers/*.py für dasselbe, bereits
bewährte Muster bei P6-5 Teil 2.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from agents.orchestrator.failure_diagnosis import _issue_signature, _no_progress
from core.message_bus import AgentResult, AgentTask
from core.verifier import ProjectVerifier


class VerificationCompletenessMixin:
    """Vollständigkeits-Check-Schleife (Stub-/Platzhalter-Code, fehlende README-Referenzen)."""

    async def _run_completeness_check_loop(
        self,
        *,
        verifier: ProjectVerifier,
        project_dir: str,
        file_owners: dict[str, str],
        all_results: list[AgentResult],
        summary_lines: list[str],
        notify: Callable[[str], None],
        run_start_tokens: int | None,
        cancel_requested: Callable[[], bool] | None,
        verification_ok: bool,
        budget_aborted: bool,
        manually_cancelled: bool,
    ):
        """P6-5 (ROADMAP_TEMP.md): aus `_run_verification_loop_impl()` extrahiert. Anders als
        die beiden vorherigen Extraktionen (`_handle_report_not_ready()`/
        `_handle_test_depth_gate()`, die BLÖCKE innerhalb der Haupt-Fixschleife sind und deshalb
        ein `continue`/`break`-Signal an den Aufrufer zurückgeben müssen) ist der
        Vollständigkeits-Check eine EIGENE, komplett in sich geschlossene `for`-Schleife mit
        eigenem Zirkuit-Breaker-Zustand (`previous_completeness_signature`,
        `completeness_model_escalation_attempted`) - sie kann deshalb als Ganzes verschoben
        werden und ihr `continue`/`break` bleibt intern, ohne Übersetzung nötig.
        """
        import agents.orchestrator.verification as _v
        max_iterations = _v.MAX_VERIFICATION_ITERATIONS

        # Zirkuit-Breaker wie in den übrigen Fix-Schleifen.
        previous_completeness_signature: frozenset[tuple[str, str]] | None = None
        # Team-Optimierung 2026-09-17 (hyperion_metrics-Root-Cause "Backend-Agent
        # remediierte den Completeness-Befund im Fix-Zyklus nicht"): anders als die
        # Test-Fehlerschleife oben (siehe stuck_owners/_escalate_agent_models weiter oben in
        # dieser Methode) gab diese Schleife beim ERSTEN identischen Wiederholungsfund sofort
        # auf, ohne je ein stärkeres Modell zu versuchen - derselbe (schwache/falsch
        # instruierte) Agent bekam nie eine zweite Chance mit HEAVY_MODEL, bevor das Veto und
        # das Backlog-Ticket entstanden. Ein Versuch, dann eskalieren, dann erst aufgeben.
        completeness_model_escalation_attempted = False
        completeness_report = None
        for attempt in range(1, max_iterations + 1):
            if cancel_requested and cancel_requested():
                manually_cancelled = True
                notify("  ⏹️ [bold red]Lauf manuell abgebrochen[/bold red] – weitere Vollständigkeits-Fixversuche werden übersprungen.")
                summary_lines.append(f"- ⏹️ Manuell abgebrochen – Vollständigkeits-Check nach Versuch {attempt - 1} beendet.")
                break

            # Die MESSUNG läuft vor dem Budget-Gate: `check_completeness()` ist ein rein
            # deterministischer AST-/Dateisystem-Check (core/verifier/completeness.py) und
            # kostet KEINE Tokens. Das Gate stand bisher davor, wodurch bei erschöpftem
            # Budget gar nicht erst gemessen wurde - `completeness_report` blieb `None`, die
            # Aufzeichnung unten (`if completeness_report is not None and ... .attempted`)
            # fiel aus, und der Check galt als "nicht gemessen" statt als bestanden oder
            # gerissen. Real beobachtet bei `sentinedge` und `eventforge_core`
            # (2026-09-19): "🚫 Lauf-Budget erreicht – Vollständigkeits-Check nach Versuch 0
            # abgebrochen" - ein Qualitätssignal ging verloren, ohne dass dadurch auch nur
            # ein Token gespart wurde. Budgetpflichtig ist erst der FIX-Versuch weiter
            # unten, der einen echten Agenten-Aufruf kostet.
            completeness_report = await asyncio.to_thread(verifier.check_completeness)
            if not completeness_report.attempted:
                break
            if completeness_report.passed:
                if attempt == 1:
                    notify("  🧩 [bold green]Vollständigkeits-Check:[/bold green] keine Stub-/Platzhalter-Funde, keine fehlenden README-Referenzen.")
                    summary_lines.append("- 🧩 Vollständigkeits-Check: keine Stub-/Platzhalter-Funde, keine fehlenden README-referenzierten Dateien.")
                else:
                    notify(f"  🧩 [bold green]Vollständigkeits-Check nach Fix (Versuch {attempt}) bestanden.[/bold green]")
                    summary_lines.append(f"- 🧩 Vollständigkeits-Check nach {attempt} Durchlauf/Durchläufen bestanden.")
                break

            # Ab hier kostet jeder weitere Schritt einen echten Agenten-Aufruf - erst jetzt
            # greift das Budget-Gate. Der Befund ist zu diesem Zeitpunkt bereits gemessen
            # und wird unten regulär aufgezeichnet, statt als "nicht gemessen" zu verpuffen.
            if run_start_tokens is not None and (
                self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
            ):
                budget_aborted = True
                top_open = "; ".join(
                    f"{i.file_path}:{i.line_number} – {i.message}" for i in completeness_report.issues[:5]
                )
                notify(
                    f"  🚫 [bold red]Budget erreicht[/bold red] – die {len(completeness_report.issues)} "
                    "Vollständigkeits-Fund(e) bleiben ungefixt (Befund wurde aber gemessen)."
                )
                summary_lines.append(
                    f"- 🚫 {self._budget_exceeded_label(run_start_tokens)} erreicht – "
                    f"{len(completeness_report.issues)} Vollständigkeits-Fund(e) gemessen, aber nach "
                    f"Versuch {attempt - 1} kein Fixversuch mehr möglich: {top_open}"
                )
                break

            current_completeness_signature = _issue_signature(
                completeness_report.issues, lambda i: (i.file_path, i.message[:300]),
            )
            if _no_progress(previous_completeness_signature, current_completeness_signature):
                stuck_owners = {
                    owner
                    for issue in completeness_report.issues
                    for owner in [file_owners.get(issue.file_path) or self._infer_owner_from_path(issue.file_path, issue.message)]
                    if owner and owner in self._agents
                }
                if not completeness_model_escalation_attempted and stuck_owners and not (
                    run_start_tokens is not None and (
                        self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
                    )
                ):
                    completeness_model_escalation_attempted = True
                    escalated_agent_ids = self._escalate_agent_models(stuck_owners)
                    if escalated_agent_ids:
                        notify(
                            f"  ⬆️ [bold yellow]Kein Fortschritt bei Vollständigkeits-Fix – letzter Versuch mit "
                            f"stärkerem Modell:[/bold yellow] {', '.join(sorted(escalated_agent_ids))}."
                        )
                        top_issues = "\n".join(
                            f"- {i.file_path}" + (f":{i.line_number}" if i.line_number else "") + f" – {i.message}"
                            for i in completeness_report.issues[:5]
                        )
                        escalation_tasks = [
                            AgentTask(
                                task_id=f"verify_completeness_model_escalation_{owner}_{attempt}",
                                agent_id=owner,
                                description=(
                                    "Dein vorheriger, gezielter Fixversuch hat den folgenden Vollständigkeits-Befund "
                                    "NICHT wirksam behoben (identisch vor und nach dem Versuch) - du bekommst jetzt "
                                    "für diesen letzten Versuch ein stärkeres Modell. Prüfe genau, ob dein letzter "
                                    "Edit tatsächlich gespeichert wurde und die beanstandete Stelle wirklich "
                                    f"verändert, statt denselben (wirkungslosen) Ansatz zu wiederholen.\n\n{top_issues}"
                                ),
                                context="", project_dir=project_dir,
                            )
                            for owner in sorted(escalated_agent_ids)
                        ]
                        fix_results = await self._run_agents_parallel(escalation_tasks, notify=notify)
                        self._update_file_owners(file_owners, fix_results)
                        all_results.extend(fix_results)
                        summary_lines.append(
                            f"- 🧩 ⬆️ Versuch {attempt}: kein Fortschritt beim vorherigen Fix → letzter Versuch mit "
                            f"HEAVY_MODEL für {', '.join(sorted(escalated_agent_ids))}."
                        )
                        completeness_report = await asyncio.to_thread(verifier.check_completeness)
                        if completeness_report.attempted and completeness_report.passed:
                            notify("  ✅ [bold green]Eskalation erfolgreich:[/bold green] Vollständigkeits-Check nach stärkerem Modell bestanden.")
                            summary_lines.append("- ✅ Eskalation mit stärkerem Modell behob den Vollständigkeits-Befund.")
                            break
                notify("  🛑 [bold red]Kein Fortschritt:[/bold red] identische Vollständigkeits-Funde wie vor dem letzten Fixversuch – breche Schleife ab.")
                summary_lines.append(
                    f"- 🧩 🛑 Versuch {attempt}: dieselben {len(completeness_report.issues)} Vollständigkeits-Fund(e) wie nach "
                    "dem vorherigen Fixversuch (keine Veränderung) – Schleife abgebrochen statt einen wirkungslosen weiteren "
                    "Versuch zu verbrauchen."
                )
                verification_ok = False
                _grund = f"{len(completeness_report.issues)} unveränderte(r) Vollständigkeits-Fund(e) nach Fixversuch (kein Fortschritt)."
                notify(f"  ❌ [bold red]Verifikations-Veto durch Completeness-Check:[/bold red] {_grund}")
                summary_lines.append(f"- ❌ **Verifikations-Veto durch Completeness-Check:** {_grund}")
                break
            previous_completeness_signature = current_completeness_signature

            top = "; ".join(
                f"{i.file_path}" + (f":{i.line_number}" if i.line_number else "") + f" – {i.message}"
                for i in completeness_report.issues[:5]
            )
            if len(completeness_report.issues) > 5:
                top += f" … und {len(completeness_report.issues) - 5} weitere"
            notify(f"  🧩 [bold red]Vollständigkeits-Check: {len(completeness_report.issues)} Fund(e).[/bold red]")
            verification_ok = False
            _grund = f"{len(completeness_report.issues)} Vollständigkeits-Fund(e) (Stub-/Platzhalter-Code oder fehlende README-referenzierte Datei): {top}"
            notify(f"  ❌ [bold red]Verifikations-Veto durch Completeness-Check:[/bold red] {_grund}")
            summary_lines.append(f"- ❌ **Verifikations-Veto durch Completeness-Check:** {_grund}")

            agents_to_fix: dict[str, list] = {}
            for issue in completeness_report.issues:
                owner = file_owners.get(issue.file_path)
                if not owner:
                    owner = self._infer_owner_from_path(issue.file_path, issue.message)
                if owner and owner in self._agents:
                    agents_to_fix.setdefault(owner, []).append(issue)

            if not agents_to_fix:
                summary_lines.append(f"- 🧩 ❌ {len(completeness_report.issues)} Vollständigkeits-Fund(e) blieben ungelöst (keinem Agenten eindeutig zuordenbar): {top}")
                break

            fix_tasks = []
            for agent_id, agent_issues in agents_to_fix.items():
                issue_text = "\n".join(
                    f"- {i.file_path}" + (f":{i.line_number}" if i.line_number else "") + f" – {i.message}"
                    for i in agent_issues
                )
                fix_tasks.append(AgentTask(
                    task_id=f"verify_fix_completeness_{agent_id}_{attempt}",
                    agent_id=agent_id,
                    description=(
                        f"Der Vollständigkeits-Check hat unfertigen Code gefunden: ein Kommentar/Stub "
                        f"beschreibt eine Funktionalität, die NICHT wirklich implementiert ist (z.B. "
                        f"\"Hier würde X erfolgen\"), oder eine im README referenzierte Datei fehlt. "
                        f"Nutze read_file, um die betroffene(n) Stelle(n) zu prüfen, und implementiere "
                        f"die fehlende Funktionalität WIRKLICH (nicht nur den Kommentar entfernen) bzw. "
                        f"lege die fehlende Datei an.\n\n{issue_text}"
                    ),
                    context="",
                    project_dir=project_dir,
                ))

            notify(f"  🛠️ [bold yellow]Gezielter Auto-Fix (Vollständigkeit):[/bold yellow] Beauftrage {', '.join(agents_to_fix.keys())}...")
            fix_results = await self._run_agents_parallel(fix_tasks, notify=notify)
            self._update_file_owners(file_owners, fix_results)
            all_results.extend(fix_results)
            summary_lines.append(f"- 🧩 Versuch {attempt}: {len(completeness_report.issues)} Vollständigkeits-Fund(e) → gezielt zur Korrektur an {', '.join(agents_to_fix.keys())} zurückgespielt: {top}")

            if attempt == max_iterations:
                notify("  ⚠️ [yellow]Maximale Vollständigkeits-Fixversuche erreicht – letzter Stand wird übernommen.[/yellow]")
                summary_lines.append(f"- 🧩 ⚠️ Nach {max_iterations} Versuchen weiterhin Stub-/Platzhalter-Funde – letzter Stand wurde übernommen.")

        return completeness_report, verification_ok, budget_aborted, manually_cancelled
