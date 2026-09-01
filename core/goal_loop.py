"""
core/goal_loop.py – Autonomer Ziel- & Iterations-Loop für das KI-Softwareentwickler-Team.

Ermöglicht vollautomatische Softwareentwicklung in Feedback-Schleifen:
1. Nimmt ein Gesamtziel (Goal / Anforderung) entgegen.
2. Führt den Entwicklungszyklus mit dem 33-köpfigen KI-Team aus (Orchestrator).
3. Analysiert nach jedem Durchlauf den aktuellen Zwischenstand (Code, Tests, Linter, Offene Punkte).
4. Bewertet via KI-Synthese:
   - Ist das Projektziel vollständig erreicht und alle Tests grün? -> Beendet den Loop mit Erfolgsmeldung.
   - Gibt es noch offene Punkte oder Testfehler? -> Generiert automatisch den nächsten präzisen Folge-Prompt.
5. Führt die nächste Iteration aus, bis das Ziel erreicht oder max_iterations erreicht ist.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents.orchestrator import Orchestrator
from config import (
    GOAL_LOOP_DEFAULT_MAX_ITERATIONS,
    GOAL_LOOP_EVAL_MODEL,
    GOAL_LOOP_MAX_TOTAL_TOKENS,
    WORKSPACE_DIR,
)
from core.backlog_store import new_ticket_id, upsert_ticket
from core.llm_factory import LLMFactory
from core.project_status import read_status
from core.token_guard import token_guard

logger = logging.getLogger(__name__)

StatusCallback = Callable[[str], None]
CancelCallback = Callable[[], bool]


@dataclass
class GoalIterationReport:
    """Ergebnisbericht einer einzelnen Iteration im Ziel-Loop."""
    iteration: int
    prompt_used: str
    summary: str = ""
    verification_ok: bool = False
    failure_detail: str = ""
    goal_reached: bool = False
    evaluation_reason: str = ""
    files_count: int = 0


@dataclass
class GoalLoopResult:
    """Gesamtergebnis eines autonomen Ziel-Loops."""
    goal: str
    project_slug: str
    success: bool
    total_iterations: int
    iterations: list[GoalIterationReport] = field(default_factory=list)
    final_message: str = ""
    cancelled: bool = False

    def format_summary(self) -> str:
        """Gibt eine übersichtliche Zusammenfassung des Ziel-Loops zurück."""
        status_icon = "✅" if self.success else ("⏹️" if self.cancelled else "⚠️")
        title = f"{status_icon} **Autonomer Ziel-Loop: {self.project_slug}**"
        
        lines = [
            title,
            f"- **Gesamtziel:** {self.goal}",
            f"- **Absolvierte Iterationen:** {self.total_iterations}",
            f"- **Status:** {'Ziel erfolgreich erreicht & verifiziert!' if self.success else ('Durch Nutzer abgebrochen' if self.cancelled else 'Max. Iterationen erreicht')}",
            "",
            "### 🔄 Iterations-Verlauf:",
        ]
        
        for it in self.iterations:
            v_icon = "✅ grün" if it.verification_ok else "⚠️ offen/rot"
            g_icon = "🎯 Ziel erreicht" if it.goal_reached else "🔄 Weiterentwicklung nötig"
            lines.append(f"1. **Iteration {it.iteration}:** {it.summary or it.prompt_used[:60]}")
            lines.append(f"   - Tests & Verifikation: {v_icon}")
            lines.append(f"   - KI-Bewertung: {g_icon} – {it.evaluation_reason}")
            if it.failure_detail:
                lines.append(f"   - Hinweis: {it.failure_detail[:120]}")

        if self.final_message:
            lines.append("")
            lines.append(f"**Fazit:** {self.final_message}")

        return "\n".join(lines)


class GoalLoopRunner:
    """Koordiniert die autonome Ausführung von Zielen in Feedback-Schleifen."""

    def __init__(self, orchestrator: Orchestrator | None = None):
        self._orchestrator = orchestrator or Orchestrator()
        self._workspace = self._orchestrator.get_workspace_manager()

    async def run(
        self,
        goal: str,
        project_dir: str | None = None,
        max_iterations: int = GOAL_LOOP_DEFAULT_MAX_ITERATIONS,
        status_callback: StatusCallback | None = None,
        cancel_requested: CancelCallback | None = None,
    ) -> GoalLoopResult:
        """
        Führt den autonomen Ziel-Loop aus.
        
        Args:
            goal: Das übergeordnete Ziel oder die Projektanforderung.
            project_dir: Optionales bestehendes Projektverzeichnis.
            max_iterations: Maximale Anzahl von Entwicklungsrunden.
            status_callback: Live-Statusmeldungen für CLI/UI.
            cancel_requested: Prüffunktion für kooperativen Abbruch (z.B. Strg+C).
        """
        def emit(msg: str):
            if status_callback:
                status_callback(msg)

        emit(f"🎯 [bold cyan]Starte autonomen Ziel-Loop[/bold cyan] (max. {max_iterations} Iterationen)...")

        # Initialen Project-Slug bestimmen
        project_slug = ""
        if project_dir:
            project_slug = Path(project_dir).name
        else:
            import re
            words = [w.lower() for w in re.findall(r"[a-zA-Z0-9]+", goal)[:4]]
            project_slug = "_".join(words) or "goal_project"
            project_dir = str(Path(WORKSPACE_DIR) / project_slug)

        current_prompt = goal
        iterations_history: list[GoalIterationReport] = []
        is_goal_reached = False
        was_cancelled = False
        budget_exceeded = False
        stagnated = False
        loop_start_tokens = token_guard.get_summary()["grand_total_tokens"]
        previous_failure_detail: str | None = None

        ticket_id = new_ticket_id("goal")
        upsert_ticket(
            ticket_id=ticket_id,
            title=f"Goal: {goal[:60]}",
            source="cli",
            status="in_progress",
            project_slug=project_slug,
        )

        for iteration in range(1, max_iterations + 1):
            if cancel_requested and cancel_requested():
                emit("⏹️ [yellow]Ziel-Loop durch Nutzer abgebrochen.[/yellow]")
                was_cancelled = True
                break

            emit(f"\n🚀 [bold blue]=== Iteration {iteration}/{max_iterations} ===[/bold blue]")
            emit(f"📋 **Aufgabe:** {current_prompt[:100]}...")

            # 1. Orchestrator-Lauf ausführen
            try:
                result_text = await self._orchestrator.process(
                    user_request=current_prompt,
                    status_callback=status_callback,
                    forced_project_dir=project_dir,
                    cancel_requested=cancel_requested or (lambda: False),
                )
            except Exception as e:
                logger.exception("Fehler während der Goal-Loop Iteration: %s", e)
                emit(f"❌ [bold red]Fehler in Iteration {iteration}:[/bold red] {e}")
                iterations_history.append(
                    GoalIterationReport(
                        iteration=iteration,
                        prompt_used=current_prompt,
                        summary=f"Fehler: {e}",
                        verification_ok=False,
                        failure_detail=str(e),
                        goal_reached=False,
                        evaluation_reason="Lauf abgebrochen wegen Exception.",
                    )
                )
                break

            # 2. Projekt-Status & Verifikation auslesen
            history_entries = read_status(project_dir)
            last_entry = history_entries[0] if history_entries else None
            
            verification_ok = last_entry.get("verification_ok", False) if last_entry else False
            failure_detail = last_entry.get("failure_detail", "") if last_entry else ""
            summary = self._orchestrator.last_task_summary or f"Iteration {iteration} abgeschlossen"

            # 3. KI-Bewertung & Synthese des nächsten Schritts
            emit(f"🔍 [bold magenta]Analysiere Zwischenstand & Zielerreichung (Iteration {iteration})...[/bold magenta]")
            eval_result = await self._evaluate_and_synthesize_next_step(
                goal=goal,
                project_dir=project_dir,
                iteration=iteration,
                max_iterations=max_iterations,
                summary=summary,
                verification_ok=verification_ok,
                failure_detail=failure_detail,
                result_text=result_text,
            )

            is_goal_reached = eval_result.get("goal_reached", False)
            evaluation_reason = eval_result.get("reason", "")
            next_prompt = eval_result.get("next_prompt", "")

            report = GoalIterationReport(
                iteration=iteration,
                prompt_used=current_prompt,
                summary=summary,
                verification_ok=verification_ok,
                failure_detail=failure_detail,
                goal_reached=is_goal_reached,
                evaluation_reason=evaluation_reason,
            )
            iterations_history.append(report)

            if is_goal_reached:
                emit(f"🎉 [bold green]Ziel vollständig erreicht in Iteration {iteration}![/bold green] ({evaluation_reason})")
                break

            # Stagnations-Erkennung: liefert die Verifikation zwei Iterationen in Folge exakt
            # denselben Fehler, dreht sich der Loop im Kreis (ein Bug, den das Team offenbar
            # nicht selbst löst) - weitere Runden verbrennen nur Tokens ohne Fortschritt.
            if (
                not verification_ok
                and failure_detail
                and previous_failure_detail is not None
                and failure_detail == previous_failure_detail
            ):
                emit(
                    "🛑 [bold red]Stagnation erkannt:[/bold red] derselbe Verifikationsfehler wie in der "
                    f"Vorrunde ({failure_detail[:100]}) – breche ab, statt Iterationen zu verschwenden."
                )
                stagnated = True
                break
            previous_failure_detail = failure_detail or None

            # Kumulatives Token-Budget über alle bisherigen Iterationen dieses Loops.
            if GOAL_LOOP_MAX_TOTAL_TOKENS > 0:
                tokens_used = token_guard.get_summary()["grand_total_tokens"] - loop_start_tokens
                if tokens_used >= GOAL_LOOP_MAX_TOTAL_TOKENS:
                    emit(
                        f"🪙 [bold red]Ziel-Loop-Budget erreicht[/bold red] ({tokens_used}/"
                        f"{GOAL_LOOP_MAX_TOTAL_TOKENS} Tokens über alle Iterationen) – breche ab."
                    )
                    budget_exceeded = True
                    break

            if iteration < max_iterations:
                if not next_prompt:
                    next_prompt = (
                        f"Setze die Entwicklung von {project_slug} fort, um das Gesamtziel '{goal}' zu erreichen. "
                        f"Behebe alle offenen Fehler und stelle sicher, dass alle Tests grün sind."
                    )
                current_prompt = next_prompt
                emit(f"🔄 [bold yellow]Generierter Folge-Prompt für Iteration {iteration+1}:[/bold yellow] {current_prompt[:120]}...")
            else:
                emit(f"⚠️ [yellow]Maximale Anzahl von {max_iterations} Iterationen erreicht.[/yellow]")

        final_success = is_goal_reached and (iterations_history[-1].verification_ok if iterations_history else False)
        final_msg = "Ziel erfolgreich fertiggestellt und verifiziert." if final_success else (
            "Abbruch durch Nutzer." if was_cancelled else (
                "Abbruch: Verifikation stagnierte über zwei Iterationen mit identischem Fehler." if stagnated else (
                    "Abbruch: kumulatives Ziel-Loop-Token-Budget erreicht." if budget_exceeded else
                    "Ziel nach maximalen Iterationen noch nicht vollständig abgeschlossen."
                )
            )
        )

        upsert_ticket(
            ticket_id=ticket_id,
            title=f"Goal: {goal[:60]}",
            source="cli",
            status="done" if final_success else "review",
            project_slug=project_slug,
            detail=f"{len(iterations_history)} Iteration(en) absolviert.",
        )

        return GoalLoopResult(
            goal=goal,
            project_slug=project_slug,
            success=final_success,
            total_iterations=len(iterations_history),
            iterations=iterations_history,
            final_message=final_msg,
            cancelled=was_cancelled,
        )

    async def _evaluate_and_synthesize_next_step(
        self,
        goal: str,
        project_dir: str,
        iteration: int,
        max_iterations: int,
        summary: str,
        verification_ok: bool,
        failure_detail: str,
        result_text: str,
    ) -> dict[str, Any]:
        """
        Bewertet den Projektzustand und erzeugt den nächsten Aktions-Prompt.
        Nutzt ein strukturiertes LLM-Prompting mit robuster Heuristik als Fallback.
        """
        # Liste vorhandener Dateien im Projekt ermitteln
        file_list: list[str] = []
        p_path = Path(project_dir)
        if p_path.exists():
            for f in p_path.rglob("*"):
                if f.is_file() and not any(part.startswith((".", "__pycache__", "node_modules")) for part in f.parts):
                    file_list.append(str(f.relative_to(p_path)))

        eval_prompt = f"""Du bist der leitende Product Owner und Quality Gate Lead des KI-Softwareentwickler-Teams.

