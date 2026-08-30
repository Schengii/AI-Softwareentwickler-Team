"""
tests/test_run_cancellation.py – Testet den kooperativen Abbruch eines laufenden Runs

Vorher: Strg+C während eines laufenden Agenten-Teams stürzte das gesamte Programm mit einem
rohen KeyboardInterrupt-Traceback ab (interface/cli.py fing das nur am Eingabe-Prompt ab,
nicht während await self._orchestrator.process(...) läuft). Kein Weg, einen sichtbar falsch
laufenden Lauf gezielt zu stoppen, außer das komplette Programm zu killen.

agents/orchestrator.py.process() akzeptiert jetzt einen optionalen cancel_requested-Callback,
der an DENSELBEN Prüfpunkten wie das bestehende MAX_RUN_TOKENS-Budget abgefragt wird (vor
jeder Fachbereichs-Phase, vor jedem Verifikations-/Fixversuch) – dieselbe Graceful-
Degradation (verbleibende Arbeit überspringen, bereits Erarbeitetes trotzdem synthetisieren
und ausliefern), nur mit einem manuellen statt einem Budget-Grund.
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


class TestDepartmentHierarchyCancellation(unittest.TestCase):
    """Testet _run_department_hierarchy() direkt - echte Ausführung, kein Mock der Methode selbst."""

    def setUp(self):
        self.orchestrator = Orchestrator()
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def test_stops_before_first_phase_when_cancel_already_requested(self):
        agent_tasks = [
            AgentTask(task_id="t1", agent_id="product_owner", description="Scope"),
            AgentTask(task_id="t2", agent_id="backend", description="API"),
        ]
        results, file_owners, budget_aborted, cancelled = asyncio.run(
            self.orchestrator._run_department_hierarchy(
                user_request="Baue eine App", task_summary="App", agent_tasks=agent_tasks,
                project_dir=".", notify=lambda msg: None, cancel_requested=lambda: True,
            )
        )
        self.assertTrue(cancelled)
        self.assertFalse(budget_aborted)
        self.assertEqual(results, [])  # kein einziger Agent lief

    def test_runs_normally_when_cancel_never_requested(self):
        agent_tasks = [AgentTask(task_id="t1", agent_id="product_owner", description="Scope")]
        results, _, budget_aborted, cancelled = asyncio.run(
            self.orchestrator._run_department_hierarchy(
                user_request="Baue eine App", task_summary="App", agent_tasks=agent_tasks,
                project_dir=".", notify=lambda msg: None, cancel_requested=lambda: False,
            )
        )
        self.assertFalse(cancelled)
        self.assertGreater(len(results), 0)

    def test_none_cancel_requested_means_no_gate(self):
        agent_tasks = [AgentTask(task_id="t1", agent_id="product_owner", description="Scope")]
        results, _, budget_aborted, cancelled = asyncio.run(
            self.orchestrator._run_department_hierarchy(
                user_request="Baue eine App", task_summary="App", agent_tasks=agent_tasks,
                project_dir=".", notify=lambda msg: None,
            )
        )
        self.assertFalse(cancelled)
        self.assertGreater(len(results), 0)

    def test_lets_already_started_phase_finish_before_stopping(self):
        """Wie beim Budget-Abbruch: die BEGONNENE Phase läuft noch fertig, erst die
        NÄCHSTE wird übersprungen - kein Abwürgen mitten in laufender Agenten-Arbeit."""
        agent_tasks = [
            AgentTask(task_id="t1", agent_id="product_owner", description="Scope"),
            AgentTask(task_id="t2", agent_id="backend", description="API"),
        ]
        call_count = {"n": 0}

        def cancel_after_first_check():
            call_count["n"] += 1
            return call_count["n"] > 1  # Phase 1 (planning_lead) darf noch starten

        results, _, budget_aborted, cancelled = asyncio.run(
            self.orchestrator._run_department_hierarchy(
                user_request="Baue eine App", task_summary="App", agent_tasks=agent_tasks,
                project_dir=".", notify=lambda msg: None, cancel_requested=cancel_after_first_check,
            )
        )
        self.assertTrue(cancelled)
        result_agent_ids = [r.agent_id for r in results]
        self.assertIn("planning_lead", result_agent_ids)  # Phase 1 lief noch komplett durch
        self.assertNotIn("dev_lead", result_agent_ids)     # Phase 2 wurde übersprungen


class TestProcessReportsCancellation(unittest.TestCase):
    """Testet process() end-to-end (mit gemocktem decompose()/Aggregator) - dieselbe
    Teststruktur wie test_plan_confirmation_gate.py."""

    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, cancel_requested):
        # orchestrator.process() ruft inzwischen save_project_checkpoint() statt direkt
        # record_run() auf (core/project_status.py) - save_project_checkpoint() reicht
        # dieselben cancelled/budget_aborted-Kwargs an sein eigenes, internes record_run()
        # weiter, ist also der richtige Patch-Punkt, um dieses Verhalten weiter zu prüfen.
        @patch("agents.orchestrator.save_project_checkpoint")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_save_checkpoint):
            task = AgentTask(task_id="t1", agent_id="backend", description="Etwas bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "cancel_test_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)

            result = asyncio.run(self.orchestrator.process(
                "Baue etwas", cancel_requested=cancel_requested,
            ))
            return result, mock_save_checkpoint

        return _inner()

    def test_final_status_shows_manually_cancelled_not_generic_unverified(self):
        result, mock_save_checkpoint = self._run(lambda: True)

        self.assertIn("Manuell abgebrochen", result)
        self.assertNotIn("NICHT verifiziert", result)

    def test_record_run_receives_cancelled_flag(self):
        _, mock_save_checkpoint = self._run(lambda: True)

        mock_save_checkpoint.assert_called_once()
        self.assertTrue(mock_save_checkpoint.call_args.kwargs.get("cancelled"))
        self.assertFalse(mock_save_checkpoint.call_args.kwargs.get("budget_aborted"))

    def test_no_cancellation_reports_normal_completion(self):
        result, mock_save_checkpoint = self._run(lambda: False)

        self.assertNotIn("Manuell abgebrochen", result)
        self.assertFalse(mock_save_checkpoint.call_args.kwargs.get("cancelled"))


if __name__ == "__main__":
    unittest.main()
