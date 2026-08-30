"""
tests/test_agentic_loop.py – Testet den echten agentischen Werkzeug-Loop in agents/base_agent.py

Simuliert einen LLM-Client, der zunächst einen write_file-Werkzeug-Aufruf anfordert
und erst im zweiten Schritt final antwortet – und prüft, dass BaseAgent.execute()
das Werkzeug wirklich ausführt (reale Datei auf der Platte), das Ergebnis als
Folge-Nachricht zurückspielt und die finale Antwort inkl. files_written liefert.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.backend_agent import BackendAgent
from core.llm_factory import LLMResponse, ToolCall
from core.message_bus import AgentTask


class _SequencedFakeLLM:
    """Gibt bei jedem generate_with_tools-Aufruf die nächste vordefinierte Antwort zurück."""

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self.call_count = 0
        self.model_name = "fake-model"

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        response = self._responses[min(self.call_count, len(self._responses) - 1)]
        self.call_count += 1
        return response


class TestAgenticToolLoop(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_agent_writes_real_file_via_tool_call_then_finishes(self):
        agent = BackendAgent()
        agent._llm = _SequencedFakeLLM([
            LLMResponse(
                text="", model_name="fake-model", prompt_tokens=100, completion_tokens=40, total_tokens=140,
                tool_calls=[ToolCall(id="call_1", name="write_file", arguments={"path": "main.py", "content": "print('hi')"})],
            ),
            LLMResponse(
                text="Fertig: main.py wurde erstellt.", model_name="fake-model",
                prompt_tokens=120, completion_tokens=20, total_tokens=140, tool_calls=[],
            ),
        ])

        task = AgentTask(task_id="t1", agent_id="backend", description="Erstelle main.py", project_dir=self.temp_dir)
        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success)
        self.assertEqual(result.content, "Fertig: main.py wurde erstellt.")
        self.assertEqual(result.files_written, ["main.py"])
        self.assertEqual(result.tool_calls_count, 1)
        self.assertEqual(result.total_tokens, 140 + 140)  # Tokens beider Iterationen summiert

        written_file = Path(self.temp_dir) / "main.py"
        self.assertTrue(written_file.exists())
        self.assertEqual(written_file.read_text(), "print('hi')")

    def test_ask_human_for_clarification_surfaces_on_agent_result(self):
        # Realer Fund: Rückfragen passierten bisher nur VOR dem Start einer Aufgabe - sobald
        # Agenten liefen, gab es kein Mittel, eine echte Blockade mitten in der Aufgabe an
        # einen Menschen zu melden, statt zu raten. ask_human_for_clarification (core/
        # agent_toolbox.py) schließt diese Lücke; hier wird geprüft, dass die Rückfrage
        # tatsächlich bis in AgentResult durchgereicht wird (agents/base_agent.py).
        agent = BackendAgent()
        agent._llm = _SequencedFakeLLM([
            LLMResponse(
                text="", model_name="fake-model", prompt_tokens=50, completion_tokens=20, total_tokens=70,
                tool_calls=[ToolCall(id="call_1", name="ask_human_for_clarification", arguments={
                    "question": "Soll die API-Authentifizierung per JWT oder Session-Cookie laufen?",
                    "context": "Auftrag nennt beide Begriffe, ohne sich festzulegen.",
                })],
            ),
            LLMResponse(
                text="Habe alles außer der Authentifizierung fertiggestellt; Rückfrage siehe oben.",
                model_name="fake-model", prompt_tokens=60, completion_tokens=15, total_tokens=75, tool_calls=[],
            ),
        ])

        task = AgentTask(task_id="t3", agent_id="backend", description="Baue Login-Endpunkt", project_dir=self.temp_dir)
        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success)
        self.assertTrue(result.needs_human_input)
        self.assertEqual(len(result.clarification_questions), 1)
        self.assertIn("JWT oder Session-Cookie", result.clarification_questions[0])

    def test_agent_without_clarification_request_has_needs_human_input_false(self):
        agent = BackendAgent()
        agent._llm = _SequencedFakeLLM([
            LLMResponse(text="Fertig.", model_name="fake-model", prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[]),
        ])
        task = AgentTask(task_id="t4", agent_id="backend", description="Triviale Aufgabe", project_dir=self.temp_dir)
        result = asyncio.run(agent.execute(task))
        self.assertFalse(result.needs_human_input)
        self.assertEqual(result.clarification_questions, [])

    def test_max_iterations_reached_yields_honest_fallback_message(self):
        agent = BackendAgent()
        always_tool_call = LLMResponse(
            text="", model_name="fake-model", prompt_tokens=10, completion_tokens=5, total_tokens=15,
            tool_calls=[ToolCall(id="call_x", name="list_files", arguments={})],
        )
        agent._llm = _SequencedFakeLLM([always_tool_call])  # liefert immer wieder denselben Tool-Call

        task = AgentTask(
            task_id="t2", agent_id="backend", description="Endlosschleife simulieren",
            project_dir=self.temp_dir, max_tool_iterations=2,
        )
        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success)
        self.assertIn("Maximale Werkzeug-Iterationen", result.content)

    def test_pins_to_actual_responding_provider_after_fallback(self):
        """
        Regressionstest für einen echten Fund aus einem echten Lauf: Iteration 1 fällt (kein
        Claude-Key) auf Groq zurück, das antwortet. Ab Iteration 2 darf NICHT erneut die volle
        Fallback-Kette ab dem Primär-Client neu aufgelöst werden (das hatte die Agenten `backend`
        und `code_reviewer` abstürzen lassen: ein Provider-Wechsel MITTEN im Tool-Dialog spielt
        einem anderen Provider einen function_call zurück, den dieser nicht selbst erzeugt hat –
        Gemini lehnt das mit "400 INVALID_ARGUMENT: missing thought_signature" ab). Stattdessen
        muss ab Iteration 2 der TATSÄCHLICH antwortende Provider (hier: Groq) direkt angesprochen
        werden, mit deaktiviertem Self-Fallback.
        """
        primary = _SequencedFakeLLM([
            LLMResponse(
                text="", model_name="groq:openai/gpt-oss-120b", prompt_tokens=10, completion_tokens=5, total_tokens=15,
                tool_calls=[ToolCall(id="call_1", name="list_files", arguments={})],
            ),
        ])
        primary.model_name = "claude-sonnet-5"  # der urspruenglich konfigurierte (aber "kein Key")-Client

        pinned_calls = []

        class _PinnedGroqStub:
            model_name = "groq:openai/gpt-oss-120b"

            async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
                pinned_calls.append(_allow_self_fallback)
                return LLMResponse(
                    text="Fertig.", model_name="groq:openai/gpt-oss-120b",
                    prompt_tokens=5, completion_tokens=5, total_tokens=10, tool_calls=[],
                )

        agent = BackendAgent()
        agent._llm = primary
        task = AgentTask(task_id="t4", agent_id="backend", description="Pin-Test", project_dir=self.temp_dir)

        with patch("agents.base_agent.LLMFactory.create_for_model", return_value=_PinnedGroqStub()):
            result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success)
        # Iteration 2 muss ueber den gepinnten Groq-Stub gelaufen sein, NICHT nochmal ueber primary.
        self.assertEqual(pinned_calls, [False])  # genau 1 Aufruf, mit deaktiviertem Self-Fallback
        self.assertEqual(primary.call_count, 1)  # primary (Claude, "kein Key") nur EINMAL versucht

    def test_task_without_project_dir_uses_single_shot_path(self):
        agent = BackendAgent()

        class _SingleShotFakeLLM:
            model_name = "fake-model"

            async def generate_with_usage(self, prompt, system_prompt=None):
                return LLMResponse(text="Einfache Antwort ohne Tools.", model_name="fake-model",
                                    prompt_tokens=10, completion_tokens=5, total_tokens=15)

        agent._llm = _SingleShotFakeLLM()
        task = AgentTask(task_id="t3", agent_id="backend", description="Nur Text, kein Projekt")
        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success)
        self.assertEqual(result.content, "Einfache Antwort ohne Tools.")
        self.assertEqual(result.files_written, [])
        self.assertEqual(result.tool_calls_count, 0)


if __name__ == "__main__":
    unittest.main()
