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
    """
    if "--check-issues" in sys.argv:
        import asyncio

        from core.issue_watcher import run_issue_poll_cycle

        report = asyncio.run(run_issue_poll_cycle(status_callback=print))
        if not report.gh_ready:
            print("ℹ️  `gh`-CLI nicht installiert/nicht eingeloggt – Issue-Poll übersprungen.")
        elif not report.results:
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
