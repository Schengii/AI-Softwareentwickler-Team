"""
tests/test_claude_billing_exhaustion.py – Regressionstest für die pulseflow_gateway-Retrospektive
(20260911_095217): das monatliche Anthropic-Kontingent wurde erschöpft ("Error code: 400 - API
usage limits reached"), weil MODEL_FALLBACKS Claude als ERSTEN Fallback für beide Gemini-Flash-
Stufen listete UND ClaudeClient diesen spezifischen Fehler (weder Rate-Limit noch Auth-Fehler)
gar nicht erkannte - jeder Folgeagent im selben Lauf zerschellte dadurch am selben harten Fehler
erneut, statt sofort auf einen anderen Provider umzuschwenken.

Prüft:
1. is_billing_exhaustion_error() erkennt Anthropics "API usage limits reached" / "credit balance
   too low", unterscheidet das aber von einem echten Rate-Limit oder einem generischen Fehler.
2. Ein erkannter Nutzungslimit-Fehler markiert das konkrete Claude-Modell in token_guard als
   erschöpft UND setzt den modul-globalen Schalter, der ALLE Claude-Modellvarianten für den Rest
   des Prozesses als nicht verfügbar meldet (_provider_available()).
3. MODEL_FALLBACKS listet Claude für die Gemini-Flash-Stufen nicht mehr als ersten Fallback,
   solange DeepSeek/OpenRouter/Groq konfiguriert sind.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import core.llm_factory as llm_factory
from core.llm_factory import (
    MODEL_FALLBACKS,
    ClaudeClient,
    _provider_available,
    is_billing_exhaustion_error,
)
from core.token_guard import token_guard

BILLING_ERROR = Exception(
    "Error code: 400 - {'error': {'type': 'invalid_request_error', "
    "'message': 'API usage limits reached for this month'}}"
)
LOW_CREDIT_ERROR = Exception("Error code: 400 - credit balance too low to complete this request")
RATE_LIMIT_ERROR = Exception("Error code: 429 - rate_limit_exceeded")


class TestIsBillingExhaustionError(unittest.TestCase):
    def test_usage_limit_marker_erkannt(self):
        self.assertTrue(is_billing_exhaustion_error(BILLING_ERROR))

    def test_credit_balance_marker_erkannt(self):
        self.assertTrue(is_billing_exhaustion_error(LOW_CREDIT_ERROR))

    def test_rate_limit_nicht_als_kontingent_fehler_erkannt(self):
        self.assertFalse(is_billing_exhaustion_error(RATE_LIMIT_ERROR))

    def test_generischer_fehler_nicht_als_kontingent_fehler_erkannt(self):
        self.assertFalse(is_billing_exhaustion_error(Exception("Connection reset by peer")))


class TestClaudeBillingExhaustionHandling(unittest.TestCase):
    def tearDown(self):
        token_guard._exhausted_models.pop("claude-sonnet-5", None)
        llm_factory._claude_billing_exhausted_reason = None

    @patch("core.llm_factory.ANTHROPIC_API_KEY", "sk-ant-fake-key")
    def test_kontingent_fehler_markiert_modell_und_gesamten_provider_erschoepft(self):
        client = ClaudeClient(model_name="claude-sonnet-5")
        client._client = AsyncMock()
        client._client.messages.create.side_effect = BILLING_ERROR

        with patch.object(ClaudeClient, "_free_heavy_fallback_client") as mock_fallback:
            mock_fallback.return_value.generate_with_usage = AsyncMock(return_value="gerettet")
            asyncio.run(client.generate_with_usage("hallo"))

        self.assertTrue(token_guard.is_model_exhausted("claude-sonnet-5"))
        self.assertIn("Nutzungslimit", token_guard.get_exhausted_reason("claude-sonnet-5"))
        # Der Schalter gilt providerweit - auch ein GANZ ANDERES Claude-Modell (z.B. Opus, das
        # in diesem Aufruf nie benutzt wurde) muss jetzt als nicht verfügbar gelten.
        self.assertFalse(_provider_available("claude-opus-5"))

    def test_provider_available_meldet_claude_nach_markierung_ueberall_als_nicht_verfuegbar(self):
        llm_factory.mark_claude_billing_exhausted("API usage limits reached")
        try:
            self.assertFalse(_provider_available("claude-sonnet-5"))
            self.assertFalse(_provider_available("claude-haiku-4-5-20251001"))
        finally:
            llm_factory._claude_billing_exhausted_reason = None


class TestModelFallbacksDeprioritizeClaude(unittest.TestCase):
    def test_flash_stufen_haben_claude_nicht_mehr_als_ersten_fallback(self):
        for gemini_model in ("gemini-3.8-flash", "gemini-3.6-flash"):
            kette = MODEL_FALLBACKS[gemini_model]
            self.assertNotIn(
                "claude", kette[0].lower(),
                f"{gemini_model}: erster Fallback ist noch Claude ({kette[0]})",
            )
            # Claude bleibt als LETZTE Ausweichstufe erhalten, damit die Kette nicht ins Leere
            # läuft, falls alle Drittanbieter gleichzeitig erschöpft sind.
            self.assertTrue(any("claude" in m.lower() for m in kette))


if __name__ == "__main__":
    unittest.main()
