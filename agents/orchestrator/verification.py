"""
agents/orchestrator/verification.py – VerificationMixin: echte Verifikations-/Fix-Schleife.

_run_verification_loop() installiert Abhängigkeiten isoliert, führt die echte Testsuite aus und
schickt bei Fehlschlägen einen GEZIELTEN Korrekturauftrag an die Agenten, deren Dateien laut
Traceback betroffen sind. Danach laufen die weiteren Checks (Docker-Build, Audits, Lint,
Coverage, Runtime-Smoke, Lastentest, Browser/A11y); Runtime-Smoke, Lastentest und Browser/UI
lösen über _run_runtime_check_with_fix() ebenfalls gezielte Fixes aus.

Die zustandslosen Diagnose-/Routing-Funktionen leben in failure_diagnosis.py (hier re-exportiert),
die Governance-Fix-Schleife in governance.py.
"""

import asyncio
import logging
import re
from collections.abc import Callable
from pathlib import Path

from agents.department_lead_agent import DEPARTMENT_DEFINITIONS
from agents.orchestrator.failure_diagnosis import (
    _diagnose_import_failure,  # noqa: F401 - re-exportiert, siehe tests/test_import_name_error_learning.py
    _diagnose_no_tests_ran,  # noqa: F401 - re-exportiert, siehe tests/test_no_tests_ran_diagnosis.py
    _diagnose_runtime_failure,  # noqa: F401 - re-exportiert, siehe tests/test_runtime_failure_diagnosis.py
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
    HEAVY_MODEL,
    LOAD_TEST_DURATION_SECONDS,
    LOAD_TEST_TIMEOUT_SECONDS,
    MAX_VERIFICATION_ITERATIONS,
    MIN_DOMAIN_LOGIC_TEST_RATIO,
    MIN_ROUTE_TEST_RATIO,
    MIN_TEST_COVERAGE,
)
from core.backlog_store import get_ticket, upsert_ticket
from core.code_graph import generate_project_brief
from core.decision_log import log_decision
from core.dependency_manifest import (
    add_requirement,
    manifest_for_package,
    package_from_finding,
    packages_from_install_hints,
    primary_python_manifest,
)
from core.failure_triage import (
    KIND_MISSING_SYMBOL,
    blocking_failures_first,
    restore_dependency_manifests,
    snapshot_dependency_manifests,
    triage_structural_failure,
)
from core.message_bus import AgentResult, AgentTask
from core.model_capability import model_capability_tier
from core.pre_flight_check import PreFlightIssue, run_pre_flight_check
from core.provider_exhaustion import FAILURE_CLASS_NO_DELIVERY
from core.team_board import unmet_requirements
from core.test_depth import (
    analyze_domain_logic_depth,
    analyze_test_depth,
    collect_test_function_names,
    restore_test_files,
    snapshot_test_files,
)
from core.verification_outcome import VerificationOutcome, parse_install_exit_code
from core.verifier import ProjectVerifier, VerificationReport

# Browser-Fehler mit Backend-Ursache (CORS, 5xx, WebSocket-Handshake, Netzwerkfehler) kann der
# frontend-Agent nicht beheben - sie werden rein textuell erkannt und an backend geroutet.
_BACKEND_CAUSED_BROWSER_ERROR_RE = re.compile(
    r"cors|cross-origin request blocked|"
    r"websocket handshake|'connection' header is missing|"
    r"failed to fetch|networkerror when attempting to fetch|"
    r"err_connection_refused|err_connection_reset|econnrefused|"
    r"\bhttp 5\d\d\b|"
    # Chrome-Statusformat sowie serverseitig fehlende/ablehnende API-Routen (404/405/422 auf /api/...).
    r"status of 5\d\d\b|\b5\d\d \((?:internal server error|bad gateway|service unavailable|gateway timeout)\)|"
    r"/api/\S*\s+(?:404|405|422)\b",
    re.IGNORECASE,
)


def _classify_browser_failure_owner(
    console_errors: list[str], missing_assets: list[str], available_agents: set[str] | dict,
) -> str | None:
    """Ermittelt den zuständigen Agenten für einen fehlgeschlagenen Browser/UI-Check.

    Bevorzugt `backend`, wenn mindestens ein gemeldeter Fehler auf eine Backend-Ursache
    hindeutet (siehe _BACKEND_CAUSED_BROWSER_ERROR_RE) UND ein backend-Agent existiert -
    sonst wie bisher `frontend`, mit `backend` als Fallback, falls kein frontend-Agent
    existiert. Gibt None zurück, wenn keiner der beiden Agenten existiert.
    """
    has_backend_signal = any(
        _BACKEND_CAUSED_BROWSER_ERROR_RE.search(msg) for msg in (*console_errors, *missing_assets)
    )
    if has_backend_signal and "backend" in available_agents:
        return "backend"
    if "frontend" in available_agents:
        return "frontend"
    if "backend" in available_agents:
        return "backend"
    return None


def _build_project_brief_context(project_dir: str | Path | None) -> str:
    """Erzeugt einen kompakten Projekt-Steckbrief für Fix- und Eskalations-Tasks."""
    if not project_dir:
        return ""
    try:
        brief = generate_project_brief(project_dir)
        return f"[PROJEKT-STECKBRIEF]\n{brief}\n\n" if brief else ""
    except Exception:
        return ""


