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
    """
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