Deine Aufgabe ist es, den aktuellen Arbeitsstand eines Projekts gegen das vorgegebene Gesamtziel zu prüfen und zu entscheiden, ob das Ziel vollständig erreicht ist oder welcher präzise Folge-Prompt für die nächste Entwicklungsrunde erforderlich ist.

### 🎯 Gesamtziel:
"{goal}"

### 📊 Aktueller Status nach Iteration {iteration}/{max_iterations}:
- Letzte Zusammenfassung: {summary}
- Verifikations-Status (Tests): {'✅ GRÜN (Bestanden)' if verification_ok else '❌ ROT (Fehlgeschlagen / Ausstehend)'}
- Verifikations-Details / Fehler: {failure_detail or 'Keine'}
- Vorhandene Projektdateien ({len(file_list)}): {', '.join(file_list[:30])}

### Regeln:
1. 'goal_reached' darf NUR dann true sein, wenn:
   - Die geforderten Hauptkomponenten (Backend, Frontend, Konfiguration etc.) substanziell vorhanden sind.
   - Der Verifikations-Status GRÜN ist (oder keine Tests erforderlich waren).
2. Wenn 'goal_reached' false ist, formuliere einen glasklaren, präzisen 'next_prompt' für das KI-Team, der:
   - Exakte Fehler aus dem Verifikations-Protokoll behebt.
   - Fehlende Endpunkte, Module oder Frontend-Views implementiert.
   - Konkrete Dateinamen und Anweisungen nennt.

