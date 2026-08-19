"""
tests/test_mock_workflow.py – Testet den End-to-End Orchestrator Workflow mit gemockten LLM-Antworten

Seit der Einführung des agentischen Werkzeug-Loops (agents/base_agent.py) rufen
Agenten mit gesetztem project_dir generate_with_tools() statt generate_with_usage()
auf. Damit dieser Test weiterhin isoliert bleibt (keine echten API-Aufrufe, keine
echten pip/pytest-Subprozesse, keine Schreibzugriffe auf das reale workspace/-
Verzeichnis), wird jedem Agenten- und Teamleiter-Client ein Fake-LLM injiziert,
das sofort mit finalem Text antwortet (tool_calls=[]) – und ProjectVerifier wird
komplett übersprungen simuliert.
"""

import unittest
from unittest.mock import AsyncMock, patch

from agents.orchestrator import Orchestrator
from core.message_bus import AgentTask
from core.llm_factory import LLMResponse
from core.verifier import VerificationReport


class _FakeToolCapableLLM:
    """Antwortet im agentischen Loop sofort final (keine tool_calls) – wie ein Ein-Schuss-Aufruf."""

    def __init__(self, text: str, model_name: str = "gemini-2.5-flash"):
        self._text = text
        self.model_name = model_name

    async def generate_with_tools(self, messages, system_prompt, tools):
        return LLMResponse(
            text=self._text, model_name=self.model_name,
            prompt_tokens=150, completion_tokens=80, total_tokens=230, tool_calls=[],
        )

    async def generate_with_usage(self, prompt, system_prompt=None):
        return LLMResponse(
            text=self._text, model_name=self.model_name,
            prompt_tokens=150, completion_tokens=80, total_tokens=230,
        )


class TestMockWorkflow(unittest.TestCase):
    """Testet den mehrphasigen Orchestrator-Workflow ohne echte API-Aufrufe oder Subprozesse."""

    def setUp(self):
        self.orchestrator = Orchestrator()
        fake_text = "```python:src/main.py\nfrom fastapi import FastAPI\napp = FastAPI()\n```"
        # Jeden Fachagenten UND jeden Fachbereichs-Teamleiter mit einem Fake-LLM ausstatten,
        # unabhängig davon, welcher Provider (Gemini/DeepSeek/Groq/...) ihm sonst zugeordnet wäre.
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM(fake_text)

    @patch("agents.orchestrator.ProjectVerifier")
    @patch("core.task_manager.TaskManager.decompose")
    @patch("core.result_aggregator.ResultAggregator.synthesize")
    async def _run_mocked_process(self, mock_synthesize, mock_decompose, mock_verifier_cls):
        mock_decompose.return_value = (
            "Erstelle eine FastAPI App",
            "fastapi_app",
            [
                AgentTask(task_id="t1", agent_id="product_owner", description="Definiere Scope"),
                AgentTask(task_id="t2", agent_id="architect", description="Architektur entwerfen"),
                AgentTask(task_id="t3", agent_id="backend", description="FastAPI Server"),
                AgentTask(task_id="t4", agent_id="code_reviewer", description="Review durchführen"),
            ]
        )
        mock_synthesize.return_value = ("### Zusammenfassung: FastAPI App erfolgreich erstellt!", 120)

        mock_verifier = mock_verifier_cls.return_value
        mock_verifier.ensure_environment.return_value = ""
        mock_verifier.run_tests.return_value = VerificationReport(
            ran=False, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.0,
            reason_skipped="Keine Testdateien gefunden (simuliert).",
        )

        status_logs = []
        result = await self.orchestrator.process(
            "Baue mir eine FastAPI App",
            status_callback=lambda msg: status_logs.append(msg)
        )

        self.assertIn("FastAPI App", result)
        self.assertIn("Projekt-Kennzahlen", result)
        self.assertIn("Gesamtverbrauch Tokens", result)
        self.assertTrue(len(status_logs) > 0)

        # Teamleiter wurden für diese Aufgaben wirklich (nicht nur simuliert) aufgerufen:
        # planning_lead delegiert/konsolidiert für product_owner/architect, dev_lead für backend,
        # governance_lead für code_reviewer -> mind. 3 aktive Fachbereiche x 2 Lead-Aufrufe.
        self.assertIn("planning_lead", result)
        mock_verifier.run_tests.assert_called()

    def test_mocked_workflow_execution(self):
        import asyncio
        asyncio.run(self._run_mocked_process())


if __name__ == "__main__":
    unittest.main()
