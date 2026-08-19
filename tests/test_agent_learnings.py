"""
tests/test_agent_learnings.py – Testet die persistente Selbstoptimierung & Wissensbasis der Agenten
"""

import unittest
import tempfile
from pathlib import Path
from memory.agent_knowledge_base import AgentKnowledgeBase


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

    def test_prompt_augmentation(self):
        self.kb.add_learning("backend", "Verwende async def für alle I/O-gebundenen Endpunkte.")
        base_prompt = "Du bist ein Backend-Entwickler."
        augmented = self.kb.get_augmented_prompt("backend", base_prompt)
        self.assertIn("Du bist ein Backend-Entwickler.", augmented)
        self.assertIn("GELERNTE BEST PRACTICES", augmented)
        self.assertIn("async def", augmented)


if __name__ == "__main__":
    unittest.main()
