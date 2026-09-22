"""
agents/orchestrator/verification_fix_dispatch.py – VerificationFixDispatchMixin (P6-5,
ROADMAP_TEMP.md): aus agents/orchestrator/verification.py extrahiert, Teil der physischen
Aufteilung des zuvor 2589 Zeilen langen VerificationMixin nach Verantwortlichkeiten.

Enthält die komplette Fix-Dispatch-/Eskalations-Maschinerie der Haupt-Fixschleife: die vier
per continue/break-Signal aus `_run_verification_loop_impl()` extrahierten Blöcke
(`_handle_report_not_ready`, `_handle_test_depth_gate`, `_handle_test_result_or_escalate`,
`_dispatch_fix_and_check_regression`) sowie die zwei Methoden, die diese bei fehlendem
Fortschritt aufrufen (`_run_no_progress_escalation_ladder`, `_second_opinion_fix_round`).

`MAX_VERIFICATION_ITERATIONS`/`upsert_ticket`/`analyze_test_depth` werden NICHT direkt
importiert, sondern über `import agents.orchestrator.verification as _v` gelesen - Testdateien
patchen diese Namen über `@patch("agents.orchestrator.verification.<name>", ...)`. Ein
direkter Import hier würde eine unabhängige Kopie binden, die ein solcher Patch nie träfe
(stiller No-Op statt Importfehler) - siehe core/llm_providers/*.py für dasselbe, bereits
bewährte Muster bei P6-5 Teil 2.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from agents.department_lead_agent import DEPARTMENT_DEFINITIONS
from agents.orchestrator.failure_diagnosis import (
    _failure_fingerprint,
    _format_failures_for_agent,
    _import_name_error_target,
    _issue_signature,
    _no_progress,
    _prior_run_context,
    _record_instance_attribute_learning,
    _record_verification_learning,
    _route_failure_owners,
)
from config import ENABLE_TEST_DEPTH_GATE, HEAVY_MODEL, MIN_ROUTE_TEST_RATIO
from core.code_graph import generate_project_brief
from core.decision_log import log_decision
from core.failure_triage import (
    KIND_MISSING_SYMBOL,
    blocking_failures_first,
    restore_dependency_manifests,
    snapshot_dependency_manifests,
    triage_structural_failure,
)
from core.message_bus import AgentResult, AgentTask
from core.model_capability import model_capability_tier
from core.provider_exhaustion import FAILURE_CLASS_NO_DELIVERY
from core.test_depth import collect_test_function_names, restore_test_files, snapshot_test_files
from core.verification_outcome import VerificationOutcome
from core.verifier import ProjectVerifier, VerificationReport


def _build_project_brief_context(project_dir: str | Path | None) -> str:
    """Erzeugt einen kompakten Projekt-Steckbrief für Fix- und Eskalations-Tasks."""
    if not project_dir:
        return ""
    try:
        brief = generate_project_brief(project_dir)
        return f"[PROJEKT-STECKBRIEF]\n{brief}\n\n" if brief else ""
    except Exception:
        return ""


class VerificationFixDispatchMixin:
    """Fix-Dispatch- und Eskalations-Maschinerie der Haupt-Fixschleife."""

    async def _handle_report_not_ready(
        self,
        *,
        verifier: ProjectVerifier,
        project_dir: str,
        report: VerificationReport,
        attempt: int,
        file_owners: dict[str, str],
        all_results: list[AgentResult],
        summary_lines: list[str],
        notify: Callable[[str], None],
        budget_aborted: bool,
        pip_hint_fix_attempted: bool,
        no_tests_fix_attempted: bool,
    ) -> tuple[str | None, bool, bool]:
        """P6-5 (ROADMAP_TEMP.md): aus der Haupt-Fixschleife (`_run_verification_loop_impl()`)
        extrahiert - behandelt VOR dem eigentlichen Testfehler-Routing zwei Fälle: (1)
        deterministische `pip install`-Hinweise aus der Testausgabe, (2) eine nicht gelaufene
        Testsuite (fehlende Testdatei/fehlender Einstiegspunkt). Eine Methode kann die
        aufrufende `for`-Schleife nicht direkt per `continue`/`break` steuern - deshalb gibt sie
        stattdessen ein Signal zurück (`"continue"`/`"break"`/`None` = normal weiterlaufen, weil
        die Testsuite lief), das der Aufrufer 1:1 in die entsprechende Schleifen-Anweisung
        übersetzt. Ebenso zurückgegeben: die beiden Einmal-Verbrauch-Flags
        (`pip_hint_fix_attempted`/`no_tests_fix_attempted`), da sie über einen einzelnen Aufruf
        dieser Methode hinaus für den Rest des Laufs bestehen bleiben müssen.
        """
        # Deterministisch: explizite "pip install <paket>"-Hinweise aus der Testausgabe (z. B.
        # Starlettes TestClient-Hinweis auf httpx2) einmalig ins passende Manifest eintragen.
        if not report.passed and not pip_hint_fix_attempted and project_dir:
            added = self._apply_pip_install_hints(project_dir, f"{report.stdout}\n{report.stderr}")
            if added:
                pip_hint_fix_attempted = True
                names = ", ".join(f"{pkg} ({manifest})" for pkg, manifest in added)
                notify(f"  📦 [green]Deterministisch ergänzt:[/green] {names} (Hinweis aus der Testausgabe).")
                summary_lines.append(f"- 📦 Versuch {attempt}: {len(added)} Paket(e) aus expliziten pip-Hinweisen ergänzt: {names}.")
                await self._resync_environment_if_dependencies_changed(
                    verifier,
                    [AgentResult(task_id="pip_hint", agent_id="refactoring", agent_name="deterministisch",
                                 success=True, content="", files_written=[m for _, m in added])],
                    notify, summary_lines,
                )
                return "continue", pip_hint_fix_attempted, no_tests_fix_attempted

        if not report.ran:
            if not report.passed:
                # Kein Einstiegspunkt bzw. conftest.py ohne echte Testdatei ist ein eigenständiger
                # Fehlschlag, nicht bloß "nicht geprüft".
                notify(f"  ❌ [bold red]{report.reason_skipped}[/bold red]")
                summary_lines.append(f"- ❌ {report.reason_skipped}")

                # Fehlt nur die Testdatei, bekommt tester denselben EINEN Nachbeauftragungs-Versuch wie
                # bei "keine Tests gefunden". Ein fehlender Einstiegspunkt ist kein Testsuite-Problem
                # und bleibt bewusst unangetastet (Aufgabe für architect/backend).
                if (
                    not no_tests_fix_attempted and not budget_aborted and "tester" in self._agents
                    and ("Testdatei" in report.reason_skipped or "Testsuite" in report.reason_skipped)
                ):
                    no_tests_fix_attempted = True
                    notify(f"  🧪 [yellow]{report.reason_skipped}[/yellow] – beauftrage tester, die fehlende Testsuite nachzuliefern...")
                    summary_lines.append(f"- 🧪 {report.reason_skipped} → tester beauftragt, eine echte Testsuite nachzuliefern.")
                    log_decision(project_dir, "missing_tests_fix_dispatched", report.reason_skipped)
                    fix_task = AgentTask(
                        task_id=f"incomplete_tests_fix_{attempt}",
                        agent_id="tester",
                        description=(
                            "Für dieses Projekt existiert ein tests/-Verzeichnis (z.B. eine "
                            "conftest.py), aber KEINE einzige echte Testdatei (test_*.py/"
                            "*_test.py) - die Testsuite bricht dadurch ab, bevor auch nur ein "
                            "Test läuft, der vorhandene Code bleibt komplett ungeprüft. Schreibe "
                            "jetzt vollständige, lauffähige Testdateien (pytest) für den "
                            f"vorhandenen Code.\n\n{report.reason_skipped}"
                        ),
                        context="", project_dir=project_dir,
                    )
                    fix_results = await self._run_agents_parallel([fix_task], notify=notify)
                    self._update_file_owners(file_owners, fix_results)
                    all_results.extend(fix_results)
                    await self._resync_environment_if_dependencies_changed(verifier, fix_results, notify, summary_lines)
                    return "continue", pip_hint_fix_attempted, no_tests_fix_attempted
                return "break", pip_hint_fix_attempted, no_tests_fix_attempted
            # Bewusst ⚠️ statt ℹ️: "keine Tests gefunden" heißt, Code wird UNGEPRÜFT ausgeliefert.
            # Vor dem Aufgeben wird tester EINMAL gezielt mit einer Testsuite beauftragt.
            if not no_tests_fix_attempted and not budget_aborted and "tester" in self._agents:
                no_tests_fix_attempted = True
                notify(f"  🧪 [yellow]{report.reason_skipped}[/yellow] – beauftrage tester mit einer echten Testsuite...")
                summary_lines.append(f"- 🧪 {report.reason_skipped} → tester beauftragt, eine echte Testsuite nachzuliefern.")
                log_decision(project_dir, "missing_tests_fix_dispatched", report.reason_skipped)
                fix_task = AgentTask(
                    task_id=f"missing_tests_fix_{attempt}",
                    agent_id="tester",
                    description=(
                        "Für dieses Projekt existiert noch KEINE echte, automatisch ausführbare "
                        "Testsuite (kein test_*.py, kein npm-Testskript gefunden) - der bereits "
                        "geschriebene Code wird dadurch komplett ungeprüft ausgeliefert. Schreibe "
                        "jetzt eine vollständige, lauffähige Testsuite (pytest bzw. das für dieses "
                        "Projekt passende Framework) für den vorhandenen Code."
                    ),
                    context="", project_dir=project_dir,
                )
                fix_results = await self._run_agents_parallel([fix_task], notify=notify)
                self._update_file_owners(file_owners, fix_results)
                all_results.extend(fix_results)
                await self._resync_environment_if_dependencies_changed(verifier, fix_results, notify, summary_lines)
                return "continue", pip_hint_fix_attempted, no_tests_fix_attempted
            notify(f"  ⚠️ [yellow]{report.reason_skipped}[/yellow]")
            summary_lines.append(f"- ⚠️ {report.reason_skipped} Generierter Code wurde NICHT automatisch verifiziert.")
            return "break", pip_hint_fix_attempted, no_tests_fix_attempted
        return None, pip_hint_fix_attempted, no_tests_fix_attempted

    async def _handle_test_depth_gate(
        self,
        *,
        verifier: ProjectVerifier,
        project_dir: str,
        report: VerificationReport,
        attempt: int,
        file_owners: dict[str, str],
        all_results: list[AgentResult],
        summary_lines: list[str],
        notify: Callable[[str], None],
        outcome: VerificationOutcome,
        run_start_tokens: int | None,
        budget_aborted: bool,
        test_depth_fix_attempted: bool,
    ) -> tuple[str | None, VerificationReport, bool, bool]:
        """P6-5 (ROADMAP_TEMP.md): aus der Haupt-Fixschleife extrahiert - der Aufrufer betritt
        diesen Block nur, wenn `report.passed and ENABLE_TEST_DEPTH_GATE`. Gibt wie
        `_handle_report_not_ready()` ein Kontrollfluss-Signal zurück, PLUS den ggf. neu
        gelaufenen `report` und `verification_ok` (dieser Block ist der einzige neben dem
        finalen Testlauf, der bei erfolgreicher Nachbesserung direkt `verification_ok = True`
        setzt UND per `break` verlässt), PLUS das Einmal-Verbrauch-Flag
        `test_depth_fix_attempted`.
        """
        import agents.orchestrator.verification as _v
        verification_ok = False
        depth = await asyncio.to_thread(_v.analyze_test_depth, project_dir, MIN_ROUTE_TEST_RATIO)
        if depth.applicable:
            outcome.record("test_depth", depth.passed, "" if depth.passed else depth.format_summary())
        can_fix_depth = (
            not depth.passed and not test_depth_fix_attempted and not budget_aborted
            and "tester" in self._agents
            and not (run_start_tokens is not None and self._run_budget_exceeded(run_start_tokens))
        )
        if can_fix_depth:
            test_depth_fix_attempted = True
            notify(f"  🧪 [yellow]Tests grün, aber zu flach:[/yellow] {depth.format_summary()[:300]}")
            summary_lines.append(f"- 🧪 ⚠️ {depth.format_summary()} → tester ergänzt Tests.")
            log_decision(project_dir, "test_depth_fix_dispatched", depth.format_summary()[:500])
            fix_task = AgentTask(
                task_id=f"test_depth_fix_{attempt}",
                agent_id="tester",
                description=(
                    "Die Testsuite ist grün, prüft aber zu wenig: folgende API-Routen werden in keinem Test "
                    "aufgerufen. Ergänze für JEDE dieser Routen mindestens einen echten Test (Erfolgsfall und "
                    "einen Fehler-/Validierungsfall) mit dem Test-Client des Frameworks. Ändere keinen "
                    "Produktionscode; fehlt dir eine Information, frage per ask_teammate.\n\n"
                    + "\n".join(f"- {r.label()}" for r in depth.untested_routes[:20])
                ),
                context="", project_dir=project_dir,
            )
            fix_results = await self._run_agents_parallel([fix_task], notify=notify)
            self._update_file_owners(file_owners, fix_results)
            all_results.extend(fix_results)
            await self._resync_environment_if_dependencies_changed(verifier, fix_results, notify, summary_lines)
            if attempt < _v.MAX_VERIFICATION_ITERATIONS:
                return "continue", report, verification_ok, test_depth_fix_attempted
            # Realer Fund (pipeline_pilot, 2026-09-16): Tests wurden erst im letzten
            # erlaubten Versuch grün, wodurch für die Testtiefen-Nachbesserung kein
            # weiterer Schleifendurchlauf mehr übrig war - ein `continue` hätte die
            # Schleife verlassen, OHNE den gerade beauftragten Fix je gegen die
            # Testsuite zu prüfen. Deshalb hier einmalig inline nachverifizieren statt
            # auf einen nicht mehr vorhandenen nächsten Durchlauf zu setzen.
            notify("  🔍 [yellow]Letzter Versuch bereits verbraucht:[/yellow] verifiziere die ergänzten Tests direkt inline...")
            depth_fix_report = await self._run_tests_logged(verifier, "test_depth_fix")
            report = depth_fix_report
            if depth_fix_report.passed:
                redepth = await asyncio.to_thread(_v.analyze_test_depth, project_dir, MIN_ROUTE_TEST_RATIO)
                if redepth.applicable:
                    outcome.record("test_depth", redepth.passed, "" if redepth.passed else redepth.format_summary())
                    icon = "✅" if redepth.passed else "⚠️"
                    summary_lines.append(f"- 🧪 {icon} {redepth.format_summary()}")
                verification_ok = True
                notify(f"  ✅ [bold green]Nachgelieferte Tests bestehen weiterhin.[/bold green] ({depth_fix_report.duration_seconds:.1f}s).")
                summary_lines.append("- ✅ Testtiefen-Nachbesserung inline verifiziert: Testsuite bleibt grün.")
            else:
                notify("  ❌ [bold red]Testtiefen-Nachbesserung hat die Suite gebrochen[/bold red] – letzter Stand wird übernommen.")
                summary_lines.append(f"- ❌ Testtiefen-Nachbesserung hat {len(depth_fix_report.failures)} Testfehler eingeführt – letzter Stand wird übernommen.")
            return "break", report, verification_ok, test_depth_fix_attempted
        if depth.applicable:
            icon = "✅" if depth.passed else "⚠️"
            summary_lines.append(f"- 🧪 {icon} {depth.format_summary()}")
        return None, report, verification_ok, test_depth_fix_attempted

    async def _handle_test_result_or_escalate(
        self,
        *,
        verifier: ProjectVerifier,
        project_dir: str,
        report: VerificationReport,
        attempt: int,
        file_owners: dict[str, str],
        all_results: list[AgentResult],
        summary_lines: list[str],
        notify: Callable[[str], None],
        run_start_tokens: int | None,
        had_prior_test_ticket: bool,
        test_ticket_id: str | None,
        previous_fix_all_no_delivery: bool,
        previous_failure_signature: frozenset[tuple[str, str]] | None,
    ) -> tuple[str | None, VerificationReport, bool, bool, frozenset[tuple[str, str]] | None]:
        """P6-5 (ROADMAP_TEMP.md): dritte Anwendung der continue/break-Signal-Technik auf die
        Haupt-Fixschleife. Deckt den Übergang von einem gelaufenen Testergebnis zum nächsten
        Schritt ab: Erfolg (Ticket schließen, `break`) ODER Fehlschlag mit Kein-Fortschritt-
        Prüfung (Signaturvergleich, Hard-Delivery-Gate-Kurzschluss, ggf. Eskalationsleiter -
        IMMER `break`) ODER echter Fortschritt (Signatur aktualisieren, `None` = normal
        weiterlaufen zum Budget-Check). `previous_failure_signature` ist der einzige Wert hier,
        der über den `None`-Rückgabepfad hinaus für die NÄCHSTE Iteration wichtig ist - er wird
        deshalb wie `previous_fix_all_no_delivery` immer zurückgegeben, unabhängig vom Signal.
        """
        import agents.orchestrator.verification as _v
        if report.passed:
            notify(f"  ✅ [bold green]Alle Tests bestanden[/bold green] (Versuch {attempt}, {report.duration_seconds:.1f}s).")
            summary_lines.append(f"- ✅ Echte Testsuite bestanden nach {attempt} Durchlauf/Durchläufen ({report.duration_seconds:.1f}s).")
            if had_prior_test_ticket and test_ticket_id:
                try:
                    _v.upsert_ticket(
                        ticket_id=test_ticket_id,
                        title=f"Nicht behobener Verifikations-Fehler: {self.last_project_slug}",
                        source="orchestrator", status="done", project_slug=self.last_project_slug,
                        detail="In einem späteren Lauf behoben - die Testsuite ist jetzt grün.",
                    )
                    notify("  🎫 [dim]Ticket für vorherigen Testfehlschlag als gelöst geschlossen.[/dim]")
                except Exception as e:
                    notify(f"  ⚠️ [dim yellow]Ticket konnte nicht geschlossen werden: {e}[/dim yellow]")
            return "break", report, True, previous_fix_all_no_delivery, previous_failure_signature

        notify(f"  ❌ [bold red]{len(report.failures)} Testfehler[/bold red] – ermittle betroffene Agenten aus dem echten Traceback...")

        current_signature = _issue_signature(report.failures, lambda f: (f.test_id, _failure_fingerprint(f.message)))
        # Einmal-Verbrauch: unabhängig vom Ergebnis unten sofort zurückgesetzt, damit ein
        # gesetztes Flag niemals über diese eine Prüfung hinaus nachwirkt (z.B. fälschlich
        # eine spätere, unabhängige Eskalationsrunde beeinflusst).
        skip_retry_no_delivery = previous_fix_all_no_delivery
        previous_fix_all_no_delivery = False
        if skip_retry_no_delivery:
            notify(
                "  🚫 [bold yellow]Vorheriger Fixversuch hat keine einzige Datei gespeichert[/bold yellow] "
                "(Hard Delivery Gate) - ein weiterer Versuch mit demselben Auftrag hätte keine neue "
                "Grundlage, auf der er anders ausfallen könnte. Überspringe die Wiederholung, eskaliere direkt."
            )
            summary_lines.append(
                f"- 🚫 Versuch {attempt}: vorheriger Fixversuch lieferte keine Datei (NO_DELIVERY) - "
                "reguläre Wiederholung übersprungen, direkt eskaliert."
            )
        if _no_progress(previous_failure_signature, current_signature) or skip_retry_no_delivery:
            # P6-5 (ROADMAP_TEMP.md): dieser Block führt IMMER zu einem `break` der Schleife
            # (jeder Pfad darin endet entweder in einem frühen `break` bei Erfolg oder im
            # abschließenden `return` unten) - er kann also nie ein zweites Mal in diesem
            # Lauf betreten werden. Deshalb sicher als eigene Methode extrahierbar: alle
            # Flags/Zwischenwerte, die nur INNERHALB dieses Blocks gelesen/geschrieben
            # werden (escalation_attempted, model_escalation_attempted,
            # second_opinion_attempted, stuck_owners, top_failures,
            # escalated_and_resolved, _heavy_escalation_downgrade_note), müssen die
            # Schleife nie wieder erreichen und leben als lokale Variablen in
            # `_run_no_progress_escalation_ladder()`. Einzige Werte, die zurück in die
            # Schleife müssen: der ggf. neu gelaufene `report` und `verification_ok`.
            report, verification_ok = await self._run_no_progress_escalation_ladder(
                verifier=verifier, project_dir=project_dir, report=report,
                file_owners=file_owners, all_results=all_results, summary_lines=summary_lines,
                notify=notify, attempt=attempt, run_start_tokens=run_start_tokens,
                skip_retry_no_delivery=skip_retry_no_delivery,
                had_prior_test_ticket=had_prior_test_ticket, test_ticket_id=test_ticket_id,
            )
            return "break", report, verification_ok, previous_fix_all_no_delivery, previous_failure_signature
        previous_failure_signature = current_signature
        return None, report, False, previous_fix_all_no_delivery, previous_failure_signature

    async def _dispatch_fix_and_check_regression(
        self,
        *,
        verifier: ProjectVerifier,
        project_dir: str,
        report: VerificationReport,
        attempt: int,
        file_owners: dict[str, str],
        all_results: list[AgentResult],
        summary_lines: list[str],
        notify: Callable[[str], None],
        outcome: VerificationOutcome,
        test_ticket_id: str | None,
        had_prior_test_ticket: bool,
        budget_aborted: bool,
    ) -> tuple[str | None, VerificationReport, bool, bool]:
        """P6-5 (ROADMAP_TEMP.md): vierte und größte Anwendung der continue/break-Signal-Technik
        auf die Haupt-Fixschleife - deckt den eigentlichen Fix-Dispatch-Schritt einer Iteration
        ab: Budget-Gate, Fehler-Routing an die zuständigen Agenten, den Test-Schrumpfungs-
        Wächter (erkennt, ob "tester" den fehlschlagenden Test statt einer echten Korrektur
        gelöscht hat) und - nur im letzten erlaubten Versuch - die Abschlussprüfung samt
        Ticket-Pflege. `verification_ok` wird bewusst NICHT als Parameter angenommen: an dieser
        Stelle in der Schleife ist es (siehe `_handle_test_result_or_escalate()`s Rückgabe von
        `False` auf dem hierher führenden Pfad) immer bereits `False` - die Methode gibt einfach
        ihren eigenen, lokal berechneten Wert zurück, der den Aufrufer exakt genauso überschreibt
        wie das inline vorher tat.
        """
        import agents.orchestrator.verification as _v
        verification_ok = False
        if budget_aborted:
            notify("  🚫 [bold red]Budget erreicht[/bold red] – kein neuer Fix-Auftrag mehr, letzter Teststand wird übernommen.")
            summary_lines.append(
                f"- 🚫 Budget erreicht – Verifikation nach Versuch {attempt} mit "
                f"{len(report.failures)} verbleibendem/n Testfehler(n) abgebrochen, ohne einen weiteren "
                "(tokenkostenden) Fix-Agenten zu beauftragen."
            )
            return "break", report, verification_ok, False

        agents_to_fix: dict[str, list] = {}
        tester_participated = any(r.agent_id == "tester" for r in all_results)
        # Collection-/Syntaxfehler blockieren die gesamte Suite - alle übrigen Fehlschläge sind
        # bis dahin Folgefehler bzw. nicht aussagekräftig und werden erst danach bearbeitet.
        dispatch_failures = blocking_failures_first(report.failures)
        if len(dispatch_failures) < len(report.failures):
            notify(
                f"  🧱 [yellow]{len(dispatch_failures)} Collection-/Syntaxfehler blockieren die Testsuite[/yellow] – "
                f"{len(report.failures) - len(dispatch_failures)} weitere Fehlschläge folgen erst danach."
            )
        triages = {
            id(f): triage_structural_failure(f.message, f.files, file_owners, project_dir) for f in dispatch_failures
        }
        for failure in dispatch_failures:
            triage = triages[id(failure)]
            # Persistentes Lernen für künftige Läufe - außerhalb der seiteneffektfreien Routing-
            # Funktion. Bei Schnittstellen-Drift liegt der Fehler beim Konsumenten, die Backend-
            # Regel wäre dann eine falsche Lektion.
            if _import_name_error_target(failure.message) is not None and (
                triage is None or triage.kind == KIND_MISSING_SYMBOL
            ):
                _record_verification_learning(failure.message)
            _record_instance_attribute_learning(failure.message)
            owners = _route_failure_owners(
                failure.message, failure.files, file_owners, self._agents, tester_participated,
                project_dir=project_dir,
            )
            for owner in owners:
                if owner in self._agents:
                    agents_to_fix.setdefault(owner, []).append(failure)

        if not agents_to_fix:
            notify("  ⚠️ [yellow]Testfehler konnten keinem Agenten eindeutig zugeordnet werden – Auto-Fix abgebrochen.[/yellow]")
            summary_lines.append(f"- ⚠️ Versuch {attempt}: {len(report.failures)} Testfehler blieben ungelöst (keine eindeutige Dateizuordnung im Traceback).")
            return "break", report, verification_ok, False

        fix_brief_ctx = _build_project_brief_context(project_dir)
        fix_tasks = []
        for agent_id, fails in agents_to_fix.items():
            failure_text = _format_failures_for_agent(fails, triages=triages, max_failures=5, max_msg_chars=1200)
            prior_no_delivery = any(
                r.agent_id == agent_id and r.failure_class == FAILURE_CLASS_NO_DELIVERY
                for r in (all_results or [])
            )
            delivery_prompt_hint = (
                "\n\n🚨 ACHTUNG (Hard Delivery Gate): Dein vorheriger Fixversuch hat KEINE Datei gespeichert! "
                "Reine Textantworten ohne Werkzeugaufruf gelten als Totalausfall. Du MUSST jetzt sofort "
                "edit_file oder write_file aufrufen, um die Korrekturen anzuwenden!\n"
                if prior_no_delivery else ""
            )
            fix_tasks.append(AgentTask(
                task_id=f"verify_fix_{agent_id}_{attempt}",
                agent_id=agent_id,
                description=(
                    f"Die ECHTE automatische Testsuite ist fehlgeschlagen (kein Schätzwert, sondern realer "
                    f"pytest/unittest-Output). Nutze read_file, um die betroffene(n) Datei(en) zu prüfen, und "
                    f"edit_file/write_file, um den Fehler zu beheben. Verifiziere deinen Fix danach mit run_tests.\n\n"
                    f"{failure_text}"
                    + delivery_prompt_hint
                    + (_prior_run_context(test_ticket_id) if attempt == 1 and test_ticket_id else "")
                ),
                context=fix_brief_ctx,
                project_dir=project_dir,
                max_tool_iterations=8,
            ))

        notify(f"  🛠️ [bold yellow]Gezielter Auto-Fix:[/bold yellow] Beauftrage {', '.join(agents_to_fix.keys())} (nicht blind alle Dev-Agenten)...")
        # Reine Strukturfehler sind nie durch Manifest-Änderungen zu beheben - Manifeste werden
        # gesichert und nach dem Fix-Schritt zurückgesetzt.
        structural_only = all(triages.get(id(f)) is not None for fails in agents_to_fix.values() for f in fails)
        manifest_snapshot = snapshot_dependency_manifests(project_dir) if project_dir and structural_only else None
        # Test-Schrumpfungs-Wächter (EventForge-Analyse 2026-09-16): erfasst die Testnamen VOR
        # dem Fix-Versuch, damit unten erkennbar ist, ob "tester" den Fehler wirklich behoben
        # oder den fehlschlagenden Test ersatzlos entfernt hat - siehe
        # `core.test_depth.collect_test_function_names()`-Docstring für den realen Fund.
        _tests_before_fix = (
            collect_test_function_names(project_dir) if "tester" in agents_to_fix else None
        )
        # Voller Dateiinhalt (nicht nur Testnamen) VOR dem Fix-Versuch, damit eine erkannte
        # Test-Schrumpfung unten tatsächlich rückgängig gemacht werden kann, statt sie nur
        # zu protokollieren (core.test_depth.snapshot_test_files()).
        _test_files_before_fix = snapshot_test_files(project_dir) if _tests_before_fix is not None else None
        fix_results = await self._run_agents_parallel(fix_tasks, notify=notify)
        # P1-5: gilt nur für DIESEN regulären, per-Rolle-geroutet Fixversuch - eine Eskalation
        # (Fachbereichsleiter/HEAVY_MODEL/Zweitmeinung, jeweils eigene fix_results weiter
        # unten) ist eine ANDERE Strategie, kein Wiederholungsversuch mit demselben Prompt,
        # und soll deshalb weiterhin regulär per Signaturvergleich geprüft werden.
        previous_fix_all_no_delivery = bool(fix_results) and all(
            r.failure_class == FAILURE_CLASS_NO_DELIVERY for r in fix_results
        )
        restored_manifests = (
            restore_dependency_manifests(project_dir, manifest_snapshot) if manifest_snapshot is not None else []
        )
        if restored_manifests:
            notify(f"  ⛔ [yellow]Manifest-Änderungen bei reinem Strukturfehler zurückgesetzt:[/yellow] {', '.join(restored_manifests)}")
            summary_lines.append(
                f"- ⛔ Versuch {attempt}: unnötige Änderungen an {', '.join(restored_manifests)} zurückgesetzt "
                "(Ursache war die Code-Struktur, keine Abhängigkeit)."
            )
        self._update_file_owners(file_owners, fix_results)
        all_results.extend(fix_results)
        # Nur re-syncen, wenn die Manifest-Änderung bestehen blieb.
        if not restored_manifests:
            await self._resync_environment_if_dependencies_changed(verifier, fix_results, notify, summary_lines)
        summary_lines.append(f"- 🛠️ Versuch {attempt}: {len(report.failures)} echte Testfehler → gezielt zur Korrektur an {', '.join(agents_to_fix.keys())} zurückgespielt.")

        # Test-Schrumpfungs-Wächter: fehlten nach dem Fix Testfunktionen, die vorher da waren
        # (und keine gleich große Ersatzmenge dazukam), wurde der Fehler wahrscheinlich durch
        # LÖSCHEN des fehlschlagenden Tests "behoben" statt durch eine echte Korrektur. Das
        # gilt als echter Verifikations-Fund - anders als Lint/SAST blockiert er den Lauf.
        if _tests_before_fix is not None:
            _tests_after_fix = collect_test_function_names(project_dir)
            _tests_lost = _tests_before_fix - _tests_after_fix
            if _tests_lost and len(_tests_after_fix) < len(_tests_before_fix):
                _lost_list = ", ".join(sorted(_tests_lost)[:10])
                notify(
                    f"  🧪 [bold red]Test-Schrumpfung erkannt:[/bold red] {len(_tests_lost)} Testfunktion(en) "
                    f"nach dem Fixversuch verschwunden statt der Fehler behoben: {_lost_list}."
                )
                # Realer Fund (Team-Optimierung 2026-09-17): dieser Zweig protokollierte die
                # Schrumpfung bisher nur (Veto + Ticket), ließ die gelöschten Tests aber
                # gelöscht - der Lauf endete als `blocked`-Ticket ohne echten Fix-Versuch, der
                # das eigentliche Problem (fehlerhafter Anwendungscode) noch angehen konnte.
                # Jetzt: gelöschte Tests werden aus _test_files_before_fix zurückgeholt und
                # EIN weiterer, expliziter Fix-Versuch mit klarem Verbot ("Tests NICHT
                # löschen") wird SOFORT nachgeschoben, inline geprüft (kein verbrauchter
                # `attempt` wie bei der Eskalation oben) - erst wenn auch der scheitert, gilt
                # es als echter, unbehobener Befund.
                _restored_test_files = (
                    restore_test_files(project_dir, _test_files_before_fix)
                    if _test_files_before_fix is not None else []
                )
                _regression_fixed = False
                if _restored_test_files:
                    notify(
                        f"  ↩️ [yellow]{len(_restored_test_files)} Testdatei(en) auf den Stand vor dem "
                        f"Fixversuch zurückgesetzt:[/yellow] {', '.join(sorted(_restored_test_files))}. "
                        "Fordere einen erneuten, echten Fix an..."
                    )
                    _anti_regression_tasks = [
                        AgentTask(
                            task_id=f"{ft.task_id}_no_regression",
                            agent_id=ft.agent_id,
                            description=(
                                "Dein vorheriger Fixversuch hat den fehlschlagenden Test ERSATZLOS GELÖSCHT "
                                "statt den zugrunde liegenden Fehler zu beheben - die Testdatei(en) wurden "
                                "deshalb auf den Stand davor zurückgesetzt. Behebe den echten Fehler im "
                                "Anwendungscode (oder korrigiere eine nachweislich falsche Testerwartung, "
                                "OHNE die Testfunktion zu entfernen). Test NICHT löschen oder überspringen "
                                f"(kein `skip`/`xfail`).\n\n{ft.description}"
                            ),
                            context=fix_brief_ctx, project_dir=project_dir, max_tool_iterations=8,
                        )
                        for ft in fix_tasks
                    ]
                    _anti_regression_results = await self._run_agents_parallel(_anti_regression_tasks, notify=notify)
                    self._update_file_owners(file_owners, _anti_regression_results)
                    all_results.extend(_anti_regression_results)
                    summary_lines.append(
                        f"- ↩️ Versuch {attempt}: Test-Schrumpfung erkannt, {len(_restored_test_files)} "
                        "Testdatei(en) zurückgesetzt und ein erneuter Fix mit explizitem Lösch-Verbot angefordert."
                    )
                    await self._resync_environment_if_dependencies_changed(verifier, _anti_regression_results, notify, summary_lines)
                    _tests_after_retry = collect_test_function_names(project_dir)
                    if not (_tests_before_fix - _tests_after_retry):
                        _retry_report = await self._run_tests_logged(verifier, "nach-test-schrumpfung")
                        if _retry_report.passed:
                            notify("  ✅ [bold green]Erneuter Fix ohne Test-Löschung erfolgreich:[/bold green] Testsuite ist grün.")
                            summary_lines.append("- ✅ Erneuter Fix ohne Test-Löschung behob den Fehler – Testsuite bestanden.")
                            report = _retry_report
                            _regression_fixed = True
                        else:
                            report = _retry_report
                if not _regression_fixed:
                    outcome.record(
                        "test_regression", False,
                        f"{len(_tests_lost)} Test(s) entfernt statt behoben: {_lost_list}",
                    )
                    summary_lines.append(
                        f"- 🧪 ❌ **Verifikations-Veto durch Test-Schrumpfung:** {len(_tests_lost)} Testfunktion(en) "
                        f"entfernt statt den Fehler zu beheben ({_lost_list})"
                        + (" – auch nach zurückgesetzten Tests und erneutem Fix-Versuch weiterhin nicht behoben." if _restored_test_files else ".")
                    )
                    if self.last_project_slug:
                        try:
                            _v.upsert_ticket(
                                ticket_id=f"test-regression-{self.last_project_slug}",
                                title=f"Tests statt Fehler entfernt: {self.last_project_slug}",
                                source="orchestrator", status="blocked", project_slug=self.last_project_slug,
                                detail=f"Versuch {attempt}: {len(_tests_lost)} Testfunktion(en) verschwunden: {_lost_list}"
                                       + (" (Tests zurückgesetzt, erneuter Fix-Versuch ebenfalls erfolglos)" if _restored_test_files else ""),
                            )
                        except Exception as e:
                            notify(f"  ⚠️ [dim yellow]Ticket für Test-Schrumpfung konnte nicht angelegt werden: {e}[/dim yellow]")

        if attempt == _v.MAX_VERIFICATION_ITERATIONS:
            # Die Schleife testet nur am Anfang jedes Versuchs - ohne diese Abschlussprüfung würde
            # der Fix des letzten Versuchs nie gegen die Testsuite geprüft.
            if any(r.files_written for r in fix_results):
                notify("  🔍 [yellow]Abschlussprüfung nach letztem Fixversuch:[/yellow] prüft, ob der Fix tatsächlich griff...")
                post_fix_report = await self._run_tests_logged(verifier, "abschluss")
                if post_fix_report.passed:
                    report = post_fix_report
                    self.last_verification_ok = True
                    verification_ok = True
                    notify(f"  🎉 [bold green]Abschlussprüfung nach Fix erfolgreich: Testsuite ist vollständig grün![/bold green] ({report.duration_seconds:.1f}s).")
                    summary_lines.append("- 🎉 Abschlussprüfung nach letztem Fix erfolgreich: Testsuite ist grün.")
                    if had_prior_test_ticket and test_ticket_id:
                        try:
                            _v.upsert_ticket(
                                ticket_id=test_ticket_id,
                                title=f"Nicht behobener Verifikations-Fehler: {self.last_project_slug}",
                                source="orchestrator", status="done", project_slug=self.last_project_slug,
                                detail="In einem späteren Lauf behoben - die Testsuite ist jetzt grün.",
                            )
                            notify("  🎫 [dim]Ticket für vorherigen Testfehlschlag als gelöst geschlossen.[/dim]")
                        except Exception as e:
                            notify(f"  ⚠️ [dim yellow]Ticket konnte nicht geschlossen werden: {e}[/dim yellow]")
                    # Bug-Fix (EventForge-Analyse 2026-09-16): dieser Abschluss-Erfolgspfad (letzter
                    # Versuch, z.B. HEAVY_MODEL-Eskalation) sprang direkt zum `break` und übersprang
                    # dabei die Testtiefen-Prüfung weiter oben (die nur am SCHLEIFENANFANG steht,
                    # hierher gelangt der Code erst NACH einem `continue`). Ein Projekt mit echten,
                    # aber ungetesteten API-Routen zeigte dadurch in der Definition of Done
                    # fälschlich "applicable: false" (nie gemessen) statt eines echten Befunds -
                    # real beobachtet bei entwickle_eventforge_ein_webhook trotz 6 erkennbarer Routen.
                    if ENABLE_TEST_DEPTH_GATE:
                        depth = await asyncio.to_thread(_v.analyze_test_depth, project_dir, MIN_ROUTE_TEST_RATIO)
                        if depth.applicable:
                            outcome.record("test_depth", depth.passed, "" if depth.passed else depth.format_summary())
                            icon = "✅" if depth.passed else "⚠️"
                            summary_lines.append(f"- 🧪 {icon} {depth.format_summary()}")
                    return "break", report, verification_ok, previous_fix_all_no_delivery
                report = post_fix_report

            notify("  ⚠️ [yellow]Maximale Verifikations-Iterationen erreicht – letzter Stand wird übernommen.[/yellow]")
            summary_lines.append(f"- ⚠️ Nach {_v.MAX_VERIFICATION_ITERATIONS} Versuchen nicht vollständig grün – letzter Stand wurde übernommen.")
            # Ticket schon beim ersten Scheitern in diesem Lauf, nicht erst nach zwei gescheiterten
            # Läufen (has_repeated_failure). Dieselbe Ticket-ID, damit beide Pfade dasselbe Ticket
            # aktualisieren statt Duplikate anzulegen.
            if self.last_project_slug:
                try:
                    _v.upsert_ticket(
                        ticket_id=f"recurring-failure-{self.last_project_slug}",
                        title=f"Nicht behobener Verifikations-Fehler: {self.last_project_slug}",
                        source="orchestrator", status="blocked", project_slug=self.last_project_slug,
                        detail="\n".join(summary_lines).strip()[:300] + self._provider_exhaustion_ticket_note(),
                    )
                except Exception as e:
                    notify(f"  ⚠️ [dim yellow]Ticket für ungelösten Testfehler konnte nicht angelegt werden: {e}[/dim yellow]")

        return None, report, verification_ok, previous_fix_all_no_delivery

    async def _run_no_progress_escalation_ladder(
        self,
        *,
        verifier: ProjectVerifier,
        project_dir: str,
        report: VerificationReport,
        file_owners: dict[str, str],
        all_results: list[AgentResult],
        summary_lines: list[str],
        notify: Callable[[str], None],
        attempt: int,
        run_start_tokens: int | None,
        skip_retry_no_delivery: bool,
        had_prior_test_ticket: bool,
        test_ticket_id: str | None,
    ) -> tuple[VerificationReport, bool]:
        """P6-5 (ROADMAP_TEMP.md): aus `_run_verification_loop_impl()` extrahiert - die
        Eskalationsleiter, die nach identischen Testfehlern zwischen zwei Versuchen (oder einem
        NO_DELIVERY-Fixversuch) greift: Fachbereichsleiter-Eskalation → HEAVY_MODEL-Eskalation →
        Zweitmeinung einer anderen Rolle, danach Aufgabe mit Ticket. Sicher isolierbar, weil
        JEDER Pfad hier die aufrufende Schleife über `break` sofort verlässt (Erfolg an jeder
        Stufe ODER endgültige Aufgabe am Ende) - der Aufrufer betritt diesen Block deshalb
        höchstens einmal pro Lauf. Gibt den ggf. neu gelaufenen `report` und `verification_ok`
        zurück; alle übrigen Zwischenwerte (welche Eskalationsstufe schon versucht wurde,
        `stuck_owners`, `top_failures`, ...) müssen die Schleife nie wieder erreichen und
        bleiben deshalb rein lokal.
        """
        import agents.orchestrator.verification as _v
        escalation_attempted = False
        model_escalation_attempted = False
        second_opinion_attempted = False
        verification_ok = False
        escalated_and_resolved = False
        _heavy_escalation_downgrade_note = ""
        stuck_owners: set = set()
        top_failures = ""
        try:
            if not escalation_attempted and not (
                run_start_tokens is not None and (
                    self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
                )
            ):
                escalation_attempted = True
                tester_participated = any(r.agent_id == "tester" for r in all_results)
                stuck_owners = set()
                for failure in (report.failures or []):
                    routed = _route_failure_owners(
                        failure.message, failure.files, file_owners, self._agents,
                        tester_participated, project_dir=project_dir,
                    )
                    stuck_owners.update(routed)
                    for f in (failure.files or []):
                        if isinstance(f, str) and f in file_owners and file_owners[f] in self._agents:
                            stuck_owners.add(file_owners[f])
                lead_targets = {
                    dept_id for dept_id, defn in DEPARTMENT_DEFINITIONS.items()
                    if stuck_owners & set(defn["members"]) and dept_id in self._dept_leads
                }
                top_failures = _format_failures_for_agent(report.failures or [], max_failures=5, max_msg_chars=1200)
                no_delivery_notice = (
                    "\n\n🚨 HARD DELIVERY GATE HINWEIS: Der vorherige Fixversuch hat keine einzige Datei gespeichert "
                    "(reine Textantwort ohne Tool-Aufruf). Deine Antwort gilt als Totalausfall, wenn du nicht zwingend "
                    "edit_file oder write_file aufrufst, um die Änderungen physisch im Dateisystem zu speichern!"
                    if skip_retry_no_delivery else ""
                )
                if lead_targets:
                    notify(
                        f"  🔀 [bold yellow]Strategiewechsel (Eskalation):[/bold yellow] Derselbe Fehler nach "
                        f"einem wirkungslosen Fixversuch – ziehe Fachbereichsleiter "
                        f"({', '.join(sorted(lead_targets))}) statt derselben Wiederholung hinzu..."
                    )
                    escalation_brief_ctx = _build_project_brief_context(project_dir)
                    escalation_tasks = [
                        AgentTask(
                            task_id=f"verify_escalation_{dept_id}_{attempt}",
                            agent_id=dept_id,
                            description=(
                                "Ein vorheriger, gezielter Fixversuch deines Fachbereichs hat den folgenden "
                                "echten Testfehler NICHT behoben (identisch vor und nach dem Versuch) - "
                                "derselbe Ansatz hat also erkennbar nicht funktioniert. Analysiere das Problem "
                                "aus einer anderen Perspektive (z.B. falsche Grundannahme, fehlende "
                                "Abhängigkeit zwischen Dateien, falscher zuständiger Agent) und weise dein "
                                f"Team mit einer GEÄNDERTEN Strategie an, statt denselben Fix zu wiederholen.\n\n{top_failures}"
                                + no_delivery_notice
                            ),
                            context=escalation_brief_ctx, project_dir=project_dir,
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
                    # Eskalationsergebnis HIER sofort per Testlauf prüfen statt per `continue`: das
                    # würde einen Versuch verbrauchen und im letzten Versuch ohne Meldung/Ticket
                    # enden (siehe tests/test_verification_no_progress_breaker.py).
                    await self._resync_environment_if_dependencies_changed(verifier, fix_results, notify, summary_lines)
                    report = await self._run_tests_logged(verifier, "nach-fixversuch")
                    if report.passed:
                        notify(f"  ✅ [bold green]Eskalation erfolgreich:[/bold green] Alle Tests bestanden (Versuch {attempt}, {report.duration_seconds:.1f}s).")
                        summary_lines.append("- ✅ Eskalation an Fachbereichsleiter behob den Fehler – Testsuite bestanden.")
                        verification_ok = True
                        if had_prior_test_ticket and test_ticket_id:
                            try:
                                _v.upsert_ticket(
                                    ticket_id=test_ticket_id,
                                    title=f"Nicht behobener Verifikations-Fehler: {self.last_project_slug}",
                                    source="orchestrator", status="done", project_slug=self.last_project_slug,
                                    detail="In einem späteren Lauf behoben - die Testsuite ist jetzt grün.",
                                )
                            except Exception as e:
                                notify(f"  ⚠️ [dim yellow]Ticket konnte nicht geschlossen werden: {e}[/dim yellow]")
                        return report, verification_ok
                    escalated_and_resolved = True  # Eskalation lief, aber weiterhin rot - unten normal abbrechen.

                # Letzter Versuch vor dem Aufgeben: dieselben stecken gebliebenen Agenten (nicht die
                # Fachbereichsleiter) bekommen für diesen einen Fix HEAVY_MODEL.
                if not model_escalation_attempted and stuck_owners:
                    model_escalation_attempted = True
                    escalated_agent_ids = self._escalate_agent_models(stuck_owners)
                    # HEAVY_MODEL nachweislich nicht erreichbar: der Versuch würde intern
                    # auf ein SCHWÄCHERES Modell zurückfallen als das, mit dem der Fix
                    # zuvor schon zweimal gescheitert ist - er kann also nichts Neues
                    # bringen und wird übersprungen statt verbrannt. Der Grund gehört
                    # sichtbar ins Protokoll UND ins Ticket, sonst liest sich das
                    # Ergebnis wie ein Agenten-/Prompt-Problem, obwohl es ein
                    # Infrastruktur-/Kontingent-Befund ist.
                    _blocked_reason = getattr(self, "last_model_escalation_blocked_reason", None)
                    if not escalated_agent_ids and _blocked_reason:
                        notify(
                            f"  ⏭️ [dim yellow]Modell-Eskalation übersprungen:[/dim yellow] "
                            f"{_blocked_reason} - ein Versuch auf derselben oder einer "
                            "schwächeren Stufe kann den Fehler nicht neu angehen."
                        )
                        summary_lines.append(
                            f"- ⏭️ Modell-Eskalation auf HEAVY_MODEL übersprungen: {_blocked_reason}. "
                            "Der Versuch wäre auf derselben oder einer schwächeren Stufe gelaufen "
                            "als die bereits gescheiterten - kein neuer Ansatz, nur Mehrverbrauch."
                        )
                        _heavy_escalation_downgrade_note = (
                            "\n\n⚠️ Hinweis: Die HEAVY_MODEL-Eskalation wurde gar nicht erst "
                            f"versucht, weil die Stufe nicht erreichbar war ({_blocked_reason}). "
                            "Dieses Ticket ist damit eher ein Infrastruktur-/Kontingent- als ein "
                            "Agenten-/Prompt-Befund - ein erneuter Anlauf lohnt erst, wenn die "
                            "Modellstufe wieder verfügbar ist."
                        )
                    if escalated_agent_ids:
                        notify(
                            f"  ⬆️ [bold yellow]Letzter Versuch mit stärkerem Modell:[/bold yellow] "
                            f"{', '.join(sorted(escalated_agent_ids))} laufen für diesen Fix-Auftrag "
                            "auf HEAVY_MODEL, statt direkt aufzugeben."
                        )
                        model_brief_ctx = _build_project_brief_context(project_dir)
                        model_escalation_tasks = [
                            AgentTask(
                                task_id=f"verify_model_escalation_{owner}_{attempt}",
                                agent_id=owner,
                                description=(
                                    "Dein vorheriger, gezielter Fixversuch UND die Eskalation an deinen "
                                    "Fachbereichsleiter haben den folgenden echten Testfehler NICHT behoben - "
                                    "du bekommst jetzt für diesen letzten Versuch ein stärkeres Modell. "
                                    "Analysiere die Grundannahme neu, statt denselben Ansatz ein drittes Mal "
                                    f"zu wiederholen.\n\n{top_failures}"
                                ),
                                context=model_brief_ctx, project_dir=project_dir,
                            )
                            for owner in sorted(escalated_agent_ids)
                        ]
                        fix_results = await self._run_agents_parallel(model_escalation_tasks, notify=notify)
                        self._update_file_owners(file_owners, fix_results)
                        all_results.extend(fix_results)
                        summary_lines.append(
                            f"- ⬆️ Versuch {attempt}: kein Fortschritt auch nach Eskalation an den "
                            f"Fachbereichsleiter → letzter Versuch mit HEAVY_MODEL für "
                            f"{', '.join(sorted(escalated_agent_ids))}."
                        )
                        # Realer Fund (chronoflow-Lauf 20260917_092911): `agent._llm` wird oben
                        # zwar zuverlässig auf HEAVY_MODEL gesetzt, der tatsächliche API-Aufruf
                        # kann aber (Kontingent-Erschöpfung) intern auf ein SCHWÄCHERES Modell
                        # zurückfallen - `model_used` zeigte am Ende `gemini-3.8-flash` statt des
                        # angeforderten `gemini-pro-latest`. Da `tester` (anders als z.B.
                        # `backend`) kein CRITICAL_AGENT_ID ist, griff dafür auch kein
                        # Capability Floor und die spätere Modell-Abstufungs-Anzeige im
                        # Abschlussbericht (core.model_capability.describe_degraded_results()) sah
                        # es nie. Ohne diesen Hinweis liest sich ein spätes "kein Fortschritt trotz
                        # HEAVY_MODEL" wie ein Agenten-/Prompt-Problem, obwohl in Wahrheit nie ein
                        # stärkeres Modell zum Einsatz kam - ein Infrastruktur-, kein Qualitätsfund.
                        _not_actually_heavy = sorted(
                            r.agent_id for r in fix_results
                            if r.agent_id in escalated_agent_ids and r.model_used
                            and model_capability_tier(r.model_used) < model_capability_tier(HEAVY_MODEL)
                        )
                        if _not_actually_heavy:
                            notify(
                                f"  ⚠️ [dim yellow]HEAVY_MODEL für {', '.join(_not_actually_heavy)} nicht "
                                "tatsächlich erreicht (vermutlich Kontingent-Erschöpfung) - der Fix lief "
                                "auf einem schwächeren Modell als angefordert.[/dim yellow]"
                            )
                            summary_lines.append(
                                f"- ⚠️ HEAVY_MODEL-Eskalation für {', '.join(_not_actually_heavy)} griff "
                                "nicht tatsächlich (Kontingent-Erschöpfung o.ä.) - der letzte Versuch lief "
                                "auf einem schwächeren als dem angeforderten Modell."
                            )
                            _heavy_escalation_downgrade_note = (
                                "\n\n⚠️ Hinweis: HEAVY_MODEL-Eskalation für "
                                f"{', '.join(_not_actually_heavy)} erreichte tatsächlich NICHT die "
                                "angeforderte Modellstufe (vermutlich Kontingent-Erschöpfung) - der "
                                "letzte Versuch lief auf einem schwächeren Modell. Dieses Ticket ist "
                                "damit eher ein Infrastruktur-/Kontingent- als ein Agenten-/Prompt-Befund."
                            )
                        await self._resync_environment_if_dependencies_changed(verifier, fix_results, notify, summary_lines)
                        report = await self._run_tests_logged(verifier, "nach-eskalation")
                        if report.passed:
                            notify(f"  ✅ [bold green]Modell-Eskalation erfolgreich:[/bold green] Alle Tests bestanden (Versuch {attempt}, {report.duration_seconds:.1f}s).")
                            summary_lines.append("- ✅ Fix mit HEAVY_MODEL behob den Fehler – Testsuite bestanden.")
                            verification_ok = True
                            if had_prior_test_ticket and test_ticket_id:
                                try:
                                    _v.upsert_ticket(
                                        ticket_id=test_ticket_id,
                                        title=f"Nicht behobener Verifikations-Fehler: {self.last_project_slug}",
                                        source="orchestrator", status="done", project_slug=self.last_project_slug,
                                        detail="In einem späteren Lauf behoben - die Testsuite ist jetzt grün.",
                                    )
                                except Exception as e:
                                    notify(f"  ⚠️ [dim yellow]Ticket konnte nicht geschlossen werden: {e}[/dim yellow]")
                            return report, verification_ok
                        escalated_and_resolved = True  # Auch mit stärkerem Modell weiterhin rot - unten normal abbrechen.

                # Letzte Stufe: Zweitmeinung einer anderen Rolle. Bewusst NACH der
                # Modell-Eskalation, aber unabhängig davon, ob diese überhaupt möglich
                # war - sie ist die einzige Stufe, die ohne stärkere Modellstufe
                # auskommt (siehe _second_opinion_fix_round()).
                if not second_opinion_attempted and stuck_owners and not (
                    run_start_tokens is not None and (
                        self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
                    )
                ):
                    second_opinion_attempted = True
                    _resolved, report = await self._second_opinion_fix_round(
                        verifier=verifier, project_dir=project_dir, stuck_owners=stuck_owners,
                        top_failures=top_failures, attempt=attempt, file_owners=file_owners,
                        all_results=all_results, summary_lines=summary_lines, notify=notify,
                        current_report=report,
                    )
                    if _resolved:
                        verification_ok = True
                        if had_prior_test_ticket and test_ticket_id:
                            try:
                                _v.upsert_ticket(
                                    ticket_id=test_ticket_id,
                                    title=f"Nicht behobener Verifikations-Fehler: {self.last_project_slug}",
                                    source="orchestrator", status="done", project_slug=self.last_project_slug,
                                    detail="In einem späteren Lauf behoben - die Testsuite ist jetzt grün.",
                                )
                            except Exception as e:
                                notify(f"  ⚠️ [dim yellow]Ticket konnte nicht geschlossen werden: {e}[/dim yellow]")
                        return report, verification_ok
                    escalated_and_resolved = True

            notify(
                "  🛑 [bold red]Kein Fortschritt:[/bold red] identische Testfehler wie vor dem letzten "
                f"Fixversuch{' (auch nach Eskalation an den Fachbereichsleiter)' if escalated_and_resolved else ''} "
                "– breche Verifikations-Schleife ab statt unverändert zu wiederholen."
            )
            summary_lines.append(
                f"- 🛑 Versuch {attempt}: dieselben {len(report.failures)} Testfehler wie nach dem vorherigen "
                "Fixversuch (keine Veränderung)" + (" - auch nach Eskalation" if escalated_and_resolved else "") +
                " – Schleife abgebrochen statt einen wirkungslosen weiteren Versuch zu verbrauchen."
            )
            if self.last_project_slug:
                try:
                    _v.upsert_ticket(
                        ticket_id=f"recurring-failure-{self.last_project_slug}",
                        title=f"Nicht behobener Verifikations-Fehler: {self.last_project_slug}",
                        source="orchestrator", status="blocked", project_slug=self.last_project_slug,
                        detail=f"Fixversuch änderte nichts an {len(report.failures)} Testfehler(n) – "
                               "vermutlich falscher/unzureichend instruierter Agent.\n\n" + top_failures
                               + _heavy_escalation_downgrade_note
                               + self._provider_exhaustion_ticket_note(),
                    )
                except Exception as e:
                    notify(f"  ⚠️ [dim yellow]Ticket für ungelösten Testfehler konnte nicht angelegt werden: {e}[/dim yellow]")
        except Exception as e:
            notify(
                f"  ⚠️ [dim yellow]Eskalations-/Ticket-Verarbeitung nach nicht behobenem "
                f"Testfehler fehlgeschlagen (kein Absturz des Laufs): {e}[/dim yellow]"
            )
            summary_lines.append(
                f"- ⚠️ Eskalations-/Ticket-Verarbeitung nach nicht behobenem Testfehler "
                f"fehlgeschlagen, ohne den Lauf abzubrechen: {e}"
            )
        return report, verification_ok

    # Rollen, die eine Zweitmeinung abgeben können: analysieren fremden Code als Kernaufgabe
    # und sind nicht selbst Eigentümer der steckenden Dateien. Reihenfolge ist Priorität.
    _SECOND_OPINION_ROLES = ("code_reviewer", "refactoring", "architect")

    async def _second_opinion_fix_round(
        self, *, verifier, project_dir: str, stuck_owners: set, top_failures: str, attempt: int,
        file_owners: dict, all_results: list, summary_lines: list[str], notify, current_report,
    ):
        """Zweitmeinung einer ANDEREN Rolle, dann ein Fix mit dieser Diagnose im Kontext.

        Letzte Stufe der Eskalationsleiter. Die drei bisherigen Stufen sind (1) derselbe Agent
        mit gezieltem Auftrag, (2) der Fachbereichsleiter mit geänderter Strategie, (3) dieselben
        Agenten auf HEAVY_MODEL. Stufe 2 und 3 haben beide eine Schwäche: der Fachbereichsleiter
        delegiert am Ende wieder an dieselben Teammitglieder, und Stufe 3 setzt voraus, dass eine
        stärkere Modellstufe überhaupt erreichbar ist - genau das war bei `aetherqueue` und
        `eventforge_core` (2026-09-18/19) nicht der Fall, weshalb die Leiter dort faktisch nach
        Stufe 2 endete und acht `recurring-failure-*`-Tickets mit derselben Diagnose entstanden:
        "Fixversuch änderte nichts an N Testfehler(n) - vermutlich falscher/unzureichend
        instruierter Agent."

        Diese Stufe ändert nicht das Modell, sondern den BLICKWINKEL, und ist damit die einzige,
        die auch bei erschöpftem Kontingent noch etwas Neues beitragen kann: eine nicht beteiligte
        Rolle liest den Code READ-ONLY und schreibt eine Diagnose; erst diese Diagnose geht dann
        als Kontext in einen letzten Fix-Auftrag an die eigentlichen Eigentümer. Das entspricht
        dem, was ein echtes Team tut, wenn jemand dreimal an derselben Stelle hängt - es holt
        jemanden dazu, der draufschaut, statt lauter dieselbe Anweisung zu wiederholen.

        Gibt `(resolved, report)` zurück: `report` ist der Teststand NACH dieser Runde (oder
        unverändert `current_report`, wenn die Runde nicht zustande kam).
        """
        reviewer = next(
            (a for a in self._SECOND_OPINION_ROLES if a in self._agents and a not in stuck_owners),
            None,
        )
        if reviewer is None:
            return False, current_report

        notify(
            f"  🧑‍⚖️ [bold yellow]Zweitmeinung:[/bold yellow] {reviewer} analysiert den Fehler "
            "unbeteiligt (read-only), bevor ein letzter Fix versucht wird..."
        )
        diagnosis_results = await self._run_agents_parallel([AgentTask(
            task_id=f"verify_second_opinion_{reviewer}_{attempt}",
            agent_id=reviewer,
            description=(
                "Ein Testfehler ist trotz mehrerer Fixversuche der zuständigen Kollegen "
                f"({', '.join(sorted(stuck_owners))}) unverändert geblieben - derselbe Ansatz "
                "hat erkennbar nicht funktioniert. Du bist an diesem Code bisher NICHT beteiligt "
                "gewesen. Lies die betroffenen Dateien und den Test und stelle eine DIAGNOSE:\n"
                "1. Was ist die tatsächliche Ursache (nicht das Symptom)?\n"
                "2. Welche Grundannahme der bisherigen Fixversuche war falsch?\n"
                "3. Welche konkrete Datei/Funktion muss wie geändert werden?\n\n"
                "Schreibe KEINEN Code und ändere KEINE Datei - liefere nur die Diagnose als "
                f"knappen Text.\n\n{top_failures}"
            ),
            context="", project_dir=project_dir, tools_read_only=True,
        )], notify=notify)
        all_results.extend(diagnosis_results)

        diagnosis = next(
            (r.content.strip() for r in diagnosis_results if r.success and r.content.strip()), "",
        )
        if not diagnosis:
            summary_lines.append(
                f"- 🧑‍⚖️ Versuch {attempt}: Zweitmeinung durch {reviewer} lieferte keine verwertbare Diagnose."
            )
            return False, current_report

        fix_results = await self._run_agents_parallel([
            AgentTask(
                task_id=f"verify_second_opinion_fix_{owner}_{attempt}",
                agent_id=owner,
                description=(
                    "Deine bisherigen Fixversuche haben den Testfehler nicht behoben. Ein "
                    f"unbeteiligter Kollege ({reviewer}) hat den Code daraufhin durchgesehen. "
                    "Setze SEINE Diagnose um, statt deinen bisherigen Ansatz zu wiederholen - "
                    "auch dann, wenn du ihn für falsch hältst; in dem Fall widerlege ihn "
                    "ausdrücklich im Ergebnis, statt ihn stillschweigend zu ignorieren.\n\n"
                    f"=== DIAGNOSE VON {reviewer.upper()} ===\n{diagnosis[:4000]}\n\n"
                    f"=== UNVERÄNDERTER TESTFEHLER ===\n{top_failures}"
                ),
                context="", project_dir=project_dir,
            )
            for owner in sorted(stuck_owners)
        ], notify=notify)
        self._update_file_owners(file_owners, fix_results)
        all_results.extend(fix_results)
        summary_lines.append(
            f"- 🧑‍⚖️ Versuch {attempt}: kein Fortschritt trotz Eskalation → Zweitmeinung durch "
            f"{reviewer} eingeholt und an {', '.join(sorted(stuck_owners))} zur Umsetzung gegeben."
        )

        await self._resync_environment_if_dependencies_changed(verifier, fix_results, notify, summary_lines)
        report = await self._run_tests_logged(verifier, "nach-zweitmeinung")
        if report.passed:
            notify(
                f"  ✅ [bold green]Zweitmeinung erfolgreich:[/bold green] Alle Tests bestanden "
                f"(Versuch {attempt}, {report.duration_seconds:.1f}s)."
            )
            summary_lines.append(
                f"- ✅ Die Zweitmeinung durch {reviewer} behob den Fehler – Testsuite bestanden."
            )
            return True, report
        return False, report

