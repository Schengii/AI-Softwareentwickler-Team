"""
interface/cli.py – Interaktives Terminal-Interface für das KI-Softwareentwickler-Team (33 Spezialisten)

Bietet:
- Live-Statusanzeige mit aktuellem Bearbeitungsschritt, Phasen und arbeitenden Agenten
- Farbige Rich-Ausgabe
- Automatischer GitHub-Commit & Push Dialog (mit Bestätigungs-Gate & Diff-Vorschau)
- Workspace- & Projekt-Dateiverwaltung (/workspace, /export, /delete-project)
- Test-Runner (/run-tests)
"""

import asyncio
import os
import sys
from pathlib import Path

from rich import box
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text

from agents.orchestrator import Orchestrator
from config import validate_config
from core.code_sandbox import CodeSandbox

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
| `/delete-project <name>` | Löscht ein Projekt unwiderruflich aus dem Workspace (mit Bestätigung) |
| `/audit-projekt [projekt]` | Lässt den Projekt-Hygiene-Agenten das Framework (oder ein Projekt) wirklich durchsehen; Löschungen nur nach Bestätigung |
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

    AUDIT_REMINDER_INTERVAL = 5  # Nach je N abgeschlossenen Aufgaben an /audit-projekt erinnern

    def __init__(self):
        self._orchestrator = Orchestrator()
        self._workspace = self._orchestrator.get_workspace_manager()
        self._loaded_project_dir: str | None = None  # von /load gesetzt, von /rag genutzt
        self._tasks_since_audit_reminder = 0

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

        # GitHub-Push Dialog. Nutzt die echte, vom TaskManager erzeugte Kurzfassung der Aufgabe
        # (Orchestrator.last_task_summary) statt der rohen Nutzereingabe für die Commit-Message –
        # user_input ist oft konversationell formuliert ("Okay ich möchte, dass ihr...") und
        # landete zuvor 1:1 (nur bei 50 Zeichen hart abgeschnitten) im Commit-Betreff. Fällt nur
        # zurück auf user_input, falls aus irgendeinem Grund keine Zusammenfassung vorliegt.
        await self._ask_for_git_push(self._orchestrator.last_task_summary or user_input)

        # Regelmäßige Erinnerung an die Projekt-Hygiene (kein Auto-Löschen – nur ein Hinweis).
        self._tasks_since_audit_reminder += 1
        if self._tasks_since_audit_reminder >= self.AUDIT_REMINDER_INTERVAL:
            self._tasks_since_audit_reminder = 0
            console.print(
                "💡 [dim]Tipp: Seit einer Weile kein Struktur-Audit mehr – "
                "`/audit-projekt` lässt den Projekt-Hygiene-Agenten das Projekt "
                "wirklich durchsehen und schlägt konkrete Aufräumungen vor.[/dim]"
            )

    @staticmethod
    def _truncate_at_word(text: str, max_len: int) -> str:
        """Kürzt einen Ein-Zeilen-Text auf max_len Zeichen, ohne mitten in einem Wort abzuschneiden.

        Vermeidet z.B. `implement Health-Check-Endpoint für FastAPI-A via ...` (hartes [:50]
        auf einem mehrzeiligen/langen task_summary) zugunsten von `... FastAPI via ...`.
        """
        flat = " ".join(text.split())  # Zeilenumbrüche/Mehrfach-Leerzeichen einebnen
        if len(flat) <= max_len:
            return flat
        cut = flat[:max_len]
        last_space = cut.rfind(" ")
        return (cut[:last_space] if last_space > 0 else cut).strip()

    async def _ask_for_git_push(self, task_summary: str) -> None:
        """
        Fragt den Nutzer, ob der GitHub-Agent Änderungen committen und pushen soll.

        Zeigt VOR der Bestätigung die konkret betroffenen Dateien, den Diff-Umfang und die
        exakte Commit-Message – nicht nur ein blindes Ja/Nein. Das ist wichtig, weil
        github_agent.commit() intern `git add -A` ausführt und damit den GESAMTEN
        Repo-Stand staged, nicht nur die Dateien des gerade bearbeiteten Projekts – der
        Nutzer soll das vor einer irreversiblen Aktion (Push) wirklich sehen können.
        """
        github_agent = self._orchestrator._agents.get("github")
        if not github_agent:
            return

        diff_status = github_agent.get_status()
        if not diff_status:
            return

        changed_files = [line.strip() for line in diff_status.splitlines() if line.strip()]
        diff_stat = github_agent.get_diff()
        commit_msg = f"feat: implement {self._truncate_at_word(task_summary, 50)} via AI Developer Team"

        console.print(
            Panel(
                (
                    f"[bold]{len(changed_files)} Datei(en) betroffen[/bold] "
                    f"(git add -A staged den GESAMTEN Repo-Stand, nicht nur dieses Projekt):\n\n"
                    + "\n".join(f"  {f}" for f in changed_files[:25])
                    + (f"\n  … und {len(changed_files) - 25} weitere" if len(changed_files) > 25 else "")
                    + (f"\n\n[dim]{diff_stat}[/dim]" if diff_stat else "")
                    + f"\n\n[bold]Geplante Commit-Message:[/bold]\n  {commit_msg}"
                ),
                title="🔀 GitHub-Agent: Vorschau vor Commit & Push",
                border_style="cyan",
            )
        )
        try:
            should_push = Confirm.ask(
                "Möchtest du, dass ich GENAU DIESE Änderungen committe und auf GitHub pushe?",
                default=False,
            )
        except Exception:
            should_push = False

        if not should_push:
            console.print("↩️ Push übersprungen – nichts wurde committet oder gepusht.", style="dim")
            return

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

    async def _delete_project_with_confirmation(self, project_name: str) -> None:
        """
        Löscht ein komplettes Projektverzeichnis aus workspace/ – IRREVERSIBEL (kompletter
        Quellcode, nicht nur Cache-Dateien). Zeigt vor der Bestätigung Pfad und Dateianzahl,
        analog zum Bestätigungs-Gate vor Git-Push (_ask_for_git_push).
        """
        # WICHTIG: Existenz VOR dem Aufruf von get_project_dir() prüfen – die Methode legt
        # das Verzeichnis bei Bedarf selbst an (mkdir(exist_ok=True)), ein Exists-Check DANACH
        # wäre also immer True und würde jede Sicherheitsprüfung wirkungslos machen.
        exists_before = (
            Path(project_name).exists() if os.path.isabs(project_name)
            else project_name in self._workspace.list_projects()
        )
        if not exists_before:
            console.print(f"⚠️ Projekt `{project_name}` existiert nicht in `workspace/`.", style="yellow")
            return

        project_dir = self._workspace.get_project_dir(project_name)
        files = self._workspace.list_project_files(project_name)
        console.print(
            Panel(
                f"[bold red]Das komplette Verzeichnis wird UNWIDERRUFLICH gelöscht:[/bold red]\n\n"
                f"  Pfad: `{project_dir}`\n"
                f"  Dateien: {len(files)}\n",
                title="🗑️ Projekt löschen: Vorschau",
                border_style="red",
            )
        )
        try:
            should_delete = Confirm.ask(
                f"Projekt `{project_name}` WIRKLICH unwiderruflich löschen?",
                default=False,
            )
        except Exception:
            should_delete = False

        if not should_delete:
            console.print("↩️ Löschung abgebrochen – nichts wurde entfernt.", style="dim")
            return

        if self._workspace.clean_project(project_name):
            console.print(f"🗑️ [bold green]Projekt `{project_name}` wurde gelöscht.[/bold green]")
            if self._loaded_project_dir == str(project_dir):
                self._loaded_project_dir = None
        else:
            console.print(f"⚠️ Löschung von `{project_name}` fehlgeschlagen.", style="yellow")

    async def _audit_project(self, target_path: str | None) -> None:
        """
        Lässt den project_cleaner-Agenten mit ECHTEM Lesezugriff (list_files/read_file/
        search_code) eine Struktur-Hygiene-Analyse durchführen – Standard: das Framework
        selbst, optional ein einzelnes workspace/-Projekt. Löscht NIE automatisch: zeigt
        den vollen Report und fragt bei konkreten Empfehlungen explizit nach Bestätigung,
        analog zu /delete-project und dem Git-Push-Gate.
        """
        from agents.project_cleaner_agent import ProjectCleanerAgent
        from config import BASE_DIR
        from core.message_bus import AgentTask

        if target_path:
            target_dir = str(self._workspace.get_project_dir(target_path))
            label = f"Projekt `{target_path}`"
        else:
            target_dir = BASE_DIR
            label = "das gesamte Framework (Projekt-Root)"

        console.print(f"🧹 [bold cyan]Projekt-Hygiene-Audit:[/bold cyan] {label} wird analysiert (echter Lesezugriff, kann etwas dauern)...")

        cleaner = self._orchestrator._agents.get("project_cleaner")
        if not cleaner:
            console.print("⚠️ project_cleaner-Agent nicht verfügbar.", style="yellow")
            return

        task = AgentTask(
            task_id="manual_audit",
            agent_id="project_cleaner",
            description=(
                f"Führe eine vollständige Struktur-Hygiene-Analyse von {label} durch. "
                "Nutze list_files/read_file/search_code, um dir einen ECHTEN Überblick zu "
                "verschaffen, bevor du irgendetwas zur Löschung empfiehlst."
            ),
            context="",
            project_dir=target_dir,
            allow_tools=True,
            tools_read_only=True,
            max_tool_iterations=8,
        )
        result = await cleaner.execute(task)

        if not result.success:
            console.print(f"⚠️ Audit fehlgeschlagen: {result.error}", style="yellow")
            return

        console.print(Panel(Markdown(result.content), title="🧹 Projekt-Hygiene-Report", border_style="cyan"))

        recommended = ProjectCleanerAgent.parse_recommended_deletions(result.content)
        if not recommended:
            console.print("✅ Keine konkreten Löschempfehlungen.", style="green")
            return

        console.print(
            Panel(
                "\n".join(f"  {p}" for p in recommended),
                title=f"🗑️ {len(recommended)} Löschempfehlung(en) – bisher wurde NICHTS gelöscht",
                border_style="red",
            )
        )
        try:
            should_apply = Confirm.ask("Diese Pfade jetzt wirklich löschen?", default=False)
        except Exception:
            should_apply = False

        if not should_apply:
            console.print("↩️ Nichts gelöscht.", style="dim")
            return

        removed, failed = ProjectCleanerAgent.apply_confirmed_deletions(target_dir, recommended)
        if removed:
            console.print(f"🗑️ [bold green]{len(removed)} Pfad(e) gelöscht:[/bold green] {', '.join(removed)}")
        if failed:
            console.print(f"⚠️ {len(failed)} Pfad(e) übersprungen: {', '.join(failed)}", style="yellow")

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

        elif cmd in ("/delete-project", "/clean-project", "/loeschen"):
            if not args:
                console.print("⚠️ Bitte gib den Projektnamen an: `/delete-project <name>`", style="yellow")
                return False
            await self._delete_project_with_confirmation(args[0])

        elif cmd in ("/audit-projekt", "/audit", "/hygiene"):
            await self._audit_project(args[0] if args else None)

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
                self._loaded_project_dir = str(self._workspace.get_project_dir(target_path))
                self._orchestrator._history.add_user_message(f"Hier ist der bestehende Projektcode, den wir analysieren/erweitern:\n\n{ctx}")
                console.print(f"✅ [bold green]Projekt erfolgreich geladen:[/bold green] `{target_path}` ({len(ctx)} Zeichen analysiert).")
                console.print("💡 Du kannst deinem Team jetzt Aufgaben zu diesem Projekt stellen (z. B. *'Refaktoriere die App und füge Tests hinzu'*).", style="dim")
            else:
                console.print(f"⚠️ Konnte keine relevanten Quellcodedateien unter `{target_path}` finden.", style="yellow")

        elif cmd in ("/rag", "/search", "/find"):
            if not args:
                console.print("⚠️ Bitte gib einen Suchbegriff an: `/rag <query>`", style="yellow")
                return False
            if not self._loaded_project_dir:
                console.print("⚠️ Kein Projekt geladen. Lade zuerst eines mit `/load <pfad_oder_name>`.", style="yellow")
                return False
            query_str = " ".join(args)
            from core.embedding_index import semantic_search
            results = semantic_search(self._loaded_project_dir, query_str, top_k=4)
            if results:
                console.print(f"🔍 [bold green]RAG-Treffer für '{query_str}':[/bold green]")
                for r in results:
                    score_note = f" (Ähnlichkeit: {r['score']})" if "score" in r else ""
                    console.print(f"📄 `{r['file']}` (Zeile {r['line_start']}){score_note}:\n```python\n{r['chunk'][:400]}\n```")
            else:
                console.print(f"Keine relevanten Codeblöcke für '{query_str}' gefunden.", style="yellow")

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
