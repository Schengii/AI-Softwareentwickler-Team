"""
tests/test_agentic_loop_resilience.py – Testet zwei Resilienz-Fixes im agentischen
Werkzeug-Loop (agents/base_agent.py), beide aus einem echten End-to-End-Testlauf gefunden

1. Groq (häufig der Fallback für HEAVY-Rollen ohne ANTHROPIC_API_KEY) lehnte einen rein
   lesenden Konsolidierungs-Aufruf hart mit 400 ab, weil das Modell selbst versuchte, ein
   NICHT deklariertes Werkzeug (write_file) aufzurufen - der Request war korrekt, nur die
   Modell-Ausgabe nicht. Ein einziger, gezielter Retry mit Korrektur-Hinweis behebt das
   meist, statt die ganze Aufgabe zu verwerfen. Echte Rate-Limit-/Auth-Fehler haben bereits
   eigene Behandlung und werden bewusst NICHT mitgefangen.
2. Auf der letzten erlaubten Iteration durfte das Modell bisher weiterhin frei zwischen
   Werkzeug-Aufruf und Text wählen - entschied es sich nochmal für ein Werkzeug, wurde
   dieser Aufruf VERWORFEN und der Nutzer sah nur "Maximale Werkzeug-Iterationen erreicht"
   statt einer echten Zusammenfassung (real beobachtet bei zwei Fachbereichs-Teamleiter-
   Aufrufen in einem Lauf). Eine explizite letzte Aufforderung erhöht die Erfolgschance.
"""

import asyncio
import shutil
import tempfile
import unittest

from agents.architect_agent import ArchitectAgent
from agents.backend_agent import BackendAgent
from core.llm_factory import LLMResponse, ToolCall
from core.message_bus import AgentTask


class _ScriptedLLM:
    """Gibt bei jedem generate_with_tools-Aufruf das nächste Item zurück - entweder eine
    LLMResponse oder eine zu werfende Exception. Merkt sich alle gesehenen Nachrichten."""

    def __init__(self, items: list):
        self._items = list(items)
        self.call_count = 0
        self.model_name = "fake-model"
        self.seen_messages: list[list] = []

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        self.seen_messages.append(list(messages))
        item = self._items[min(self.call_count, len(self._items) - 1)]
        self.call_count += 1
        if isinstance(item, Exception):
            raise item
        return item


def _final_response(text: str = "Fertig.") -> LLMResponse:
    return LLMResponse(text=text, model_name="fake-model", prompt_tokens=10,
                        completion_tokens=5, total_tokens=15, tool_calls=[])


