"""
tests/test_duplicate_project_warning.py – Testet die Frühwarnung vor doppelten Projekten

Realer Fund aus einem echten Lauf: "calculator_service" vs. "simple_calculator" und
"notes_tasks_api" vs. "personal_notes_tasks" waren jeweils zwei komplette, separat
bezahlte Läufe für praktisch dieselbe Anwendung, weil project_slug pro Lauf neu vom
Modell geraten wird und sich selbst bei inhaltlich identischer Aufgabe unterscheiden
kann. agents/orchestrator.py.process() gibt seitdem einen rein informativen Hinweis
aus (kein LLM-Aufruf, keine Heuristik), sobald ein NEUER Projektordner angelegt würde,
während bereits andere Projekte im Workspace existieren.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
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


class TestDuplicateProjectWarning(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, new_slug: str):
        @patch("agents.orchestrator.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            mock_decompose.return_value = (
                "Kurze Aufgabe", new_slug,
                [AgentTask(task_id="t1", agent_id="backend", description="Etwas bauen")],
            )
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=False, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.0,
                reason_skipped="simuliert",
            )
            status_logs: list[str] = []
            asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return status_logs

        return _inner()

    def test_warns_when_new_project_created_alongside_existing_ones(self):
        (self.orchestrator._workspace.base_dir / "calculator_service").mkdir()
        logs = self._run("simple_calculator")
        self.assertTrue(any("Neues Projekt 'simple_calculator'" in line and "calculator_service" in line for line in logs))
        self.assertTrue(any("/load" in line for line in logs))

    def test_no_warning_on_first_ever_project(self):
        logs = self._run("brand_new_project")
        self.assertFalse(any("Neues Projekt" in line for line in logs))

    def test_no_warning_when_continuing_an_existing_project(self):
        (self.orchestrator._workspace.base_dir / "already_here").mkdir()
        logs = self._run("already_here")
        self.assertFalse(any("Neues Projekt" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
