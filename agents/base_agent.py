"""
agents/base_agent.py – Abstrakte Basisklasse für alle Unteragenten

Jeder spezialisierte Agent erbt von dieser Klasse. Ist ein Projektverzeichnis
gesetzt (AgentTask.project_dir) und Werkzeuge erlaubt, durchläuft der Agent
einen ECHTEN agentischen Loop: Er bekommt Zugriff auf read_file, write_file,
edit_file, list_files, search_code, run_command und run_tests, ruft sie über
natives Function-Calling der jeweiligen LLM-API auf und sieht die realen
Ergebnisse (Dateiinhalte, Testausgaben) – statt nur einen einzelnen Text zu
generieren, der hinterher per Regex nach Codeblöcken durchsucht wird.

Ohne project_dir (z.B. für reine Text-/Synthese-Aufgaben) bleibt der einfache
Ein-Schuss-Aufruf über generate_with_usage() erhalten.
"""

import json
import time
from abc import ABC, abstractmethod

from config import MAX_AGENT_TOOL_ITERATIONS
from core.agent_toolbox import AgentToolbox
from core.llm_factory import AgentMessage, GeminiClient, LLMFactory, LLMResponse
from core.message_bus import AgentResult, AgentTask


class BaseAgent(ABC):
    """
    Abstrakte Basisklasse für alle Unteragenten des KI-Teams.
    """

    def __init__(self, agent_id: str, name: str, model_name: str | None = None):
        self.agent_id = agent_id
        self.name = name
        self._llm: GeminiClient = LLMFactory.create_for_agent(agent_id) if not model_name \
            else LLMFactory.create_gemini(model_name)

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Der spezialisierte System-Prompt für diesen Agenten."""
        ...

    async def execute(self, task: AgentTask) -> AgentResult:
        """
        Führt die zugewiesene Aufgabe aus und gibt das Ergebnis samt Tokenmetriken zurück.
        Reichert den System-Prompt automatisch mit persistent gelernten Regeln an.
        """
        start_time = time.monotonic()
        use_tools = bool(task.project_dir) and task.allow_tools
        toolbox: AgentToolbox | None = None

        try:
            from memory.agent_knowledge_base import agent_knowledge_base
            effective_system_prompt = agent_knowledge_base.get_augmented_prompt(self.agent_id, self.system_prompt)

            if use_tools:
                toolbox = AgentToolbox(project_dir=task.project_dir, agent_id=self.agent_id, read_only=task.tools_read_only)
                effective_system_prompt = self._augment_with_tool_instructions(effective_system_prompt)
                response, prompt_tokens, completion_tokens = await self._run_agentic_loop(
                    task=task, toolbox=toolbox, system_prompt=effective_system_prompt,
                )
            else:
                prompt = self._build_prompt(task)
                response = await self._llm.generate_with_usage(prompt, effective_system_prompt)
                prompt_tokens, completion_tokens = response.prompt_tokens, response.completion_tokens

            duration = time.monotonic() - start_time
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                agent_name=self.name,
                success=True,
                content=response.text,
                duration_seconds=duration,
                model_used=response.model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                files_written=sorted(toolbox.files_written) if toolbox else [],
                tool_calls_count=toolbox.call_count if toolbox else 0,
            )

        except Exception as e:
            duration = time.monotonic() - start_time
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                agent_name=self.name,
                success=False,
                content="",
                error=str(e),
                duration_seconds=duration,
                model_used=self._llm.model_name,
                files_written=sorted(toolbox.files_written) if toolbox else [],
                tool_calls_count=toolbox.call_count if toolbox else 0,
            )

    async def _run_agentic_loop(
        self,
        task: AgentTask,
        toolbox: AgentToolbox,
        system_prompt: str,
    ) -> tuple[LLMResponse, int, int]:
        """
        Der echte Werkzeug-Loop: Modell antwortet entweder mit finalem Text ODER
        mit angeforderten Werkzeug-Aufrufen. Werkzeug-Aufrufe werden ausgeführt,
        ihr reales Ergebnis wird als Folge-Nachricht zurückgespielt, bis das
        Modell eine finale Textantwort liefert oder das Iterationslimit erreicht ist.

        Provider wird pro Aufgabe FESTGENAGELT, sobald ein Fallback-Hop tatsächlich
        geantwortet hat (siehe active_llm unten). Realer Fund aus einem echten Lauf: Ohne
        das löste jede Iteration die Fallback-Kette (core/llm_factory.py MODEL_FALLBACKS)
        unabhängig neu auf. Antwortete z.B. Iteration 1 über Groq (kein Claude-Key) und
        scheiterte Groq dann in Iteration 2 (z.B. Rate-Limit), sprang die Kette weiter zu
        Gemini – das dann die BISHERIGE Historie inkl. eines von GROQ erzeugten function_call
        sah, dem die von Gemini zwingend verlangte thought_signature fehlt, und lehnte mit
        "400 INVALID_ARGUMENT: Function call is missing a thought_signature" komplett ab
        (beobachtet bei den Agenten `backend` und `code_reviewer`). Einmal gepinnt, wird kein
        weiterer Fallback mehr innerhalb DIESER Aufgabe zugelassen (_allow_self_fallback=False)
        – schlägt der gepinnte Provider erneut fehl, ist ein klarer Fehlschlag (jetzt sichtbar,
        siehe agents/orchestrator.py _status_notify_line) der sichereren Alternative vorzuziehen,
        Historie stillschweigend über einen weiteren, ebenfalls fremden Provider zu beschädigen.
        """
        max_iterations = task.max_tool_iterations or MAX_AGENT_TOOL_ITERATIONS
        initial_prompt = self._build_prompt(task)

        # Aktuellen Dateibaum EINMALIG synchron voranstellen, statt darauf zu vertrauen, dass
        # das Modell von sich aus zuerst list_files aufruft. Spart eine ganze Loop-Iteration
        # (Prompt+Response-Tokens) UND verringert das Risiko, dass ein Agent unwissentlich eine
        # bereits von einem anderen Teammitglied dieser Phase geschriebene Datei unter anderem
        # Namen doppelt neu implementiert (real beobachtet: `app.py`/`test_app.py` UND separat
        # `main.py`/`test_main.py` für denselben trivialen Health-Check-Endpoint).
        existing_files = await toolbox.list_files_snapshot()
        if existing_files:
            initial_prompt += (
                "\n\n**BEREITS VORHANDENE DATEIEN IM PROJEKT (von dir oder Teamkollegen):**\n"
                + "\n".join(f"- {f}" for f in existing_files)
                + "\n\nPrüfe VOR jedem write_file, ob die gewünschte Funktionalität hier bereits "
                "(ggf. unter anderem Dateinamen) existiert. Erweitere/nutze bestehenden Code statt "
                "eine zweite, parallele Implementierung derselben Sache anzulegen."
            )

        turns: list[AgentMessage] = [AgentMessage(role="user", text=initial_prompt)]

        total_prompt_tokens = 0
        total_completion_tokens = 0
        response: LLMResponse | None = None
        active_llm = self._llm

        for iteration in range(1, max_iterations + 1):
            allow_fallback = active_llm is self._llm
            response = await active_llm.generate_with_tools(
                turns, system_prompt, toolbox.tool_specs(), _allow_self_fallback=allow_fallback,
            )
            total_prompt_tokens += response.prompt_tokens
            total_completion_tokens += response.completion_tokens

            if allow_fallback and response.model_name != self._llm.model_name:
                active_llm = LLMFactory.create_for_model(response.model_name)

            if not response.tool_calls or iteration == max_iterations:
                if not response.text and response.tool_calls:
                    # Modell hat im letzten erlaubten Schritt nur Werkzeuge angefordert,
                    # aber keinen Abschlusstext geliefert -> ehrliche Notiz statt leerer Antwort.
                    files_note = ", ".join(sorted(toolbox.files_written)) or "keine"
                    response.text = (
                        f"⚠️ Maximale Werkzeug-Iterationen ({max_iterations}) erreicht, bevor eine finale "
                        f"Zusammenfassung generiert wurde. Bisher geschriebene/geänderte Dateien: {files_note}."
                    )
                break

            turns.append(AgentMessage(role="assistant", text=response.text, tool_calls=response.tool_calls))
            for tool_call in response.tool_calls:
                result = await toolbox.dispatch(tool_call.name, tool_call.arguments)
                turns.append(AgentMessage(
                    role="tool",
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    text=json.dumps(result, ensure_ascii=False),
                ))

        assert response is not None
        return response, total_prompt_tokens, total_completion_tokens

    def _augment_with_tool_instructions(self, system_prompt: str) -> str:
        return f"""{system_prompt}

