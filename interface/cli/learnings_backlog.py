"""
interface/cli/learnings_backlog.py - Gelernte Regeln, Selbstoptimierung, Backlog, Ziel-Loop.

Teil der P6-5-Aufteilung von interface/cli.py (ROADMAP_TEMP.md): CLILearningsBacklogMixin
buendelt das persistente Agenten-Gedaechtnis (Learnings, Optimierungsvorschlaege) und das
gemeinsame Backlog (Kanban-Board, manuelle Tickets, autonomer Ziel-Loop).

`BACKLOG_WIP_LIMIT_IN_PROGRESS` wird in `_show_backlog` bewusst PER-AUFRUF ueber `interface.cli`
re-importiert statt am Modulkopf - bestehende Tests patchen ihn als
`interface.cli.BACKLOG_WIP_LIMIT_IN_PROGRESS` (siehe Modul-Docstring von scripts/_assemble_cli.py).
"""

import asyncio
import signal
from pathlib import Path

from rich import box
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from core.backlog_store import STATUSES, count_by_status, is_ticket_ready, list_tickets, new_ticket_id, upsert_ticket
from interface.cli._shared import _PRIORITY_ICONS, _PRIORITY_LABELS, console


class CLILearningsBacklogMixin:
    def _manage_team_lessons(self, args: list[str]) -> None:
        """Team-Lektionen mit Lebenszyklus (core/team_memory.py):
        `/lessons` zeigt die Übersicht, `/lessons link` verknüpft Lektionen mit dem Regelwerk,
        `/lessons <signatur> <open|implemented|verified|archived> [Notiz]` setzt den Status."""
        from core.team_memory import (
            LESSON_STATUSES,
            auto_link_lessons_to_rules,
            format_lesson_board,
            update_lesson_status,
        )

        if not args:
            console.print(Markdown(format_lesson_board()))
            console.print("💡 [dim]`/lessons link` | `/lessons <signatur> <status> [Notiz]`[/dim]")
            return
        if args[0] == "link":
            linked = auto_link_lessons_to_rules()
            console.print(f"🔗 {len(linked)} Lektion(en) mit dem Regelwerk verknüpft.", style="green" if linked else "dim")
            return
        if len(args) < 2 or args[1] not in LESSON_STATUSES:
            console.print(f"⚠️ Aufruf: `/lessons <signatur> <{'|'.join(LESSON_STATUSES)}> [Notiz]`", style="yellow")
            return
        if update_lesson_status(args[0], args[1], " ".join(args[2:])):
            console.print(f"✅ Lektion `{args[0]}` ist jetzt `{args[1]}`.", style="green")
        else:
            console.print(f"⚠️ Keine Lektion mit Signatur `{args[0]}` gefunden (siehe `/lessons`).", style="yellow")

    def _show_learnings(self) -> None:
        """
        Zeigt memory/agent_learnings.json (persistentes Gedächtnis) für ALLE Agenten an -
        bisher eine reine Black Box, die bei JEDEM künftigen Aufruf eines Agenten automatisch
        in dessen System-Prompt einfließt (siehe agent_knowledge_base.get_augmented_prompt),
        ohne dass der Mensch je einsehen konnte, was dort eigentlich gelernt wurde.
        """
        from datetime import UTC, datetime

        from memory.agent_knowledge_base import agent_knowledge_base

        all_learnings = agent_knowledge_base.get_all_learnings()
        if not all_learnings:
            console.print("📭 Noch keine gelernten Regeln vorhanden (memory/agent_learnings.json ist leer).", style="dim")
            return

        # P2-1 (ROADMAP_TEMP.md): Wirksamkeit (violations_after/injections) und Alter statt einer
        # reinen Textliste - vorher war nicht erkennbar, ob eine Regel tatsächlich wirkt.
        table = Table(title="🧠 Gelernte Regeln (persistentes Gedächtnis)", box=box.ROUNDED)
        table.add_column("Agent", style="cyan")
        table.add_column("Nr.", justify="right", style="dim")
        table.add_column("Regel")
        table.add_column("Wirksamkeit", justify="right")
        table.add_column("Alter", justify="right", style="dim")

        for agent_id in sorted(all_learnings):
            for i, detail in enumerate(agent_knowledge_base.get_learning_details(agent_id), start=1):
                effectiveness = detail.get("effectiveness")
                if effectiveness is None:
                    wirksamkeit = f"[dim]— ({detail.get('injections', 0)}/{5})[/dim]"
                else:
                    style = "green" if effectiveness < 0.3 else ("yellow" if effectiveness < 0.7 else "red")
                    wirksamkeit = f"[{style}]{1 - effectiveness:.0%}[/{style}]"
                created_at = detail.get("created_at") or ""
                try:
                    age_days = (datetime.now(UTC) - datetime.fromisoformat(created_at)).days
                    alter = f"{age_days}d"
                except (ValueError, TypeError):
                    alter = "?"
                table.add_row(agent_id, str(i), detail["rule"], wirksamkeit, alter)

        console.print(table)
        console.print(
            "💡 [dim]Eine falsche/überholte Regel entfernen: `/delete-learning <agent> <nr>`[/dim]"
        )

    def _show_optimization_report(self) -> None:
        """
        Zeigt core/optimization_advisor.py auf Abruf an - dieselbe datenbasierte Analyse, die
        auch automatisch am Ende jedes Laufs angehängt wird (nur dort leer, wenn nichts
        Auffälliges gefunden wurde), hier jederzeit ohne einen neuen Lauf abrufbar. Rein
        informativ, ändert nichts an config.py.
        """
        from core.optimization_advisor import analyze, format_report_for_humans

        report = analyze()
        if report.is_empty():
            console.print(
                "📭 Aktuell keine auffälligen Optimierungspotenziale erkannt (zu wenig Historie "
                "oder alle Agenten performen vergleichbar - siehe MIN_SAMPLE_SIZE/MIN_SUCCESS_RATE_GAP "
                "in core/optimization_advisor.py).",
                style="dim",
            )
            return
        console.print(Panel(Markdown(format_report_for_humans(report)), title="🔧 Selbstoptimierungs-Vorschläge", border_style="cyan"))

    def _apply_single_tuning_suggestion(self, agent_id: str | None) -> None:
        """
        Punkt 4 der Team-Retrospektive (2026-09-06): manueller Mittelweg zwischen "Vorschlag
        ignorieren" und dem Alles-oder-nichts-Schalter config.ENABLE_AUTO_MODEL_TUNING. `/optimize`
        zeigt nur an, ändert aber nie config.py; `/apply-tuning <agent>` übernimmt GEZIELT genau
        EINEN der dort angezeigten Modell-Vorschläge nach core/optimization_advisor.py.
        apply_single_suggestion() - wirkt unabhängig vom globalen Flag, weil eine explizite,
        einzelne Bestätigung per Kommando per Definition kein überraschendes automatisches
        Verhalten ist.
        """
        from core.optimization_advisor import analyze, apply_single_suggestion

        if not agent_id:
            console.print(
                "⚠️ Bitte gib eine Agenten-ID an: `/apply-tuning <agent_id>` (siehe `/optimize` "
                "für die aktuell verfügbaren Vorschläge).",
                style="yellow",
            )
            return

        report = analyze()
        if not any(s.agent_id == agent_id for s in report.model_suggestions):
            available = ", ".join(s.agent_id for s in report.model_suggestions) or "keine"
            console.print(
                f"📭 Kein Modell-Vorschlag für '{agent_id}' vorhanden. Verfügbar: {available}.",
                style="dim",
            )
            return

        applied = apply_single_suggestion(report, agent_id)
        if applied is None:
            console.print(f"❌ Konnte den Vorschlag für '{agent_id}' nicht schreiben (siehe Log).", style="red")
            return
        console.print(
            f"✅ [bold green]Übernommen:[/bold green] '{applied.agent_id}' läuft ab dem nächsten Aufruf mit "
            f"'{applied.suggested_model}' ({applied.suggested_success_rate}% Erfolgsquote statt "
            f"{applied.current_success_rate}% mit '{applied.current_model}'). Gespeichert in "
            "memory/auto_tuned_models.json."
        )

    async def _run_goal_loop_command(self, args: list[str]) -> None:
        """
        Startet den autonomen Ziel- und Feedback-Loop (/goal, /autoloop).
        Arbeitet in aufeinanderfolgenden Iterationen weiter, bis das Ziel erreicht
        und die Verifikation (Tests) grün ist.
        """
        from core.goal_loop import GoalLoopRunner

        max_iterations = 5
        goal_parts = []
        if args and args[0].isdigit():
            max_iterations = int(args[0])
            goal_parts = args[1:]
        else:
            goal_parts = args

        goal_text = " ".join(goal_parts).strip()
        if not goal_text:
            if self._loaded_project_dir:
                proj_name = Path(self._loaded_project_dir).name
                goal_text = f"Vervollständige die Entwicklung von {proj_name}, behebe alle offenen Test- und Schnittstellenfehler und stelle sicher, dass alle Tests grün sind."
                console.print(f"🎯 [cyan]Kein separates Ziel angegeben – nutze geladenes Projekt `{proj_name}`:[/cyan]\n  '{goal_text}'\n")
            else:
                console.print(
                    "⚠️ Bitte gib ein Ziel für den autonomen Loop an:\n"
                    "👉 `/goal [max_runden] <Zielbeschreibung>` (z. B. `/goal Baue ein vollständiges Dashboard mit Tests`)",
                    style="yellow"
                )
                return

        runner = GoalLoopRunner(orchestrator=self._orchestrator)
        original_sigint = self._install_cancel_handler()
        try:
            res = await runner.run(
                goal=goal_text,
                project_dir=self._loaded_project_dir,
                max_iterations=max_iterations,
                status_callback=lambda msg: console.print(msg),
                cancel_requested=self._cancel_event.is_set,
            )
        finally:
            signal.signal(signal.SIGINT, original_sigint)

        console.print()
        console.print(
            Panel(
                Markdown(res.format_summary()),
                title="[bold green]🎯 Autonomer Ziel-Loop: Abschlussbericht[/bold green]",
                border_style="green" if res.success else "yellow",
                padding=(1, 2),
            )
        )
        if res.success:
            await self._ask_for_git_push(f"feat: {goal_text[:60]}")

    async def _show_backlog(self) -> None:
        """
        Zeigt memory/backlog.json (core/backlog_store.py) - alle Tickets über CLI, Dashboard
        UND autonome GitHub-Issue-Läufe (core/issue_watcher.py) hinweg, gruppiert nach Spalte.
        Bisher hatte jede dieser drei Trigger-Quellen ihren eigenen, isolierten Fortschritts-
        Begriff - kein einziger Befehl zeigte, woran das Team gerade/zuletzt gearbeitet hat.

        Zieht VOR der Anzeige echte GitHub-Merges nach (core/merge_watcher.py) - ohne den
        wiederkehrenden `--check-issues`-Poll-Zyklus (core/issue_watcher.py) eingerichtet zu
        haben, wäre das sonst die einzige Stelle, an der "review"-Tickets je auf "done"
        gezogen würden. asyncio.to_thread, da der Merge-Check echte, blockierende
        `gh`-Subprozessaufrufe macht.
        """
        from core.merge_watcher import check_merged_tickets
        await asyncio.to_thread(check_merged_tickets)

        from interface.cli import BACKLOG_WIP_LIMIT_IN_PROGRESS
        tickets = list_tickets()
        if not tickets:
            console.print("📭 Noch keine Tickets im Backlog (memory/backlog.json ist leer).", style="dim")
            return

        if BACKLOG_WIP_LIMIT_IN_PROGRESS > 0:
            in_progress_count = count_by_status("in_progress")
            if in_progress_count > BACKLOG_WIP_LIMIT_IN_PROGRESS:
                console.print(
                    f"⚠️ [bold yellow]WIP-Limit überschritten:[/bold yellow] {in_progress_count} Tickets "
                    f"gleichzeitig 'in_progress' (Limit: {BACKLOG_WIP_LIMIT_IN_PROGRESS}) – laufende "
                    "Arbeit erst abschließen, bevor Neues gestartet wird.", style="yellow",
                )

        table = Table(title="🎫 Backlog / Kanban-Board", box=box.ROUNDED)
        table.add_column("Status", style="cyan")
        table.add_column("Prio.", justify="center")
        table.add_column("Schätzung", style="dim")
        table.add_column("Epic", style="magenta")
        table.add_column("Quelle", style="dim")
        table.add_column("Titel")
        table.add_column("Details/Aktualisiert", style="dim")

        for status in STATUSES:
            # Innerhalb einer Spalte nach Priorität sortiert (1=hoch zuerst) - macht sichtbar,
            # woran als Nächstes gearbeitet werden sollte, statt nur chronologisch.
            in_column = sorted((t for t in tickets if t.status == status), key=lambda t: t.priority)
            for ticket in in_column:
                title = ticket.title
                # Sichtbar machen, WARUM ein "todo"-Ticket noch nicht angefasst werden kann,
                # bevor core/backlog_worker.py es eigenständig aufgreift - genau die "niemals
                # stumm überspringen"-Linie wie is_ticket_ready() selbst schon verfolgt.
                if status == "todo" and ticket.depends_on:
                    ready, blocking = is_ticket_ready(ticket, tickets)
                    if not ready:
                        title = f"🔗 {title} [dim](wartet auf: {', '.join(blocking)})[/dim]"
                table.add_row(
                    status, _PRIORITY_ICONS.get(ticket.priority, str(ticket.priority)), ticket.estimate,
                    ticket.epic, ticket.source, title, ticket.detail or ticket.updated_at,
                )

        console.print(table)

    def _add_backlog_ticket(self, title: str, priority_arg: str | None) -> None:
        """
        Legt manuell ein neues, noch nicht begonnenes Ticket im Status "todo" an (Sprint-/
        Kapazitäts-Planung: bisher entstand JEDES Ticket erst, wenn eine Aufgabe bereits lief
        (`_process_task()` legt sofort "in_progress" an) - es gab keine Möglichkeit, mehrere
        geplante Aufgaben VORAB zu priorisieren, bevor das Team sie tatsächlich angeht. Führt
        selbst nichts aus – ein "todo"-Ticket wird erst zu echter Arbeit, wenn du die
        Aufgabe regulär in den Chat schreibst (genau wie core/pr_review_watcher.py bereits
        "todo"-Tickets aus PR-Kommentaren anlegt, ohne sie automatisch abzuarbeiten).
        """
        priority = _PRIORITY_LABELS.get((priority_arg or "").strip().lower(), 2)

        ticket = upsert_ticket(ticket_id=new_ticket_id("cli"), title=title, source="cli", status="todo", priority=priority)
        console.print(f"✅ [bold green]Ticket angelegt:[/bold green] `{ticket.title}` (Priorität: {_PRIORITY_ICONS[priority]}, Status: todo)")

    async def _delete_learning_with_confirmation(self, agent_id: str, index_str: str) -> None:
        """Entfernt eine einzelne gelernte Regel - IRREVERSIBEL, mit Bestätigung analog zu
        /delete-project und dem Git-Push-Gate. Kein Crash bei ungültiger Eingabe (z.B. Buchstaben
        statt einer Nummer, unbekannter Agent) - klare Fehlermeldung statt Traceback."""
        from memory.agent_knowledge_base import agent_knowledge_base

        try:
            index = int(index_str)
        except ValueError:
            console.print(f"⚠️ '{index_str}' ist keine gültige Nummer. Siehe `/learnings` für die richtigen Nummern.", style="yellow")
            return

        rules = agent_knowledge_base.get_learnings(agent_id)
        if not rules or not (1 <= index <= len(rules)):
            console.print(f"⚠️ Keine Regel Nr. {index} für Agent `{agent_id}` gefunden. Siehe `/learnings`.", style="yellow")
            return

        rule_text = rules[index - 1]
        console.print(
            Panel(
                f"[bold red]Diese gelernte Regel wird UNWIDERRUFLICH entfernt:[/bold red]\n\n"
                f"  Agent: `{agent_id}` (Regel Nr. {index})\n"
                f"  Regel: {rule_text}\n",
                title="🧠 Gelernte Regel entfernen: Vorschau",
                border_style="red",
            )
        )
        try:
            should_delete = Confirm.ask(f"Regel Nr. {index} von `{agent_id}` WIRKLICH entfernen?", default=False)
        except Exception:
            should_delete = False

        if not should_delete:
            console.print("↩️ Entfernung abgebrochen – nichts wurde geändert.", style="dim")
            return

        removed = agent_knowledge_base.remove_learning(agent_id, index)
        if removed is not None:
            console.print(f"🗑️ [bold green]Regel entfernt:[/bold green] {removed}")
        else:
            console.print(f"⚠️ Regel Nr. {index} von `{agent_id}` konnte nicht entfernt werden (evtl. zwischenzeitlich geändert).", style="yellow")

