"""
agents/base_agent.py – Abstrakte Basisklasse für alle Unteragenten

Mit Projektverzeichnis (AgentTask.project_dir) und erlaubten Werkzeugen läuft ein
echter agentischer Loop: Das Modell ruft die Werkzeuge der AgentToolbox über
natives Function-Calling auf und sieht deren reale Ergebnisse.

Ohne project_dir (reine Text-/Synthese-Aufgaben) bleibt der einfache
Ein-Schuss-Aufruf über generate_with_usage() erhalten.
"""

import asyncio
import json
import logging
import re
import time
from abc import ABC, abstractmethod

from config import (
    CONTEXT_COMPACTION_KEEP_ROUNDS,
    CONTEXT_COMPACTION_MIN_CHARS,
    ENABLE_AGENT_WATCHDOG,
    ENABLE_CONTEXT_COMPACTION,
    ENABLE_DEVELOPER_HANDOFF_GATE,
    ENABLE_FORCED_TOOL_CALL,
    MAX_AGENT_TOOL_ITERATIONS,
    MAX_HANDOFF_RETRIES,
    WATCHDOG_MAX_PROMPT_TOKENS,
    WATCHDOG_TASK_TOKEN_CAP,
)
from core.agent_toolbox import AgentToolbox
from core.agent_watchdog import AgentWatchdog
from core.context_compaction import compact_tool_results
from core.handoff_check import HANDOFF_GATE_AGENT_IDS, check_handoff
from core.llm_factory import AgentMessage, GeminiClient, LLMFactory, LLMResponse, require_tool_call
from core.message_bus import AgentResult, AgentTask
from core.model_capability import min_tier_for_agent, pop_capability_floor, push_capability_floor
from core.provider_exhaustion import FAILURE_CLASS_AGENT_ERROR, classify_failure, is_infrastructure_failure
from core.workspace import extract_file_blocks, text_has_extractable_file_blocks

logger = logging.getLogger(__name__)

# Provider lehnen einen Request mit 400 ab, wenn das Modell ein Werkzeug aufruft, das gar nicht
# im deklarierten Tool-Set steht. Bewusst nur an dieser konkreten Signatur erkannt, damit echte
# Rate-Limit-/Auth-Fehler nicht mitgefangen und blind wiederholt werden – die haben eigene
# Behandlung in core/llm_factory.py (Cooldown/Fallback-Kette).
_DISALLOWED_TOOL_CALL_ERROR_MARKERS = (
    "tool_use_failed",
    "which was not in request.tools",
)


def _is_disallowed_tool_call_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _DISALLOWED_TOOL_CALL_ERROR_MARKERS)


# Rollen, deren Auftrag echte Artefakte im Projekt hinterlassen muss (nicht nur Planungs-/
# Analyse-Text). Grundlage für das "Hard Delivery Gate" unten: ein Lauf ohne eine einzige
# gespeicherte Datei sieht im Report sonst wie ein Erfolg aus, obwohl der Tokenverbrauch
# verpufft ist. Bewusst nur Rollen mit eindeutigem Artefakt-Auftrag, um Fehlalarme zu
# vermeiden; compliance/code_reviewer fehlen absichtlich, weil ihr Befund-TEXT vom
# Governance-Fix-Loop direkt aus AgentResult.content konsumiert wird.
CODE_WRITING_AGENT_IDS = {
    "backend", "frontend", "database", "api_integration", "data_engineer",
    "mobile", "ml", "devops", "tester", "resilience_guard", "refactoring",
    "readme", "documentation", "security", "performance",
}

# Ziel-Dateivorschlag je Analyse-Rolle für den Korrektur-Hinweis unten: ein generischer
# "ruf write_file auf" lässt das Modell raten, WELCHE Datei gemeint ist.
_ANALYSIS_AGENT_TARGET_FILES = {
    "security": "docs/SECURITY_AUDIT.md",
    "compliance": "docs/COMPLIANCE_REPORT.md",
    "code_reviewer": "docs/CODE_REVIEW.md",
    "documentation": "README.md",
}


def _analysis_target_file_hint(agent_id: str) -> str:
    """Nennt Analyse-Rollen im Hard-Delivery-Gate-Hinweis explizit ihre Zieldatei."""
    target = _ANALYSIS_AGENT_TARGET_FILES.get(agent_id)
    if not target:
        return ""
    return f" Speichere deine Analyse jetzt SOFORT per write_file(\"{target}\", ...)."

# Erkennt den ADR-Abschnitt, den das feste Ausgabeformat von agents/architect_agent.py verlangt.
# Für architect ist ein Codeblock-Check (wie bei CODE_WRITING_AGENT_IDS) untauglich, da er
# legitim Code-Fences für Mermaid-Diagramme liefert, ohne eine Datei schreiben zu müssen.
_ADR_TEXT_MARKERS = ("Technologie-Entscheidung", "Architektur-Entscheidung", "ADR")

# Fällt ein Codeblock ohne jeden Dateipfad-Anker an, erkennt ihn core/workspace.py nicht. Nur für
# die frontend-Rolle ist das Ziel eindeutig erratbar: ein Fence mit vollständigem HTML-Dokument
# ist praktisch immer die Haupt-UI-Seite.
_GENERIC_FENCE_RE = re.compile(r'```([a-zA-Z0-9_\-]*)\r?\n(.*?)```', re.DOTALL)
_HTML_DOCUMENT_MARKERS = ("<!doctype html", "<html")


