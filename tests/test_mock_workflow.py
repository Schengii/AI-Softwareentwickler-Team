"""
tests/test_mock_workflow.py – Testet den End-to-End Orchestrator Workflow mit gemockten LLM-Antworten
"""

import unittest
from unittest.mock import AsyncMock, patch
from agents.orchestrator import Orchestrator
from core.message_bus import AgentTask


class TestMockWorkflow(unittest.TestCase):
    """Testet den mehrphasigen Orchestrator-Workflow ohne echte API-Aufrufe."""

    def setUp(self):
        self.orchestrator = Orchestrator()

    @patch("core.task_manager.TaskManager.decompose")
    @patch("agents.base_agent.GeminiClient.generate")
    @patch("core.result_aggregator.ResultAggregator.synthesize")
    async def _run_mocked_process(self, mock_synthesize, mock_generate, mock_decompose):
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
        mock_generate.return_value = "```python:src/main.py\nfrom fastapi import FastAPI\napp = FastAPI()\n```"
        mock_synthesize.return_value = "### Zusammenfassung: FastAPI App erfolgreich erstellt!"

        status_logs = []
        result = await self.orchestrator.process(
            "Baue mir eine FastAPI App",
            status_callback=lambda msg: status_logs.append(msg)
        )

        self.assertIn("FastAPI App", result)
        self.assertTrue(len(status_logs) > 0)

    def test_mocked_workflow_execution(self):
        import asyncio
        asyncio.run(self._run_mocked_process())


if __name__ == "__main__":
    unittest.main()
