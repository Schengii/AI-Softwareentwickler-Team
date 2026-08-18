"""
interface/cli.py – Kommandozeilen-Interface für das KI-Softwareentwickler-Team

Bietet ein schönes, interaktives CLI mit:
- Farbiger Ausgabe (Rich-Bibliothek)
- Echtzeit-Status-Updates während Agenten arbeiten
- Gesprächsverlauf-Anzeige
- Hilfe-Befehle
"""

import asyncio
import sys
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table
from rich import box
from agents.orchestrator import Orchestrator
from config import validate_config

console = Console()

# ──────────────────────────────────────────
# ASCII-Banner
# ──────────────────────────────────────────
BANNER = """
╔══════════════════════════════════════════════════════════════╗
║        🤖  KI-Softwareentwickler-Team  🤖                   ║
║        ─────────────────────────────────────                 ║
║  Dein persönliches KI-Team für Softwareentwicklung          ║
║  Powered by Google Gemini                                    ║
╚══════════════════════════════════════════════════════════════╝
"""

HELP_TEXT = """
**Verfügbare Befehle:**

| Befehl | Beschreibung |
|--------|--------------|
| `/team` | Zeigt alle verfügbaren Agenten an |
| `/verlauf` | Zeigt den bisherigen Gesprächsverlauf |
| `/neu` | Startet eine neue Konversation (löscht Verlauf) |
| `/hilfe` | Zeigt diese Hilfe an |
| `/beenden` | Beendet das Programm |

**Einfach eine Aufgabe eingeben, z.B.:**
- *"Erstelle eine einfache Todo-App"*
- *"Baue eine REST-API für eine Blog-Plattform"*
- *"Überprüfe die Sicherheit meines Login-Systems"*
"""


class CLIInterface:
    """Das Kommandozeilen-Interface für das KI-Team."""

    def __init__(self):
        self._orchestrator = Orchestrator()
        self._status_messages: list[str] = []

    def run(self) -> None:
        """Startet das interaktive CLI."""
        # Konfiguration prüfen
        errors = validate_config()
        if errors:
            for error in errors:
                console.print(f"❌ Konfigurationsfehler: {error}", style="bold red")
            console.print(
                "\n💡 Bitte trage deinen API-Key in die .env Datei ein.",
                style="yellow"
            )
            sys.exit(1)

        # Banner anzeigen
        console.print(BANNER, style="bold cyan")
        console.print(
            "💡 Tippe /hilfe für eine Befehlsübersicht oder starte direkt mit deiner Aufgabe!\n",
            style="dim"
        )

        # Haupt-Loop starten
        asyncio.run(self._main_loop())

    async def _main_loop(self) -> None:
        """Hauptschleife: Eingabe → Verarbeitung → Ausgabe."""
        while True:
            try:
                user_input = console.input(
                    "[bold green]Du[/bold green] → "
                ).strip()
            except (KeyboardInterrupt, EOFError):
                self._print_goodbye()
                break

            if not user_input:
                continue

            # Befehle verarbeiten
            if user_input.startswith("/"):
                should_exit = await self._handle_command(user_input)
                if should_exit:
                    break
                continue

            # Aufgabe an das Team übergeben
            await self._process_task(user_input)

    async def _process_task(self, user_input: str) -> None:
        """Verarbeitet eine Nutzeraufgabe und zeigt das Ergebnis an."""
        self._status_messages = []
        status_lines = []

        console.print()  # Leerzeile

        # Live-Status-Anzeige während Agenten arbeiten
        with Live(
            self._render_status_panel(status_lines),
            console=console,
            refresh_per_second=4,
        ) as live:
            def on_status(msg: str):
                status_lines.append(msg)
                live.update(self._render_status_panel(status_lines))

            try:
                result = await self._orchestrator.process(
                    user_request=user_input,
                    status_callback=on_status,
                )
            except Exception as e:
                console.print(
                    f"\n❌ Fehler bei der Verarbeitung: {e}",
                    style="bold red"
                )
                return

        # Ergebnis anzeigen
        console.print()
        console.print(
            Panel(
                Markdown(result),
                title="[bold blue]🤖 Hauptagent[/bold blue]",
                border_style="blue",
                padding=(1, 2),
            )
        )
        console.print()

    async def _handle_command(self, command: str) -> bool:
        """
        Verarbeitet einen CLI-Befehl.
        Returns: True wenn das Programm beendet werden soll.
        """
        cmd = command.lower().strip()

        if cmd in ("/beenden", "/exit", "/quit", "/q"):
            self._print_goodbye()
            return True

        elif cmd in ("/hilfe", "/help", "/h"):
            console.print(Panel(Markdown(HELP_TEXT), title="Hilfe", border_style="cyan"))

        elif cmd in ("/team", "/agenten"):
            info = self._orchestrator.get_team_info()
            console.print(Panel(Markdown(info), title="Dein Team", border_style="green"))

        elif cmd in ("/verlauf", "/history"):
            self._print_history()

        elif cmd in ("/neu", "/reset", "/clear"):
            self._orchestrator.clear_history()
            console.print(
                "✅ Gesprächsverlauf gelöscht. Neue Konversation gestartet.",
                style="green"
            )

        else:
            console.print(
                f"❓ Unbekannter Befehl: '{command}'. Tippe /hilfe für eine Übersicht.",
                style="yellow"
            )

        return False

    def _render_status_panel(self, lines: list[str]) -> Panel:
        """Rendert das Status-Panel mit Live-Updates."""
        if not lines:
            content = Text("🔄 Starte...", style="dim")
        else:
            content = Text("\n".join(lines))

        return Panel(
            content,
            title="[bold yellow]⚙️  Team arbeitet...[/bold yellow]",
            border_style="yellow",
            padding=(0, 1),
        )

    def _print_history(self) -> None:
        """Zeigt den Gesprächsverlauf an."""
        history = self._orchestrator.get_history()
        messages = history.get_messages(max_messages=20)

        if not messages:
            console.print("📭 Noch keine Nachrichten im Verlauf.", style="dim")
            return

        console.print(f"\n📜 Gesprächsverlauf ({len(messages)} Nachrichten):\n")
        for msg in messages:
            if msg.role == "user":
                console.print(f"[bold green]Du:[/bold green] {msg.content[:100]}...")
            else:
                console.print(f"[bold blue]Team:[/bold blue] {msg.content[:100]}...")
        console.print()

    def _print_goodbye(self) -> None:
        """Zeigt die Abschiedsnachricht an."""
        console.print(
            "\n👋 Auf Wiedersehen! Dein KI-Team freut sich auf das nächste Projekt.\n",
            style="bold cyan"
        )
