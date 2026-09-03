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
import re
from collections.abc import Callable

from agents.orchestrator.constants import REVIEW_ONLY_AGENT_IDS
from config import (
    ENABLE_COMPLETENESS_CHECK,
    ENABLE_GOVERNANCE_FIX_LOOP,
    ENABLE_LOAD_TEST_CHECK,
    LOAD_TEST_DURATION_SECONDS,
    LOAD_TEST_TIMEOUT_SECONDS,
    MAX_REVIEW_ITERATIONS,
    MAX_TASK_TOKENS,
    MAX_VERIFICATION_ITERATIONS,
    MIN_TEST_COVERAGE,
)
from core.backlog_store import upsert_ticket
from core.decision_log import log_decision
from core.message_bus import AgentResult, AgentTask
from core.review_gate import (
    find_critical_findings,
    find_permission_blocked_questions,
    find_structural_scope_questions,
    route_findings_to_owners,
)
from core.team_memory import record_lesson
from core.verifier import ProjectVerifier, VerificationReport

# Realer Fund (taskpulse-Projekt, 2026-09-03): eine fehlende `app/models.py` (referenziert per
# `from . import database, models, schemas`) führte zu einem ModuleNotFoundError/ImportError,
# der als ganz normaler Testfehlschlag durch die Fix-Schleife unten lief - die generische
# Fix-Beschreibung ("Nutze read_file, um die betroffene(n) Datei(en) zu prüfen...") nannte NIE
# konkret, WELCHE Datei fehlt, nur den vollen Traceback-Text. Der beauftragte Agent musste sich
# das selbst erschließen und tat es über mehrere Versuche hinweg nicht zuverlässig (33
# Agenten-Durchläufe, 714k Tokens, am Ende trotzdem verification_ok=False). Diese Muster
# erkennen die beiden häufigsten Python-Fehlerklassen für "referenziertes Modul/Symbol
# existiert nicht" und machen die fehlende Datei/das fehlende Symbol im Fix-Auftrag EXPLIZIT,
# statt es implizit im Traceback zu verstecken.
_MODULE_NOT_FOUND_RE = re.compile(r"ModuleNotFoundError: No module named ['\"]([\w.]+)['\"]")
_IMPORT_NAME_ERROR_RE = re.compile(r"ImportError: cannot import name ['\"](\w+)['\"] from ['\"]([\w.]+)['\"]")


