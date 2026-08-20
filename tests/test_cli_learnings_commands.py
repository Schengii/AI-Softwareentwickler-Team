"""
tests/test_cli_learnings_commands.py – Testet /learnings & /delete-learning in interface/cli.py

Realer Bedarf: memory/agent_learnings.json war bisher eine reine Black Box - fließt bei
JEDEM künftigen Aufruf eines Agenten automatisch in dessen System-Prompt ein (siehe
agent_knowledge_base.get_augmented_prompt), ohne dass der Mensch je einsehen oder eine
falsche/überholte Regel gezielt entfernen konnte (siehe tests/test_agent_learnings.py für
die Wissensbasis-Seite selbst).
"""

import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rich.console import Console as RichConsole

from interface.cli import CLIInterface
from memory.agent_knowledge_base import AgentKnowledgeBase


class TestLearningsCommands(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.kb = AgentKnowledgeBase(file_path=Path(self.temp_dir.name) / "learnings.json")
        self._kb_patcher = patch("memory.agent_knowledge_base.agent_knowledge_base", self.kb)
        self._kb_patcher.start()
        self.addCleanup(self._kb_patcher.stop)
        self.addCleanup(self.temp_dir.cleanup)

    def _handle(self, command: str) -> None:
        with patch("interface.cli.console.print"):
            asyncio.run(self.cli._handle_command(command))

    def test_learnings_command_with_empty_knowledge_base_shows_no_crash(self):
        # Kein console.print-Mock nötig für die eigentliche Assertion, aber konsistent mit
        # den übrigen Tests hier - stellt vor allem sicher, dass /learnings ohne Daten nicht crasht.
        self._handle("/learnings")

    @patch("interface.cli.console.print")
    def test_learnings_command_lists_all_agents_and_rules(self, mock_print):
        self.kb.add_learning("backend", "Nutze async def für I/O-gebundene Endpunkte.")
        self.kb.add_learning("frontend", "Vermeide inline styles.")

        asyncio.run(self.cli._handle_command("/learnings"))

        # console.print() bekommt ein rich.table.Table-Objekt, kein Klartext - über eine
        # eigene, aufzeichnende Console gerendert prüfen statt gegen rich-Interna zu greifen.
        # file=io.StringIO() verhindert, dass rich unter Windows zusätzlich versucht, über den
        # Legacy-Konsolen-Renderer auf das echte cp1252-Terminal zu schreiben (Emoji-Crash).
        capture = RichConsole(record=True, width=120, file=io.StringIO())
        for call in mock_print.call_args_list:
            for arg in call.args:
                capture.print(arg)
        rendered = capture.export_text()

        self.assertIn("backend", rendered)
        self.assertIn("frontend", rendered)
        self.assertIn("async def", rendered)

    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_delete_learning_with_confirmation_removes_the_rule(self, mock_confirm):
        self.kb.add_learning("backend", "Regel A")
        self.kb.add_learning("backend", "Regel B (falsch)")

        self._handle("/delete-learning backend 2")

        self.assertEqual(self.kb.get_learnings("backend"), ["Regel A"])

    @patch("interface.cli.Confirm.ask", return_value=False)
    def test_declining_confirmation_keeps_the_rule(self, mock_confirm):
        self.kb.add_learning("backend", "Regel A")

        self._handle("/delete-learning backend 1")

        self.assertEqual(self.kb.get_learnings("backend"), ["Regel A"])

    def test_delete_learning_with_missing_args_shows_hint_and_does_not_crash(self):
        self._handle("/delete-learning backend")  # keine Nummer angegeben

    def test_delete_learning_with_non_numeric_index_shows_error_not_crash(self):
        self.kb.add_learning("backend", "Regel A")
        self._handle("/delete-learning backend abc")
        self.assertEqual(self.kb.get_learnings("backend"), ["Regel A"])  # unverändert

    def test_delete_learning_with_unknown_agent_shows_error_not_crash(self):
        self._handle("/delete-learning does_not_exist 1")

    def test_delete_learning_with_out_of_range_index_shows_error_not_crash(self):
        self.kb.add_learning("backend", "Regel A")
        self._handle("/delete-learning backend 99")
        self.assertEqual(self.kb.get_learnings("backend"), ["Regel A"])  # unverändert


if __name__ == "__main__":
    unittest.main()
