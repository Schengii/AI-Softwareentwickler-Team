"""
interface/cli.py – Interaktives Terminal-Interface für das KI-Softwareentwickler-Team (30 Spezialisten)

Bietet:
- Live-Statusanzeige mit aktuellem Bearbeitungsschritt, Phasen und arbeitenden Agenten
- Farbige Rich-Ausgabe
- Automatischer GitHub-Commit & Push Dialog
- Workspace- & Projekt-Dateiverwaltung (/workspace, /export)
- Test-Runner (/run-tests)
"""

import asyncio
import os
import sys
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.table import Table
from rich.prompt import Confirm
from rich import box
from agents.orchestrator import Orchestrator
from core.code_sandbox import CodeSandbox
from config import validate_config, WORKSPACE_DIR

console = Console()

BANNER = """
╔══════════════════════════════════════════════════════════════╗
║        🤖  KI-Softwareentwickler-Team (v4.2)  🤖            ║
║        ─────────────────────────────────────                 ║
║  Dein 32-köpfiges autonomes KI-Entwickler-Team               ║
║  5 Fachbereiche • RAG • Sandbox • MCP & Web-Dashboard        ║
╚══════════════════════════════════════════════════════════════╝
"""

HELP_TEXT = """
**Verfügbare Befehle:**

| Befehl | Beschreibung |
|---|---|
| `/projekte` | Listet alle bestehenden Projekte im Workspace auf |
| `/load <pfad/name>` | Lädt ein bestehendes Projekt (Workspace oder externer Pfad) zur Weiterentwicklung |
| `/tokens` | Zeigt den aktuellen Tokenverbrauch und verbleibende Kontingente an |
| `/rag <begriff>` | Führt eine semantische Code-Recherche im geladenen Projekt durch |
| `/team` | Zeigt alle 5 Fachbereiche, Teamleiter und 33 Spezialisten an |
| `/workspace [projekt]` | Listet alle generierten Dateien im Projektordner auf |
| `/export [projekt]` | Packt das Projektverzeichnis in ein ZIP-Archiv |
| `/run-tests [projekt]` | Führt automatische Unit-Tests im Projekt aus |
| `/push` | Führt manuell einen Git-Commit & Push aus |
| `/verlauf` | Zeigt den bisherigen Gesprächsverlauf |
| `/neu` | Startet eine neue Konversation (löscht Verlauf) |
| `/hilfe` | Zeigt diese Hilfe an |
| `/beenden` | Beendet das Programm |

**So startest du ein neues Projekt:**
Schreibe einfach deine Anforderung in den Chat (z. B. *"Erstelle eine Todo-Webapp mit FastAPI & SQLite"*).

**So entwickelst du ein bestehendes/externes Projekt weiter:**
1. Lade das Projekt mit `/load C:\\MeinProjekt` oder `/load mein-projekt`
2. Gib dem Team deine Anweisung (z. B. *"Füge Authentifizierung hinzu und refaktoriere die Datenbank"*).
"""


