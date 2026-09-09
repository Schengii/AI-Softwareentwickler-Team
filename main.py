"""
main.py – Einstiegspunkt für das KI-Softwareentwickler-Team

Starte das System mit:
    python main.py
"""

import io
import sys

# Windows UTF-8 Fix: Emojis und Sonderzeichen korrekt ausgeben
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from interface.cli import CLIInterface


def main():
    """Startet das KI-Softwareentwickler-Team.

    Standardmäßig die interaktive CLI. Mit `--dashboard [--port N] [--host ADRESSE]`
    stattdessen das Web-Dashboard (siehe interface/web_dashboard.py). Ohne `--host`
    bindet das Dashboard aus Sicherheitsgründen nur auf 127.0.0.1 (config.DASHBOARD_HOST).
    Mit `--check-issues` läuft EIN Poll-Zyklus über offene GitHub-Issues mit
    config.ISSUE_TRIGGER_LABEL und beendet sich danach wieder – gedacht für einen externen
    Aufruf per Cron/Windows-Taskplaner/GitHub-Actions-Schedule (siehe core/issue_watcher.py),
    kein eingebauter Dauer-Scheduler.
    Mit `--work-backlog` läuft EIN Poll-Zyklus über bereits im Backlog wartende, abhängigkeits-
    freie "todo"-Tickets (siehe core/backlog_worker.py) – das Team wartet dabei NICHT auf einen
    externen Trigger (Issue-Label), sondern greift eigenständig priorisierte Arbeit auf, die
    z.B. per `/backlog-add` vorgemerkt wurde.
    Mit `--check-deployments` läuft EIN Poll-Zyklus, der jedes per `/deploy-cloud` deployte
    Projekt auf echte Erreichbarkeit prüft und bei einem Ausfall automatisch ein Backlog-Ticket
    eröffnet (siehe core/production_monitor.py) – dasselbe On-Call-Prinzip wie oben, nur für
    bereits live laufende Deployments statt für offene Aufgaben.
    Mit `--eval [--tasks t1,t2]` startet die kanonische Benchmark-Evaluierungs-Suite
    (siehe evals/), misst Token-Verbrauch, Dauer und Verifikationsergebnis und speichert
    die Ergebnisse in der Benchmark-Historie. Mit `--list-evals` werden alle verfügbaren
    Benchmark-Aufgaben aufgelistet.
    Mit `--audit-workspace` läuft EIN Poll-Zyklus, der ProjectVerifier.run_tests() erneut gegen
    JEDES vorhandene Workspace-Projekt ausführt (unabhängig von aktiver Entwicklung) und bei
    einem echten Fehlschlag ein Backlog-Ticket öffnet (siehe core/workspace_audit.py) – dasselbe
    On-Call-Prinzip wie `--check-dependencies`, nur für Verifikations-Drift statt neuer CVEs.
    Mit `--propose-roadmap <projekt>` lässt der product_owner-Agent read-only 3-5 sinnvolle
    nächste Schritte für ein bestehendes workspace/-Projekt vorschlagen (siehe
    core/roadmap_advisor.py) - landet als niedrig priorisierte Tickets im Backlog
    (source="product_owner_proposal"), NICHT automatisch umgesetzt.
    Mit `--team-retro` läuft EIN Durchlauf, der alle offenen Backlog-Tickets OHNE automatischen
    Retry-Pfad (z.B. "unused-agent-<id>" von core/optimization_advisor.py, "team-verification-
    trend" von core/workspace_audit.py) auflistet, die seit core/team_retro.STALE_TICKET_DAYS
    Tagen unverändert liegen (siehe core/team_retro.py) – gedacht für eine periodische, z.B.
    wöchentliche Routine (Cron/Taskplaner/`/loop`/`schedule`-Skill), die genau die Ticket-
    Kategorie sichtbar macht, die --work-backlog bewusst NIE von selbst aufgreift.
    Mit `--weekly-digest [--days N]` (Standard: core/team_retro.DIGEST_WINDOW_DAYS=7) zeigt ein
    Sprint-Review-artiger Überblick abgeschlossene/neu eröffnete Tickets, Velocity, Token-
    verbrauch und Verifikations-Erfolgsquote der letzten N Tage, plus denselben liegengebliebenen
    Ticket-Block wie `--team-retro`.
    """
    if "--sync-obsidian" in sys.argv:
        from core.obsidian_sync import sync_project_to_obsidian
        force = "--force" in sys.argv
        res = sync_project_to_obsidian(force=force)
        print(res.format_summary())
        return

    if "--watch-obsidian" in sys.argv:
        from scripts.watch_obsidian_sync import run_watcher
        run_watcher()
        return

    if "--check-models" in sys.argv:
        # Beantwortet die Frage, die sich das Framework zuvor nie gestellt hat: Mit welchen
        # Modellen arbeitet das Team gerade WIRKLICH? Live-Fund der Masterplan-Analyse: Alle
        # drei Komplexitätsstufen wurden von ein und demselben Modell beantwortet, obwohl
        # config.py drei verschiedene vorsieht.
        import asyncio

        from core.model_preflight import format_preflight_report, run_model_preflight

        print("🔎 Prüfe die tatsächliche Verfügbarkeit aller Modell-Stufen ...\n")
        ergebnisse = asyncio.run(run_model_preflight())
        print(format_preflight_report(ergebnisse))
        return

    if "--list-evals" in sys.argv:

        from evals.tasks import list_tasks
        print("🎯 Verfügbare Benchmark-Aufgaben:")
        for t in list_tasks():
            print(f"  - {t.slug:<20} [{t.category:<8}] {t.name}: {t.description}")
        return

    if "--eval" in sys.argv:
        import asyncio

        from evals.runner import run_benchmark

        tasks_filter = None
        if "--tasks" in sys.argv:
            try:
                tasks_raw = sys.argv[sys.argv.index("--tasks") + 1]
                tasks_filter = [t.strip() for t in tasks_raw.split(",") if t.strip()]
            except IndexError:
                pass

        print("🚀 Starte KI-Team Benchmark-Suite...")
        suite_res = asyncio.run(run_benchmark(task_slugs=tasks_filter, status_callback=print))
        print("\n" + suite_res.format_terminal_table())
        return

    if "--check-dependencies" in sys.argv:
        import asyncio

        from core.dependency_watch import run_dependency_watch_cycle

        report = asyncio.run(run_dependency_watch_cycle(status_callback=print))
        if report.scanned_projects == 0:
            print("ℹ️  Keine Projekte im Workspace gefunden.")
        elif not report.results:
            print(f"✅ {report.scanned_projects} Projekt(e) geprüft – keine bekannten Schwachstellen gefunden.")
        else:
            for r in report.results:
                print(f"🔓 {r.project_name}: {r.detail}")
        return

    if "--audit-workspace" in sys.argv:
        import asyncio

        from core.workspace_audit import run_workspace_audit_cycle

        report = asyncio.run(run_workspace_audit_cycle(status_callback=print))
        if report.scanned_projects == 0:
            print("ℹ️  Keine Projekte im Workspace gefunden.")
        else:
            failed = [r for r in report.results if not r.healthy]
            print(f"📋 {report.scanned_projects} Projekt(e) erneut geprüft.")
            if not failed:
                print("✅ Alle Projekte weiterhin verifiziert.")
            else:
                for r in failed:
                    print(f"❌ {r.project_name}: {r.detail}")
        if report.verification_trend_warning:
            print(f"⚠️ {report.verification_trend_warning}")
        return

    if "--propose-roadmap" in sys.argv:
        import asyncio

        from agents.orchestrator import Orchestrator
        from core.roadmap_advisor import propose_next_steps

        try:
            slug = sys.argv[sys.argv.index("--propose-roadmap") + 1]
        except IndexError:
            print("❌ Fehler: Bitte gib ein Projekt an (z. B. `python main.py --propose-roadmap mein-projekt`).")
            return
        report = asyncio.run(propose_next_steps(Orchestrator(), slug))
        if report.error:
            print(f"⚠️ {report.error}")
        else:
            print(f"🧭 {len(report.ticket_ids)} Vorschlag/Vorschläge für '{slug}' als Ticket angelegt:")
            for p in report.proposals:
                print(f"  - {p.title}: {p.rationale}")
        return

    if "--team-retro" in sys.argv:
        from core.team_retro import build_team_retro_report

        report = build_team_retro_report()
        print(report.format_for_humans())
        return

    if "--weekly-digest" in sys.argv:
        from core.team_retro import DIGEST_WINDOW_DAYS, build_weekly_digest

        window = DIGEST_WINDOW_DAYS
        if "--days" in sys.argv:
            try:
                window = int(sys.argv[sys.argv.index("--days") + 1])
            except (IndexError, ValueError):
                pass
        print(build_weekly_digest(window_days=window).format_for_humans())
        return

    if "--check-pr-reviews" in sys.argv:
        import asyncio

        from core.pr_review_watcher import run_pr_review_cycle

        report = asyncio.run(run_pr_review_cycle(status_callback=print))
        if not report.gh_available:
            print("ℹ️  `gh`-CLI nicht installiert/nicht authentifiziert – PR-Review-Check übersprungen.")
        else:
            if report.created_ticket_ids:
                print(f"📥 {len(report.created_ticket_ids)} neues PR-Review Feedback Ticket(s) erstellt: {', '.join(report.created_ticket_ids)}")
            else:
                print(f"✅ {report.scanned_prs} offene(r) PR(s) geprüft – kein neues Review-Feedback gefunden.")
        return

    if "--check-issues" in sys.argv:
        import asyncio

        from core.issue_watcher import run_issue_poll_cycle

        report = asyncio.run(run_issue_poll_cycle(status_callback=print))
        if not report.gh_ready:
            print("ℹ️  `gh`-CLI nicht installiert/nicht eingeloggt – Issue-Poll übersprungen.")
        else:
            if report.merged_ticket_ids:
                print(f"🔀 {len(report.merged_ticket_ids)} Backlog-Ticket(s) auf gemergte PRs aktualisiert: {', '.join(report.merged_ticket_ids)}")
            if not report.results:
                print("ℹ️  Keine neuen Issues mit passendem Label gefunden.")
            else:
                for r in report.results:
                    detail = f" – {r.detail}" if r.detail else ""
                    print(f"#{r.issue_number} '{r.title}' -> {r.outcome}{detail}")
        return

    if "--work-backlog" in sys.argv:
        import asyncio

        from core.backlog_worker import run_backlog_poll_cycle

        report = asyncio.run(run_backlog_poll_cycle(status_callback=print))
        if report.merged_ticket_ids:
            print(f"🔀 {len(report.merged_ticket_ids)} Backlog-Ticket(s) auf gemergte PRs aktualisiert: {', '.join(report.merged_ticket_ids)}")
        if report.skipped_reason:
            print(f"ℹ️  {report.skipped_reason}")
        for r in report.results:
            detail = f" – {r.detail}" if r.detail else ""
            print(f"`{r.ticket_id}` '{r.title}' -> {r.outcome}{detail}")
        # Team-Optimierung (KI-Team-Weiterentwicklung): siehe core/backlog_worker.py.
        # BacklogPollReport.retries_exhausted_ticket_ids-Docstring - separat und deutlich
        # hervorgehoben, statt in der generischen results-Liste oben untergehen zu lassen.
        if report.retries_exhausted_ticket_ids:
            print(
                f"🛑 {len(report.retries_exhausted_ticket_ids)} Ticket(s) haben ihre automatischen "
                f"Wiederholungsversuche ausgeschöpft und benötigen jetzt menschliche Prüfung: "
                f"{', '.join(report.retries_exhausted_ticket_ids)}"
            )
        return

    if "--check-deployments" in sys.argv:
        import asyncio

        from core.production_monitor import run_deployment_health_check_cycle

        report = asyncio.run(run_deployment_health_check_cycle(status_callback=print))
        if not report.checked:
            print("ℹ️  Keine überwachten Deployments gefunden (siehe `/deploy-cloud`).")
        else:
            for r in report.checked:
                print(f"{'✅' if r.healthy else '❌'} {r.project_slug} ({r.url}): {r.detail}")
        return

    if "--goal" in sys.argv:
        import asyncio
        from pathlib import Path

        from config import WORKSPACE_DIR
        from core.goal_loop import run_goal_loop

        try:
            goal_idx = sys.argv.index("--goal") + 1
            goal_text = sys.argv[goal_idx]
        except IndexError:
            print("❌ Fehler: Bitte gib ein Ziel nach `--goal` an (z. B. `python main.py --goal \"Baue eine Notiz-API\"`).")
            return

        max_iterations = 5
        if "--max-iterations" in sys.argv:
            try:
                max_iterations = int(sys.argv[sys.argv.index("--max-iterations") + 1])
            except (IndexError, ValueError):
                pass

        project_dir = None
        if "--project" in sys.argv:
            try:
                proj_name = sys.argv[sys.argv.index("--project") + 1]
                project_dir = str(Path(WORKSPACE_DIR) / proj_name)
            except IndexError:
                pass

        print(f"🎯 Starte autonomen Ziel-Loop: '{goal_text}' (max. {max_iterations} Iterationen)...")
        res = asyncio.run(
            run_goal_loop(
                goal=goal_text,
                project_dir=project_dir,
                max_iterations=max_iterations,
                status_callback=print,
            )
        )
        print("\n" + res.format_summary())
        return

    if "--dashboard" in sys.argv:
        from interface.web_dashboard import run_dashboard
        port = 8080
        host = None
        if "--port" in sys.argv:
            try:
                port = int(sys.argv[sys.argv.index("--port") + 1])
            except (IndexError, ValueError):
                pass
        if "--host" in sys.argv:
            try:
                host = sys.argv[sys.argv.index("--host") + 1]
            except IndexError:
                pass
        run_dashboard(port=port, host=host)
        return

    cli = CLIInterface()
    cli.run()


if __name__ == "__main__":
    main()