class TestDisallowedToolCallRetry(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_disallowed_tool_call_error_triggers_one_retry_then_succeeds(self):
        error = Exception(
            "Error code: 400 - {'error': {'message': \"Tool call validation failed: "
            "attempted to call tool 'write_file' which was not in request.tools\", "
            "'code': 'tool_use_failed'}}"
        )
        fake_llm = _ScriptedLLM([error, _final_response("Konsolidierter Bericht.")])
        agent = BackendAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="backend", description="Fasse zusammen",
                          project_dir=self.temp_dir, tools_read_only=True, max_tool_iterations=5)

        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.content, "Konsolidierter Bericht.")
        self.assertEqual(fake_llm.call_count, 2)
        # Der zweite Versuch muss den Korrektur-Hinweis gesehen haben.
        retry_messages_text = " ".join(m.text for m in fake_llm.seen_messages[1])
        self.assertIn("nicht verfügbares Werkzeug", retry_messages_text)

    def test_unrelated_exception_is_not_retried_and_propagates_as_failure(self):
        fake_llm = _ScriptedLLM([RuntimeError("Verbindung zum Provider verloren")])
        agent = BackendAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="backend", description="Baue etwas",
                          project_dir=self.temp_dir, max_tool_iterations=5)

        result = asyncio.run(agent.execute(task))

        self.assertFalse(result.success)
        self.assertIn("Verbindung zum Provider verloren", result.error)
        self.assertEqual(fake_llm.call_count, 1)  # kein Retry für eine unbekannte Exception

    def test_disallowed_tool_call_error_on_last_iteration_is_not_retried(self):
        """Ein Retry auf der letzten erlaubten Iteration würde `response` auf None lassen -
        bewusst NICHT retryen, sondern die Exception normal durchreichen."""
        error = Exception("tool_use_failed: attempted to call tool 'x' which was not in request.tools")
        fake_llm = _ScriptedLLM([error])
        agent = BackendAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="backend", description="Baue etwas",
                          project_dir=self.temp_dir, max_tool_iterations=1)

        result = asyncio.run(agent.execute(task))

        self.assertFalse(result.success)
        self.assertEqual(fake_llm.call_count, 1)

    def test_only_one_retry_even_if_error_recurs(self):
        error = Exception("tool_use_failed: attempted to call tool 'x' which was not in request.tools")
        fake_llm = _ScriptedLLM([error, error, _final_response()])
        agent = BackendAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="backend", description="Baue etwas",
                          project_dir=self.temp_dir, max_tool_iterations=5)

        result = asyncio.run(agent.execute(task))

        # Zweiter, wiederholter Fehler wird NICHT nochmal abgefangen -> Lauf schlägt fehl.
        self.assertFalse(result.success)
        self.assertEqual(fake_llm.call_count, 2)


class TestFinalIterationStopUsingTools(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_final_iteration_receives_explicit_stop_instruction(self):
        fake_llm = _ScriptedLLM([
            LLMResponse(text="", model_name="fake-model", prompt_tokens=10, completion_tokens=5,
                        total_tokens=15, tool_calls=[ToolCall(id="c1", name="list_files", arguments={})]),
            _final_response("Zusammenfassung."),
        ])
        agent = BackendAgent()
        agent._llm = fake_llm
        # tools_read_only=True: dieser Test prüft ausschließlich die Stop-Instruktion der
        # letzten Iteration, nicht das Hard Delivery Gate - "Prüfe den Stand" ist ein reiner
        # Lese-/Check-Auftrag ohne erwartete Dateischreibung (siehe
        # test_read_only_task_never_triggers_the_hard_delivery_gate).
        task = AgentTask(task_id="t1", agent_id="backend", description="Prüfe den Stand",
                          project_dir=self.temp_dir, max_tool_iterations=2, tools_read_only=True)

        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success, result.error)
        last_call_text = " ".join(m.text for m in fake_llm.seen_messages[-1])
        self.assertIn("LETZTE Gelegenheit", last_call_text)

    def test_no_stop_instruction_when_only_a_single_iteration_is_allowed(self):
        """Bei max_tool_iterations=1 ist JEDE Iteration die letzte - eine Extra-Nachricht
        dafür wäre redundant/sinnlos, siehe `max_iterations > 1`-Bedingung."""
        fake_llm = _ScriptedLLM([_final_response("Direkt fertig.")])
        agent = BackendAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="backend", description="Kurze Aufgabe",
                          project_dir=self.temp_dir, max_tool_iterations=1)

        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success, result.error)
        first_call_text = " ".join(m.text for m in fake_llm.seen_messages[0])
        self.assertNotIn("LETZTE Gelegenheit", first_call_text)

    def test_dropped_final_tool_call_case_still_produces_honest_fallback_text(self):
        """Ignoriert das Modell die letzte Aufforderung trotzdem und ruft erneut ein
        Werkzeug auf, greift weiterhin die bestehende ehrliche Fallback-Notiz."""
        fake_llm = _ScriptedLLM([
            LLMResponse(text="", model_name="fake-model", prompt_tokens=10, completion_tokens=5,
                        total_tokens=15, tool_calls=[ToolCall(id="c1", name="list_files", arguments={})]),
        ])
        agent = BackendAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="backend", description="Prüfe den Stand",
                          project_dir=self.temp_dir, max_tool_iterations=1)

        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success)
        self.assertIn("Maximale Werkzeug-Iterationen", result.content)


