"""
tests/test_test_regression_auto_revert.py – Testet den Auto-Revert nach erkannter
Test-Schrumpfung in agents/orchestrator/verification.py.

Realer Fund (Backlog-Tickets `test-regression-pipeline_pilot`,
`test-regression-entwickle_das_projekt_sentinel`, 2026-09-16/17): der Test-Schrumpfungs-Wächter
(core.test_depth.collect_test_function_names()) erkannte zuverlässig, wenn ein Fix-Agent einen
fehlschlagenden Test ERSATZLOS ENTFERNT hat statt den echten Fehler zu beheben - protokollierte
das bisher aber nur als Veto und legte ein `blocked`-Ticket an, OHNE die gelöschten Tests
zurückzuholen oder einen echten Fix-Versuch zu erzwingen. Jetzt: die betroffene(n) Testdatei(en)
werden auf den Stand vor dem Fixversuch zurückgesetzt (core.test_depth.restore_test_files()) und
EIN weiterer, expliziter Fix-Versuch mit klarem Lösch-Verbot wird sofort inline nachgeschoben,
bevor endgültig ein Ticket angelegt wird.
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

_TEST_FILE = "tests/test_x.py"

_TEST_PRESENT = "def test_x():\n    assert True\n"
_TEST_DELETED = "# der fehlschlagende Test wurde entfernt\n"

_FAILURE = TestFailure(
    test_id="tests/test_x.py::test_x", message="AssertionError: boom", files=[_TEST_FILE],
)
FAILING_REPORT = VerificationReport(
    ran=True, passed=False, exit_code=1, stdout="", stderr="", duration_seconds=0.1, failures=[_FAILURE],
)
PASSING_REPORT = VerificationReport(
    ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1, failures=[],
)


class _FakeToolCapableLLM:
    """Generisches Test-Double ohne Werkzeug-Aufrufe - für Agenten, die in diesen Tests nicht
    im Mittelpunkt stehen, aber trotzdem aufgerufen werden könnten."""

    def __init__(self, text: str = "Fertig."):
        self._text = text
        self.model_name = "fake-model"

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[])

    async def generate_with_usage(self, prompt, system_prompt=None):
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15)


class _SequencedWriteFileLLM:
    """Schreibt bei JEDER separaten Agenten-Aufgabe (execute()-Aufruf) GENAU EINEN Eintrag aus
    `contents` in `_TEST_FILE` - simuliert eine realistische Abfolge (1. echte
    Test-Implementierung, 2. fehlerhafter "Fix" per Test-Löschung, 3. ein möglicher weiterer
    Versuch nach dem Auto-Revert). Jede Aufgabe liest die Datei zuerst (`read_file`, wie es der
    Fix-Auftrag in agents/orchestrator/verification.py auch vorschreibt - core/agent_toolbox.py
    ._reject_if_stale() lehnt sonst ein blindes Überschreiben einer bereits existierenden, von
    dieser Aufgabe noch nie gesehenen Datei ab), schreibt dann und schließt mit reinem Text ab -
    drei Runden pro Aufgabe. Reicht `contents` nicht aus, antworten weitere Aufgaben ohne
    Werkzeug-Aufruf."""

    def __init__(self, contents: list[str]):
        self._contents = contents
        self._write_index = 0
        self._stage = 0  # 0=read_file, 1=write_file, 2=Bestätigungstext
        self.model_name = "fake-model"

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        tool_calls = []
        if self._stage == 0 and self._write_index < len(self._contents):
            tool_calls = [ToolCall(id="call_read", name="read_file", arguments={"path": _TEST_FILE})]
            self._stage = 1
        elif self._stage == 1:
            content = self._contents[self._write_index]
            self._write_index += 1
            tool_calls = [ToolCall(id="call_write", name="write_file",
                                   arguments={"path": _TEST_FILE, "content": content})]
            self._stage = 2
        else:
            self._stage = 0
        text = "" if tool_calls else "Fertig."
        return LLMResponse(text=text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=tool_calls)

    async def generate_with_usage(self, prompt, system_prompt=None):
        return LLMResponse(text="Fertig.", model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15)


class TestTestRegressionAutoRevert(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, run_tests_side_effect, tester_contents):
        self.orchestrator._agents["tester"]._llm = _SequencedWriteFileLLM(tester_contents)

        @patch("agents.orchestrator.verification.MAX_VERIFICATION_ITERATIONS", 1)
        @patch("agents.orchestrator.verification.upsert_ticket")
        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls, mock_upsert_ticket):
            task = AgentTask(task_id="t1", agent_id="tester", description="tests/test_x.py schreiben")
            mock_decompose.return_value = ("Kurze Aufgabe", "test_regression_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.side_effect = run_tests_side_effect
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_lint.return_value = []

            status_logs: list[str] = []
            asyncio.run(self.orchestrator.process("Baue etwas mit Tests", status_callback=status_logs.append))
            return status_logs, mock_verifier, mock_upsert_ticket

        return _inner()

    def test_regression_is_reverted_and_real_fix_succeeds(self):
        """Löscht der Fix-Agent den fehlschlagenden Test, wird die Testdatei zurückgesetzt und
        ein weiterer Fix-Versuch angefordert - gelingt der (hier: Test bleibt beim erneuten
        Versuch erhalten und die Suite wird grün), gilt der Lauf als verifiziert, OHNE dass ein
        `test-regression`-Ticket angelegt wird."""
        logs, mock_verifier, mock_upsert_ticket = self._run(
            run_tests_side_effect=[FAILING_REPORT, PASSING_REPORT, PASSING_REPORT],
            tester_contents=[_TEST_PRESENT, _TEST_DELETED, _TEST_PRESENT],
        )

        self.assertEqual(mock_verifier.run_tests.call_count, 3)
        self.assertTrue(self.orchestrator.last_verification_ok)
        self.assertTrue(any("Test-Schrumpfung erkannt" in line for line in logs))
        self.assertTrue(any("zurückgesetzt" in line for line in logs))
        self.assertTrue(any("Erneuter Fix ohne Test-Löschung erfolgreich" in line for line in logs))
        regression_ticket_calls = [
            c for c in mock_upsert_ticket.call_args_list
            if str(c.kwargs.get("ticket_id", "")).startswith("test-regression-")
        ]
        self.assertEqual(regression_ticket_calls, [])

    def test_regression_persists_after_retry_creates_ticket(self):
        """Löscht der Fix-Agent den Test auch im erzwungenen zweiten Versuch erneut, bleibt der
        Lauf unverifiziert und ein `test-regression`-Ticket wird angelegt - aber erst NACH dem
        Auto-Revert-Versuch, nicht sofort beim ersten Fund."""
        logs, mock_verifier, mock_upsert_ticket = self._run(
            run_tests_side_effect=[FAILING_REPORT, FAILING_REPORT],
            tester_contents=[_TEST_PRESENT, _TEST_DELETED, _TEST_DELETED],
        )

        self.assertEqual(mock_verifier.run_tests.call_count, 2)
        self.assertFalse(self.orchestrator.last_verification_ok)
        self.assertTrue(any("Test-Schrumpfung erkannt" in line for line in logs))
        self.assertTrue(any("zurückgesetzt" in line for line in logs))
        regression_ticket_calls = [
            c for c in mock_upsert_ticket.call_args_list
            if str(c.kwargs.get("ticket_id", "")).startswith("test-regression-")
        ]
        self.assertEqual(len(regression_ticket_calls), 1)
        self.assertIn("erneuter Fix-Versuch ebenfalls erfolglos", regression_ticket_calls[0].kwargs.get("detail", ""))


if __name__ == "__main__":
    unittest.main()
