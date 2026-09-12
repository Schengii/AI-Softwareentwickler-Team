"""
tests/test_verification_post_fix_validation.py – Testet die Post-Fix-Abschlussprüfung in
agents/orchestrator/verification.py._run_verification_loop(): die Schleife ruft run_tests()
bisher NUR am ANFANG jedes Versuchs auf - im LETZTEN erlaubten Versuch (attempt ==
MAX_VERIFICATION_ITERATIONS) verbrauchte der `range()` danach keinen weiteren Schleifendurchlauf
mehr, sodass der Fix des letzten Versuchs NIE gegen die echte Testsuite geprüft wurde, bevor der
Lauf als fehlgeschlagen gewertet und ein Backlog-Ticket eröffnet wurde - selbst wenn der Fix
tatsächlich griff (ki_team_fehleranalyse_zusammenfassung.md). Eine zusätzliche Abschlussprüfung
NACH einem dateiverändernden letzten Fixversuch schließt diese Lücke.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse, ToolCall
from core.message_bus import AgentTask
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
FAILING_C = VerificationReport(
    ran=True, passed=False, exit_code=1, stdout="", stderr="", duration_seconds=0.1,
    failures=[TestFailure(test_id="tests/test_app.py::test_c", message="AssertionError: C", files=["backend/app.py"])],
)
FAILING_D = VerificationReport(
    ran=True, passed=False, exit_code=1, stdout="", stderr="", duration_seconds=0.1,
    failures=[TestFailure(test_id="tests/test_app.py::test_d", message="AssertionError: D", files=["backend/app.py"])],
)
PASSING_REPORT = VerificationReport(
    ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1, failures=[],
)


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
    """Schreibt bei JEDEM generate_with_tools()-Aufruf `written_file` per write_file - anders als
    die einmalig schreibende Variante in test_verification_no_progress_breaker.py, weil dieser
    Test gezielt prüft, dass GENAU der letzte Fixversuch (attempt == MAX_VERIFICATION_ITERATIONS)
    als dateiverändernd erkannt wird und die Abschlussprüfung auslöst."""

    def __init__(self, written_file: str, text: str = "Fertig."):
        self._written_file = written_file
        self._text = text
        self._call_count = 0
        self.model_name = "fake-model"

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        self._call_count += 1
        # read_file VOR write_file in derselben Antwort: core/agent_toolbox.py._reject_if_stale()
        # lehnt ein Überschreiben ab, wenn dieser (pro Aufgabe frische) Toolbox-Aufruf den
        # aktuellen Inhalt einer bereits existierenden Datei nicht kennt - ohne den read_file-
        # Aufruf würde jeder Fixversuch ab dem zweiten scheitern, weil die Datei vom vorherigen
        # Versuch bereits existiert.
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


class TestVerificationPostFixValidation(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()
        self.orchestrator._agents["backend"]._llm = _AlwaysWritingLLM(written_file="backend/app.py")

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, run_tests_side_effect):
        @patch("agents.orchestrator.verification.upsert_ticket")
        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls, mock_upsert_ticket):
            task = AgentTask(task_id="t1", agent_id="backend", description="backend/app.py bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "post_fix_validation_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.side_effect = run_tests_side_effect
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_lint.return_value = []

            status_logs: list[str] = []
            result = asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return result, status_logs, mock_verifier, mock_upsert_ticket

        return _inner()

    def test_successful_final_fix_triggers_passing_abschlusspruefung(self):
        # MAX_VERIFICATION_ITERATIONS ist standardmäßig 3 (config.py). Drei reguläre, jeweils
        # UNTERSCHIEDLICHE Fehlschläge (kein Zirkuit-Breaker-Abbruch wegen "kein Fortschritt"),
        # danach EIN zusätzlicher Abschluss-Testlauf NACH dem letzten (dateiverändernden)
        # Fixversuch - genau dieser vierte run_tests-Aufruf ist grün.
        result, logs, mock_verifier, mock_upsert_ticket = self._run(
            [FAILING_A, FAILING_B, FAILING_C, PASSING_REPORT],
        )

        self.assertEqual(mock_verifier.run_tests.call_count, 4)
        self.assertTrue(self.orchestrator.last_verification_ok)
        self.assertTrue(any("Abschlussprüfung nach letztem Fixversuch" in line for line in logs))
        self.assertTrue(any("Abschlussprüfung nach Fix erfolgreich" in line for line in logs))
        # Der erfolgreiche Fix darf NICHT als "recurring-failure" fehlgeschlagen gewertet werden.
        recurring_calls = [
            c for c in mock_upsert_ticket.call_args_list
            if c.kwargs.get("ticket_id", "").startswith("recurring-failure-")
        ]
        self.assertEqual(recurring_calls, [])

    def test_still_failing_after_final_fix_keeps_old_behaviour(self):
        # Bleibt die Abschlussprüfung weiterhin rot, ändert sich am bisherigen Verhalten nichts:
        # "letzter Stand wird übernommen" und ein Backlog-Ticket wird eröffnet.
        result, logs, mock_verifier, mock_upsert_ticket = self._run(
            [FAILING_A, FAILING_B, FAILING_C, FAILING_D],
        )

        self.assertEqual(mock_verifier.run_tests.call_count, 4)
        self.assertFalse(self.orchestrator.last_verification_ok)
        self.assertTrue(any("Maximale Verifikations-Iterationen erreicht" in line for line in logs))
        recurring_calls = [
            c for c in mock_upsert_ticket.call_args_list
            if c.kwargs.get("ticket_id", "").startswith("recurring-failure-")
        ]
        self.assertTrue(recurring_calls)


if __name__ == "__main__":
    unittest.main()
