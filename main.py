"""
main.py – Einstiegspunkt für das KI-Softwareentwickler-Team

Starte das System mit:
    python main.py
"""

import sys
import io

# Windows UTF-8 Fix: Emojis und Sonderzeichen korrekt ausgeben
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from interface.cli import CLIInterface


def main():
    """Startet das KI-Softwareentwickler-Team."""
    cli = CLIInterface()
    cli.run()


if __name__ == "__main__":
    main()
