"""
tests/test_project_continuity_integration.py – End-to-End-Nachweis der Projekt-Kontinuität

Realer Fund: memory/conversation_history.py ist sitzungsgebunden - eine neue Sitzung (neues
Terminal) hatte bisher KEINEN Zugriff auf frühere Läufe an einem Projekt, selbst bei
erneutem /load desselben Projekts. Dieser Test simuliert genau das: zwei GETRENNTE
Orchestrator-Instanzen (= zwei Sitzungen) arbeiten nacheinander am selben Projektverzeichnis
- die zweite muss die Historie der ersten sehen.
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


class TestProjectContinuityAcrossSessions(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _make_orchestrator(self) -> Orchestrator:
        orch = Orchestrator()
        orch._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(orch._agents.values()) + list(orch._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()
        return orch

    def _run(self, orchestrator: Orchestrator, task_summary: str, capture_task_context: list):
        @patch("agents.orchestrator.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            task = AgentTask(task_id="t1", agent_id="backend", description="Etwas bauen")
            mock_decompose.return_value = (task_summary, "continuity_project", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
            )
            asyncio.run(orchestrator.process("Baue etwas"))
            capture_task_context.append(task.context)

        _inner()

    def test_second_session_sees_history_from_first_session(self):
        # Sitzung 1: eine erste, GETRENNTE Orchestrator-Instanz arbeitet am Projekt.
        first_session_context: list = []
        self._run(self._make_orchestrator(), "Erste Version implementiert", first_session_context)

        # Sitzung 1 hatte noch keine Historie zu sehen (brandneues Projekt).
        self.assertNotIn("Bisherige Läufe", first_session_context[0])

        # Sitzung 2: eine KOMPLETT NEUE Orchestrator-Instanz (= neues Terminal/neue Sitzung,
        # kein geteilter Python-Prozess-Zustand außer der Datei auf der Platte).
        second_session_context: list = []
        self._run(self._make_orchestrator(), "Zweite Version implementiert", second_session_context)

        self.assertIn("Bisherige Läufe an diesem Projekt", second_session_context[0])
        self.assertIn("Erste Version implementiert", second_session_context[0])
        self.assertIn("✅", second_session_context[0])


if __name__ == "__main__":
    unittest.main()
