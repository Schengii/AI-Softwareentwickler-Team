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
from core.model_capability import min_tier_for_agent, pop_capability_floor, push_capability_floor
from core.provider_exhaustion import FAILURE_CLASS_AGENT_ERROR, classify_failure, is_infrastructure_failure
from core.workspace import text_has_extractable_file_blocks

# Realer Fund aus einem echten Lauf: Groq (häufig der Fallback für HEAVY-Rollen ohne
# ANTHROPIC_API_KEY, siehe config.py) lehnte einen rein lesenden Konsolidierungs-Aufruf
# (tools_read_only=True, also KEIN write_file im deklarierten Tool-Set) hart mit 400 ab,
# weil das Modell selbst trotzdem versuchte, `write_file` aufzurufen – der Request war
# korrekt, nur die Modell-AUSGABE nicht. Bewusst an der konkreten Fehler-Signatur erkannt
# (nicht jede Exception), um echte Rate-Limits/Auth-Fehler NICHT versehentlich mitzufangen
# und blind zu wiederholen – die haben bereits eigene, spezifischere Behandlung
# (core/llm_factory.py Cooldown/Fallback-Kette).
_DISALLOWED_TOOL_CALL_ERROR_MARKERS = (
    "tool_use_failed",
    "which was not in request.tools",
)


def _is_disallowed_tool_call_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _DISALLOWED_TOOL_CALL_ERROR_MARKERS)


# Rollen, deren eigentlicher Auftrag darin besteht, echte Artefakte im Projekt zu hinterlassen
# (nicht nur Planungs-/Analyse-Text). Realer Fund aus einem echten Lauf: der backend-Agent
# meldete success=True, verbrauchte echte 36.000+ Tokens und lieferte fertigen Code – aber
# AUSSCHLIESSLICH als Markdown-Codeblock im Antworttext statt über write_file/edit_file, sodass
# git status danach komplett leer war (0 Dateien geändert). Ohne Gegenmaßnahme sieht ein
# solcher Lauf im Report identisch zu einem echten Erfolg aus und der komplette
# Tokenverbrauch verpufft, ohne dass irgendetwas Nutzbares im Projekt ankommt. Bewusst NUR
# die Rollen mit eindeutigem Artefakt-Auftrag (kein product_owner/architect/ui_ux/etc. –
# deren Aufgabe legitim reiner Text sein kann), um Fehlalarme gering zu halten. Lebt hier
# (nicht in agents/orchestrator.py, das die Konstante nur noch importiert), weil
# _run_agentic_loop() unten sie direkt für einen Korrektur-Retry braucht.
CODE_WRITING_AGENT_IDS = {
    "backend", "frontend", "database", "api_integration", "data_engineer",
    "mobile", "ml", "devops", "tester", "resilience_guard", "refactoring",
    "readme", "documentation", "security", "performance",
}
# HINWEIS (`/goal`-Auftrag, Schwachstelle 3): compliance und code_reviewer werden BEWUSST NICHT
# hier aufgenommen - beide sind laut agents/orchestrator/constants.py.REVIEW_ONLY_AGENT_IDS
# etablierte reine Text-Review-Rollen, deren Befund-Text der Governance-Fix-Loop (agents/
# orchestrator/verification.py._run_governance_fix_loop) direkt aus `AgentResult.content`
# konsumiert, KEIN write_file-Aufruf nötig oder erwartet. Ein Test schützt genau das
# (tests/test_error_visibility.py::test_metrics_summary_does_not_flag_review_only_or_planning_
# roles) - beide hier aufzunehmen würde legitime, dateilose Review-Abschlüsse fälschlich als
# "Hard Delivery Gate"-Fehlschlag markieren.

