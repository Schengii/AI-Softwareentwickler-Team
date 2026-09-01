"""
tests/test_project_token_budget.py – Testet das Pro-Projekt-Kostenbudget
(`/constitution` `max_project_tokens`, agents/orchestrator.py)

Realer struktureller Fund: das bestehende MAX_RUN_TOKENS (siehe test_run_budget_cap.py)
begrenzt nur EINEN einzelnen Lauf – ein Projekt mit vielen aufeinanderfolgenden Läufen (z.B.
für einen externen Auftraggeber mit festem Kostenrahmen) hatte bisher kein Limit über ALLE
Läufe hinweg. core/project_constitution.py (max_project_tokens) + memory/run_history.py
(bereits vorhandene, project_slug-gefilterte Lauf-Historie) schließen diese Lücke, unabhängig
vom globalen Lauf-Budget.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agents.orchestrator as orch_module
import agents.orchestrator.budget as orch_budget_module
from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.project_constitution import write_constitution
from core.token_guard import TokenGuard
from core.verifier import VerificationReport
from core.workspace import WorkspaceManager

TOKENS_PER_CALL = 5000


class _TokenBurningFakeLLM:
    """Wie in test_run_budget_cap.py: verbucht Tokens über denselben token_guard, den
    agents/orchestrator.py für die Budget-Prüfung liest."""

    def __init__(self, label: str):
        self.label = label
        self.model_name = "fake-model"

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        orch_module.token_guard.record_usage(self.model_name, TOKENS_PER_CALL, 0)
        return LLMResponse(
            text=f"[{self.label}] verarbeitet.", model_name=self.model_name,
            prompt_tokens=TOKENS_PER_CALL, completion_tokens=0, total_tokens=TOKENS_PER_CALL, tool_calls=[],
        )

    async def generate_with_usage(self, prompt, system_prompt=None):
        orch_module.token_guard.record_usage(self.model_name, TOKENS_PER_CALL, 0)
        return LLMResponse(
            text=f"[{self.label}] verarbeitet.", model_name=self.model_name,
            prompt_tokens=TOKENS_PER_CALL, completion_tokens=0, total_tokens=TOKENS_PER_CALL,
        )


class TestBudgetHelperMethods(unittest.TestCase):
    """Reine Logiktests der neuen Instanzmethoden, ohne Agenten-Ausführung."""

    def setUp(self):
        self.orchestrator = Orchestrator()
        self.orchestrator.last_project_slug = "kunde_x"

    def test_disabled_by_default(self):
        self.assertFalse(self.orchestrator._project_budget_exceeded(0))

    def test_exceeded_when_prior_plus_current_reaches_budget(self):
        self.orchestrator._project_token_budget = 10_000
        self.orchestrator._project_tokens_before_run = 9_000
        with patch.object(Orchestrator, "_tokens_used_since", return_value=1_000):
            self.assertTrue(self.orchestrator._project_budget_exceeded(0))

    def test_not_exceeded_below_budget(self):
        self.orchestrator._project_token_budget = 10_000
        self.orchestrator._project_tokens_before_run = 1_000
        with patch.object(Orchestrator, "_tokens_used_since", return_value=500):
            self.assertFalse(self.orchestrator._project_budget_exceeded(0))

    def test_label_prefers_project_budget_when_that_is_the_binding_constraint(self):
        self.orchestrator._project_token_budget = 5_000
        self.orchestrator._project_tokens_before_run = 5_000
        with patch.object(Orchestrator, "_tokens_used_since", return_value=0), \
             patch("agents.orchestrator.budget.MAX_RUN_TOKENS", 0):
            label = self.orchestrator._budget_exceeded_label(0)
        self.assertIn("Projekt-Budget", label)
        self.assertIn("kunde_x", label)

    def test_label_falls_back_to_run_budget_when_project_budget_not_exceeded(self):
        self.orchestrator._project_token_budget = 0
        with patch("agents.orchestrator.budget.MAX_RUN_TOKENS", 50_000):
            label = self.orchestrator._budget_exceeded_label(0)
        self.assertIn("Lauf-Budget", label)
        self.assertIn("MAX_RUN_TOKENS", label)


class TestDepartmentHierarchyRespectsProjectBudget(unittest.TestCase):
    """Wie test_run_budget_cap.py, aber für das Projekt- statt das Lauf-Budget."""

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

        self.orchestrator = Orchestrator()
        self.orchestrator.last_project_slug = "kunde_x"
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _TokenBurningFakeLLM(agent.agent_id)

    def test_project_budget_aborts_even_when_run_budget_is_disabled(self):
        agent_tasks = [
            AgentTask(task_id="t1", agent_id="product_owner", description="Scope"),
            AgentTask(task_id="t2", agent_id="backend", description="API"),
            AgentTask(task_id="t3", agent_id="ui_ux", description="UI"),
            AgentTask(task_id="t4", agent_id="tester", description="Tests"),
            AgentTask(task_id="t5", agent_id="compliance", description="DSGVO-Check"),
        ]
        # Phase 1 (planning_lead) verbraucht 3 Aufrufe x 5.000 = 15.000 Tokens -> übersteigt
        # das 8.000-Projekt-Budget, obwohl MAX_RUN_TOKENS deaktiviert ist.
        self.orchestrator._project_token_budget = 8000
        self.orchestrator._project_tokens_before_run = 0
        with patch.object(orch_budget_module, "MAX_RUN_TOKENS", 0):
            results, _fo, budget_aborted, _cancelled = asyncio.run(self.orchestrator._run_department_hierarchy(
                user_request="Baue eine Todo-App", task_summary="Todo-App", agent_tasks=agent_tasks,
                project_dir=".", run_start_tokens=0, notify=lambda msg: None,
            ))

        self.assertTrue(budget_aborted)
        result_agent_ids = [r.agent_id for r in results]
        self.assertIn("planning_lead", result_agent_ids)
        self.assertNotIn("dev_lead", result_agent_ids)

    def test_prior_usage_from_earlier_runs_counts_toward_the_budget(self):
        agent_tasks = [
            AgentTask(task_id="t1", agent_id="backend", description="API"),
            AgentTask(task_id="t2", agent_id="tester", description="Tests"),
            AgentTask(task_id="t3", agent_id="compliance", description="DSGVO-Check"),
        ]
        # Bereits 7.000 Tokens aus FRÜHEREN Läufen an diesem Projekt verbraucht - ein einziger
        # weiterer Aufruf (5.000 Tokens) in DIESEM Lauf reicht, um das 10.000-Budget zu reißen.
        self.orchestrator._project_token_budget = 10_000
        self.orchestrator._project_tokens_before_run = 7_000
        with patch.object(orch_budget_module, "MAX_RUN_TOKENS", 0):
            _results, _fo, budget_aborted, _cancelled = asyncio.run(self.orchestrator._run_department_hierarchy(
                user_request="Baue etwas", task_summary="X", agent_tasks=agent_tasks,
                project_dir=".", run_start_tokens=0, notify=lambda msg: None,
            ))
        self.assertTrue(budget_aborted)

    def test_disabled_project_budget_has_no_effect(self):
        agent_tasks = [
            AgentTask(task_id="t1", agent_id="backend", description="API"),
            AgentTask(task_id="t2", agent_id="tester", description="Tests"),
        ]
        self.orchestrator._project_token_budget = 0  # Standard: kein Projekt-Budget aktiv
        with patch.object(orch_budget_module, "MAX_RUN_TOKENS", 0):
            _results, _fo, budget_aborted, _cancelled = asyncio.run(self.orchestrator._run_department_hierarchy(
                user_request="Baue etwas", task_summary="X", agent_tasks=agent_tasks,
                project_dir=".", run_start_tokens=0, notify=lambda msg: None,
            ))
        self.assertFalse(budget_aborted)


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


class TestProcessAbortsBeforeRunWhenProjectBudgetAlreadyExhausted(unittest.TestCase):
    """Vollständiger Orchestrator.process()-Lauf (Muster aus test_governance_fix_loop.py):
    ein VOR Laufbeginn bereits erschöpftes Projekt-Budget darf keinen einzigen Agenten starten."""

    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def test_exhausted_project_budget_blocks_the_run_entirely(self):
        project_dir = Path(self.temp_workspace) / "kunde_projekt"
        project_dir.mkdir()
        write_constitution(str(project_dir), {"max_project_tokens": "1000"})

        tasks = [AgentTask(task_id="t1", agent_id="backend", description="Baue etwas")]

        with patch("core.task_manager.TaskManager.decompose") as mock_decompose, \
             patch("agents.orchestrator.get_total_tokens_for_project", return_value=1000), \
             patch.object(Orchestrator, "_run_department_hierarchy") as mock_hierarchy:
            mock_decompose.return_value = ("Kurze Aufgabe", "kunde_projekt", tasks)
            result = asyncio.run(self.orchestrator.process("Baue etwas"))

        mock_hierarchy.assert_not_called()
        self.assertIn("Projekt-Budget erschöpft", result)
        self.assertIn("1,000", result)  # bereits verbrauchte Tokens

    def test_project_budget_not_yet_exhausted_lets_the_run_start(self):
        project_dir = Path(self.temp_workspace) / "kunde_projekt2"
        project_dir.mkdir()
        write_constitution(str(project_dir), {"max_project_tokens": "1000000"})

        tasks = [AgentTask(task_id="t1", agent_id="backend", description="Baue etwas")]

        with patch("core.task_manager.TaskManager.decompose") as mock_decompose, \
             patch("agents.orchestrator.get_total_tokens_for_project", return_value=100), \
             patch("agents.orchestrator.verification.ProjectVerifier") as mock_verifier_cls, \
             patch("core.result_aggregator.ResultAggregator.synthesize") as mock_synthesize, \
             patch.object(Orchestrator, "_run_department_hierarchy") as mock_hierarchy:
            mock_decompose.return_value = ("Kurze Aufgabe", "kunde_projekt2", tasks)
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
            )
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_lint.return_value = []
            mock_hierarchy.return_value = ([], {}, False, False)
            asyncio.run(self.orchestrator.process("Baue etwas"))

        mock_hierarchy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
