"""
tests/test_agent_trainer_triggered_by_underperformer.py – Testet, dass der Agent-Trainer
automatisch ausgelöst wird, wenn der Optimization-Advisor dauerhaft schlechte Agenten
identifiziert – auch wenn der laufende Lauf selbst technisch grün ist.

Team-Optimierung (KI-Team-Analyse 07.09.2026, Punkt 1):
Bisher wurde der Trainer NICHT ausgelöst, wenn verification_ok=True und alle Agenten
technisch erfolgreich waren – obwohl z.B. der `tester` seit Wochen bei 57% Erfolgsquote lag.
Nach der Änderung in agents/orchestrator/retrospective.py/_run_agent_trainer_self_optimization()
wird der Trainer jetzt auch bei `optimization_hints` ausgelöst (low_performing_agents aus dem
Optimization-Advisor) und erhält den Underperformer-Kontext im Task.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.optimization_advisor import LowPerformingAgent, OptimizationReport
from core.verifier import VerificationReport
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


class TestAgentTrainerTriggeredByUnderperformer(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run_with_underperformer(self, report: OptimizationReport):
        @patch("agents.orchestrator.analyze_optimization_potential", return_value=report)
        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls, mock_analyze):
            task = AgentTask(task_id="t1", agent_id="backend", description="Etwas bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "underperf_test_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            # Alles technisch grün – kein Fehler, keine fehlgeschlagenen Tests
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
            )
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_sast.return_value = []
            mock_verifier.check_licenses.return_value = []
            mock_verifier.check_lint.return_value = []
            mock_verifier.check_runtime_smoke.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_browser_ui.return_value.attempted = False
            mock_verifier.check_accessibility.return_value.attempted = False
            mock_verifier.check_coverage.return_value.attempted = False
            mock_verifier.check_completeness.return_value.passed = True
            mock_verifier.check_completeness.return_value.issues = []
            mock_verifier.check_api_contracts.return_value.passed = True
            mock_verifier.check_api_contracts.return_value.mismatches = []

            # Tatsächlichen Trainer-Aufruf belauschen
            original_execute = self.orchestrator._agents["agent_trainer"].execute
            execute_calls = []
            async def _spy_execute(task_arg):
                execute_calls.append(task_arg)
                return await original_execute(task_arg)

            self.orchestrator._agents["agent_trainer"].execute = _spy_execute
            asyncio.run(self.orchestrator.process("Baue etwas"))
            return execute_calls

        return _inner()

    def test_trainer_is_triggered_with_underperformer_hints(self):
        """Agent-Trainer soll auch bei grünem Lauf ausgelöst werden, wenn ein Agent chronisch schlechte Erfolgsquote hat."""
        report = OptimizationReport(
            low_performing_agents=[
                LowPerformingAgent(agent_id="tester", success_rate=57.1, calls=7, team_average=85.7),
            ],
        )
        trainer_calls = self._run_with_underperformer(report)

        # Trainer MUSS aufgerufen worden sein – auch ohne Lauf-Fehler
        self.assertGreater(len(trainer_calls), 0,
            "Agent-Trainer wurde nicht ausgelöst, obwohl ein dauerhafter Underperformer vorliegt.")
        # Der Kontext muss den Underperformer erwähnen
        context = trainer_calls[0].context
        self.assertIn("tester", context, "Underperformer 'tester' fehlt im Trainer-Kontext.")
        self.assertIn("57.1", context, "Erfolgsquote des Underperformers fehlt im Trainer-Kontext.")
        self.assertIn("UNDERPERFORMER", context.upper(), "Underperformer-Abschnitt fehlt im Trainer-Kontext.")

    def test_trainer_not_triggered_without_underperformer_and_green_run(self):
        """Agent-Trainer soll NICHT ausgelöst werden, wenn der Lauf grün ist und kein Underperformer vorliegt."""
        report = OptimizationReport()  # Leer – kein Underperformer
        trainer_calls = self._run_with_underperformer(report)

        self.assertEqual(len(trainer_calls), 0,
            "Agent-Trainer wurde unnötigerweise ausgelöst, obwohl Lauf grün und kein Underperformer.")


if __name__ == "__main__":
    unittest.main()
