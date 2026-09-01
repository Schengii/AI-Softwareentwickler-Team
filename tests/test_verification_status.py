"""
tests/test_verification_status.py – Testet, dass "Fertig!" jetzt ehrlich Verifikation widerspiegelt

Realer Fund: JEDER Lauf endete bisher mit demselben uneingeschränkten "✅ Fertig! Alle
Fachbereiche haben ihre Aufgaben erfolgreich abgeschlossen." – unabhängig davon, ob die
echte Testsuite tatsächlich bestanden hatte, nie gefunden wurde, oder nach mehreren
Fixversuchen weiterhin fehlschlug. Orchestrator.process() gibt jetzt einen ehrlichen,
unterschiedlichen Abschluss-Status zurück (self.last_verification_ok) und meldet
entsprechend "✅ Fertig!" NUR bei tatsächlich bestandener Verifikation, sonst
"⚠️ Fertig, aber NICHT verifiziert!".
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


class TestVerificationStatusReflectsReality(unittest.TestCase):
    def setUp(self):
        # Isolierter Workspace statt des echten workspace/-Ordners - sonst legt
        # get_project_dir("test_proj") real workspace/test_proj/ im Repo an.
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, verifier_report: VerificationReport):
        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            mock_decompose.return_value = (
                "Kurze Aufgabe", "test_proj",
                [AgentTask(task_id="t1", agent_id="backend", description="Etwas bauen")],
            )
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = verifier_report

            status_logs: list[str] = []
            asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return status_logs

        return _inner()

    def test_reports_success_when_tests_actually_passed(self):
        logs = self._run(VerificationReport(
            ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=1.0,
        ))
        self.assertTrue(self.orchestrator.last_verification_ok)
        self.assertTrue(any("✅" in line and "Fertig!" in line and "NICHT" not in line for line in logs))

    def test_warns_when_no_tests_were_found(self):
        logs = self._run(VerificationReport(
            ran=False, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.0,
            reason_skipped="Keine Testdateien gefunden.",
        ))
        self.assertFalse(self.orchestrator.last_verification_ok)
        self.assertTrue(any("NICHT verifiziert" in line for line in logs))

    def test_warns_when_tests_ran_but_never_passed(self):
        from core.verifier import TestFailure
        failing_report = VerificationReport(
            ran=True, passed=False, exit_code=1, stdout="", stderr="", duration_seconds=1.0,
            failures=[TestFailure(test_id="test_x", message="AssertionError", files=[])],
        )
        logs = self._run(failing_report)
        self.assertFalse(self.orchestrator.last_verification_ok)
        self.assertTrue(any("NICHT verifiziert" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
