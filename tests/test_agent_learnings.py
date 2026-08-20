"""
tests/test_agent_learnings.py – Testet die persistente Selbstoptimierung & Wissensbasis der Agenten
"""

import tempfile
import unittest
from pathlib import Path

from memory.agent_knowledge_base import MAX_RULE_LENGTH, AgentKnowledgeBase


class TestAgentKnowledgeBase(unittest.TestCase):
    """Testet das persistente Langzeitgedächtnis für Agenten-Optimierungen."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.file_path = Path(self.temp_dir.name) / "test_learnings.json"
        self.kb = AgentKnowledgeBase(file_path=self.file_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_add_and_retrieve_learning(self):
        self.kb.add_learning("database", "Verwende stets db_index=True bei ForeignKey-Relationen.")
        learnings = self.kb.get_learnings("database")
        self.assertEqual(len(learnings), 1)
        self.assertIn("db_index=True", learnings[0])

    def test_overlong_rule_is_truncated_to_prevent_permanent_prompt_bloat(self):
        """
        Jede gespeicherte Regel landet bei JEDEM künftigen Aufruf des Agenten im
        System-Prompt (siehe get_augmented_prompt) - eine einzelne, unbegrenzt lange
        "Regel" (der Trainer-Agent liefert Freitext) würde diesen Tokenverbrauch bei
        jedem künftigen Lauf unbemerkt wiederholen.
        """
        overlong_rule = "Wichtige Regel: " + ("sehr ausführlicher Text " * 30)
        self.assertGreater(len(overlong_rule), MAX_RULE_LENGTH)

        self.kb.add_learning("backend", overlong_rule)
        stored = self.kb.get_learnings("backend")[0]

        self.assertLessEqual(len(stored), MAX_RULE_LENGTH + 1)  # +1 für das "…"-Suffix
        self.assertTrue(stored.endswith("…"))

    def test_prompt_augmentation(self):
        self.kb.add_learning("backend", "Verwende async def für alle I/O-gebundenen Endpunkte.")
        base_prompt = "Du bist ein Backend-Entwickler."
        augmented = self.kb.get_augmented_prompt("backend", base_prompt)
        self.assertIn("Du bist ein Backend-Entwickler.", augmented)
        self.assertIn("GELERNTE BEST PRACTICES", augmented)
        self.assertIn("async def", augmented)


if __name__ == "__main__":
    unittest.main()
