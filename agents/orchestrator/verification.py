"""
agents/orchestrator/verification.py – VerificationMixin: Governance-Fix-Schleife und echte
Verifikations-/Fix-Schleife (Ersetzt die alte Keyword-basierte Fix-Schleife).

_run_governance_fix_loop() beauftragt gezielte Korrekturen für kritische Review-Befunde
(code_reviewer/security/compliance) NACH der Fachbereichs-Hierarchie und VOR der echten
Testverifikation.

_run_verification_loop() installiert Abhängigkeiten in einer isolierten Umgebung, führt die
echte Testsuite aus und schickt bei Fehlschlägen einen GEZIELTEN Korrekturauftrag an genau
die Agenten, deren Dateien laut echtem Traceback betroffen sind. Führt anschließend alle
weiteren Verifikations-Checks aus (Docker-Build, Dependency-/SAST-/Lizenz-Audit, Lint,
Coverage, Runtime-Smoke, Lastentest, Browser/A11y) - Runtime-Smoke, Lastentest und Browser/UI
laufen dabei über _run_runtime_check_with_fix() (siehe unten), das bei Fehlschlag ebenfalls
einen gezielten Korrekturauftrag auslöst statt nur verification_ok zurückzusetzen.
"""

import asyncio
from collections.abc import Callable

