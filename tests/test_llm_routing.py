"""
tests/test_llm_routing.py – Regressionstest für die Provider-Fallback-Weiche

Realer Fund aus einem echten End-to-End-Lauf: Sobald ein Nicht-Gemini-Modellname
(z.B. "claude-sonnet-5") als Fallback-Ziel in MODEL_FALLBACKS auftaucht, wurde er
in der alten Implementierung ohne Provider-Erkennung direkt als `model=`-Parameter
an die Gemini-API durchgereicht -> 400/404-Fehler, bevor die Kette überhaupt beim
eigentlich vorgesehenen Claude-Fallback ankam. Dieser Test stellt sicher, dass
NIEMALS ein Nicht-Gemini-Modellname an den echten Gemini-Client geht.
"""

import unittest
from unittest.mock import AsyncMock, patch

from core.llm_factory import GeminiClient
from core.token_guard import token_guard


class _FakeGenAIResponse:
    def __init__(self, text: str):
        self.text = text


class TestLLMRouting(unittest.TestCase):
    def tearDown(self):
        # Global geteilten TokenGuard-Zustand nicht in andere Tests durchsickern lassen.
        token_guard._exhausted_models.pop("gemini-3.6-flash", None)

    @patch("core.llm_factory._gemini_client")
    def test_gemini_fallback_chain_never_sends_claude_model_name_to_gemini_api(self, mock_gemini_client):
        """
        Simuliert: primäres Modell (gemini-3.6-flash) ist erschöpft, die Fallback-Kette
        enthält 'claude-sonnet-5'. Ohne ANTHROPIC_API_KEY fällt Claude intern auf Gemini
        zurück – aber die Gemini-API selbst darf 'claude-sonnet-5' NIE als model= sehen.
        """
        token_guard.mark_model_exhausted("gemini-3.6-flash", "Test: simulierte Quota-Erschöpfung")

        called_models: list[str] = []

        def fake_generate_content(model, contents, config):
            called_models.append(model)
            if model == "claude-sonnet-5":
                raise AssertionError("Claude-Modellname wurde faelschlich an die Gemini-API gesendet!")
            return _FakeGenAIResponse(text="ok")

        mock_gemini_client.models.generate_content = fake_generate_content

        client = GeminiClient(model_name="gemini-3.6-flash")

        async def run():
            return await client.generate_with_usage("Sag nur 'ok'.", None)

        import asyncio
        result = asyncio.run(run())

        self.assertEqual(result.text, "ok")
        # Da gemini-3.6-flash als erschöpft markiert ist, muss die Kette auf die naechste
        # gueltige GEMINI-Stufe (flash-lite) ausweichen - 'claude-sonnet-5' darf in den
        # tatsaechlich an die Gemini-API gestellten Aufrufen nicht auftauchen.
        self.assertNotIn("claude-sonnet-5", called_models)
        self.assertTrue(all(m.startswith("gemini") for m in called_models), called_models)


if __name__ == "__main__":
    unittest.main()