class VerificationMixin:
    """Governance-Fix-Schleife und echte Test-/Deployment-Verifikations-Schleife."""

    async def _run_runtime_check_with_fix(
        self,
        *,
        check_fn: Callable,
        build_fix_task: Callable,
        all_results: list[AgentResult],
        file_owners: dict[str, str],
        notify: Callable[[str], None],
        run_start_tokens: int | None,
        cancel_requested: Callable[[], bool] | None,
        is_attempted: Callable,
        is_passed: Callable,
    ):
        """
        Gezielte Fix-Schleife für Runtime-Smoke-Test, Lastentest und Browser/UI-Check - ohne sie
        bliebe ein kaputtes Projekt über beliebig viele Läufe rot. Die Owner-Ermittlung übergibt
        der Aufrufer, da diese Checks keinen Python-Traceback mit Dateien liefern.

        Gibt (report, all_results, budget_aborted, manually_cancelled) zurück. `report` ist
        das Ergebnis des letzten Check-Laufs (erster Lauf, falls nie gefixt wurde).
        """
        report = await asyncio.to_thread(check_fn)
        budget_aborted = False
        manually_cancelled = False
        if not is_attempted(report) or is_passed(report):
            return report, all_results, budget_aborted, manually_cancelled

        for attempt in range(1, MAX_VERIFICATION_ITERATIONS + 1):
            if run_start_tokens is not None and (
                self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
            ):
                budget_aborted = True
                notify("  🚫 [bold red]Budget erreicht[/bold red] – weitere Fixversuche werden übersprungen.")
                break
            if cancel_requested and cancel_requested():
                manually_cancelled = True
                notify("  ⏹️ [bold red]Lauf manuell abgebrochen[/bold red] – weitere Fixversuche werden übersprungen.")
                break

            fix_task = build_fix_task(report, attempt)
            if fix_task is None:
                # Kein zuständiger Agent ermittelbar - letzter Check-Stand bleibt maßgeblich.
                break

            notify(f"  🛠️ [bold yellow]Gezielter Auto-Fix (Versuch {attempt}):[/bold yellow] Beauftrage {fix_task.agent_id}...")
            fix_results = await self._run_agents_parallel([fix_task], notify=notify)
            self._update_file_owners(file_owners, fix_results)
            all_results.extend(fix_results)

            report = await asyncio.to_thread(check_fn)
            if is_passed(report):
                break
            if attempt == MAX_VERIFICATION_ITERATIONS:
                notify("  ⚠️ [yellow]Maximale Fixversuche erreicht – letzter Check-Stand wird übernommen.[/yellow]")

        return report, all_results, budget_aborted, manually_cancelled

    async def _run_smoke_test_gate(
        self,
        verifier: ProjectVerifier,
        project_dir: str,
        all_results: list[AgentResult],
        file_owners: dict[str, str],
        notify: Callable[[str], None],
    ) -> list[str]:
        """
        Prüft VOR der Testschleife, ob die Anwendung überhaupt startet, und lässt einen
        Startfehler gezielt beheben, bevor Token in eine vollständige Testsuite fließen.
        Gibt die Zeilen für das Verifikations-Protokoll zurück.

        Bewusst höchstens EIN Fixversuch: die reguläre Testschleife sieht einen verbleibenden
        Startfehler erneut und hat ihre eigene Eskalationsleiter.
        """
        summary: list[str] = []
        try:
            report = await asyncio.to_thread(verifier.check_runtime_smoke)
        except Exception as e:
            # Ein Smoke-Test ist eine Zusatzabsicherung - fällt er selbst aus, darf das die
            # reguläre Verifikation nicht verhindern.
            notify(f"  ⚠️ [dim yellow]Smoke-Test-Gate übersprungen ({type(e).__name__}).[/dim yellow]")
            return summary

        if not report.attempted:
            # Kein erkennbarer Einstiegspunkt (z.B. reine Bibliothek) - kein Fehler, nur nicht prüfbar.
            return summary
        if report.passed:
            notify("  ✅ [green]Smoke-Test-Gate:[/green] Die Anwendung startet.")
            summary.append(f"- 🚦 Smoke-Test-Gate bestanden (`{report.entrypoint}` startet).")
            return summary

        fehlertext = (report.output or "").strip()
        notify(
            f"  🚦 [bold red]Smoke-Test-Gate: Die Anwendung startet nicht[/bold red] "
            f"(`{report.entrypoint}`) – behebe das VOR der Testsuite."
        )
        summary.append(
            f"- 🚦 ❌ Smoke-Test-Gate: `{report.entrypoint}` startet nicht – gezielter Fix vor der Testsuite."
        )
        log_decision(project_dir, "smoke_test_gate_failed", fehlertext[:500])

        # Zuständigkeit über die bekannten Datei-Eigentümer bestimmen; ohne Zuordnung übernimmt
        # der backend-Agent, weil ein nicht startender Einstiegspunkt fast immer dort liegt.
        owner = file_owners.get(report.entrypoint or "", "") or "backend"
        if owner not in self._agents:
            owner = "backend"
        if owner not in self._agents:
            return summary

        fix_tasks = [AgentTask(
            task_id=f"smoke-gate-fix-{owner}",
            agent_id=owner,
            description=(
                "🚦 KRITISCH – die Anwendung startet überhaupt nicht. Solange das so ist, ist "
                "jeder Test wertlos, weil ausnahmslos alle Tests an derselben Ursache scheitern.\n\n"
                f"Einstiegspunkt: `{report.entrypoint}`\n"
                f"Art der Anwendung: {report.app_type or 'unbekannt'}\n\n"
                "ECHTE Fehlerausgabe des Startversuchs:\n"
                f"```\n{fehlertext[:3000]}\n```\n\n"
                "Behebe AUSSCHLIESSLICH die Ursache dieses Startfehlers (fehlender Import, "
                "Syntaxfehler, falscher Modulpfad, fehlende Abhängigkeit in requirements.txt, "
                "Konfigurationsfehler beim Start). Schreibe KEINE neuen Features und KEINE Tests. "
                "Prüfe deine Korrektur, indem du den Einstiegspunkt tatsächlich importierst bzw. "
                "startest."
            ),
            context="",
            project_dir=project_dir,
        )]
        fix_results = await self._run_agents_parallel(fix_tasks, notify=notify)
        self._update_file_owners(file_owners, fix_results)
        all_results.extend(fix_results)

        try:
            recheck = await asyncio.to_thread(verifier.check_runtime_smoke)
        except Exception:
            return summary

        if recheck.passed:
            notify("  ✅ [green]Smoke-Test-Gate:[/green] Startfehler behoben – weiter mit der Testsuite.")
            summary.append(f"- 🚦 ✅ Startfehler durch `{owner}` behoben – die Anwendung startet jetzt.")
        else:
            notify(
                "  ⚠️ [yellow]Smoke-Test-Gate: Start weiterhin fehlerhaft – die reguläre "
                "Testschleife übernimmt.[/yellow]"
            )
            summary.append(
                f"- 🚦 ⚠️ Startfehler durch `{owner}` NICHT behoben – die reguläre Testschleife übernimmt."
            )
        return summary

    _DEPENDENCY_MANIFEST_NAMES = frozenset({
        "requirements.txt", "requirements-dev.txt", "requirements_dev.txt", "requirements-test.txt",
        "package.json", "pyproject.toml", "pipfile", "poetry.lock",
    })

    @classmethod
    def _fix_touched_dependency_manifests(cls, fix_results: list[AgentResult]) -> bool:
        """True, wenn ein Fix-Agent (tester, backend, ...) eine Dependency-Datei (requirements.txt,
        package.json, pyproject.toml, ...) neu angelegt oder verändert hat."""
        return any(
            Path(f).name.lower() in cls._DEPENDENCY_MANIFEST_NAMES
            for r in fix_results for f in r.files_written
        )

    @staticmethod
    def _apply_pip_install_hints(project_dir: str, output: str) -> list[tuple[str, str]]:
        """Trägt Pakete aus `pip install <paket>`-Hinweisen ins passende Manifest ein.

        Liefert (Paket, Manifestname) je tatsächlich ergänztem Paket - leer, wenn nichts zu tun war.
        """
        added: list[tuple[str, str]] = []
        for package in packages_from_install_hints(output):
            target = manifest_for_package(Path(project_dir), package, "tests/")
            if target is None:
                continue
            try:
                if add_requirement(target, package):
                    added.append((package, target.name))
            except (ValueError, OSError):
                continue
        return added

    async def _resync_environment_if_dependencies_changed(
        self, verifier: ProjectVerifier, fix_results: list[AgentResult],
        notify: Callable[[str], None], summary_lines: list[str],
    ) -> None:
        """
        Synchronisiert die Umgebung erneut, wenn ein Fix-Agent ein Dependency-Manifest geändert hat -
        sonst liefe der Re-Test gegen die alte venv ohne das neu eingetragene Paket. Bei reinen
        Code-Fixes kein unnötiger pip/npm-Install.
        """
        if not self._fix_touched_dependency_manifests(fix_results):
            return
        notify("  📦 [cyan]Dependency-Manifest durch Fix-Agent geändert:[/cyan] synchronisiere Umgebung erneut vor dem Re-Test...")
        install_log = await asyncio.to_thread(verifier.ensure_environment)
        if install_log:
            notify(f"  📦 {install_log.splitlines()[0]}")
            summary_lines.append(f"- 📦 Umgebung nach Fix-Versuch neu synchronisiert: {install_log.splitlines()[0]}")

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
            logging.getLogger(__name__).warning(
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
            logging.getLogger(__name__).error("Unerwarteter Fehler in _run_verification_loop: %r", e, exc_info=True)
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
        verifier = ProjectVerifier(project_dir)
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

        pre_flight_report = None
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
        # Bei "kein Fortschritt" EIN Eskalationsversuch an den Fachbereichsleiter (andere Perspektive
        # statt exakter Wiederholung) - nicht mehr, damit die Schleife begrenzt bleibt.
        escalation_attempted = False
        # Danach GENAU EINMAL pro Lauf ein letzter Versuch mit HEAVY_MODEL nur für die betroffenen
        # Agenten, statt erst im späteren Backlog-Retry (core/backlog_worker.py) zu eskalieren.
        model_escalation_attempted = False
        # Letzte Stufe der Eskalationsleiter: eine Zweitmeinung einer ANDEREN Rolle - siehe
        # _second_opinion_fix_round(). Greift auch dann, wenn HEAVY_MODEL nicht erreichbar ist,
        # und ist damit die einzige Stufe, die keine stärkere Modellstufe voraussetzt.
        second_opinion_attempted = False
        # Vorinitialisiert: bei MAX_VERIFICATION_ITERATIONS > 2 kann der "kein Fortschritt"-Zweig nach
        # bereits erfolgter Eskalation erneut greifen und top_failures im Ticket-Text referenzieren.
        top_failures = ""
        # Vorinitialisiert: wird das Budget vor der ersten Eskalation überschritten, bliebe stuck_owners
        # sonst ungesetzt und der Modell-Eskalations-Check würde mit NameError crashen.
        stuck_owners: set = set()
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
        previous_preflight_signature: frozenset[tuple[str, str]] | None = None
        for attempt in range(1, MAX_VERIFICATION_ITERATIONS + 1):
            if run_start_tokens is not None and (
                self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
            ):
                budget_aborted = True
                notify("  🚫 [bold red]Budget erreicht[/bold red] – Pre-Flight-Check übersprungen.")
                break
            if cancel_requested and cancel_requested():
                manually_cancelled = True
                notify("  ⏹️ [bold red]Lauf manuell abgebrochen[/bold red] – Pre-Flight-Check übersprungen.")
                break

            try:
                pre_flight_report = await asyncio.to_thread(run_pre_flight_check, project_dir)
            except Exception as e:
                notify(f"  ⚠️ [dim]Pre-Flight-Check übersprungen: {e}[/dim]")
                break
            if pre_flight_report.error:
                notify(f"  ⚠️ [dim]Pre-Flight-Check übersprungen: {pre_flight_report.error}[/dim]")
                break
            if pre_flight_report.passed:
                if attempt > 1:
                    notify(f"  ✨ [bold green]Pre-Flight-Check nach Fix (Versuch {attempt}) bestanden.[/bold green]")
                    summary_lines.append(f"- 🔍 Pre-Flight-Check: nach {attempt} Durchlauf/Durchläufen bestanden.")
                else:
                    notify(f"  ✨ [bold green]Pre-Flight-Check bestanden ({pre_flight_report.files_checked} Dateien geprüft).[/bold green]")
                break

            notify(f"  🔍 [bold yellow]Pre-Flight-Check:[/bold yellow] {len(pre_flight_report.issues)} Problem(e) in {pre_flight_report.files_checked} Dateien gefunden.")
            for issue in pre_flight_report.issues[:3]:
                notify(f"    ⚠️ [{issue.issue_type}] {issue.file}:{issue.line}: {issue.message}")

            current_preflight_signature = _issue_signature(
                pre_flight_report.issues, lambda i: (i.file, i.message[:300])
            )
            if _no_progress(previous_preflight_signature, current_preflight_signature):
                notify("  🛑 [bold red]Kein Fortschritt:[/bold red] identische Pre-Flight-Funde wie vor dem letzten Fixversuch – breche ab, weiter mit der regulären Testsuite.")
                summary_lines.append(
                    f"- 🔍 🛑 Pre-Flight-Check, Versuch {attempt}: dieselben {len(pre_flight_report.issues)} Fund(e) wie nach "
                    "dem vorherigen Fixversuch (keine Veränderung) – Schleife abgebrochen statt einen wirkungslosen "
                    "weiteren Versuch zu verbrauchen."
                )
                break
            previous_preflight_signature = current_preflight_signature

            # Zuständigkeits-Fallback für Funde ohne file_owners-Eintrag, damit sie nicht unbeauftragt
            # liegen bleiben: Struktur/Imports -> project_cleaner, Manifest-Lücken -> refactoring,
            # übrige Code-Probleme -> dev_lead.
            _FALLBACK_OWNER_BY_ISSUE_TYPE = {
                "missing_init": "project_cleaner",
                "hidden_runtime_dependency": "project_cleaner",
                "missing_dependency": "refactoring",
                "syntax_error": "dev_lead",
                # Tests/-Verzeichnis ohne echte Testfunktion: fehlende Testabdeckung, kein Code-Problem.
                "empty_test_suite": "tester",
            }
            # Deterministischer Kurzschluss: ein exakt benanntes fehlendes Paket wird ohne LLM-Agent
            # direkt ins Manifest eingetragen (schneller, keine parallele Überschreibung). Test-/
            # Werkzeugpakete landen in requirements-dev.txt (manifest_for_package).
            remaining_issues = list(pre_flight_report.issues)
            manifest = primary_python_manifest(project_dir) if project_dir else None
            if manifest is not None:
                resolved_by_manifest: dict[str, list[str]] = {}
                still_open: list[PreFlightIssue] = []
                for issue in remaining_issues:
                    package = issue.issue_type == "missing_dependency" and package_from_finding(issue.suggestion)
                    target = manifest_for_package(Path(project_dir), package, issue.file) if package else None
                    if not package or target is None:
                        still_open.append(issue)
                        continue
                    try:
                        add_requirement(target, package)
                        resolved_by_manifest.setdefault(target.name, []).append(package)
                    except (ValueError, OSError):
                        still_open.append(issue)
                for manifest_name, packages in sorted(resolved_by_manifest.items()):
                    names = ", ".join(sorted(set(packages)))
                    notify(f"  📦 [green]Deterministisch ergänzt:[/green] {names} in {manifest_name} (kein LLM-Aufruf nötig).")
                    summary_lines.append(f"- 📦 Versuch {attempt}: {len(packages)} fehlende Paket(e) deterministisch in {manifest_name} ergänzt: {names}.")
                remaining_issues = still_open

            # Rollen, die in dieser Phase keine Code-Patches schreiben (z.B. architect, der nur in
            # Phase 4/5 Verträge/ADRs liefert): file_owners kann so eine Rolle für eine Datei
            # eintragen, die architect initial angelegt hat (z.B. app/main.py-Grundgerüst). Ein
            # Pre-Flight-Fixauftrag an eine solche Rolle bleibt wirkungslos (0 Dateien geschrieben)
            # und lässt den Circuit-Breaker mit dauerhaft negativem pre_flight-Outcome abbrechen -
            # echter Fund `root-cause-cachegrid_proxy-pre-flight-fixversuche-scheitern-durch-
            # ineffektive-agentenzu`. Für solche Owner greift die pfadbasierte Heuristik statt der
            # (nicht code-schreibenden) file_owners-Zuweisung.
            _NON_CODE_WRITING_ROLES = {"architect"}
            agents_to_fix: dict[str, list[PreFlightIssue]] = {}
            for issue in remaining_issues:
                owner = file_owners.get(issue.file)
                if owner in _NON_CODE_WRITING_ROLES:
                    owner = self._infer_owner_from_path(issue.file, issue.message) or owner
                if not owner or owner not in self._agents:
                    owner = _FALLBACK_OWNER_BY_ISSUE_TYPE.get(issue.issue_type, "dev_lead")
                if owner in self._agents:
                    agents_to_fix.setdefault(owner, []).append(issue)

            if not agents_to_fix:
                if not remaining_issues:
                    # Alle Funde deterministisch behoben - direkt erneut prüfen.
                    continue
                summary_lines.append(f"- 🔍 ❌ Pre-Flight-Check: {len(remaining_issues)} Fund(e) blieben ungelöst (keinem Agenten eindeutig zuordenbar).")
                break

            fix_tasks = []
            for agent_id, agent_issues in agents_to_fix.items():
                issue_text = "\n".join(
                    f"- [{i.issue_type}] {i.file}:{i.line} – {i.message}"
                    + (f" Lösung: {i.suggestion}" if i.suggestion else "")
                    for i in agent_issues
                )
                fix_tasks.append(AgentTask(
                    task_id=f"verify_fix_preflight_{agent_id}_{attempt}",
                    agent_id=agent_id,
                    description=(
                        "Ein statischer Pre-Flight-Check (VOR jeder Dependency-Installation und "
                        "jedem Testlauf) hat Probleme gefunden, die einen Testlauf mit hoher "
                        "Wahrscheinlichkeit zum Scheitern bringen. Behebe AUSSCHLIESSLICH diese "
                        "Befunde, erstelle keine neuen Features.\n\n"
                        f"{issue_text}"
                    ),
                    context="", project_dir=project_dir,
                ))

            notify(f"  🛠️ [bold yellow]Gezielter Auto-Fix (Pre-Flight-Check):[/bold yellow] Beauftrage {', '.join(agents_to_fix.keys())}...")
            fix_results = await self._run_agents_parallel(fix_tasks, notify=notify)
            self._update_file_owners(file_owners, fix_results)
            all_results.extend(fix_results)
            summary_lines.append(f"- 🔍 Pre-Flight-Check, Versuch {attempt}: {len(pre_flight_report.issues)} Problem(e) → gezielt zur Korrektur an {', '.join(agents_to_fix.keys())} zurückgespielt.")

            if attempt == MAX_VERIFICATION_ITERATIONS:
                notify("  ⚠️ [yellow]Maximale Pre-Flight-Fixversuche erreicht – weiter mit der regulären Testsuite.[/yellow]")
                summary_lines.append(f"- 🔍 ⚠️ Pre-Flight-Check nach {MAX_VERIFICATION_ITERATIONS} Versuchen weiterhin mit Funden – weiter mit der regulären Testsuite.")

        if pre_flight_report is not None and not pre_flight_report.error:
            outcome.record(
                "pre_flight", pre_flight_report.passed,
                "" if pre_flight_report.passed else f"{len(pre_flight_report.issues)} Fund(e)",
            )

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
        # und würden sonst erst nach der teuren Test-/Governance-Kaskade auffallen. Prüft Import-
        # Funde UND (seit ecotrack_ai-Fund 2026-09-17) unaufgelöste Namen in Einstiegsdateien
        # (`undefined_entrypoint_name`, z.B. ein registrierter, aber nie importierter Router) -
        # beides garantierte NameError/ImportError-Abstürze beim Start, dieselbe Kategorie. Stub-
        # Marker u.ä. bleiben beim späteren vollständigen Durchlauf.
        _PREIMPORT_ISSUE_KINDS = {"missing_local_import", "undefined_entrypoint_name"}
        if ENABLE_COMPLETENESS_CHECK and not (budget_aborted or manually_cancelled):
            # Zirkuit-Breaker wie in den übrigen Fix-Schleifen.
            previous_preimport_signature: frozenset[tuple[str, str]] | None = None
            for attempt in range(1, MAX_VERIFICATION_ITERATIONS + 1):
                if run_start_tokens is not None and (
                    self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
                ):
                    budget_aborted = True
                    notify("  🚫 [bold red]Budget erreicht[/bold red] – Vorab-Import-Check übersprungen.")
                    break
                if cancel_requested and cancel_requested():
                    manually_cancelled = True
                    notify("  ⏹️ [bold red]Lauf manuell abgebrochen[/bold red] – Vorab-Import-Check übersprungen.")
                    break

                pre_report = await asyncio.to_thread(verifier.check_completeness)
                # Erst .attempted/.passed, dann .issues: hält Tests mit komplett gemocktem
                # ProjectVerifier lauffähig (MagicMock().issues wäre nicht iterierbar).
                if not pre_report.attempted or pre_report.passed:
                    break
                # CompletenessIssue.kind ist ein stabiles Tag und erfasst auch fehlende Symbol-Importe,
                # die eine Substring-Suche auf die Meldung verpassen würde.
                import_issues = [i for i in pre_report.issues if i.kind in _PREIMPORT_ISSUE_KINDS]
                if not import_issues:
                    if attempt > 1:
                        notify(f"  🧩 [bold green]Vorab-Import-Check nach Fix (Versuch {attempt}) bestanden.[/bold green]")
                        summary_lines.append(f"- 🧩 Vorab-Import-Check (statisch, vor der Testsuite): nach {attempt} Durchlauf/Durchläufen bestanden.")
                    break

                current_preimport_signature = _issue_signature(import_issues, lambda i: (i.file_path, i.message[:300]))
                if _no_progress(previous_preimport_signature, current_preimport_signature):
                    notify("  🛑 [bold red]Kein Fortschritt:[/bold red] identische Import-Funde wie vor dem letzten Fixversuch – breche Vorab-Import-Check ab, weiter mit der regulären Testsuite.")
                    summary_lines.append(
                        f"- 🧩 🛑 Vorab-Import-Check, Versuch {attempt}: dieselben {len(import_issues)} Fund(e) wie nach dem "
                        "vorherigen Fixversuch (keine Veränderung) – Schleife abgebrochen statt einen wirkungslosen weiteren "
                        "Versuch zu verbrauchen (bleibt im regulären Testlauf danach erneut sichtbar)."
                    )
                    break
                previous_preimport_signature = current_preimport_signature

                top = "; ".join(f"{i.file_path}:{i.line_number} – {i.message}" for i in import_issues[:5])
                notify(f"  🧩 [bold red]Vorab-Import-Check: {len(import_issues)} fehlende(s)/unaufgelöste(s) lokale(s) Modul/Symbol/Name VOR jedem Testlauf gefunden.[/bold red]")

                # Fehlendes lokales Modul/Symbol/unaufgelöster Name ist immer ein Code-Problem - Fallback-Owner dev_lead.
                agents_to_fix: dict[str, list] = {}
                for issue in import_issues:
                    owner = file_owners.get(issue.file_path)
                    if not owner or owner not in self._agents:
                        owner = "dev_lead"
                    if owner in self._agents:
                        agents_to_fix.setdefault(owner, []).append(issue)

                if not agents_to_fix:
                    summary_lines.append(f"- 🧩 ❌ Vorab-Import-Check: {len(import_issues)} Fund(e) blieben ungelöst (keinem Agenten eindeutig zuordenbar): {top}")
                    break

                fix_tasks = []
                for agent_id, agent_issues in agents_to_fix.items():
                    issue_text = "\n".join(f"- {i.file_path}:{i.line_number} – {i.message}" for i in agent_issues)
                    fix_tasks.append(AgentTask(
                        task_id=f"verify_fix_preimport_{agent_id}_{attempt}",
                        agent_id=agent_id,
                        description=(
                            "Ein statischer Vorab-Check (VOR jedem Testlauf) hat lokale Python-Importe "
                            "gefunden, die auf nicht existierende Dateien/Symbole verweisen, oder Namen "
                            "(z.B. ein registrierter Router), die in einer Einstiegsdatei verwendet werden, "
                            "ohne dort importiert/definiert zu sein - der Code kann dadurch nicht einmal "
                            "gestartet werden. Lege die fehlende(n) Datei(en)/Symbol(e) mit echtem Inhalt an "
                            "und importiere sie in der genannten Einstiegsdatei, statt sie nur zu registrieren.\n\n"
                            f"{issue_text}"
                        ),
                        context="",
                        project_dir=project_dir,
                    ))

                notify(f"  🛠️ [bold yellow]Gezielter Auto-Fix (Vorab-Import-Check):[/bold yellow] Beauftrage {', '.join(agents_to_fix.keys())}...")
                fix_results = await self._run_agents_parallel(fix_tasks, notify=notify)
                self._update_file_owners(file_owners, fix_results)
                all_results.extend(fix_results)
                summary_lines.append(f"- 🧩 Vorab-Import-Check, Versuch {attempt}: {len(import_issues)} Fund(e) → gezielt zur Korrektur an {', '.join(agents_to_fix.keys())} zurückgespielt: {top}")

                if attempt == MAX_VERIFICATION_ITERATIONS:
                    notify("  ⚠️ [yellow]Maximale Vorab-Import-Fixversuche erreicht – weiter mit der regulären Testsuite.[/yellow]")
                    summary_lines.append(f"- 🧩 ⚠️ Vorab-Import-Check nach {MAX_VERIFICATION_ITERATIONS} Versuchen weiterhin mit Funden – weiter mit der regulären Testsuite (dort erneut sichtbar).")

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
        for attempt in range(1, MAX_VERIFICATION_ITERATIONS + 1):
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

            notify(f"  🧪 [yellow]Testlauf {attempt}/{MAX_VERIFICATION_ITERATIONS}:[/yellow] Führe echte Tests aus...")
            report = await self._run_tests_logged(verifier, "erstlauf")

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
                    continue

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
                        continue
                    break
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
                    continue
                notify(f"  ⚠️ [yellow]{report.reason_skipped}[/yellow]")
                summary_lines.append(f"- ⚠️ {report.reason_skipped} Generierter Code wurde NICHT automatisch verifiziert.")
                break

            if report.passed and ENABLE_TEST_DEPTH_GATE:
                depth = await asyncio.to_thread(analyze_test_depth, project_dir, MIN_ROUTE_TEST_RATIO)
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
                    if attempt < MAX_VERIFICATION_ITERATIONS:
                        continue
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
                        redepth = await asyncio.to_thread(analyze_test_depth, project_dir, MIN_ROUTE_TEST_RATIO)
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
                    break
                if depth.applicable:
                    icon = "✅" if depth.passed else "⚠️"
                    summary_lines.append(f"- 🧪 {icon} {depth.format_summary()}")

            if report.passed:
                notify(f"  ✅ [bold green]Alle Tests bestanden[/bold green] (Versuch {attempt}, {report.duration_seconds:.1f}s).")
                summary_lines.append(f"- ✅ Echte Testsuite bestanden nach {attempt} Durchlauf/Durchläufen ({report.duration_seconds:.1f}s).")
                verification_ok = True
                if had_prior_test_ticket and test_ticket_id:
                    try:
                        upsert_ticket(
                            ticket_id=test_ticket_id,
                            title=f"Nicht behobener Verifikations-Fehler: {self.last_project_slug}",
                            source="orchestrator", status="done", project_slug=self.last_project_slug,
                            detail="In einem späteren Lauf behoben - die Testsuite ist jetzt grün.",
                        )
                        notify("  🎫 [dim]Ticket für vorherigen Testfehlschlag als gelöst geschlossen.[/dim]")
                    except Exception as e:
                        notify(f"  ⚠️ [dim yellow]Ticket konnte nicht geschlossen werden: {e}[/dim yellow]")
                break

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
                escalated_and_resolved = False
                _heavy_escalation_downgrade_note = ""
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
                                        upsert_ticket(
                                            ticket_id=test_ticket_id,
                                            title=f"Nicht behobener Verifikations-Fehler: {self.last_project_slug}",
                                            source="orchestrator", status="done", project_slug=self.last_project_slug,
                                            detail="In einem späteren Lauf behoben - die Testsuite ist jetzt grün.",
                                        )
                                    except Exception as e:
                                        notify(f"  ⚠️ [dim yellow]Ticket konnte nicht geschlossen werden: {e}[/dim yellow]")
                                break
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
                                            upsert_ticket(
                                                ticket_id=test_ticket_id,
                                                title=f"Nicht behobener Verifikations-Fehler: {self.last_project_slug}",
                                                source="orchestrator", status="done", project_slug=self.last_project_slug,
                                                detail="In einem späteren Lauf behoben - die Testsuite ist jetzt grün.",
                                            )
                                        except Exception as e:
                                            notify(f"  ⚠️ [dim yellow]Ticket konnte nicht geschlossen werden: {e}[/dim yellow]")
                                    break
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
                                        upsert_ticket(
                                            ticket_id=test_ticket_id,
                                            title=f"Nicht behobener Verifikations-Fehler: {self.last_project_slug}",
                                            source="orchestrator", status="done", project_slug=self.last_project_slug,
                                            detail="In einem späteren Lauf behoben - die Testsuite ist jetzt grün.",
                                        )
                                    except Exception as e:
                                        notify(f"  ⚠️ [dim yellow]Ticket konnte nicht geschlossen werden: {e}[/dim yellow]")
                                break
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
                            upsert_ticket(
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
                break
            previous_failure_signature = current_signature

            if budget_aborted:
                notify("  🚫 [bold red]Budget erreicht[/bold red] – kein neuer Fix-Auftrag mehr, letzter Teststand wird übernommen.")
                summary_lines.append(
                    f"- 🚫 Budget erreicht – Verifikation nach Versuch {attempt} mit "
                    f"{len(report.failures)} verbleibendem/n Testfehler(n) abgebrochen, ohne einen weiteren "
                    "(tokenkostenden) Fix-Agenten zu beauftragen."
                )
                break

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
                break

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
                                upsert_ticket(
                                    ticket_id=f"test-regression-{self.last_project_slug}",
                                    title=f"Tests statt Fehler entfernt: {self.last_project_slug}",
                                    source="orchestrator", status="blocked", project_slug=self.last_project_slug,
                                    detail=f"Versuch {attempt}: {len(_tests_lost)} Testfunktion(en) verschwunden: {_lost_list}"
                                           + (" (Tests zurückgesetzt, erneuter Fix-Versuch ebenfalls erfolglos)" if _restored_test_files else ""),
                                )
                            except Exception as e:
                                notify(f"  ⚠️ [dim yellow]Ticket für Test-Schrumpfung konnte nicht angelegt werden: {e}[/dim yellow]")

            if attempt == MAX_VERIFICATION_ITERATIONS:
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
                                upsert_ticket(
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
                            depth = await asyncio.to_thread(analyze_test_depth, project_dir, MIN_ROUTE_TEST_RATIO)
                            if depth.applicable:
                                outcome.record("test_depth", depth.passed, "" if depth.passed else depth.format_summary())
                                icon = "✅" if depth.passed else "⚠️"
                                summary_lines.append(f"- 🧪 {icon} {depth.format_summary()}")
                        break
                    report = post_fix_report

                notify("  ⚠️ [yellow]Maximale Verifikations-Iterationen erreicht – letzter Stand wird übernommen.[/yellow]")
                summary_lines.append(f"- ⚠️ Nach {MAX_VERIFICATION_ITERATIONS} Versuchen nicht vollständig grün – letzter Stand wurde übernommen.")
                # Ticket schon beim ersten Scheitern in diesem Lauf, nicht erst nach zwei gescheiterten
                # Läufen (has_repeated_failure). Dieselbe Ticket-ID, damit beide Pfade dasselbe Ticket
                # aktualisieren statt Duplikate anzulegen.
                if self.last_project_slug:
                    try:
                        upsert_ticket(
                            ticket_id=f"recurring-failure-{self.last_project_slug}",
                            title=f"Nicht behobener Verifikations-Fehler: {self.last_project_slug}",
                            source="orchestrator", status="blocked", project_slug=self.last_project_slug,
                            detail="\n".join(summary_lines).strip()[:300] + self._provider_exhaustion_ticket_note(),
                        )
                    except Exception as e:
                        notify(f"  ⚠️ [dim yellow]Ticket für ungelösten Testfehler konnte nicht angelegt werden: {e}[/dim yellow]")

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
            docker_report = await asyncio.to_thread(verifier.check_docker_build)
            if docker_report.attempted:
                outcome.record("docker_build", docker_report.success)
                if docker_report.success:
                    notify("  🐳 [bold green]Docker-Image baut erfolgreich.[/bold green]")
                    summary_lines.append("- 🐳 Docker-Image baut erfolgreich (echter `docker build`).")
                else:
                    notify("  🐳 [bold red]Docker-Build fehlgeschlagen.[/bold red]")
                    summary_lines.append(f"- 🐳 ❌ Docker-Build fehlgeschlagen: {docker_report.output[:500]}")
            elif docker_report.reason_skipped and "Daemon" in docker_report.reason_skipped:
                # Sichtbar, weil ein fehlender Daemon sonst mit einem Dockerfile-Fehler verwechselt wird.
                notify(f"  🐳 [dim yellow]{docker_report.reason_skipped}[/dim yellow]")
                summary_lines.append(f"- 🐳 ⏭️ {docker_report.reason_skipped}")

        # Echter `npm run build` VOR dem Browser-UI-Check: ohne Build würde der Browser-Check rohe
        # Quelldateien (z.B. main.tsx) servieren und einen Build-Fehler als Frontend-Bug melden.
        if not (budget_aborted or manually_cancelled):
            frontend_build_reports = await asyncio.to_thread(verifier.check_frontend_build)
            for fb_report in frontend_build_reports:
                if not fb_report.attempted:
                    if fb_report.reason_skipped:
                        notify(f"  📦 [dim yellow]Frontend-Build ({fb_report.directory}): {fb_report.reason_skipped}[/dim yellow]")
                    continue
                if outcome.status("frontend_build") is not False:
                    outcome.record("frontend_build", fb_report.passed, "" if fb_report.passed else f"{fb_report.directory}: {fb_report.output[:300]}")
                if fb_report.passed:
                    notify(f"  📦 [bold green]Frontend-Build ({fb_report.directory}) erfolgreich:[/bold green] `npm run build`.")
                    summary_lines.append(f"- 📦 Frontend-Build (`{fb_report.directory}`) erfolgreich (echter `npm run build`).")
                else:
                    notify(f"  📦 [bold red]Frontend-Build ({fb_report.directory}) fehlgeschlagen.[/bold red]")
                    summary_lines.append(f"- 📦 ❌ Frontend-Build (`{fb_report.directory}`) fehlgeschlagen: {fb_report.output[:500]}")
                    verification_ok = False
                    fb_owner = file_owners.get(f"{fb_report.directory}/package.json") if fb_report.directory != "." else file_owners.get("package.json")
                    fb_owner = fb_owner or next((a for a in ("frontend", "devops") if a in self._agents), None)
                    if fb_owner and fb_owner in self._agents:
                        notify(f"  🛠️ [bold yellow]Frontend-Build-Fix:[/bold yellow] Beauftrage {fb_owner}...")
                        fix_result = (await self._run_agents_parallel([AgentTask(
                            task_id=f"verify_fix_frontend_build_{fb_owner}",
                            agent_id=fb_owner,
                            description=(
                                f"Der ECHTE Produktions-Build (`npm run build` unter `{fb_report.directory}`) ist "
                                f"fehlgeschlagen. Nutze read_file, um die betroffene(n) Datei(en) zu prüfen, und "
                                f"edit_file/write_file, um den Fehler zu beheben.\n\n{fb_report.output[:2000]}"
                            ),
                            context="", project_dir=project_dir,
                        )], notify=notify))
                        self._update_file_owners(file_owners, fix_result)
                        all_results.extend(fix_result)

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
            for attempt in range(1, MAX_VERIFICATION_ITERATIONS + 1):
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

                if attempt == MAX_VERIFICATION_ITERATIONS:
                    notify("  ⚠️ [yellow]Maximale Vollständigkeits-Fixversuche erreicht – letzter Stand wird übernommen.[/yellow]")
                    summary_lines.append(f"- 🧩 ⚠️ Nach {MAX_VERIFICATION_ITERATIONS} Versuchen weiterhin Stub-/Platzhalter-Funde – letzter Stand wurde übernommen.")

        if completeness_report is not None and completeness_report.attempted:
            outcome.record(
                "completeness", bool(completeness_report.passed),
                "" if completeness_report.passed else f"{len(completeness_report.issues)} Fund(e)",
            )

        # Opt-in-Abdeckungsschwelle (MIN_TEST_COVERAGE, Standard 0): Pass/Fail allein sagt nichts
        # über ungetesteten Code. Nur sinnvoll bei gelaufener UND bestandener Testsuite.
        if not (budget_aborted or manually_cancelled) and MIN_TEST_COVERAGE > 0 and report is not None and report.ran and report.passed:
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

    async def _record_accessibility_check(
        self, verifier: ProjectVerifier, outcome: VerificationOutcome,
        summary_lines: list[str], notify: Callable[[str], None],
    ) -> None:
        """P6-5 (ROADMAP_TEMP.md, Teilschritt): aus `_run_verification_loop_impl()` extrahiert -
        echter axe-core-Scan (WCAG 2.x), rein informativ, beeinflusst `verification_ok` nicht,
        deshalb ohne Rückgabewert sicher isolierbar (kein geteilter Kontrollfluss-Zustand)."""
        a11y_report = await asyncio.to_thread(verifier.check_accessibility)
        if not a11y_report.attempted:
            return
        outcome.record("accessibility", bool(a11y_report.passed))
        if a11y_report.passed:
            notify(f"  ♿ [bold green]Accessibility-Check (axe-core) erfolgreich:[/bold green] `{a11y_report.tested_url}`.")
            summary_lines.append(f"- ♿ Accessibility-Check (axe-core): `{a11y_report.tested_url}` keine WCAG-Verstöße.")
        else:
            top = "; ".join(f"{v.rule_id} [{v.impact}] {v.target}" for v in a11y_report.violations[:5])
            if len(a11y_report.violations) > 5:
                top += f" … und {len(a11y_report.violations) - 5} weitere"
            notify(f"  ♿ [bold red]Accessibility-Check (axe-core): {len(a11y_report.violations)} WCAG-Verstoß/Verstöße.[/bold red]")
            summary_lines.append(f"- ♿ ⚠️ Accessibility-Check (axe-core): {len(a11y_report.violations)} WCAG-Verstoß/Verstöße: {top}")

    async def _record_domain_logic_depth_check(
        self, project_dir: str, outcome: VerificationOutcome, summary_lines: list[str],
    ) -> None:
        """P6-5 (ROADMAP_TEMP.md, Teilschritt): aus `_run_verification_loop_impl()` extrahiert -
        P4-3s Fachlogik-Testtiefe-Signal, rein informativ (siehe
        `core/test_depth.py.analyze_domain_logic_depth()`-Docstring), beeinflusst
        `verification_ok` nicht, deshalb ohne Rückgabewert sicher isolierbar."""
        domain_depth = await asyncio.to_thread(analyze_domain_logic_depth, project_dir, MIN_DOMAIN_LOGIC_TEST_RATIO)
        if not domain_depth.applicable:
            return
        outcome.record("domain_logic_depth", domain_depth.passed, "" if domain_depth.passed else domain_depth.format_summary())
        if not domain_depth.passed:
            summary_lines.append(f"- 🧬 ⚠️ {domain_depth.format_summary()}")

    async def _check_coverage_threshold(
        self, verifier: ProjectVerifier, outcome: VerificationOutcome,
        summary_lines: list[str], notify: Callable[[str], None],
    ) -> bool | None:
        """P6-5 (ROADMAP_TEMP.md, Teilschritt): aus `_run_verification_loop_impl()` extrahiert -
        die Opt-in-Abdeckungsschwelle (MIN_TEST_COVERAGE). Anders als Accessibility/Fachlogik-
        Testtiefe KANN dieser Check `verification_ok` zurücksetzen (echte, explizit
        konfigurierte Anforderung) - da eine Methode eine lokale bool-Variable des Aufrufers
        nicht direkt mutieren kann, meldet sie das per Rückgabewert statt eines geteilten
        Zustandsobjekts: `False` = Veto (Aufrufer setzt `verification_ok = False`), `None` =
        kein Veto (Schwelle erreicht oder Check nicht durchgeführt)."""
        coverage_report = await asyncio.to_thread(verifier.check_coverage)
        if not coverage_report.attempted:
            return None
        self.last_coverage_percent = coverage_report.percent
        outcome.record("coverage", coverage_report.percent >= MIN_TEST_COVERAGE, f"{coverage_report.percent}%")
        if coverage_report.percent >= MIN_TEST_COVERAGE:
            notify(f"  📊 [bold green]Testabdeckung: {coverage_report.percent}%[/bold green] (Schwelle: {MIN_TEST_COVERAGE}%).")
            summary_lines.append(f"- 📊 Testabdeckung: {coverage_report.percent}% (Schwelle von {MIN_TEST_COVERAGE}% erreicht).")
            return None
        # Eine explizit konfigurierte Schwelle ist eine echte Anforderung - verification_ok zurücksetzen.
        notify(f"  📊 [bold red]Testabdeckung {coverage_report.percent}% UNTER der Schwelle von {MIN_TEST_COVERAGE}%.[/bold red]")
        summary_lines.append(f"- 📊 ❌ Testabdeckung {coverage_report.percent}% UNTER der konfigurierten Schwelle (`MIN_TEST_COVERAGE={MIN_TEST_COVERAGE}%`).")
        _grund = f"Testabdeckung {coverage_report.percent}% liegt unter der konfigurierten Schwelle von {MIN_TEST_COVERAGE}%."
        notify(f"  ❌ [bold red]Verifikations-Veto durch Coverage-Check:[/bold red] {_grund}")
        summary_lines.append(f"- ❌ **Verifikations-Veto durch Coverage-Check:** {_grund}")
        return False

    async def _run_browser_ui_check(
        self,
        verifier: ProjectVerifier,
        project_dir: str,
        all_results: list[AgentResult],
        file_owners: dict[str, str],
        outcome: VerificationOutcome,
        summary_lines: list[str],
        notify: Callable[[str], None],
        run_start_tokens: int | None,
        cancel_requested: Callable[[], bool] | None,
    ) -> tuple[bool, bool, bool]:
        """P6-5 (ROADMAP_TEMP.md, Teilschritt): aus `_run_verification_loop_impl()` extrahiert -
        Browser/Frontend-UI-Check inkl. gezielter Auto-Fix-Schleife. `all_results` wird über
        `_run_runtime_check_with_fix()` in-place erweitert (`.extend()`, dieselbe Liste bleibt
        bestehen) - keine Rückgabe nötig. `budget_aborted`/`manually_cancelled`/`verification_ok`
        sind dagegen lokale bool-Variablen des Aufrufers, die eine Methode nicht direkt mutieren
        kann - deshalb als Drei-Tupel (budget_aborted, manually_cancelled, verification_ok_veto)
        zurückgegeben statt über ein geteiltes Zustandsobjekt."""
        def _build_browser_fix_task(browser_report, attempt):
            agent_id = _classify_browser_failure_owner(
                browser_report.console_errors, browser_report.missing_assets, self._agents,
            )
            if agent_id is None:
                return None
            details = browser_report.missing_assets + browser_report.console_errors + [
                f"Canvas nie gezeichnet: {c}" for c in browser_report.blank_canvases
            ]
            backend_hint = (
                " Die Fehlermeldung deutet auf eine Backend-Ursache hin (CORS, 5xx-Antwort, "
                "WebSocket-Handshake oder Netzwerkfehler) - prüfe zuerst die betroffenen "
                "Endpunkte/Middleware, nicht das Frontend-Rendering."
                if agent_id == "backend"
                else ""
            )
            return AgentTask(
                task_id=f"verify_fix_browser_{agent_id}_{attempt}",
                agent_id=agent_id,
                description=(
                    f"Der ECHTE Browser/UI-Check (Playwright) gegen `{browser_report.tested_url}` ist "
                    f"fehlgeschlagen: {'; '.join(details)[:800]}.{backend_hint} Nutze read_file, um die "
                    f"betroffene(n) Datei(en) zu prüfen, und edit_file/write_file, um den Fehler zu "
                    f"beheben (z.B. fehlendes Asset, JS-Konsolenfehler, nie gezeichnetes Canvas-Element)."
                ),
                context="",
                project_dir=project_dir,
            )

        browser_report, all_results, br_aborted, br_cancelled = await self._run_runtime_check_with_fix(
            check_fn=verifier.check_browser_ui,
            build_fix_task=_build_browser_fix_task,
            all_results=all_results,
            file_owners=file_owners,
            notify=notify,
            run_start_tokens=run_start_tokens,
            cancel_requested=cancel_requested,
            is_attempted=lambda r: r.attempted,
            is_passed=lambda r: r.passed,
        )
        if not browser_report.attempted:
            return br_aborted, br_cancelled, False
        outcome.record(
            "browser_ui",
            bool(browser_report.passed),
            "" if browser_report.passed else "; ".join(
                browser_report.missing_assets + browser_report.console_errors
            )[:300],
        )
        if browser_report.passed:
            if browser_report.engine == "playwright":
                notify(f"  🌐 [bold green]Frontend/UI-Check erfolgreich:[/bold green] `{browser_report.tested_url}` [playwright, echter Browser-Lauf].")
                summary_lines.append(f"- 🌐 Frontend/UI-Check: `{browser_report.tested_url}` [playwright] fehlerfrei (JS wurde echt ausgeführt).")
            else:
                # static_dom-Fallback führt KEIN JavaScript aus - deutlich als eingeschränkt
                # kennzeichnen, damit er nicht wie ein echter Playwright-Pass wirkt.
                notify(f"  🌐 [bold yellow]Frontend/UI-Check eingeschränkt:[/bold yellow] `{browser_report.tested_url}` [static_dom] - kein echter Browser installiert, JavaScript wurde NICHT ausgeführt (nur Dateiexistenz geprüft).")
                summary_lines.append(f"- 🌐 ⚠️ Frontend/UI-Check nur eingeschränkt (`static_dom`, `{browser_report.tested_url}`): referenzierte Dateien existieren, aber JavaScript lief NICHT in einem echten Browser (Playwright fehlt/nicht nutzbar) - Laufzeitfehler bleiben so unentdeckt.")
            return br_aborted, br_cancelled, False
        details = browser_report.missing_assets + browser_report.console_errors + [
            f"Canvas nie gezeichnet: {c}" for c in browser_report.blank_canvases
        ]
        err_details = "; ".join(details)[:150]
        notify(f"  🌐 [bold red]Frontend/UI-Check fehlgeschlagen:[/bold red] {err_details}.")
        summary_lines.append(f"- 🌐 ❌ Frontend/UI-Check fehlgeschlagen: {err_details}.")
        notify(f"  ❌ [bold red]Verifikations-Veto durch Browser-UI-Check:[/bold red] {err_details}.")
        summary_lines.append(f"- ❌ **Verifikations-Veto durch Browser-UI-Check:** {err_details}.")
        return br_aborted, br_cancelled, True

    async def _run_smoke_check(
        self,
        verifier: ProjectVerifier,
        project_dir: str,
        all_results: list[AgentResult],
        file_owners: dict[str, str],
        outcome: VerificationOutcome,
        summary_lines: list[str],
        notify: Callable[[str], None],
        run_start_tokens: int | None,
        cancel_requested: Callable[[], bool] | None,
    ) -> tuple[bool, bool, bool]:
        """P6-5 (ROADMAP_TEMP.md, Teilschritt): aus `_run_verification_loop_impl()` extrahiert -
        Runtime-Smoke-Check (startet die App tatsächlich?) inkl. gezielter Auto-Fix-Schleife.
        Gleiches Rückgabemuster wie `_run_browser_ui_check()`: `all_results` wird in-place über
        `_run_runtime_check_with_fix()` erweitert, `budget_aborted`/`manually_cancelled`/
        `verification_ok` als Drei-Tupel zurückgegeben, da lokale bool-Variablen des Aufrufers
        nicht direkt mutierbar sind."""
        def _build_smoke_fix_task(smoke_report, attempt):
            owner = file_owners.get(smoke_report.entrypoint) if smoke_report.entrypoint else None
            agent_id = owner if owner in self._agents else ("backend" if "backend" in self._agents else None)
            if agent_id is None:
                return None
            return AgentTask(
                task_id=f"verify_fix_smoke_{agent_id}_{attempt}",
                agent_id=agent_id,
                description=(
                    f"Der ECHTE Runtime-Smoke-Test ist fehlgeschlagen: die App startet nicht bzw. "
                    f"antwortet nicht (Entrypoint `{smoke_report.entrypoint}`, Typ {smoke_report.app_type}). "
                    f"Tests waren grün, aber 'Tests grün' heißt nicht 'App startet'. Nutze read_file, "
                    f"um die betroffene(n) Datei(en) zu prüfen, und edit_file/write_file, um den Start-"
                    f"fehler zu beheben.\n\nFehlerausgabe:\n{smoke_report.output[:1000]}"
                ),
                context="",
                project_dir=project_dir,
            )

        smoke_report, all_results, sb_aborted, sb_cancelled = await self._run_runtime_check_with_fix(
            check_fn=verifier.check_runtime_smoke,
            build_fix_task=_build_smoke_fix_task,
            all_results=all_results,
            file_owners=file_owners,
            notify=notify,
            run_start_tokens=run_start_tokens,
            cancel_requested=cancel_requested,
            is_attempted=lambda r: r.attempted,
            is_passed=lambda r: r.passed,
        )
        if not smoke_report.attempted:
            return sb_aborted, sb_cancelled, False
        outcome.record("smoke", bool(smoke_report.passed), "" if smoke_report.passed else (smoke_report.output or "")[:300])
        if smoke_report.passed:
            code_info = f" (HTTP {smoke_report.status_code})" if smoke_report.status_code else ""
            notify(f"  🚀 [bold green]Runtime-Smoke-Test erfolgreich:[/bold green] `{smoke_report.entrypoint}` [{smoke_report.app_type}]{code_info}.")
            summary_lines.append(f"- 🚀 Runtime-Smoke-Test: `{smoke_report.entrypoint}` [{smoke_report.app_type}] startet fehlerfrei{code_info}.")
            return sb_aborted, sb_cancelled, False
        # Eine geprüfte, aber nicht startende App ist eine echte Anforderungsverletzung -
        # sichtbar melden und verification_ok zurücksetzen.
        err = f": {smoke_report.output[:150]}" if smoke_report.output else ""
        notify(f"  🚀 [bold red]Runtime-Smoke-Test fehlgeschlagen:[/bold red] `{smoke_report.entrypoint}` [{smoke_report.app_type}]{err}.")
        summary_lines.append(f"- 🚀 ❌ Runtime-Smoke-Test fehlgeschlagen: `{smoke_report.entrypoint}` [{smoke_report.app_type}] startet nicht{err}.")
        _grund = f"`{smoke_report.entrypoint}` [{smoke_report.app_type}] startet nicht{err}."
        notify(f"  ❌ [bold red]Verifikations-Veto durch Runtime-Smoke-Test:[/bold red] {_grund}")
        summary_lines.append(f"- ❌ **Verifikations-Veto durch Runtime-Smoke-Test:** {_grund}")
        return sb_aborted, sb_cancelled, True

    async def _run_load_test_check(
        self,
        verifier: ProjectVerifier,
        project_dir: str,
        all_results: list[AgentResult],
        file_owners: dict[str, str],
        outcome: VerificationOutcome,
        summary_lines: list[str],
        notify: Callable[[str], None],
        run_start_tokens: int | None,
        cancel_requested: Callable[[], bool] | None,
    ) -> tuple[bool, bool, bool]:
        """P6-5 (ROADMAP_TEMP.md, Teilschritt): aus `_run_verification_loop_impl()` extrahiert -
        Lastentest (k6/Locust) inkl. gezielter Auto-Fix-Schleife. Gleiches Rückgabemuster wie
        `_run_browser_ui_check()`/`_run_smoke_check()`."""
        def _build_load_fix_task(perf_report, attempt):
            owner = file_owners.get(perf_report.script) if perf_report.script else None
            agent_id = owner if owner in self._agents else ("backend" if "backend" in self._agents else None)
            if agent_id is None:
                return None
            return AgentTask(
                task_id=f"verify_fix_load_{agent_id}_{attempt}",
                agent_id=agent_id,
                description=(
                    f"Der ECHTE Lastentest (`{perf_report.script}`, {perf_report.tool}) ist fehlgeschlagen: "
                    f"{perf_report.failed_requests} von {perf_report.total_requests} Requests scheiterten "
                    f"unter simultaner Last. Nutze read_file, um die betroffene(n) Datei(en) zu prüfen, "
                    f"und edit_file/write_file, um die Ursache (z.B. fehlende Nebenläufigkeitssicherung, "
                    f"blockierende I/O) zu beheben."
                ),
                context="",
                project_dir=project_dir,
            )

        perf_report, all_results, lb_aborted, lb_cancelled = await self._run_runtime_check_with_fix(
            check_fn=lambda: verifier.check_load_test(LOAD_TEST_DURATION_SECONDS, LOAD_TEST_TIMEOUT_SECONDS),
            build_fix_task=_build_load_fix_task,
            all_results=all_results,
            file_owners=file_owners,
            notify=notify,
            run_start_tokens=run_start_tokens,
            cancel_requested=cancel_requested,
            is_attempted=lambda r: r.attempted,
            is_passed=lambda r: r.passed,
        )
        if not perf_report.attempted:
            return lb_aborted, lb_cancelled, False
        outcome.record("load_test", bool(perf_report.passed))
        stats = f"{perf_report.total_requests} Requests, {perf_report.failed_requests} fehlgeschlagen"
        # isinstance() statt "is not None": hält Tests mit unvollständig gemocktem Verifier
        # robust (MagicMock würde an ":.0f" mit TypeError crashen).
        if isinstance(perf_report.p95_ms, (int, float)):
            stats += f", p95={perf_report.p95_ms:.0f}ms"
        if perf_report.passed:
            notify(f"  🏋️ [bold green]Lastentest ({perf_report.tool}) bestanden:[/bold green] `{perf_report.script}` [{stats}].")
            summary_lines.append(f"- 🏋️ Lastentest ({perf_report.tool}) bestanden: `{perf_report.script}` [{stats}].")
            return lb_aborted, lb_cancelled, False
        notify(f"  🏋️ [bold red]Lastentest ({perf_report.tool}) fehlgeschlagen:[/bold red] `{perf_report.script}` [{stats}].")
        summary_lines.append(f"- 🏋️ ❌ Lastentest ({perf_report.tool}) fehlgeschlagen: `{perf_report.script}` [{stats}].")
        _grund = f"Lastentest ({perf_report.tool}) fehlgeschlagen: `{perf_report.script}` [{stats}]."
        notify(f"  ❌ [bold red]Verifikations-Veto durch Lastentest:[/bold red] {_grund}")
        summary_lines.append(f"- ❌ **Verifikations-Veto durch Lastentest:** {_grund}")
        return lb_aborted, lb_cancelled, True

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

    async def _recheck_stale_blocking_checks(
        self, project_dir: str, outcome: VerificationOutcome,
        summary_lines: list[str], notify,
    ) -> None:
        """Misst `pre_flight` und `security_handoff` am ENDE der Verifikation neu, wenn sie
        zuvor fehlgeschlagen sind.

        Beide Prüfungen laufen früh im Lauf, blockieren `verification_ok` hart und wurden
        danach NIE wieder ausgewertet - auch dann nicht, wenn spätere Fix-Runden (Testsuite,
        Completeness, Integrations-Checkpoint, Frontend-Build) die Ursache längst behoben
        hatten. Zwei reale Fälle:

        * **`pre_flight` (cachegrid_proxy, 2026-09-19):** Der Check lief nur in der Schleife vor
          der Testausführung, brach nach dem Circuit-Breaker mit 2 Funden ab und wurde mit genau
          diesem - inzwischen veralteten - Report aufgezeichnet. `run_pre_flight_check()` gegen
          denselben Projektstand liefert heute `passed=True`; das Projekt ist de facto fertig und
          steht trotzdem dauerhaft als rot in der Historie.
        * **`security_handoff` (aegisflow/sentinedge, 2026-09-18/19):** `_run_security_
          requirements_checkpoint()` beauftragt genau EINEN Agenten, prüft einmal nach und legt
          das Ergebnis auf `self._security_unmet_requirements` ab. `verification.py` liest das
          Feld am Schleifenanfang und trägt das Veto ein - spätere Reparaturen erreichen es nicht
          mehr.

        Bewusst nur Neu-MESSUNG, kein weiterer Fix-Versuch: hier ist die Verifikation bereits
        durchlaufen, ein zusätzlicher Agenten-Aufruf würde Budget kosten, ohne dass noch eine
        Prüfung folgt, die sein Ergebnis bewerten könnte. Ein weiterhin fehlschlagender Check
        bleibt deshalb unverändert auf `failed`.
        """
        if outcome.status("pre_flight") is False:
            try:
                report = await asyncio.to_thread(run_pre_flight_check, project_dir)
            except Exception as e:  # noqa: BLE001 - Neu-Messung darf den Lauf nie abbrechen
                logging.getLogger(__name__).warning("Pre-Flight-Neumessung fehlgeschlagen: %r", e)
            else:
                if not report.error and report.passed:
                    outcome.record("pre_flight", True, "")
                    notify("  🔍 [bold green]Pre-Flight-Check: Funde durch spätere Fix-Runden behoben.[/bold green]")
                    summary_lines.append(
                        "- 🔍 ✅ Pre-Flight-Check am Laufende erneut gemessen: die früheren Funde "
                        "wurden durch spätere Fix-Runden behoben."
                    )

        if outcome.status("security_handoff") is False:
            try:
                recheck = await asyncio.to_thread(unmet_requirements, project_dir)
            except Exception as e:  # noqa: BLE001 - siehe oben
                logging.getLogger(__name__).warning("Security-Handoff-Neumessung fehlgeschlagen: %r", e)
            else:
                remaining = [(agent, req) for agent, req in recheck if agent == "security"]
                self._security_unmet_requirements = remaining
                if not remaining:
                    outcome.record("security_handoff", True, "")
                    notify("  🛡️ [bold green]Sicherheits-Übergabe: Anforderungen inzwischen erfüllt.[/bold green]")
                    summary_lines.append(
                        "- 🛡️ ✅ Sicherheits-Übergabe am Laufende erneut geprüft: alle vom "
                        "security-Agenten geforderten Anforderungen sind erfüllt."
                    )