def _extract_recoverable_frontend_html(text: str) -> str | None:
    """Erster Fence-Block in `text`, der wie ein vollständiges HTML-Dokument aussieht - sonst
    None. Nur als letzte Rettungsstufe, wenn `extract_file_blocks()` bereits leer zurückkam."""
    for _lang, content in _GENERIC_FENCE_RE.findall(text):
        lowered = content.strip().lower()
        if lowered and any(lowered.startswith(marker) or f"\n{marker}" in lowered for marker in _HTML_DOCUMENT_MARKERS):
            return content
    return None


def _frontend_html_target_path(toolbox: AgentToolbox) -> str:
    """Zielpfad für einen geretteten HTML-Block: folgt der im Projekt etablierten Konvention
    (`static/` vs. `public/`), statt blind immer denselben Pfad zu wählen."""
    if (toolbox.project_dir / "static").is_dir():
        return "static/index.html"
    return "public/index.html"


class BaseAgent(ABC):
    """
    Abstrakte Basisklasse für alle Unteragenten des KI-Teams.
    """

    def __init__(self, agent_id: str, name: str, model_name: str | None = None):
        self.agent_id = agent_id
        self.name = name
        self._llm: GeminiClient = LLMFactory.create_for_agent(agent_id) if not model_name \
            else LLMFactory.create_gemini(model_name)
        # Mindest-Modellstufe für kritische Rollen (core/model_capability.py): verhindert, dass
        # Fallback-Ketten Architektur-/Security-Aufgaben still auf ein Lite-Modell abstufen.
        self._min_tier = min_tier_for_agent(agent_id, self._llm.model_name)

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
        floor_tokens = push_capability_floor(self._min_tier, owner=self.agent_id)

        try:
            from memory.agent_knowledge_base import agent_knowledge_base

            # Cache-stabile Reihenfolge: STATISCHE Bestandteile zuerst, VOLATILE zuletzt.
            # Prompt-Caching greift nur über ein gemeinsames Präfix - stünden die Learnings
            # (ändern sich bei jeder neuen Lernregel) vor dem Werkzeugkatalog, würde dieser
            # unverändert große Block bei jeder Regeländerung mit aus dem Cache fallen.
            hard_delivery_gate_failed = False
            if use_tools:
                toolbox = AgentToolbox(project_dir=task.project_dir, agent_id=self.agent_id, read_only=task.tools_read_only)
                stable_prompt = self._augment_with_tool_instructions(self.system_prompt, read_only=task.tools_read_only)
                effective_system_prompt = agent_knowledge_base.get_augmented_prompt(self.agent_id, stable_prompt)
                response, prompt_tokens, completion_tokens, hard_delivery_gate_failed = await self._run_agentic_loop(
                    task=task, toolbox=toolbox, system_prompt=effective_system_prompt,
                )
            else:
                # Ohne Werkzeuge gibt es keinen Werkzeugkatalog - der Basis-Prompt ist hier
                # bereits das stabile Präfix, die Learnings hängen wie oben hinten an.
                effective_system_prompt = agent_knowledge_base.get_augmented_prompt(
                    self.agent_id, self.system_prompt,
                )
                prompt = self._build_prompt(task)
                response = await self._llm.generate_with_usage(prompt, effective_system_prompt)
                prompt_tokens, completion_tokens = response.prompt_tokens, response.completion_tokens

            duration = time.monotonic() - start_time
            # Hard Delivery Gate: ein Code-schreibender Agent, der trotz Korrektur-Retry in
            # _run_agentic_loop() keine einzige Datei speichert, gilt nie als success=True -
            # sonst hält der Orchestrator den Schritt für fertig. success=False lässt den Step
            # in die reguläre Eskalation/den Fix-Loop laufen (agents/orchestrator/verification.py).
            if hard_delivery_gate_failed:
                return AgentResult(
                    task_id=task.task_id,
                    agent_id=self.agent_id,
                    agent_name=self.name,
                    success=False,
                    content=response.text,
                    error=(
                        "Hard Delivery Gate: Agent hat trotz Korrektur-Hinweis keine einzige Datei "
                        "über write_file/edit_file gespeichert - der Tokenverbrauch ist verpufft."
                    ),
                    duration_seconds=duration,
                    model_used=response.model_name,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                    files_written=[],
                    tool_calls_count=toolbox.call_count if toolbox else 0,
                    failure_class=FAILURE_CLASS_AGENT_ERROR,
                    needs_human_input=bool(toolbox and toolbox.clarification_requests),
                    clarification_questions=list(toolbox.clarification_requests) if toolbox else [],
                )
            if toolbox is not None and not task.tools_read_only and toolbox.files_written:
                self._record_team_handoff(task, toolbox, response.text)
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
                needs_human_input=bool(toolbox and toolbox.clarification_requests),
                clarification_questions=list(toolbox.clarification_requests) if toolbox else [],
                context_chars_compacted=toolbox.context_chars_compacted if toolbox else 0,
                watchdog_events=list(toolbox.watchdog_events) if toolbox else [],
            )

        except Exception as e:
            duration = time.monotonic() - start_time
            # Bei Infrastruktur-Ausfällen (fehlender API-Key, erschöpftes Kontingent) bleibt
            # `model_used` leer: scheiterte der Call, bevor überhaupt ein Provider antwortete,
            # darf das nur konfigurierte, nie kontaktierte Modell keine Fehlerstatistik erben.
            failure_class = classify_failure(str(e))
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.agent_id,
                agent_name=self.name,
                success=False,
                content="",
                error=str(e),
                duration_seconds=duration,
                model_used="" if is_infrastructure_failure(failure_class) else self._llm.model_name,
                failure_class=failure_class,
                files_written=sorted(toolbox.files_written) if toolbox else [],
                tool_calls_count=toolbox.call_count if toolbox else 0,
                needs_human_input=bool(toolbox and toolbox.clarification_requests),
                clarification_questions=list(toolbox.clarification_requests) if toolbox else [],
            )
        finally:
            pop_capability_floor(floor_tokens)

    async def _attempt_auto_recovery_save(self, toolbox: AgentToolbox, response_text: str) -> list[str]:
        """
        Rettet fertigen Code, den der Agent nur als Markdown-Codeblock in den Antworttext
        geschrieben hat, statt write_file aufzurufen. Gespeichert wird über denselben
        validierten write_file-Pfad wie bei einem echten Tool-Aufruf (inkl. Syntax-/Manifest-
        Prüfung), damit der Hard Delivery Gate nicht für tatsächlich gelieferten Code feuert.

        Erkennt zwei Formate:
        1. Ein Dateipfad-Anker vor dem Codeblock (core/workspace.py.extract_file_blocks).
        2. Nur für den frontend-Agenten, wenn (1) nichts fand: ein Fence mit vollständigem
           HTML-Dokument ohne Pfad-Hinweis (siehe _frontend_html_target_path).
        """
        recovered_paths: list[str] = []
        blocks = extract_file_blocks(response_text)
        if not blocks and self.agent_id == "frontend":
            html_content = _extract_recoverable_frontend_html(response_text)
            if html_content:
                blocks = {_frontend_html_target_path(toolbox): html_content}

        for path, content in blocks.items():
            result = await toolbox.dispatch("write_file", {"path": path, "content": content})
            if "error" in result:
                logger.warning(
                    "[Auto-Recovery] Codeblock für '%s' aus Chat-Antwort erkannt, aber Speichern "
                    "abgelehnt: %s", path, result["error"],
                )
                continue
            recovered_paths.append(path)
            logger.info(
                "[Auto-Recovery] Code-Block aus Chat-Antwort extrahiert und als %s gespeichert.", path,
            )
        return recovered_paths

    async def _run_agentic_loop(
        self,
        task: AgentTask,
        toolbox: AgentToolbox,
        system_prompt: str,
    ) -> tuple[LLMResponse, int, int, bool]:
        """
        Der echte Werkzeug-Loop: Modell antwortet entweder mit finalem Text ODER
        mit angeforderten Werkzeug-Aufrufen. Werkzeug-Aufrufe werden ausgeführt,
        ihr reales Ergebnis wird als Folge-Nachricht zurückgespielt, bis das
        Modell eine finale Textantwort liefert oder das Iterationslimit erreicht ist.

        Der Provider wird pro Aufgabe festgenagelt, sobald ein Fallback-Hop geantwortet hat
        (`active_llm`): Ein Providerwechsel mitten in der Historie scheitert, weil die
        Werkzeug-Aufrufe des einen Providers für den nächsten ungültig sind (z.B. Gemini
        verlangt eine thought_signature, die ein fremder function_call nicht hat). Einmal
        gepinnt, ist kein weiterer Fallback mehr erlaubt (_allow_self_fallback=False) - ein
        sichtbarer Fehlschlag ist besser als eine still beschädigte Historie.
        """
        max_iterations = task.max_tool_iterations or MAX_AGENT_TOOL_ITERATIONS
        initial_prompt = self._build_prompt(task)

        # Dateibaum einmalig voranstellen, statt darauf zu vertrauen, dass das Modell zuerst
        # list_files aufruft: spart eine Loop-Iteration und verhindert, dass ein Agent eine von
        # einem Kollegen bereits geschriebene Datei unter anderem Namen doppelt implementiert.
        existing_files = await toolbox.list_files_snapshot()
        if existing_files:
            initial_prompt += (
                "\n\n**BEREITS VORHANDENE DATEIEN IM PROJEKT (von dir oder Teamkollegen):**\n"
                + "\n".join(f"- {f}" for f in existing_files)
                + "\n\nPrüfe VOR jedem write_file, ob die gewünschte Funktionalität hier bereits "
                "(ggf. unter anderem Dateinamen) existiert. Erweitere/nutze bestehenden Code statt "
                "eine zweite, parallele Implementierung derselben Sache anzulegen."
            )

        board_view = self._team_board_view(task)
        if board_view:
            initial_prompt += "\n\n" + board_view

        turns: list[AgentMessage] = [AgentMessage(role="user", text=initial_prompt)]

        total_prompt_tokens = 0
        total_completion_tokens = 0
        response: LLMResponse | None = None
        active_llm = self._llm
        disallowed_tool_call_retry_used = False
        no_file_written_retry_used = False
        no_adr_call_retry_used = False
        hard_delivery_gate_failed = False
        # `hard_limit` ist die tatsächliche Abbruchgrenze der Schleife (nicht `max_iterations`):
        # Ein Code-schreibender Agent ohne gespeicherte Datei bekommt in der letzten Iteration
        # statt des Werkzeug-Verbots die Aufforderung, JETZT write_file aufzurufen - sonst
        # würde ihn das Werkzeug-Verbot in reinen Text drängen und der Hard Delivery Gate
        # bestrafte ihn für genau das. Genau EINE Rettungs-Iteration pro Aufgabe
        # (`write_rescue_grant_used`), damit die Schleife garantiert terminiert.
        hard_limit = max_iterations
        write_rescue_grant_used = False
        watchdog = AgentWatchdog(
            agent_id=self.agent_id,
            code_writing=self.agent_id in CODE_WRITING_AGENT_IDS and not task.tools_read_only,
            max_prompt_tokens=WATCHDOG_MAX_PROMPT_TOKENS,
            task_token_cap=WATCHDOG_TASK_TOKEN_CAP,
        ) if ENABLE_AGENT_WATCHDOG else None
        # Übergabe-Prüfung (core/handoff_check.py): wie oft der Agent bereits aufgefordert wurde,
        # statische Fehler in seinen eigenen Dateien vor der Abgabe zu beheben.
        handoff_retries_used = 0

        iteration = 0
        while iteration < hard_limit:
            iteration += 1
            rescue_applicable = False
            if (
                iteration == max_iterations - 1
                and max_iterations > 2
                and self.agent_id in CODE_WRITING_AGENT_IDS
                and not toolbox.files_written
                and not task.tools_read_only
                and not toolbox.clarification_requests
            ):
                # "Write First"-Vorwarnung eine Iteration vor der erzwungenen Textantwort: der
                # "keine Datei geschrieben"-Retry weiter unten greift nur, wenn der Agent von
                # sich aus vorzeitig mit Text abschließt. Bleibt er bis zuletzt im Tool-Loop,
                # ist dies seine einzige Chance, doch noch write_file aufzurufen.
                turns.append(AgentMessage(
                    role="user",
                    text=(
                        "WARNUNG: Du hast bisher noch KEINE Datei über write_file/edit_file "
                        "gespeichert. Nur noch EINE Werkzeug-Iteration steht dir zur Verfügung, "
                        "bevor du zwingend nur noch Text liefern darfst. Rufe JETZT write_file "
                        "für deine wichtigste Zieldatei auf - reines Lesen reicht ab hier nicht "
                        "mehr aus." + _analysis_target_file_hint(self.agent_id)
                    ),
                ))
            if iteration == hard_limit and max_iterations > 1:
                # Ein Code-schreibender Agent ohne gespeicherte Datei bekommt hier statt des
                # Werkzeug-Verbots die zwingende Aufforderung zum write_file-Aufruf;
                # `write_rescue_grant_used` gewährt dafür einmalig eine zusätzliche Iteration
                # (siehe `hard_limit`-Erhöhung nach dem LLM-Call).
                rescue_applicable = (
                    not write_rescue_grant_used
                    and self.agent_id in CODE_WRITING_AGENT_IDS
                    and not toolbox.files_written
                    and not task.tools_read_only
                    and not toolbox.clarification_requests
                )
                if rescue_applicable:
                    turns.append(AgentMessage(
                        role="user",
                        text=(
                            "Dies ist deine LETZTE Gelegenheit zu antworten - du hast aber bisher "
                            "noch KEINE Datei über write_file/edit_file gespeichert. Rufe JETZT "
                            "zwingend write_file (oder edit_file) für deine wichtigste Zieldatei "
                            "auf - dein Code im reinen Antworttext wird NICHT als Lieferung "
                            "gewertet. Danach darfst du noch kurz zusammenfassen."
                        ),
                    ))
                else:
                    # Ein Werkzeug-Aufruf in der letzten Iteration würde unten verworfen (die
                    # Schleife bricht ab, bevor er ausgeführt wird) und der Nutzer sähe nur die
                    # generische "Maximale Werkzeug-Iterationen erreicht"-Notiz. Die explizite
                    # Aufforderung erhöht die Chance auf eine echte finale Antwort.
                    turns.append(AgentMessage(
                        role="user",
                        text=(
                            "Dies ist deine LETZTE Gelegenheit zu antworten. Rufe KEIN weiteres "
                            "Werkzeug mehr auf – liefere jetzt deine finale Textantwort basierend "
                            "auf allem, was du bisher gesehen hast."
                        ),
                    ))

            allow_fallback = active_llm is self._llm
            if ENABLE_CONTEXT_COMPACTION:
                compaction = compact_tool_results(
                    turns, keep_recent_rounds=CONTEXT_COMPACTION_KEEP_ROUNDS, min_chars=CONTEXT_COMPACTION_MIN_CHARS,
                )
                toolbox.context_chars_compacted += compaction.chars_saved
            # Code-Rollen ohne bisher gespeicherte Datei: in der ersten Iteration und in der
            # Rettungs-Iteration ist ein Werkzeug-Aufruf Pflicht (core/llm_factory.require_tool_call).
            force_tool_call = (
                ENABLE_FORCED_TOOL_CALL
                and self.agent_id in CODE_WRITING_AGENT_IDS
                and not task.tools_read_only
                and not toolbox.files_written
                and not toolbox.clarification_requests
                and ((iteration == 1 and hard_limit > 1) or rescue_applicable)
            )
            try:
                with require_tool_call(force_tool_call):
                    response = await active_llm.generate_with_tools(
                        turns, system_prompt, toolbox.tool_specs(), _allow_self_fallback=allow_fallback,
                    )
            except Exception as e:
                # Ein Retry verbraucht die aktuelle Iteration mit - auf der letzten erlaubten
                # NICHT mehr retryen, sonst bliebe `response` None (siehe assert unten). Echte
                # Rate-Limit-/Auth-Fehler werden bewusst nicht gefangen (eigene Behandlung in
                # core/llm_factory.py).
                if iteration < hard_limit and not disallowed_tool_call_retry_used and _is_disallowed_tool_call_error(e):
                    disallowed_tool_call_retry_used = True
                    turns.append(AgentMessage(
                        role="user",
                        text=(
                            "HINWEIS: Dein letzter Versuch wurde vom Provider abgelehnt, weil "
                            "ein nicht verfügbares Werkzeug aufgerufen wurde. Nutze "
                            "AUSSCHLIESSLICH die dir bereitgestellten Werkzeuge oder antworte "
                            "direkt mit Text, falls du keines benötigst."
                        ),
                    ))
                    continue
                raise

            total_prompt_tokens += response.prompt_tokens
            total_completion_tokens += response.completion_tokens

            if allow_fallback and response.model_name != self._llm.model_name:
                active_llm = LLMFactory.create_for_model(response.model_name)

            if rescue_applicable and response.tool_calls and not write_rescue_grant_used:
                # Der Agent ist der Rettungs-Aufforderung gefolgt: `hard_limit` wird genau einmal
                # pro Aufgabe erhöht, damit der Aufruf unten wirklich ausgeführt wird und danach
                # noch eine finale Textantwort möglich ist.
                write_rescue_grant_used = True
                hard_limit += 1

            if not response.tool_calls or iteration == hard_limit:
                if not response.text and response.tool_calls:
                    # Modell hat im letzten erlaubten Schritt nur Werkzeuge angefordert,
                    # aber keinen Abschlusstext geliefert -> ehrliche Notiz statt leerer Antwort.
                    files_note = ", ".join(sorted(toolbox.files_written)) or "keine"
                    response.text = (
                        f"⚠️ Maximale Werkzeug-Iterationen ({hard_limit}) erreicht, bevor eine finale "
                        f"Zusammenfassung generiert wurde. Bisher geschriebene/geänderte Dateien: {files_note}."
                    )
                elif (
                    not response.tool_calls
                    and iteration < hard_limit
                    and not no_file_written_retry_used
                    and self.agent_id in CODE_WRITING_AGENT_IDS
                    and not toolbox.files_written
                    and not task.tools_read_only
                    and not toolbox.clarification_requests
                ):
                    # Hard Delivery Gate, erste Stufe: JEDER Abschluss eines Code-schreibenden
                    # Agenten ohne eine einzige gespeicherte Datei wird verwarnt, unabhängig vom
                    # Antworttext (ein Code-Fence-Check greift zu kurz - Abschlüsse mit reinem
                    # Planungstext kommen genauso vor). `not task.tools_read_only` schließt
                    # legitime Nur-Lese-Aufträge aus, `not toolbox.clarification_requests`
                    # legitime Rückfragen. Bleibt es beim Nichts-Geschrieben, eskaliert der
                    # Post-Loop-Gate in execute() zu success=False.
                    no_file_written_retry_used = True
                    turns.append(AgentMessage(role="assistant", text=response.text, tool_calls=[]))
                    # Analyse-Rollen bekommen die konkrete Zieldatei genannt statt der generischen
                    # "Code verpufft"-Formulierung, die für Analysetext unpassend ist.
                    analysis_hint = _analysis_target_file_hint(self.agent_id)
                    if analysis_hint:
                        gate_hint_text = (
                            "FEHLER: Du hast wertvolle Analyse geliefert, aber kein Dateitool "
                            "aufgerufen." + analysis_hint + " Erst danach eine kurze "
                            "Abschlusszusammenfassung."
                        )
                    else:
                        gate_hint_text = (
                            "FEHLER: Du bist ein Code-schreibender Agent, hast aber keine einzige "
                            "Datei über write_file/edit_file gespeichert. Dein Code verpufft! "
                            "Speichere den Code jetzt zwingend mit write_file/edit_file – erst "
                            "danach eine kurze Abschlusszusammenfassung."
                        )
                    turns.append(AgentMessage(role="user", text=gate_hint_text))
                    continue
                elif (
                    not response.tool_calls
                    and iteration < hard_limit
                    and not no_adr_call_retry_used
                    and self.agent_id == "architect"
                    and not toolbox.files_written
                    and any(marker in response.text for marker in _ADR_TEXT_MARKERS)
                ):
                    # Eigene Heuristik für architect, da das Gate oben für ihn nicht gilt (er
                    # schreibt normalerweise keine Projektdateien): Die Antwort nennt
                    # Technologie-/Architektur-Entscheidungen (_ADR_TEXT_MARKERS), aber
                    # files_written ist leer - nicht mal ein ADR wurde dokumentiert.
                    no_adr_call_retry_used = True
                    turns.append(AgentMessage(role="assistant", text=response.text, tool_calls=[]))
                    turns.append(AgentMessage(
                        role="user",
                        text=(
                            "Deine Antwort beschreibt Technologie-/Architektur-Entscheidungen, "
                            "aber du hast noch KEIN ADR über das Werkzeug "
                            "record_architecture_decision dokumentiert. Rufe es JETZT für jede "
                            "Entscheidung mit einer echten Alternative auf – erst danach eine "
                            "kurze Abschlusszusammenfassung."
                        ),
                    ))
                    continue
                elif (
                    not response.tool_calls
                    and ENABLE_DEVELOPER_HANDOFF_GATE
                    and handoff_retries_used < MAX_HANDOFF_RETRIES
                    and self.agent_id in HANDOFF_GATE_AGENT_IDS
                    and toolbox.files_written
                    and not task.tools_read_only
                    and not toolbox.clarification_requests
                    and (handoff := await self._run_handoff_check(task, toolbox)) is not None
                    and not handoff.passed
                ):
                    # "Nur grün abgeben": statische Fehler in den EIGENEN Dateien (Syntax, Import
                    # auf nicht existierendes lokales Modul) behebt der Agent noch innerhalb seiner
                    # Aufgabe, statt sie als Pre-Flight-Fund an eine spätere Fix-Runde zu vererben.
                    # Jede Aufforderung gewährt zwei echte Zusatz-Iterationen, begrenzt durch
                    # MAX_HANDOFF_RETRIES - die Schleife terminiert damit garantiert.
                    handoff_retries_used += 1
                    hard_limit = max(hard_limit, iteration + 2)
                    turns.append(AgentMessage(role="assistant", text=response.text, tool_calls=[]))
                    turns.append(AgentMessage(role="user", text=handoff.format_for_agent()))
                    continue
                gate_retry_exhausted = (
                    self.agent_id in CODE_WRITING_AGENT_IDS
                    and not toolbox.files_written
                    and not task.tools_read_only
                    and not toolbox.clarification_requests
                    and (
                        no_file_written_retry_used
                        or (iteration == hard_limit and max_iterations > 1 and not response.tool_calls)
                    )
                )
                if gate_retry_exhausted:
                    # Letzter Rettungsversuch, bevor das Gate unten endgültig fehlschlägt:
                    # gelingt er, ist `toolbox.files_written` danach nicht mehr leer und die
                    # folgende Bedingung greift gar nicht erst.
                    await self._attempt_auto_recovery_save(toolbox, response.text)
                if (
                    gate_retry_exhausted
                    and not toolbox.files_written
                    and not text_has_extractable_file_blocks(response.text)
                ):
                    # Hard Delivery Gate, zweite Stufe: der Korrektur-Hinweis wurde bereits
                    # gegeben und der Agent liefert trotzdem keine Datei - execute() wertet das
                    # nie als success=True, damit der Orchestrator sofort eskaliert.
                    #
                    # `gate_retry_exhausted` deckt zusätzlich den Fall ab, dass der Agent alle
                    # Iterationen mit Tool-Aufrufen (z.B. nur read_file) verbrachte und erst in
                    # der erzwungenen Text-Iteration ohne Datei abschloss - dort kam der Retry
                    # oben (verlangt `iteration < hard_limit`) nie zum Zug. Bewusst ausgenommen:
                    # `max_iterations == 1` (nie eine reale Korrekturchance) und ein aktiver
                    # Werkzeug-Aufruf in der letzten Iteration (ehrlicher Abbruch mangels Zeit).
                    #
                    # `not text_has_extractable_file_blocks(...)`: enthält der Antworttext einen
                    # Codeblock, den der orchestrator-weite Text-Fallback (AUTO_SAVE_WORKSPACE)
                    # noch speichern würde, ist nichts verpufft - der greift aber nur für
                    # `res.success`, also darf das Gate ihn nicht vorher abwürgen.
                    hard_delivery_gate_failed = True
                break

            turns.append(AgentMessage(role="assistant", text=response.text, tool_calls=response.tool_calls))
            iteration_results: list[dict] = []
            for tool_call in response.tool_calls:
                result = await toolbox.dispatch(tool_call.name, tool_call.arguments)
                iteration_results.append(result)
                turns.append(AgentMessage(
                    role="tool",
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    text=json.dumps(result, ensure_ascii=False),
                ))

            if watchdog is not None:
                for intervention in watchdog.observe(
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    tool_calls=[(tc.name, tc.arguments) for tc in response.tool_calls],
                    tool_results=iteration_results,
                    files_written_count=len(toolbox.files_written),
                ):
                    if intervention.compact:
                        toolbox.context_chars_compacted += compact_tool_results(
                            turns, keep_recent_rounds=1, min_chars=500,
                        ).chars_saved
                    if intervention.stop:
                        hard_limit = min(hard_limit, iteration + 1)
                    turns.append(AgentMessage(role="user", text=intervention.message))
                toolbox.watchdog_events = list(watchdog.events)

        assert response is not None
        return response, total_prompt_tokens, total_completion_tokens, hard_delivery_gate_failed

    def _team_board_view(self, task: AgentTask) -> str:
        """Aktuelle Team-Board-Sicht (core/team_board.py) für den Start dieser Aufgabe."""
        from config import ENABLE_TEAM_BOARD, TEAM_BOARD_PROMPT_CHARS
        if not ENABLE_TEAM_BOARD or not task.project_dir:
            return ""
        try:
            from core.team_board import format_for_agent
            return format_for_agent(task.project_dir, self.agent_id, max_chars=TEAM_BOARD_PROMPT_CHARS)
        except Exception as e:  # noqa: BLE001 - Board-Sicht ist Zusatzkontext, nie ein Blocker
            logging.getLogger(__name__).warning("Team-Board-Sicht für %s nicht verfügbar: %r", self.agent_id, e)
            return ""

    def _record_team_handoff(self, task: AgentTask, toolbox: AgentToolbox, response_text: str) -> None:
        """Legt die Übergabe-Notiz auf das Team-Board: Dateien, gelieferte Symbole/Routen, Bedarf, Offenes."""
        from config import ENABLE_TEAM_BOARD
        if not ENABLE_TEAM_BOARD or not task.project_dir:
            return
        try:
            from core.team_board import Handoff, derive_provides, parse_handoff_note, record_handoff
            files = sorted(toolbox.files_written)
            note = parse_handoff_note(response_text) or {}
            provides = list(note.get("provides", [])) + derive_provides(task.project_dir, files)
            record_handoff(task.project_dir, Handoff(
                agent_id=self.agent_id, task_id=task.task_id, files=files, provides=provides,
                requires=list(note.get("requires", [])), open_issues=list(note.get("open_issues", [])),
            ))
        except Exception as e:  # noqa: BLE001 - Übergabe-Notiz darf ein Ergebnis nie gefährden
            logging.getLogger(__name__).warning("Übergabe-Notiz von %s nicht gespeichert: %r", self.agent_id, e)

    async def _run_handoff_check(self, task: AgentTask, toolbox: AgentToolbox):
        """Führt die Übergabe-Prüfung aus - ein interner Fehler darf die Abgabe nie blockieren."""
        try:
            return await asyncio.to_thread(check_handoff, task.project_dir, set(toolbox.files_written))
        except Exception as e:  # noqa: BLE001 - reine Qualitätshilfe, kein Blocker
            logger.warning("Übergabe-Prüfung für %s fehlgeschlagen: %r", self.agent_id, e)
            return None

    def _augment_with_tool_instructions(self, system_prompt: str, read_only: bool = False) -> str:
        # Bei kleinen Aufgaben wird architect oft gar nicht eingeplant; Code-schreibende Rollen
        # treffen Technologie-Entscheidungen dann selbst, ohne sie zu dokumentieren. Zweite
        # Verteidigungslinie zur decompose()-Regel - nur für diese Rollen, da z.B.
        # copywriter/i18n legitim keine Architektur-Entscheidungen treffen.
        adr_note = (
            "\n\nTriffst du dabei eine Entscheidung mit einer echten Alternative (z.B. "
            "'PostgreSQL statt In-Memory-Liste', 'REST statt GraphQL'), dokumentiere sie "
            "ZUSÄTZLICH über das Werkzeug `record_architecture_decision` – nicht nur in "
            "deiner Zusammenfassung, sonst ist sie beim nächsten Lauf an diesem Projekt "
            "bereits wieder vergessen."
            if self.agent_id in CODE_WRITING_AGENT_IDS else ""
        )
        # Ohne diesen Hinweis fragen Nur-Lese-Rollen per `ask_human_for_clarification` nach
        # Schreibrechten - eine Frage, die nie beantwortet wird, obwohl der Governance-Fix-Loop
        # (agents/orchestrator/verification.py) kritische Funde ohnehin automatisch weiterreicht.
        # Macht den Schreibzugriff für beide Fälle explizit.
        write_access_note = (
            "\n\n⚠️ WICHTIG: Du hast in dieser Aufgabe KEINEN Schreibzugriff (nur `list_files`/`read_file`/"
            "`search_code`). Ein gefundenes Problem, das Code-Änderungen braucht, behebst du NICHT selbst und "
            "fragst dafür AUCH NICHT über `ask_human_for_clarification` nach Schreibrechten - das ist keine "
            "echte Unklarheit, sondern eine bewusste Rollentrennung. Melde es stattdessen wie gewohnt in deinem "
            "Bericht mit klarer Schweregrad-Markierung (z.B. \"Kritisch\"); ein separater, automatischer "
            "Mechanismus liest kritische Funde aus deinem Bericht und beauftragt gezielt den zuständigen "
            "schreibberechtigten Agenten mit der Korrektur."
            if read_only else
            "\n\n⚠️ WICHTIG: Du hast in dieser Aufgabe vollen Schreibzugriff (`write_file`/`edit_file`). Findest "
            "du ein konkretes, technisch behebbares Problem im Code, behebe es DIREKT selbst über diese "
            "Werkzeuge - frage NICHT per `ask_human_for_clarification` nach Schreibrechten, die du bereits hast."
        )
        # Macht "fehlende Struktur selbst anlegen" proaktiv zum Standardverhalten. Die
        # reaktive Korrektur nach dem Lauf (_run_scope_clarification_autofix) kostet sonst
        # jedes Mal eine komplette zusätzliche Fix-Runde. Nur für code-schreibende Rollen,
        # für die eine leere Struktur eine sinnvolle Handlungsanweisung ist.
        empty_scope_note = (
            "\n\n⚠️ WICHTIG: Findest du nicht die erwartete Projektstruktur vor (z.B. kein `app/`-Verzeichnis, "
            "leeres Projektverzeichnis, referenzierte Dateien fehlen komplett), obwohl der Auftrag von "
            "bestehendem Code ausgeht ('repariere', 'erweitere', 'teste X') - frage NICHT per "
            "`ask_human_for_clarification` nach, ob du sie neu anlegen darfst. Es ist kein Mensch anwesend, der "
            "das in Echtzeit beantworten könnte. Lege die fehlende Grundstruktur selbst an und erledige die "
            "Aufgabe darauf vollständig; dokumentiere die getroffene Annahme kurz (z.B. als Kommentar oder "
            "README-Abschnitt)."
            if self.agent_id in CODE_WRITING_AGENT_IDS else ""
        )
        # Setzt vor dem wiederkehrenden ruff-Fund BLE001 an: ein bewusst breiter
        # `except Exception:` ist oft gewollt, erzeugt aber Dauer-Rauschen im
        # Verifikationsprotokoll und ein Backlog-Ticket, das nie automatisch schließt. Besser
        # gleich spezifischer fangen oder das noqa begründen. Nur für Code-schreibende Rollen.
        exception_handling_note = (
            "\n\n⚠️ FEHLERBEHANDLUNG: Fange NIEMALS pauschal `except Exception:` (oder gar "
            "`except:`) ohne Weiterbehandlung ab, wenn eine spezifischere Exception (z.B. "
            "`except (KeyError, ValueError):`, `except sqlalchemy.exc.IntegrityError:`, "
            "`except httpx.HTTPError:`) die tatsächlich erwartbare Fehlerursache genauer trifft "
            "- ein zu breiter Fang verschluckt echte Programmierfehler (z.B. AttributeError durch "
            "einen Tippfehler) genauso wie die erwartete Ausnahme und macht sie unsichtbar. Ist "
            "ein bewusst breiter Fallback nötig (z.B. ein Hintergrund-Task/Worker-Loop, der bei "
            "JEDEM Fehler robust weiterlaufen muss, statt abzustürzen), ist `except Exception:` "
            "dafür legitim - kennzeichne ihn dann aber explizit mit einem kurzen Kommentar, WARUM "
            "er bewusst breit ist (z.B. `except Exception:  # noqa: BLE001 - Worker darf nie "
            "abstürzen`), statt ihn unkommentiert stehen zu lassen. So bleibt der Lint-Scan des "
            "Verifikators aussagekräftig, statt bei jedem Lauf denselben bereits bekannten, "
            "bewusst akzeptierten Fund erneut gegen echte neue Funde zu vermischen."
            if self.agent_id in CODE_WRITING_AGENT_IDS else ""
        )
        handoff_note = (
            "\n\n✅ ÜBERGABE-REGEL (wie im echten Team): Bevor du abschließt, muss dein Code importierbar sein. "
            "Existieren Tests für deinen Bereich, führe `run_tests` aus und behebe Fehler in DEINEN Dateien selbst. "
            "Nach deiner Abschlussantwort prüft das System deine Dateien automatisch (Syntax, lokale Importe) und "
            "gibt sie dir bei Fehlern zur Korrektur zurück."
            if self.agent_id in HANDOFF_GATE_AGENT_IDS and not read_only else ""
        )
        team_note = (
            "\n\n🤝 TEAMARBEIT: Oben im Auftrag steht ggf. ein TEAM-BOARD mit den Übergaben deiner Kollegen, "
            "Datei-Ownern und dem Stand des Schnittstellen-Vertrags - richte dich danach. Brauchst du eine "
            "Information, die ein Kollege liefert (Route, Feldname, Signatur), frage ihn per `ask_teammate`, statt "
            "zu raten. Beende deine finale Antwort mit drei Zeilen für die Übergabe:\n"
            "provides: <was du lieferst, z.B. `GET /api/metrics` (app/api/metrics.py); `MetricsService`>\n"
            "requires: <was du von anderen erwartest, mit Datei/Route/`Symbol`, oder: keine>\n"
            "open_issues: <was offen ist, oder: keine>"
            if self.agent_id in CODE_WRITING_AGENT_IDS and not read_only else ""
        )
        return f"""{system_prompt}

## 🛠️ WERKZEUG-NUTZUNG (agentischer Modus)
Du hast direkten Zugriff auf das Projektverzeichnis über Werkzeuge:
- `list_files` / `read_file`: Verschaffe dir IMMER zuerst einen Überblick über bestehenden Code, bevor du etwas änderst.
- `write_file`: Für neue Dateien oder vollständige Neuerstellung.
- `edit_file`: Für punktuelle Änderungen an bestehenden Dateien (präziser Patch statt Neuerstellung).
- `search_code`: Um relevante Stellen im Projekt zu finden, ohne jede Datei einzeln zu lesen.
- `run_command` / `run_tests`: Um Abhängigkeiten zu installieren bzw. deine Änderungen wirklich zu verifizieren.

**WICHTIG: Gib keinen Quellcode als reine Chat-Nachricht aus. Du MUSST das Werkzeug `write_file(path, content)`
verwenden, um Code zu speichern. Code, der nur im Chat-Text steht, wird vom System verworfen.**

Speichere Code IMMER direkt über write_file/edit_file im Projektverzeichnis – gib ihn nicht nur als Text in
deiner Antwort aus. Schreibe NIEMALS Platzhalter wie `# ...`, `# Rest beibehalten` oder unvollständigen Pseudo-Code;
jede Datei muss zu 100% vollständig und syntaktisch lauffähig sein. Deine finale Textantwort soll eine KURZE
Zusammenfassung sein (was wurde geschrieben/geändert, warum, was ist noch offen) – kein erneutes Einfügen des kompletten Codes.{adr_note}

Triffst du auf eine ECHTE, für die Aufgabe entscheidende Unklarheit, die nur ein Mensch sinnvoll auflösen kann
(nicht: eine übliche technische Entscheidung, die du selbst treffen kannst) – nutze `ask_human_for_clarification`,
statt zu raten und trotzdem etwas möglicherweise Falsches auszuliefern. Ein erfahrener Senior-Entwickler fragt bei
echter Mehrdeutigkeit nach, statt zu spekulieren. Setze deine Arbeit danach so weit wie möglich fort und fasse in
deiner finalen Antwort ehrlich zusammen, was bereits erledigt ist und was durch die Rückfrage offen bleibt.
{write_access_note}{empty_scope_note}{exception_handling_note}{handoff_note}{team_note}"""

    def _build_prompt(self, task: AgentTask) -> str:
        """Baut den finalen Prompt token-effizient zusammen mit strikten Sparsamkeits-Regeln."""
        prompt_parts = [
            f"**DEINE AUFGABE:**\n{task.description}\n",
            "**TOKEN-EFFIZIENZ-REGEL:** Antworte hochpräzise, fokussiert und ohne Füllwörter oder Redundanzen. Liefere vollständigen, lauffähigen Code und Fakten in kompakter Markdown-Struktur."
        ]

        if task.context:
            prompt_parts.insert(0, f"**PROJEKT-KONTEXT:**\n{task.context}\n")
            # ADRs und Schnittstellen-Verträge stecken bereits vollständig im PROJEKT-KONTEXT
            # (siehe agents/orchestrator/department.py); ohne diesen Hinweis laden Agenten
            # dieselben Dateien in den ersten Iterationen nochmal per read_file und verdrängen
            # das eigentliche write_file ans knappe Ende. Nur für Code-schreibende Rollen, da
            # nur deren Aufträge typischerweise ADRs/Contracts im Kontext enthalten.
            if self.agent_id in CODE_WRITING_AGENT_IDS:
                prompt_parts.append(
                    "**KONTEXT-HINWEIS:** Alle ADRs, Schnittstellen-Verträge (`interface_contract.json`) "
                    "und Architekturentscheidungen liegen dir bereits VOLLSTÄNDIG oben im PROJEKT-KONTEXT vor. "
                    "Rufe dafür KEIN read_file mehr auf - das verschwendet Werkzeug-Iterationen und Tokens ohne "
                    "neue Information. Beginne stattdessen bereits in Iteration 1 oder 2 mit write_file für deine "
                    "Zieldatei(en)."
                )

        return "\n\n".join(prompt_parts)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id='{self.agent_id}', name='{self.name}', model='{self._llm.model_name}')"