Antworte AUSSCHLIESSLICH im folgenden JSON-Format:
```json
{{
  "goal_reached": true/false,
  "reason": "Kurze Begründung der Bewertung",
  "next_prompt": "Präziser Folgeauftrag für das KI-Team (leer falls goal_reached true)"
}}
```"""

        try:
            # create_for_model() statt eines nicht existierenden create_llm(): dieselbe
            # zentrale Provider-Erkennung wie bei jedem Agenten-Aufruf, inklusive der in
            # GeminiClient._call_with_retry_and_usage() eingebauten MODEL_FALLBACKS-Kette
            # (Cross-Provider-Fallback bei Erschöpfung/Fehler des primären Eval-Modells).
            llm = LLMFactory.create_for_model(GOAL_LOOP_EVAL_MODEL)
            response_text = await llm.generate(eval_prompt)
            
            # JSON aus der Antwort extrahieren
            clean_text = response_text.strip()
            if "```json" in clean_text:
                clean_text = clean_text.split("```json")[1].split("```")[0].strip()
            elif "```" in clean_text:
                clean_text = clean_text.split("```")[1].split("```")[0].strip()

            parsed = json.loads(clean_text)
            if isinstance(parsed, dict) and "goal_reached" in parsed:
                return parsed
        except Exception as e:
            logger.warning("LLM-Evaluation im Goal-Loop fehlgeschlagen (%s), nutze Heuristik-Fallback.", e)

        # Robuster Heuristik-Fallback
        if verification_ok and len(file_list) >= 3:
            return {
                "goal_reached": True,
                "reason": "Verifikation ist grün und alle Kernkomponenten existieren.",
                "next_prompt": "",
            }
        else:
            reason = "Tests sind noch nicht grün oder Komponenten fehlen."
            fix_instruction = f"Behebe die offenen Verifikations- und Testfehler ({failure_detail[:100]})." if failure_detail else "Vervollständige die Implementierung und führe Tests aus."
            next_prompt = f"Projekt {Path(project_dir).name}: {fix_instruction} Mache alle Tests grün und vollende das Gesamtziel '{goal}'."
            return {
                "goal_reached": False,
                "reason": reason,
                "next_prompt": next_prompt,
            }


async def run_goal_loop(
    goal: str,
    project_dir: str | None = None,
    max_iterations: int = GOAL_LOOP_DEFAULT_MAX_ITERATIONS,
    status_callback: StatusCallback | None = None,
    cancel_requested: CancelCallback | None = None,
) -> GoalLoopResult:
    """Hilfsfunktion zum direkten Starten eines GoalLoop-Laufs."""
    runner = GoalLoopRunner()
    return await runner.run(
        goal=goal,
        project_dir=project_dir,
        max_iterations=max_iterations,
        status_callback=status_callback,
        cancel_requested=cancel_requested,
    )
