"""
tests/test_optimization_advisor_integration.py – Testet die Anbindung von
core/optimization_advisor.py an agents/orchestrator.py.process()

Nutzerwunsch: der Bericht soll automatisch am Ende jedes Laufs erscheinen, wenn es einen
statistisch aussagekräftigen Befund gibt - und für die Mehrheit der Läufe ohne einen solchen
Befund unsichtbar bleiben (kein unnötiger Abschnitt). Rein additiv, ändert nichts an config.py.
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


class TestOptimizationAdvisorInProcess(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, report: OptimizationReport):
        @patch("agents.orchestrator.analyze_optimization_potential", return_value=report)
        @patch("agents.orchestrator.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls, mock_analyze):
            task = AgentTask(task_id="t1", agent_id="backend", description="Etwas bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "opt_test_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value.ran = False
            mock_verifier.run_tests.return_value.reason_skipped = "Keine Tests gefunden."
            mock_verifier.check_docker_build.return_value.attempted = False

            return asyncio.run(self.orchestrator.process("Baue etwas"))

        return _inner()

    def test_non_empty_report_appears_in_final_output(self):
        report = OptimizationReport(
            low_performing_agents=[
                LowPerformingAgent(agent_id="backend", success_rate=20.0, calls=5, team_average=85.0),
            ],
        )
        result = self._run(report)

        self.assertIn("Selbstoptimierungs-Vorschläge", result)
        self.assertIn("backend", result)
        self.assertIn("keine automatische Änderung", result)

    def test_empty_report_adds_no_noise_to_final_output(self):
        result = self._run(OptimizationReport())

        self.assertNotIn("Selbstoptimierungs-Vorschläge", result)


if __name__ == "__main__":
    unittest.main()
