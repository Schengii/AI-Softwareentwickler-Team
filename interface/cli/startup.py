"""
interface/cli/startup.py - Sitzungsstart, Haupt-Eingabeschleife und Modell-Preflight.

Teil der P6-5-Aufteilung von interface/cli.py (ROADMAP_TEMP.md): CLIStartupMixin deckt alles ab,
was VOR/RUND UM die eigentliche Aufgabenbearbeitung liegt - Banner, Modell-Preflight,
mehrzeilige Eingabe-Erkennung, Strg+C-Handling, Live-Status-Rendering und Sitzungsende.

`ENABLE_STARTUP_MODEL_PREFLIGHT` und `_pending_console_input` werden dort, wo sie tatsaechlich
gebraucht werden, bewusst PER-AUFRUF ueber `interface.cli` re-importiert (nicht am Modulkopf) -
bestehende Tests patchen sie als `interface.cli.<name>`; ein Modulkopf-Import hier wuerde diese
Patches stumm wirkungslos machen (siehe Modul-Docstring von scripts/_assemble_cli.py).
"""

import asyncio
import signal
import sys
import threading

from rich.panel import Panel
from rich.prompt import Confirm
from rich.text import Text

from agents.orchestrator import Orchestrator
from config import STARTUP_MODEL_PREFLIGHT_TIMEOUT_SECONDS, validate_config
from core.framework_revision import source_fingerprint
from core.task_manager import META_PROMPT_WARNING, is_framework_meta_prompt
from interface.cli._shared import (
    _BLOCK_DELIMITER,
    _CONTINUATION_SUFFIXES,
    BANNER,
    _looks_like_fragment,
    console,
)


