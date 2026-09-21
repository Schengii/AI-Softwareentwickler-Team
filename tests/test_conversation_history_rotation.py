"""
tests/test_conversation_history_rotation.py – Regressionstest für ki_team_verbesserungsanalyse.md,
Teil 5.5: `memory/history_default.json` wuchs unbegrenzt auf 13,2 MB an, weil
memory/conversation_history.py.ConversationHistory bisher KEINE Obergrenze für die Anzahl
gespeicherter Nachrichten kannte (anders als z.B. memory/run_history.py.MAX_RUNS_KEPT).
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from memory.conversation_history import MAX_MESSAGE_CONTENT_CHARS, MAX_MESSAGES_KEPT, ConversationHistory


class TestConversationHistoryRotation(unittest.TestCase):
    def test_ueberschreitende_nachrichten_werden_beim_speichern_verworfen(self):
        with TemporaryDirectory() as tmp:
            with patch("memory.conversation_history.MEMORY_DIR", tmp):
                history = ConversationHistory(session_id="rotation_test")
                for i in range(MAX_MESSAGES_KEPT + 50):
                    history.add_user_message(f"Nachricht {i}")

                self.assertEqual(len(history), MAX_MESSAGES_KEPT)
                # Die ÄLTESTEN Nachrichten fliegen raus, nicht die neuesten.
                messages = history.get_messages(max_messages=MAX_MESSAGES_KEPT)
                self.assertEqual(messages[-1].content, f"Nachricht {MAX_MESSAGES_KEPT + 49}")
                self.assertNotIn("Nachricht 0", [m.content for m in messages])

                on_disk = json.loads(Path(tmp, "history_rotation_test.json").read_text(encoding="utf-8"))
                self.assertEqual(len(on_disk), MAX_MESSAGES_KEPT)

    def test_bereits_ueberlange_datei_wird_beim_laden_einmalig_kompaktiert(self):
        with TemporaryDirectory() as tmp:
            oversized_file = Path(tmp, "history_legacy.json")
            oversized_file.write_text(
                json.dumps([
                    {"role": "user", "content": f"alt {i}", "timestamp": "2026-01-01T00:00:00"}
                    for i in range(MAX_MESSAGES_KEPT + 500)
                ]),
                encoding="utf-8",
            )

            with patch("memory.conversation_history.MEMORY_DIR", tmp):
                history = ConversationHistory(session_id="legacy")

            self.assertEqual(len(history), MAX_MESSAGES_KEPT)
            # Die Kompaktierung wurde sofort persistiert, nicht erst bei der nächsten Nachricht.
            on_disk = json.loads(oversized_file.read_text(encoding="utf-8"))
            self.assertEqual(len(on_disk), MAX_MESSAGES_KEPT)
            self.assertEqual(on_disk[-1]["content"], f"alt {MAX_MESSAGES_KEPT + 499}")


class TestConversationHistoryContentSizeCap(unittest.TestCase):
    """P6-3 (ROADMAP_TEMP.md): die reine Anzahl-Obergrenze allein begrenzte nicht die GRÖSSE -
    memory/history_default.json lag bei 195 Nachrichten trotzdem bei 2 MB, weil eine einzelne
    assistant-Nachricht (ein kompletter Abschlussbericht) bis zu ~50.000 Zeichen groß werden
    kann, obwohl weder get_context_string() noch interface/cli.py._print_history() je mehr als
    500 bzw. 100 Zeichen davon lesen."""

    def test_new_oversized_message_is_truncated_on_write(self):
        with TemporaryDirectory() as tmp:
            with patch("memory.conversation_history.MEMORY_DIR", tmp):
                history = ConversationHistory(session_id="size_cap_test")
                huge = "x" * (MAX_MESSAGE_CONTENT_CHARS * 3)
                history.add_assistant_message(huge)

                stored = history.get_messages(max_messages=1)[0].content
                self.assertLess(len(stored), len(huge))
                self.assertLessEqual(len(stored), MAX_MESSAGE_CONTENT_CHARS)
                self.assertIn("gekürzt", stored)

    def test_short_message_is_stored_unchanged(self):
        with TemporaryDirectory() as tmp:
            with patch("memory.conversation_history.MEMORY_DIR", tmp):
                history = ConversationHistory(session_id="size_cap_test_short")
                history.add_user_message("Baue eine Login-Seite")

                self.assertEqual(history.get_messages(max_messages=1)[0].content, "Baue eine Login-Seite")

    def test_legacy_oversized_content_is_truncated_once_on_load(self):
        with TemporaryDirectory() as tmp:
            legacy_file = Path(tmp, "history_legacy_size.json")
            huge = "y" * (MAX_MESSAGE_CONTENT_CHARS * 4)
            legacy_file.write_text(
                json.dumps([{"role": "assistant", "content": huge, "timestamp": "2026-01-01T00:00:00"}]),
                encoding="utf-8",
            )

            with patch("memory.conversation_history.MEMORY_DIR", tmp):
                history = ConversationHistory(session_id="legacy_size")

            stored = history.get_messages(max_messages=1)[0].content
            self.assertLessEqual(len(stored), MAX_MESSAGE_CONTENT_CHARS)
            # Sofort persistiert, nicht erst bei der nächsten Nachricht.
            on_disk = json.loads(legacy_file.read_text(encoding="utf-8"))
            self.assertLessEqual(len(on_disk[0]["content"]), MAX_MESSAGE_CONTENT_CHARS)


if __name__ == "__main__":
    unittest.main()
