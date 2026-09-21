"""
tests/test_deterministic_retrospective.py – Testet P2-4 (ROADMAP_TEMP.md): "Der Retrospektiv-
Schritt arbeitet blind"

Realer Fund (Lauf `cachegrid_proxy`): der LLM-Retrospektiv-Schritt bekam nur einen auf ~250
Zeichen je Agent gekürzten Prosa-Auszug ohne `project_dir`/Werkzeuge - 1.325 Prompt-Tokens,
0 Tool-Calls, 0 Dateien, für eine Analyse auf derselben unvollständigen Evidenz, die
core/root_cause_analyst.py mit echtem Dateizugriff ohnehin schon liefert. `_run_retrospective`
(agents/orchestrator/retrospective.py) ist jetzt "Variante B" aus dem Roadmap-Eintrag: eine rein
deterministische Kennzahlen-Zusammenfassung ohne jeden LLM-Aufruf.
"""

import asyncio
import shutil
import tempfile
import unittest

from agents.orchestrator import Orchestrator
from core.message_bus import AgentResult
from core.workspace import WorkspaceManager


class TestDeterministicRetrospective(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def test_returns_deterministic_summary_without_any_llm_call(self):
        """Der 'retrospective'-Agent (samt LLM) wird für diesen Schritt gar nicht mehr
        aufgerufen - ein Aufruf würde bei einem gepatchten LLM sofort auffallen."""
        results = [
            AgentResult(task_id="t1", agent_id="backend", agent_name="Backend", success=True, content="ok", total_tokens=100),
            AgentResult(task_id="t2", agent_id="tester", agent_name="Tester", success=False, content="", error="Timeout", total_tokens=50),
        ]

        async def _fail_if_called(*_args, **_kwargs):
            raise AssertionError("LLM darf für die Retrospektive nicht mehr aufgerufen werden")

        self.orchestrator._agents["retrospective"]._llm.generate_with_tools = _fail_if_called
        self.orchestrator._agents["retrospective"]._llm.generate_with_usage = _fail_if_called

        result = asyncio.run(self.orchestrator._run_retrospective(
            user_request="Baue etwas", results=results, total_duration=12.5,
        ))

        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertEqual(result.total_tokens, 0)
        self.assertIn("12.5s", result.content)
        self.assertIn("1/2 erfolgreich", result.content)
        self.assertIn("tester", result.content)
        self.assertIn("Timeout", result.content)

    def test_no_failures_still_produces_a_summary(self):
        results = [
            AgentResult(task_id="t1", agent_id="backend", agent_name="Backend", success=True, content="ok", total_tokens=100),
        ]

        result = asyncio.run(self.orchestrator._run_retrospective(
            user_request="Baue etwas", results=results, total_duration=1.0,
        ))

        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertNotIn("❌", result.content)

    def test_none_when_retrospective_agent_missing(self):
        del self.orchestrator._agents["retrospective"]

        result = asyncio.run(self.orchestrator._run_retrospective(
            user_request="Baue etwas", results=[], total_duration=0.0,
        ))

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
