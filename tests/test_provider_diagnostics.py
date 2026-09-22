"""
tests/test_provider_diagnostics.py – Provider-Cooldowns & nachvollziehbare Fallback-Fehler

Realer Fund (Smoke-Lauf 2026-09-10, logs/runs/20260910_105833_smoke_jwt_router.jsonl): alle 11
Agenten-Aufrufe scheiterten. Die Fehlermeldung nannte nur den letzten Gemini-429 - dass DeepSeek
("Insufficient Balance") und OpenRouter ("requires more credits") kein Guthaben hatten und Groq sein
Tageskontingent ("tokens per day ... try again in 2h42m9.504s") aufgebraucht hatte, war nur durch
manuelle Einzelaufrufe erkennbar. Zudem bekamen diese drei Fälle nur 60 s Cooldown.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from core.llm_factory import (
    BILLING_EXHAUSTION_COOLDOWN_SECONDS,
    DAILY_QUOTA_COOLDOWN_SECONDS,
    AgentMessage,
    DeepSeekClient,
    GeminiClient,
    GroqClient,
    _exhaustion_cooldown_seconds,
    _retry_after_seconds,
)
from core.token_guard import token_guard

_GROQ_TPD_ERROR = (
    "Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b` in "
    "organization `org_x` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 198334, "
    "Requested 24188. Please try again in 2h42m9.504s.', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}"
)
_GEMINI_DAILY_ERROR = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota, please "
    "check your plan and billing details. Please retry in 56.830125164s.', 'details': [{'@type': "
    "'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaId': "
    "'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}]}]}}"
)


class TestCooldownClassification(unittest.TestCase):
    def test_retry_after_parsing(self):
        self.assertAlmostEqual(_retry_after_seconds("Please try again in 2h42m9.504s."), 9729.504)
        self.assertAlmostEqual(_retry_after_seconds("Please retry in 56.830125164s."), 56.830125164)
        self.assertAlmostEqual(_retry_after_seconds("try again in 850ms"), 0.85)
        self.assertIsNone(_retry_after_seconds("429 Too Many Requests"))

    def test_missing_balance_gets_long_billing_cooldown(self):
        self.assertEqual(_exhaustion_cooldown_seconds("Insufficient Balance"), BILLING_EXHAUSTION_COOLDOWN_SECONDS)
        self.assertEqual(
            _exhaustion_cooldown_seconds("This request requires more credits, or fewer max_tokens."),
            BILLING_EXHAUSTION_COOLDOWN_SECONDS,
        )

    def test_groq_daily_quota_uses_exact_provider_reset_time(self):
        self.assertAlmostEqual(_exhaustion_cooldown_seconds(_GROQ_TPD_ERROR), 9729.504)

    def test_gemini_daily_quota_ignores_short_minute_retry_hint(self):
        self.assertEqual(_exhaustion_cooldown_seconds(_GEMINI_DAILY_ERROR), DAILY_QUOTA_COOLDOWN_SECONDS)

    def test_gemini_billing_hint_text_is_not_mistaken_for_missing_balance(self):
        # "check your plan and billing details" steht in JEDEM Gemini-429.
        self.assertNotEqual(_exhaustion_cooldown_seconds(_GEMINI_DAILY_ERROR), BILLING_EXHAUSTION_COOLDOWN_SECONDS)

    def test_minute_limit_uses_provider_hint_and_unknown_stays_default(self):
        self.assertAlmostEqual(_exhaustion_cooldown_seconds("429 quota exceeded, retry in 44s"), 44.0)
        self.assertIsNone(_exhaustion_cooldown_seconds("429 Too Many Requests"))


class _CleanGuard:
    MODELS = (
        "groq:openai/gpt-oss-120b", "deepseek:deepseek-chat", "openrouter:openrouter/auto",
        "gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.1-flash-lite", "claude-sonnet-5",
    )

    def setUp(self):
        for model in self.MODELS:
            token_guard._exhausted_models.pop(model, None)

    def tearDown(self):
        self.setUp()


class TestProvidersApplyCooldowns(_CleanGuard, unittest.TestCase):
    @patch("core.llm_factory._groq_client")
    def test_groq_daily_quota_marks_model_until_reset(self, mock_groq):
        mock_groq.chat.completions.create.side_effect = RuntimeError(_GROQ_TPD_ERROR)
        with self.assertRaises(RuntimeError):
            asyncio.run(GroqClient().generate_with_tools(
                [AgentMessage(role="user", text="hi")], None, [], _allow_self_fallback=False,
            ))
        info = token_guard._exhausted_models["groq:openai/gpt-oss-120b"]
        self.assertAlmostEqual(info.cooldown_seconds, 9729.504)
        self.assertIn("tokens per day", info.reason)

    @patch("core.llm_factory.DEEPSEEK_API_KEY", "test-key")
    def test_deepseek_missing_balance_marks_billing_cooldown(self):
        response = MagicMock(status_code=402)
        response.json.return_value = {"error": {"message": "Insufficient Balance"}}
        http_client = MagicMock()
        http_client.post = AsyncMock(return_value=response)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=http_client)
        context.__aexit__ = AsyncMock(return_value=False)

        with patch("core.llm_providers.deepseek.httpx.AsyncClient", return_value=context), self.assertRaises(RuntimeError):
            asyncio.run(DeepSeekClient().generate_with_usage("hi", None, _allow_self_fallback=False))

        info = token_guard._exhausted_models["deepseek:deepseek-chat"]
        self.assertEqual(info.cooldown_seconds, BILLING_EXHAUSTION_COOLDOWN_SECONDS)


class TestChainFailureReport(_CleanGuard, unittest.TestCase):
    @patch("core.llm_factory.ANTHROPIC_API_KEY", "")
    @patch("core.llm_factory.OPENROUTER_API_KEY", "")
    @patch("core.llm_factory.DEEPSEEK_API_KEY", "test-key")
    @patch("core.llm_factory.GROQ_API_KEY", "test-key")
    @patch("core.llm_factory.GroqClient.generate_with_tools", new_callable=AsyncMock)
    @patch("asyncio.sleep", new_callable=AsyncMock)
    @patch("core.llm_factory._gemini_rate_limiter")
    @patch("core.llm_factory._gemini_client")
    def test_final_error_explains_every_candidate(self, mock_gemini, mock_limiter, _sleep, mock_groq_tools):
        mock_limiter.acquire = AsyncMock()
        mock_gemini.models.generate_content.side_effect = RuntimeError(_GEMINI_DAILY_ERROR)
        mock_groq_tools.side_effect = RuntimeError("Groq-Tageskontingent erschöpft")
        token_guard.mark_model_exhausted("deepseek:deepseek-chat", "DeepSeek: Insufficient Balance", cooldown_seconds=999)

        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(GeminiClient(model_name="gemini-3.8-flash").generate_with_tools(
                [AgentMessage(role="user", text="hi")], None, [],
            ))

        message = str(ctx.exception)
        self.assertTrue(message.startswith("Gemini Function-Calling Fehler nach allen Fallback-Modellen (gemini-3.8-flash)"))
        self.assertIn("RESOURCE_EXHAUSTED", message)
        self.assertIn("| Kette:", message)
        self.assertIn("claude-sonnet-5: übersprungen (kein API-Key)", message)
        self.assertIn("deepseek:deepseek-chat: übersprungen (DeepSeek: Insufficient Balance)", message)
        self.assertIn("openrouter:openrouter/auto: übersprungen (kein API-Key)", message)
        self.assertIn("groq:openai/gpt-oss-120b: Groq-Tageskontingent erschöpft", message)
        self.assertIn("gemini-3.8-flash: 429 RESOURCE_EXHAUSTED", message)


if __name__ == "__main__":
    unittest.main()
