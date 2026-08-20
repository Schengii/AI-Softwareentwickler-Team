"""
tests/test_clarifying_questions.py – Testet Rückfragen bei unklaren Anforderungen

Realer Fund: vage Nutzeranfragen ("Ich möchte, dass ihr das Projekt weiter verbessert")
führten bisher dazu, dass der Planer einfach irgendein thematisch beliebiges Demo-Projekt
erfand, statt nachzufragen - ein erfahrener Senior-Entwickler würde bei einer derart
unklaren Aufgabe zuerst präzisierende Fragen stellen. TaskManager.decompose() erkennt
jetzt "needs_clarification" im Modell-Output und liefert die Fragen statt eines geratenen
Plans; Orchestrator.process() zeigt sie direkt an, OHNE auch nur einen einzigen Agenten
zu starten (kein Tokenverbrauch für einen erratenen, möglicherweise falschen Plan).
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from agents.orchestrator import Orchestrator
from core.task_manager import TaskManager


class TestTaskManagerClarification(unittest.TestCase):
    def setUp(self):
        self.task_manager = TaskManager(model_name="gemini-3.6-flash")
        self.task_manager._llm = AsyncMock()

    def test_returns_questions_when_model_signals_needs_clarification(self):
        self.task_manager._llm.generate_json.return_value = json.dumps({
            "needs_clarification": True,
            "clarifying_questions": ["Welche Datenbank soll verwendet werden?", "Wer sind die Nutzer der App?"],
            "task_summary": "",
            "project_slug": "",
            "required_agents": [],
        })

        task_summary, project_slug, agent_tasks = asyncio.run(
            self.task_manager.decompose("Baut mir irgendwas Nützliches")
        )

        self.assertTrue(task_summary.startswith("❓"))
        self.assertIn("Welche Datenbank", task_summary)
        self.assertIn("Wer sind die Nutzer", task_summary)
        self.assertEqual(agent_tasks, [])

    def test_normal_plan_is_unaffected_when_clarification_not_needed(self):
        self.task_manager._llm.generate_json.return_value = json.dumps({
            "needs_clarification": False,
            "clarifying_questions": [],
            "task_summary": "Health-Check-Endpoint implementiert",
            "project_slug": "health_check",
            "required_agents": [{"agent_id": "backend", "task": "Endpoint bauen"}],
        })

        task_summary, project_slug, agent_tasks = asyncio.run(
            self.task_manager.decompose("Baue einen Health-Check-Endpoint mit FastAPI")
        )

        self.assertEqual(task_summary, "Health-Check-Endpoint implementiert")
        self.assertEqual(len(agent_tasks), 1)

    def test_clarification_flag_without_questions_is_ignored(self):
        """needs_clarification=true aber leere Fragenliste - degenerierter Modell-Output,
        darf nicht zu einem stummen 'nichts passiert' ohne jede Erklärung führen."""
        self.task_manager._llm.generate_json.return_value = json.dumps({
            "needs_clarification": True,
            "clarifying_questions": [],
            "task_summary": "Trotzdem etwas gebaut",
            "project_slug": "fallback_proj",
            "required_agents": [{"agent_id": "backend", "task": "Etwas bauen"}],
        })

        task_summary, project_slug, agent_tasks = asyncio.run(
            self.task_manager.decompose("Baue etwas")
        )

        self.assertFalse(task_summary.startswith("❓"))
        self.assertEqual(len(agent_tasks), 1)


class TestOrchestratorClarificationCostsNoAgentRun(unittest.TestCase):
    def test_no_agent_is_executed_when_clarification_is_needed(self):
        orchestrator = Orchestrator()
        for agent in orchestrator._agents.values():
            agent.execute = AsyncMock(side_effect=AssertionError(
                "Kein Agent darf laufen, solange eine Rückfrage offen ist!"
            ))

        with patch("core.task_manager.TaskManager.decompose") as mock_decompose:
            mock_decompose.return_value = (
                "❓ Bevor ich das Team loslasse, brauche ich noch eine Präzisierung:\n\n1. Welches Zielsystem?",
                "project", [],
            )
            result = asyncio.run(orchestrator.process("Baut mir irgendwas"))

        self.assertIn("❓", result)
        self.assertIn("Welches Zielsystem", result)


if __name__ == "__main__":
    unittest.main()
