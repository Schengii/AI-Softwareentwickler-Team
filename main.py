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
    Mit `--eval [--tasks t1,t2]` startet die kanonische Benchmark-Evaluierungs-Suite
    (siehe evals/), misst Token-Verbrauch, Dauer und Verifikationsergebnis und speichert
    die Ergebnisse in der Benchmark-Historie. Mit `--list-evals` werden alle verfügbaren
    Benchmark-Aufgaben aufgelistet.
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
