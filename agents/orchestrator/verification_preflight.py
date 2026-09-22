"""
agents/orchestrator/verification_preflight.py – VerificationPreflightMixin (P6-5,
ROADMAP_TEMP.md): aus agents/orchestrator/verification.py extrahiert, Teil der physischen
Aufteilung des zuvor 2589 Zeilen langen VerificationMixin nach Verantwortlichkeiten.

Enthält alles, was VOR der eigentlichen Testschleife läuft: den Smoke-Test-Gate (startet die App
überhaupt?), den deterministischen Pre-Flight-Check (AST-basiert, fehlende __init__.py,
Syntaxfehler, nicht deklarierte Abhängigkeiten), den Vorab-Import-Check (fehlende lokale
Module/Symbole) sowie die geteilten Dependency-Manifest-Hilfsfunktionen, die mehrere dieser
Checks nutzen.

`run_pre_flight_check`/`MAX_VERIFICATION_ITERATIONS` werden NICHT direkt importiert, sondern
über `import agents.orchestrator.verification as _v` gelesen - Testdateien patchen diese Namen
über `@patch("agents.orchestrator.verification.<name>", ...)`. Ein direkter Import hier würde
eine unabhängige Kopie binden, die ein solcher Patch nie träfe (stiller No-Op statt
Importfehler) - siehe core/llm_providers/*.py für dasselbe, bereits bewährte Muster bei P6-5
Teil 2.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from agents.orchestrator.failure_diagnosis import _issue_signature, _no_progress
from config import ENABLE_COMPLETENESS_CHECK
from core.decision_log import log_decision
from core.dependency_manifest import (
    add_requirement,
    manifest_for_package,
    package_from_finding,
    packages_from_install_hints,
    primary_python_manifest,
)
from core.message_bus import AgentResult, AgentTask
from core.pre_flight_check import PreFlightIssue
from core.verification_outcome import VerificationOutcome
from core.verifier import ProjectVerifier


class VerificationPreflightMixin:
    """Checks, die VOR der eigentlichen Testschleife laufen (Smoke-Gate, Pre-Flight, Vorab-Import)."""

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

    async def _run_preflight_check_loop(
        self,
        project_dir: str,
        run_start_tokens: dict | None,
        cancel_requested: Callable[[], bool] | None,
        notify: Callable[[str], None],
        file_owners: dict[str, str],
        all_results: list[AgentResult],
        summary_lines: list[str],
        outcome: VerificationOutcome,
    ) -> tuple[bool, bool]:
        """P6-5 (ROADMAP_TEMP.md, Teilschritt): aus `_run_verification_loop_impl()` extrahiert -
        deterministischer Pre-Flight-Check (ast-basiert, ohne LLM): fehlende __init__.py,
        Syntaxfehler, nicht deklarierte Abhängigkeiten. Funde werden sofort per Fix-und-Retry mit
        Owner-Routing und Kein-Fortschritt-Breaker behoben, statt bis zum teuren Testlauf zu
        warten. Rückgabe (budget_aborted, manually_cancelled) statt eines Zustandsobjekts, exakt
        wie bei den bereits extrahierten Fix-Schleifen-Checks - `pre_flight_report` selbst wird
        nach diesem Block nirgends mehr gebraucht (das abschließende `outcome.record(...)` ist
        hier mit hineingezogen), `file_owners`/`all_results`/`summary_lines`/`outcome` werden
        alle in-place mutiert und brauchen deshalb keine Rückgabe."""
        import agents.orchestrator.verification as _v
        max_iterations = _v.MAX_VERIFICATION_ITERATIONS

        budget_aborted = False
        manually_cancelled = False
        pre_flight_report = None
        previous_preflight_signature: frozenset[tuple[str, str]] | None = None
        for attempt in range(1, max_iterations + 1):
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
                pre_flight_report = await asyncio.to_thread(_v.run_pre_flight_check, project_dir)
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

            if attempt == max_iterations:
                notify("  ⚠️ [yellow]Maximale Pre-Flight-Fixversuche erreicht – weiter mit der regulären Testsuite.[/yellow]")
                summary_lines.append(f"- 🔍 ⚠️ Pre-Flight-Check nach {max_iterations} Versuchen weiterhin mit Funden – weiter mit der regulären Testsuite.")

        if pre_flight_report is not None and not pre_flight_report.error:
            outcome.record(
                "pre_flight", pre_flight_report.passed,
                "" if pre_flight_report.passed else f"{len(pre_flight_report.issues)} Fund(e)",
            )
        return budget_aborted, manually_cancelled

    async def _run_preimport_check_loop(
        self,
        project_dir: str,
        verifier: ProjectVerifier,
        run_start_tokens: dict | None,
        cancel_requested: Callable[[], bool] | None,
        notify: Callable[[str], None],
        file_owners: dict[str, str],
        all_results: list[AgentResult],
        summary_lines: list[str],
        budget_aborted: bool,
        manually_cancelled: bool,
    ) -> tuple[bool, bool]:
        """P6-5 (ROADMAP_TEMP.md, Teilschritt): aus `_run_verification_loop_impl()` extrahiert -
        prüft Import-Funde UND (seit ecotrack_ai-Fund 2026-09-17) unaufgelöste Namen in
        Einstiegsdateien (`undefined_entrypoint_name`, z.B. ein registrierter, aber nie
        importierter Router) - beides garantierte NameError/ImportError-Abstürze beim Start,
        dieselbe Kategorie. Stub-Marker u.ä. bleiben beim späteren vollständigen Durchlauf.
        `budget_aborted`/`manually_cancelled` kommen als Parameter herein (anders als beim
        Pre-Flight-Check ist hier NICHT garantiert, dass sie noch `False` sind) und werden am
        Ende zurückgegeben - `file_owners`/`all_results`/`summary_lines` bleiben in-place
        mutiert."""
        if not ENABLE_COMPLETENESS_CHECK or budget_aborted or manually_cancelled:
            return budget_aborted, manually_cancelled

        import agents.orchestrator.verification as _v
        max_iterations = _v.MAX_VERIFICATION_ITERATIONS

        _PREIMPORT_ISSUE_KINDS = {"missing_local_import", "undefined_entrypoint_name"}
        # Zirkuit-Breaker wie in den übrigen Fix-Schleifen.
        previous_preimport_signature: frozenset[tuple[str, str]] | None = None
        for attempt in range(1, max_iterations + 1):
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

            if attempt == max_iterations:
                notify("  ⚠️ [yellow]Maximale Vorab-Import-Fixversuche erreicht – weiter mit der regulären Testsuite.[/yellow]")
                summary_lines.append(f"- 🧩 ⚠️ Vorab-Import-Check nach {max_iterations} Versuchen weiterhin mit Funden – weiter mit der regulären Testsuite (dort erneut sichtbar).")

        return budget_aborted, manually_cancelled
