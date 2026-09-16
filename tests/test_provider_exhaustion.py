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
from core.provider_exhaustion import (
    all_failed_on_provider_exhaustion,
    is_provider_exhaustion_error,
    should_trip_run_breaker,
)


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


class TestShouldTripRunBreaker(unittest.TestCase):
    """
    Laufweite Breaker-Quote. Die Wellenschwelle (should_trip_breaker) und das Folge-Limit in
    agents/orchestrator/department.py sehen beide nur einen Ausschnitt; ein gleichmäßig über
    viele Wellen verteilter Kontingent-Engpass rutscht durch beide hindurch. Realer Fund
    `sentinelgrid`: 5 von 15 Aufrufen erschöpft, kein Breaker sprach an, 105.972 Tokens für
    einen roten Lauf.
    """

    def _result(self, success: bool, error: str | None = None) -> AgentResult:
        return AgentResult(
            task_id="t", agent_id="backend", agent_name="Backend",
            success=success, content="", error=error,
        )

    def _mix(self, exhausted: int, total: int) -> list:
        return (
            [self._result(False, "429 RESOURCE_EXHAUSTED") for _ in range(exhausted)]
            + [self._result(True) for _ in range(total - exhausted)]
        )

    def test_sentinelgrid_pattern_trips_the_run_breaker(self):
        # 5 von 15 = 33,3% - unter jeder Wellenschwelle, aber über der laufweiten Quote.
        self.assertTrue(should_trip_run_breaker(self._mix(5, 15), 0.30, 6))

    def test_below_threshold_does_not_trip(self):
        self.assertFalse(should_trip_run_breaker(self._mix(2, 15), 0.30, 6))

    def test_small_sample_never_trips(self):
        # Realer Fall `ai_team_framework`: 1 von 2 Aufrufen = 50%, aber keine Aussage über den Lauf.
        self.assertFalse(should_trip_run_breaker(self._mix(1, 2), 0.30, 6))

    def test_threshold_zero_disables_the_breaker(self):
        self.assertFalse(should_trip_run_breaker(self._mix(10, 10), 0.0, 6))

    def test_unrelated_failures_do_not_count_as_infrastructure(self):
        results = [self._result(False, "SyntaxError: invalid syntax") for _ in range(10)]
        self.assertFalse(should_trip_run_breaker(results, 0.30, 6))


class TestRunAgentsParallelBudgetStop(unittest.TestCase):
    """
    Laufanalyse 2026-09-16: Das Budget wurde nur am Phasenkopf und nach jedem SEQUENZIELLEN
    Mitglied geprüft. Eine parallele Phase arbeitet bei MAX_CONCURRENT_AGENTS=2 aber mehrere
    Blöcke nacheinander ab - dazwischen lief keine Prüfung, obwohl dort die größten Einzelposten
    entstehen (im Lauf `cloudpulse` 273.468 Tokens für einen einzelnen backend-Aufruf).
    """

    def _task(self, agent_id: str, task_id: str) -> AgentTask:
        return AgentTask(task_id=task_id, agent_id=agent_id, description="x")

    def _host_with_counting_agent(self) -> tuple:
        host = _DispatchHost()
        gestartet: list[str] = []

        async def _execute(task, *args, **kwargs):
            gestartet.append(task.task_id)
            return AgentResult(
                task_id=task.task_id, agent_id="backend", agent_name="Backend",
                success=True, content="ok", total_tokens=1000,
            )

        agent = AsyncMock()
        agent.execute.side_effect = _execute
        agent.name = "Backend"
        host._agents = {"backend": agent}
        return host, gestartet

    def test_tasks_not_yet_started_are_skipped_once_budget_is_gone(self):
        host, gestartet = self._host_with_counting_agent()
        # Budget reißt, sobald der erste Aufruf durch ist.
        zustand = {"gestartet": 0}

        def _stop():
            zustand["gestartet"] += 1
            return None if zustand["gestartet"] <= 1 else "Lauf-Budget erreicht"

        tasks = [self._task("backend", f"t{i}") for i in range(5)]
        results = asyncio.run(host._run_agents_parallel(tasks, should_stop=_stop))

        self.assertEqual(len(gestartet), 1)
        self.assertEqual(len(results), 1)

    def test_skipped_tasks_are_not_counted_as_failures(self):
        """Ein nie gestarteter Aufruf darf weder die Erfolgsquoten noch die
        Infrastruktur-Quote des Circuit Breakers verfälschen."""
        host, _ = self._host_with_counting_agent()
        tasks = [self._task("backend", f"t{i}") for i in range(4)]

        results = asyncio.run(host._run_agents_parallel(tasks, should_stop=lambda: "Budget weg"))

        self.assertEqual(results, [])
        self.assertFalse(host._provider_exhausted_this_run)
        self.assertFalse(getattr(host, "_provider_breaker_tripped", False))

    def test_without_should_stop_every_task_runs(self):
        host, gestartet = self._host_with_counting_agent()
        tasks = [self._task("backend", f"t{i}") for i in range(4)]

        results = asyncio.run(host._run_agents_parallel(tasks))

        self.assertEqual(len(gestartet), 4)
        self.assertEqual(len(results), 4)


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

    def test_run_breaker_trips_across_waves_that_are_individually_harmless(self):
        """Keine einzelne Welle erreicht die 60%-Wellenschwelle, der Lauf blutet trotzdem aus."""
        host = _DispatchHost()
        ok_agent, dead_agent = AsyncMock(), AsyncMock()
        ok_agent.execute.return_value = AgentResult(
            task_id="t", agent_id="backend", agent_name="Backend", success=True, content="ok",
        )
        dead_agent.execute.return_value = AgentResult(
            task_id="t", agent_id="tester", agent_name="Tester",
            success=False, content="", error="429 RESOURCE_EXHAUSTED",
        )
        host._agents = {"backend": ok_agent, "tester": dead_agent}
        # Je Welle 1 von 3 erschöpft (33%) - unter der Wellenschwelle von 60%.
        for _ in range(3):
            asyncio.run(host._run_agents_parallel(
                [self._task("backend"), self._task("backend"), self._task("tester")]
            ))
        self.assertTrue(host._provider_breaker_tripped)
        self.assertTrue(host._provider_exhausted_this_run)

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
