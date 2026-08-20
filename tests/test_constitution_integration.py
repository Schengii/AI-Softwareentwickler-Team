"""
tests/test_constitution_integration.py – Testet die Injektion der Projekt-Konstitution in den
Agenten-Kontext (agents/orchestrator.py.process())

Realer Fund: project_slug/Architektur/Tech-Stack werden pro Lauf frisch vom Modell geraten -
selbst am selben Projekt kann Lauf 2 eine andere Sprache/Framework wählen als Lauf 1. Eine
per /constitution festgelegte Präferenz muss bei JEDEM künftigen Lauf tatsächlich im Kontext
jeder Teilaufgabe ankommen, nicht nur in der Datei liegen bleiben.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.project_constitution import write_constitution
from core.workspace import WorkspaceManager


class _CapturingLLM:
    """Zeichnet den system_prompt/context jedes Aufrufs auf, um zu prüfen, was der Agent
    wirklich sieht - anstatt nur das Endergebnis zu prüfen."""

    def __init__(self):
        self.model_name = "fake-model"
        self.seen_messages: list = []

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        self.seen_messages.append(messages)
        return LLMResponse(text="Fertig.", model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[])

    async def generate_with_usage(self, prompt, system_prompt=None):
        self.seen_messages.append(prompt)
        return LLMResponse(text="Fertig.", model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15)


class TestConstitutionReachesAgentContext(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        self.capturing_llm = _CapturingLLM()
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = self.capturing_llm

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self):
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose):
            task = AgentTask(task_id="t1", agent_id="backend", description="Etwas bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "constitution_test_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            return asyncio.run(self.orchestrator.process("Baue etwas"))

        return _inner()

    def test_constitution_is_injected_into_every_task_context(self):
        project_dir = str(self.orchestrator._workspace.get_project_dir("constitution_test_proj"))
        write_constitution(project_dir, {"language": "TypeScript", "framework": "Next.js"})

        self._run()

        all_seen = "\n".join(str(m) for m in self.capturing_llm.seen_messages)
        self.assertIn("TypeScript", all_seen)
        self.assertIn("Next.js", all_seen)
        self.assertIn("Projekt-Konstitution", all_seen)

    def test_no_constitution_adds_no_context_noise(self):
        self._run()

        all_seen = "\n".join(str(m) for m in self.capturing_llm.seen_messages)
        self.assertNotIn("Projekt-Konstitution", all_seen)


if __name__ == "__main__":
    unittest.main()
