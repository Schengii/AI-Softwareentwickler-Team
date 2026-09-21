"""
interface/cli/task_processing.py - Eine einzelne Nutzeraufgabe entgegennehmen und ausfuehren.

Teil der P6-5-Aufteilung von interface/cli.py (ROADMAP_TEMP.md): CLITaskProcessingMixin deckt
den eigentlichen Ablauf EINER Aufgabe ab - Lauf-Report schreiben, den Plan zur Bestaetigung
anzeigen, den Orchestrator-Lauf mit Live-Statusanzeige starten und das Ergebnis aufbereiten.

`Live`/`Panel`/`ENABLE_PLAN_CONFIRMATION` werden in `_process_task`/`_render_and_confirm_plan`
bewusst PER-AUFRUF ueber `interface.cli` re-importiert statt am Modulkopf - bestehende Tests
patchen sie als `interface.cli.<name>` (siehe Modul-Docstring von scripts/_assemble_cli.py).
"""

import signal
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

from rich.prompt import Confirm

from agents.department_lead_agent import DEPARTMENT_DEFINITIONS
from agents.orchestrator import PHASE_ORDER
from core.backlog_store import new_ticket_id, upsert_ticket
from core.message_bus import AgentTask
from core.task_manager import AVAILABLE_AGENTS
from interface.cli._shared import console

# agent_id -> Fachbereichs-ID (z.B. "backend" -> "dev_lead") - Grundlage fuer die nach
# Fachbereich gruppierte Plan-Vorschau (siehe _render_and_confirm_plan).
_AGENT_TO_DEPARTMENT: dict[str, str] = {
    agent_id: dept_id
    for dept_id, info in DEPARTMENT_DEFINITIONS.items()
    for agent_id in info["members"]
}


