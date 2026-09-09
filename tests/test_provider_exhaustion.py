"""
tests/test_provider_exhaustion.py – Testet core/provider_exhaustion.py (gemeinsame Erkennung
einer API-Kontingent-/Rate-Limit-Erschöpfung) und deren Verdrahtung in
agents/orchestrator/dispatch.py.DispatchMixin._run_agents_parallel().

Siehe core/provider_exhaustion.py-Moduldocstring für den echten Fund (memory/history_default.
json, 2026-09-09), der diese Auslagerung/Verdrahtung motiviert hat.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock

from agents.orchestrator.dispatch import DispatchMixin
from core.message_bus import AgentResult, AgentTask
from core.provider_exhaustion import all_failed_on_provider_exhaustion, is_provider_exhaustion_error


class TestIsProviderExhaustionError(unittest.TestCase):
    def test_none_is_not_exhaustion(self):
        self.assertFalse(is_provider_exhaustion_error(None))

    def test_empty_string_is_not_exhaustion(self):
        self.assertFalse(is_provider_exhaustion_error(""))

    def test_unrelated_error_is_not_exhaustion(self):
        self.assertFalse(is_provider_exhaustion_error("SyntaxError: invalid syntax"))

    def test_429_marker_detected(self):
        self.assertTrue(is_provider_exhaustion_error("Gemini API Fehler: 429 RESOURCE_EXHAUSTED"))

    def test_resource_exhausted_marker_detected_case_insensitive(self):
        self.assertTrue(is_provider_exhaustion_error("error: RESOURCE_EXHAUSTED, retry later"))

    def test_quota_marker_detected(self):
        self.assertTrue(is_provider_exhaustion_error("You exceeded your current quota"))


class TestAllFailedOnProviderExhaustion(unittest.TestCase):
    def _result(self, success: bool, error: str | None) -> AgentResult:
        return AgentResult(
            task_id="t", agent_id="backend", agent_name="Backend",
            success=success, content="", error=error,
        )

    def test_empty_results_is_not_all_exhausted(self):
        self.assertFalse(all_failed_on_provider_exhaustion([]))

    def test_all_failed_on_exhaustion_is_true(self):
        results = [
            self._result(False, "429 RESOURCE_EXHAUSTED"),
            self._result(False, "quota exceeded"),
        ]
        self.assertTrue(all_failed_on_provider_exhaustion(results))

    def test_one_success_makes_it_false(self):
        results = [self._result(False, "429 RESOURCE_EXHAUSTED"), self._result(True, None)]
        self.assertFalse(all_failed_on_provider_exhaustion(results))

    def test_failure_for_unrelated_reason_makes_it_false(self):
        results = [
            self._result(False, "429 RESOURCE_EXHAUSTED"),
            self._result(False, "SyntaxError: invalid syntax"),
        ]
        self.assertFalse(all_failed_on_provider_exhaustion(results))


class _DispatchHost(DispatchMixin):
    """Minimaler Host für DispatchMixin - stellt nur die von _run_agents_parallel()/
    _provider_exhaustion_ticket_note() benötigten Attribute/Methoden bereit."""

    def __init__(self):
        self._agents = {}
        self._dept_leads = {}
        self._provider_exhausted_this_run = False

    def _status_notify_line(self, ok_label, fail_label, name, duration, success, error):
        return ok_label if success else fail_label


class TestRunAgentsParallelExhaustionFlag(unittest.TestCase):
    def _task(self, agent_id: str) -> AgentTask:
        return AgentTask(task_id=agent_id, agent_id=agent_id, description="x")

    def test_flag_set_when_all_agents_fail_on_exhaustion(self):
        host = _DispatchHost()
        fake_agent = AsyncMock()
        fake_agent.execute.return_value = AgentResult(
            task_id="t", agent_id="backend", agent_name="Backend",
            success=False, content="", error="429 RESOURCE_EXHAUSTED",
        )
        host._agents = {"backend": fake_agent}
        asyncio.run(host._run_agents_parallel([self._task("backend")]))
        self.assertTrue(host._provider_exhausted_this_run)
        self.assertIn("Kontingent-Erschöpfung", host._provider_exhaustion_ticket_note())

    def test_flag_not_set_on_normal_success(self):
        host = _DispatchHost()
        fake_agent = AsyncMock()
        fake_agent.execute.return_value = AgentResult(
            task_id="t", agent_id="backend", agent_name="Backend",
            success=True, content="ok",
        )
        host._agents = {"backend": fake_agent}
        asyncio.run(host._run_agents_parallel([self._task("backend")]))
        self.assertFalse(host._provider_exhausted_this_run)
        self.assertEqual(host._provider_exhaustion_ticket_note(), "")

    def test_flag_not_set_when_failure_unrelated_to_exhaustion(self):
        host = _DispatchHost()
        fake_agent = AsyncMock()
        fake_agent.execute.return_value = AgentResult(
            task_id="t", agent_id="backend", agent_name="Backend",
            success=False, content="", error="SyntaxError: invalid syntax",
        )
        host._agents = {"backend": fake_agent}
        asyncio.run(host._run_agents_parallel([self._task("backend")]))
        self.assertFalse(host._provider_exhausted_this_run)


if __name__ == "__main__":
    unittest.main()
