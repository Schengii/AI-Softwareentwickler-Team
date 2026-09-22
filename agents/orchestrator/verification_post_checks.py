"""
agents/orchestrator/verification_post_checks.py – VerificationPostChecksMixin (P6-5,
ROADMAP_TEMP.md): aus agents/orchestrator/verification.py extrahiert, Teil der physischen
Aufteilung des zuvor 2589 Zeilen langen VerificationMixin nach Verantwortlichkeiten.

Enthält die Prüfschritte, die NACH der eigentlichen Testschleife laufen: Docker-Build,
Frontend-Build, Runtime-Smoke, Lastentest, Browser/UI, Accessibility, Fachlogik-Testtiefe,
Testabdeckung, sowie die Neu-Messung früh im Lauf blockierender Checks am Laufende
(`_recheck_stale_blocking_checks`). `_run_runtime_check_with_fix()` ist die gemeinsame
Fix-Schleife, die Runtime-Smoke/Lastentest/Browser-UI teilen.

Nicht zu verwechseln mit `agents/orchestrator/verification_checks.py` (bereits vorher
existierendes, eigenständiges Modul mit `reconcile_verification_ok`/`CheckContext`/
`run_informational_checks` - unverändert, dieser Name war schon vergeben).

`MAX_VERIFICATION_ITERATIONS`/`MIN_TEST_COVERAGE`/`run_pre_flight_check`/`unmet_requirements`
werden NICHT direkt importiert, sondern über `import agents.orchestrator.verification as _v`
gelesen - Testdateien patchen diese Namen über
`@patch("agents.orchestrator.verification.<name>", ...)`. Ein direkter Import hier würde eine
unabhängige Kopie binden, die ein solcher Patch nie träfe (stiller No-Op statt Importfehler) -
siehe core/llm_providers/*.py für dasselbe, bereits bewährte Muster bei P6-5 Teil 2.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable

from config import (
    LOAD_TEST_DURATION_SECONDS,
    LOAD_TEST_TIMEOUT_SECONDS,
    MIN_DOMAIN_LOGIC_TEST_RATIO,
)
from core.message_bus import AgentResult, AgentTask
from core.test_depth import analyze_domain_logic_depth
from core.verification_outcome import VerificationOutcome
from core.verifier import ProjectVerifier

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


class VerificationPostChecksMixin:
    """Prüfschritte, die NACH der eigentlichen Testschleife laufen (Docker/Frontend-Build,
    Runtime-Smoke, Lastentest, Browser/UI, Accessibility, Fachlogik-Testtiefe, Coverage)."""

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
        import agents.orchestrator.verification as _v
        max_iterations = _v.MAX_VERIFICATION_ITERATIONS

        report = await asyncio.to_thread(check_fn)
        budget_aborted = False
        manually_cancelled = False
        if not is_attempted(report) or is_passed(report):
            return report, all_results, budget_aborted, manually_cancelled

        for attempt in range(1, max_iterations + 1):
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
            if attempt == max_iterations:
                notify("  ⚠️ [yellow]Maximale Fixversuche erreicht – letzter Check-Stand wird übernommen.[/yellow]")

        return report, all_results, budget_aborted, manually_cancelled

    async def _run_frontend_build_check(
        self,
        verifier: ProjectVerifier,
        outcome: VerificationOutcome,
        summary_lines: list[str],
        notify: Callable[[str], None],
        file_owners: dict[str, str],
        all_results: list[AgentResult],
        project_dir: str,
    ) -> bool | None:
        """P6-5 (ROADMAP_TEMP.md, Teilschritt): aus `_run_verification_loop_impl()` extrahiert -
        echter `npm run build` VOR dem Browser-UI-Check: ohne Build würde der Browser-Check rohe
        Quelldateien (z.B. main.tsx) servieren und einen Build-Fehler als Frontend-Bug melden.
        Gibt `False` zurück, wenn ein fehlgeschlagener Build `verification_ok` veto'en soll
        (Aufrufer setzt es), sonst `None` - `outcome`/`summary_lines`/`file_owners`/
        `all_results` werden in-place mutiert."""
        veto = None
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
                veto = False
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
        return veto

    async def _record_docker_build_check(
        self, verifier: ProjectVerifier, outcome: VerificationOutcome,
        summary_lines: list[str], notify: Callable[[str], None],
    ) -> None:
        """P6-5 (ROADMAP_TEMP.md, Teilschritt): aus `_run_verification_loop_impl()` extrahiert -
        prüft nur die Build-Fähigkeit des Dockerfiles (kein run/push/deploy), rein informativ,
        beeinflusst `verification_ok` nicht, deshalb ohne Rückgabewert sicher isolierbar."""
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
        import agents.orchestrator.verification as _v
        min_coverage = _v.MIN_TEST_COVERAGE

        coverage_report = await asyncio.to_thread(verifier.check_coverage)
        if not coverage_report.attempted:
            return None
        self.last_coverage_percent = coverage_report.percent
        outcome.record("coverage", coverage_report.percent >= min_coverage, f"{coverage_report.percent}%")
        if coverage_report.percent >= min_coverage:
            notify(f"  📊 [bold green]Testabdeckung: {coverage_report.percent}%[/bold green] (Schwelle: {min_coverage}%).")
            summary_lines.append(f"- 📊 Testabdeckung: {coverage_report.percent}% (Schwelle von {min_coverage}% erreicht).")
            return None
        # Eine explizit konfigurierte Schwelle ist eine echte Anforderung - verification_ok zurücksetzen.
        notify(f"  📊 [bold red]Testabdeckung {coverage_report.percent}% UNTER der Schwelle von {min_coverage}%.[/bold red]")
        summary_lines.append(f"- 📊 ❌ Testabdeckung {coverage_report.percent}% UNTER der konfigurierten Schwelle (`MIN_TEST_COVERAGE={min_coverage}%`).")
        _grund = f"Testabdeckung {coverage_report.percent}% liegt unter der konfigurierten Schwelle von {min_coverage}%."
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
        import agents.orchestrator.verification as _v

        if outcome.status("pre_flight") is False:
            try:
                report = await asyncio.to_thread(_v.run_pre_flight_check, project_dir)
            except Exception as e:  # noqa: BLE001 - Neu-Messung darf den Lauf nie abbrechen
                logging.getLogger("agents.orchestrator.verification").warning("Pre-Flight-Neumessung fehlgeschlagen: %r", e)
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
                recheck = await asyncio.to_thread(_v.unmet_requirements, project_dir)
            except Exception as e:  # noqa: BLE001 - siehe oben
                logging.getLogger("agents.orchestrator.verification").warning("Security-Handoff-Neumessung fehlgeschlagen: %r", e)
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
