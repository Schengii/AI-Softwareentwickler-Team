"""
tests/test_provider_auth_error_handling.py – Regressionstest für ki_team_verbesserungsanalyse.md,
Stufe-0-#1: `_provider_available()` prüfte für Claude/Groq bisher NUR, ob ein API-Key überhaupt
GESETZT ist (`bool(ANTHROPIC_API_KEY)`), nie ob er tatsächlich FUNKTIONIERT. Ein falscher oder
widerrufener Key wurde dadurch bei jedem einzelnen Aufruf (jeder frisch instanziierte
ClaudeClient/GroqClient) erneut live gegen die echte API versucht, statt sich die erste
Ablehnung zu merken - ganz anders als OpenRouter/DeepSeek, die einen 401 bereits am
`status_code` erkennen und dauerhaft auf einen Fallback-Provider umschalten.

Prüft:
1. Ein Auth-Fehler (401/"invalid_api_key"/...) wird als solcher erkannt (is_authentication_error)
   und NICHT mit einem echten Rate-Limit verwechselt.
2. Nach einem erkannten Auth-Fehler markiert ClaudeClient/GroqClient das Modell in token_guard
   als (lange) erschöpft, statt es beim nächsten Aufruf erneut zu versuchen.
3. Ein bereits als auth-fehlerhaft markiertes Modell wird BEIM NÄCHSTEN Aufruf desselben Clients
   ohne erneuten Live-Versuch übersprungen (Pre-Check) und fällt sofort auf den Ausweich-Client.
"""

import unittest
from unittest.mock import AsyncMock, patch

from core.llm_factory import (
    AUTH_FAILURE_COOLDOWN_SECONDS,
    ClaudeClient,
    GroqClient,
    is_authentication_error,
)
from core.token_guard import token_guard

AUTH_ERROR = Exception(
    "Error code: 401 - {'error': {'type': 'authentication_error', "
    "'message': 'invalid x-api-key'}}"
)
RATE_LIMIT_ERROR = Exception("Error code: 429 - rate_limit_exceeded")


class TestIsAuthenticationError(unittest.TestCase):
    def test_401_marker_erkannt(self):
        self.assertTrue(is_authentication_error(AUTH_ERROR))

    def test_rate_limit_nicht_als_auth_fehler_erkannt(self):
        self.assertFalse(is_authentication_error(RATE_LIMIT_ERROR))

    def test_generischer_fehler_nicht_als_auth_fehler_erkannt(self):
        self.assertFalse(is_authentication_error(Exception("Connection reset by peer")))


class TestClaudeAuthErrorHandling(unittest.TestCase):
    def tearDown(self):
        token_guard._exhausted_models.pop("claude-sonnet-5", None)

    @patch("core.llm_factory.ANTHROPIC_API_KEY", "sk-ant-fake-invalid-key")
    def test_auth_fehler_markiert_modell_dauerhaft_erschoepft(self):
        client = ClaudeClient(model_name="claude-sonnet-5")
        client._client = AsyncMock()
        client._client.messages.create.side_effect = AUTH_ERROR

        import asyncio
        with patch.object(
            ClaudeClient, "_free_heavy_fallback_client",
        ) as mock_fallback:
            mock_fallback.return_value.generate_with_usage = AsyncMock(return_value="gerettet")
            asyncio.run(client.generate_with_usage("hallo"))

        self.assertTrue(token_guard.is_model_exhausted("claude-sonnet-5"))
        reason = token_guard.get_exhausted_reason("claude-sonnet-5")
        self.assertIn("Auth-Fehler", reason)

    @patch("core.llm_factory.ANTHROPIC_API_KEY", "sk-ant-fake-invalid-key")
    def test_zweiter_aufruf_versucht_nicht_erneut_live_call(self):
        """Nach dem ersten (fehlgeschlagenen) Aufruf darf ein zweiter, frischer ClaudeClient
        mit demselben Modellnamen NICHT erneut `messages.create` aufrufen - der Pre-Check muss
        direkt zum Ausweich-Client springen."""
        token_guard.mark_model_exhausted(
            "claude-sonnet-5", "Claude Auth-Fehler (ungültiger/abgelehnter API-Key): 401",
            cooldown_seconds=AUTH_FAILURE_COOLDOWN_SECONDS,
        )
        client = ClaudeClient(model_name="claude-sonnet-5")
        client._client = AsyncMock()

        import asyncio
        with patch.object(ClaudeClient, "_free_heavy_fallback_client") as mock_fallback:
            mock_fallback.return_value.generate_with_usage = AsyncMock(return_value="gerettet")
            result = asyncio.run(client.generate_with_usage("hallo"))

        client._client.messages.create.assert_not_called()
        self.assertEqual(result, "gerettet")


class TestGroqAuthErrorHandling(unittest.TestCase):
    def tearDown(self):
        token_guard._exhausted_models.pop("groq:openai/gpt-oss-120b", None)

    @patch("core.llm_factory._groq_client")
    def test_auth_fehler_markiert_modell_dauerhaft_erschoepft(self, mock_groq_client):
        mock_groq_client.chat.completions.create.side_effect = AUTH_ERROR
        client = GroqClient(model_name="openai/gpt-oss-120b")

        import asyncio
        with patch("core.llm_factory._cross_provider_failover_with_usage", new=AsyncMock(return_value="gerettet")):
            asyncio.run(client.generate_with_usage("hallo"))

        self.assertTrue(token_guard.is_model_exhausted("groq:openai/gpt-oss-120b"))
        reason = token_guard.get_exhausted_reason("groq:openai/gpt-oss-120b")
        self.assertIn("Auth-Fehler", reason)

    @patch("core.llm_factory._groq_client")
    def test_zweiter_aufruf_versucht_nicht_erneut_live_call(self, mock_groq_client):
        token_guard.mark_model_exhausted(
            "groq:openai/gpt-oss-120b", "Groq Auth-Fehler (ungültiger/abgelehnter API-Key): 401",
            cooldown_seconds=AUTH_FAILURE_COOLDOWN_SECONDS,
        )
        client = GroqClient(model_name="openai/gpt-oss-120b")

        import asyncio
        with patch("core.llm_factory._cross_provider_failover_with_usage", new=AsyncMock(return_value="gerettet")):
            result = asyncio.run(client.generate_with_usage("hallo"))

        mock_groq_client.chat.completions.create.assert_not_called()
        self.assertEqual(result, "gerettet")


if __name__ == "__main__":
    unittest.main()