def _diagnose_import_failure(message: str) -> str | None:
    """Extrahiert aus einer Python-Fehlermeldung, FALLS es sich um eine der beiden häufigsten
    'Modul/Symbol existiert nicht'-Fehlerklassen handelt, eine konkrete, an den Fix-Agenten
    adressierbare Diagnosezeile - None, wenn keines der beiden Muster passt (dann bleibt der
    generische Fix-Auftrag unverändert, siehe Aufrufer)."""
    m = _MODULE_NOT_FOUND_RE.search(message)
    if m:
        module = m.group(1)
        as_path = module.replace(".", "/")
        return (
            f"⚠️ KONKRETE URSACHE: Das Modul `{module}` existiert nicht (fehlende Datei "
            f"`{as_path}.py` oder fehlendes Paket-Verzeichnis `{as_path}/__init__.py`). Lege "
            f"GENAU DIESE Datei mit echtem Inhalt an, statt nur die importierende Datei zu ändern."
        )
    m = _IMPORT_NAME_ERROR_RE.search(message)
    if m:
        name, module = m.group(1), m.group(2)
        as_path = module.replace(".", "/")
        return (
            f"⚠️ KONKRETE URSACHE: `{name}` existiert nicht in `{as_path}.py` (Modul selbst ist "
            f"vorhanden, das importierte Symbol fehlt darin). Ergänze `{name}` (Klasse/Funktion/"
            f"Variable) in genau dieser Datei, statt nur die importierende Datei zu ändern."
        )
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
                if still_critical:
                    notify("  🛑 [bold red]Fix nicht bestätigt:[/bold red] Re-Review meldet weiterhin kritische Befunde – Backlog-Ticket für menschliche Prüfung eröffnet.")
                    summary_lines.append(
                        f"- 🛑 Nach {MAX_REVIEW_ITERATIONS} Versuch(en) bestätigt der Re-Review WEITERHIN "
                        f"{len(still_critical)} kritische(n) Befund(e) – Backlog-Ticket eröffnet statt "
                        "stillschweigend zu übernehmen."
                    )
                    try:
                        upsert_ticket(
                            ticket_id=f"unresolved-governance-critical-{getattr(self, 'last_project_slug', 'project')}",
                            title=f"Ungelöster kritischer Governance-Befund: {getattr(self, 'last_project_slug', 'project')}",
                            source="orchestrator", status="blocked",
                            project_slug=getattr(self, "last_project_slug", "project"),
                            detail="\n\n".join(still_critical)[:300],
                        )
                    except Exception as e:
                        notify(f"⚠️ [dim yellow]Ticket für ungelösten Governance-Befund konnte nicht angelegt werden: {e}[/dim yellow]")
                    record_lesson(
                        project_slug=getattr(self, "last_project_slug", "project"),
                        category="unresolved_governance_critical",
                        detail="\n\n".join(still_critical)[:300],
                    )
                    log_decision(project_dir, "unresolved_governance_critical_ticket_opened", "\n\n".join(still_critical)[:300])
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
                    try:
                        upsert_ticket(
                            ticket_id=f"unresolved-permission-blocked-{getattr(self, 'last_project_slug', 'project')}",
                            title=f"Ungelöster, zuvor schreibgeschützt blockierter Befund: {getattr(self, 'last_project_slug', 'project')}",
                            source="orchestrator", status="blocked",
                            project_slug=getattr(self, "last_project_slug", "project"),
                            detail="\n\n".join(still_critical)[:300],
                        )
                    except Exception as e:
                        notify(f"⚠️ [dim yellow]Ticket konnte nicht angelegt werden: {e}[/dim yellow]")
                    record_lesson(
                        project_slug=getattr(self, "last_project_slug", "project"),
                        category="unresolved_permission_blocked_fix",
                        detail="\n\n".join(still_critical)[:300],
                    )
                    log_decision(project_dir, "unresolved_permission_blocked_fix_ticket_opened", "\n\n".join(still_critical)[:300])
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

        notify("🧪 [bold cyan]Verifikation:[/bold cyan] Installiere Abhängigkeiten in isolierter Umgebung...")
        install_log = await asyncio.to_thread(verifier.ensure_environment)
        if install_log:
            notify(f"  📦 {install_log.splitlines()[0]}")
            summary_lines.append(f"- 📦 {install_log.splitlines()[0]}")

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
                import_issues = [i for i in pre_report.issues if "existierendes lokales" in i.message]
                if not import_issues:
                    if attempt > 1:
                        notify(f"  🧩 [bold green]Vorab-Import-Check nach Fix (Versuch {attempt}) bestanden.[/bold green]")
                        summary_lines.append(f"- 🧩 Vorab-Import-Check (statisch, vor der Testsuite): nach {attempt} Durchlauf/Durchläufen bestanden.")
                    break

                top = "; ".join(f"{i.file_path}:{i.line_number} – {i.message}" for i in import_issues[:5])
                notify(f"  🧩 [bold red]Vorab-Import-Check: {len(import_issues)} fehlende(s) lokale(s) Modul/Symbol VOR jedem Testlauf gefunden.[/bold red]")

                agents_to_fix: dict[str, list] = {}
                for issue in import_issues:
                    owner = file_owners.get(issue.file_path)
                    if owner and owner in self._agents:
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
                # verlangte zwei Argumente, die GUI übergab nur eines). DECOMPOSE_SYSTEM_PROMPT
                # (core/task_manager.py) weist das Modell inzwischen an, den tester-Agenten bei
                # echter Programmlogik einzubeziehen - reicht aber nicht immer (real beobachtet
                # am incidentpilot-Projekt: tester blieb ganz ohne Testdatei, statt hier nur
                # sichtbar zu bleiben, wird jetzt EIN gezielter Nachbeauftragungs-Versuch
                # unternommen, bevor endgültig aufgegeben wird.
                if not no_tests_fix_attempted and "tester" in self._agents:
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
                    continue
                notify(f"  ⚠️ [yellow]{report.reason_skipped}[/yellow]")
                summary_lines.append(f"- ⚠️ {report.reason_skipped} Generierter Code wurde NICHT automatisch verifiziert.")
                break

            if report.passed:
                notify(f"  ✅ [bold green]Alle Tests bestanden[/bold green] (Versuch {attempt}, {report.duration_seconds:.1f}s).")
                summary_lines.append(f"- ✅ Echte Testsuite bestanden nach {attempt} Durchlauf/Durchläufen ({report.duration_seconds:.1f}s).")
                verification_ok = True
                break

            notify(f"  ❌ [bold red]{len(report.failures)} Testfehler[/bold red] – ermittle betroffene Agenten aus dem echten Traceback...")

            current_signature = frozenset((f.test_id, f.message[:300]) for f in report.failures)
            if previous_failure_signature is not None and current_signature == previous_failure_signature:
                notify("  🛑 [bold red]Kein Fortschritt:[/bold red] identische Testfehler wie vor dem letzten Fixversuch – breche Verifikations-Schleife ab statt unverändert zu wiederholen.")
                summary_lines.append(
                    f"- 🛑 Versuch {attempt}: dieselben {len(report.failures)} Testfehler wie nach dem vorherigen "
                    "Fixversuch (keine Veränderung) – Schleife abgebrochen statt einen wirkungslosen weiteren "
                    "Versuch zu verbrauchen."
                )
                if self.last_project_slug:
                    try:
                        upsert_ticket(
                            ticket_id=f"recurring-failure-{self.last_project_slug}",
                            title=f"Nicht behobener Verifikations-Fehler: {self.last_project_slug}",
                            source="orchestrator", status="blocked", project_slug=self.last_project_slug,
                            detail=f"Fixversuch änderte nichts an {len(report.failures)} Testfehler(n) – "
                                   "vermutlich falscher/unzureichend instruierter Agent."[:300],
                        )
                    except Exception as e:
                        notify(f"  ⚠️ [dim yellow]Ticket für ungelösten Testfehler konnte nicht angelegt werden: {e}[/dim yellow]")
                break
            previous_failure_signature = current_signature

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
                    + (f"\n{diag}" if (diag := _diagnose_import_failure(f.message)) else "")
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
                            detail="\n".join(summary_lines).strip()[:300],
                        )
                    except Exception as e:
                        notify(f"  ⚠️ [dim yellow]Ticket für ungelösten Testfehler konnte nicht angelegt werden: {e}[/dim yellow]")

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
            elif docker_report.reason_skipped and "Daemon" in docker_report.reason_skipped:
                # Sichtbar (anders als "kein Dockerfile"/"Docker nicht installiert"), weil diese
                # Ursache sonst leicht mit einem echten, im Dockerfile liegenden Fehler verwechselt
                # wird - siehe _DOCKER_DAEMON_UNAVAILABLE_RE (core/verifier/models.py).
                notify(f"  🐳 [dim yellow]{docker_report.reason_skipped}[/dim yellow]")
                summary_lines.append(f"- 🐳 ⏭️ {docker_report.reason_skipped}")

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
        # Fingerabdruck aller Lint-Funde dieses Laufs ("tool:datei:regel") - dient
        # core/project_status.py.has_repeated_lint_finding() dazu, denselben, über mehrere
        # Läufe unverändert bestehen bleibenden Lint-Fund zu erkennen (siehe Kommentar dort).
        # self.last_lint_signature statt Erweiterung des Rückgabe-Tupels dieser Methode - hält
        # bestehende Aufrufer/Tests, die die feste Tupel-Länge erwarten, unverändert.
        self.last_lint_signature: list[str] = []
        if not (budget_aborted or manually_cancelled):
            lint_reports = await asyncio.to_thread(verifier.check_lint)
            for lint in lint_reports:
                if not lint.attempted:
                    continue
                self.last_lint_signature.extend(
                    f"{lint.tool}:{i.file_path}:{i.rule}" for i in lint.issues
                )
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

        # Vollständigkeits-Check: erkennt Stub-/Platzhalter-Code (z.B. "Hier würde die
        # Verschlüsselung erfolgen") und im README referenzierte, aber fehlende Dateien (z.B.
        # requirements.txt) - siehe core/verifier/completeness.py und ENABLE_COMPLETENESS_CHECK
        # (config.py) für den vollständigen Kontext. Anders als Lint/SAST blockiert ein Fund
        # hier verification_ok, weil ein Stub-Kommentar eine nicht erfüllte fachliche
        # Anforderung ist, kein Stil-Hinweis - deshalb dieselbe gezielte Fix-Schleife wie beim
        # echten Testfehler oben, statt nur eine informative Zeile im Protokoll.
        if ENABLE_COMPLETENESS_CHECK and not (budget_aborted or manually_cancelled):
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

                top = "; ".join(
                    f"{i.file_path}" + (f":{i.line_number}" if i.line_number else "") + f" – {i.message}"
                    for i in completeness_report.issues[:5]
                )
                if len(completeness_report.issues) > 5:
                    top += f" … und {len(completeness_report.issues) - 5} weitere"
                notify(f"  🧩 [bold red]Vollständigkeits-Check: {len(completeness_report.issues)} Fund(e).[/bold red]")
                verification_ok = False

                agents_to_fix: dict[str, list] = {}
                for issue in completeness_report.issues:
                    owner = file_owners.get(issue.file_path)
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