## 🛠️ WERKZEUG-NUTZUNG (agentischer Modus)
Du hast direkten Zugriff auf das Projektverzeichnis über Werkzeuge:
- `list_files` / `read_file`: Verschaffe dir IMMER zuerst einen Überblick über bestehenden Code, bevor du etwas änderst.
- `write_file`: Für neue Dateien oder vollständige Neuerstellung.
- `edit_file`: Für punktuelle Änderungen an bestehenden Dateien (präziser Patch statt Neuerstellung).
- `search_code`: Um relevante Stellen im Projekt zu finden, ohne jede Datei einzeln zu lesen.
- `run_command` / `run_tests`: Um Abhängigkeiten zu installieren bzw. deine Änderungen wirklich zu verifizieren.

Speichere Code IMMER direkt über write_file/edit_file im Projektverzeichnis – gib ihn nicht nur als Text in
deiner Antwort aus. Deine finale Textantwort soll eine KURZE Zusammenfassung sein (was wurde geschrieben/geändert,
warum, was ist noch offen) – kein erneutes Einfügen des kompletten Codes."""

    def _build_prompt(self, task: AgentTask) -> str:
        """Baut den finalen Prompt token-effizient zusammen mit strikten Sparsamkeits-Regeln."""
        prompt_parts = [
            f"**DEINE AUFGABE:**\n{task.description}\n",
            "**TOKEN-EFFIZIENZ-REGEL:** Antworte hochpräzise, fokussiert und ohne Füllwörter oder Redundanzen. Liefere vollständigen, lauffähigen Code und Fakten in kompakter Markdown-Struktur."
        ]

        if task.context:
            prompt_parts.insert(0, f"**PROJEKT-KONTEXT:**\n{task.context}\n")

        return "\n\n".join(prompt_parts)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id='{self.agent_id}', name='{self.name}', model='{self._llm.model_name}')"
