"""
tests/test_cli_multiline_input.py – Testet CLIInterface._read_user_input()

Realer Fund (Nutzeranfrage): `console.input()` (dünner Wrapper um Pythons `input()`) liest
immer nur bis zum ersten Zeilenumbruch. Eine mehrzeilige Aufgabenbeschreibung - oder ein in
das Terminal eingefügter mehrzeiliger Text - wurde dadurch NICHT als eine Eingabe erkannt,
sondern jede Zeile einzeln als eigener Prompt an interface/cli.py._main_loop() weitergereicht.
_read_user_input() erlaubt jetzt eine Fortsetzung über mehrere Zeilen, wenn eine Zeile auf ein
einzelnes `\\` endet - dieselbe Konvention wie in der Shell/in Python selbst.
"""

import unittest
from unittest.mock import patch

from interface.cli import CLIInterface


class TestCLIMultilineInput(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()

    def test_single_line_input_unchanged(self):
        with patch("interface.cli.console.input", side_effect=["Baue eine Login-Seite"]) as mock_input:
            result = self.cli._read_user_input()
        self.assertEqual(result, "Baue eine Login-Seite")
        mock_input.assert_called_once()  # nur EIN console.input()-Aufruf für den Alltagsfall

    def test_trailing_backslash_continues_on_the_next_line(self):
        with patch("interface.cli.console.input", side_effect=[
            "Baue eine App mit folgenden Anforderungen: \\",
            "- Login \\",
            "- Dashboard",
        ]):
            result = self.cli._read_user_input()
        self.assertEqual(
            result,
            "Baue eine App mit folgenden Anforderungen: \n- Login \n- Dashboard",
        )

    def test_backslash_is_stripped_from_each_continued_line(self):
        with patch("interface.cli.console.input", side_effect=["erste Zeile\\", "zweite Zeile"]):
            result = self.cli._read_user_input()
        self.assertNotIn("\\", result)

    def test_result_is_stripped_of_surrounding_whitespace(self):
        with patch("interface.cli.console.input", side_effect=["  Aufgabe mit Leerzeichen  "]):
            result = self.cli._read_user_input()
        self.assertEqual(result, "Aufgabe mit Leerzeichen")

    def test_keyboard_interrupt_during_continuation_propagates(self):
        """Strg+C mitten in einer mehrzeiligen Eingabe muss weiterhin sauber abbrechen -
        dieselbe Behandlung wie bisher bei einer einzeiligen Eingabe (siehe _main_loop())."""
        with patch("interface.cli.console.input", side_effect=["erste Zeile\\", KeyboardInterrupt()]):
            with self.assertRaises(KeyboardInterrupt):
                self.cli._read_user_input()


if __name__ == "__main__":
    unittest.main()
