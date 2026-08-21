"""
tests/test_adr_integration.py – Testet die Injektion bestehender ADRs in den Agenten-Kontext
(agents/orchestrator.py.process())

core/project_constitution.py hält das WAS fest (Tech-Stack) - aber nicht das WARUM. Eine per
record_architecture_decision() (core/agent_toolbox.py) geschriebene ADR muss bei JEDEM
künftigen Lauf an diesem Projekt tatsächlich im Kontext jeder Teilaufgabe ankommen, nicht nur
in der Datei liegen bleiben - dasselbe Prinzip wie bei der Projekt-Konstitution
(tests/test_constitution_integration.py).
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.adr import write_adr
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
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


class TestAdrsReachAgentContext(unittest.TestCase):
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
            mock_decompose.return_value = ("Kurze Aufgabe", "adr_test_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            return asyncio.run(self.orchestrator.process("Baue etwas"))

        return _inner()

    def test_existing_adr_is_injected_into_every_task_context(self):
        project_dir = str(self.orchestrator._workspace.get_project_dir("adr_test_proj"))
        write_adr(
            project_dir, title="PostgreSQL statt MongoDB",
            context="Relationale Integrität nötig.", decision="PostgreSQL wegen ACID.",
            consequences="Migrationswerkzeug nötig.",
        )

        self._run()

        all_seen = "\n".join(str(m) for m in self.capturing_llm.seen_messages)
        self.assertIn("PostgreSQL statt MongoDB", all_seen)
        self.assertIn("ADR-0001", all_seen)
        self.assertIn("Architektur-Entscheidungen", all_seen)

    def test_no_adrs_adds_no_context_noise(self):
        self._run()

        all_seen = "\n".join(str(m) for m in self.capturing_llm.seen_messages)
        self.assertNotIn("Architektur-Entscheidungen", all_seen)


if __name__ == "__main__":
    unittest.main()
