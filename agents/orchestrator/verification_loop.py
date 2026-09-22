"""
agents/orchestrator/verification_loop.py – VerificationLoopMixin (P6-5, ROADMAP_TEMP.md): aus
agents/orchestrator/verification.py extrahiert, Teil der physischen Aufteilung des zuvor 2589
Zeilen langen VerificationMixin nach Verantwortlichkeiten.

Enthält den zentralen Einstiegspunkt der Verifikation: `_run_verification_loop()` (Fehler-
Abfang-Wrapper) und `_run_verification_loop_impl()` - nach vier Extraktionsrunden (siehe
verification_fix_dispatch.py/verification_completeness.py/verification_post_checks.py) nur
noch reine Orchestrierung: installiert Abhängigkeiten, ruft die Preflight-/Completeness-/
Post-Checks über die jeweiligen Mixin-Methoden auf (Python löst `self.<methode>` über die MRO
der zusammengesetzten `VerificationMixin`-Klasse auf, unabhängig davon, in welcher Mixin-Datei
die Methode tatsächlich definiert ist) und fasst das Endergebnis zusammen.

`ProjectVerifier`/`MAX_VERIFICATION_ITERATIONS`/`MIN_TEST_COVERAGE` werden NICHT direkt
importiert, sondern über `import agents.orchestrator.verification as _v` gelesen -
Testdateien patchen diese Namen über `@patch("agents.orchestrator.verification.<name>", ...)`.
Ein direkter Import hier würde eine unabhängige Kopie binden, die ein solcher Patch nie träfe
(stiller No-Op statt Importfehler) - siehe core/llm_providers/*.py für dasselbe, bereits
bewährte Muster bei P6-5 Teil 2. `ProjectVerifier` wird hier nur EINMAL tatsächlich
KONSTRUIERT (`_v.ProjectVerifier(project_dir)`) - alle anderen Vorkommen des Namens in den
übrigen Mixin-Dateien sind reine Typ-Annotationen (werden bei Funktionsdefinition ausgewertet,
nie zur Laufzeit erneut gelesen) und deshalb dort als normaler Import unkritisch.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from agents.orchestrator.verification_checks import (
    CheckContext,
    reconcile_verification_ok,
    run_informational_checks,
)
from config import (
    ENABLE_COMPLETENESS_CHECK,
    ENABLE_DOMAIN_LOGIC_DEPTH_SIGNAL,
    ENABLE_LOAD_TEST_CHECK,
    ENABLE_SMOKE_TEST_GATE,
    ENABLE_TEST_DEPTH_GATE,
)
from core.backlog_store import get_ticket
from core.message_bus import AgentResult
from core.verification_outcome import VerificationOutcome, parse_install_exit_code
from core.verifier import ProjectVerifier, VerificationReport


class VerificationLoopMixin:
    """Zentraler Einstiegspunkt der echten Test-/Deployment-Verifikations-Schleife."""

    async def _run_tests_logged(self, verifier: ProjectVerifier, phase: str) -> VerificationReport:
        """
        Führt die echte Testsuite aus und schreibt deren ROHE Ausgabe (stdout+stderr) in das
        Verifikations-Log dieses Laufs (core/run_logger.py), da der Bericht nur eine gekürzte
        Zusammenfassung enthält. `phase` unterscheidet Erstlauf und Wiederholungen nach Fixversuchen.
        """
        report = await asyncio.to_thread(verifier.run_tests)
        try:
            run_logger = getattr(self, "_run_logger", None)
            if run_logger is not None:
                run_logger.log_verification_output(
                    step=f"pytest ({phase})",
                    exit_code=report.exit_code,
                    output=(report.stdout or "") + (
                        f"\n--- stderr ---\n{report.stderr}" if report.stderr else ""
                    ),
                )
        except Exception as e:
            # Sichtbar statt verschluckt: ohne Rohausgabe ist ein roter Lauf nicht diagnostizierbar.
            logging.getLogger("agents.orchestrator.verification").warning(
                "Testausgabe (%s) konnte nicht ins Verifikations-Log geschrieben werden: %r", phase, e,
            )
        return report

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
        Robuste Außenhülle um `_run_verification_loop_impl()`: `process()` erwartet IMMER ein
        valides 5er-Tupel `(all_results, summary, budget_aborted, manually_cancelled,
        verification_ok)`, nie eine Exception. `all_results` bleibt bei einem Absturz unverändert;
        `verification_ok=False` macht den unvollständigen Status sichtbar.
        """
        self.last_verification_outcome = VerificationOutcome()
        try:
            return await self._run_verification_loop_impl(
                project_dir, all_results, file_owners, notify,
                run_start_tokens=run_start_tokens, cancel_requested=cancel_requested,
            )
        except Exception as e:
            logging.getLogger("agents.orchestrator.verification").error("Unerwarteter Fehler in _run_verification_loop: %r", e, exc_info=True)
            notify(f"  ⚠️ [bold yellow]Verifikationsschleife wegen unerwarteter Ausnahme abgefangen:[/bold yellow] {e}")
            summary = f"### 🧪 Verifikations-Protokoll\n- ⚠️ Verifikation konnte wegen eines internen Fehlers nicht vollständig abgeschlossen werden: {e}"
            return all_results, summary, False, False, False

    async def _run_verification_loop_impl(
        self,
        project_dir: str,
        all_results: list[AgentResult],
        file_owners: dict[str, str],
        notify: Callable[[str], None],
        run_start_tokens: int | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> tuple[list[AgentResult], str, bool, bool, bool]:
        """
        Installiert Abhängigkeiten isoliert, führt die echte Testsuite aus und schickt bei
        Fehlschlägen einen GEZIELTEN Korrekturauftrag an die laut Traceback betroffenen Agenten.

        Gibt zusätzlich budget_aborted/manually_cancelled zurück (run_start_tokens bzw.
        cancel_requested=None deaktiviert den Mechanismus) sowie verification_ok: True NUR, wenn
        die echte Testsuite gelaufen UND bestanden ist - damit process() keinen unbestätigten
        Lauf als "Fertig" meldet.
        """
        import agents.orchestrator.verification as _v
        verifier = _v.ProjectVerifier(project_dir)
        summary_lines: list[str] = []
        budget_aborted = False
        manually_cancelled = False
        verification_ok = False
        outcome = getattr(self, "last_verification_outcome", None)
        if not isinstance(outcome, VerificationOutcome):
            outcome = VerificationOutcome()
            self.last_verification_outcome = outcome

        # Sicherheits-Übergabe-Checkpoint (department.py, nach der qa_lead-Phase) - siehe
        # IntegrationMixin._run_security_requirements_checkpoint()-Docstring für den realen Fund
        # (EventForge, SSRF-Fix als "Behoben" im Audit dokumentiert, aber nie an app/main.py
        # zurückgespielt). Anders als der reine Team-Board-Hinweis in `_check_team_board_
        # requirements()` (informativ) blockiert eine WEITERHIN unerfüllte Anforderung des
        # security-Agenten hier explizit die Verifikation.
        security_unmet = getattr(self, "_security_unmet_requirements", None) or []
        if security_unmet:
            shown = "; ".join(req for _agent, req in security_unmet[:5])
            outcome.record("security_handoff", False, f"{len(security_unmet)} Anforderung(en): {shown}")
            summary_lines.append(
                f"- 🛡️ ❌ **Verifikations-Veto durch offene Sicherheits-Übergabe:** "
                f"{len(security_unmet)} vom security-Agenten geforderte, weiterhin unerfüllte "
                f"Anforderung(en): {shown}"
            )

        completeness_report = None
        # Bleibt None, wenn die Schleife nie durchläuft (MAX_VERIFICATION_ITERATIONS<=0).
        report: VerificationReport | None = None
        # Höchstens EIN Nachbeauftragungs-Versuch für "keine Tests gefunden" (keine Endlosschleife).
        no_tests_fix_attempted = False
        # Zirkuit-Breaker: identische Testfehler nach einem Fixversuch bedeuten, dass der Agent das
        # Problem nicht lösen kann - sofort abbrechen statt einen weiteren Versuch zu verbrauchen.
        previous_failure_signature: frozenset[tuple[str, str]] | None = None
        # P1-5 (ROADMAP_TEMP.md): "Hard Delivery Gate: Agent hat trotz Korrektur-Hinweis keine
        # einzige Datei gespeichert" (agents/base_agent.py) trägt failure_class=
        # FAILURE_CLASS_NO_DELIVERY - der Agent wurde befragt, hat aber NICHTS geändert. Ein
        # weiterer Versuch mit demselben Prompt hätte strukturell keine neue Grundlage, auf der
        # er anders ausfallen könnte, aber der reine Signaturvergleich (_no_progress() oben)
        # erkennt das erst EINE RUNDE SPÄTER, sobald derselbe Testfehler ein zweites Mal auftritt
        # - eine reale Sitzung fand das zu riskant für eine sofortige Kontrollfluss-Änderung
        # (2026-09-20) und stellte nur die Erkennung (failure_class) bereit. Dieses Flag lässt
        # den bereits bestehenden Eskalationspfad EINE Runde früher greifen, wenn ALLE
        # Fix-Ergebnisse des letzten Versuchs NO_DELIVERY waren - dieselbe Eskalation, die sonst
        # ohnehin nach dem nächsten identischen Fehlschlag ausgelöst würde, kein neuer Pfad.
        previous_fix_all_no_delivery = False
        # escalation_attempted/model_escalation_attempted/second_opinion_attempted/top_failures/
        # stuck_owners: jetzt lokale Variablen in _run_no_progress_escalation_ladder() bzw.
        # _run_completeness_check_loop() (P6-5, ROADMAP_TEMP.md) - die Blöcke, die sie
        # lesen/schreiben, führen IMMER zu einem `break`/Rückgabe, sie müssen also nie über
        # einen einzelnen Aufruf dieser Methode hinaus bestehen bleiben.
        # Cross-Run-Gedächtnis: ein offenes Ticket aus einem früheren Lauf fließt in den ersten
        # Fix-Auftrag ein und wird geschlossen, sobald die Testsuite grün ist.
        test_ticket_id = f"recurring-failure-{self.last_project_slug}" if self.last_project_slug else None
        try:
            had_prior_test_ticket = bool(test_ticket_id and get_ticket(test_ticket_id) is not None)
        except Exception:
            had_prior_test_ticket = False

        # Deterministischer Pre-Flight-Check (ast-basiert, ohne LLM): fehlende __init__.py,
        # Syntaxfehler, nicht deklarierte Abhängigkeiten. Funde werden sofort per Fix-und-Retry mit
        # Owner-Routing und Kein-Fortschritt-Breaker behoben, statt bis zum teuren Testlauf zu warten.
        pf_budget_aborted, pf_manually_cancelled = await self._run_preflight_check_loop(
            project_dir, run_start_tokens, cancel_requested, notify, file_owners, all_results,
            summary_lines, outcome,
        )
        budget_aborted = budget_aborted or pf_budget_aborted
        manually_cancelled = manually_cancelled or pf_manually_cancelled

        notify("🧪 [bold cyan]Verifikation:[/bold cyan] Installiere Abhängigkeiten in isolierter Umgebung...")
        install_log = await asyncio.to_thread(verifier.ensure_environment)
        if install_log:
            # Alle Installationsschritte zeigen: ein fehlgeschlagener requirements-dev-Install stand
            # sonst nur im strukturierten Ergebnis, während das Protokoll die erste (grüne) Zeile zeigte.
            for line in install_log.splitlines():
                if line.strip():
                    notify(f"  📦 {line.strip()}")
                    summary_lines.append(f"- 📦 {line.strip()}")
        install_exit_code = parse_install_exit_code(install_log or "")
        outcome.record(
            "deps_install",
            None if install_exit_code is None else install_exit_code == 0,
            f"exit_code={install_exit_code}" if install_exit_code is not None else "",
        )

        # Vorab-Import-Check: fehlende lokale Module/Symbole sind statisch in Millisekunden erkennbar
        # und würden sonst erst nach der teuren Test-/Governance-Kaskade auffallen.
        budget_aborted, manually_cancelled = await self._run_preimport_check_loop(
            project_dir, verifier, run_start_tokens, cancel_requested, notify, file_owners,
            all_results, summary_lines, budget_aborted, manually_cancelled,
        )

        # ── Smoke-Test-Gate: Startet die App überhaupt? ───────────────────────────────────
        #
        # VOR der Testschleife: startet die App nicht, scheitern alle Tests an derselben Ursache und
        # die Fix-Schleife verbrennt Token an Folgefehlern. Deshalb zuerst genau diesen Fehler beheben.
        if ENABLE_SMOKE_TEST_GATE and not (budget_aborted or manually_cancelled):
            smoke_gate_summary = await self._run_smoke_test_gate(
                verifier=verifier, project_dir=project_dir, all_results=all_results,
                file_owners=file_owners, notify=notify,
            )
            summary_lines.extend(smoke_gate_summary)

        test_depth_fix_attempted = False
        pip_hint_fix_attempted = False
        for attempt in range(1, _v.MAX_VERIFICATION_ITERATIONS + 1):
            if cancel_requested and cancel_requested():
                manually_cancelled = True
                notify("  ⏹️ [bold red]Lauf manuell abgebrochen[/bold red] – weitere Verifikations-/Fixversuche werden übersprungen.")
                summary_lines.append(f"- ⏹️ Manuell abgebrochen – Verifikation nach Versuch {attempt - 1} beendet.")
                break

            # Das Budget blockiert nur neue Fix-Agenten, NIE einen lokalen Testlauf (0 LLM-Tokens) - ein
            # bereits geschriebener Fix soll noch kostenlos als grün bestätigt werden können.
            # budget_aborted wird deshalb erst vor dem nächsten Fix-Dispatch ausgewertet.
            if not budget_aborted and run_start_tokens is not None and (
                self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
            ):
                budget_aborted = True
                notify(
                    "  🚫 [bold red]Budget erreicht[/bold red] – keine neuen Fix-Agenten mehr, "
                    "der laufende Bestätigungstest wird aber weiter ausgeführt (kostet 0 Tokens)."
                )
                summary_lines.append(
                    f"- 🚫 {self._budget_exceeded_label(run_start_tokens)} erreicht – ab Versuch {attempt} "
                    "werden keine neuen Fix-Agenten mehr beauftragt, lokale Bestätigungstests laufen weiter."
                )

            notify(f"  🧪 [yellow]Testlauf {attempt}/{_v.MAX_VERIFICATION_ITERATIONS}:[/yellow] Führe echte Tests aus...")
            report = await self._run_tests_logged(verifier, "erstlauf")

            loop_signal, pip_hint_fix_attempted, no_tests_fix_attempted = await self._handle_report_not_ready(
                verifier=verifier, project_dir=project_dir, report=report, attempt=attempt,
                file_owners=file_owners, all_results=all_results, summary_lines=summary_lines,
                notify=notify, budget_aborted=budget_aborted,
                pip_hint_fix_attempted=pip_hint_fix_attempted, no_tests_fix_attempted=no_tests_fix_attempted,
            )
            if loop_signal == "continue":
                continue
            if loop_signal == "break":
                break

            if report.passed and ENABLE_TEST_DEPTH_GATE:
                loop_signal, report, verification_ok, test_depth_fix_attempted = await self._handle_test_depth_gate(
                    verifier=verifier, project_dir=project_dir, report=report, attempt=attempt,
                    file_owners=file_owners, all_results=all_results, summary_lines=summary_lines,
                    notify=notify, outcome=outcome, run_start_tokens=run_start_tokens,
                    budget_aborted=budget_aborted, test_depth_fix_attempted=test_depth_fix_attempted,
                )
                if loop_signal == "continue":
                    continue
                if loop_signal == "break":
                    break

            (
                loop_signal, report, verification_ok, previous_fix_all_no_delivery, previous_failure_signature,
            ) = await self._handle_test_result_or_escalate(
                verifier=verifier, project_dir=project_dir, report=report, attempt=attempt,
                file_owners=file_owners, all_results=all_results, summary_lines=summary_lines,
                notify=notify, run_start_tokens=run_start_tokens,
                had_prior_test_ticket=had_prior_test_ticket, test_ticket_id=test_ticket_id,
                previous_fix_all_no_delivery=previous_fix_all_no_delivery,
                previous_failure_signature=previous_failure_signature,
            )
            if loop_signal == "break":
                break

            (
                loop_signal, report, verification_ok, previous_fix_all_no_delivery,
            ) = await self._dispatch_fix_and_check_regression(
                verifier=verifier, project_dir=project_dir, report=report, attempt=attempt,
                file_owners=file_owners, all_results=all_results, summary_lines=summary_lines,
                notify=notify, outcome=outcome, test_ticket_id=test_ticket_id,
                had_prior_test_ticket=had_prior_test_ticket, budget_aborted=budget_aborted,
            )
            if loop_signal == "break":
                break

        # verification_ok spiegelt hier nur die Kern-Testsuite wider - nachgelagerte Prüfungen setzen
        # es ggf. zurück, ohne das Testergebnis selbst zu verfälschen.
        if report is not None:
            if report.ran or verification_ok:
                outcome.record("tests", verification_ok, "" if verification_ok else f"{len(report.failures)} Testfehler")
            elif not report.passed:
                outcome.record("tests", False, report.reason_skipped or "")
            else:
                outcome.record("tests", None, report.reason_skipped or "keine Tests ausgeführt")

        # Prüft nur die Build-Fähigkeit des Dockerfiles (kein run/push/deploy - die Ziel-Infrastruktur
        # ist unbekannt). Kein Fehler ohne Dockerfile oder ohne lokales Docker.
        if not (budget_aborted or manually_cancelled):
            await self._record_docker_build_check(verifier, outcome, summary_lines, notify)

        # Echter `npm run build` VOR dem Browser-UI-Check: ohne Build würde der Browser-Check rohe
        # Quelldateien (z.B. main.tsx) servieren und einen Build-Fehler als Frontend-Bug melden.
        if not (budget_aborted or manually_cancelled):
            veto = await self._run_frontend_build_check(
                verifier, outcome, summary_lines, notify, file_owners, all_results, project_dir,
            )
            if veto is False:
                verification_ok = False

        # Informative Prüfschritte (Dependency-Audit, SAST, Lizenzen, Lint) aus verification_checks.py;
        # beeinflussen verification_ok nicht. last_lint_*: siehe has_repeated_lint_finding().
        self.last_lint_signature: list[str] = []
        self.last_lint_attempted: bool = False
        if not (budget_aborted or manually_cancelled):
            check_ctx = await run_informational_checks(
                CheckContext(verifier=verifier, outcome=outcome, notify=notify, summary_lines=summary_lines)
            )
            self.last_lint_signature = check_ctx.lint_signature
            self.last_lint_attempted = check_ctx.lint_attempted

        # Vollständigkeits-Check: Stub-/Platzhalter-Code und im README referenzierte, fehlende Dateien.
        # Anders als Lint/SAST blockiert ein Fund verification_ok (nicht erfüllte Anforderung) und
        # löst eine gezielte Fix-Schleife aus.
        if ENABLE_COMPLETENESS_CHECK and not (budget_aborted or manually_cancelled):
            completeness_report, verification_ok, budget_aborted, manually_cancelled = await self._run_completeness_check_loop(
                verifier=verifier, project_dir=project_dir, file_owners=file_owners, all_results=all_results,
                summary_lines=summary_lines, notify=notify, run_start_tokens=run_start_tokens,
                cancel_requested=cancel_requested, verification_ok=verification_ok,
                budget_aborted=budget_aborted, manually_cancelled=manually_cancelled,
            )

        if completeness_report is not None and completeness_report.attempted:
            outcome.record(
                "completeness", bool(completeness_report.passed),
                "" if completeness_report.passed else f"{len(completeness_report.issues)} Fund(e)",
            )

        # Opt-in-Abdeckungsschwelle (MIN_TEST_COVERAGE, Standard 0): Pass/Fail allein sagt nichts
        # über ungetesteten Code. Nur sinnvoll bei gelaufener UND bestandener Testsuite.
        if not (budget_aborted or manually_cancelled) and _v.MIN_TEST_COVERAGE > 0 and report is not None and report.ran and report.passed:
            if await self._check_coverage_threshold(verifier, outcome, summary_lines, notify) is False:
                verification_ok = False

        # Runtime Smoke-Check: Prüft, ob die generierte App tatsächlich hochfährt / antwortet (Tests grün != App startet)
        #
        # Läuft auch bei roter Testsuite (z.B. findet er einen ImportError günstiger als ein späteres
        # Review). `report.ran` bleibt Voraussetzung, da sonst keine Dependency-Installation gesichert ist.
        if not (budget_aborted or manually_cancelled) and report is not None and report.ran:
            sb_aborted, sb_cancelled, sb_veto = await self._run_smoke_check(
                verifier, project_dir, all_results, file_owners, outcome, summary_lines, notify,
                run_start_tokens, cancel_requested,
            )
            budget_aborted = budget_aborted or sb_aborted
            manually_cancelled = manually_cancelled or sb_cancelled
            if sb_veto:
                verification_ok = False

        # Lastentest: führt k6-/Locust-Skripte unter tests/load/ kurz gegen die gestartete App aus.
        # Kein Benchmark, aber fehlgeschlagene Requests unter Last sind eine echte
        # Anforderungsverletzung. Für die meisten Projekte ein No-Op (Skript + Tool nötig).
        if ENABLE_LOAD_TEST_CHECK and not (budget_aborted or manually_cancelled) and report is not None and report.ran and report.passed:
            lb_aborted, lb_cancelled, lb_veto = await self._run_load_test_check(
                verifier, project_dir, all_results, file_owners, outcome, summary_lines, notify,
                run_start_tokens, cancel_requested,
            )
            budget_aborted = budget_aborted or lb_aborted
            manually_cancelled = manually_cancelled or lb_cancelled
            if lb_veto:
                verification_ok = False

        # Browser / Frontend UI-Check: Prüft statische Assets, Rendering und JS-Konsolenfehler.
        # Blockiert verification_ok, da er oft die EINZIGE Instanz ist, die echten Browser-Code
        # ausführt (Unit-Tests mocken Canvas/DOM häufig komplett weg).
        if not (budget_aborted or manually_cancelled):
            br_aborted, br_cancelled, br_veto = await self._run_browser_ui_check(
                verifier, project_dir, all_results, file_owners, outcome, summary_lines, notify,
                run_start_tokens, cancel_requested,
            )
            budget_aborted = budget_aborted or br_aborted
            manually_cancelled = manually_cancelled or br_cancelled
            if br_veto:
                verification_ok = False

        # Accessibility-Check: echter axe-core-Scan (WCAG 2.x) gegen die gerenderte Seite.
        # Rein informativ, beeinflusst verification_ok nicht.
        if not (budget_aborted or manually_cancelled):
            await self._record_accessibility_check(verifier, outcome, summary_lines, notify)

        # Fachlogik-Testtiefe (P4-3, ROADMAP_TEMP.md): ergänzendes, rein informatives Signal
        # zur routenbasierten Testtiefe oben - misst, ob öffentliche Funktionen/Klassen in
        # core/services/domain/logic überhaupt in einem Test vorkommen, nicht nur, ob API-Routen
        # aufgerufen werden (siehe core/test_depth.py.analyze_domain_logic_depth()-Docstring für
        # den realen cachegrid_proxy-Fund, den die Routenmessung allein nicht sehen konnte).
        if not (budget_aborted or manually_cancelled) and ENABLE_DOMAIN_LOGIC_DEPTH_SIGNAL:
            await self._record_domain_logic_depth_check(project_dir, outcome, summary_lines)

        # Blockierende Prüfungen, die FRÜH im Lauf fehlgeschlagen sind, noch einmal messen -
        # siehe _recheck_stale_blocking_checks() für die beiden realen Funde dahinter.
        if not (budget_aborted or manually_cancelled):
            await self._recheck_stale_blocking_checks(project_dir, outcome, summary_lines, notify)

        # Rekonziliert `verification_ok` gegen `outcome` - siehe reconcile_verification_ok()-
        # Docstring (agents/orchestrator/verification_checks.py) für den realen Fund und die
        # Begründung. `None` (weder blockierender Fehlschlag noch bestandene Kern-Testsuite)
        # lässt die bisherige Mitschrift unverändert.
        if not (budget_aborted or manually_cancelled):
            _reconciled_ok = reconcile_verification_ok(
                outcome,
                tests_ran=bool(report is not None and report.ran),
                tests_passed=bool(report is not None and report.passed),
            )
            if _reconciled_ok is not None:
                verification_ok = _reconciled_ok

        # Hat die Kern-Testsuite bestanden und kein nachgelagerter Check verification_ok zurückgesetzt,
        # gilt der Lauf als erfolgreich - auch wenn eine optionale Prüfung danach noch das Budget
        # traf. Sonst meldete run_closed budget_aborted und verification_ok gleichzeitig.
        if verification_ok and budget_aborted:
            summary_lines.append(
                "- ℹ️ Token-Budget nach bestandener Kern-Testsuite erreicht – "
                "nachgelagerte optionale Prüfungen wurden übersprungen, der Lauf gilt "
                "trotzdem als erfolgreich abgeschlossen."
            )
            budget_aborted = False

        verification_summary = "### 🧪 Verifikations-Protokoll (echte Dependency-Installation & Testausführung)\n" + (
            "\n".join(summary_lines) if summary_lines else "- Keine Verifikation durchgeführt."
        )
        return all_results, verification_summary, budget_aborted, manually_cancelled, verification_ok

