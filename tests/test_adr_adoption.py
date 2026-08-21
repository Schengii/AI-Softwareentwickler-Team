"""
tests/test_adr_adoption.py – Testet die ADR-Adoption-Verbesserungen (zweite Verteidigungslinie)

Realer Fund aus dem echten End-to-End-Testlauf: obwohl die Aufgabe explizit eine
Technologie-Abwägung mit echter Alternative verlangte ("wäge zwischen In-Memory-Liste und
SQLite ab"), plante der Hauptagent den architect-Agenten gar nicht erst ein - backend/database
trafen die Entscheidung dann selbst, ohne sie je über record_architecture_decision zu
dokumentieren. Zwei unabhängige Gegenmaßnahmen:

1. core/task_manager.py: DECOMPOSE_SYSTEM_PROMPT bekommt eine explizite, nicht-optionale
   Einbeziehungs-Regel für architect (analog zu den bestehenden Regeln für
   security/compliance/tester) - dies ist bewusst nur ein Regressionstest auf den Prompt-TEXT
   selbst (dass die Regel nicht versehentlich wieder verschwindet), KEIN Beweis, dass ein
   echtes LLM ihr tatsächlich folgt (das kann nur ein echter Lauf zeigen).
2. agents/base_agent.py: Code-schreibende Agenten (CODE_WRITING_AGENT_IDS) selbst bekommen
   zusätzlich einen expliziten Hinweis auf das record_architecture_decision-Werkzeug, falls
   architect trotzdem nicht eingeplant wird.
"""

import unittest

from agents.backend_agent import BackendAgent
from agents.copywriter_agent import CopywriterAgent
from core.task_manager import DECOMPOSE_SYSTEM_PROMPT


class TestDecomposePromptIncludesArchitectRule(unittest.TestCase):
    def test_architect_inclusion_rule_is_present_and_non_optional(self):
        self.assertIn("architect einbeziehen", DECOMPOSE_SYSTEM_PROMPT)
        self.assertIn("NICHT optional", DECOMPOSE_SYSTEM_PROMPT.split("architect einbeziehen")[1][:400])


class TestCodeWritingAgentsGetAdrReminder(unittest.TestCase):
    def test_code_writing_agent_sees_adr_tool_reminder(self):
        agent = BackendAgent()
        augmented = agent._augment_with_tool_instructions("Basis-Prompt.")
        self.assertIn("record_architecture_decision", augmented)

    def test_non_code_writing_agent_does_not_see_adr_reminder(self):
        # copywriter trifft legitim keine Architektur-Entscheidungen - kein unnötiger
        # Prompt-Text für eine Rolle, die ihn nie braucht.
        agent = CopywriterAgent()
        augmented = agent._augment_with_tool_instructions("Basis-Prompt.")
        self.assertNotIn("record_architecture_decision", augmented)


if __name__ == "__main__":
    unittest.main()
