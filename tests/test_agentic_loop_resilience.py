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
        task = AgentTask(task_id="t1", agent_id="backend", description="Prüfe den Stand",
                          project_dir=self.temp_dir, max_tool_iterations=2)

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
        self.assertIn("KEINE Datei", retry_messages_text)

    def test_plain_text_summary_without_code_fence_is_not_retried(self):
        fake_llm = _ScriptedLLM([_final_response("Ich habe app.py erstellt und getestet.")])
        agent = BackendAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="backend", description="Baue app.py",
                          project_dir=self.temp_dir, max_tool_iterations=5)

        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success, result.error)
        self.assertEqual(fake_llm.call_count, 1)  # kein Code-Fence -> kein Retry-Grund

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

    def test_only_one_retry_even_if_agent_still_writes_no_file(self):
        fake_llm = _ScriptedLLM([
            _final_response("Erster Versuch:\n```python\nprint('a')\n```"),
            _final_response("Zweiter Versuch, ignoriert den Hinweis:\n```python\nprint('b')\n```"),
        ])
        agent = BackendAgent()
        agent._llm = fake_llm
        task = AgentTask(task_id="t1", agent_id="backend", description="Baue app.py",
                          project_dir=self.temp_dir, max_tool_iterations=5)

        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success, result.error)
        self.assertEqual(fake_llm.call_count, 2)  # nur EIN Retry, kein zweiter trotz erneut fehlender Datei
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


if __name__ == "__main__":
    unittest.main()
