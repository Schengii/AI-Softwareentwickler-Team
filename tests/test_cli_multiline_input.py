"""
tests/test_cli_multiline_input.py – Testet CLIInterface._read_user_input()

Realer Fund (Nutzeranfrage): `console.input()` (dünner Wrapper um Pythons `input()`) liest
immer nur bis zum ersten Zeilenumbruch. Eine mehrzeilige Aufgabenbeschreibung - oder ein in
das Terminal eingefügter mehrzeiliger Text - wurde dadurch NICHT als eine Eingabe erkannt,
sondern jede Zeile einzeln als eigener Prompt an interface/cli.py._main_loop() weitergereicht.
_read_user_input() erlaubt jetzt eine Fortsetzung über mehrere Zeilen, wenn eine Zeile auf ein
einzelnes `\\` endet - dieselbe Konvention wie in der Shell/in Python selbst.

Zweiter realer Fund (auditlog_sentinel, 2026-09-10): die `\\`-Konvention allein genügte nicht -
ein eingefügter mehrzeiliger Auftrag mit Zeilen wie "... (auditlog_sentinel). /" und
"2. Sicherheit & Governance:" startete ZWEI separate, unvollständige Läufe. Die restlichen
Tests hier decken die Paste-Erkennung, den Fragment-Schutz und den Blockmodus (dreifaches
Anführungszeichen als Start-/End-Markierung) ab, die das beheben.
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

    def test_trailing_slash_continuation_marker(self):
        # Realer Fund auditlog_sentinel: "Erstelle ein neues ... Projekt (auditlog_sentinel). /"
        # sollte als Fortsetzungsmarke erkannt werden, nicht als abgeschlossene Zeile.
        with patch("interface.cli.console.input", side_effect=[
            "Erstelle ein Projekt (auditlog_sentinel). /",
            "Architektur- und Technologie-Vorgaben: dieses und jenes.",
        ]):
            result = self.cli._read_user_input()
        self.assertIn("Erstelle ein Projekt (auditlog_sentinel).", result)
        self.assertIn("Architektur- und Technologie-Vorgaben", result)
        self.assertNotIn(" /", result)

    def test_block_mode_collects_everything_between_triple_quotes(self):
        with patch("interface.cli.console.input", side_effect=[
            '"""',
            "Erste Zeile.",
            "Zweite Zeile.",
            '"""',
        ]):
            result = self.cli._read_user_input()
        self.assertEqual(result, "Erste Zeile.\nZweite Zeile.")

    def test_block_mode_preserves_lines_that_look_like_continuations(self):
        # Innerhalb eines Blocks werden Zeilen NICHT auf \\-Fortsetzung geprüft - der Block-
        # Delimiter ist die einzige Steuerung.
        with patch("interface.cli.console.input", side_effect=[
            '"""',
            "Ende mit Backslash\\",
            '"""',
        ]):
            result = self.cli._read_user_input()
        self.assertEqual(result, "Ende mit Backslash\\")

    def test_fragment_detection_keeps_reading_short_heading_lines(self):
        # "2. Sicherheit & Governance:" sieht wie der Kopf einer mehrzeiligen Anforderung aus
        # (kurz, endet auf ":") - darf NICHT sofort als abgeschlossene Eingabe gelten.
        with patch("interface.cli.console.input", side_effect=[
            "2. Sicherheit & Governance:",
            "JWT-Auth und Rate-Limiting ergänzen.",
            "",
        ]):
            result = self.cli._read_user_input()
        self.assertIn("2. Sicherheit & Governance:", result)
        self.assertIn("JWT-Auth und Rate-Limiting ergänzen.", result)

    def test_fragment_detection_does_not_trigger_on_normal_sentences(self):
        with patch("interface.cli.console.input", side_effect=[
            "Baue eine Todo-App mit FastAPI und SQLite.",
        ]) as mock_input:
            result = self.cli._read_user_input()
        self.assertEqual(result, "Baue eine Todo-App mit FastAPI und SQLite.")
        mock_input.assert_called_once()

    def test_fragment_detection_does_not_trigger_on_slash_commands(self):
        with patch("interface.cli.console.input", side_effect=["/hilfe"]) as mock_input:
            result = self.cli._read_user_input()
        self.assertEqual(result, "/hilfe")
        mock_input.assert_called_once()

    def test_paste_detection_keeps_reading_without_continuation_marker(self):
        # Simuliert einen Terminal-Paste: nach der ersten Zeile warten bereits weitere Zeilen im
        # Puffer (_pending_console_input()==True), obwohl keine \\/" /"-Fortsetzungsmarke steht.
        with patch("interface.cli._pending_console_input", side_effect=[True, False]), \
             patch("interface.cli.console.input", side_effect=[
                 "Erste eingefügte Zeile ohne Marke",
                 "Zweite eingefügte Zeile.",
             ]):
            result = self.cli._read_user_input()
        self.assertEqual(result, "Erste eingefügte Zeile ohne Marke\nZweite eingefügte Zeile.")


if __name__ == "__main__":
    unittest.main()