class CLITaskProcessingMixin:
    def _write_run_report(self, result: str, ticket_id: str) -> Path:
        """
        Schreibt das vollständige Lauf-Ergebnis (Verifikations-Protokoll, Fehleranalyse etc.)
        in eine temporäre Datei statt es als riesigen Panel-Block ins Terminal zu drucken.

        Realer Fund: bei mehrstufigen Korrekturschleifen (Pre-Flight, Testfixes, Root-Cause-
        Analyse) wurde `result` schnell mehrere hundert Zeilen lang und hat die Konsole bei
        jedem Lauf komplett zugeschrieben - der eigentlich interessante Teil (bestanden/
        gescheitert, Kernfehler) ging darin unter. Die Datei liegt im System-Temp-Verzeichnis,
        damit sie das Repo/den Workspace nicht zumüllt; wer die Details braucht, bekommt nur
        noch den Pfad angezeigt.
        """
        report_dir = Path(tempfile.gettempdir()) / "ki_team_reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = report_dir / f"{timestamp}_{ticket_id}.md"
        report_path.write_text(result, encoding="utf-8")
        return report_path

    async def _process_task(self, user_input: str) -> None:
        """Verarbeitet eine Nutzeraufgabe mit detailliertem Live-Status."""
        status_lines: list[str] = []

        # Sofort im gemeinsamen Backlog sichtbar (core/backlog_store.py), noch bevor eine
        # echte Kurzfassung vorliegt - daher zunächst mit der rohen Nutzereingabe als Titel.
        # _ask_for_git_push() aktualisiert Titel/Status beim Abschluss auf die echte
        # Zusammenfassung bzw. den tatsächlichen Ausgang (review/done/blocked).
        ticket_id = new_ticket_id("cli")
        upsert_ticket(ticket_id=ticket_id, title=user_input[:80], source="cli", status="in_progress")

        from interface.cli import ENABLE_PLAN_CONFIRMATION, Live, Panel
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

            async def confirm_plan(task_summary: str, project_slug: str, agent_tasks: list[AgentTask]) -> bool:
                # Confirm.ask() ist ein blockierender Terminal-Prompt - während die Live-
                # Anzeige aktiv rendert, würde sich das mit deren Auto-Refresh-Thread beißen.
                # live.stop()/live.start() pausiert die Anzeige exakt für die Dauer der Abfrage
                # (dasselbe Muster wie der bereits bestehende Git-Push-Gate, nur DORT läuft die
                # Abfrage bereits außerhalb des Live-Blocks, hier mitten im laufenden Lauf).
                live.stop()
                try:
                    return self._render_and_confirm_plan(task_summary, project_slug, agent_tasks)
                finally:
                    live.start()

            # Strg+C setzt beim ERSTEN Druck nur self._cancel_event (kooperativer Abbruch an
            # denselben Prüfpunkten wie das bestehende MAX_RUN_TOKENS-Budget), statt sofort
            # einen KeyboardInterrupt auszulösen, der den laufenden Werkzeug-Loop/Subprozess
            # mitten in einer Datei-Operation abwürgen könnte. Der Handler MUSS in jedem Fall
            # wiederhergestellt werden (siehe finally), sonst bliebe Strg+C für den Rest der
            # Sitzung verändert.
            original_sigint_handler = self._install_cancel_handler()
            try:
                try:
                    # Nach /load reicht jede folgende Chat-Nachricht das geladene Projektverzeichnis
                    # durch, statt (wie zuvor) einen neuen project_slug erraten und einen neuen
                    # workspace/-Ordner anlegen zu lassen. Vorher hatte _loaded_project_dir nur
                    # Auswirkung auf /rag – die im Hilfetext dokumentierte "So entwickelst du ein
                    # bestehendes Projekt weiter"-Anleitung funktionierte real also nicht.
                    result = await self._orchestrator.process(
                        user_request=user_input,
                        status_callback=on_status,
                        forced_project_dir=self._loaded_project_dir,
                        plan_confirmation_callback=confirm_plan if ENABLE_PLAN_CONFIRMATION else None,
                        cancel_requested=self._cancel_event.is_set,
                    )
                except Exception as e:
                    console.print(
                        f"\n❌ Fehler bei der Verarbeitung: {e}",
                        style="bold red"
                    )
                    # Realer Fund (Backlog-Bestandsaufnahme): mehrere "blocked"-Tickets trugen nur
                    # str(e)[:200] als detail - z.B. bloß "sequence item 0: expected str instance,
                    # NoneType found", OHNE Traceback. Ohne den ist nachträglich nicht mehr
                    # rekonstruierbar, WELCHE Zeile den Fehler auslöste - der Fund war praktisch
                    # unbehebbar, sobald die Sitzung vorbei war. Jetzt wird der volle Traceback
                    # (gedeckelt, wie MAX_FAILURE_DETAIL_CHARS in core/project_status.py) mit
                    # gespeichert, damit ein künftiger Wiederholungsfall tatsächlich diagnostizierbar
                    # bleibt statt erneut nur die nackte Exception-Nachricht zu hinterlassen.
                    tb = traceback.format_exc()[-1000:]
                    upsert_ticket(
                        ticket_id=ticket_id, title=user_input[:80], source="cli",
                        status="blocked", detail=f"{e}\n\n{tb}"[:1200],
                    )
                    return
            finally:
                signal.signal(signal.SIGINT, original_sigint_handler)

        # Gesamtergebnis: volles Verifikations-Protokoll in eine temp. Datei statt in die
        # Konsole - siehe _write_run_report() für den Hintergrund. Im Terminal bleibt nur ein
        # kompakter Hinweis mit Erfolg/Misserfolg und dem Dateipfad für die Detailanalyse.
        report_path = self._write_run_report(result, ticket_id)
        self._last_report_path = str(report_path)
        verification_ok_short = getattr(self._orchestrator, "last_verification_ok", False)
        # Ticket sofort nach dem Lauf finalisieren: endet die Sitzung vor dem Push-Dialog
        # (Abbruch, nicht-interaktiver Aufruf, kein GitHub-Agent), blieb es sonst dauerhaft
        # "in_progress" (Backlog-Analyse 2026-09-15: 10 solcher Tickets). Der Push-Dialog
        # verfeinert den Status anschließend (review/done/blocked).
        run_summary = getattr(self._orchestrator, "last_task_summary", None)
        run_slug = getattr(self._orchestrator, "last_project_slug", None)
        upsert_ticket(
            ticket_id=ticket_id,
            title=(run_summary if isinstance(run_summary, str) and run_summary else user_input)[:80],
            source="cli",
            status="done" if verification_ok_short is True else "blocked",
            detail="" if verification_ok_short is True else f"Verifikation nicht bestanden – Protokoll: {report_path}"[:300],
            project_slug=run_slug if isinstance(run_slug, str) and run_slug else None,
        )
        status_icon = "✅" if verification_ok_short else "⚠️"
        status_text = "verifiziert" if verification_ok_short else "NICHT vollständig verifiziert"
        console.print()
        console.print(
            Panel(
                f"{status_icon} Lauf abgeschlossen – Code {status_text}.\n"
                f"📄 Vollständiges Protokoll (Verifikation, Fehleranalyse): [bold]{report_path}[/bold]",
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
        await self._ask_for_git_push(self._orchestrator.last_task_summary or user_input, ticket_id=ticket_id)

        # Automatischer Obsidian-Gedächtnis-Sync (falls aktiviert)
        try:
            from core.obsidian_sync import auto_sync_if_enabled, record_sync_health_ticket
            obs_res = auto_sync_if_enabled()
            record_sync_health_ticket(obs_res)
            if obs_res and obs_res.synced_files:
                console.print(f"🧠 [dim]Obsidian-Gedächtnis aktualisiert: {', '.join(obs_res.synced_files)}[/dim]")
            elif obs_res and not obs_res.success:
                console.print(f"⚠️ [dim]Obsidian-Sync fehlgeschlagen ({', '.join(obs_res.failed_files)}) - als Ticket vermerkt.[/dim]")
        except Exception as e:
            from core.obsidian_sync import record_sync_health_ticket
            record_sync_health_ticket(None, exception=e)
            console.print(f"⚠️ [dim]Obsidian-Sync fehlgeschlagen: {e}[/dim]")

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

    # Marker, an denen ein task_summary erkennbar noch die rohe, an das Team GERICHTETE
    # Nutzeranfrage ist statt einer Zusammenfassung dessen, was entstanden ist – real
    # beobachtet trotz verschärftem DECOMPOSE_SYSTEM_PROMPT (core/task_manager.py), z.B.
    # "Ich möchte das ihr ein neues Projekt erstellt. Es" als Commit-Betreff. Deterministische
    # Absicherung ohne weiteren LLM-Aufruf – bewusst nur eindeutige Anrede-/Bitte-Formeln,
    # um echte (auch mal umgangssprachlich formulierte) Zusammenfassungen nicht fälschlich
    # zu verwerfen.
    _RAW_REQUEST_PREFIXES = (
        "ich möchte", "ich will", "ich hätte gern", "könnt ihr", "könntest du", "kannst du",
        "bitte ", "okay,", "okay ", "hallo", "hi,", "hi ",
    )

    @classmethod
    def _looks_like_raw_user_request(cls, text: str) -> bool:
        normalized = text.strip().lower()
        return normalized.startswith(cls._RAW_REQUEST_PREFIXES)

    def _render_and_confirm_plan(
        self, task_summary: str, project_slug: str, agent_tasks: list[AgentTask],
    ) -> bool:
        """
        Zeigt den von TaskManager.decompose() erstellten Plan (Zusammenfassung + genau die
        Spezialisten/Teilaufgaben, die gleich wirklich beauftragt würden - keine Schätzung,
        keine Zusammenfassung, der reale Plan) gruppiert nach Fachbereich, und lässt ihn
        bestätigen, BEVOR auch nur ein Agent startet.
        """
        from interface.cli import Panel
        dept_meta = {dept_id: (icon, label) for dept_id, label, icon, _mode in PHASE_ORDER}
        grouped: dict[str, list[AgentTask]] = {}
        for task in agent_tasks:
            grouped.setdefault(_AGENT_TO_DEPARTMENT.get(task.agent_id, "?"), []).append(task)

        lines: list[str] = [f"[dim]Projekt: {project_slug}[/dim]\n"]
        # In derselben Reihenfolge wie die tatsächliche Ausführung (PHASE_ORDER), damit die
        # Vorschau exakt widerspiegelt, was gleich passiert.
        ordered_dept_ids = [d for d, _, _, _ in PHASE_ORDER] + [d for d in grouped if d not in dept_meta]
        for dept_id in ordered_dept_ids:
            tasks = grouped.get(dept_id)
            if not tasks:
                continue
            icon, label = dept_meta.get(dept_id, ("❔", DEPARTMENT_DEFINITIONS.get(dept_id, {}).get("title", dept_id)))
            lines.append(f"{icon} [bold]{label}[/bold]")
            for t in tasks:
                agent_name = AVAILABLE_AGENTS.get(t.agent_id, {}).get("name", t.agent_id)
                desc = t.description if len(t.description) <= 110 else t.description[:107] + "..."
                lines.append(f"  • [cyan]{agent_name}[/cyan]: {desc}")
            lines.append("")

        console.print(
            Panel(
                "\n".join(lines).rstrip(),
                title=f"📋 Geplanter Aufgaben-Umfang: {task_summary}",
                border_style="cyan",
            )
        )
        try:
            return Confirm.ask(
                f"Team mit {len(agent_tasks)} Spezialist(en) aus {len(grouped)} Fachbereich(en) loslassen?",
                default=True,
            )
        except Exception:
            return False

