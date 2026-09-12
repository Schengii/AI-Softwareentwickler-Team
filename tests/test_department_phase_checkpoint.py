"""
tests/test_department_phase_checkpoint.py – Regressionstest für den Phasen-Checkpoint
(core/checkpoint.py) in agents/orchestrator/department.py._run_department_hierarchy().

Deckt zwei Anforderungen ab:
1. Mit enable_phase_checkpoint=True (der echte Produktionspfad, siehe
   agents/orchestrator/__init__.py.process()) wird nach jeder abgeschlossenen Phase ein
   .ai_team_checkpoint.json im Projektordner geschrieben, und ein erneuter Aufruf für
   DASSELBE Verzeichnis überspringt bereits abgeschlossene Phasen.
2. Ohne den Parameter (Standard: False) - der Pfad, den alle bestehenden Tests nutzen, die
   _run_department_hierarchy direkt mit project_dir="." aufrufen - passiert KEINERLEI
   Datei-I/O, damit unabhängige Testaufrufe im selben Arbeitsverzeichnis sich nicht
   gegenseitig über einen stehengebliebenen Checkpoint beeinflussen.
"""

import asyncio
import tempfile
import unittest
from pathlib import Path

from agents.orchestrator import Orchestrator
from core.checkpoint import CHECKPOINT_FILENAME, load_checkpoint
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask


class _FakeToolCapableLLM:
    def __init__(self, text: str = "Fertig."):
        self._text = text
        self.model_name = "fake-model"

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[])

    async def generate_with_usage(self, prompt, system_prompt=None):
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15)


class TestDepartmentPhaseCheckpoint(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def test_disabled_by_default_writes_no_checkpoint_file(self):
        agent_tasks = [AgentTask(task_id="t1", agent_id="product_owner", description="Scope")]
        asyncio.run(
            self.orchestrator._run_department_hierarchy(
                user_request="Baue eine App", task_summary="App", agent_tasks=agent_tasks,
                project_dir=self.tmp_dir, notify=lambda msg: None,
            )
        )
        self.assertFalse((Path(self.tmp_dir) / CHECKPOINT_FILENAME).exists())

    def test_enabled_resume_skips_already_completed_phase(self):
        agent_tasks = [
            AgentTask(task_id="t1", agent_id="product_owner", description="Scope"),
            AgentTask(task_id="t2", agent_id="backend", description="API"),
        ]
        call_count = {"n": 0}

        def cancel_after_first_phase():
            call_count["n"] += 1
            return call_count["n"] > 1  # bricht NACH der ersten vollständigen Phase ab

        results_first, _, _, cancelled = asyncio.run(
            self.orchestrator._run_department_hierarchy(
                user_request="Baue eine App", task_summary="App", agent_tasks=agent_tasks,
                project_dir=self.tmp_dir, notify=lambda msg: None,
                cancel_requested=cancel_after_first_phase, enable_phase_checkpoint=True,
            )
        )
        self.assertTrue(cancelled)
        checkpoint = load_checkpoint(self.tmp_dir)
        self.assertIsNotNone(checkpoint)
        self.assertGreater(len(checkpoint["completed_phases"]), 0)

        # Zweiter Aufruf für DASSELBE Verzeichnis: die bereits abgeschlossene(n) Phase(n)
        # dürfen NICHT erneut ausgeführt werden.
        results_second, _, _, _ = asyncio.run(
            self.orchestrator._run_department_hierarchy(
                user_request="Baue eine App", task_summary="App", agent_tasks=agent_tasks,
                project_dir=self.tmp_dir, notify=lambda msg: None,
                enable_phase_checkpoint=True,
            )
        )
        first_agent_ids = {r.agent_id for r in results_first}
        second_agent_ids = {r.agent_id for r in results_second}
        self.assertTrue(first_agent_ids.isdisjoint(second_agent_ids) or not first_agent_ids)

    def test_full_completion_clears_checkpoint(self):
        agent_tasks = [AgentTask(task_id="t1", agent_id="product_owner", description="Scope")]
        asyncio.run(
            self.orchestrator._run_department_hierarchy(
                user_request="Baue eine App", task_summary="App", agent_tasks=agent_tasks,
                project_dir=self.tmp_dir, notify=lambda msg: None, enable_phase_checkpoint=True,
            )
        )
        self.assertIsNone(load_checkpoint(self.tmp_dir))


if __name__ == "__main__":
    unittest.main()
