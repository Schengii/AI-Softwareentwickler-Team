"""
tests/test_frontend_build_integration.py – Testet die Frontend-Build-Prüfung im Verifikationslauf.

Realer Fund (auditlog_sentinel, 2026-09-10): core/verifier/runtime.py.check_frontend_build()
(echter `npm run build`) existierte bereits, wurde aber NIRGENDS aus der Verifikation aufgerufen -
ein React/Vite-Frontend, das nie tatsächlich baute, bestand die Verifikation trotzdem und der
Browser-UI-Check servierte danach die rohe .tsx-Quelle (MIME-Type-Fehler). Diese Tests stellen
sicher, dass ProjectVerifier.check_frontend_build() jetzt aufgerufen wird und ein Fehlschlag
sowohl gemeldet als auch an einen zuständigen Agenten zur Korrektur zurückgespielt wird.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.verifier import FrontendBuildReport, VerificationReport
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


class TestFrontendBuildInVerificationLoop(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, reports: list[FrontendBuildReport], task_agent: str = "backend"):
        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            task = AgentTask(task_id="t1", agent_id=task_agent, description="Etwas bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "frontend_build_test_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
            )
            mock_verifier.check_frontend_build.return_value = reports

            status_logs: list[str] = []
            result = asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return result, status_logs, mock_verifier

        return _inner()

    def test_successful_build_is_reported(self):
        result, logs, mock_verifier = self._run(
            [FrontendBuildReport(attempted=True, passed=True, directory=".")]
        )
        mock_verifier.check_frontend_build.assert_called_once()
        self.assertIn("Frontend-Build (`.`) erfolgreich", result)
        self.assertTrue(self.orchestrator.last_verification_ok)

    def test_failed_build_is_reported_and_dispatched_to_frontend(self):
        self.orchestrator._agents["frontend"]._llm = _FakeToolCapableLLM()
        result, logs, mock_verifier = self._run(
            [FrontendBuildReport(attempted=True, passed=False, directory=".", output="TS2307: Cannot find module")]
        )
        self.assertIn("Frontend-Build (`.`) fehlgeschlagen", result)
        self.assertIn("TS2307", result)
        self.assertFalse(self.orchestrator.last_verification_ok)
        self.assertTrue(any("Beauftrage frontend" in line for line in logs))

    def test_skipped_build_adds_no_noise_and_stays_verified(self):
        result, logs, mock_verifier = self._run(
            [FrontendBuildReport(attempted=False, passed=True, directory=".", reason_skipped="`npm` ist auf diesem System nicht installiert/verfügbar.")]
        )
        self.assertNotIn("Frontend-Build (`.`) erfolgreich", result)
        self.assertNotIn("Frontend-Build (`.`) fehlgeschlagen", result)
        self.assertTrue(self.orchestrator.last_verification_ok)

    def test_no_frontend_project_is_a_no_op(self):
        result, logs, mock_verifier = self._run([])
        self.assertNotIn("Frontend-Build", result)
        self.assertTrue(self.orchestrator.last_verification_ok)


if __name__ == "__main__":
    unittest.main()
