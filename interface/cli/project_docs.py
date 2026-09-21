"""
interface/cli/project_docs.py - ADRs, Projekt-Checkpoint, Team-Health, Konstitution/Design-System.

Teil der P6-5-Aufteilung von interface/cli.py (ROADMAP_TEMP.md): CLIProjectDocsMixin buendelt
alle read-mostly Projekt-Dokumentations-/Governance-Befehle - Architecture Decision Records,
Checkpoint-Anzeige, Health-Rollup, Roadmap-Vorschlaege, Tech-Stack-/Design-Konstitution und das
Struktur-Hygiene-Audit.
"""

import os
from pathlib import Path

from rich import box
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from interface.cli._shared import console


class CLIProjectDocsMixin:
    def _show_adrs(self, project_name: str | None) -> None:
        """
        Zeigt die Architecture Decision Records (core/adr.py) eines Projekts – alle bisher
        per record_architecture_decision()-Werkzeug (core/agent_toolbox.py, primär vom
        architect-Agenten genutzt) dokumentierten Architektur-Entscheidungen samt
        Begründung, statt dass sie nur einmalig im Antworttext eines Laufs auftauchen.
        """
        project_dir = self._resolve_project_dir(project_name)
        if project_dir is None:
            if project_name:
                console.print(f"⚠️ Projekt `{project_name}` existiert nicht in `workspace/`.", style="yellow")
            else:
                console.print(
                    "⚠️ Kein Projekt angegeben und keines geladen. Nutze `/adr <projekt>` "
                    "oder lade zuerst eines mit `/load <projekt>`.", style="yellow",
                )
            return

        from core.adr import list_adrs

        records = list_adrs(project_dir)
        if not records:
            console.print(f"📭 Noch keine Architecture Decision Records für `{project_dir.name}`.", style="dim")
            return

        table = Table(title=f"📐 Architecture Decision Records – {project_dir.name}", box=box.ROUNDED)
        table.add_column("Nr.", justify="right", style="dim")
        table.add_column("Status", style="cyan")
        table.add_column("Titel")
        table.add_column("Datei", style="dim")
        for r in records:
            table.add_row(f"{r.number:04d}", r.status, r.title, str(r.path.relative_to(project_dir)))
        console.print(table)

    def _show_project_state(self, project_name: str | None) -> None:
        """
        Zeigt den aktuellen State-Checkpoint (PROJECT_STATE.md) eines Projekts an –
        kompakt, inklusive aller Kernkomponenten, letztem Verifikations-Status und nächsten Schritten.
        """
        from core.project_status import generate_project_state_md, read_project_state_md

        project_dir = self._resolve_project_dir(project_name)
        if project_dir is None:
            if project_name:
                console.print(f"⚠️ Projekt `{project_name}` existiert nicht in `workspace/`.", style="yellow")
            else:
                console.print(
                    "⚠️ Kein Projekt angegeben und keines geladen. Nutze `/state <projekt>` "
                    "oder lade zuerst eines mit `/load <projekt>`.",
                    style="yellow",
                )
            return

        state_md = read_project_state_md(str(project_dir))
        if not state_md:
            # Fallback: Live generieren
            state_md = generate_project_state_md(str(project_dir))

        console.print(
            Panel(
                Markdown(state_md),
                title=f"📌 Projekt-Checkpoint: {project_dir.name}",
                border_style="cyan",
                padding=(1, 2),
            )
        )

    def _show_team_health(self) -> None:
        """
        Zeigt einen projektübergreifenden Health-Rollup (core/team_health.py) über ALLE
        Projekte in workspace/ - macht sichtbar, welche Projekte gerade "rot" sind, seit wann,
        und ob mehrere Projekte an DERSELBEN Fehlerkategorie scheitern (z.B. ein gemeinsam
        kaputter Frontend-Baustein). Bisher musste dafür jedes .ai_team_status.json einzeln
        von Hand gelesen werden.
        """
        from config import WORKSPACE_DIR
        from core.team_health import build_team_health_rollup

        rollup = build_team_health_rollup(WORKSPACE_DIR)
        if not rollup.projects:
            console.print(
                "📭 Noch keine Projekte mit protokollierter Lauf-Historie in `workspace/` gefunden.",
                style="dim",
            )
            return

        status_icons = {
            "ok": "✅", "failed": "⚠️", "budget_aborted": "🚫", "cancelled": "⏹️", "unknown": "❔",
        }

        table = Table(title="🩺 Team-Health-Rollup (alle Projekte)", box=box.ROUNDED)
        table.add_column("Status")
        table.add_column("Projekt", style="cyan")
        table.add_column("Seit wann rot", justify="center")
        table.add_column("Kategorie", style="magenta")
        table.add_column("Letzter Lauf", style="dim")
        table.add_column("Kurzfehler", style="dim")

        for p in rollup.projects:
            icon = status_icons.get(p.status, "❔")
            streak = f"{p.red_streak} Lauf/Läufe in Folge" if p.red_streak else "-"
            short_error = (p.failure_detail or "").splitlines()[0][:80] if p.failure_detail else ""
            table.add_row(
                icon, p.name, streak, p.failure_category or "-",
                f"{p.timestamp}\n{p.task_summary}", short_error,
            )

        console.print(table)

        if rollup.shared_patterns:
            lines = ["🔗 [bold]Erkannte gemeinsame Fehlermuster:[/bold]"]
            for category, names in rollup.shared_patterns.items():
                lines.append(f"  • [bold]{category}[/bold]: {len(names)} Projekte betroffen ({', '.join(names)})")
            console.print(Panel("\n".join(lines), border_style="yellow"))
        else:
            console.print("ℹ️ Kein gemeinsames Fehlermuster über mehrere Projekte hinweg erkannt.", style="dim")

    async def _propose_roadmap(self, project_slug: str) -> None:
        """
        Team-Optimierung (KI-Team-Zustandsbericht 2026-09-08, "Product-Owner-Weiterdenken"):
        der product_owner-Agent bearbeitet bisher AUSSCHLIESSLICH die konkret gestellte Aufgabe.
        Lässt ihn hier read-only über ein BEREITS BESTEHENDES Projekt nachdenken und legt seine
        Vorschläge als niedrig priorisierte Backlog-Tickets an (core/roadmap_advisor.py) - KEINE
        automatische Umsetzung, ein Mensch entscheidet, welcher Vorschlag es wert ist.
        """
        from core.roadmap_advisor import propose_next_steps

        console.print(f"🧭 [bold cyan]product_owner denkt über '{project_slug}' nach (read-only)...[/bold cyan]")
        report = await propose_next_steps(self._orchestrator, project_slug)

        if report.error:
            console.print(f"⚠️ [yellow]{report.error}[/yellow]")
            if report.raw_content:
                console.print(Panel(report.raw_content[:1500], title="Rohe Antwort", border_style="dim"))
            return

        lines = [f"{i + 1}. **{p.title}** - {p.rationale}" for i, p in enumerate(report.proposals)]
        console.print(Panel(
            "\n\n".join(lines),
            title=f"🧭 Vorschläge für '{project_slug}' ({len(report.ticket_ids)} als Ticket angelegt)",
            border_style="cyan",
        ))
        console.print(
            "💡 [dim]Diese Tickets werden NICHT automatisch umgesetzt - greenlighte einen "
            "Vorschlag, indem du ihn regulär als Aufgabe stellst.[/dim]"
        )

    def _resolve_constitution_target(self, project_arg: str | None) -> tuple[str | None, str | None]:
        """Gibt (project_dir, error_message) zurück – dieselbe Existenzprüfung wie
        _delete_project_with_confirmation (vor get_project_dir(), das sonst leer anlegen würde)."""
        if project_arg:
            exists = (
                Path(project_arg).exists() if os.path.isabs(project_arg)
                else project_arg in self._workspace.list_projects()
            )
            if not exists:
                return None, f"⚠️ Projekt `{project_arg}` existiert nicht. Nutze `/projekte` zur Übersicht."
            return str(self._workspace.get_project_dir(project_arg)), None
        if self._loaded_project_dir:
            return self._loaded_project_dir, None
        return None, "⚠️ Kein Projekt angegeben und keines geladen. Nutze `/constitution <projekt>` oder lade zuerst eines mit `/load <name>`."

    def _manage_constitution(self, project_arg: str | None) -> None:
        """
        Zeigt und bearbeitet die Projekt-Konstitution (core/project_constitution.py) – feste
        Tech-Stack-Präferenzen (Sprache, Framework, Test-Framework, Code-Stil,
        Deployment-Ziel), die JEDEM künftigen Lauf an diesem Projekt als verbindlicher Kontext
        mitgegeben werden, statt bei jeder Anfrage neu vom Modell geraten zu werden.
        """
        from core.project_constitution import FIELDS, read_constitution, write_constitution

        project_dir, error = self._resolve_constitution_target(project_arg)
        if error:
            console.print(error, style="yellow")
            return

        current = read_constitution(project_dir)
        project_label = Path(project_dir).name

        if current:
            lines = [f"- **{FIELDS[k]}:** {v}" for k, v in current.items() if k in FIELDS]
            console.print(Panel(Markdown("\n".join(lines)), title=f"📜 Projekt-Konstitution: {project_label}", border_style="cyan"))
        else:
            console.print(f"📭 Noch keine Projekt-Konstitution für `{project_label}` festgelegt.", style="dim")

        try:
            should_edit = Confirm.ask("Werte jetzt festlegen/bearbeiten?", default=not bool(current))
        except Exception:
            should_edit = False
        if not should_edit:
            return

        console.print("[dim]Enter = aktuellen Wert behalten, '-' = Feld löschen.[/dim]")
        updated = dict(current)
        for key, label in FIELDS.items():
            try:
                value = Prompt.ask(label, default=current.get(key, ""))
            except Exception:
                break
            if value.strip() == "-":
                updated.pop(key, None)
            elif value.strip():
                updated[key] = value.strip()

        write_constitution(project_dir, updated)
        console.print(f"✅ [bold green]Projekt-Konstitution für `{project_label}` gespeichert.[/bold green]")

    def _resolve_design_system_target(self, project_arg: str | None) -> tuple[str | None, str | None]:
        """Gibt (project_dir, error_message) zurück – dieselbe Existenzprüfung wie
        _resolve_constitution_target, nur mit dem passenden Befehlshinweis in der Fehlermeldung."""
        if project_arg:
            exists = (
                Path(project_arg).exists() if os.path.isabs(project_arg)
                else project_arg in self._workspace.list_projects()
            )
            if not exists:
                return None, f"⚠️ Projekt `{project_arg}` existiert nicht. Nutze `/projekte` zur Übersicht."
            return str(self._workspace.get_project_dir(project_arg)), None
        if self._loaded_project_dir:
            return self._loaded_project_dir, None
        return None, "⚠️ Kein Projekt angegeben und keines geladen. Nutze `/design-system <projekt>` oder lade zuerst eines mit `/load <name>`."

    def _manage_design_system(self, project_arg: str | None) -> None:
        """
        Zeigt und bearbeitet das Projekt-Design-System (core/design_system.py) – feste
        visuelle Präferenzen (Farbpalette, Typografie, Spacing-Skala, Komponenten-
        Namenskonvention, Tonalität), die JEDEM künftigen Lauf an diesem Projekt als
        verbindlicher Kontext mitgegeben werden – das Pendant zu /constitution, nur für
        Design statt Tech-Stack.
        """
        from core.design_system import FIELDS, read_design_system, write_design_system

        project_dir, error = self._resolve_design_system_target(project_arg)
        if error:
            console.print(error, style="yellow")
            return

        current = read_design_system(project_dir)
        project_label = Path(project_dir).name

        if current:
            lines = [f"- **{FIELDS[k]}:** {v}" for k, v in current.items() if k in FIELDS]
            console.print(Panel(Markdown("\n".join(lines)), title=f"🎨 Projekt-Design-System: {project_label}", border_style="magenta"))
        else:
            console.print(f"📭 Noch kein Design-System für `{project_label}` festgelegt.", style="dim")

        try:
            should_edit = Confirm.ask("Werte jetzt festlegen/bearbeiten?", default=not bool(current))
        except Exception:
            should_edit = False
        if not should_edit:
            return

        console.print("[dim]Enter = aktuellen Wert behalten, '-' = Feld löschen.[/dim]")
        updated = dict(current)
        for key, label in FIELDS.items():
            try:
                value = Prompt.ask(label, default=current.get(key, ""))
            except Exception:
                break
            if value.strip() == "-":
                updated.pop(key, None)
            elif value.strip():
                updated[key] = value.strip()

        write_design_system(project_dir, updated)
        console.print(f"✅ [bold green]Design-System für `{project_label}` gespeichert.[/bold green]")

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

