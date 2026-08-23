"""
tests/test_notifier.py – Testet core/notifier.py (optionale externe Benachrichtigung)

core/issue_watcher.py (Cron-Poll-Zyklus) und interface/web_dashboard.py (Hintergrund-Jobs)
laufen unbeaufsichtigt - dieser Test stellt sicher, dass notify_external() ohne konfigurierten
Webhook ein reines No-op ist, mit Webhook den erwarteten POST absetzt, und ein Fehlschlag beim
Senden NIE eine Exception nach außen durchreicht (Best-Effort-Prinzip).
"""

import unittest
from unittest.mock import patch

from core.notifier import notify_external


class TestNotifyExternal(unittest.TestCase):
    @patch("core.notifier.httpx.post")
    @patch("core.notifier.NOTIFY_WEBHOOK_URL", "")
    def test_no_webhook_configured_sends_nothing(self, mock_post):
        notify_external("Test-Event", "Test-Nachricht")
        mock_post.assert_not_called()

    @patch("core.notifier.httpx.post")
    @patch("core.notifier.NOTIFY_WEBHOOK_URL", "https://hooks.example.com/x")
    def test_configured_webhook_sends_expected_payload(self, mock_post):
        notify_external("Lauf-Budget erreicht", "42/100 Tokens verbraucht.")

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://hooks.example.com/x")
        self.assertIn("Lauf-Budget erreicht", kwargs["json"]["text"])
        self.assertIn("42/100 Tokens verbraucht.", kwargs["json"]["text"])

    @patch("core.notifier.httpx.post", side_effect=ConnectionError("kein Netzwerk"))
    @patch("core.notifier.NOTIFY_WEBHOOK_URL", "https://hooks.example.com/x")
    def test_send_failure_is_swallowed(self, mock_post):
        try:
            notify_external("Test-Event", "Test-Nachricht")
        except Exception as e:  # noqa: BLE001 - genau das darf hier NIE passieren
            self.fail(f"notify_external() durfte keine Exception werfen, hat aber: {e}")

    @patch("core.notifier.httpx.post")
    @patch("core.notifier.NOTIFY_WEBHOOK_URL", "https://hooks.example.com/x")
    def test_payload_uses_slack_block_kit_with_event_and_message(self, mock_post):
        notify_external("Lauf-Budget erreicht", "42/100 Tokens verbraucht.")

        payload = mock_post.call_args.kwargs["json"]
        block = payload["attachments"][0]["blocks"][0]
        self.assertEqual(block["type"], "section")
        self.assertIn("Lauf-Budget erreicht", block["text"]["text"])
        self.assertIn("42/100 Tokens verbraucht.", block["text"]["text"])
        context_block = payload["attachments"][0]["blocks"][1]
        self.assertEqual(context_block["type"], "context")

    @patch("core.notifier.httpx.post")
    @patch("core.notifier.NOTIFY_WEBHOOK_URL", "https://hooks.example.com/x")
    def test_failure_keyword_colors_the_attachment_red(self, mock_post):
        notify_external("CI fehlgeschlagen", "Der Build ist rot.")

        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["attachments"][0]["color"], "#dc2626")

    @patch("core.notifier.httpx.post")
    @patch("core.notifier.NOTIFY_WEBHOOK_URL", "https://hooks.example.com/x")
    def test_neutral_event_gets_the_default_color(self, mock_post):
        notify_external("Release erstellt", "notizen_api-v0.1.0 wurde getaggt.")

        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["attachments"][0]["color"], "#2563eb")

    @patch("core.notifier.httpx.post")
    @patch("core.notifier.NOTIFY_WEBHOOK_URL", "https://hooks.example.com/x")
    def test_top_level_text_fallback_is_still_present(self, mock_post):
        """Slacks eigene Fallback-Konvention (Push-Vorschau, Clients ohne Block-Kit-Rendering)
        - und Rückwärtskompatibilität für Fremd-Webhooks, die nur "text" auswerten."""
        notify_external("Test-Event", "Test-Nachricht")

        payload = mock_post.call_args.kwargs["json"]
        self.assertIn("Test-Event", payload["text"])
        self.assertIn("Test-Nachricht", payload["text"])


if __name__ == "__main__":
    unittest.main()
