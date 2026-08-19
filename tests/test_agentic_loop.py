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

from agents.backend_agent import BackendAgent
from core.llm_factory import LLMResponse, ToolCall
from core.message_bus import AgentTask


class _SequencedFakeLLM:
    """Gibt bei jedem generate_with_tools-Aufruf die nächste vordefinierte Antwort zurück."""

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self.call_count = 0
        self.model_name = "fake-model"

    async def generate_with_tools(self, messages, system_prompt, tools):
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
