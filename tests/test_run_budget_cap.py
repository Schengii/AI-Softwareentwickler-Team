"""
tests/test_run_budget_cap.py – Testet das harte Lauf-Budget (config.MAX_RUN_TOKENS)

core/quota_estimator.py zeigte Tokenverbrauch bisher nur an, OHNE dass ein Lauf jemals
automatisch abgebrochen wurde – auch nicht bei kostenpflichtigen Modellen ohne dauerhaftes
Gratis-Kontingent (z.B. Claude). Dieser Test stellt sicher, dass agents/orchestrator.py bei
überschrittenem MAX_RUN_TOKENS tatsächlich abbricht: bereits begonnene Fachbereichs-Phasen
laufen zu Ende, aber NACHFOLGENDE Phasen werden übersprungen statt weiter Tokens (und bei
kostenpflichtigen Modellen: Geld) zu verbrauchen.
"""

import asyncio
import unittest
from unittest.mock import patch

import agents.orchestrator as orch_module
from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.token_guard import TokenGuard

TOKENS_PER_CALL = 5000


class _TokenBurningFakeLLM:
    """
    Simuliert einen echten Provider-Aufruf: verbucht Tokens über denselben token_guard,
    den agents/orchestrator.py für die Budget-Prüfung liest (core/llm_factory.py tut dies bei
    echten Providern genauso über token_guard.record_usage()).
    """

    def __init__(self, label: str):
        self.label = label
        self.model_name = "fake-model"

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        orch_module.token_guard.record_usage(self.model_name, TOKENS_PER_CALL, 0)
        return LLMResponse(
            text=f"[{self.label}] verarbeitet.", model_name=self.model_name,
            prompt_tokens=TOKENS_PER_CALL, completion_tokens=0,
            total_tokens=TOKENS_PER_CALL, tool_calls=[],
        )

    async def generate_with_usage(self, prompt, system_prompt=None):
        orch_module.token_guard.record_usage(self.model_name, TOKENS_PER_CALL, 0)
        return LLMResponse(
            text=f"[{self.label}] verarbeitet.", model_name=self.model_name,
            prompt_tokens=TOKENS_PER_CALL, completion_tokens=0, total_tokens=TOKENS_PER_CALL,
        )


class TestRunBudgetCap(unittest.TestCase):
    def setUp(self):
        # Frischer, isolierter Token-Zähler pro Test statt des globalen Singletons, das sich
        # sonst über die gesamte Testsuite hinweg (test-Reihenfolge-abhängig) aufsummiert.
        self._fresh_guard = TokenGuard()
        guard_patch = patch.object(orch_module, "token_guard", self._fresh_guard)
        guard_patch.start()
        self.addCleanup(guard_patch.stop)

        self.orchestrator = Orchestrator()
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _TokenBurningFakeLLM(agent.agent_id)

    def test_disabled_by_default_runs_all_phases(self):
        """MAX_RUN_TOKENS=0 (Standard) darf bestehende Läufe nicht beeinflussen."""
        agent_tasks = [
            AgentTask(task_id="t1", agent_id="product_owner", description="Scope"),
            AgentTask(task_id="t2", agent_id="compliance", description="DSGVO-Check"),
        ]
        with patch.object(orch_module, "MAX_RUN_TOKENS", 0):
            results, _, budget_aborted, _cancelled = asyncio.run(self.orchestrator._run_department_hierarchy(
                user_request="Baue eine App", task_summary="App", agent_tasks=agent_tasks,
                project_dir=".", run_start_tokens=0, notify=lambda msg: None,
            ))
        self.assertFalse(budget_aborted)
        result_agent_ids = [r.agent_id for r in results]
        self.assertIn("planning_lead", result_agent_ids)
        self.assertIn("governance_lead", result_agent_ids)  # letzte Phase lief noch komplett durch

    def test_hierarchy_stops_before_later_phases_once_budget_exceeded(self):
        # Ein Task pro Fachbereich, in PHASE_ORDER-Reihenfolge: planning -> design -> dev -> content -> qa -> governance.
        agent_tasks = [
            AgentTask(task_id="t1", agent_id="product_owner", description="Scope"),
            AgentTask(task_id="t2", agent_id="ui_ux", description="UI"),
            AgentTask(task_id="t3", agent_id="backend", description="API"),
            AgentTask(task_id="t4", agent_id="documentation", description="Doku"),
            AgentTask(task_id="t5", agent_id="tester", description="Tests"),
            AgentTask(task_id="t6", agent_id="compliance", description="DSGVO-Check"),
        ]
        # Phase 1 (planning_lead) verbraucht bereits 3 Aufrufe x 5.000 = 15.000 Tokens
        # (Delegation + product_owner + Konsolidierung) -> übersteigt das 8.000-Budget deutlich,
        # sodass ALLE nachfolgenden Phasen übersprungen werden müssen.
        with patch.object(orch_module, "MAX_RUN_TOKENS", 8000):
            results, file_owners, budget_aborted, _cancelled = asyncio.run(self.orchestrator._run_department_hierarchy(
                user_request="Baue eine Todo-App", task_summary="Todo-App", agent_tasks=agent_tasks,
                project_dir=".", run_start_tokens=0, notify=lambda msg: None,
            ))

        self.assertTrue(budget_aborted)
        result_agent_ids = [r.agent_id for r in results]

        # Phase 1 (bereits begonnen, als das Budget geprüft wurde) lief noch vollständig durch.
        self.assertIn("planning_lead", result_agent_ids)
        self.assertIn("product_owner", result_agent_ids)

        # Alle nachfolgenden Phasen (2-6) wurden NICHT mehr gestartet.
        for skipped_id in ("design_lead", "ui_ux", "dev_lead", "backend", "content_lead", "documentation", "qa_lead", "tester", "governance_lead", "compliance"):
            self.assertNotIn(skipped_id, result_agent_ids, f"'{skipped_id}' hätte nach Budget-Überschreitung nicht mehr laufen dürfen")

    def test_tokens_used_since_reflects_only_delta(self):
        orch_module.token_guard.record_usage("fake-model", 1000, 500)
        start = orch_module.token_guard.get_summary()["grand_total_tokens"]
        orch_module.token_guard.record_usage("fake-model", 2000, 0)
        self.assertEqual(Orchestrator._tokens_used_since(start), 2000)

    def test_budget_check_disabled_when_max_run_tokens_zero(self):
        with patch.object(orch_module, "MAX_RUN_TOKENS", 0):
            orch_module.token_guard.record_usage("fake-model", 10**9, 0)  # absurd hoher Verbrauch
            self.assertFalse(Orchestrator._run_budget_exceeded(0))


if __name__ == "__main__":
    unittest.main()