class TestCodeInTextWithoutFileWriteRetry(unittest.TestCase):
    """
    Realer Fund aus einem echten End-to-End-Testlauf: mehrere Code-schreibende Agenten
    lieferten fertigen Code AUSSCHLIESSLICH im Antworttext statt über write_file/edit_file –
    zusammen ~48.000 Tokens verpufft, ohne dass etwas Nutzbares im Projekt ankam. Der
    Regex-Text-Fallback (core/workspace.py.parse_and_save_files()) fängt das nicht
    zuverlässig auf, wenn kein erkennbarer Dateipfad-Marker im Fließtext steht.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_code_fence_without_any_write_triggers_retry_that_then_writes_the_file(self):
        write_call = LLMResponse(
            text="", model_name="fake-model", prompt_tokens=10, completion_tokens=5, total_tokens=15,
            tool_calls=[ToolCall(id="c1", name="write_file", arguments={"path": "app.py", "content": "print('hi')\n"})],
        )
        fake_llm = _ScriptedLLM([
            _final_response("Hier ist der Code:\n```python\nprint('hi')\n```"),
            write_call,
            _final_response("Datei gespeichert."),
        ])
        agent = BackendAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="backend", description="Baue app.py",
                          project_dir=self.temp_dir, max_tool_iterations=5)

        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.content, "Datei gespeichert.")
        self.assertEqual(result.files_written, ["app.py"])
        self.assertEqual(fake_llm.call_count, 3)
        retry_messages_text = " ".join(m.text for m in fake_llm.seen_messages[1])
        self.assertIn("keine einzige Datei", retry_messages_text)

    def test_plain_text_summary_without_code_fence_is_retried_then_fails(self):
        """Realer Fund (pulseflow_gateway, 20260911_095217): eine reine Textbehauptung ("Ich habe
        app.py erstellt") OHNE Code-Fence und OHNE tatsächlichen write_file-Aufruf schloss bisher
        unbeanstandet mit success=True ab, obwohl files_written leer blieb - das Fence-Erfordernis
        wurde deshalb aus dem Hard Delivery Gate entfernt (siehe agents/base_agent.py)."""
        fake_llm = _ScriptedLLM([
            _final_response("Ich habe app.py erstellt und getestet."),
            _final_response("Ich habe app.py erstellt und getestet."),
        ])
        agent = BackendAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="backend", description="Baue app.py",
                          project_dir=self.temp_dir, max_tool_iterations=5)

        result = asyncio.run(agent.execute(task))

        self.assertFalse(result.success)
        self.assertIn("Hard Delivery Gate", result.error)
        self.assertEqual(fake_llm.call_count, 2)  # EIN Korrektur-Retry, dann Abbruch

    def test_no_retry_when_a_file_was_already_written_earlier_in_the_task(self):
        write_call = LLMResponse(
            text="", model_name="fake-model", prompt_tokens=10, completion_tokens=5, total_tokens=15,
            tool_calls=[ToolCall(id="c1", name="write_file", arguments={"path": "app.py", "content": "print('hi')\n"})],
        )
        fake_llm = _ScriptedLLM([
            write_call,
            _final_response("Fertig, zur Referenz nochmal der Kern:\n```python\nprint('hi')\n```"),
        ])
        agent = BackendAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="backend", description="Baue app.py",
                          project_dir=self.temp_dir, max_tool_iterations=5)

        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.files_written, ["app.py"])
        self.assertEqual(fake_llm.call_count, 2)  # bereits geschrieben -> kein Retry trotz Code-Fence in der Zusammenfassung

    def test_no_retry_for_agent_outside_code_writing_set(self):
        fake_llm = _ScriptedLLM([_final_response("Vorschlag:\n```python\nprint('hi')\n```")])
        agent = ArchitectAgent()  # "architect" ist NICHT in CODE_WRITING_AGENT_IDS
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="architect", description="Entwirf die Architektur",
                          project_dir=self.temp_dir, max_tool_iterations=5)

        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success, result.error)
        self.assertEqual(fake_llm.call_count, 1)

    def test_only_one_retry_then_hard_delivery_gate_fails_the_step(self):
        """Hard Delivery Gate (KI-Team-Härtung, echter Fund keygate_service-Lauf): ignoriert der
        Agent den EINEN Korrektur-Retry und liefert weiterhin keine Datei, gilt der Schritt NICHT
        mehr als success=True (sonst verpufft der Tokenverbrauch unbemerkt) - nur EIN Retry wird
        gewährt, kein zweiter."""
        fake_llm = _ScriptedLLM([
            _final_response("Erster Versuch:\n```python\nprint('a')\n```"),
            _final_response("Zweiter Versuch, ignoriert den Hinweis:\n```python\nprint('b')\n```"),
        ])
        agent = BackendAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="backend", description="Baue app.py",
                          project_dir=self.temp_dir, max_tool_iterations=5)

        result = asyncio.run(agent.execute(task))

        self.assertFalse(result.success)
        self.assertIn("Hard Delivery Gate", result.error)
        self.assertEqual(fake_llm.call_count, 2)  # nur EIN Retry, kein zweiter trotz erneut fehlender Datei
        self.assertEqual(result.files_written, [])
        # Ticket P1-5 (ROADMAP_TEMP.md, realer Fund über 7 Projekte): eigene failure_class statt
        # des generischen "agent_error" - der Fix-Loop kann diesen Fall damit von einem Agenten
        # unterscheiden, der etwas (falsches) geliefert hat, und braucht keinen identischen
        # Wiederholungsversuch mit derselben Grundlage abzuwarten.
        from core.provider_exhaustion import FAILURE_CLASS_NO_DELIVERY, is_infrastructure_failure
        self.assertEqual(result.failure_class, FAILURE_CLASS_NO_DELIVERY)
        # Kein Infrastruktur-Fehler: der Agent WURDE befragt, hat sich aber gegen das Liefern
        # entschieden - das darf nicht wie ein 429/fehlender API-Key aus der Erfolgsquote fallen.
        self.assertFalse(is_infrastructure_failure(result.failure_class))

    def test_plain_text_without_code_fence_also_triggers_the_hard_delivery_gate(self):
        """Realer Fund (pulseflow_gateway, 20260911_095217): ein backend-Agent schloss mit reinem
        Planungs-Fließtext OHNE Code-Fence ab und meldete trotz files_written=[] success=True. Das
        Gate darf sich NICHT mehr auf das Vorhandensein eines ``` -Markers verlassen."""
        fake_llm = _ScriptedLLM([
            _final_response("Ich würde als Nächstes app/main.py mit der FastAPI-Instanz anlegen."),
            _final_response("Ich habe den Plan nochmal durchdacht, aber noch nichts geschrieben."),
        ])
        agent = BackendAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="backend", description="Baue app.py",
                          project_dir=self.temp_dir, max_tool_iterations=5)

        result = asyncio.run(agent.execute(task))

        self.assertFalse(result.success)
        self.assertIn("Hard Delivery Gate", result.error)
        self.assertEqual(result.files_written, [])

    def test_no_retry_when_no_iterations_remain(self):
        fake_llm = _ScriptedLLM([_final_response("Code:\n```python\nprint('hi')\n```")])
        agent = BackendAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="backend", description="Baue app.py",
                          project_dir=self.temp_dir, max_tool_iterations=1)

        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success, result.error)
        self.assertEqual(fake_llm.call_count, 1)  # max_tool_iterations=1 -> keine Iteration für einen Retry übrig

    def test_read_only_iterations_until_forced_final_text_still_hits_the_hard_delivery_gate(self):
        """Realer Fund (fehleranalyse_ki_team.md, CertPulse-Lauf 12.09.2026, Befund 2): der
        Agent ruft in JEDER Iteration bis zur letzten ein Werkzeug auf (hier: wiederholt
        list_files statt write_file) - der "keine Datei geschrieben"-Korrektur-Retry weiter
        oben griff NIE, weil er `iteration < max_iterations` voraussetzt. Erst in der
        erzwungenen letzten Iteration ("LETZTE Gelegenheit") liefert das Modell reinen Text
        ohne jede gespeicherte Datei. Das Gate muss auch DIESEN Fall als Fehlschlag werten,
        statt still mit success=True/files_written=[] durchzuwinken (genau das passierte vor
        dem Fix: 300k+ Tokens verpufften, ohne dass der Orchestrator es bemerkte)."""
        list_call = LLMResponse(
            text="", model_name="fake-model", prompt_tokens=10, completion_tokens=5, total_tokens=15,
            tool_calls=[ToolCall(id="c1", name="list_files", arguments={})],
        )
        fake_llm = _ScriptedLLM([
            list_call, list_call, list_call, list_call,
            _final_response("Ich würde app/main.py so aufbauen: ..."),
        ])
        agent = BackendAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="backend", description="Baue app.py",
                          project_dir=self.temp_dir, max_tool_iterations=5)

        result = asyncio.run(agent.execute(task))

        self.assertFalse(result.success)
        self.assertIn("Hard Delivery Gate", result.error)
        self.assertEqual(result.files_written, [])
        self.assertEqual(fake_llm.call_count, 5)

    def test_read_only_task_never_triggers_the_hard_delivery_gate(self):
        """Ein Nur-Lese-Auftrag (task.tools_read_only=True, z.B. Governance-Fix-Schleife) darf mit
        0 geschriebenen Dateien NIE als Ghost-Code gewertet werden, selbst wenn die Antwort einen
        Code-Fence enthält (z. B. ein zitierter Ausschnitt in einem Befund-Bericht) - das ist dort
        der gewollte Normalfall, nicht abweichendes Verhalten."""
        fake_llm = _ScriptedLLM([_final_response("Befund:\n```python\nprint('kaputt')\n```")])
        agent = BackendAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="backend", description="Prüfe den Stand",
                          project_dir=self.temp_dir, tools_read_only=True, max_tool_iterations=5)

        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success, result.error)
        self.assertEqual(fake_llm.call_count, 1)  # kein Retry, kein Hard-Fail trotz 0 Dateien

    def test_pending_clarification_request_never_triggers_the_hard_delivery_gate(self):
        """Eine echte Rückfrage mitten in der Aufgabe (ask_human_for_clarification) ist ein
        legitimer Abschluss ohne Datei, KEIN Ghost-Code - toolbox.clarification_requests schließt
        den Gate deshalb explizit aus, selbst wenn die Antwort zufällig einen Code-Fence enthält."""
        clarify_call = LLMResponse(
            text="", model_name="fake-model", prompt_tokens=10, completion_tokens=5, total_tokens=15,
            tool_calls=[ToolCall(id="c1", name="ask_human_for_clarification", arguments={
                "question": "JWT oder Session-Cookie?", "context": "Auftrag nennt beides.",
            })],
        )
        fake_llm = _ScriptedLLM([
            clarify_call,
            _final_response("Beispielhafter Ansatz:\n```python\nprint('todo')\n```\nRückfrage siehe oben."),
        ])
        agent = BackendAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="backend", description="Baue Login-Endpunkt",
                          project_dir=self.temp_dir, max_tool_iterations=5)

        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success, result.error)
        self.assertTrue(result.needs_human_input)
        self.assertEqual(fake_llm.call_count, 2)  # kein zusätzlicher Retry trotz Code-Fence


class TestArchitectAdrCallRetry(unittest.TestCase):
    """
    Realer Fund aus einem echten End-to-End-Testlauf: architect wurde korrekt eingeplant und
    explizit mit "erstelle ADR" beauftragt, hat aber trotz eigener System-Prompt-Anweisung NIE
    record_architecture_decision aufgerufen - die Entscheidung stand nur im Fließtext. Der
    Code-Fence-Check (TestCodeInTextWithoutFileWriteRetry) greift hier nicht: architect ist
    NICHT in CODE_WRITING_AGENT_IDS und liefert legitim Code-Fences für Mermaid-Diagramme.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_adr_marker_without_any_write_triggers_retry_that_then_calls_the_tool(self):
        adr_call = LLMResponse(
            text="", model_name="fake-model", prompt_tokens=10, completion_tokens=5, total_tokens=15,
            tool_calls=[ToolCall(id="c1", name="record_architecture_decision", arguments={
                "title": "PostgreSQL statt MongoDB", "context": "K", "decision": "E", "consequences": "K",
            })],
        )
        fake_llm = _ScriptedLLM([
            _final_response("## 6. Technologie-Entscheidungen (ADRs)\n\nWir wählen PostgreSQL."),
            adr_call,
            _final_response("ADR dokumentiert."),
        ])
        agent = ArchitectAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="architect", description="Entwirf die Architektur",
                          project_dir=self.temp_dir, max_tool_iterations=5)

        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.content, "ADR dokumentiert.")
        self.assertEqual(len(result.files_written), 1)
        self.assertTrue(result.files_written[0].startswith("docs/adr/"))
        self.assertEqual(fake_llm.call_count, 3)
        retry_messages_text = " ".join(m.text for m in fake_llm.seen_messages[1])
        self.assertIn("KEIN ADR", retry_messages_text)

    def test_no_retry_without_adr_marker_in_text(self):
        fake_llm = _ScriptedLLM([_final_response("Ich schlage FastAPI und PostgreSQL vor.")])
        agent = ArchitectAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="architect", description="Entwirf die Architektur",
                          project_dir=self.temp_dir, max_tool_iterations=5)

        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success, result.error)
        self.assertEqual(fake_llm.call_count, 1)  # kein Entscheidungs-Marker -> kein Retry-Grund

    def test_no_retry_when_architect_already_wrote_a_file(self):
        write_call = LLMResponse(
            text="", model_name="fake-model", prompt_tokens=10, completion_tokens=5, total_tokens=15,
            tool_calls=[ToolCall(id="c1", name="write_file", arguments={"path": "docs/architecture.md", "content": "# Architektur\n"})],
        )
        fake_llm = _ScriptedLLM([
            write_call,
            _final_response("## 6. Technologie-Entscheidungen (ADRs)\n\nSiehe docs/architecture.md."),
        ])
        agent = ArchitectAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="architect", description="Entwirf die Architektur",
                          project_dir=self.temp_dir, max_tool_iterations=5)

        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.files_written, ["docs/architecture.md"])
        self.assertEqual(fake_llm.call_count, 2)  # bereits geschrieben -> kein Retry trotz ADR-Marker

    def test_non_architect_agent_with_adr_marker_still_hits_hard_delivery_gate(self):
        # backend ist NICHT von der ADR-Heuristik betroffen (nur architect), fällt aber als
        # Code-schreibender Agent ohne jede geschriebene Datei unter das allgemeine Hard
        # Delivery Gate (agents/base_agent.py) - unabhängig vom ADR-Marker im Text.
        fake_llm = _ScriptedLLM([
            _final_response("## 6. Technologie-Entscheidungen (ADRs)\n\nOK."),
            _final_response("## 6. Technologie-Entscheidungen (ADRs)\n\nOK."),
        ])
        agent = BackendAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="backend", description="Baue etwas",
                          project_dir=self.temp_dir, max_tool_iterations=5)

        result = asyncio.run(agent.execute(task))

        self.assertFalse(result.success)
        self.assertIn("Hard Delivery Gate", result.error)
        self.assertEqual(fake_llm.call_count, 2)

    def test_only_one_adr_retry_even_if_still_not_called(self):
        fake_llm = _ScriptedLLM([
            _final_response("## 6. Technologie-Entscheidungen (ADRs)\n\nErster Versuch."),
            _final_response("## 6. Technologie-Entscheidungen (ADRs)\n\nIgnoriert den Hinweis."),
        ])
        agent = ArchitectAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="architect", description="Entwirf die Architektur",
                          project_dir=self.temp_dir, max_tool_iterations=5)

        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success, result.error)
        self.assertEqual(fake_llm.call_count, 2)  # nur EIN Retry
        self.assertEqual(result.files_written, [])

    def test_no_retry_when_no_iterations_remain(self):
        fake_llm = _ScriptedLLM([_final_response("## 6. Technologie-Entscheidungen (ADRs)\n\nOK.")])
        agent = ArchitectAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="architect", description="Entwirf die Architektur",
                          project_dir=self.temp_dir, max_tool_iterations=1)

        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success, result.error)
        self.assertEqual(fake_llm.call_count, 1)


class TestCacheTokensPropagateToAgentResult(unittest.TestCase):
    """Realer Fund (ROADMAP_TEMP.md P5-2, notecatcher-Referenzlauf 2026-09-20): Caching wurde
    korrekt an token_guard gemeldet (Abschlussbericht zeigte 63% Trefferquote), aber
    AgentResult - und damit jede einzelne Trace-Zeile - hatte gar kein cache_read_tokens-Feld.
    Diese Tests decken die Weitergabe LLMResponse -> _run_agentic_loop() -> AgentResult ab,
    inklusive Summierung über mehrere Iterationen desselben Werkzeug-Loops."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_single_iteration_cache_tokens_reach_agent_result(self):
        # tools_read_only=True: umgeht das Hard Delivery Gate (das nur codeschreibende Aufgaben
        # betrifft) und hält den Test auf EINE Iteration beschränkt - reiner Nachweis, dass ein
        # einzelnes cache_read_tokens korrekt bis ins AgentResult durchgereicht wird.
        response = LLMResponse(
            text="Zusammenfassung.", model_name="fake-model",
            prompt_tokens=100, completion_tokens=20, total_tokens=120,
            cache_read_tokens=3336, cache_write_tokens=0, tool_calls=[],
        )
        fake_llm = _ScriptedLLM([response])
        agent = BackendAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="backend", description="Fasse den Stand zusammen",
                          project_dir=self.temp_dir, tools_read_only=True, max_tool_iterations=5)

        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.cache_read_tokens, 3336)
        self.assertEqual(result.cache_write_tokens, 0)

    def test_cache_tokens_summed_across_multiple_iterations(self):
        from core.llm_factory import ToolCall

        write_call = LLMResponse(
            text="", model_name="fake-model", prompt_tokens=50, completion_tokens=10,
            total_tokens=60, cache_read_tokens=1000, cache_write_tokens=500,
            tool_calls=[ToolCall(id="1", name="write_file", arguments={"path": "app.py", "content": "print('a')"})],
        )
        final_response = LLMResponse(
            text="Fertig.", model_name="fake-model", prompt_tokens=40, completion_tokens=5,
            total_tokens=45, cache_read_tokens=1200, cache_write_tokens=0, tool_calls=[],
        )
        fake_llm = _ScriptedLLM([write_call, final_response])
        agent = BackendAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="backend", description="Baue app.py",
                          project_dir=self.temp_dir, max_tool_iterations=5)

        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success, result.error)
        # Summiert über BEIDE Iterationen, nicht nur die letzte.
        self.assertEqual(result.cache_read_tokens, 1000 + 1200)
        self.assertEqual(result.cache_write_tokens, 500)


if __name__ == "__main__":
    unittest.main()