class CLIStartupMixin:
    def __init__(self):
        self._orchestrator = Orchestrator()
        self._workspace = self._orchestrator.get_workspace_manager()
        self._loaded_project_dir: str | None = None  # von /load gesetzt, von /rag genutzt
        self._tasks_since_audit_reminder = 0
        self._last_report_path: str | None = None  # zuletzt geschriebenes Lauf-Protokoll (_write_run_report)
        # Gesetzt/geleert bei jedem Lauf (siehe _process_task) - Grundlage für den
        # kooperativen Strg+C-Abbruch (Orchestrator.process(cancel_requested=...)).
        self._cancel_event = threading.Event()
        # Fingerabdruck der beim Start geladenen Framework-Quelldateien (siehe
        # _confirm_framework_code_current) - realer Fund auditlog_sentinel 2026-09-10.
        self._code_fingerprint_at_start = source_fingerprint()
        # Läuft genau EINMAL pro Sitzung, siehe _run_startup_model_preflight() - nicht vor
        # jeder einzelnen Aufgabe (jeder Ping ist ein echter, budgetzählender API-Call).
        self._startup_preflight_done = False

    def _confirm_framework_code_current(self) -> bool:
        """Warnt, wenn sich der Framework-Code seit dem Start dieser Sitzung geändert hat.

        Realer Fund (2026-09-10): Eine seit dem Vormittag laufende CLI führte einen Lauf mit dem
        beim Start importierten Code aus – die 40 Minuten zuvor committete Modell-Mindeststufe
        griff dadurch nie, alle Rollen liefen auf dem schwächsten Modell. Python lädt geänderte
        Module nicht nach; nur ein Neustart übernimmt Korrekturen. True = Aufgabe starten."""
        current = source_fingerprint()
        if current == self._code_fingerprint_at_start:
            return True
        console.print(Panel(
            "Der Framework-Code (agents/, core/, interface/, memory/, config.py) wurde seit dem Start "
            "dieser Sitzung geändert. Diese Sitzung führt weiterhin den ALTEN, beim Start geladenen "
            "Code aus – neue Korrekturen greifen erst nach einem Neustart (`/beenden`, dann "
            "`python main.py`).",
            title="⚠️ Veralteter Framework-Code geladen",
            border_style="yellow",
        ))
        if Confirm.ask("Trotzdem mit dem alten Code fortfahren?", default=False):
            self._code_fingerprint_at_start = current
            return True
        console.print("[dim]Aufgabe nicht gestartet – bitte die CLI neu starten.[/dim]")
        return False

    async def _run_startup_model_preflight(self, *, interactive_confirm: bool = True) -> None:
        """
        Sicherheitsmaßnahme (KI-Team-Gesamtanalyse): pingt EINMAL pro Sitzung alle
        Komplexitätsstufen (LITE/STANDARD/HEAVY/ORCHESTRATOR + ggf. DeepSeek/OpenRouter, siehe
        core/model_preflight.py) an, BEVOR der Nutzer die erste Aufgabe tippen kann, und zeigt
        eine Ampel-Einschätzung, ob sich ein Projektlauf gerade lohnt.

        Realer Fund (CertPulse-Lauf, 12.09.2026, fehleranalyse_ki_team.md): ein Lauf verbrauchte
        319.244 Tokens und lieferte am Ende NICHTS ab, weil die verfügbare Modell-/Budget-Lage
        vorher nirgends sichtbar war. `core/model_preflight.py` existierte für genau diese Frage
        bereits, war aber nur über den manuellen `python main.py --check-models`-Flag abrufbar -
        diese Methode macht den Preflight endlich zur eigentlich beabsichtigten Startroutine
        (siehe dortiger Moduldocstring: "der Preflight läuft einmal beim Start").

        Rein informativ bei 🟢/🟡 - nur bei 🔴 (kein einziges Kernmodell erreichbar) fragt sie
        explizit nach, ob der Nutzer die Sitzung trotzdem fortsetzen will, statt das stillschweigend
        zu unterschlagen. Ein "Nein" beendet die CLI nicht (es gibt an dieser Stelle noch keine
        laufende Aufgabe, die abzubrechen wäre) - es ist die bewusste, protokollierte
        Kenntnisnahme, bevor der Nutzer trotzdem eine Aufgabe tippt.
        """
        from core.model_preflight import (
            assess_run_readiness,
            format_preflight_report,
            format_recovery_outlook,
            format_run_readiness,
            run_model_preflight,
        )
        from core.provider_budget import format_budget_report
        from core.token_guard import token_guard

        console.print("\n🔎 [dim]Prüfe kurz die Verfügbarkeit aller KI-Modelle...[/dim]")
        try:
            ergebnisse = await run_model_preflight(timeout_seconds=STARTUP_MODEL_PREFLIGHT_TIMEOUT_SECONDS)
        except Exception as e:
            # Der Preflight darf einen Start NIE blockieren (siehe Moduldocstring) - schlägt
            # er selbst unerwartet fehl (z.B. Netzwerkfehler außerhalb der pro-Stufe-Behandlung),
            # startet die Sitzung trotzdem ganz normal.
            console.print(f"[dim]⚠️ Modell-Preflight übersprungen: {e}[/dim]")
            return

        readiness = assess_run_readiness(ergebnisse)
        border = {"green": "green", "yellow": "yellow", "red": "red"}.get(readiness.level, "cyan")
        report_text = format_preflight_report(ergebnisse) + "\n\n" + format_run_readiness(readiness)
        # Beantwortet die naheliegende Anschlussfrage an die Ampel: WANN genau sind die gerade
        # nicht erreichbaren Kernstufen voraussichtlich wieder da (core/token_guard.py kennt
        # den genauen Cooldown bereits aus den Preflight-Pings selbst, siehe dortiger Docstring).
        recovery_outlook = format_recovery_outlook(ergebnisse, guard=token_guard)
        if recovery_outlook:
            report_text += "\n" + recovery_outlook
        budget_report = format_budget_report(token_guard)
        if budget_report:
            report_text += "\n" + budget_report
        console.print(Panel(report_text, title="🩺 Modell-Preflight", border_style=border))

        if interactive_confirm and readiness.should_confirm:
            Confirm.ask(
                "Trotzdem fortfahren und es bei Bedarf versuchen? (Aufgaben scheitern derzeit "
                "wahrscheinlich sofort)",
                default=True,
            )

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
            "💡 Schreibe einfach deine Projektidee in den Chat! (Tippe /hilfe für Befehle)\n"
            "   Mehrzeilige Eingaben: einfach einfügen, Zeile mit \\ beenden oder einen Block\n"
            "   mit \"\"\" beginnen und mit \"\"\" abschließen.\n",
            style="dim"
        )

        asyncio.run(self._main_loop())

    def _read_user_input(self) -> str:
        """
        Liest EINE Nutzereingabe, ggf. über mehrere Zeilen hinweg – realer Fund: `console.
        input()` (dünner Wrapper um Pythons `input()`) liest immer nur bis zum ersten
        Zeilenumbruch. Eine mehrzeilige Aufgabenbeschreibung wurde dadurch nicht als EINE
        Eingabe erkannt, sondern jede Zeile einzeln als eigener, meist unsinniger Prompt an
        `_main_loop()` weitergereicht.

        Zweiter realer Fund (auditlog_sentinel, 2026-09-10): die `\\`-Konvention allein genügte
        nicht. Ein eingefügter Auftrag mit Zeilen wie „… (auditlog_sentinel). /“ und
        „2. Sicherheit & Governance:“ startete ZWEI komplette Läufe (1,36 Mio. Tokens) mit
        je einer einzigen Zeile als Spezifikation. Eine Eingabe gilt deshalb erst als
        abgeschlossen, wenn
        - keine Fortsetzungsmarke (`\\` oder ` /`) am Zeilenende steht,
        - kein Blockmodus (`\"\"\"` … `\"\"\"`) offen ist,
        - keine weiteren eingefügten Zeilen bereits im Eingabepuffer warten (Paste-Erkennung),
        - der bisherige Text nicht erkennbar nur ein Fragment ist (Überschrift, Aufzählungs-
          Kopf mit „:“, Trennlinie). Eine leere Zeile beendet ein solches Fragment bewusst.
        """
        from interface.cli import _pending_console_input
        lines: list[str] = []
        prompt_label = "[bold green]Du[/bold green] → "
        continuation_label = "[bold green]…[/bold green] → "
        in_block = False
        fragment_mode = False
        while True:
            line = console.input(prompt_label)
            prompt_label = continuation_label
            stripped = line.strip()

            if stripped == _BLOCK_DELIMITER:
                if in_block:
                    break
                in_block = True
                continue
            if in_block:
                lines.append(line)
                continue

            continued = False
            for suffix in _CONTINUATION_SUFFIXES:
                if line.endswith(suffix):
                    line = line[: -len(suffix)]
                    continued = True
                    break
            lines.append(line)
            if continued or _pending_console_input():
                continue
            if not stripped and len(lines) > 1:
                break
            if fragment_mode:
                continue
            if _looks_like_fragment("\n".join(lines)):
                fragment_mode = True
                console.print(
                    "[dim]↳ Das sieht nach dem Anfang einer mehrzeiligen Anforderung aus – schreibe "
                    "weiter, eine leere Zeile schließt die Eingabe ab.[/dim]"
                )
                continue
            break
        return "\n".join(lines).strip()

    async def _main_loop(self) -> None:
        """Hauptschleife: Eingabe → Verarbeitung → Ausgabe."""
        from interface.cli import ENABLE_STARTUP_MODEL_PREFLIGHT
        if ENABLE_STARTUP_MODEL_PREFLIGHT and not self._startup_preflight_done:
            self._startup_preflight_done = True
            await self._run_startup_model_preflight()
        while True:
            try:
                user_input = self._read_user_input()
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

            if not self._confirm_framework_code_current():
                continue

            # Meta-Prompt-Schutzfilter (core/task_manager.py): blockiert versehentlich
            # eingefügte Framework-Verbesserungs-Aufträge, statt sie krampfhaft als
            # Software-Projekt im workspace/ zu interpretieren (siehe dortiger Docstring).
            if is_framework_meta_prompt(user_input):
                console.print(f"\n{META_PROMPT_WARNING}\n", style="yellow")
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

