"""
tests/test_agents_parallel_dispatch.py – Testet die Exception-Härtung in
DispatchMixin._run_agents_parallel() (agents/orchestrator/dispatch.py) und die
Parallelisierung unabhängiger Fachbereiche (content_lead/qa_lead) in
DepartmentMixin._run_department_hierarchy() (agents/orchestrator/department.py).

Realer Fund (KI-Team-Analyse, Punkt 4): asyncio.gather(..., return_exceptions=False) hätte bei
einer durchschlagenden Exception in EINEM parallelen Branch (z.B. devops) den GESAMTEN Aufruf
abgebrochen und dabei auch bereits fertige Ergebnisse anderer, unabhängig laufender Branches
(z.B. frontend/backend) verworfen - obwohl agent.execute() Exceptions in der Praxis bereits
selbst abfängt, ist return_exceptions=True + saubere Nachbehandlung die korrekte Absicherung
gegen genau diesen Fall.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.workspace import WorkspaceManager


class _FakeLLM:
    def __init__(self, agent_id: str, delay: float = 0.0):
        self.agent_id = agent_id
        self.model_name = "fake-model"
        self.delay = delay

    async def generate_with_usage(self, prompt: str, system_prompt: str = "") -> LLMResponse:
        if self.delay:
            await asyncio.sleep(self.delay)
        return LLMResponse(
            text=f"Fertig von {self.agent_id}.", model_name=self.model_name,
            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[],
        )

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        if self.delay:
            await asyncio.sleep(self.delay)
        return LLMResponse(
            text=f"Fertig von {self.agent_id}.", model_name=self.model_name,
            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[],
        )


class TestRunAgentsParallelExceptionHardening(unittest.TestCase):
    def setUp(self):
        self.orchestrator = Orchestrator()

    def test_one_task_raising_does_not_lose_the_others_results(self):
        good_task = AgentTask(task_id="t1", agent_id="backend", description="ok")
        bad_task = AgentTask(task_id="t2", agent_id="frontend", description="boom")

        async def fake_run_single_agent(task):
            if task.agent_id == "frontend":
                raise RuntimeError("unerwarteter Absturz")
            from core.message_bus import AgentResult
            return AgentResult(task_id=task.task_id, agent_id=task.agent_id, agent_name=task.agent_id, success=True, content="ok")

        with patch.object(self.orchestrator, "_run_single_agent", side_effect=fake_run_single_agent):
            results = asyncio.run(self.orchestrator._run_agents_parallel([good_task, bad_task], notify=lambda msg: None))

        self.assertEqual(len(results), 2)
        by_agent = {r.agent_id: r for r in results}
        self.assertTrue(by_agent["backend"].success)
        self.assertFalse(by_agent["frontend"].success)
        self.assertIn("unerwarteter Absturz", by_agent["frontend"].error)


class TestContentAndQaLeadRunConcurrently(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeLLM(agent.agent_id, delay=0.2)

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def test_content_lead_and_qa_lead_overlap_in_wall_clock_time(self):
        # Team-Optimierung (Parallelisierung unabhängiger Fachbereiche): content_lead (Doku)
        # und qa_lead (DevOps/Tests) laufen jetzt gleichzeitig statt strikt sequentiell - mit
        # je einem künstlich verzögerten Mitglied muss die Gesamtlaufzeit deutlich UNTER der
        # Summe beider Einzellaufzeiten liegen, sonst liefe hier weiterhin alles sequentiell.
        agent_tasks = [
            AgentTask(task_id="t_doc", agent_id="documentation", description="Doku erstellen"),
            AgentTask(task_id="t_devops", agent_id="devops", description="CI/CD einrichten"),
        ]

        import time
        t0 = time.monotonic()
        results, file_owners, budget_aborted, cancelled = asyncio.run(
            self.orchestrator._run_department_hierarchy(
                user_request="Kleines Projekt", task_summary="Kleines Projekt",
                agent_tasks=agent_tasks, project_dir=self.temp_workspace, notify=lambda msg: None,
            )
        )
        elapsed = time.monotonic() - t0

        self.assertFalse(budget_aborted)
        self.assertFalse(cancelled)
        agent_ids = {r.agent_id for r in results}
        self.assertIn("documentation", agent_ids)
        self.assertIn("devops", agent_ids)
        # Jede Phase allein bräuchte inkl. Delegation+Konsolidierung mehrere Aufrufe à 0.2s -
        # laufen beide Phasen wirklich parallel, bleibt die Gesamtzeit klar unter 1s.
        self.assertLess(elapsed, 1.0, msg=f"content_lead/qa_lead liefen offenbar sequentiell ({elapsed:.2f}s)")


if __name__ == "__main__":
    unittest.main()
