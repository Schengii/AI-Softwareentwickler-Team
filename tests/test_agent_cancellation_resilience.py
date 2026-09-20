"""
tests/test_agent_cancellation_resilience.py – Ein abgebrochener Agenten-Aufruf reißt nicht den
ganzen Lauf mit

Realer Fund (Ticket `orchestrator-crash-CancelledError-entwickle_eventforge_ein_webhook`,
Traceback in `agents/base_agent.py._run_agentic_loop` -> `generate_with_tools`): ein
`asyncio.CancelledError` erbt von `BaseException`, NICHT von `Exception`. Der allgemeine
`except Exception`-Handler in `BaseAgent.execute()` fing ihn deshalb nie - der Abbruch EINES
Agenten-Aufrufs beendete den GESAMTEN Lauf samt aller bis dahin geleisteten Arbeit, und das
Backlog trug den Absturz als `orchestrator_crash`-Ticket.

Pauschal schlucken wäre falsch: `CancelledError` ist der Mechanismus, mit dem asyncio
kooperative Abbrüche umsetzt. Wurde der laufende Task tatsächlich zum Abbruch angefordert
(`Task.cancelling() > 0`), MUSS die Ausnahme weiterlaufen - sonst hängt ein Nutzer-Abbruch oder
ein `asyncio.wait_for`. Nur ein Abbruch ohne solche Anforderung (z.B. tief im Provider-SDK)
wird zu einem gewöhnlichen Fehlschlag dieses einen Schritts.
"""

from __future__ import annotations

import asyncio
import unittest

from agents.backend_agent import BackendAgent
from core.message_bus import AgentTask
from core.provider_exhaustion import (
    FAILURE_CLASS_CANCELLED,
    is_infrastructure_failure,
)


class _CancellingLLM:
    """Bricht den Modell-Aufruf ab, ohne dass der Task zum Abbruch angefordert wurde -
    simuliert einen Abbruch tief im Provider-SDK."""

    model_name = "fake-model"

    async def generate_with_tools(self, *_a, **_kw):
        raise asyncio.CancelledError()

    async def generate_with_usage(self, *_a, **_kw):
        raise asyncio.CancelledError()


class TestCancelledAgentCallBecomesFailedStep(unittest.TestCase):
    def setUp(self):
        self.agent = BackendAgent()
        self.agent._llm = _CancellingLLM()
        self.task = AgentTask(task_id="t1", agent_id="backend", description="Baue app/main.py")

    def test_cancelled_call_returns_failed_result_instead_of_crashing(self):
        result = asyncio.run(self.agent.execute(self.task))

        self.assertFalse(result.success)
        self.assertEqual(result.failure_class, FAILURE_CLASS_CANCELLED)
        self.assertIn("abgebrochen", result.error)
        self.assertEqual(result.agent_id, "backend")

    def test_cancellation_is_not_blamed_on_the_agent(self):
        """Ein nie zu Ende geführter Aufruf sagt nichts über die Qualität des Agenten - er
        darf seine Erfolgsquote nicht belasten (dieselbe Linie wie bei 429/fehlendem Key)."""
        self.assertTrue(is_infrastructure_failure(FAILURE_CLASS_CANCELLED))

        result = asyncio.run(self.agent.execute(self.task))
        # Kein Modell zugeordnet: der Aufruf kam nie zu einer Antwort.
        self.assertEqual(result.model_used, "")

    def test_real_task_cancellation_still_propagates(self):
        """Gegenprobe - der wichtigste Teil: ein ECHTER Abbruch (Nutzer-Stopp, wait_for) muss
        weiterlaufen, sonst lässt sich der Lauf nicht mehr abbrechen."""

        async def _scenario():
            task = asyncio.current_task()

            class _SelfCancellingLLM:
                model_name = "fake-model"

                async def generate_with_tools(self, *_a, **_kw):
                    task.cancel()
                    await asyncio.sleep(0)

                async def generate_with_usage(self, *_a, **_kw):
                    task.cancel()
                    await asyncio.sleep(0)

            self.agent._llm = _SelfCancellingLLM()
            return await self.agent.execute(self.task)

        async def _outer():
            inner = asyncio.create_task(_scenario())
            with self.assertRaises(asyncio.CancelledError):
                await inner

        asyncio.run(_outer())


if __name__ == "__main__":
    unittest.main()
