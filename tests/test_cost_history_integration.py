"""
tests/test_cost_history_integration.py – Testet die Kosten-Historie-Integration in
agents/orchestrator.py.process()

Realer Fund: core/token_guard.py ist ein reiner In-Memory-Zähler für den GESAMTEN Prozess –
ein zweiter Lauf in derselben Sitzung darf beim Schreiben in memory/cost_history.py NICHT den
ersten Lauf erneut mitzählen. process() berechnet deshalb den Pro-Modell-DELTA seit
Laufbeginn (Orchestrator._model_usage_deltas()), nicht den Gesamtzähler des Prozesses.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agents.orchestrator as orch_module
import agents.orchestrator.budget as orch_budget_module
import memory.cost_history as cost_history_module
from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.token_guard import TokenGuard
from core.workspace import WorkspaceManager
from memory.cost_history import get_lifetime_totals

TOKENS_PER_CALL = 100


class _TokenBurningFakeLLM:
    """Verbucht Tokens über denselben token_guard, den agents/orchestrator.py liest –
    dasselbe Muster wie tests/test_run_budget_cap.py."""

    def __init__(self, label: str):
        self.label = label
        self.model_name = "fake-model"

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        orch_module.token_guard.record_usage(self.model_name, TOKENS_PER_CALL, 0)
        return LLMResponse(text=f"[{self.label}] Fertig.", model_name=self.model_name,
                            prompt_tokens=TOKENS_PER_CALL, completion_tokens=0,
                            total_tokens=TOKENS_PER_CALL, tool_calls=[])

    async def generate_with_usage(self, prompt, system_prompt=None):
        orch_module.token_guard.record_usage(self.model_name, TOKENS_PER_CALL, 0)
        return LLMResponse(text=f"[{self.label}] Fertig.", model_name=self.model_name,
                            prompt_tokens=TOKENS_PER_CALL, completion_tokens=0, total_tokens=TOKENS_PER_CALL)


class TestModelUsageDeltasHelper(unittest.TestCase):
    """Unit-Test der reinen Delta-Berechnung, isoliert von einem vollen process()-Lauf."""

    def setUp(self):
        self._fresh_guard = TokenGuard()
        guard_patch = patch.object(orch_module, "token_guard", self._fresh_guard)
        guard_patch.start()
        self.addCleanup(guard_patch.stop)
        # BudgetMixin (agents/orchestrator/budget.py) hält eine EIGENE token_guard-Referenz -
        # muss separat auf denselben frischen Zähler gepatcht werden (siehe test_run_budget_cap.py).
        guard_patch_budget = patch.object(orch_budget_module, "token_guard", self._fresh_guard)
        guard_patch_budget.start()
        self.addCleanup(guard_patch_budget.stop)

    def test_delta_for_a_brand_new_model_equals_its_full_usage(self):
        start_stats = orch_module.token_guard.get_summary()["models"]  # leer
        orch_module.token_guard.record_usage("claude-sonnet-5", 500, 200)

        deltas = orch_module.Orchestrator._model_usage_deltas(start_stats)

        self.assertEqual(deltas["claude-sonnet-5"]["total_tokens"], 700)

    def test_delta_excludes_usage_recorded_before_the_snapshot(self):
        orch_module.token_guard.record_usage("claude-sonnet-5", 1000, 0)  # "vorherige Sitzung/Lauf"
        start_stats = orch_module.token_guard.get_summary()["models"]
        orch_module.token_guard.record_usage("claude-sonnet-5", 500, 200)  # "dieser Lauf"

        deltas = orch_module.Orchestrator._model_usage_deltas(start_stats)

        self.assertEqual(deltas["claude-sonnet-5"]["total_tokens"], 700)  # nur der NEUE Teil

    def test_delta_includes_cache_read_and_write_tokens(self):
        """
        Realer Fund: cache_read_tokens/cache_write_tokens fehlten hier bisher komplett im
        zurückgegebenen Delta-Dict - record_run_usage() erhielt dadurch für jedes Modell IMMER
        ein Delta von 0 für beide Werte, selbst wenn Prompt-Caching tatsächlich Cache-Treffer
        hatte (core/token_guard.py zählt sie längst korrekt mit).
        """
        start_stats = orch_module.token_guard.get_summary()["models"]  # leer
        orch_module.token_guard.record_usage("claude-sonnet-5", 500, 200, cache_read_tokens=300, cache_write_tokens=50)

        deltas = orch_module.Orchestrator._model_usage_deltas(start_stats)

        self.assertEqual(deltas["claude-sonnet-5"]["cache_read_tokens"], 300)
        self.assertEqual(deltas["claude-sonnet-5"]["cache_write_tokens"], 50)


class TestCostHistoryReachesOrchestrator(unittest.TestCase):
    def setUp(self):
        self._fresh_guard = TokenGuard()
        guard_patch = patch.object(orch_module, "token_guard", self._fresh_guard)
        guard_patch.start()
        self.addCleanup(guard_patch.stop)
        # BudgetMixin (agents/orchestrator/budget.py) hält eine EIGENE token_guard-Referenz -
        # muss separat auf denselben frischen Zähler gepatcht werden (siehe test_run_budget_cap.py).
        guard_patch_budget = patch.object(orch_budget_module, "token_guard", self._fresh_guard)
        guard_patch_budget.start()
        self.addCleanup(guard_patch_budget.stop)

        self.temp_workspace = tempfile.mkdtemp()
        self.temp_cost_dir = tempfile.mkdtemp()
        cost_file_patch = patch.object(
            cost_history_module, "COST_HISTORY_FILE", Path(self.temp_cost_dir) / "cost_history.json",
        )
        cost_file_patch.start()
        self.addCleanup(cost_file_patch.stop)

        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _TokenBurningFakeLLM(agent.agent_id)

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.temp_cost_dir, ignore_errors=True)

    def _run(self):
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose):
            task = AgentTask(task_id="t1", agent_id="backend", description="Etwas bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "cost_test_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            return asyncio.run(self.orchestrator.process("Baue etwas"))

        return _inner()

    def test_single_run_is_recorded_to_lifetime_history(self):
        self._run()
        totals = get_lifetime_totals()
        self.assertIn("fake-model", totals["models"])
        self.assertGreater(totals["models"]["fake-model"]["total_tokens"], 0)
        self.assertEqual(totals["runs_recorded"], 1)

    def test_second_run_in_same_session_adds_only_its_own_usage(self):
        self._run()
        after_first = get_lifetime_totals()["models"]["fake-model"]["total_tokens"]

        self._run()
        after_second = get_lifetime_totals()["models"]["fake-model"]["total_tokens"]

        added_by_second_run = after_second - after_first
        # Identischer Task/Mocks -> jeder Lauf trägt exakt gleich viel bei, statt den
        # gesamten bisherigen Prozess-Zähler (der beide Läufe enthält) erneut zu addieren.
        self.assertEqual(added_by_second_run, after_first)
        self.assertEqual(get_lifetime_totals()["runs_recorded"], 2)


if __name__ == "__main__":
    unittest.main()
