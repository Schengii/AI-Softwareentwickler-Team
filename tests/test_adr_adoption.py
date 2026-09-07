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
from agents.ml_agent import MLAgent
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


class TestWriteAccessNoteReflectsReadOnlyFlag(unittest.TestCase):
    """
    Realer Fund (omnichat-Projekt): der security-Agent identifizierte ein echtes kritisches
    Problem, hatte aber keine Schreibrechte und fragte per `ask_human_for_clarification` nach
    ihnen - eine Frage, die nie beantwortet wurde, obwohl core/review_gate.py bereits eine
    automatische Fix-Schleife für genau diesen Fall bereitstellt. `_augment_with_tool_instructions`
    macht den tatsächlichen Schreibzugriffs-Status jetzt explizit im Prompt sichtbar.
    """

    def test_read_only_task_tells_agent_to_report_not_ask(self):
        agent = BackendAgent()
        augmented = agent._augment_with_tool_instructions("Basis-Prompt.", read_only=True)
        self.assertIn("KEINEN Schreibzugriff", augmented)
        self.assertIn("AUCH NICHT über `ask_human_for_clarification` nach Schreibrechten", augmented)

    def test_write_enabled_task_tells_agent_to_fix_directly(self):
        agent = BackendAgent()
        augmented = agent._augment_with_tool_instructions("Basis-Prompt.", read_only=False)
        self.assertIn("vollen Schreibzugriff", augmented)

    def test_default_matches_write_enabled_behavior(self):
        # Kein `read_only`-Argument (Standardfall) darf sich nicht wie ein Nur-Lese-Aufruf
        # verhalten - bestehende Aufrufer (z.B. der ADR-Reminder-Test oben) übergeben es nicht.
        agent = BackendAgent()
        augmented = agent._augment_with_tool_instructions("Basis-Prompt.")
        self.assertIn("vollen Schreibzugriff", augmented)


class TestCodeWritingAgentsGetExceptionHandlingNote(unittest.TestCase):
    """
    Nutzerauftrag: ruff-Fund BLE001 (`except Exception:` ohne Weiterbehandlung) trat wiederholt
    über mehrere Projekte hinweg auf und erzeugte damit dauerhaftes Rauschen im
    Verifikationsprotokoll bzw. ein "recurring-lint-"-Ticket (core/project_status.py.
    has_repeated_lint_finding()). Code-schreibende Agenten bekommen jetzt vorab die konkrete
    Regel (spezifischere Exception ODER dokumentiertes bewusstes noqa), statt den Fund erst
    hinterher als Ticket zu melden.
    """

    def test_code_writing_agent_sees_exception_handling_note(self):
        agent = BackendAgent()
        augmented = agent._augment_with_tool_instructions("Basis-Prompt.")
        self.assertIn("FEHLERBEHANDLUNG", augmented)
        self.assertIn("except Exception", augmented)

    def test_ml_agent_sees_exception_handling_note(self):
        agent = MLAgent()
        augmented = agent._augment_with_tool_instructions("Basis-Prompt.")
        self.assertIn("FEHLERBEHANDLUNG", augmented)

    def test_non_code_writing_agent_does_not_see_exception_handling_note(self):
        agent = CopywriterAgent()
        augmented = agent._augment_with_tool_instructions("Basis-Prompt.")
        self.assertNotIn("FEHLERBEHANDLUNG", augmented)


if __name__ == "__main__":
    unittest.main()
