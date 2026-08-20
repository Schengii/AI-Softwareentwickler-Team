"""
tests/test_error_visibility.py – Testet, dass rohe Agenten-Fehlertexte den Nutzer wirklich erreichen

Realer Fund aus einem echten Lauf: Ein Agent (backend) schlug komplett fehl (0 Tokens
verarbeitet), aber der reale Fehlertext (AgentResult.error) landete NIRGENDS beim Nutzer –
weder in der Live-Statuszeile ("❌ Fehler: Backend-Entwickler (61.7s)" ohne jeden Grund) noch
im finalen Ergebnis. Nur die Retrospektive (ein separater, freier LLM-Aufruf) paraphrasierte
den Fehler unverifiziert. Dieser Test stellt sicher, dass der rohe Fehlertext jetzt sowohl in
der Live-Statuszeile als auch garantiert (nicht nur LLM-abhängig) im finalen Ergebnis auftaucht.
"""

import asyncio
import unittest

from agents.orchestrator import Orchestrator
from core.message_bus import AgentResult, AgentTask


class TestErrorVisibility(unittest.TestCase):
    def setUp(self):
        self.orchestrator = Orchestrator()

    def test_status_notify_line_includes_raw_error_on_failure(self):
        line = Orchestrator._status_notify_line(
            "✅ OK", "❌ FAIL", "Backend-Entwickler", 61.7, False,
            "400 INVALID_ARGUMENT: Function call is missing a thought_signature",
        )
        self.assertIn("❌ FAIL", line)
        self.assertIn("Backend-Entwickler", line)
        self.assertIn("400 INVALID_ARGUMENT", line)
        self.assertIn("thought_signature", line)

    def test_status_notify_line_omits_error_note_on_success(self):
        line = Orchestrator._status_notify_line("✅ OK", "❌ FAIL", "Backend-Entwickler", 12.3, True, None)
        self.assertIn("✅ OK", line)
        self.assertNotIn(" — ", line)  # kein Fehler-Anhängsel bei Erfolg

    def test_parallel_run_notifies_raw_error_text(self):
        async def _boom(task: AgentTask) -> AgentResult:
            return AgentResult(
                task_id=task.task_id, agent_id=task.agent_id, agent_name="Backend-Entwickler",
                success=False, content="", error="400 INVALID_ARGUMENT: fehlende thought_signature",
                duration_seconds=61.7,
            )

        self.orchestrator._run_single_agent = _boom
        notified: list[str] = []
        task = AgentTask(task_id="t1", agent_id="backend", description="API bauen")

        asyncio.run(self.orchestrator._run_agents_parallel([task], notify=notified.append))

        self.assertTrue(any("thought_signature" in msg for msg in notified))

    def test_metrics_summary_includes_raw_error_block_on_failure(self):
        results = [
            AgentResult(
                task_id="t1", agent_id="backend", agent_name="Backend-Entwickler",
                success=False, content="", error="400 INVALID_ARGUMENT: fehlende thought_signature",
            ),
        ]
        summary = self.orchestrator._build_metrics_summary(
            results=results, synth_tokens=10, total_duration=5.0, project_dir="test_proj",
        )
        self.assertIn("Rohe Fehlermeldungen", summary)
        self.assertIn("thought_signature", summary)
        self.assertIn("Backend-Entwickler", summary)

    def test_metrics_summary_omits_error_block_when_all_succeed(self):
        results = [
            AgentResult(task_id="t1", agent_id="backend", agent_name="Backend-Entwickler", success=True, content="ok"),
        ]
        summary = self.orchestrator._build_metrics_summary(
            results=results, synth_tokens=10, total_duration=5.0, project_dir="test_proj",
        )
        self.assertNotIn("Rohe Fehlermeldungen", summary)


if __name__ == "__main__":
    unittest.main()
