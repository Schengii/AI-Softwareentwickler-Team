"""
tests/test_user_feedback_command.py – Testet `/feedback <gut|schlecht> <text>`
(interface/cli.py._record_user_feedback())

KI-Team-Analyse 07.09.2026, Punkt 10 "Kein strukturiertes Feedback-System vom Nutzer zurück ans
Team": core/team_memory.py.record_lesson() wurde bisher NUR intern von der Retrospektive/dem
Optimization-Advisor aufgerufen. Dieser Test prüft den neuen, direkten Nutzer-Rückkanal, OHNE
die echte, versionierte memory/team_lessons.jsonl zu berühren (record_lesson() gemockt, dieselbe
Isolations-Philosophie wie tests/conftest.py._no_real_team_lesson_writes für den Orchestrator-
Pfad).
"""

import unittest
from unittest.mock import patch

from interface.cli import CLIInterface


class TestUserFeedbackCommand(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()
        self.cli._loaded_project_dir = None

    @patch("interface.cli.console.print")
    def test_missing_args_shows_usage_hint(self, mock_print):
        with patch("core.team_memory.record_lesson") as mock_record:
            self.cli._record_user_feedback([])
            mock_record.assert_not_called()
        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        self.assertIn("Nutzung", printed)

    @patch("interface.cli.console.print")
    def test_invalid_polarity_shows_usage_hint(self, mock_print):
        with patch("core.team_memory.record_lesson") as mock_record:
            self.cli._record_user_feedback(["neutral", "Text"])
            mock_record.assert_not_called()
        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        self.assertIn("Nutzung", printed)

    @patch("interface.cli.console.print")
    def test_positive_feedback_without_loaded_project_uses_team_slug(self, _mock_print):
        with patch("core.team_memory.record_lesson") as mock_record:
            self.cli._record_user_feedback(["gut", "Backend-Agent", "hat", "CORS", "korrekt", "gesetzt"])
            mock_record.assert_called_once_with(
                project_slug="_team", category="user_feedback_positive",
                detail="Backend-Agent hat CORS korrekt gesetzt",
            )

    @patch("interface.cli.console.print")
    def test_negative_feedback_uses_loaded_project_slug(self, _mock_print):
        self.cli._loaded_project_dir = "/workspace/mein_projekt"
        with patch("core.team_memory.record_lesson") as mock_record:
            self.cli._record_user_feedback(["schlecht", "Tester", "hat", "Mocks", "vergessen"])
            mock_record.assert_called_once_with(
                project_slug="mein_projekt", category="user_feedback_negative",
                detail="Tester hat Mocks vergessen",
            )

    @patch("interface.cli.console.print")
    def test_accepts_synonyms_positiv_negativ(self, _mock_print):
        with patch("core.team_memory.record_lesson") as mock_record:
            self.cli._record_user_feedback(["positiv", "Test"])
            self.cli._record_user_feedback(["negativ", "Test"])
            self.assertEqual(mock_record.call_count, 2)
            self.assertEqual(mock_record.call_args_list[0].kwargs["category"], "user_feedback_positive")
            self.assertEqual(mock_record.call_args_list[1].kwargs["category"], "user_feedback_negative")


if __name__ == "__main__":
    unittest.main()