from agents.orchestrator.constants import REVIEW_ONLY_AGENT_IDS
from config import (
    ENABLE_GOVERNANCE_FIX_LOOP,
    ENABLE_LOAD_TEST_CHECK,
    LOAD_TEST_DURATION_SECONDS,
    LOAD_TEST_TIMEOUT_SECONDS,
    MAX_REVIEW_ITERATIONS,
    MAX_VERIFICATION_ITERATIONS,
    MIN_TEST_COVERAGE,
)
from core.message_bus import AgentResult, AgentTask
from core.review_gate import find_critical_findings, route_findings_to_owners
from core.verifier import ProjectVerifier, VerificationReport


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
                break

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

            fix_tasks = []
            for agent_id, texts in agents_to_fix.items():
                finding_text = "\n\n".join(texts)[:3000]
                fix_tasks.append(AgentTask(
                    task_id=f"governance_fix_{agent_id}_{attempt}",
                    agent_id=agent_id,
                    description=(
                        f"Das Governance-Review (code_reviewer/security/compliance) hat ein "
                        f"KRITISCHES Problem in deinem Code gefunden. Nutze read_file, um die "
                        f"betroffene(n) Datei(en) zu prüfen, und edit_file/write_file, um das "
                        f"Problem zu beheben.\n\n{finding_text}"
                    ),
                    context="", project_dir=project_dir,
                ))

            notify(f"  🛠️ [bold yellow]Governance-Fix:[/bold yellow] Beauftrage {', '.join(agents_to_fix.keys())} mit {len(findings)} kritischem/kritischen Befund(en)...")
            fix_results = await self._run_agents_parallel(fix_tasks, notify=notify)
            self._update_file_owners(file_owners, fix_results)
            all_results.extend(fix_results)
            summary_lines.append(
                f"- 🛠️ Versuch {attempt}: {len(findings)} kritische(r) Governance-Befund(e) → gezielt "
                f"zur Korrektur an {', '.join(agents_to_fix.keys())} zurückgespielt (der Fix wird NICHT "
                f"erneut vom Reviewer bestätigt – das übernimmt für automatisiert testbares Verhalten "
                f"nur die anschließende echte Testverifikation, nicht die qualitative Review-Aussage selbst)."
            )

            if attempt == MAX_REVIEW_ITERATIONS:
                summary_lines.append(f"- ℹ️ Nach {MAX_REVIEW_ITERATIONS} Versuch(en) letzter Stand übernommen.")

        summary = (
            "### 🔍 Governance-Fix-Protokoll (kritische Review-Befunde)\n" + "\n".join(summary_lines)
            if summary_lines else ""
        )
        return all_results, summary, budget_aborted, manually_cancelled

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
        # Bleibt None, wenn die Schleife unten (z.B. MAX_VERIFICATION_ITERATIONS<=0) nie
        # durchläuft - der Coverage-Check danach prüft explizit auf None, statt sich auf eine
        # garantierte Zuweisung zu verlassen.
        report: VerificationReport | None = None

        notify("🧪 [bold cyan]Verifikation:[/bold cyan] Installiere Abhängigkeiten in isolierter Umgebung...")
        install_log = await asyncio.to_thread(verifier.ensure_environment)
        if install_log:
            notify(f"  📦 {install_log.splitlines()[0]}")
            summary_lines.append(f"- 📦 {install_log.splitlines()[0]}")

        for attempt in range(1, MAX_VERIFICATION_ITERATIONS + 1):
            if run_start_tokens is not None and (
                self._run_budget_exceeded(run_start_tokens) or self._project_budget_exceeded(run_start_tokens)
            ):
                budget_aborted = True
                notify("  🚫 [bold red]Budget erreicht[/bold red] – weitere Verifikations-/Fixversuche werden übersprungen.")
                summary_lines.append(f"- 🚫 {self._budget_exceeded_label(run_start_tokens)} erreicht – Verifikation nach Versuch {attempt - 1} abgebrochen.")
                break
            if cancel_requested and cancel_requested():
                manually_cancelled = True
                notify("  ⏹️ [bold red]Lauf manuell abgebrochen[/bold red] – weitere Verifikations-/Fixversuche werden übersprungen.")
                summary_lines.append(f"- ⏹️ Manuell abgebrochen – Verifikation nach Versuch {attempt - 1} beendet.")
                break

            notify(f"  🧪 [yellow]Testlauf {attempt}/{MAX_VERIFICATION_ITERATIONS}:[/yellow] Führe echte Tests aus...")
            report = await asyncio.to_thread(verifier.run_tests)

            if not report.ran:
                if not report.passed:
                    # Realer Fund (Workspace-Audit): ein mehrteiliges Backend-Projekt ohne jeden
                    # Einstiegspunkt bzw. eine Testsuite mit conftest.py, aber ohne echte Testdatei,
                    # sah bisher genauso aus wie "keine Tests gefunden" und lief als vermeintlich
                    # bestandene Verifikation durch – core/verifier.py.ProjectVerifier erkennt das
                    # jetzt als eigenständigen Fehlschlag statt als bloßes "nicht geprüft".
                    notify(f"  ❌ [bold red]{report.reason_skipped}[/bold red]")
                    summary_lines.append(f"- ❌ {report.reason_skipped}")
                    break
                # Bewusst ⚠️ statt ℹ️: "keine Tests gefunden" bedeutet, dass generierter Code
                # UNGEPRÜFT ausgeliefert wird – real beobachtet an einem Taschenrechner-Projekt
                # ohne jeden Test, dessen "+"-Button sofort mit TypeError abstürzte (Add.execute()
                # verlangte zwei Argumente, die GUI übergab nur eines). Reine Sichtbarkeit, kein
                # automatischer Abbruch – DECOMPOSE_SYSTEM_PROMPT (core/task_manager.py) weist das
                # Modell inzwischen an, den tester-Agenten bei echter Programmlogik einzubeziehen.
                notify(f"  ⚠️ [yellow]{report.reason_skipped}[/yellow]")
                summary_lines.append(f"- ⚠️ {report.reason_skipped} Generierter Code wurde NICHT automatisch verifiziert.")
                break

            if report.passed:
                notify(f"  ✅ [bold green]Alle Tests bestanden[/bold green] (Versuch {attempt}, {report.duration_seconds:.1f}s).")
                summary_lines.append(f"- ✅ Echte Testsuite bestanden nach {attempt} Durchlauf/Durchläufen ({report.duration_seconds:.1f}s).")
                verification_ok = True
                break

            notify(f"  ❌ [bold red]{len(report.failures)} Testfehler[/bold red] – ermittle betroffene Agenten aus dem echten Traceback...")

            agents_to_fix: dict[str, list] = {}
            for failure in report.failures:
                owners = {file_owners[f] for f in failure.files if f in file_owners}
                if not owners and any(r.agent_id == "tester" for r in all_results):
                    owners = {"tester"}
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
                    f"Test: {f.test_id}\nFehlermeldung: {f.message}\nBetroffene Dateien: {', '.join(f.files) or 'unbekannt'}"
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
                    ),
                    context="",
                    project_dir=project_dir,
                ))

            notify(f"  🛠️ [bold yellow]Gezielter Auto-Fix:[/bold yellow] Beauftrage {', '.join(agents_to_fix.keys())} (nicht blind alle Dev-Agenten)...")
            fix_results = await self._run_agents_parallel(fix_tasks, notify=notify)
            self._update_file_owners(file_owners, fix_results)
            all_results.extend(fix_results)
            summary_lines.append(f"- 🛠️ Versuch {attempt}: {len(report.failures)} echte Testfehler → gezielt zur Korrektur an {', '.join(agents_to_fix.keys())} zurückgespielt.")

            if attempt == MAX_VERIFICATION_ITERATIONS:
                notify("  ⚠️ [yellow]Maximale Verifikations-Iterationen erreicht – letzter Stand wird übernommen.[/yellow]")
                summary_lines.append(f"- ⚠️ Nach {MAX_VERIFICATION_ITERATIONS} Versuchen nicht vollständig grün – letzter Stand wurde übernommen.")

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
                if docker_report.success:
                    notify("  🐳 [bold green]Docker-Image baut erfolgreich.[/bold green]")
                    summary_lines.append("- 🐳 Docker-Image baut erfolgreich (echter `docker build`).")
                else:
                    notify("  🐳 [bold red]Docker-Build fehlgeschlagen.[/bold red]")
                    summary_lines.append(f"- 🐳 ❌ Docker-Build fehlgeschlagen: {docker_report.output[:500]}")

        # Ersetzt die rein LLM-basierte Einschätzung des security-Agenten zu Abhängigkeits-
        # Risiken durch einen echten Abgleich gegen eine öffentliche Advisory-Datenbank
        # (pip-audit/npm audit) – kein Raten mehr, ob eine gepinnte Paketversion bekannte
        # CVEs hat. Ein technischer Fehlschlag des Scans (Tool fehlt, kein Netzwerk zur
        # Advisory-Datenbank) ist NIE ein Fehler, nur nicht prüfbar (attempted=False) und
        # wird deshalb bewusst NICHT als "keine Schwachstellen" ausgegeben.
        if not (budget_aborted or manually_cancelled):
            audit_reports = await asyncio.to_thread(verifier.check_dependency_vulnerabilities)
            for audit in audit_reports:
                if not audit.attempted:
                    continue
                if audit.vulnerable:
                    top = "; ".join(
                        f"{v.package} {v.version} ({v.vulnerability_id})" for v in audit.vulnerabilities[:5]
                    )
                    if len(audit.vulnerabilities) > 5:
                        top += f" … und {len(audit.vulnerabilities) - 5} weitere"
                    notify(f"  🔓 [bold red]{audit.tool}: {len(audit.vulnerabilities)} bekannte Schwachstelle(n) in Abhängigkeiten.[/bold red]")
                    summary_lines.append(f"- 🔓 ❌ {audit.tool}: {len(audit.vulnerabilities)} bekannte Schwachstelle(n) in Abhängigkeiten: {top}")
                else:
                    notify(f"  🔒 [bold green]{audit.tool}: keine bekannten Schwachstellen in Abhängigkeiten.[/bold green]")
                    summary_lines.append(f"- 🔒 {audit.tool}: keine bekannten Schwachstellen in Abhängigkeiten gefunden.")

        # Ersetzt die rein LLM-basierte Einschätzung des security-Agenten zu Schwachstellen
        # im SELBST GESCHRIEBENEN Code (Freitext-Vermutungen ohne Datei/Zeile) durch einen
        # echten statischen Scan (bandit für Python) – dasselbe Prinzip wie beim Dependency-
        # Audit oben, nur für eigenen Code statt Fremdpakete. Rein informativ wie der
        # Lint-Check, beeinflusst verification_ok nicht - ein SAST-Fund kann ein False
        # Positive sein und braucht menschliche Einschätzung, anders als ein roter Test.
        if not (budget_aborted or manually_cancelled):
            sast_reports = await asyncio.to_thread(verifier.check_sast)
            for sast in sast_reports:
                if not sast.attempted:
                    continue
                if sast.vulnerable:
                    top = "; ".join(
                        f"{f.file_path}:{f.line_number} [{f.rule}/{f.severity}]" for f in sast.findings[:5]
                    )
                    if len(sast.findings) > 5:
                        top += f" … und {len(sast.findings) - 5} weitere"
                    notify(f"  🕵️ [bold red]{sast.tool}: {len(sast.findings)} potenzielle Sicherheits-Fund(e) im Code.[/bold red]")
                    summary_lines.append(f"- 🕵️ ⚠️ {sast.tool}: {len(sast.findings)} potenzielle Sicherheits-Fund(e) im Code: {top}")
                else:
                    notify(f"  🕵️ [bold green]{sast.tool}: keine Sicherheits-Funde im Code.[/bold green]")
                    summary_lines.append(f"- 🕵️ {sast.tool}: keine Sicherheits-Funde im Code (statischer Scan).")

        # Ersetzt die rein LLM-basierte Lizenz-Tabelle des compliance-Agenten ("MIT/AGPL 🔴",
        # geraten) durch einen echten Scan der tatsächlich installierten Paket-Lizenzen
        # (pip-licenses). Rein informativ wie Lint/SAST, beeinflusst verification_ok nicht -
        # ein Copyleft-Fund ist eine rechtliche Einschätzungsfrage (z. B. Nutzung als Library
        # vs. verlinkt vs. modifiziert), kein automatisch behebbarer Codefehler.
        if not (budget_aborted or manually_cancelled):
            license_reports = await asyncio.to_thread(verifier.check_licenses)
            for lic in license_reports:
                if not lic.attempted:
                    continue
                if lic.has_copyleft_risk:
                    copyleft_findings = [f for f in lic.findings if f.copyleft]
                    top = "; ".join(f"{f.package} {f.version} ({f.license})" for f in copyleft_findings[:5])
                    if len(copyleft_findings) > 5:
                        top += f" … und {len(copyleft_findings) - 5} weitere"
                    notify(f"  📜 [bold red]{lic.tool}: {len(copyleft_findings)} Copyleft-Lizenz(en) in Abhängigkeiten (GPL/LGPL/MPL/…).[/bold red]")
                    summary_lines.append(f"- 📜 ⚠️ {lic.tool}: {len(copyleft_findings)} Copyleft-Lizenz(en) in Abhängigkeiten: {top}")
                else:
                    notify(f"  📜 [bold green]{lic.tool}: keine Copyleft-Lizenzen in Abhängigkeiten.[/bold green]")
                    summary_lines.append(f"- 📜 {lic.tool}: keine Copyleft-Lizenzen in Abhängigkeiten gefunden ({len(lic.findings)} geprüft).")

        # Erstmals überhaupt eine automatische Stil-/Fehlerprüfung für generierten Code -
        # ruff.toml lief bisher NUR gegen den Framework-Code selbst (workspace/ dort bewusst
        # ausgeschlossen). Python wird immer geprüft (ruff braucht keine Projekt-Konfiguration),
        # ESLint/tsc nur, wenn das Projekt sie selbst bereits mitbringt (keine ungefragte
        # Meinungsänderung an einem Projekt, das sich nie dafür entschieden hat). Rein
        # informativ, beeinflusst verification_ok nicht - anders als ein Testfehler hat ein
        # Lint-Fund oft keine unmittelbare Ein-Zeilen-Lösung.
        if not (budget_aborted or manually_cancelled):
            lint_reports = await asyncio.to_thread(verifier.check_lint)
            for lint in lint_reports:
                if not lint.attempted:
                    continue
                if not lint.passed:
                    top = "; ".join(
                        f"{i.file_path}:{i.line_number} [{i.rule}]" for i in lint.issues[:5]
                    )
                    if len(lint.issues) > 5:
                        top += f" … und {len(lint.issues) - 5} weitere"
                    notify(f"  🎨 [bold yellow]{lint.tool}: {len(lint.issues)} Lint-Fund(e).[/bold yellow]")
                    summary_lines.append(f"- 🎨 ⚠️ {lint.tool}: {len(lint.issues)} Lint-Fund(e): {top}")
                else:
                    notify(f"  🎨 [bold green]{lint.tool}: keine Lint-Funde.[/bold green]")
                    summary_lines.append(f"- 🎨 {lint.tool}: keine Lint-Funde.")

        # Realer Fund bei einer Bestandsaufnahme des eigenen Teams: die Verifikation misst
        # bisher nur Pass/Fail, keine Abdeckung - ein Projekt mit 3 bestandenen Tests bei 500
        # Zeilen ungetestetem Code gilt genauso als "verifiziert" wie eines mit echter
        # Abdeckung. Opt-in über MIN_TEST_COVERAGE (Standard 0 = deaktiviert, siehe config.py) -
        # nur sinnvoll, wenn die Testsuite überhaupt gelaufen UND bestanden ist (report kann
        # None sein, wenn die Schleife oben nie durchlief, z.B. MAX_VERIFICATION_ITERATIONS<=0).
        if not (budget_aborted or manually_cancelled) and MIN_TEST_COVERAGE > 0 and report is not None and report.ran and report.passed:
            coverage_report = await asyncio.to_thread(verifier.check_coverage)
            if coverage_report.attempted:
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

        # Runtime Smoke-Check: Prüft, ob die generierte App tatsächlich hochfährt / antwortet (Tests grün != App startet)
        if not (budget_aborted or manually_cancelled) and report is not None and report.ran and report.passed:
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
                agent_id = "frontend" if "frontend" in self._agents else next(
                    (a for a in ("backend",) if a in self._agents), None,
                )
                if agent_id is None:
                    return None
                details = browser_report.missing_assets + browser_report.console_errors + [
                    f"Canvas nie gezeichnet: {c}" for c in browser_report.blank_canvases
                ]
                return AgentTask(
                    task_id=f"verify_fix_browser_{agent_id}_{attempt}",
                    agent_id=agent_id,
                    description=(
                        f"Der ECHTE Browser/UI-Check (Playwright) gegen `{browser_report.tested_url}` ist "
                        f"fehlgeschlagen: {'; '.join(details)[:800]}. Nutze read_file, um die betroffene(n) "
                        f"Datei(en) zu prüfen, und edit_file/write_file, um den Fehler zu beheben (z.B. "
                        f"fehlendes Asset, JS-Konsolenfehler, nie gezeichnetes Canvas-Element)."
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

        # Accessibility-Check: echter axe-core-Scan (WCAG 2.x) gegen die gerenderte Seite -
        # ersetzt die rein LLM-basierte Einschätzung des accessibility-Agenten durch geparste
        # Verstöße mit Regel/Schweregrad/Element. Rein informativ wie Lint/SAST/Lizenz-Scan
        # (beeinflusst verification_ok nicht) - dieselbe Einstufung wie der bereits bestehende
        # Frontend/UI-Check direkt darüber, der aus demselben Grund ebenfalls nicht blockiert.
        if not (budget_aborted or manually_cancelled):
            a11y_report = await asyncio.to_thread(verifier.check_accessibility)
            if a11y_report.attempted:
                if a11y_report.passed:
                    notify(f"  ♿ [bold green]Accessibility-Check (axe-core) erfolgreich:[/bold green] `{a11y_report.tested_url}`.")
                    summary_lines.append(f"- ♿ Accessibility-Check (axe-core): `{a11y_report.tested_url}` keine WCAG-Verstöße.")
                else:
                    top = "; ".join(f"{v.rule_id} [{v.impact}] {v.target}" for v in a11y_report.violations[:5])
                    if len(a11y_report.violations) > 5:
                        top += f" … und {len(a11y_report.violations) - 5} weitere"
                    notify(f"  ♿ [bold red]Accessibility-Check (axe-core): {len(a11y_report.violations)} WCAG-Verstoß/Verstöße.[/bold red]")
                    summary_lines.append(f"- ♿ ⚠️ Accessibility-Check (axe-core): {len(a11y_report.violations)} WCAG-Verstoß/Verstöße: {top}")

        verification_summary = "### 🧪 Verifikations-Protokoll (echte Dependency-Installation & Testausführung)\n" + (
            "\n".join(summary_lines) if summary_lines else "- Keine Verifikation durchgeführt."
        )
        return all_results, verification_summary, budget_aborted, manually_cancelled, verification_ok
