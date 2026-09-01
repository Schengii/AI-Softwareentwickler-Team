"""
tests/test_docker_build_integration.py – Testet die Docker-Build-Prüfung im Verifikationslauf

Echtes Deployment beginnt damit, dass sich ein Projekt überhaupt containerisieren lässt -
ein generiertes Dockerfile, das nie tatsächlich baut, bringt niemanden näher an ein echtes
Ausrollen. agents/orchestrator.py._run_verification_loop() ruft jetzt echte
ProjectVerifier.check_docker_build() auf und macht das Ergebnis sichtbar.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.verifier import DockerBuildReport, VerificationReport
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


class TestDockerBuildInVerificationLoop(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, docker_report: DockerBuildReport):
        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            task = AgentTask(task_id="t1", agent_id="backend", description="Etwas bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "docker_test_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
            )
            mock_verifier.check_docker_build.return_value = docker_report

            status_logs: list[str] = []
            result = asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return result, status_logs, mock_verifier

        return _inner()

    def test_successful_docker_build_is_reported(self):
        result, logs, mock_verifier = self._run(
            DockerBuildReport(attempted=True, success=True, output="Successfully built")
        )
        mock_verifier.check_docker_build.assert_called_once()
        self.assertIn("Docker-Image baut erfolgreich", result)
        self.assertTrue(any("Docker-Image baut erfolgreich" in line for line in logs))

    def test_failed_docker_build_is_reported_with_output(self):
        result, logs, mock_verifier = self._run(
            DockerBuildReport(attempted=True, success=False, output="pull access denied for bad-image")
        )
        self.assertIn("Docker-Build fehlgeschlagen", result)
        self.assertIn("pull access denied", result)

    def test_skipped_docker_check_adds_no_noise_to_summary(self):
        result, logs, mock_verifier = self._run(
            DockerBuildReport(attempted=False, success=True, output="", reason_skipped="Kein Dockerfile im Projekt gefunden.")
        )
        self.assertNotIn("Docker-Image baut", result)
        self.assertNotIn("Docker-Build fehlgeschlagen", result)


if __name__ == "__main__":
    unittest.main()
