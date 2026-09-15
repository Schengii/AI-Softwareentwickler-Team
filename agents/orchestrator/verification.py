"""
agents/orchestrator/verification.py – VerificationMixin: echte Verifikations-/Fix-Schleife.

Die Governance-Fix-Schleife und die autonome Behandlung von Rückfragen leben seit der
Team-Analyse 2026-09-15 in agents/orchestrator/governance.py (GovernanceMixin).

_run_verification_loop() installiert Abhängigkeiten in einer isolierten Umgebung, führt die
echte Testsuite aus und schickt bei Fehlschlägen einen GEZIELTEN Korrekturauftrag an genau
die Agenten, deren Dateien laut echtem Traceback betroffen sind. Führt anschließend alle
weiteren Verifikations-Checks aus (Docker-Build, Dependency-/SAST-/Lizenz-Audit, Lint,
Coverage, Runtime-Smoke, Lastentest, Browser/A11y) - Runtime-Smoke, Lastentest und Browser/UI
laufen dabei über _run_runtime_check_with_fix() (siehe unten), das bei Fehlschlag ebenfalls
einen gezielten Korrekturauftrag auslöst statt nur verification_ok zurückzusetzen.

ki_team_verbesserungsanalyse.md, Teil 5.1 (größte Einzeldatei des Frameworks, ~2850 Zeilen):
Die reinen, zustandslosen Diagnose-/Routing-Funktionen (Regex-basierte Fehlerklassifikation,
Owner-Ermittlung, Fortschritts-Signaturen) leben seitdem in
agents/orchestrator/failure_diagnosis.py - diese Datei re-exportiert sie unverändert (Import
unten), damit bestehende Importe (Tests, core-Module) unangetastet bleiben.
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
    _failure_diagnosis,
    _failure_fingerprint,
    _import_name_error_target,
    _issue_signature,
    _no_progress,
    _prior_run_context,
    _record_instance_attribute_learning,
    _record_verification_learning,
    _route_failure_owners,
)
from agents.orchestrator.verification_checks import CheckContext, run_informational_checks
from config import (
    ENABLE_COMPLETENESS_CHECK,
    ENABLE_LOAD_TEST_CHECK,
    ENABLE_SMOKE_TEST_GATE,
    ENABLE_TEST_DEPTH_GATE,
    LOAD_TEST_DURATION_SECONDS,
    LOAD_TEST_TIMEOUT_SECONDS,
    MAX_VERIFICATION_ITERATIONS,
    MIN_ROUTE_TEST_RATIO,
    MIN_TEST_COVERAGE,
)
from core.backlog_store import get_ticket, upsert_ticket
from core.decision_log import log_decision
from core.dependency_manifest import (
    add_requirement,
    manifest_for_package,
    package_from_finding,
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
from core.pre_flight_check import PreFlightIssue, run_pre_flight_check
from core.test_depth import analyze_test_depth
from core.verification_outcome import VerificationOutcome, parse_install_exit_code
from core.verifier import ProjectVerifier, VerificationReport

# Team-Optimierung (root_cause_analysis, syncwave-Projekt, 2026-09-15): _build_browser_fix_task()
# wies JEDEN Fehlschlag des Browser/UI-Checks hartcodiert dem frontend-Agenten zu. Ein Teil der
# echten Konsolenfehler (CORS-Ablehnungen, 5xx-API-Antworten, abgelehnte WebSocket-Handshakes,
# Netzwerkfehler wie ECONNREFUSED) hat seine Ursache aber im Backend - der Frontend-Agent kann
# einen fehlenden CORS-Header oder einen abstürzenden Endpunkt nicht beheben, sieht das korrekt,
# und der Fix-Loop drehte sich bisher wiederholt ergebnislos. Diese Signale sind rein textuell
# aus den vom Browser gemeldeten Fehlern erkennbar, kein LLM-Aufruf nötig.
_BACKEND_CAUSED_BROWSER_ERROR_RE = re.compile(
    r"cors|cross-origin request blocked|"
    r"websocket handshake|'connection' header is missing|"
    r"failed to fetch|networkerror when attempting to fetch|"
    r"err_connection_refused|err_connection_reset|econnrefused|"
    r"\bhttp 5\d\d\b|"
    # Chromes Standardformat ("the server responded with a status of 500") und API-Routen, die
    # es serverseitig nicht gibt bzw. die Eingaben ablehnen (404/405/422 auf /api/...).
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
        Realer Fund bei einer Bestandsaufnahme des eigenen Teams: anders als ein echter
        Testfehler (siehe _run_verification_loop oben) lösten ein fehlgeschlagener Runtime-
        Smoke-Test, Lastentest oder Browser/UI-Check bisher NIE einen Korrekturauftrag aus -
        sie setzten nur verification_ok=False und der Lauf endete. Ein Projekt mit einem
        kaputten Frontend blieb dadurch über beliebig viele Läufe hinweg rot, weil derselbe
        Fehler nie behoben wurde (real beobachtet: snippet_vault scheiterte 3 Läufe in Folge
        am selben Frontend-Check). Dieselbe gezielte Fix-Schleife wie beim Testfehler, nur
        mit vom Aufrufer übergebener Owner-Ermittlung statt Traceback-Dateizuordnung (diese
        Checks liefern keinen Python-Traceback mit betroffenen Dateien).

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
                # Kein zuständiger Agent ermittelbar (z.B. kein frontend-Agent Teil des Plans) -
                # Fix-Schleife kann hier nichts beitragen, letzter Check-Stand bleibt maßgeblich.
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
        Prüft VOR der Testschleife, ob die erzeugte Anwendung überhaupt startet, und lässt einen
        Startfehler gezielt beheben, bevor Zeit und Token in eine vollständige Testsuite fließen.

        Gibt die Zeilen zurück, die ins Verifikations-Protokoll aufgenommen werden sollen.

        Bewusst höchstens EIN Fixversuch: Das Gate soll den häufigsten und teuersten Fall früh
        abfangen (App startet gar nicht), nicht die eigentliche Fix-Schleife duplizieren. Bleibt
        der Start danach kaputt, läuft die reguläre Testschleife trotzdem an - sie sieht denselben
        Fehler dann erneut und hat ihre eigene, mehrstufige Eskalationsleiter dafür.
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

    async def _resync_environment_if_dependencies_changed(
        self, verifier: ProjectVerifier, fix_results: list[AgentResult],
        notify: Callable[[str], None], summary_lines: list[str],
    ) -> None:
        """
        Team-Optimierung (Analysebericht `ki_team_schwachstellen_und_fehleranalyse_aethermesh_
        20260913.md`, Schwachstelle 2): `verifier.ensure_environment()` lief bisher NUR einmal
        ganz zu Beginn der Verifizierungsphase. Trägt ein Fix-Agent (`tester`, `backend`, ...) im
        Rahmen der Fix-Schleife ein neues Paket in `requirements.txt`/`package.json`/
        `pyproject.toml` ein (z.B. `pytest-asyncio`), lief der darauffolgende Testlauf bisher
        gegen die UNVERÄNDERTE venv - das neu eingetragene Paket war schlicht nicht installiert,
        der eigentlich korrekte Fix scheiterte am Re-Test aus einem rein infrastrukturellen
        Grund. Ein erneuter `ensure_environment()`-Aufruf VOR dem nächsten Testlauf schließt
        diese Lücke, läuft aber gezielt NUR, wenn tatsächlich eine Manifest-Datei verändert
        wurde (kein unnötiger pip/npm-Install bei reinen Code-Fixes).
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
        Verifikations-Log dieses Laufs (core/run_logger.py).

        Realer Fund (KI-Team-Masterplan-Analyse): In den Bericht wandert nur eine stark gekürzte
        Zusammenfassung ("⚠️ pip install -r requirements.txt (exit_code=1)"). Die eigentliche
        Fehlerausgabe - also genau das, was ein Mensch zum Debuggen braucht - existierte nach
        Ende des Laufs nirgends mehr, weil `logs/` leer blieb und die rich-Konsolenausgabe mit
        dem Terminal verschwand. `phase` unterscheidet den Erstlauf von den Wiederholungen nach
        einem Fixversuch, damit im Log nachvollziehbar bleibt, ob ein Fix etwas bewirkt hat.
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
            # Sichtbar statt verschluckt: ohne Rohausgabe ist ein roter Lauf später nicht mehr
            # diagnostizierbar (Framework-Analyse 2026-09-10).
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
        Robuste Außenhülle um `_run_verification_loop_impl()` (Fehleranalyse ecochef-Lauf 3,
        `logs/runs/20260913_163546_ecochef.jsonl`, abort_reason "exception:TypeError"): egal was
        innerhalb der Schleife schiefgeht (z.B. unerwartete Failure-Datentypen aus einem
        Testrunner-Sonderfall) - `process()` erwartet hier IMMER ein valides 5er-Tupel
        `(all_results, summary, budget_aborted, manually_cancelled, verification_ok)` und darf NIE
        mit einer durchgereichten Exception abstürzen. `all_results` wird dabei bewusst
        unverändert zurückgegeben (statt eines Teilzustands), da bei einem Absturz nicht sicher
        feststeht, wie weit die Schleife intern schon mutiert hat; `verification_ok=False` macht
        den unvollständigen Verifikationsstatus sichtbar statt ihn zu verschleiern.
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
        outcome = getattr(self, "last_verification_outcome", None)
        if not isinstance(outcome, VerificationOutcome):
            outcome = VerificationOutcome()
            self.last_verification_outcome = outcome
        pre_flight_report = None
        completeness_report = None
        # Bleibt None, wenn die Schleife unten (z.B. MAX_VERIFICATION_ITERATIONS<=0) nie
        # durchläuft - der Coverage-Check danach prüft explizit auf None, statt sich auf eine
        # garantierte Zuweisung zu verlassen.
        report: VerificationReport | None = None
        # Höchstens EIN automatischer Nachbeauftragungs-Versuch für "keine Tests gefunden" (siehe
        # unten) - verhindert eine Endlosschleife, falls der tester-Agent wiederholt keine
        # echte Testdatei anlegt.
        no_tests_fix_attempted = False
        # Zirkuit-Breaker gegen wirkungslose Wiederholungen (Team-Retrospektive nach dem
        # taskpulse-Lauf): bisher wurde ein zweiter Fixversuch immer unternommen, selbst wenn
        # der erste erkennbar NICHTS verändert hat - derselbe Satz Testfehler (gleiche
        # test_id+Fehlermeldung) nach einem Fixversuch bedeutet fast immer, dass der
        # beauftragte Agent das Problem nicht lösen konnte, nicht dass ein zweiter,
        # identischer Auftrag beim nächsten Versuch anders ausgeht. Bricht die Schleife dann
        # SOFORT ab (spart einen kompletten, meist wirkungslosen Agenten-Durchlauf) statt den
        # letzten erlaubten Versuch trotzdem zu verbrauchen.
        previous_failure_signature: frozenset[tuple[str, str]] | None = None
        # Team-Retrospektive (Verbesserungsvorschlag "Strategiewechsel statt Wiederholung"):
        # bisher bedeutete der obige Zirkuit-Breaker nur "aufgeben" - derselbe Agent bekam
        # denselben Fehler zweimal exakt gleich beschrieben und scheiterte beide Male gleich,
        # das Ergebnis wurde dann trotzdem als "letzter Stand" übernommen (real beobachtet in
        # mehreren Läufen: sentinelproxy, incidentpilot, omnichat - "Nach 2 Versuchen nicht
        # vollständig grün"). EIN zusätzlicher Eskalations-Versuch (nicht mehr, um die Schleife
        # nicht doch wieder unbegrenzt zu verlängern) holt bei "kein Fortschritt" den
        # zuständigen Fachbereichsleiter (falls vorhanden) statt denselben Mitarbeiter erneut
        # gegen dasselbe Problem laufen zu lassen - eine andere Perspektive/Instruktion statt
        # exakter Wiederholung.
        escalation_attempted = False
        # Team-Optimierung (Retrospektive 2026-09-05, Punkt 3): core/backlog_worker.py eskaliert
        # bereits beim ZWEITEN automatischen Retry eines liegen gebliebenen Governance-/
        # Verifikations-Tickets auf HEAVY_MODEL (Orchestrator(escalate_models=True)) - aber ERST
        # in einem SEPARATEN, späteren Lauf. Real beobachtet (workspace/zeiterfassung_app,
        # 2026-09-04): drei komplette, eigenständige Läufe an demselben Projekt, bevor der Fehler
        # behoben war - jeder einzelne davon wiederholte innerhalb sich selbst nur "derselbe
        # Agent, dann der Fachbereichsleiter", beide mit dem UNVERÄNDERTEN Standard-Modell. Bevor
        # DIESER Lauf komplett aufgibt und ein Ticket für einen erst viel später folgenden
        # Backlog-Retry eröffnet, wird deshalb - GENAU EINMAL pro Lauf, NUR für die tatsächlich
        # betroffenen Agenten (kein pauschales Hochstufen aller 33 Fachagenten) - ein letzter
        # Versuch mit HEAVY_MODEL unternommen. Das verkürzt den in zeiterfassung_app real
        # beobachteten Drei-Lauf-Kreislauf im Idealfall auf einen einzigen Lauf.
        model_escalation_attempted = False
        # Defensiv vorinitialisiert (nicht nur im escalation_attempted-Zweig unten): bei einem
        # per Env auf >2 hochgesetzten MAX_VERIFICATION_ITERATIONS kann der "kein Fortschritt"-
        # Zweig ein zweites Mal greifen, NACHDEM escalation_attempted schon True ist - top_failures
        # würde dann sonst nie (neu) berechnet, aber unten beim Ticket-Text referenziert.
        top_failures = ""
        # Ebenso defensiv vorinitialisiert: wird das Budget bereits VOR der ersten Eskalation
        # überschritten (run_start_tokens-Check oben), bleibt der gesamte
        # "if not escalation_attempted and not (...)"-Zweig ungelaufen und stuck_owners würde
        # nie gesetzt - der direkt danach folgende Check "if not model_escalation_attempted and
        # stuck_owners" würde dann mit einem NameError crashen (real möglich bei knappem
        # Token-Budget + fehlenden betroffenen Dateien, z.B. bei `npm test`-Fehlern ohne
        # zuordenbare Datei). Ein leeres Set ist hier bewusst "kein stecken gebliebener Owner
        # gefunden" statt eines Absturzes.
        stuck_owners: set = set()
        # Cross-Run-Gedächtnis (Team-Retrospektive nach dem taskpulse-Lauf, zweite Runde): ein
        # offenes Ticket aus einem VORHERIGEN Lauf desselben Projekts fließt als Kontext in den
        # ERSTEN Fix-Auftrag dieses Laufs ein (siehe _prior_run_context()) - und wird, sobald
        # die Testsuite in DIESEM Lauf tatsächlich grün wird, als gelöst geschlossen, statt als
        # "blocked" liegen zu bleiben, obwohl das Problem längst behoben ist.
        test_ticket_id = f"recurring-failure-{self.last_project_slug}" if self.last_project_slug else None
        try:
            had_prior_test_ticket = bool(test_ticket_id and get_ticket(test_ticket_id) is not None)
        except Exception:
            had_prior_test_ticket = False

        # Deterministischer Pre-Flight-Check: ast-basiert, blitzschnell vor isolierter Testsuite.
        # Erkennt fehlende __init__.py, Syntax-Fehler und nicht deklarierte Abhängigkeiten in
        # requirements.txt.
        #
        # Realer Fund (Analyse 2026-09-06): core/pre_flight_check.py wurde eingeführt, aber nur
        # für eine reine Notify-Anzeige verdrahtet - format_pre_flight_issues_for_fix() (extra
        # dafür geschrieben) und has_blocking_issues wurden nie aufgerufen, jeder Fund blieb
        # bis zum teuren, isolierten Testlauf liegen statt sofort behoben zu werden, obwohl er
        # in Millisekunden ohne LLM erkannt wurde. Jetzt derselbe gezielte Fix-und-Retry-Loop
        # (Owner-Routing über file_owners, Kein-Fortschritt-Zirkuitbrecher) wie beim Vorab-
        # Import-Check direkt darunter.
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

            # Zuständigkeits-Fallback (Team-Optimierung, echter Fund: Pre-Flight-Befunde ohne
            # bekannten file_owners-Eintrag blieben bisher komplett unbeauftragt liegen und
            # landeten als Dauer-Blocker im recurring-failure-*-Backlog-Ticket, ohne dass je ein
            # Agent den Fix übernahm. Statt den Fund stillschweigend fallen zu lassen: Format-/
            # Lint-/Import-Funde (missing_init = fehlende __init__.py, hidden_runtime_dependency
            # = Import ohne deklarierte Abhängigkeit) gehen an project_cleaner (räumt Struktur/
            # Imports auf), reine Dependency-Manifest-Lücken (missing_dependency) an refactoring
            # (pflegt requirements.txt/pyproject.toml), alle übrigen echten Code-Probleme
            # (syntax_error u.ä.) an dev_lead als Auffangzuständigkeit für Code-Fehler.
            _FALLBACK_OWNER_BY_ISSUE_TYPE = {
                "missing_init": "project_cleaner",
                "hidden_runtime_dependency": "project_cleaner",
                "missing_dependency": "refactoring",
                "syntax_error": "dev_lead",
                # Team-Optimierung (KI-Team-Zustandsbericht 2026-09-08): "empty_test_suite"
                # (core/pre_flight_check.py._check_empty_test_suite) meldet ein tests/-
                # Verzeichnis ohne eine einzige echte Testfunktion - kein Code-/Import-Problem,
                # sondern fehlende Testabdeckung. `tester` (nicht dev_lead) schreibt bereits
                # regulär die gesamte Testsuite und ist damit der fachlich richtige Owner.
                "empty_test_suite": "tester",
            }
            # Deterministischer Kurzschluss für "missing_dependency": ein exakt benanntes,
            # fehlendes PyPI-Paket (z.B. `alembic`, `asyncpg`, `greenlet` - realer Fund
            # auditlog_sentinel 2026-09-10, dreimal derselbe Fehlerklasse) wird direkt in
            # requirements.txt eingetragen, OHNE einen LLM-Agenten zu beauftragen - schneller,
            # günstiger und ohne das Risiko einer parallelen Überschreibung des Manifests.
            # Test-/Werkzeugpakete (pytest, locust, ...) bzw. Pakete, die nur aus Testdateien
            # importiert werden, landen in requirements-dev.txt (core/dependency_manifest.
            # manifest_for_package) - sonst blähen sie die Produktions-Abhängigkeiten auf.
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

            agents_to_fix: dict[str, list[PreFlightIssue]] = {}
            for issue in remaining_issues:
                owner = file_owners.get(issue.file)
                if not owner or owner not in self._agents:
                    owner = _FALLBACK_OWNER_BY_ISSUE_TYPE.get(issue.issue_type, "dev_lead")
                if owner in self._agents:
                    agents_to_fix.setdefault(owner, []).append(issue)

            if not agents_to_fix:
                if not remaining_issues:
                    # Alle Funde deterministisch behoben (siehe oben) - direkt erneut prüfen,
                    # statt fälschlich "ungelöst" zu melden.
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
            notify(f"  📦 {install_log.splitlines()[0]}")
            summary_lines.append(f"- 📦 {install_log.splitlines()[0]}")
        install_exit_code = parse_install_exit_code(install_log or "")
        outcome.record(
            "deps_install",
            None if install_exit_code is None else install_exit_code == 0,
            f"exit_code={install_exit_code}" if install_exit_code is not None else "",
        )

        # Vorab-Check (statt Vollständigkeits-Check erst NACH der teuren Testsuite/Governance-
        # Schleife, siehe unten): ein fehlendes lokales Python-Modul (z.B. `app/models.py`, das
        # per `from . import database, models, schemas` referenziert wird) ist rein statisch,
        # ohne jeden Testlauf, in Millisekunden erkennbar (core/verifier/completeness.py.
        # _missing_local_python_imports) - beim taskpulse-Lauf wurde genau dieser Fund erst nach
        # der vollständigen Test-/Governance-/Review-Kaskade sichtbar (33 Agenten-Durchläufe,
        # 714k Tokens, 23 Minuten), obwohl er von Anfang an feststand. Läuft NUR gegen
        # Import-Auflösungs-Funde (nicht den vollen Vollständigkeits-Check inkl. Stub-Marker/
        # fehlender I/O - die bleiben bewusst beim regulären, späteren Durchlauf, der zusätzlich
        # den frischen Testlauf mitprüft), maximal MAX_VERIFICATION_ITERATIONS Versuche wie jede
        # andere Fix-Schleife hier.
        if ENABLE_COMPLETENESS_CHECK and not (budget_aborted or manually_cancelled):
            # Derselbe Zirkuit-Breaker wie in den übrigen Fix-Schleifen dieser Datei (Team-
            # Retrospektive nach dem taskpulse-Lauf) - identische Import-Funde nach einem
            # Fixversuch bedeuten fast immer, dass der Agent das Problem nicht lösen konnte.
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
                # Dieselbe Reihenfolge (erst .attempted, DANN .passed, bevor .issues überhaupt
                # angefasst wird) wie der bestehende Vollständigkeits-Check weiter unten - hält
                # Tests, die ProjectVerifier komplett mocken, ohne check_completeness() explizit
                # zu konfigurieren, unverändert lauffähig (ein MagicMock().passed ist truthy,
                # ein MagicMock().issues wäre dagegen nicht iterierbar und würde crashen).
                if not pre_report.attempted or pre_report.passed:
                    break
                # Team-Optimierung (vollständige Umsetzung einer KI-Team-Retrospektive, echter
                # Fund am event_relay-Lauf 2026-09-06): dieselbe fragile Substring-Suche wie
                # oben (structural_import_issues) - core/verifier/models.py.CompletenessIssue.
                # kind == "missing_local_import" erfasst jetzt auch einen fehlenden SYMBOL-Import
                # (z.B. `from app.resilience import resilience`), den die alte Suche nach
                # "existierendes lokales" NIE fand, obwohl check_completeness() ihn bereits
                # korrekt erkannte - der Vorab-Check brach damit still ab, statt den längst
                # erkannten Fund zur Korrektur weiterzureichen.
                import_issues = [i for i in pre_report.issues if i.kind == "missing_local_import"]
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
                notify(f"  🧩 [bold red]Vorab-Import-Check: {len(import_issues)} fehlende(s) lokale(s) Modul/Symbol VOR jedem Testlauf gefunden.[/bold red]")

                # Derselbe Zuständigkeits-Fallback wie beim Pre-Flight-Check oben: ein fehlendes
                # lokales Modul/Symbol ist immer ein Code-Problem, nie ein Format-/Lint-Fund -
                # ohne bekannten file_owners-Eintrag geht der Fund deshalb an dev_lead statt
                # unbeauftragt liegen zu bleiben.
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
                            "gefunden, die auf nicht existierende Dateien/Symbole verweisen - der Code kann "
                            "dadurch nicht einmal importiert werden. Lege die fehlende(n) Datei(en) mit "
                            "echtem Inhalt an bzw. ergänze das fehlende Symbol in der genannten Datei.\n\n"
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
        # Team-Optimierung (KI-Team-Masterplan, Stufe 2): Der Runtime-Smoke-Test lief bisher
        # ERST NACH der kompletten Testschleife (siehe check_runtime_smoke weiter unten). Der
        # `tester` ist mit 78 Aufrufen der meistgerufene und mit 65,4% der schwächste
        # Kern-Agent - und ein Großteil dieser Fehlschläge entsteht, weil die Anwendung
        # überhaupt nicht startet. Eine vollständige Testsuite gegen eine App zu schreiben und
        # auszuführen, die schon beim Import scheitert, erzeugt nur Folgefehler: Jeder einzelne
        # Test schlägt aus derselben Ursache fehl, die Fix-Schleife bekommt einen Berg
        # scheinbar unabhängiger Fehler und verbrennt Token an Symptomen statt an der Ursache.
        # Genau das erklärt die teuren Fehlläufe (opspilot: 1.038.910 Tokens, agent_governance:
        # 999.313 - beide ohne bestandene Verifikation).
        #
        # Deshalb VOR der Testschleife: Startet die App nicht, wird genau dieser eine Fehler
        # gezielt behoben, bevor irgendetwas anderes passiert.
        if ENABLE_SMOKE_TEST_GATE and not (budget_aborted or manually_cancelled):
            smoke_gate_summary = await self._run_smoke_test_gate(
                verifier=verifier, project_dir=project_dir, all_results=all_results,
                file_owners=file_owners, notify=notify,
            )
            summary_lines.extend(smoke_gate_summary)

        test_depth_fix_attempted = False
        for attempt in range(1, MAX_VERIFICATION_ITERATIONS + 1):
            if cancel_requested and cancel_requested():
                manually_cancelled = True
                notify("  ⏹️ [bold red]Lauf manuell abgebrochen[/bold red] – weitere Verifikations-/Fixversuche werden übersprungen.")
                summary_lines.append(f"- ⏹️ Manuell abgebrochen – Verifikation nach Versuch {attempt - 1} beendet.")
                break

            # Team-Optimierung (Analysebericht `ki_team_schwachstellen_und_fehleranalyse_
            # aethermesh_20260913.md`, Schwachstelle 3): das Budget darf NEUE, tokenkostende
            # Fix-Agent-Aufträge blockieren, aber NIEMALS einen reinen lokalen Testlauf - pytest
            # selbst verbraucht 0 LLM-Tokens. Vorher brach die Schleife HIER, VOR dem Testlauf,
            # sofort ab, sobald das Budget (inkl. 10%-Puffer) überschritten war - selbst wenn ein
            # Fix-Agent im vorherigen Versuch seinen Fix bereits erfolgreich ins Dateisystem
            # geschrieben hatte (realer Fund: AetherMesh-Lauf, `budget_aborted: true` trotz
            # bereits vorhandener, funktionierender pytest.ini). Das Projekt wurde dadurch
            # fälschlich als gescheitert gewertet, obwohl ein kostenloser Re-Test es als grün
            # bestätigt hätte. `budget_aborted` wird daher nur noch gesetzt und erst NACH dem
            # Testlauf ausgewertet (siehe unten, vor dem Dispatch neuer Fix-Agenten).
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

            if not report.ran:
                if not report.passed:
                    # Realer Fund (Workspace-Audit): ein mehrteiliges Backend-Projekt ohne jeden
                    # Einstiegspunkt bzw. eine Testsuite mit conftest.py, aber ohne echte Testdatei,
                    # sah bisher genauso aus wie "keine Tests gefunden" und lief als vermeintlich
                    # bestandene Verifikation durch – core/verifier.py.ProjectVerifier erkennt das
                    # jetzt als eigenständigen Fehlschlag statt als bloßes "nicht geprüft".
                    notify(f"  ❌ [bold red]{report.reason_skipped}[/bold red]")
                    summary_lines.append(f"- ❌ {report.reason_skipped}")

                    # Team-Optimierung (Retrospektive, zeiterfassung_app-Lauf): "conftest.py ohne
                    # jede echte Testdatei" wurde bisher zwar korrekt als Fehlschlag ERKANNT, aber
                    # nie ein Fix dafür ausgelöst - der Zweig endete direkt in `break`, anders als
                    # der Nachbar-Zweig weiter unten ("keine Tests gefunden" bei report.passed=True),
                    # der den tester gezielt nachbeauftragt. Ergebnis: das Projekt blieb dauerhaft
                    # ohne lauffähige Testsuite, obwohl die Ursache (fehlende Testdatei, kein
                    # fehlender Einstiegspunkt) für den tester-Agenten genauso behebbar gewesen wäre
                    # wie im Nachbar-Fall. Derselbe EINE Nachbeauftragungs-Versuch (no_tests_fix_
                    # attempted-Zirkuit-Breaker) wie dort, NUR für die Testdatei-Variante des Befunds
                    # - eine fehlende Einstiegspunkt-Datei (main.py/app.py/...) ist kein Testsuite-
                    # Problem und bleibt bewusst unangetastet, damit der tester nicht fälschlich mit
                    # einer Aufgabe beauftragt wird, die architect/backend lösen müssten.
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
                # Bewusst ⚠️ statt ℹ️: "keine Tests gefunden" bedeutet, dass generierter Code
                # UNGEPRÜFT ausgeliefert wird – real beobachtet an einem Taschenrechner-Projekt
                # ohne jeden Test, dessen "+"-Button sofort mit TypeError abstürzte (Add.execute()
                # verlangte zwei Argumente, die GUI übergab nur eines). DECOMPOSE_SYSTEM_PROMPT
                # (core/task_manager.py) weist das Modell inzwischen an, den tester-Agenten bei
                # echter Programmlogik einzubeziehen - reicht aber nicht immer (real beobachtet
                # am incidentpilot-Projekt: tester blieb ganz ohne Testdatei, statt hier nur
                # sichtbar zu bleiben, wird jetzt EIN gezielter Nachbeauftragungs-Versuch
                # unternommen, bevor endgültig aufgegeben wird.
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
                    and "tester" in self._agents and attempt < MAX_VERIFICATION_ITERATIONS
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
                    continue
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
            if _no_progress(previous_failure_signature, current_signature):
                escalated_and_resolved = False
                try:
                    if not escalation_attempted and not (
                        run_start_tokens is not None and (
                            self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
                        )
                    ):
                        escalation_attempted = True
                        stuck_owners = {
                            file_owners[f]
                            for failure in (report.failures or [])
                            for f in (failure.files or [])
                            if isinstance(f, str) and f in file_owners
                        } & set(self._agents.keys())
                        lead_targets = {
                            dept_id for dept_id, defn in DEPARTMENT_DEFINITIONS.items()
                            if stuck_owners & set(defn["members"]) and dept_id in self._dept_leads
                        }
                        top_failures = "\n\n".join(
                            f"Test: {f.test_id}\nFehlermeldung: {f.message}\nBetroffene Dateien: {', '.join(str(x) for x in (f.files or [])) or 'unbekannt'}"
                            for f in report.failures[:5]
                        )
                        if lead_targets:
                            notify(
                                f"  🔀 [bold yellow]Strategiewechsel (Eskalation):[/bold yellow] Derselbe Fehler nach "
                                f"einem wirkungslosen Fixversuch – ziehe Fachbereichsleiter "
                                f"({', '.join(sorted(lead_targets))}) statt derselben Wiederholung hinzu..."
                            )
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
                            # WICHTIG: das Ergebnis der Eskalation wird HIER SOFORT per echtem
                            # Testlauf geprüft (nicht über `continue` in die äußere Schleife
                            # zurückgereicht) - ein `continue` würde einen der ohnehin knappen
                            # MAX_VERIFICATION_ITERATIONS-Versuche für die Eskalation selbst
                            # verbrauchen und im letzten erlaubten Versuch dazu führen, dass die
                            # Schleife nach der Eskalation kommentarlos endet, OHNE das Scheitern
                            # zu melden oder ein Ticket zu eröffnen (so beim ersten Implementierungs-
                            # versuch real per Test aufgedeckt, siehe
                            # tests/test_verification_no_progress_breaker.py).
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

                        # Team-Optimierung (Retrospektive 2026-09-05, Punkt 3): letzter Versuch VOR
                        # dem endgültigen Aufgeben - dieselben stecken gebliebenen Agenten (NICHT die
                        # Fachbereichsleiter, die haben es gerade erst versucht) bekommen für GENAU
                        # diesen einen Fix-Auftrag ein stärkeres Modell (HEAVY_MODEL), statt den Fehler
                        # unverändert in ein Ticket zu schieben, das ohnehin erst bei einem viel
                        # späteren Backlog-Retry (core/backlog_worker.py) dieselbe Eskalation bekäme.
                        if not model_escalation_attempted and stuck_owners:
                            model_escalation_attempted = True
                            escalated_agent_ids = self._escalate_agent_models(stuck_owners)
                            if escalated_agent_ids:
                                notify(
                                    f"  ⬆️ [bold yellow]Letzter Versuch mit stärkerem Modell:[/bold yellow] "
                                    f"{', '.join(sorted(escalated_agent_ids))} laufen für diesen Fix-Auftrag "
                                    "auf HEAVY_MODEL, statt direkt aufzugeben."
                                )
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
                                        context="", project_dir=project_dir,
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
                # Persistentes Lernen (siehe _record_verification_learning) für künftige Läufe
                # desselben Agenten - bewusst außerhalb der seiteneffektfreien Routing-Funktion.
                # Bei Schnittstellen-Drift liegt der Fehler beim Konsumenten, die Backend-Regel
                # ("Symbol im Zielmodul definieren") wäre dann eine falsche Lektion.
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

            fix_tasks = []
            for agent_id, fails in agents_to_fix.items():
                failure_text = "\n\n".join(
                    f"Test: {f.test_id}\nFehlermeldung: {f.message}\nBetroffene Dateien: {', '.join(str(x) for x in (f.files or [])) or 'unbekannt'}"
                    + (f"\n{diag}" if (diag := _failure_diagnosis(f.message, triages.get(id(f)))) else "")
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
                        + (_prior_run_context(test_ticket_id) if attempt == 1 and test_ticket_id else "")
                    ),
                    context="",
                    project_dir=project_dir,
                    max_tool_iterations=8,
                ))

            notify(f"  🛠️ [bold yellow]Gezielter Auto-Fix:[/bold yellow] Beauftrage {', '.join(agents_to_fix.keys())} (nicht blind alle Dev-Agenten)...")
            # Reine Strukturfehler sind nie durch Manifest-Änderungen zu beheben (realer Fehl-Loop:
            # refactoring editierte requirements.txt bei einem ImportError) - Manifeste werden
            # deshalb gesichert und nach dem Fix-Schritt zurückgesetzt.
            structural_only = all(triages.get(id(f)) is not None for fails in agents_to_fix.values() for f in fails)
            manifest_snapshot = snapshot_dependency_manifests(project_dir) if project_dir and structural_only else None
            fix_results = await self._run_agents_parallel(fix_tasks, notify=notify)
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
            # Nur re-syncen, wenn die Manifest-Änderung tatsächlich bestehen blieb (siehe oben) -
            # bei einem Rücksetzer entspricht die Umgebung bereits wieder dem installierten Stand.
            if not restored_manifests:
                await self._resync_environment_if_dependencies_changed(verifier, fix_results, notify, summary_lines)
            summary_lines.append(f"- 🛠️ Versuch {attempt}: {len(report.failures)} echte Testfehler → gezielt zur Korrektur an {', '.join(agents_to_fix.keys())} zurückgespielt.")

            if attempt == MAX_VERIFICATION_ITERATIONS:
                # Fehleranalyse ki_team_fehleranalyse_zusammenfassung.md: die Schleife oben ruft
                # _run_tests_logged() NUR am ANFANG jedes Versuchs auf (Zeile "erstlauf") - im
                # LETZTEN erlaubten Versuch verbraucht der `range()` danach keinen weiteren
                # Schleifendurchlauf mehr, der Fix des letzten Versuchs wurde also NIE gegen die
                # echte Testsuite geprüft, bevor unten das Ticket eröffnet und der Lauf als
                # fehlgeschlagen gewertet wurde - selbst wenn der Fix tatsächlich griff. Eine
                # einzelne zusätzliche Abschlussprüfung schließt genau diese Lücke, bevor endgültig
                # aufgegeben wird.
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
                        break
                    report = post_fix_report

                notify("  ⚠️ [yellow]Maximale Verifikations-Iterationen erreicht – letzter Stand wird übernommen.[/yellow]")
                summary_lines.append(f"- ⚠️ Nach {MAX_VERIFICATION_ITERATIONS} Versuchen nicht vollständig grün – letzter Stand wurde übernommen.")
                # Realer Fund (Team-Retrospektive, omnichat-Projekt): bisher wurde ein nach
                # MAX_VERIFICATION_ITERATIONS aufgegebener Testfehlschlag NUR geloggt - kein
                # Backlog-Ticket, keine sonstige Eskalation. Die bereits bestehende
                # `has_repeated_failure`-Eskalation in agents/orchestrator/__init__.py greift
                # erst NACH zwei aufeinanderfolgenden kompletten Läufen - hier wird bereits
                # beim ERSTEN Scheitern innerhalb dieses einen Laufs ein Ticket eröffnet
                # (upsert_ticket, dieselbe Ticket-ID wie ein etwaiges späteres wiederholtes
                # Scheitern würde erzeugen, damit beide Pfade dasselbe Ticket aktualisieren
                # statt Duplikate anzulegen), statt auf einen zweiten fehlgeschlagenen Lauf
                # zu warten, bevor überhaupt ein sichtbares Signal für menschliche Prüfung
                # entsteht.
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

        # Strukturiertes Testergebnis (core/verification_outcome.py): verification_ok spiegelt an
        # dieser Stelle ausschließlich die Kern-Testsuite wider - nachgelagerte Prüfungen setzen es
        # ggf. später zurück, ohne das Testergebnis selbst zu verfälschen.
        if report is not None:
            if report.ran or verification_ok:
                outcome.record("tests", verification_ok, "" if verification_ok else f"{len(report.failures)} Testfehler")
            elif not report.passed:
                outcome.record("tests", False, report.reason_skipped or "")
            else:
                outcome.record("tests", None, report.reason_skipped or "keine Tests ausgeführt")

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
                outcome.record("docker_build", docker_report.success)
                if docker_report.success:
                    notify("  🐳 [bold green]Docker-Image baut erfolgreich.[/bold green]")
                    summary_lines.append("- 🐳 Docker-Image baut erfolgreich (echter `docker build`).")
                else:
                    notify("  🐳 [bold red]Docker-Build fehlgeschlagen.[/bold red]")
                    summary_lines.append(f"- 🐳 ❌ Docker-Build fehlgeschlagen: {docker_report.output[:500]}")
            elif docker_report.reason_skipped and "Daemon" in docker_report.reason_skipped:
                # Sichtbar (anders als "kein Dockerfile"/"Docker nicht installiert"), weil diese
                # Ursache sonst leicht mit einem echten, im Dockerfile liegenden Fehler verwechselt
                # wird - siehe _DOCKER_DAEMON_UNAVAILABLE_RE (core/verifier/models.py).
                notify(f"  🐳 [dim yellow]{docker_report.reason_skipped}[/dim yellow]")
                summary_lines.append(f"- 🐳 ⏭️ {docker_report.reason_skipped}")

        # Realer Fund (auditlog_sentinel, 2026-09-10): core/verifier/runtime.py.check_frontend_build()
        # (echter `npm run build`) existierte bereits, wurde aber NIRGENDS aus der Verifikation
        # aufgerufen - ein React/Vite-Frontend, das nie tatsächlich baute, bestand die Verifikation
        # trotzdem. Der Browser-UI-Check unten servierte danach die ROHE `main.tsx` statisch,
        # der Browser brach mit "Expected a JavaScript-or-Wasm module script but the server
        # responded with a MIME type of text/plain" ab - ein Fehler, der wie ein Frontend-Bug
        # aussah, obwohl es ein fehlender Build-Schritt war. Läuft VOR dem Browser-UI-Check, damit
        # core/browser_verifier.py bereits den echten `dist/`-Output servieren kann.
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

        # Informative Prüfschritte (Dependency-Audit, SAST, Lizenzen, Lint) - ausgelagert in
        # agents/orchestrator/verification_checks.py; beeinflussen verification_ok nicht.
        # last_lint_signature/last_lint_attempted: siehe core/project_status.has_repeated_lint_finding()
        # und das automatische Schließen von recurring-lint-Tickets in agents/orchestrator/__init__.py.
        self.last_lint_signature: list[str] = []
        self.last_lint_attempted: bool = False
        if not (budget_aborted or manually_cancelled):
            check_ctx = await run_informational_checks(
                CheckContext(verifier=verifier, outcome=outcome, notify=notify, summary_lines=summary_lines)
            )
            self.last_lint_signature = check_ctx.lint_signature
            self.last_lint_attempted = check_ctx.lint_attempted

        # Vollständigkeits-Check: erkennt Stub-/Platzhalter-Code (z.B. "Hier würde die
        # Verschlüsselung erfolgen") und im README referenzierte, aber fehlende Dateien (z.B.
        # requirements.txt) - siehe core/verifier/completeness.py und ENABLE_COMPLETENESS_CHECK
        # (config.py) für den vollständigen Kontext. Anders als Lint/SAST blockiert ein Fund
        # hier verification_ok, weil ein Stub-Kommentar eine nicht erfüllte fachliche
        # Anforderung ist, kein Stil-Hinweis - deshalb dieselbe gezielte Fix-Schleife wie beim
        # echten Testfehler oben, statt nur eine informative Zeile im Protokoll.
        if ENABLE_COMPLETENESS_CHECK and not (budget_aborted or manually_cancelled):
            # Derselbe Zirkuit-Breaker wie in der Test-Fix- und der Governance-Fix-Schleife
            # (Team-Retrospektive nach dem taskpulse-Lauf): identische Vollständigkeits-Funde
            # nach einem Fixversuch bedeuten fast immer, dass der Agent das Problem nicht lösen
            # konnte - ein zweiter, identischer Fix-Dispatch wäre reine Verschwendung.
            previous_completeness_signature: frozenset[tuple[str, str]] | None = None
            for attempt in range(1, MAX_VERIFICATION_ITERATIONS + 1):
                if run_start_tokens is not None and (
                    self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
                ):
                    budget_aborted = True
                    notify("  🚫 [bold red]Budget erreicht[/bold red] – weitere Vollständigkeits-Fixversuche werden übersprungen.")
                    summary_lines.append(f"- 🚫 {self._budget_exceeded_label(run_start_tokens)} erreicht – Vollständigkeits-Check nach Versuch {attempt - 1} abgebrochen.")
                    break
                if cancel_requested and cancel_requested():
                    manually_cancelled = True
                    notify("  ⏹️ [bold red]Lauf manuell abgebrochen[/bold red] – weitere Vollständigkeits-Fixversuche werden übersprungen.")
                    summary_lines.append(f"- ⏹️ Manuell abgebrochen – Vollständigkeits-Check nach Versuch {attempt - 1} beendet.")
                    break

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

                current_completeness_signature = _issue_signature(
                    completeness_report.issues, lambda i: (i.file_path, i.message[:300]),
                )
                if _no_progress(previous_completeness_signature, current_completeness_signature):
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

        # Realer Fund bei einer Bestandsaufnahme des eigenen Teams: die Verifikation misst
        # bisher nur Pass/Fail, keine Abdeckung - ein Projekt mit 3 bestandenen Tests bei 500
        # Zeilen ungetestetem Code gilt genauso als "verifiziert" wie eines mit echter
        # Abdeckung. Opt-in über MIN_TEST_COVERAGE (Standard 0 = deaktiviert, siehe config.py) -
        # nur sinnvoll, wenn die Testsuite überhaupt gelaufen UND bestanden ist (report kann
        # None sein, wenn die Schleife oben nie durchlief, z.B. MAX_VERIFICATION_ITERATIONS<=0).
        if not (budget_aborted or manually_cancelled) and MIN_TEST_COVERAGE > 0 and report is not None and report.ran and report.passed:
            coverage_report = await asyncio.to_thread(verifier.check_coverage)
            if coverage_report.attempted:
                self.last_coverage_percent = coverage_report.percent
                outcome.record("coverage", coverage_report.percent >= MIN_TEST_COVERAGE, f"{coverage_report.percent}%")
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
                    _grund = f"Testabdeckung {coverage_report.percent}% liegt unter der konfigurierten Schwelle von {MIN_TEST_COVERAGE}%."
                    notify(f"  ❌ [bold red]Verifikations-Veto durch Coverage-Check:[/bold red] {_grund}")
                    summary_lines.append(f"- ❌ **Verifikations-Veto durch Coverage-Check:** {_grund}")

        # Runtime Smoke-Check: Prüft, ob die generierte App tatsächlich hochfährt / antwortet (Tests grün != App startet)
        #
        # Team-Optimierung (Retrospektive 2026-09-04): bisher lief dieser Check nur bei
        # report.passed - also GENAU DANN NICHT, wenn die Testsuite nach MAX_VERIFICATION_
        # ITERATIONS-Versuchen weiterhin rot blieb und "der letzte Stand übernommen" wurde
        # (siehe Zweig oben, `verify_fix_test`-Schleife). Real beobachtet an `zeiterfassung_
        # app`: genau in diesem Fall blieb ein simpler ImportError (Klassenname-Mismatch
        # zwischen main.py-Import und der tatsächlichen Middleware-Klasse) unentdeckt, bis ihn
        # ein SPÄTERER Governance-Review-Lauf per Code-Lesen fand - der automatisierte Smoke-
        # Test hätte ihn sofort UND günstiger gefunden. `report.ran` bleibt Voraussetzung (ohne
        # jeden Testlauf ist z.B. auch keine Dependency-Installation gesichert, gegen die
        # `check_runtime_smoke()` starten könnte), `report.passed` nicht mehr.
        if not (budget_aborted or manually_cancelled) and report is not None and report.ran:
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
            budget_aborted = budget_aborted or sb_aborted
            manually_cancelled = manually_cancelled or sb_cancelled
            if smoke_report.attempted:
                outcome.record("smoke", bool(smoke_report.passed), "" if smoke_report.passed else (smoke_report.output or "")[:300])
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
                    _grund = f"`{smoke_report.entrypoint}` [{smoke_report.app_type}] startet nicht{err}."
                    notify(f"  ❌ [bold red]Verifikations-Veto durch Runtime-Smoke-Test:[/bold red] {_grund}")
                    summary_lines.append(f"- ❌ **Verifikations-Veto durch Runtime-Smoke-Test:** {_grund}")

        # Lastentest: führt vom performance-Agenten geschriebene k6-/Locust-Skripte (tests/load/)
        # tatsächlich AUS statt sie nur unausgeführt im Projekt liegen zu lassen - startet die
        # App und lässt einen kurzen Smoke-Lasttest (wenige Sekunden, wenige virtuelle Nutzer)
        # dagegen laufen. Rein informativ wie Lint/SAST (kein Performance-Benchmark, keine
        # Kapazitätsaussage) - EXCEPT ein fehlgeschlagener Request ist wie beim Runtime-Smoke-
        # Test eine echte Anforderungsverletzung (die App crasht/fehlerantwortet unter simultaner
        # Last), kein reiner Stil-Hinweis. In der Praxis für die meisten Projekte ein No-Op
        # (braucht ein Skript unter tests/load/ UND das jeweilige Tool lokal installiert).
        if ENABLE_LOAD_TEST_CHECK and not (budget_aborted or manually_cancelled) and report is not None and report.ran and report.passed:
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
            budget_aborted = budget_aborted or lb_aborted
            manually_cancelled = manually_cancelled or lb_cancelled
            if perf_report.attempted:
                outcome.record("load_test", bool(perf_report.passed))
                stats = f"{perf_report.total_requests} Requests, {perf_report.failed_requests} fehlgeschlagen"
                # isinstance() statt "is not None": ein Test, der ProjectVerifier komplett mockt,
                # aber check_load_test() nicht explizit auf ein PerfCheckReport setzt (wie bei
                # check_docker_build/check_runtime_smoke gibt es hier keinen sicheren MagicMock-
                # Default), liefert für p95_ms sonst ein MagicMock-Objekt statt None - das würde
                # an der ":.0f"-Formatierung mit TypeError crashen. isinstance() ist für den
                # echten Produktivpfad (p95_ms ist dort immer float|None) gleichwertig, macht den
                # Codepfad aber robust gegen unvollständig gemockte Verifier in Tests.
                if isinstance(perf_report.p95_ms, (int, float)):
                    stats += f", p95={perf_report.p95_ms:.0f}ms"
                if perf_report.passed:
                    notify(f"  🏋️ [bold green]Lastentest ({perf_report.tool}) bestanden:[/bold green] `{perf_report.script}` [{stats}].")
                    summary_lines.append(f"- 🏋️ Lastentest ({perf_report.tool}) bestanden: `{perf_report.script}` [{stats}].")
                else:
                    notify(f"  🏋️ [bold red]Lastentest ({perf_report.tool}) fehlgeschlagen:[/bold red] `{perf_report.script}` [{stats}].")
                    summary_lines.append(f"- 🏋️ ❌ Lastentest ({perf_report.tool}) fehlgeschlagen: `{perf_report.script}` [{stats}].")
                    verification_ok = False
                    _grund = f"Lastentest ({perf_report.tool}) fehlgeschlagen: `{perf_report.script}` [{stats}]."
                    notify(f"  ❌ [bold red]Verifikations-Veto durch Lastentest:[/bold red] {_grund}")
                    summary_lines.append(f"- ❌ **Verifikations-Veto durch Lastentest:** {_grund}")

        # Browser / Frontend UI-Check: Prüft statische Assets, Rendering und JS-Konsolenfehler.
        # Realer Fund (Pong-Projekt): ein Fehlschlag hier war bisher rein informativ und
        # beeinflusste verification_ok NICHT - ein Frontend, das im echten Browser mit einem
        # JS-Fehler crasht oder ein <canvas> nie tatsächlich zeichnet (siehe blank_canvases,
        # core/browser_verifier.py), bestand die Verifikation trotzdem. Das war eine bewusste
        # Design-Entscheidung analog zu Lint/SAST - für ein Frontend-Projekt ist dieser Check
        # aber oft die EINZIGE Instanz, die überhaupt echten Browser-Code ausführt (Unit-Tests
        # wie im Pong-Fall mockten Canvas/DOM komplett weg), nicht nur ein Stil-Hinweis wie ein
        # Lint-Fund. Ein echter Fehlschlag zählt deshalb jetzt wie beim Lastentest/Runtime-
        # Smoke-Test oben als echte Anforderungsverletzung.
        if not (budget_aborted or manually_cancelled):
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
            budget_aborted = budget_aborted or br_aborted
            manually_cancelled = manually_cancelled or br_cancelled
            if browser_report.attempted:
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
                        # static_dom-Fallback: prüft NUR, ob referenzierte Dateien existieren -
                        # es läuft dabei KEIN JavaScript. Ein grüner static_dom-Pass sah bisher
                        # optisch identisch zu einem echten Playwright-Pass aus (nur der kleine
                        # "[engine]"-Zusatz unterschied sie) - genau der fehlende Kontrast, der
                        # einen kaputten Bootstrap (fehlendes type="module", kein Game-Loop) als
                        # "geprüft und ok" durchgehen ließ, obwohl nie echter Code lief.
                        notify(f"  🌐 [bold yellow]Frontend/UI-Check eingeschränkt:[/bold yellow] `{browser_report.tested_url}` [static_dom] - kein echter Browser installiert, JavaScript wurde NICHT ausgeführt (nur Dateiexistenz geprüft).")
                        summary_lines.append(f"- 🌐 ⚠️ Frontend/UI-Check nur eingeschränkt (`static_dom`, `{browser_report.tested_url}`): referenzierte Dateien existieren, aber JavaScript lief NICHT in einem echten Browser (Playwright fehlt/nicht nutzbar) - Laufzeitfehler bleiben so unentdeckt.")
                else:
                    details = browser_report.missing_assets + browser_report.console_errors + [
                        f"Canvas nie gezeichnet: {c}" for c in browser_report.blank_canvases
                    ]
                    err_details = "; ".join(details)[:150]
                    notify(f"  🌐 [bold red]Frontend/UI-Check fehlgeschlagen:[/bold red] {err_details}.")
                    summary_lines.append(f"- 🌐 ❌ Frontend/UI-Check fehlgeschlagen: {err_details}.")
                    verification_ok = False
                    notify(f"  ❌ [bold red]Verifikations-Veto durch Browser-UI-Check:[/bold red] {err_details}.")
                    summary_lines.append(f"- ❌ **Verifikations-Veto durch Browser-UI-Check:** {err_details}.")

        # Accessibility-Check: echter axe-core-Scan (WCAG 2.x) gegen die gerenderte Seite -
        # ersetzt die rein LLM-basierte Einschätzung des accessibility-Agenten durch geparste
        # Verstöße mit Regel/Schweregrad/Element. Rein informativ wie Lint/SAST/Lizenz-Scan
        # (beeinflusst verification_ok nicht) - dieselbe Einstufung wie der bereits bestehende
        # Frontend/UI-Check direkt darüber, der aus demselben Grund ebenfalls nicht blockiert.
        if not (budget_aborted or manually_cancelled):
            a11y_report = await asyncio.to_thread(verifier.check_accessibility)
            if a11y_report.attempted:
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

        # Bugfix (Analysebericht 2026-09-13, HyperionSentinel-Lauf): budget_aborted konnte bis
        # hierhin auch dann noch True werden, wenn die Kern-Testsuite trotz erreichtem Budget
        # über den weiterhin kostenlos ausgeführten Bestätigungs-Testlauf (siehe oben) bereits
        # erfolgreich bestanden hatte (verification_ok == True) - eine NACHGELAGERTE, rein
        # optionale Prüfung (Docker-Build, Vollständigkeits-
        # Check, Lastentest, ...) traf danach erneut auf dasselbe (weiterhin überschrittene)
        # Token-Limit und setzte budget_aborted = True, obwohl am eigentlichen Ergebnis nichts
        # mehr abzubrechen war. Real beobachtet: `run_closed` meldete `budget_aborted: true`
        # UND `verification_ok: true` gleichzeitig, wodurch der Lauf in Dashboard/Team-Historie
        # fälschlich als abgebrochen statt als erfolgreich zählte. Ein NACHGELAGERTER Fehlschlag
        # (Coverage unter Schwelle, Runtime-Smoke/Lastentest/Browser-Check fehlgeschlagen) setzt
        # verification_ok oben explizit wieder auf False zurück - genau dann bleibt
        # budget_aborted zurecht bestehen. Nur wenn verification_ok an DIESER Stelle noch True
        # ist (die Kern-Testsuite bestand UND kein nachgelagerter Check fand einen echten
        # Fehlschlag), gilt der Lauf als erfolgreich abgeschlossen - mit einem Hinweis, dass
        # lediglich weitere optionale Prüfungen wegen des Budgets übersprungen wurden.
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
