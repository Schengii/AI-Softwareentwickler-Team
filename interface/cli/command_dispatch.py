"""
interface/cli/command_dispatch.py - Der zentrale `/befehl`-Dispatcher.

Teil der P6-5-Aufteilung von interface/cli.py (ROADMAP_TEMP.md): CLICommandDispatchMixin enthaelt
ausschliesslich `_handle_command()` - den einzigen Ort, der einen rohen `/befehl`-String auf die
ueber alle anderen Mixins verteilten Methoden routet (Python-MRO loest `self.<methode>` bei der
zusammengesetzten CLIInterface-Klasse unabhaengig davon auf, in welcher Mixin-Datei sie lebt).
"""

from rich.markdown import Markdown
from rich.panel import Panel

from interface.cli._shared import _PRIORITY_LABELS, HELP_TEXT, console


class CLICommandDispatchMixin:
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

        elif cmd in ("/prune-worktrees", "/worktrees-aufraeumen", "/cleanup-worktrees"):
            self._prune_worktrees()

        elif cmd in ("/learnings", "/gelernt", "/knowledge"):
            self._show_learnings()

        elif cmd in ("/lessons", "/lektionen"):
            self._manage_team_lessons(args)

        elif cmd in ("/optimize", "/optimierung", "/self-optimize"):
            self._show_optimization_report()

        elif cmd in ("/apply-tuning", "/tuning-anwenden"):
            self._apply_single_tuning_suggestion(args[0] if args else None)

        elif cmd in ("/backlog", "/board", "/kanban", "/tickets"):
            await self._show_backlog()

        elif cmd in ("/backlog-add", "/plan"):
            if not args:
                console.print(
                    "⚠️ Bitte gib einen Titel an: `/backlog-add [priorität] <titel>` "
                    "(Priorität optional als erstes Wort: 1/hoch, 2/mittel, 3/niedrig)",
                    style="yellow",
                )
                return False
            # Priorität nur erkannt, wenn sie als ERSTES Wort steht UND noch ein Titel übrig
            # bleibt - sonst würde ein Titel, der zufällig mit "hoch"/"1" beginnt, falsch
            # als Prioritäts-Flag statt als Text interpretiert.
            if args[0].lower() in _PRIORITY_LABELS and len(args) > 1:
                priority_arg, title = args[0], " ".join(args[1:])
            else:
                priority_arg, title = None, " ".join(args)
            self._add_backlog_ticket(title, priority_arg)

        elif cmd in ("/adr", "/adrs", "/entscheidungen"):
            self._show_adrs(args[0] if args else None)

        elif cmd in ("/delete-learning", "/forget", "/vergessen"):
            if len(args) < 2:
                console.print("⚠️ Bitte gib Agent und Nummer an: `/delete-learning <agent> <nr>` (siehe `/learnings`)", style="yellow")
                return False
            await self._delete_learning_with_confirmation(args[0], args[1])

        elif cmd in ("/constitution", "/konstitution", "/techstack"):
            self._manage_constitution(args[0] if args else None)

        elif cmd in ("/design-system", "/designsystem"):
            self._manage_design_system(args[0] if args else None)

        elif cmd in ("/push", "/git"):
            await self._ask_for_git_push("manuelles Update")

        elif cmd in ("/release", "/tag"):
            await self._create_release_with_confirmation()

        elif cmd in ("/rollback", "/revert"):
            if not args:
                console.print("⚠️ Bitte gib die PR-Nummer an: `/rollback <PR-Nummer>`", style="yellow")
                return False
            await self._rollback_merged_pr(args[0])

        elif cmd in ("/run-tests", "/test"):
            proj_name = args[0] if args else "jobsuche-app"
            self._run_tests(proj_name)

        elif cmd in ("/deploy", "/rollout"):
            await self._deploy_project_with_confirmation(args[0] if args else None)

        elif cmd in ("/deploy-stop", "/undeploy"):
            await self._stop_deployment(args[0] if args else None)

        elif cmd in ("/deploy-cloud", "/cloud-deploy"):
            await self._deploy_cloud_with_confirmation(args)

        elif cmd in ("/protect-branch", "/branch-protection"):
            await self._protect_branch_with_confirmation(args[0] if args else None)

        elif cmd in ("/state", "/checkpoint", "/status-projekt", "/status"):
            self._show_project_state(args[0] if args else None)

        elif cmd in ("/goal", "/autoloop", "/ziel", "/loop"):
            await self._run_goal_loop_command(args)

        elif cmd in ("/team-health", "/teamgesundheit", "/rollup"):
            self._show_team_health()

        elif cmd in ("/propose-roadmap", "/roadmap-vorschlagen", "/naechster-schritt"):
            if not args:
                console.print("⚠️ Bitte gib das Projekt an: `/propose-roadmap <projekt>`", style="yellow")
                return False
            await self._propose_roadmap(args[0])

        elif cmd in ("/sync-obsidian", "/obsidian-sync", "/obsidian"):
            from core.obsidian_sync import sync_project_to_obsidian
            force = "--force" in args
            console.print("🔄 [bold cyan]Synchronisiere Projektdateien in den Obsidian-Vault...[/bold cyan]")
            res = sync_project_to_obsidian(force=force)
            console.print(Panel(Markdown(res.format_summary()), title="🧠 Obsidian-Sync", border_style="cyan" if res.success else "red"))


        elif cmd in ("/load", "/laden", "/open", "/oeffnen", "/import"):
            if not args:
                console.print("⚠️ Bitte gib den Pfad oder Namen des Projekts an:\n👉 `/load <pfad_oder_name> [aufgabe]`", style="yellow")
                return False
            # Kombinierter `/load <projekt> [aufgabe]`-Modus (echter Fund: `/load opspilot Baue
            # das Dashboard` interpretierte bisher den GESAMTEN Rest inkl. der Aufgabenbeschreibung
            # als Pfad -> unter Windows ein WinError 3 (Path too long / Invalid Path), weil aus
            # Wörtern wie "Baue" und "Dashboard" ein einziger, nie existierender Pfad zusammen-
            # gebaut wurde. Nur args[0] ist der Projektname/-pfad; alles danach (args[1:]) ist eine
            # sofort im Anschluss ans Team übergebene Folgeaufgabe.
            target_path = args[0]
            follow_up_task = " ".join(args[1:]).strip()
            ctx = self._workspace.read_existing_project_context(target_path)
            if ctx:
                self._loaded_project_dir = str(self._workspace.get_project_dir(target_path))
                self._orchestrator._history.add_user_message(f"Hier ist der bestehende Projektcode, den wir analysieren/erweitern:\n\n{ctx}")
                console.print(f"✅ [bold green]Projekt erfolgreich geladen:[/bold green] `{target_path}` ({len(ctx)} Zeichen analysiert).")

                # Checkpoint-Vorschau anzeigen, falls vorhanden (spart Tokens und gibt sofort Überblick)
                from core.project_status import read_project_state_md
                state_preview = read_project_state_md(self._loaded_project_dir)
                if state_preview:
                    console.print("📌 [dim]Aktueller Projekt-Checkpoint gefunden (Details mit `/state`):[/dim]")
                    # Zeige erste 5 Zeilen des Checkpoints als Vorschau
                    preview_lines = [line for line in state_preview.splitlines() if line.strip()][:5]
                    console.print(Panel("\n".join(preview_lines), title="📌 Checkpoint-Zusammenfassung", border_style="dim cyan"))

                if follow_up_task:
                    console.print(f"🚀 [bold cyan]Übergebe Folgeaufgabe an das Team:[/bold cyan] {follow_up_task}")
                    await self._process_task(follow_up_task)
                else:
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

        elif cmd in ("/modelle", "/models", "/check-models", "/preflight"):
            # Manueller Re-Check derselben Prüfung, die beim Sitzungsstart automatisch läuft
            # (siehe _run_startup_model_preflight) - z.B. sinnvoll nach einer Quota-Reset-
            # Wartezeit oder wenn ein neuer API-Key eingetragen wurde, ohne die CLI neu zu
            # starten. interactive_confirm=False: hier keine Ja/Nein-Rückfrage, der Nutzer hat
            # den Befehl bewusst selbst ausgelöst und liest den Bericht ohnehin gleich mit.
            await self._run_startup_model_preflight(interactive_confirm=False)

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

