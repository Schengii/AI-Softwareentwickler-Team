"""
tests/test_telemetry_failures_are_logged.py – Telemetrie-Lücken werden sichtbar statt verschluckt

Realer Fund (Framework-Analyse 2026-09-10): agents/orchestrator/dispatch.py (Agenten-Aufruf) und
agents/orchestrator/verification.py (Rohausgabe der Testsuite) fingen JEDEN Fehler beim
Schreiben ins Lauf-Log mit `except Exception: pass` ab - Agenten-Aufrufe und Testausgaben fehlten
dadurch lautlos in allen späteren Auswertungen. Der Lauf darf weiterhin nie daran scheitern.
"""

import asyncio
import unittest
from unittest.mock import MagicMock

from agents.orchestrator.dispatch import DispatchMixin
from agents.orchestrator.verification import VerificationMixin
from core.message_bus import AgentResult, AgentTask
from core.verifier import VerificationReport


class _FakeAgent:
    async def execute(self, task):
        return AgentResult(task_id=task.task_id, agent_id=task.agent_id, agent_name="Fake", success=True, content="ok")


class _Dispatcher(DispatchMixin):
    def __init__(self):
        self._agents = {"backend": _FakeAgent()}
        self._dept_leads = {}
        self._run_logger = MagicMock()
        self._run_logger.log_agent_result.side_effect = OSError("Datei gesperrt")


class _Verifier(VerificationMixin):
    def __init__(self):
        self._run_logger = MagicMock()
        self._run_logger.log_verification_output.side_effect = OSError("Datei gesperrt")


class TestTelemetryFailuresAreLogged(unittest.TestCase):
    def test_agent_call_log_failure_is_warned_and_run_continues(self):
        task = AgentTask(task_id="t1", agent_id="backend", description="x")
        with self.assertLogs("agents.orchestrator.dispatch", level="WARNING") as logs:
            result = asyncio.run(_Dispatcher()._run_single_agent(task))
        self.assertTrue(result.success)
        self.assertIn("backend", logs.output[0])

    def test_test_output_log_failure_is_warned_and_report_returned(self):
        verifier = MagicMock()
        verifier.run_tests.return_value = VerificationReport(
            ran=True, passed=False, exit_code=1, stdout="FAILED", stderr="", duration_seconds=0.1,
        )
        with self.assertLogs("agents.orchestrator.verification", level="WARNING") as logs:
            report = asyncio.run(_Verifier()._run_tests_logged(verifier, "erstlauf"))
        self.assertEqual(report.exit_code, 1)
        self.assertIn("erstlauf", logs.output[0])


if __name__ == "__main__":
    unittest.main()
