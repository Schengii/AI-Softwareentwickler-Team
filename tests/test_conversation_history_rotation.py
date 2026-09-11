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

from memory.conversation_history import MAX_MESSAGES_KEPT, ConversationHistory


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


if __name__ == "__main__":
    unittest.main()
