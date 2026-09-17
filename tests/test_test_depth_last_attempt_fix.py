"""
tests/test_test_depth_last_attempt_fix.py – Testet die Testtiefen-Nachbesserung in
agents/orchestrator/verification.py, wenn die Testsuite erst im LETZTEN erlaubten Versuch
(attempt == MAX_VERIFICATION_ITERATIONS) grün, aber zu flach wird.

Realer Fund (pipeline_pilot, 2026-09-16, logs/FEHLERANALYSE_KI_TEAM_20260916.md-Nachfolgeanalyse):
Die Testsuite brauchte zwei echte Fixversuche, um grün zu werden - genau die beiden Versuche, die
`MAX_VERIFICATION_ITERATIONS` (Default 3) davor bereits verbraucht hatten. Die Testtiefen-Prüfung
lief zwar noch an (sie prüft nur `if report.passed`), aber die Nachbesserung war bisher an
`attempt < MAX_VERIFICATION_ITERATIONS` gebunden - im letzten Versuch also NIE erreichbar. tester
bekam dadurch nie den Auftrag, die fehlenden Routen-Tests zu ergänzen, und `test_depth` blieb im
Definition-of-Done-Bericht als ungelöster Blocker stehen, obwohl ein einziger zusätzlicher
tester-Aufruf ausgereicht hätte.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse, ToolCall
from core.message_bus import AgentTask
from core.test_depth import RouteRef, TestDepthReport
from core.verifier import TestFailure, VerificationReport
from core.workspace import WorkspaceManager

FAILING_A = VerificationReport(
    ran=True, passed=False, exit_code=1, stdout="", stderr="", duration_seconds=0.1,
    failures=[TestFailure(test_id="tests/test_app.py::test_a", message="AssertionError: A", files=["backend/app.py"])],
)
FAILING_B = VerificationReport(
    ran=True, passed=False, exit_code=1, stdout="", stderr="", duration_seconds=0.1,
    failures=[TestFailure(test_id="tests/test_app.py::test_b", message="AssertionError: B", files=["backend/app.py"])],
)
PASSING_BUT_SHALLOW = VerificationReport(
    ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1, failures=[],
)
STILL_PASSING = VerificationReport(
    ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1, failures=[],
)
BROKEN_BY_DEPTH_FIX = VerificationReport(
    ran=True, passed=False, exit_code=1, stdout="", stderr="", duration_seconds=0.1,
    failures=[TestFailure(test_id="tests/test_app.py::test_new_route", message="AssertionError: neu kaputt", files=[])],
)

SHALLOW_REPORT = TestDepthReport(
    routes=[RouteRef("GET", "/api/a", "app/main.py"), RouteRef("GET", "/api/b", "app/main.py")],
    untested_routes=[RouteRef("GET", "/api/b", "app/main.py")],
)
DEEP_REPORT = TestDepthReport(routes=list(SHALLOW_REPORT.routes), untested_routes=[])


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


class _AlwaysWritingLLM:
    """Schreibt bei JEDEM generate_with_tools()-Aufruf `written_file` per write_file, damit die
    ersten beiden (echten) Fixversuche als dateiverändernd erkannt werden - siehe
    tests/test_verification_post_fix_validation.py für dasselbe Muster."""

    def __init__(self, written_file: str, text: str = "Fertig."):
        self._written_file = written_file
        self._text = text
        self._call_count = 0
        self.model_name = "fake-model"

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        self._call_count += 1
        tool_calls = [
            ToolCall(id=f"call_{self._call_count}_read", name="read_file", arguments={"path": self._written_file}),
            ToolCall(id=f"call_{self._call_count}_write", name="write_file",
                     arguments={"path": self._written_file, "content": f"# fix {self._call_count}\n"}),
        ]
        return LLMResponse(text="", model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=tool_calls)

    async def generate_with_usage(self, prompt, system_prompt=None):
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15)


class TestTestDepthFixOnLastAttempt(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()
        self.orchestrator._agents["backend"]._llm = _AlwaysWritingLLM(written_file="backend/app.py")

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, run_tests_side_effect, analyze_test_depth_side_effect):
        @patch("agents.orchestrator.verification.upsert_ticket")
        @patch("agents.orchestrator.verification.analyze_test_depth", side_effect=analyze_test_depth_side_effect)
        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls, mock_analyze, mock_upsert_ticket):
            task = AgentTask(task_id="t1", agent_id="backend", description="backend/app.py bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "depth_last_attempt_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.side_effect = run_tests_side_effect
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_lint.return_value = []

            dispatched: list[str] = []
            original_parallel = self.orchestrator._run_agents_parallel

            async def spy(tasks, notify=None):
                dispatched.extend(t.task_id for t in tasks)
                return await original_parallel(tasks, notify=notify)

            self.orchestrator._run_agents_parallel = spy

            status_logs: list[str] = []
            asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return status_logs, mock_verifier, dispatched

        return _inner()

    def test_depth_fix_dispatched_and_inline_reverified_on_last_attempt(self):
        # MAX_VERIFICATION_ITERATIONS ist standardmäßig 3 (config.py): zwei echte Fehlschläge
        # verbrauchen die ersten beiden Versuche, erst Versuch 3 wird grün - aber zu flach. Ein
        # vierter, inline nachgeschobener Testlauf bestätigt die von tester ergänzten Tests.
        logs, mock_verifier, dispatched = self._run(
            run_tests_side_effect=[FAILING_A, FAILING_B, PASSING_BUT_SHALLOW, STILL_PASSING],
            analyze_test_depth_side_effect=[SHALLOW_REPORT, DEEP_REPORT],
        )

        self.assertEqual(mock_verifier.run_tests.call_count, 4)
        self.assertTrue(any(task_id.startswith("test_depth_fix_") for task_id in dispatched))
        self.assertTrue(any("Letzter Versuch bereits verbraucht" in line for line in logs))
        self.assertTrue(any("Nachgelieferte Tests bestehen weiterhin" in line for line in logs))
        self.assertTrue(self.orchestrator.last_verification_ok)
        self.assertTrue(self.orchestrator.last_verification_outcome.status("test_depth"))

    def test_depth_fix_breaking_suite_on_last_attempt_keeps_last_state(self):
        # Bricht der nachgelieferte Test die Suite (statt sie nur zu vertiefen), übernimmt der
        # Lauf ehrlich den letzten (roten) Stand statt einen falschen Erfolg zu melden.
        logs, mock_verifier, dispatched = self._run(
            run_tests_side_effect=[FAILING_A, FAILING_B, PASSING_BUT_SHALLOW, BROKEN_BY_DEPTH_FIX],
            analyze_test_depth_side_effect=[SHALLOW_REPORT],
        )

        self.assertEqual(mock_verifier.run_tests.call_count, 4)
        self.assertTrue(any(task_id.startswith("test_depth_fix_") for task_id in dispatched))
        self.assertTrue(any("Testtiefen-Nachbesserung hat die Suite gebrochen" in line for line in logs))
        self.assertFalse(self.orchestrator.last_verification_ok)


if __name__ == "__main__":
    unittest.main()
