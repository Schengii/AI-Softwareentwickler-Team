"""
tests/test_push_gate_verification_warning.py – Testet die Verifikations-Warnung vor Push

Realer Fund: JEDER Lauf endete mit demselben "✅ Fertig!", egal ob die echte Testsuite
tatsächlich bestanden hatte, nie gefunden wurde, oder weiter fehlschlug – wer nur die
Push-Bestätigung sah, hatte keinen Hinweis darauf, dass der zu committende Code nie
verifiziert wurde. interface/cli.py._ask_for_git_push() zeigt jetzt eine klare Warnung
und eine andere Bestätigungsfrage, wenn Orchestrator.last_verification_ok False ist.
"""

import asyncio
import unittest
from unittest.mock import MagicMock, patch

from interface.cli import CLIInterface


class TestPushGateVerificationWarning(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()
        self.fake_github = MagicMock()
        self.fake_github.get_status.return_value = "M some_file.py"
        self.fake_github.get_diff.return_value = "some_file.py | 3 +--"
        self.fake_github.commit.return_value = (True, "commit ok")
        self.fake_github.push.return_value = (True, "push ok")
        self.cli._orchestrator._agents["github"] = self.fake_github
        self._print_patcher = patch("interface.cli.console.print")
        self._print_patcher.start()
        self.addCleanup(self._print_patcher.stop)

    @patch("interface.cli.Confirm.ask", return_value=False)
    def test_shows_warning_prompt_when_verification_failed(self, mock_confirm):
        self.cli._orchestrator.last_verification_ok = False
        asyncio.run(self.cli._ask_for_git_push("Testaufgabe"))
        prompt_text = mock_confirm.call_args[0][0]
        self.assertIn("NICHT bestandener", prompt_text)

    @patch("interface.cli.Confirm.ask", return_value=False)
    def test_no_warning_prompt_when_verification_passed(self, mock_confirm):
        self.cli._orchestrator.last_verification_ok = True
        asyncio.run(self.cli._ask_for_git_push("Testaufgabe"))
        prompt_text = mock_confirm.call_args[0][0]
        self.assertNotIn("NICHT bestandener", prompt_text)

    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_can_still_push_after_explicit_confirmation_despite_failed_verification(self, mock_confirm):
        """Die Warnung blockiert nichts hart - der Mensch kann bewusst trotzdem pushen."""
        self.cli._orchestrator.last_verification_ok = False
        asyncio.run(self.cli._ask_for_git_push("Testaufgabe"))
        self.fake_github.commit.assert_called_once()
        self.fake_github.push.assert_called_once()


if __name__ == "__main__":
    unittest.main()
