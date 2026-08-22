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
import signal
import sys
import threading
from pathlib import Path

from rich import box
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from agents.department_lead_agent import DEPARTMENT_DEFINITIONS
from agents.orchestrator import PHASE_ORDER, Orchestrator
from config import (
    BRANCH_PROTECTION_REQUIRED_REVIEWS,
    ENABLE_PLAN_CONFIRMATION,
    ENABLE_PR_WORKFLOW,
    GIT_PROTECTED_BRANCHES,
    validate_config,
)
from core.backlog_store import STATUSES, list_tickets, new_ticket_id, upsert_ticket
from core.code_sandbox import CodeSandbox
from core.message_bus import AgentTask
from core.notifier import notify_external
from core.task_manager import AVAILABLE_AGENTS

console = Console()

# agent_id -> Fachbereichs-ID (z.B. "backend" -> "dev_lead"), einmalig aus
# DEPARTMENT_DEFINITIONS abgeleitet - Grundlage für die nach Fachbereich gruppierte
# Plan-Vorschau (siehe _render_and_confirm_plan).
_AGENT_TO_DEPARTMENT: dict[str, str] = {
    agent_id: dept_id
    for dept_id, info in DEPARTMENT_DEFINITIONS.items()
    for agent_id in info["members"]
}

BANNER = """
╔══════════════════════════════════════════════════════════════╗
║        🤖  KI-Softwareentwickler-Team (v4.3)  🤖            ║
║        ─────────────────────────────────────                 ║
║  Dein 33-köpfiges autonomes KI-Entwickler-Team               ║
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
| `/learnings` | Zeigt alle von den Agenten gelernten Regeln (persistentes Gedächtnis) mit Nummer je Agent an |
| `/delete-learning <agent> <nr>` | Entfernt eine einzelne, falsche/überholte gelernte Regel (mit Bestätigung) |
| `/constitution [projekt]` | Zeigt/bearbeitet feste Tech-Stack-Präferenzen (Sprache, Framework, Code-Stil, …) für ein Projekt – gilt für jeden künftigen Lauf daran |
| `/backlog` | Zeigt das Kanban-Board (Todo/In Bearbeitung/Review/Blockiert/Fertig) über CLI, Dashboard UND autonome Issue-Läufe hinweg |
| `/adr [projekt]` | Zeigt die dokumentierten Architecture Decision Records (Begründungen echter Architektur-Entscheidungen) eines Projekts |
| `/deploy [projekt]` | Deployt ein Projekt lokal per Docker (Compose bevorzugt, sonst Dockerfile) – mit Vorschau & Bestätigung |
| `/deploy-stop [projekt]` | Fährt ein per `/deploy` gestartetes Deployment wieder herunter |
| `/push` | Führt manuell einen Git-Commit & Push aus |
| `/protect-branch [branch]` | Aktiviert echte GitHub-Branch-Protection (Pflicht-Reviews, kein Force-Push) für den Hauptbranch – mit Vorschau & Bestätigung |
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
        # Gesetzt/geleert bei jedem Lauf (siehe _process_task) - Grundlage für den
        # kooperativen Strg+C-Abbruch (Orchestrator.process(cancel_requested=...)).
        self._cancel_event = threading.Event()

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

            # Aufgabe an das Team übergeben. _process_task() fängt ein ERSTES Strg+C
            # kooperativ ab (siehe _install_cancel_handler) - dieser äußere Block bleibt als
            # Sicherheitsventil für ein ERZWUNGENES ZWEITES Strg+C während desselben Laufs
            # (der Nutzer will wirklich sofort raus): sauberer Rücksprung zum Prompt statt
            # eines rohen Tracebacks/Programmabsturzes.
            try:
                await self._process_task(user_input)
            except KeyboardInterrupt:
                console.print("\n⏹️ [bold red]Lauf hart abgebrochen.[/bold red]", style="red")

    def _install_cancel_handler(self):
        """
        Installiert für die Dauer EINES Laufs einen eigenen SIGINT-Handler und gibt den
        vorherigen zurück (MUSS vom Aufrufer wiederhergestellt werden, siehe _process_task).

        Strg+C setzt beim ERSTEN Druck nur self._cancel_event (kooperativer Abbruch – siehe
        Orchestrator.process(cancel_requested=...), das dieselben Prüfpunkte wie das
        bestehende MAX_RUN_TOKENS-Budget nutzt), statt sofort einen KeyboardInterrupt
        auszulösen, der den laufenden Werkzeug-Loop/Subprozess (z. B. mitten in einem
        write_file oder einer laufenden npm-Installation) abrupt abwürgen könnte. Ein
        ZWEITES Strg+C während desselben, bereits abbrechenden Laufs ruft bewusst den
        ursprünglichen Handler auf – ein Sicherheitsventil für einen wirklich hängenden Lauf,
        der auf den ersten kooperativen Versuch nicht reagiert.

        Bekannte Grenze: ein bereits per asyncio.to_thread() gestarteter Subprozess (pip/npm
        install, Testlauf) lässt sich dadurch nicht sofort beenden – er läuft im Hintergrund
        zu Ende, während der sichtbare Lauf bereits als abgebrochen gilt. Dasselbe gilt
        grundsätzlich für jedes Python-CLI-Tool, das Subprozesse startet.
        """
        self._cancel_event.clear()
        original_handler = signal.getsignal(signal.SIGINT)

        def handler(signum, frame):
            if self._cancel_event.is_set():
                # original_handler ist normalerweise signal.default_int_handler (Python
                # installiert den standardmäßig) - defensiv trotzdem gegen SIG_DFL/SIG_IGN
                # (nicht aufrufbar) abgesichert, statt dort selbst mit TypeError zu crashen.
                if callable(original_handler):
                    original_handler(signum, frame)
                else:
                    raise KeyboardInterrupt()
                return
            self._cancel_event.set()
            console.print(
                "\n⏹️ [bold yellow]Abbruch angefordert[/bold yellow] – Team beendet die laufende "
                "Phase und liefert den bisherigen Stand aus (nochmal Strg+C für Sofort-Abbruch)...",
                style="yellow",
            )

        signal.signal(signal.SIGINT, handler)
        return original_handler

    async def _process_task(self, user_input: str) -> None:
        """Verarbeitet eine Nutzeraufgabe mit detailliertem Live-Status."""
        status_lines: list[str] = []

        # Sofort im gemeinsamen Backlog sichtbar (core/backlog_store.py), noch bevor eine
        # echte Kurzfassung vorliegt - daher zunächst mit der rohen Nutzereingabe als Titel.
        # _ask_for_git_push() aktualisiert Titel/Status beim Abschluss auf die echte
        # Zusammenfassung bzw. den tatsächlichen Ausgang (review/done/blocked).
        ticket_id = new_ticket_id("cli")
        upsert_ticket(ticket_id=ticket_id, title=user_input[:80], source="cli", status="in_progress")

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
                    upsert_ticket(
                        ticket_id=ticket_id, title=user_input[:80], source="cli",
                        status="blocked", detail=str(e)[:200],
                    )
                    return
            finally:
                signal.signal(signal.SIGINT, original_sigint_handler)

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
        await self._ask_for_git_push(self._orchestrator.last_task_summary or user_input, ticket_id=ticket_id)

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

    async def _ask_for_git_push(self, task_summary: str, ticket_id: str | None = None) -> None:
        """
        Fragt den Nutzer, ob der GitHub-Agent Änderungen committen und pushen soll.

        Zeigt VOR der Bestätigung die konkret betroffenen Dateien, den Diff-Umfang und die
        exakte Commit-Message – nicht nur ein blindes Ja/Nein. Das ist wichtig, weil
        github_agent.commit() intern `git add -A` ausführt und damit den GESAMTEN
        Repo-Stand staged, nicht nur die Dateien des gerade bearbeiteten Projekts – der
        Nutzer soll das vor einer irreversiblen Aktion (Push) wirklich sehen können.

        `ticket_id`: das im gemeinsamen Backlog (core/backlog_store.py) bereits als
        "in_progress" angelegte Ticket dieses Laufs (siehe _process_task()) – wird hier auf
        den tatsächlichen Ausgang finalisiert (review/done/blocked). Ohne Angabe (der
        manuelle `/push`-Befehl hat keinen vorherigen Lauf-Ticket) wird eins neu angelegt.
        """
        ticket_id = ticket_id or new_ticket_id("cli")

        github_agent = self._orchestrator._agents.get("github")
        if not github_agent:
            return

        diff_status = github_agent.get_status()
        if not diff_status:
            # Nichts zu committen - aus Sicht des Backlogs ist die Arbeit trotzdem
            # abgeschlossen (kein Push-Schritt für diese Aufgabe nötig).
            upsert_ticket(ticket_id=ticket_id, title=task_summary[:80], source="cli", status="done")
            return

        changed_files = [line.strip() for line in diff_status.splitlines() if line.strip()]
        diff_stat = github_agent.get_diff()

        # Realer Fund: commit()/push() prüften den Inhalt nie – ein Agent, der versehentlich
        # einen echten API-Key/ein Passwort in eine generierte Datei schreibt, hätte diesen
        # Secret unbemerkt auf GitHub gepusht. scan_for_secrets() staged (git add -A, dasselbe
        # tut commit() ohnehin gleich danach) und durchsucht den vollen Diff regelbasiert
        # (core/secret_scanner.py) – rein lesend, blockiert hier noch nichts selbst.
        secret_findings = github_agent.scan_for_secrets()
        secret_note = ""
        if secret_findings:
            finding_lines = "\n".join(
                f"  {f.file_path}:{f.line_number} [{f.rule}] {f.snippet}"
                for f in secret_findings[:10]
            )
            if len(secret_findings) > 10:
                finding_lines += f"\n  … und {len(secret_findings) - 10} weitere Funde"
            secret_note = (
                f"\n\n[bold red]🔑 Möglicher Secret-Fund ({len(secret_findings)}):[/bold red]\n"
                f"{finding_lines}\n"
                "[dim]Vor dem Pushen prüfen – ein erfolgter Push entfernt diese Werte NICHT "
                "mehr rückwirkend aus der Historie.[/dim]"
            )

        if self._looks_like_raw_user_request(task_summary):
            # task_summary ist erkennbar keine Zusammenfassung, sondern die an das Team
            # gerichtete Anfrage selbst – der (immer kurze, bereits sanitierte) Projektordner-
            # name ist hier ein zuverlässigerer Commit-Betreff als ein weiteres hartes [:50].
            fallback_slug = getattr(self._orchestrator, "last_project_slug", "") or "projekt"
            commit_msg = f"feat: {fallback_slug} weiterentwickelt via AI Developer Team"
        else:
            commit_msg = f"feat: implement {self._truncate_at_word(task_summary, 50)} via AI Developer Team"

        # PR-Workflow statt Direct-Push: Ein echtes Team committet nicht direkt auf den
        # Hauptbranch. AKTIV, wenn der aktuelle Branch tatsächlich ein Hauptbranch ist ODER
        # noch ein "feat/"-Branch aus einem VORHERIGEN PR-Workflow-Lauf ist (das
        # Arbeitsverzeichnis wechselt nach einem Lauf bewusst NICHT mehr zurück, siehe unten
        # - ein "feat/"-Branch ist damit fast immer unser eigener Leftover-Zustand, kein
        # bewusst vom Menschen ausgecheckter Feature-Branch, den es zu respektieren gälte).
        # Schon auf einem ANDEREN, nicht-protected Branch (z.B. ein isolierter
        # Selbstverbesserungs-Worktree mit "ai-team/"-Präfix, oder ein manuell vom Menschen
        # ausgecheckter Branch) -> ganz normal direkt darauf committen/pushen. Zusätzlich muss
        # die `gh`-CLI installiert + eingeloggt sein (gh_ready()) - sonst Graceful Degradation
        # auf den bisherigen Direct-Push, statt den Nutzer ganz zu blockieren.
        original_branch = github_agent.get_current_branch()
        is_leftover_feature_branch = original_branch.startswith("feat/") and original_branch not in GIT_PROTECTED_BRANCHES
        use_pr_workflow = (
            ENABLE_PR_WORKFLOW
            and (original_branch in GIT_PROTECTED_BRANCHES or is_leftover_feature_branch)
            and github_agent.gh_ready()
        )
        # Der eigentliche Ziel-/Basis-Branch für PR und neuen Feature-Branch – bei einem
        # Leftover-"feat/"-Branch NICHT original_branch selbst (der ist ja gerade das Problem),
        # sondern der erste konfigurierte Hauptbranch.
        base_branch = original_branch if original_branch in GIT_PROTECTED_BRANCHES else (GIT_PROTECTED_BRANCHES[0] if GIT_PROTECTED_BRANCHES else "main")
        feature_branch = github_agent.build_feature_branch_name(task_summary) if use_pr_workflow else None
        branch_note = (
            f"\n\n[bold cyan]🔀 PR-Workflow:[/bold cyan] Feature-Branch `{feature_branch}` wird "
            f"angelegt, gepusht und als Pull Request gegen `{base_branch}` geöffnet - "
            f"KEIN Direct-Commit auf `{base_branch}`."
            if use_pr_workflow else ""
        )

        # Realer Fund: JEDER Lauf endete bisher mit demselben "✅ Fertig!", egal ob die echte
        # Testsuite tatsächlich bestanden hatte, nie gefunden wurde, oder nach Fixversuchen
        # weiter fehlschlug – wer nur die letzte Statuszeile sah, hielt ungeprüften Code für
        # verifiziert. last_verification_ok (Orchestrator._run_verification_loop) macht den
        # Unterschied jetzt genau HIER sichtbar, wo eine irreversible Aktion (Push) ansteht.
        verification_ok = getattr(self._orchestrator, "last_verification_ok", False)
        verification_note = (
            "\n\n[bold yellow]⚠️ Nicht verifiziert:[/bold yellow] Die echte Testsuite hat diesen "
            "Code NICHT bestätigt bestanden (siehe Verifikations-Protokoll im Ergebnis oben)."
            if not verification_ok else ""
        )

        console.print(
            Panel(
                (
                    f"[bold]{len(changed_files)} Datei(en) betroffen[/bold] "
                    f"(git add -A staged den GESAMTEN Repo-Stand, nicht nur dieses Projekt):\n\n"
                    + "\n".join(f"  {f}" for f in changed_files[:25])
                    + (f"\n  … und {len(changed_files) - 25} weitere" if len(changed_files) > 25 else "")
                    + (f"\n\n[dim]{diff_stat}[/dim]" if diff_stat else "")
                    + f"\n\n[bold]Geplante Commit-Message:[/bold]\n  {commit_msg}"
                    + branch_note
                    + verification_note
                    + secret_note
                ),
                title="🔀 GitHub-Agent: Vorschau vor Commit & Push",
                border_style="red" if secret_findings else ("cyan" if verification_ok else "yellow"),
            )
        )
        try:
            if secret_findings:
                prompt = "🔑 Trotz möglicher Secret-Funde (siehe oben) wirklich committen und pushen?"
            elif verification_ok:
                prompt = "Möchtest du, dass ich GENAU DIESE Änderungen committe und auf GitHub pushe?"
            else:
                prompt = "Trotz NICHT bestandener/fehlender Verifikation committen und pushen?"
            should_push = Confirm.ask(prompt, default=False)
        except Exception:
            should_push = False

        if not should_push:
            console.print("↩️ Push übersprungen – nichts wurde committet oder gepusht.", style="dim")
            upsert_ticket(ticket_id=ticket_id, title=task_summary[:80], source="cli", status="done")
            return

        if use_pr_workflow:
            success_b, out_b = github_agent.create_branch(feature_branch, base=base_branch)
            if not success_b:
                console.print(
                    f"⚠️ Feature-Branch `{feature_branch}` konnte nicht angelegt werden ({out_b}) "
                    "– falle auf Direct-Push zurück.", style="yellow",
                )
                use_pr_workflow = False

        # Ticket-Endstatus wird unten je nach tatsächlichem Ausgang gesetzt (statt an jedem
        # Rückgabepunkt einzeln) - EIN upsert_ticket()-Aufruf am Ende deckt alle Pfade ab.
        ticket_status, ticket_detail = "blocked", ""

        success_c, out_c = github_agent.commit(commit_msg)
        if success_c:
            console.print(f"✅ [green]Commit erfolgreich:[/green] {commit_msg}")
            success_p, out_p = github_agent.push(branch=feature_branch if use_pr_workflow else None)
            if success_p:
                if use_pr_workflow:
                    console.print(f"🚀 [bold green]Feature-Branch `{feature_branch}` gepusht.[/bold green]")
                    success_pr, pr_out = github_agent.create_pull_request(
                        title=commit_msg,
                        body=f"Automatisch erstellt vom KI-Softwareentwickler-Team.\n\nAufgabe: {task_summary}",
                        base=base_branch, head=feature_branch,
                    )
                    if success_pr:
                        pr_url = pr_out.splitlines()[-1] if pr_out else pr_out
                        console.print(f"🔀 [bold green]Pull Request erstellt:[/bold green] {pr_url}")
                        ticket_status, ticket_detail = "review", pr_url
                    else:
                        console.print(
                            f"⚠️ PR-Erstellung fehlgeschlagen ({pr_out}) – Branch ist trotzdem "
                            "gepusht, PR ggf. manuell auf GitHub anlegen.", style="yellow",
                        )
                        ticket_detail = pr_out
                else:
                    console.print("🚀 [bold green]Änderungen erfolgreich auf GitHub gepusht![/bold green]")
                    ticket_status = "done"
                # Realer Fund: das CI-Ergebnis wurde bisher nur angezeigt, nie ausgewertet - ein
                # eröffneter PR/Direct-Push blieb im Backlog auf "review"/"done" stehen, selbst
                # wenn die echte CI-Pipeline danach tatsächlich rot wurde. Rote CI zieht den
                # Ticket-Status jetzt auf "blocked" (braucht menschliche Aufmerksamkeit), bevor
                # jemand versehentlich einen kaputten PR mergt. "passed"/"timeout"/"no_run"
                # ändern nichts am bisherigen Verhalten.
                ci_status, ci_detail = await self._report_ci_status(github_agent)
                if ci_status == "failed":
                    ticket_status = "blocked"
                    ticket_detail = f"{ticket_detail} | CI fehlgeschlagen: {ci_detail}" if ticket_detail else f"CI fehlgeschlagen: {ci_detail}"
            else:
                console.print(f"⚠️ Push nicht abgeschlossen: {out_p}", style="yellow")
                ticket_detail = out_p
        else:
            console.print(f"⚠️ Commit nicht möglich: {out_c}", style="yellow")
            ticket_detail = out_c

        upsert_ticket(
            ticket_id=ticket_id, title=task_summary[:80], source="cli",
            status=ticket_status, detail=ticket_detail[:300],
        )

        # Bewusst KEIN Zurückwechseln zum Hauptbranch mehr (realer Fund: ein `git checkout`
        # weg vom Feature-Branch entfernt jede Datei, die NUR auf diesem Branch committet
        # ist, aus dem Arbeitsverzeichnis - das gerade erst generierte Projekt wäre bis zum
        # PR-Merge lokal komplett verschwunden, `/load`/erneute Läufe am selben Projekt hätten
        # es fälschlich als neu angelegt). Das Arbeitsverzeichnis bleibt stattdessen auf dem
        # Feature-Branch stehen - die obige is_leftover_feature_branch-Erkennung sorgt dafür,
        # dass der NÄCHSTE Lauf trotzdem korrekt (wieder über den PR-Workflow, von base_branch
        # abgezweigt) einen neuen Feature-Branch anlegt statt fälschlich direkt auf diesen
        # Leftover-Branch zu committen.

    async def _report_ci_status(self, github_agent) -> tuple[str, str]:
        """
        Wartet auf die echte CI-Pipeline (.github/workflows/ci.yml, läuft bei jedem Push) und
        meldet das tatsächliche Ergebnis – realer Fund: push() war bisher "fire and forget",
        ob CI tatsächlich grün wurde, hat das Team nie erfahren. Ein `no_run`-Ergebnis (kein
        `gh` verfügbar, kein GitHub-Remote, ...) ist dabei kein Fehler, nur nicht prüfbar.

        Gibt (status, detail) zurück – zweiter realer Fund: das Ergebnis wurde bisher nur
        angezeigt, nie ausgewertet. _ask_for_git_push() nutzt es jetzt, um den Backlog-Ticket-
        Status bei roter CI auf "blocked" zu ziehen, statt bei "review"/"done" stehen zu bleiben.
        """
        branch = github_agent.get_current_branch()
        console.print(f"🔄 [dim]Warte auf CI-Status für `{branch}` (max. 90s)...[/dim]")
        status, detail = await github_agent.wait_for_ci_status(branch)
        if status == "passed":
            console.print(f"✅ [bold green]CI grün:[/bold green] {detail}")
        elif status == "failed":
            console.print(f"❌ [bold red]CI fehlgeschlagen:[/bold red] {detail}", style="red")
            await asyncio.to_thread(notify_external, "CI fehlgeschlagen", f"Branch `{branch}`: {detail}")
        elif status == "timeout":
            console.print(f"⏳ [yellow]{detail}[/yellow] – prüfe den Status später manuell.")
        else:  # "no_run"
            console.print(f"ℹ️ [dim]CI-Status nicht prüfbar: {detail}[/dim]")
        return status, detail

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

    def _show_learnings(self) -> None:
        """
        Zeigt memory/agent_learnings.json (persistentes Gedächtnis) für ALLE Agenten an -
        bisher eine reine Black Box, die bei JEDEM künftigen Aufruf eines Agenten automatisch
        in dessen System-Prompt einfließt (siehe agent_knowledge_base.get_augmented_prompt),
        ohne dass der Mensch je einsehen konnte, was dort eigentlich gelernt wurde.
        """
        from memory.agent_knowledge_base import agent_knowledge_base

        all_learnings = agent_knowledge_base.get_all_learnings()
        if not all_learnings:
            console.print("📭 Noch keine gelernten Regeln vorhanden (memory/agent_learnings.json ist leer).", style="dim")
            return

        table = Table(title="🧠 Gelernte Regeln (persistentes Gedächtnis)", box=box.ROUNDED)
        table.add_column("Agent", style="cyan")
        table.add_column("Nr.", justify="right", style="dim")
        table.add_column("Regel")

        for agent_id in sorted(all_learnings):
            for i, rule in enumerate(all_learnings[agent_id], start=1):
                table.add_row(agent_id, str(i), rule)

        console.print(table)
        console.print(
            "💡 [dim]Eine falsche/überholte Regel entfernen: `/delete-learning <agent> <nr>`[/dim]"
        )

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

        tickets = list_tickets()
        if not tickets:
            console.print("📭 Noch keine Tickets im Backlog (memory/backlog.json ist leer).", style="dim")
            return

        table = Table(title="🎫 Backlog / Kanban-Board", box=box.ROUNDED)
        table.add_column("Status", style="cyan")
        table.add_column("Quelle", style="dim")
        table.add_column("Titel")
        table.add_column("Details/Aktualisiert", style="dim")

        for status in STATUSES:
            for ticket in [t for t in tickets if t.status == status]:
                table.add_row(status, ticket.source, ticket.title, ticket.detail or ticket.updated_at)

        console.print(table)

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

        elif cmd in ("/learnings", "/gelernt", "/knowledge"):
            self._show_learnings()

        elif cmd in ("/backlog", "/board", "/kanban", "/tickets"):
            await self._show_backlog()

        elif cmd in ("/adr", "/adrs", "/entscheidungen"):
            self._show_adrs(args[0] if args else None)

        elif cmd in ("/delete-learning", "/forget", "/vergessen"):
            if len(args) < 2:
                console.print("⚠️ Bitte gib Agent und Nummer an: `/delete-learning <agent> <nr>` (siehe `/learnings`)", style="yellow")
                return False
            await self._delete_learning_with_confirmation(args[0], args[1])

        elif cmd in ("/constitution", "/konstitution", "/techstack"):
            self._manage_constitution(args[0] if args else None)

        elif cmd in ("/push", "/git"):
            await self._ask_for_git_push("manuelles Update")

        elif cmd in ("/run-tests", "/test"):
            proj_name = args[0] if args else "jobsuche-app"
            self._run_tests(proj_name)

        elif cmd in ("/deploy", "/rollout"):
            await self._deploy_project_with_confirmation(args[0] if args else None)

        elif cmd in ("/deploy-stop", "/undeploy"):
            await self._stop_deployment(args[0] if args else None)

        elif cmd in ("/protect-branch", "/branch-protection"):
            await self._protect_branch_with_confirmation(args[0] if args else None)

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

    async def _protect_branch_with_confirmation(self, branch: str | None) -> None:
        """
        Aktiviert echte GitHub-Branch-Protection (agents/github_agent.py.set_branch_protection())
        für `branch` (Standard: der erste konfigurierte GIT_PROTECTED_BRANCHES-Eintrag, i.d.R.
        "main") – mit Vorschau + Bestätigung, analog zu /deploy: eine Änderung an den
        Repo-Einstellungen selbst über die GitHub-API ist ein bewusster, schwer beiläufig
        rückgängig zu machender Schritt, verdient dieselbe Bestätigungs-Gate-Philosophie statt
        stillschweigend loszulaufen. Realer struktureller Fund: der PR-Workflow verhindert nur,
        dass DIESES Tool direkt auf den Hauptbranch pusht – ohne dieses Kommando könnte ein
        Mensch (oder ein anderes Tool) weiterhin `git push origin main` direkt ausführen.
        """
        target_branch = branch or (GIT_PROTECTED_BRANCHES[0] if GIT_PROTECTED_BRANCHES else "main")
        github_agent = self._orchestrator._agents.get("github")
        if github_agent is None or not github_agent.gh_ready():
            console.print(
                "⚠️ `gh`-CLI nicht installiert/nicht eingeloggt – Branch-Protection kann nicht "
                "gesetzt werden. Prüfe `gh auth status`.", style="yellow",
            )
            return

        console.print(
            Panel(
                f"[bold]Branch:[/bold] `{target_branch}`\n"
                f"[bold]Pflicht-Freigaben vor Merge:[/bold] {BRANCH_PROTECTION_REQUIRED_REVIEWS}\n"
                "[bold]Zusätzlich:[/bold] kein Force-Push, keine Branch-Löschung, gilt auch für Repo-Admins.\n"
                "[dim]Erfordert Admin-Rechte auf dem Repo (die aktuelle `gh`-Anmeldung).[/dim]",
                title="🔒 Branch-Protection: Vorschau",
                border_style="cyan",
            )
        )
        try:
            should_apply = Confirm.ask(f"Branch-Protection für `{target_branch}` wirklich aktivieren?", default=False)
        except Exception:
            should_apply = False
        if not should_apply:
            console.print("↩️ Übersprungen.", style="dim")
            return

        success, output = await asyncio.to_thread(
            github_agent.set_branch_protection, target_branch, BRANCH_PROTECTION_REQUIRED_REVIEWS,
        )
        if success:
            console.print(f"✅ [bold green]Branch-Protection für `{target_branch}` aktiviert.[/bold green]")
        else:
            console.print(f"❌ [bold red]Fehlgeschlagen:[/bold red]\n{output}", style="red")

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

    def _render_and_confirm_plan(
        self, task_summary: str, project_slug: str, agent_tasks: list[AgentTask],
    ) -> bool:
        """
        Zeigt den von TaskManager.decompose() erstellten Plan (Zusammenfassung + genau die
        Spezialisten/Teilaufgaben, die gleich wirklich beauftragt würden - keine Schätzung,
        keine Zusammenfassung, der reale Plan) gruppiert nach Fachbereich, und lässt ihn
        bestätigen, BEVOR auch nur ein Agent startet.
        """
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