class CLIInterface:
    """Das interaktive Kommandozeilen-Interface."""

    def __init__(self):
        self._orchestrator = Orchestrator()
        self._workspace = self._orchestrator.get_workspace_manager()

    def run(self) -> None:
        """Startet das interaktive CLI."""
        errors = validate_config()
        if errors:
            for error in errors:
                console.print(f"❌ Konfigurationsfehler: {error}", style="bold red")
            console.print(
                "\n💡 Bitte trage deinen GEMINI_API_KEY oder ANTHROPIC_API_KEY in die .env Datei ein.",
                style="yellow"
            )
            sys.exit(1)

        console.print(BANNER, style="bold cyan")
        console.print(
            "💡 Schreibe einfach deine Projektidee in den Chat! (Tippe /hilfe für Befehle)\n",
            style="dim"
        )

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
        """Verarbeitet eine Nutzeraufgabe mit detailliertem Live-Status."""
        status_lines: list[str] = []

        console.print()

        # Live-Statusanzeige während Agenten arbeiten
        with Live(
            self._render_status_panel(status_lines),
            console=console,
            refresh_per_second=6,
            transient=False,
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

        # Gesamtergebnis ausgeben
        console.print()
        console.print(
            Panel(
                Markdown(result),
                title="[bold blue]🤖 Hauptagent (Geprüftes Gesamtergebnis)[/bold blue]",
                border_style="blue",
                padding=(1, 2),
            )
        )
        console.print()

        # GitHub-Push Dialog
        await self._ask_for_git_push(user_input)

    async def _ask_for_git_push(self, task_summary: str) -> None:
        """Fragt den Nutzer, ob der GitHub-Agent Änderungen committen und pushen soll."""
        github_agent = self._orchestrator._agents.get("github")
        if not github_agent:
            return

        diff_status = github_agent.get_status()
        if not diff_status:
            return

        console.print("🔀 [bold cyan]GitHub-Agent:[/bold cyan] Ich habe ungespeicherte Änderungen im Projekt erkannt.")
        try:
            should_push = Confirm.ask(
                "Möchtest du, dass ich die Änderungen automatisch committe und auf GitHub pushe?",
                default=False,
            )
        except Exception:
            should_push = False

        if should_push:
            commit_msg = f"feat: implement {task_summary[:50].strip()} via AI Developer Team"
            success_c, out_c = github_agent.commit(commit_msg)
            if success_c:
                console.print(f"✅ [green]Commit erfolgreich:[/green] {commit_msg}")
                success_p, out_p = github_agent.push()
                if success_p:
                    console.print("🚀 [bold green]Änderungen erfolgreich auf GitHub gepusht![/bold green]")
                else:
                    console.print(f"⚠️ Push nicht abgeschlossen: {out_p}", style="yellow")
            else:
                console.print(f"⚠️ Commit nicht möglich: {out_c}", style="yellow")

    async def _handle_command(self, command: str) -> bool:
        """Verarbeitet CLI-Befehle."""
        parts = command.strip().split()
        cmd = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        if cmd in ("/beenden", "/exit", "/quit", "/q"):
            self._print_goodbye()
            return True

        elif cmd in ("/hilfe", "/help", "/h"):
            console.print(Panel(Markdown(HELP_TEXT), title="Hilfe", border_style="cyan"))

        elif cmd in ("/team", "/agenten"):
            info = self._orchestrator.get_team_info()
            console.print(Panel(Markdown(info), title="Dein Team (30 Spezialisten)", border_style="green"))

        elif cmd in ("/workspace", "/dateien", "/files"):
            proj_name = args[0] if args else "jobsuche-app"
            self._print_workspace(proj_name)

        elif cmd in ("/export", "/zip"):
            proj_name = args[0] if args else "jobsuche-app"
            self._export_workspace(proj_name)

        elif cmd in ("/push", "/git"):
            await self._ask_for_git_push("manuelles Update")

        elif cmd in ("/run-tests", "/test"):
            proj_name = args[0] if args else "jobsuche-app"
            self._run_tests(proj_name)

        elif cmd in ("/load", "/laden", "/open", "/oeffnen", "/import"):
            if not args:
                console.print("⚠️ Bitte gib den Pfad oder Namen des Projekts an:\n👉 `/load <pfad_oder_name>`", style="yellow")
                return False
            target_path = " ".join(args)
            ctx = self._workspace.read_existing_project_context(target_path)
            if ctx:
                self._orchestrator._history.add_user_message(f"Hier ist der bestehende Projektcode, den wir analysieren/erweitern:\n\n{ctx}")
                console.print(f"✅ [bold green]Projekt erfolgreich geladen:[/bold green] `{target_path}` ({len(ctx)} Zeichen analysiert).")
                console.print("💡 Du kannst deinem Team jetzt Aufgaben zu diesem Projekt stellen (z. B. *'Refaktoriere die App und füge Tests hinzu'*).", style="dim")
            else:
                console.print(f"⚠️ Konnte keine relevanten Quellcodedateien unter `{target_path}` finden.", style="yellow")

        elif cmd in ("/rag", "/search", "/find"):
            if not args:
                console.print("⚠️ Bitte gib einen Suchbegriff an: `/rag <query>`", style="yellow")
                return False
            query_str = " ".join(args)
            from core.vector_store import code_index
            results = code_index.search(query_str, top_k=4)
            if results:
                console.print(f"🔍 [bold green]RAG-Treffer für '{query_str}':[/bold green]")
                for r in results:
                    console.print(f"📄 `{r['file']}` (Zeile {r['line_start']}):\n```python\n{r['chunk'][:400]}\n```")
            else:
                console.print(f"Keine relevanten Codeblöcke für '{query_str}' gefunden (Index ist leer oder keine Übereinstimmung). Lade zuerst ein Projekt mit `/load`.", style="yellow")

        elif cmd in ("/tokens", "/token", "/verbrauch", "/quota", "/kosten"):
            from core.quota_estimator import QuotaEstimator
            table_md = QuotaEstimator.format_markdown_table()
            console.print(Panel(Markdown(table_md), title="🪙 Live Token & Quota Tracker", border_style="gold1"))

        elif cmd in ("/projekte", "/projects", "/list"):
            self._list_all_projects()

        elif cmd in ("/verlauf", "/history"):
            self._print_history()

        elif cmd in ("/neu", "/reset", "/clear"):
            self._orchestrator.clear_history()
            console.print("✅ Gesprächsverlauf gelöscht. Neue Konversation gestartet.", style="green")

        else:
            console.print(f"❓ Unbekannter Befehl: '{command}'. Tippe /hilfe für eine Übersicht.", style="yellow")

        return False

    def _list_all_projects(self) -> None:
        """Listet alle vorhandenen Projekte im Workspace auf."""
        base = self._workspace.base_dir
        subdirs = [p for p in base.iterdir() if p.is_dir()]
        if not subdirs:
            console.print("📭 Noch keine Projekte im Workspace vorhanden.", style="yellow")
            return

        table = Table(title="🗂️ Vorhandene Projekte im Workspace", box=box.ROUNDED)
        table.add_column("Projektname", style="cyan bold")
        table.add_column("Dateien", justify="right", style="green")
        table.add_column("Pfad", style="dim")

        for d in sorted(subdirs, key=lambda x: x.name):
            file_count = sum(1 for f in d.rglob("*") if f.is_file())
            table.add_row(d.name, str(file_count), str(d))

        console.print(table)

    def _print_workspace(self, project_name: str) -> None:
        files = self._workspace.list_project_files(project_name)
        if not files:
            console.print(f"📭 Keine Dateien im Projektordner 'workspace/{project_name}/' gefunden.", style="yellow")
            return

        table = Table(title=f"📁 Dateien in workspace/{project_name}/", box=box.ROUNDED)
        table.add_column("Dateipfad", style="cyan")
        table.add_column("Größe", justify="right", style="green")

        for f in files:
            table.add_row(f["path"], f"{f['size_bytes']:,} B")

        console.print(table)

    def _export_workspace(self, project_name: str) -> None:
        try:
            zip_path = self._workspace.create_project_zip(project_name)
            console.print(f"📦 Projekt erfolgreich als ZIP exportiert:\n👉 [bold green]{zip_path}[/bold green]")
        except Exception as e:
            console.print(f"❌ Fehler beim Export: {e}", style="bold red")

    def _run_tests(self, project_name: str) -> None:
        proj_dir = self._workspace.get_project_dir(project_name)
        console.print(f"🧪 Starte Tests in '{proj_dir}'...", style="cyan")
        res = CodeSandbox.run_command([sys.executable, "-m", "unittest", "discover"], cwd=proj_dir)

        if res.exit_code == 0:
            console.print(f"✅ Alle Tests erfolgreich!\n{res.stdout}", style="bold green")
        else:
            console.print(f"❌ Tests fehlgeschlagen:\n{res.stderr or res.stdout}", style="bold red")

    def _render_status_panel(self, lines: list[str]) -> Panel:
        if not lines:
            content = Text("🔄 Starte Agenten-Team...", style="dim")
        else:
            recent_lines = lines[-14:]
            content = Text.from_markup("\n".join(recent_lines))

        return Panel(
            content,
            title="[bold yellow]⚡ Live-Status: Team arbeitet im Hintergrund...[/bold yellow]",
            border_style="yellow",
            padding=(0, 1),
        )

    def _print_history(self) -> None:
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
        console.print(
            "\n👋 Auf Wiedersehen! Dein KI-Team freut sich auf das nächste Projekt.\n",
            style="bold cyan"
        )
