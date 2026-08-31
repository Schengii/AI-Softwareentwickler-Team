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
    """
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
