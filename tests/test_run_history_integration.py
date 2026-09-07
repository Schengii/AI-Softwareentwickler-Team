"""
tests/test_run_history_integration.py – Testet die Lauf-Historie-Integration in
agents/orchestrator.py.process() (Observability über Zeit)

Realer Fund bei einer Bestandsaufnahme des eigenen Teams: das Web-Dashboard zeigte bisher nur
den aktuellen/letzten Job, keine Trends über die Zeit. agents/orchestrator.py.process()
speichert jetzt nach jedem Lauf eine kompakte Zusammenfassung in memory/run_history.py -
selbes Integrationsmuster wie test_cost_history_integration.py.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import memory.run_history as run_history_module
from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.workspace import WorkspaceManager
from memory.run_history import get_agent_success_rates, get_recent_runs


class _FakeLLM:
    def __init__(self, label: str, succeed: bool = True):
        self.label = label
        # Bewusst NICHT "fake-model" (das in praktisch jeder anderen Testdatei dieser Suite
        # verwendete generische Fake-LLM-Modellname): memory/run_history.py._is_real_run()
        # filtert genau diesen Namen seit der KI-Team-Analyse 07.09.2026 (Punkt 5, "Fake-Model
        # in Testzyklen") aus jeder Optimierungsberechnung heraus, um die reale
        # memory/run_history.json vor Test-Rauschen zu schützen. Dieser Test prüft die reine
        # Lese-Plumbing von get_agent_success_rates() selbst, nicht die Fake-Model-Filterung -
        # ein anderer, nicht gefilterter Modellname hält beide Anliegen sauber getrennt.
        self.model_name = "test-stub-model"
        self._succeed = succeed

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        return LLMResponse(text=f"[{self.label}] Fertig.", model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[])

    async def generate_with_usage(self, prompt, system_prompt=None):
        return LLMResponse(text=f"[{self.label}] Fertig.", model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15)


class TestRunHistoryReachesOrchestrator(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.temp_history_dir = tempfile.mkdtemp()
        self._patcher = patch.object(
            run_history_module, "RUN_HISTORY_FILE", Path(self.temp_history_dir) / "run_history.json",
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeLLM(agent.agent_id)

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_history_dir, ignore_errors=True)

    def _run(self):
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose):
            task = AgentTask(task_id="t1", agent_id="backend", description="Etwas bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "run_history_test_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            return asyncio.run(self.orchestrator.process("Baue etwas"))

        return _inner()

    def test_completed_run_is_recorded_with_project_and_agent_results(self):
        self._run()

        runs = get_recent_runs()

        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["project_slug"], "run_history_test_proj")
        self.assertGreater(runs[0]["total_tokens"], 0)
        agent_ids = {r["agent_id"] for r in runs[0]["agent_results"]}
        self.assertIn("backend", agent_ids)

    def test_agent_success_rates_reflect_the_run(self):
        self._run()

        rates = get_agent_success_rates()

        backend = next(r for r in rates if r["agent_id"] == "backend")
        self.assertEqual(backend["calls"], 1)
        self.assertEqual(backend["successes"], 1)

    def test_two_runs_both_appear_in_history(self):
        self._run()
        self._run()

        self.assertEqual(len(get_recent_runs(limit=100)), 2)


if __name__ == "__main__":
    unittest.main()
