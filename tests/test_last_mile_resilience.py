"""
tests/test_last_mile_resilience.py – Testet die Absicherung der beiden ungeschützten
LLM-Aufrufe außerhalb des Agenten-Systems (ResultAggregator, TaskManager)

Realer Fund aus einem echten End-to-End-Lauf: Als an einem Tag alle konfigurierten
Provider gleichzeitig erschöpft/nicht erreichbar waren (Groq-Tageslimit + kein Claude-Key),
stürzte der GESAMTE Lauf ganz am Ende beim finalen Synthese-Schritt ab – obwohl das Team
zu diesem Zeitpunkt bereits echte Arbeit geleistet hatte (Dateien geschrieben, Tests
bestanden, alles im Workspace gespeichert). Der Nutzer bekam nur einen Crash zu sehen,
keinerlei Ergebnis. BaseAgent.execute() fängt sowas längst ab (siehe agents/base_agent.py) –
ResultAggregator und TaskManager sind aber KEINE Agenten und hatten diesen Schutz nicht.
"""

import unittest
from unittest.mock import AsyncMock

from core.message_bus import AgentResult
from core.result_aggregator import ResultAggregator
from core.task_manager import TaskManager


class TestResultAggregatorFallback(unittest.TestCase):
    def setUp(self):
        self.aggregator = ResultAggregator(model_name="gemini-3.6-flash")
        self.aggregator._llm = AsyncMock()

    def test_synthesize_falls_back_when_all_providers_unavailable(self):
        self.aggregator._llm.generate_with_usage.side_effect = RuntimeError(
            "Gemini API Fehler nach allen Versuchen: Claude nicht verfügbar (kein Key)."
        )
        results = [
            AgentResult(
                task_id="t1", agent_id="backend", agent_name="Backend-Entwickler",
                success=True, content="calculator.py wurde erstellt.", files_written=["calculator.py"],
            ),
        ]

        text, tokens = self._run(self.aggregator.synthesize("Baue einen Rechner", "Rechner-App", results))

        self.assertEqual(tokens, 0)
        self.assertIn("Automatische Synthese nicht verfügbar", text)
        # Die echte Arbeit des Teams darf trotzdem sichtbar bleiben, nicht nur eine Fehlermeldung.
        self.assertIn("Backend-Entwickler", text)
        self.assertIn("calculator.py wurde erstellt.", text)

    def test_synthesize_still_works_normally_on_success(self):
        from core.llm_factory import LLMResponse
        self.aggregator._llm.generate_with_usage.return_value = LLMResponse(
            text="Fertige Zusammenfassung.", model_name="gemini-3.6-flash",
            prompt_tokens=10, completion_tokens=5, total_tokens=15,
        )
        results = [AgentResult(task_id="t1", agent_id="backend", agent_name="Backend", success=True, content="ok")]

        text, tokens = self._run(self.aggregator.synthesize("Aufgabe", "Zusammenfassung", results))

        self.assertEqual(text, "Fertige Zusammenfassung.")
        self.assertEqual(tokens, 15)

    @staticmethod
    def _run(coro):
        import asyncio
        return asyncio.run(coro)


class TestTaskManagerFallback(unittest.TestCase):
    def setUp(self):
        self.task_manager = TaskManager(model_name="gemini-3.6-flash")
        self.task_manager._llm = AsyncMock()

    def test_decompose_falls_back_when_all_providers_unavailable(self):
        self.task_manager._llm.generate_json.side_effect = RuntimeError("Alle Provider erschöpft.")

        import asyncio
        task_summary, project_slug, agent_tasks = asyncio.run(
            self.task_manager.decompose("Baue eine App")
        )

        self.assertTrue(task_summary.startswith("⚠️"))
        self.assertEqual(agent_tasks, [])
        # Orchestrator.process() muss diesen Fall (task_summary beginnt mit "⚠️") erkennen
        # und ihn dem Nutzer direkt zeigen können, statt der generischen Standardmeldung.


if __name__ == "__main__":
    unittest.main()
