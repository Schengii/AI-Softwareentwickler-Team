"""
core/agent_watchdog.py – Live-Überwachung eines Agenten während seines Werkzeug-Loops

Bisher fielen Fehlverhalten erst NACH der Aufgabe auf (Hard Delivery Gate, Pre-Flight, Trainer).
Beobachtete Muster aus echten Läufen, die jeweils zehntausende Tokens kosteten:
- Code-Rolle liest Iteration um Iteration, ohne je zu schreiben
- dieselbe Datei wird immer wieder komplett neu geschrieben
- derselbe Werkzeug-Fehler wiederholt sich unverändert
- der Prompt wächst pro Iteration weit über 80k Tokens (tester: 128k für 1,6k Ausgabe)
- eine einzelne Aufgabe verbraucht ein Viertel des Laufbudgets

Der Watchdog erkennt diese Muster nach jeder Iteration deterministisch und greift sofort ein:
Hinweis an den Agenten, aggressive Kontext-Verdichtung oder geordneter Abschluss.
Jede Intervention (außer dem Abschluss) feuert höchstens einmal pro Aufgabe.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

READ_TOOLS = frozenset({"read_file", "list_files", "search_code", "find_symbol_definition",
                        "find_symbol_references", "analyze_code_impact", "search_component_library"})
WRITE_TOOLS = frozenset({"write_file", "edit_file", "patch_file", "add_dependency"})


@dataclass
class Intervention:
    kind: str
    message: str
    compact: bool = False
    stop: bool = False


@dataclass
class AgentWatchdog:
    agent_id: str
    code_writing: bool
    max_prompt_tokens: int = 80_000
    task_token_cap: int = 250_000
    read_streak_limit: int = 2
    rewrite_limit: int = 3
    tool_call_soft_limit: int = 15
    events: list[str] = field(default_factory=list)
    _fired: set[str] = field(default_factory=set)
    _read_only_streak: int = 0
    _total_tokens: int = 0
    _tool_calls: int = 0
    _last_prompt_alarm: int = 0
    _writes: Counter = field(default_factory=Counter)
    _last_error: str = ""

    def _fire(self, kind: str, message: str, **flags) -> Intervention | None:
        if kind in self._fired and not flags.get("stop"):
            return None
        self._fired.add(kind)
        self.events.append(kind)
        return Intervention(kind=kind, message=f"🛡️ WATCHDOG ({kind}): {message}", **flags)

    def observe(
        self,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        tool_calls: list[tuple[str, dict]],
        tool_results: list[dict],
        files_written_count: int,
    ) -> list[Intervention]:
        interventions: list[Intervention | None] = []
        self._total_tokens += (prompt_tokens or 0) + (completion_tokens or 0)
        names = [name for name, _ in tool_calls]

        if self.code_writing and files_written_count == 0 and names and all(n in READ_TOOLS for n in names):
            self._read_only_streak += 1
        elif any(n in WRITE_TOOLS for n in names):
            self._read_only_streak = 0
        if self._read_only_streak >= self.read_streak_limit:
            # Realer Fund (cloudpulse, 2026-09-16): der Hinweis feuerte pro Aufgabe nur EIN
            # einziges Mal. Ein Agent, der danach weiterliest, bekam nie wieder ein Signal -
            # der Lauf lief mit 1,04 Mio Tokens ins Budget-Aus. Jede WEITERE reine Lese-
            # Iteration nach dem ersten Hinweis meldet sich deshalb erneut, jetzt mit
            # erzwungener Kontext-Verdichtung.
            escalated = self._read_only_streak > self.read_streak_limit
            interventions.append(self._fire(
                f"read_without_write#{self._read_only_streak}" if escalated else "read_without_write",
                f"Du hast {self._read_only_streak} Iterationen nur gelesen und noch keine Datei gespeichert. "
                "Du hast genug Kontext - schreibe JETZT deine erste Zieldatei per write_file."
                + (" Weiteres Lesen ohne Schreiben wird als Fehlschlag der Aufgabe gewertet." if escalated else ""),
                compact=escalated,
            ))

        for (name, args), result in zip(tool_calls, tool_results, strict=False):
            if name == "write_file" and "error" not in result:
                path = str((args or {}).get("path", ""))
                self._writes[path] += 1
                if self._writes[path] >= self.rewrite_limit:
                    interventions.append(self._fire(
                        "repeated_rewrite",
                        f"'{path}' wurde bereits {self._writes[path]}-mal komplett neu geschrieben. Hör auf, die Datei "
                        "neu zu erzeugen: nutze edit_file für gezielte Korrekturen oder run_tests, um den Fehler zu finden.",
                    ))
            error = str(result.get("error", "")) if isinstance(result, dict) else ""
            if error:
                signature = f"{name}:{error[:160]}"
                if signature == self._last_error:
                    interventions.append(self._fire(
                        "repeated_tool_error",
                        f"Derselbe Fehler bei '{name}' ist zweimal hintereinander aufgetreten: {error[:200]}. "
                        "Wiederhole den Aufruf nicht unverändert - ändere Ansatz, Pfad oder Argumente.",
                    ))
                self._last_error = signature
            elif name:
                self._last_error = ""

        # Eskalierend statt einmalig: bisher verdichtete der Watchdog den Kontext genau einmal.
        # Wuchs der Prompt danach weiter (tester: 208k, backend: 273k Tokens in EINEM Aufruf,
        # cloudpulse 2026-09-16), passierte nichts mehr. Jede weitere Verdopplung der
        # Überschreitung löst deshalb eine erneute Verdichtung aus.
        if prompt_tokens and prompt_tokens > self.max_prompt_tokens:
            threshold = max(self._last_prompt_alarm * 2, self.max_prompt_tokens)
            if prompt_tokens >= threshold:
                self._last_prompt_alarm = prompt_tokens
                interventions.append(self._fire(
                    "prompt_explosion" if threshold == self.max_prompt_tokens else f"prompt_explosion#{prompt_tokens}",
                    f"Der Kontext ist auf {prompt_tokens:,} Tokens angewachsen. Ältere Werkzeug-Ergebnisse wurden gekürzt; "
                    "lies nur noch gezielt (line_start/line_end) und komm zum Abschluss.",
                    compact=True,
                ))

        # Werkzeug-Budget: ein Agent, der nach vielen Aufrufen noch nichts gespeichert hat,
        # dreht erfahrungsgemäß im Kreis (backend: 22 Tool-Calls / 273k Tokens). Der Deckel
        # greift unabhängig vom Tokenzähler, weil viele kleine Lesezugriffe den Token-Deckel
        # erst spät erreichen, den Kontext aber längst aufgebläht haben.
        self._tool_calls += len(names)
        if self._tool_calls >= self.tool_call_soft_limit and files_written_count == 0:
            interventions.append(self._fire(
                "tool_call_budget",
                f"Du hast bereits {self._tool_calls} Werkzeugaufrufe gemacht, ohne eine einzige Datei zu speichern. "
                "Persistiere JETZT deinen bisherigen Zwischenstand per write_file - unfertige, aber gespeicherte "
                "Arbeit ist wertvoller als ein weiterer Lesedurchgang.",
                compact=True,
            ))

        if self._total_tokens > self.task_token_cap and "task_token_cap" not in self._fired:
            interventions.append(self._fire(
                "task_token_cap",
                f"Diese Aufgabe hat bereits {self._total_tokens:,} Tokens verbraucht (Deckel {self.task_token_cap:,}). "
                "Schließe JETZT ab: speichere fertige Arbeit und liefere deine Zusammenfassung mit offenen Punkten.",
                stop=True,
            ))
        return [i for i in interventions if i is not None]
