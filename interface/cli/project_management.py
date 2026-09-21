"""
interface/cli/project_management.py - Workspace-Verwaltung, Tests, lokales/Cloud-Deployment.

Teil der P6-5-Aufteilung von interface/cli.py (ROADMAP_TEMP.md): CLIProjectManagementMixin
buendelt alles rund um ein einzelnes Projektverzeichnis in workspace/ - auflisten, exportieren,
loeschen, Tests ausfuehren, lokal/in die Cloud deployen.
"""

import asyncio
import os
import sys
from pathlib import Path

from rich import box
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from core.code_sandbox import CodeSandbox
from interface.cli._shared import console


class CLIProjectManagementMixin:
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

    def _resolve_project_dir(self, project_name: str | None) -> Path | None:
        """
        Löst einen optionalen Projektnamen auf einen echten, EXISTIERENDEN Projektordner auf
        - ohne Namen wird das per `/load` geladene Projekt verwendet. None, wenn nichts
        angegeben/geladen ist ODER der genannte Name nicht existiert (der Aufrufer
        unterscheidet diese beiden Fälle für eine passende Fehlermeldung selbst).
        """
        if project_name:
            exists = (
                Path(project_name).exists() if os.path.isabs(project_name)
                else project_name in self._workspace.list_projects()
            )
            return Path(self._workspace.get_project_dir(project_name)) if exists else None
        if self._loaded_project_dir:
            return Path(self._loaded_project_dir)
        return None

    async def _deploy_project_with_confirmation(self, project_name: str | None) -> None:
        """
        Deployt ein Projekt lokal per Docker (core/deployment.py: Compose bevorzugt, sonst
        Dockerfile+docker run) – mit Vorschau + Bestätigung, analog zum Git-Push-Gate
        (_ask_for_git_push): echte Container-Ausführung startet einen laufenden Prozess und
        belegt Ports, verdient dieselbe Bestätigungs-Gate-Philosophie statt stillschweigend
        loszulaufen.
        """
        project_dir = self._resolve_project_dir(project_name)
        if project_dir is None:
            if project_name:
                console.print(f"⚠️ Projekt `{project_name}` existiert nicht in `workspace/`.", style="yellow")
            else:
                console.print(
                    "⚠️ Kein Projekt angegeben und keines geladen. Nutze `/deploy <projekt>` "
                    "oder lade zuerst eines mit `/load <projekt>`.", style="yellow",
                )
            return

        from core.deployment import deploy_project, describe_deploy_plan

        console.print(
            Panel(
                f"[bold]Projekt:[/bold] `{project_dir}`\n"
                f"[bold]Geplanter Schritt:[/bold] {describe_deploy_plan(project_dir)}",
                title="🚀 Deployment: Vorschau",
                border_style="cyan",
            )
        )
        try:
            should_deploy = Confirm.ask("Wirklich deployen (startet echte Docker-Container)?", default=False)
        except Exception:
            should_deploy = False
        if not should_deploy:
            console.print("↩️ Deployment übersprungen.", style="dim")
            return

        console.print("🚀 [dim]Deploye... (kann je nach Projekt mehrere Minuten dauern)[/dim]")
        # asyncio.to_thread: deploy_project() ist blockierend (echte Subprozesse) - direkt im
        # Event-Loop aufgerufen würde es die Live-Anzeige/den Strg+C-Handler einfrieren.
        result = await asyncio.to_thread(deploy_project, project_dir)

        if not result.attempted:
            console.print(f"⚠️ {result.reason_skipped}", style="yellow")
        elif result.success:
            urls_note = "\n".join(f"  🌐 {u}" for u in result.urls) if result.urls else "  (kein Port ermittelt)"
            console.print(f"✅ [bold green]Deployment erfolgreich ({result.method}):[/bold green]\n{urls_note}")
            console.print("💡 [dim]Stoppen mit `/deploy-stop`.[/dim]")
        else:
            console.print(f"❌ [bold red]Deployment fehlgeschlagen:[/bold red]\n{result.output}", style="red")

    async def _deploy_cloud_with_confirmation(self, args: list[str]) -> None:
        """
        Deployt ein Projekt in die Cloud (core/cloud_deployment.py: Fly.io/Vercel echt per CLI,
        Render/Railway als vorbereitete Manifeste - siehe dort für die Begründung) - mit
        Vorschau + Bestätigung, analog zu /deploy (core/deployment.py, LOKALES Docker-
        Deployment). Realer Fund: CloudDeploymentManager existierte bereits vollständig fertig
        implementiert, war aber nirgends in CLI/Dashboard verdrahtet - README behauptete "CLI
        & Dashboard können per echtem Deploy-Befehl eine Preview-URL bereitstellen", was schlicht
        nicht stimmte.

        Syntax: /deploy-cloud <fly|vercel|render|railway> [projekt] [--real]
        Standard (ohne --real) ist ein Dry-Run (nur Manifeste generieren, kein echter Deploy) -
        dieselbe "sicherer Default"-Linie wie an anderer Stelle im Projekt (z.B.
        MAX_RUN_TOKENS=0), da ein echter Cloud-Deploy reale, öffentlich erreichbare Ressourcen
        anlegt.
        """
        if not args:
            console.print(
                "⚠️ Bitte gib einen Provider an: `/deploy-cloud <fly|vercel|render|railway> [projekt] [--real]`",
                style="yellow",
            )
            return
        provider = args[0].lower()
        if provider not in ("fly", "vercel", "render", "railway"):
            console.print(f"⚠️ Unbekannter Provider `{provider}`. Erlaubt: fly, vercel, render, railway.", style="yellow")
            return
        real_deploy = "--real" in args
        remaining = [a for a in args[1:] if a != "--real"]
        project_name = remaining[0] if remaining else None

        project_dir = self._resolve_project_dir(project_name)
        if project_dir is None:
            if project_name:
                console.print(f"⚠️ Projekt `{project_name}` existiert nicht in `workspace/`.", style="yellow")
            else:
                console.print(
                    "⚠️ Kein Projekt angegeben und keines geladen. Nutze `/deploy-cloud <provider> <projekt>` "
                    "oder lade zuerst eines mit `/load <projekt>`.", style="yellow",
                )
            return

        from core.cloud_deployment import CloudDeploymentManager

        manager = CloudDeploymentManager(project_dir)
        mode_note = "ECHTER Deploy-Versuch" if real_deploy else "Dry-Run (nur Manifeste generieren, kein echter Deploy)"
        console.print(
            Panel(
                f"[bold]Projekt:[/bold] `{project_dir}`\n[bold]Provider:[/bold] {provider}\n[bold]Modus:[/bold] {mode_note}",
                title="☁️ Cloud-Deployment: Vorschau",
                border_style="cyan",
            )
        )
        try:
            should_deploy = Confirm.ask(
                "Wirklich fortfahren?" + (" (echter Deploy-Befehl, kann mehrere Minuten dauern)" if real_deploy else ""),
                default=False,
            )
        except Exception:
            should_deploy = False
        if not should_deploy:
            console.print("↩️ Cloud-Deployment übersprungen.", style="dim")
            return

        console.print("☁️ [dim]Deploye...[/dim]")
        # asyncio.to_thread: deploy() ist blockierend (echte Subprozesse bei fly/vercel) -
        # direkt im Event-Loop aufgerufen würde es die Live-Anzeige/den Strg+C-Handler einfrieren.
        result = await asyncio.to_thread(manager.deploy, provider, not real_deploy)

        if not result.attempted:
            console.print(f"⚠️ {result.reason_skipped}", style="yellow")
        elif result.success:
            console.print(f"✅ [bold green]Cloud-Deployment ({result.provider}) erfolgreich:[/bold green]\n  🌐 {result.preview_url}")
            if result.generated_files:
                console.print(f"📄 [dim]Generierte Manifeste: {', '.join(result.generated_files)}[/dim]")
            if real_deploy:
                # Nur ein ECHTER, erfolgreicher Deploy wird überwacht (core/production_monitor.py)
                # - eine Dry-Run-URL wurde nie wirklich deployt, ein Health-Check dagegen würde
                # nur falsche "nicht erreichbar"-Alarme für etwas erzeugen, das nie live war.
                from core.deployment_status import record_deployment
                record_deployment(project_dir, provider=result.provider, url=result.preview_url)
                console.print("💡 [dim]`python main.py --check-deployments` überwacht diese URL künftig automatisch.[/dim]")
        else:
            console.print(f"❌ [bold red]Cloud-Deployment fehlgeschlagen:[/bold red]\n{result.output}", style="red")

    async def _stop_deployment(self, project_name: str | None) -> None:
        """Fährt ein per /deploy gestartetes Deployment wieder herunter."""
        project_dir = self._resolve_project_dir(project_name)
        if project_dir is None:
            if project_name:
                console.print(f"⚠️ Projekt `{project_name}` existiert nicht in `workspace/`.", style="yellow")
            else:
                console.print("⚠️ Kein Projekt angegeben und keines geladen.", style="yellow")
            return

        from core.deployment import stop_deployment

        console.print(f"⏹️ [dim]Stoppe Deployment für `{project_dir}`...[/dim]")
        result = await asyncio.to_thread(stop_deployment, project_dir)

        if not result.attempted:
            console.print(f"⚠️ {result.reason_skipped}", style="yellow")
        elif result.success:
            console.print("⏹️ [bold green]Deployment gestoppt.[/bold green]")
        else:
            console.print(f"❌ Stoppen fehlgeschlagen:\n{result.output}", style="red")