# Team-Optimierung (`/goal`-Auftrag, Schwachstelle 3): Ziel-Dateivorschlag je Analyse-Rolle für
# den Korrektur-Hinweis unten (_analysis_target_file_hint()) - ein generischer "ruf write_file
# auf"-Hinweis lässt das Modell erneut raten, WELCHE Datei gemeint ist; der konkrete Pfad
# (identisch zu dem, den der jeweilige Agenten-System-Prompt selbst als Standard-Ausgabeziel
# nennt, siehe security_agent.py) nimmt genau dieses Raten weg. compliance/code_reviewer bleiben
# hier trotz der REVIEW_ONLY-Ausnahme oben gelistet, falls ein zukünftiger Aufrufer (außerhalb
# des Hard Delivery Gate) denselben Zieldatei-Hinweis für diese Rollen braucht.
_ANALYSIS_AGENT_TARGET_FILES = {
    "security": "docs/SECURITY_AUDIT.md",
    "compliance": "docs/COMPLIANCE_REPORT.md",
    "code_reviewer": "docs/CODE_REVIEW.md",
    "documentation": "README.md",
}


def _analysis_target_file_hint(agent_id: str) -> str:
    """Rollenspezifischer Zusatzsatz für den Hard-Delivery-Gate-Korrekturhinweis: nennt
    Analyse-Rollen (security/compliance/code_reviewer/documentation) explizit die Zieldatei,
    statt sie nur pauschal zu write_file/edit_file aufzufordern."""
    target = _ANALYSIS_AGENT_TARGET_FILES.get(agent_id)
    if not target:
        return ""
    return f" Speichere deine Analyse jetzt SOFORT per write_file(\"{target}\", ...)."

# Realer Fund aus einem echten End-to-End-Testlauf: architect wurde korrekt eingeplant und
# explizit mit "erstelle ADR" beauftragt (core/task_manager.py DECOMPOSE_SYSTEM_PROMPT-Regel),
# hat aber trotz eigener System-Prompt-Anweisung (agents/architect_agent.py) NIE
# record_architecture_decision aufgerufen - die Entscheidung stand nur im Fließtext. Diese
# Marker erkennen genau den Abschnitt, den architect_agent.py's fixes Ausgabeformat IMMER
# verlangt ("## 6. Technologie-Entscheidungen (ADRs)") - kein Codeblock-Check wie bei
# CODE_WRITING_AGENT_IDS, da architect legitim Code-Fences für Mermaid-Diagramme liefert, ohne
# dass "kein write_file aufgerufen" dort ein Problem wäre.
_ADR_TEXT_MARKERS = ("Technologie-Entscheidung", "Architektur-Entscheidung", "ADR")


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

            # Cache-stabile Reihenfolge (KI-Team-Masterplan, Stufe 3): STATISCHE Bestandteile
            # zuerst, VOLATILE zuletzt.
            #
            # Zuvor lautete die Reihenfolge: Basis-Prompt → Learnings → Werkzeug-Anweisungen. Der
            # Learnings-Block ändert sich aber, sobald der Agent etwas Neues lernt - er stand
            # damit MITTEN im Prompt und entwertete alles, was danach kam. Da Prompt-Caching
            # ausschließlich über ein gemeinsames PRÄFIX funktioniert, wurde dadurch bei jeder
            # neuen Lernregel auch der vollkommen unveränderte, große Werkzeugkatalog aus dem
            # Cache geworfen. Passend dazu der reale Befund: 21,08 Mio. Prompt-Tokens gegenüber
            # 0,84 Mio. Completion-Tokens (25:1) bei nur 12% Cache-Trefferquote.
            #
            # Jetzt: Basis-Prompt + Werkzeug-Anweisungen (beide über viele Läufe hinweg
            # bytegleich) bilden das stabile Präfix, die Learnings hängen hinten an.
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
            # Hard Delivery Gate (KI-Team-Härtung, echter Fund keygate_service-Lauf): ein
            # Code-schreibender Agent, der trotz des expliziten Korrektur-Retries in
            # _run_agentic_loop() KEINE einzige Datei speichert, gilt NIEMALS als success=True -
            # sonst verpufft der komplette Tokenverbrauch unbemerkt und der Orchestrator hält den
            # Schritt für "Fertig!". success=False lässt den Step wie jeden anderen echten
            # Agentenfehler in die reguläre Eskalation/den Fix-Loop laufen (siehe
            # agents/orchestrator/verification.py), statt separat behandelt werden zu müssen.
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
            )

        except Exception as e:
            duration = time.monotonic() - start_time
            # Realer Fund (KI-Team-Masterplan-Analyse): hier stand bisher unbedingt
            # `model_used=self._llm.model_name` - also das KONFIGURIERTE Modell. Scheiterte der
            # Call, BEVOR überhaupt ein Provider antwortete (fehlender API-Key, erschöpftes
            # Tageskontingent), wurde der Fehlschlag damit einem Modell zugeschrieben, das nie
            # einen Call gemacht hat: memory/run_history.json zeigte 160 Fehler unter
            # `claude-sonnet-5`, während memory/cost_history.json für dieses Modell null Calls
            # kennt (ANTHROPIC_API_KEY war leer). Bei Infrastruktur-Ausfällen bleibt das Feld
            # deshalb leer - ein nie kontaktiertes Modell darf keine Fehlerstatistik erben.
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
        disallowed_tool_call_retry_used = False
        no_file_written_retry_used = False
        no_adr_call_retry_used = False
        hard_delivery_gate_failed = False
        # Realer Fund (KI-Team-Gesamtanalyse, hooksentinel-Lauf 12.09.2026, Schwachstelle 2 -
        # "Contradictory Prompt"-Bug): bisher wurde JEDEM Agenten auf der letzten erlaubten
        # Iteration hart verboten, überhaupt noch ein Werkzeug aufzurufen ("Rufe KEIN weiteres
        # Werkzeug mehr auf") - ein Code-schreibender Agent, der bis dahin noch keine Datei
        # gespeichert hatte, schrieb daraufhin brav gehorsam seinen fertigen Code als Text in
        # die Antwort statt über write_file, und wurde direkt im Anschluss vom Hard Delivery
        # Gate unten als fehlgeschlagen markiert - der Agent wurde also für genau das
        # bestraft, was ihm das Framework selbst befohlen hatte (im HookSentinel-Lauf real der
        # Ausfall des Frontend-Entwicklers, 43.401 verpuffte Tokens). `hard_limit` ersetzt
        # `max_iterations` als tatsächliche Abbruchgrenze der Schleife: bleibt ein
        # Code-schreibender Agent bis zur letzten Iteration ohne gespeicherte Datei, wird ihm
        # dort STATT des Werkzeug-Verbots eine zwingende Aufforderung geschickt, JETZT
        # write_file aufzurufen, und `hard_limit` einmalig um eine echte Rettungs-Iteration
        # erhöht, damit ein tatsächlich zurückgegebener Werkzeug-Aufruf nicht wie bisher
        # verworfen, sondern normal ausgeführt wird. Genau EINE solche Verlängerung pro
        # Aufgabe (`write_rescue_grant_used`), damit die Schleife garantiert terminiert.
        hard_limit = max_iterations
        write_rescue_grant_used = False

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
                # "Write First"-Vorwarnung (KI-Team-Gesamtanalyse, Befund 1 im CertPulse-Lauf
                # vom 12.09.2026: ein Code-schreibender Agent verbrachte Iteration 1-4 komplett
                # mit read_file auf bereits im Prompt zusammengefassten ADRs/Interface-Contracts
                # und erreichte danach nur noch die erzwungene reine Textiteration, OHNE dass
                # jemals ein write_file/edit_file-Aufruf stattfand. Die einzige bisherige
                # Korrektur-Chance (der "keine Datei geschrieben"-Retry weiter unten) greift NUR,
                # wenn der Agent von sich aus VORZEITIG mit reinem Text abschließt - bleibt er bis
                # zur letzten Iteration im Tool-Loop, kommt diese Warnung nie zum Zug. Eine
                # zusätzliche, frühere Warnung EINE Iteration vor der erzwungenen Text-Antwort
                # gibt dem Agenten noch eine reale Chance, write_file aufzurufen, BEVOR ihm das
                # Werkzeug in der letzten Iteration verboten wird.
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
                # "Contradictory Prompt"-Bugfix (KI-Team-Gesamtanalyse, hooksentinel-Lauf
                # 12.09.2026): ein Code-schreibender Agent, der bis zur letzten Iteration keine
                # einzige Datei gespeichert hat, darf hier NICHT mehr pauschal jedes Werkzeug
                # verboten bekommen - sonst gehorcht er dem Verbot, schreibt seinen Code als
                # Text in die Antwort, und wird direkt danach vom Hard Delivery Gate unten als
                # fehlgeschlagen markiert (bestraft für einen vom Framework selbst erzwungenen
                # Zustand). Stattdessen wird er zwingend zu genau diesem Werkzeug-Aufruf
                # aufgefordert; `write_rescue_grant_used` gewährt dafür EINMALIG eine echte
                # zusätzliche Iteration (siehe `hard_limit`-Erhöhung unten, nach dem LLM-Call),
                # statt einen tatsächlich zurückgegebenen write_file-Aufruf wie bisher zu
                # verwerfen.
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
                    # Realer Fund: auf der letzten erlaubten Iteration durfte das Modell bisher
                    # weiterhin frei zwischen Werkzeug-Aufruf und Text wählen – entschied es sich
                    # (real beobachtet bei zwei Fachbereichs-Teamleiter-Aufrufen in einem Lauf)
                    # nochmal für ein Werkzeug, wurde dieser Aufruf VERWORFEN (die Schleife bricht
                    # unten ab, bevor er ausgeführt wird) und der Nutzer sah nur die generische
                    # "Maximale Werkzeug-Iterationen erreicht"-Notiz statt einer echten
                    # Zusammenfassung. Eine explizite letzte Aufforderung erhöht die Chance auf
                    # eine echte finale Antwort, statt die Iteration zu verschwenden.
                    turns.append(AgentMessage(
                        role="user",
                        text=(
                            "Dies ist deine LETZTE Gelegenheit zu antworten. Rufe KEIN weiteres "
                            "Werkzeug mehr auf – liefere jetzt deine finale Textantwort basierend "
                            "auf allem, was du bisher gesehen hast."
                        ),
                    ))

            allow_fallback = active_llm is self._llm
            try:
                response = await active_llm.generate_with_tools(
                    turns, system_prompt, toolbox.tool_specs(), _allow_self_fallback=allow_fallback,
                )
            except Exception as e:
                # Ein Retry verbraucht die aktuelle Iteration mit - auf der ohnehin letzten
                # erlaubten Iteration NICHT mehr retryen, sonst bliebe `response` auf None
                # (siehe assert unten). Echte Rate-Limit-/Auth-Fehler haben bereits eigene,
                # spezifischere Behandlung in core/llm_factory.py und werden hier bewusst NICHT
                # gefangen (_is_disallowed_tool_call_error grenzt gezielt ein).
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
                # Der Agent ist der Rettungs-Aufforderung gefolgt und hat tatsächlich ein
                # Werkzeug (hoffentlich write_file/edit_file) aufgerufen, statt wie zuvor in
                # reinen Text auszuweichen. `hard_limit` wird GENAU EINMAL pro Aufgabe erhöht,
                # damit dieser Aufruf unten reell ausgeführt (nicht verworfen) wird und der
                # Agent im Anschluss noch eine echte finale Textantwort liefern kann.
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
                    # "Hard Delivery Gate" (KI-Team-Härtung, echter Fund keygate_service-Lauf:
                    # backend/database/tester verbrauchten 400k+ Tokens, meldeten success=True,
                    # aber toolbox.files_written blieb über die GESAMTE Aufgabe leer – das Projekt
                    # schloss ohne main.py/Tests ab). Ursprünglich griff dieses Gate NUR, wenn
                    # "```" (ein Code-Fence) im Abschlusstext stand - real beobachtet
                    # (pulseflow_gateway, 20260911_095217) schloss ein backend-Agent aber auch
                    # mit reinem Planungs-Fließtext OHNE Fence oder nach einem einzelnen
                    # list_files-Aufruf mit files_written: [] und success: true ab. Das
                    # Fence-Erfordernis wurde deshalb entfernt: JEDER Abschluss eines
                    # Code-schreibenden Agenten ohne eine einzige gespeicherte Datei wird jetzt
                    # verwarnt, unabhängig vom Antworttext. `not task.tools_read_only` schließt
                    # weiterhin legitime Nur-Lese-Aufträge aus (z. B. Governance-Fix-Schleife),
                    # `not toolbox.clarification_requests` legitime Rückfragen mitten in der
                    # Aufgabe (`ask_human_for_clarification`). EIN gezielter Korrektur-Hinweis
                    # statt die Antwort unkorrigiert zu akzeptieren; bleibt es dabei, eskaliert
                    # der Post-Loop-Gate unten in execute() zu success=False, statt den
                    # Fehlschlag als "Fertig!" zu verkaufen.
                    no_file_written_retry_used = True
                    turns.append(AgentMessage(role="assistant", text=response.text, tool_calls=[]))
                    # Bei den Analyse-Rollen (security/compliance/code_reviewer/documentation)
                    # nennt der Hinweis explizit die erwartete Zieldatei statt der generischen
                    # "Code verpufft"-Formulierung, die für reinen Analyse-Fließtext unpassend ist.
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
                    # Realer Fund aus einem echten End-to-End-Testlauf: architect wurde diesmal
                    # (dank der neuen decompose()-Pflichtregel, siehe core/task_manager.py)
                    # korrekt eingeplant UND explizit mit "erstelle ADR" beauftragt – hat aber
                    # trotz seines eigenen System-Prompt-Hinweises (agents/architect_agent.py)
                    # NIE record_architecture_decision aufgerufen, die Entscheidung stand nur im
                    # Fließtext. Der obige Code-Fence-Check (CODE_WRITING_AGENT_IDS) greift hier
                    # NICHT: architect liefert legitim Code-Fences für Mermaid-Diagramme, ohne
                    # dass "kein write_file aufgerufen" ein Problem wäre - er schreibt normalerweise
                    # ohnehin keine Projektdateien. Eigene, gezielte Heuristik: Antwort erwähnt
                    # Technologie-/Architektur-Entscheidungen (_ADR_TEXT_MARKERS, deckt das vom
                    # architect-Prompt selbst vorgeschriebene Ausgabeformat ab), aber toolbox.
                    # files_written ist über die GESAMTE Aufgabe leer (nicht mal ein ADR).
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
                if (
                    self.agent_id in CODE_WRITING_AGENT_IDS
                    and not toolbox.files_written
                    and not task.tools_read_only
                    and not toolbox.clarification_requests
                    and (
                        no_file_written_retry_used
                        or (iteration == hard_limit and max_iterations > 1 and not response.tool_calls)
                    )
                    and not text_has_extractable_file_blocks(response.text)
                ):
                    # Hard Delivery Gate, zweite Stufe: der obige Korrektur-Hinweis wurde bereits
                    # EINMAL gegeben (no_file_written_retry_used) und der Agent liefert trotzdem
                    # keine einzige Datei - execute() unten wertet das NIEMALS als success=True,
                    # damit der Orchestrator sofort eskaliert statt den DoD-Fehler erst Minuten
                    # später über einen leeren `git status` zu bemerken.
                    #
                    # Bugfix (KI-Team-Gesamtanalyse, fehleranalyse_ki_team.md Befund 2, CertPulse-
                    # Lauf 12.09.2026): `no_file_written_retry_used` allein reichte NICHT, um diese
                    # Stufe auszulösen, wenn der Agent Iterationen 1..max_iterations-1 durchgängig
                    # MIT Tool-Aufrufen (z.B. nur read_file) verbrachte und erst in der letzten,
                    # erzwungenen Text-Iteration (oben: "LETZTE Gelegenheit") ohne jede geschriebene
                    # Datei abschloss - der "keine Datei geschrieben"-Korrektur-Retry weiter oben
                    # verlangt zwingend `iteration < max_iterations` und kam dadurch NIE zum Zug,
                    # `no_file_written_retry_used` blieb `False`, und dieses Gate feuerte ebenfalls
                    # nicht: der Agent meldete `success=True, files_written=[]`, obwohl 300k+ Tokens
                    # verpufften. Die zusätzliche Bedingung `iteration == max_iterations and
                    # max_iterations > 1 and not response.tool_calls` deckt genau diesen Fall ab,
                    # OHNE zwei bewusst weiterhin erwünschte Fälle zu treffen: (a)
                    # `max_iterations == 1` (siehe test_no_retry_when_no_iterations_remain: bei
                    # nur EINER erlaubten Iteration gab es nie eine reale Korrekturchance) und
                    # (b) der Agent ruft in der letzten Iteration weiterhin AKTIV ein Werkzeug auf
                    # (`response.tool_calls` nicht leer) - dann greift bereits der obige
                    # "Maximale Werkzeug-Iterationen erreicht"-Fallback-Text, und das ist ein
                    # ehrlicher Abbruch mangels Zeit, kein "premature final answer" (real
                    # reproduziert: test_max_iterations_reached_yields_honest_fallback_message
                    # brach ohne diese Einschränkung fälschlich mit Hard-Fail ab, obwohl der Agent
                    # bis zur letzten Sekunde fleißig weiterarbeiten wollte).
                    #
                    # Bugfix (bei der KI-Team-Gesamtanalyse gefunden): `not text_has_extractable_
                    # file_blocks(response.text)` ergänzt - enthält der Antworttext trotz allem
                    # einen Codeblock, den core/workspace.py.parse_and_save_files() (Text-
                    # Fallback) erkennen und speichern WÜRDE, ist der Tokenverbrauch NICHT
                    # "verpufft": der Orchestrator rettet die Datei gleich im Anschluss über
                    # genau diesen Fallback-Pfad (agents/orchestrator/__init__.py,
                    # `AUTO_SAVE_WORKSPACE`, greift nur für `res.success and res.content`). Ohne
                    # diese Ausnahme erstickte das Gate den Text-Fallback-Mechanismus faktisch,
                    # indem es den Agenten schon VOR dessen Aufruf als gescheitert markierte -
                    # real reproduziert: tests/test_text_fallback_report_visibility.py (exakt die
                    # Fixture, die Text-Fallback ursprünglich absichern sollte, schlug dadurch
                    # selbst fehl). Der Korrektur-Hinweis oben bleibt unverändert bestehen - ein
                    # nativer write_file-Aufruf ist robuster als Regex-Extraktion aus Freitext
                    # (siehe parse_and_save_files()-Docstring), nur die ENDGÜLTIGE
                    # Fehlschlag-Markierung wird softened, wenn eine Rettung noch möglich ist.
                    hard_delivery_gate_failed = True
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
        return response, total_prompt_tokens, total_completion_tokens, hard_delivery_gate_failed

    def _augment_with_tool_instructions(self, system_prompt: str, read_only: bool = False) -> str:
        # Realer Fund aus einem echten Lauf: der architect-Agent wird vom Hauptagenten bei
        # kleineren, gut umrissenen Aufgaben oft gar nicht erst eingeplant (siehe
        # core/task_manager.py DECOMPOSE_SYSTEM_PROMPT) - selbst wenn die Aufgabe explizit
        # eine Technologie-Abwägung mit echter Alternative verlangte. Code-schreibende Agenten
        # (CODE_WRITING_AGENT_IDS) treffen solche Entscheidungen dann selbst, ohne sie je zu
        # dokumentieren, obwohl ihnen dasselbe record_architecture_decision-Werkzeug wie dem
        # architect zur Verfügung steht. Zweite Verteidigungslinie zusätzlich zur decompose()-
        # Regel: der Hinweis geht an genau diese Rollen, nicht an alle (z.B. copywriter/i18n
        # treffen legitim keine Architektur-Entscheidungen).
        adr_note = (
            "\n\nTriffst du dabei eine Entscheidung mit einer echten Alternative (z.B. "
            "'PostgreSQL statt In-Memory-Liste', 'REST statt GraphQL'), dokumentiere sie "
            "ZUSÄTZLICH über das Werkzeug `record_architecture_decision` – nicht nur in "
            "deiner Zusammenfassung, sonst ist sie beim nächsten Lauf an diesem Projekt "
            "bereits wieder vergessen."
            if self.agent_id in CODE_WRITING_AGENT_IDS else ""
        )
        # Realer Fund (omnichat-Projekt): der security-Agent identifizierte ein echtes
        # kritisches Problem, hatte aber in diesem Aufruf keine Schreibrechte (`read_only`)
        # und fragte per `ask_human_for_clarification` "Wie erhalte ich Schreibrechte...?" -
        # eine Frage, die nie beantwortet wurde, obwohl core/review_gate.py.
        # find_critical_findings() genau für diesen Fall bereits eine automatische Fix-
        # Schleife bereitstellt (siehe agents/orchestrator/verification.py.
        # _run_governance_fix_loop). Der Agent kannte diesen Mechanismus schlicht nicht und
        # griff zur einzig ihm bekannten Eskalation. Diese Zeile macht den fehlenden
        # Schreibzugriff für BEIDE Fälle explizit: nutzbar (schreib es einfach) oder wirklich
        # nicht nutzbar (melde es normal, kein `ask_human_for_clarification` dafür).
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
        # Team-Retrospektive (Verbesserungsvorschlag "Fehlende Struktur selbst anlegen als
        # Standard-Policy"): dieselbe Rückfrage ("Ich sehe kein `app/`-Verzeichnis / das
        # Projektverzeichnis ist leer - soll ich von Grund auf neu aufsetzen?") trat in
        # mehreren unabhängigen realen Läufen auf (incidentpilot, omnichat, webhookshield),
        # jedes Mal NACHDEM der Agent schon eine Aufgabe angenommen hatte. Bisher gab es dafür
        # nur eine REAKTIVE Korrektur NACH dem Lauf (agents/orchestrator/verification.py.
        # _run_scope_clarification_autofix) - die kostet jedes Mal eine komplette zusätzliche
        # Fix-Runde (Tokens + Zeit), bevor überhaupt losgebaut wird. Dieser Hinweis macht
        # dieselbe Annahme jetzt PROAKTIV zum Standardverhalten, nur für code-schreibende
        # Rollen (nicht z.B. copywriter/i18n, für die eine leere Struktur keine sinnvolle
        # Handlungsanweisung ist).
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
        # Team-Optimierung (Retrospektive: wiederkehrende ruff-Funde BLE001 "Do not catch blind
        # exception: `Exception`" über mehrere Projekte hinweg) - core/project_status.py.
        # has_repeated_lint_finding() eröffnet nach zwei Läufen mit identischem Lint-Fund ein
        # "recurring-lint-"-Ticket für menschliche Prüfung, das NIE automatisch wieder schließt,
        # solange derselbe Fund bestehen bleibt. `except Exception:` als pauschaler Fallback
        # (z.B. um einen Hintergrund-Task nicht abstürzen zu lassen) ist oft bewusst gewollt,
        # nicht versehentlich - der Fund selbst ist dann kein echter Bug, sondern reines
        # Dauer-Rauschen im Verifikationsprotokoll UND im Backlog. Diese Regel setzt vor dem
        # Fund an (spezifischere Exception ODER ein dokumentiertes bewusstes noqa-Kommentar),
        # statt ihn erst hinterher als Ticket zu melden. Nur für Code-schreibende Rollen (nicht
        # z.B. copywriter/i18n, die keinen fehleranfälligen Code erzeugen).
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
        return f"""{system_prompt}

## 🛠️ WERKZEUG-NUTZUNG (agentischer Modus)
Du hast direkten Zugriff auf das Projektverzeichnis über Werkzeuge:
- `list_files` / `read_file`: Verschaffe dir IMMER zuerst einen Überblick über bestehenden Code, bevor du etwas änderst.
- `write_file`: Für neue Dateien oder vollständige Neuerstellung.
- `edit_file`: Für punktuelle Änderungen an bestehenden Dateien (präziser Patch statt Neuerstellung).
- `search_code`: Um relevante Stellen im Projekt zu finden, ohne jede Datei einzeln zu lesen.
- `run_command` / `run_tests`: Um Abhängigkeiten zu installieren bzw. deine Änderungen wirklich zu verifizieren.

Speichere Code IMMER direkt über write_file/edit_file im Projektverzeichnis – gib ihn nicht nur als Text in
deiner Antwort aus. Schreibe NIEMALS Platzhalter wie `# ...`, `# Rest beibehalten` oder unvollständigen Pseudo-Code;
jede Datei muss zu 100% vollständig und syntaktisch lauffähig sein. Deine finale Textantwort soll eine KURZE
Zusammenfassung sein (was wurde geschrieben/geändert, warum, was ist noch offen) – kein erneutes Einfügen des kompletten Codes.{adr_note}

Triffst du auf eine ECHTE, für die Aufgabe entscheidende Unklarheit, die nur ein Mensch sinnvoll auflösen kann
(nicht: eine übliche technische Entscheidung, die du selbst treffen kannst) – nutze `ask_human_for_clarification`,
statt zu raten und trotzdem etwas möglicherweise Falsches auszuliefern. Ein erfahrener Senior-Entwickler fragt bei
echter Mehrdeutigkeit nach, statt zu spekulieren. Setze deine Arbeit danach so weit wie möglich fort und fasse in
deiner finalen Antwort ehrlich zusammen, was bereits erledigt ist und was durch die Rückfrage offen bleibt.
{write_access_note}{empty_scope_note}{exception_handling_note}"""

    def _build_prompt(self, task: AgentTask) -> str:
        """Baut den finalen Prompt token-effizient zusammen mit strikten Sparsamkeits-Regeln."""
        prompt_parts = [
            f"**DEINE AUFGABE:**\n{task.description}\n",
            "**TOKEN-EFFIZIENZ-REGEL:** Antworte hochpräzise, fokussiert und ohne Füllwörter oder Redundanzen. Liefere vollständigen, lauffähigen Code und Fakten in kompakter Markdown-Struktur."
        ]

        if task.context:
            prompt_parts.insert(0, f"**PROJEKT-KONTEXT:**\n{task.context}\n")
            # Realer Fund (KI-Team-Gesamtanalyse, hooksentinel/certpulse-Läufe 12.09.2026):
            # ADRs und Schnittstellen-Verträge stecken bereits vollständig im obigen
            # PROJEKT-KONTEXT (siehe agents/orchestrator/department.py), trotzdem verbrachten
            # backend/frontend/database ihre ersten 1-2 Werkzeug-Iterationen fast immer damit,
            # dieselben Dateien nochmal per read_file zu laden - das kostet pro Agent
            # 20.000-30.000 Tokens, ohne neue Information zu liefern, und drängt das echte
            # write_file in Richtung der knapp bemessenen letzten Iterationen. Nur für
            # Code-schreibende Rollen, da nur deren Aufträge typischerweise ADRs/Contracts im
            # Kontext enthalten.
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
