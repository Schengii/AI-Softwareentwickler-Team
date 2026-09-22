"""
tests/test_cross_provider_quota_failover.py – Provider-unabhängiges Failover bei 429-Quota

Realer Fund (logipulse-Lauf 2026-09-10, logs/runs/20260910_084833_logipulse.jsonl): HEAVY-Rollen
forderten Groq an, liefen aber auf `gemini-3.1-flash-lite`, bis dessen Free-Tier-Tageskontingent
den Lauf beendete - obwohl andere Provider konfiguriert waren. Diese Tests sichern ab, dass eine
echte Quota-Erschöpfung sofort zu einem unabhängigen Provider wechselt und flash-lite nur noch
letzte Rettung ist.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from core.llm_factory import (
    AgentMessage,
    DeepSeekClient,
    GeminiClient,
    GroqClient,
    LLMResponse,
    _is_quota_exhaustion,
    _prefer_independent_providers,
    _resolve_gemini_candidates,
)
from core.token_guard import token_guard

_GEMINI_DAILY_QUOTA_ERROR = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota', "
    "'details': [{'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': "
    "[{'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}]}]}}"
)
_TOUCHED_MODELS = (
    "gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.1-flash-lite", "groq:openai/gpt-oss-120b",
    "deepseek:deepseek-chat", "openrouter:openrouter/auto", "claude-sonnet-5",
)


def _response(model_name: str) -> LLMResponse:
    return LLMResponse(text="ok", model_name=model_name, prompt_tokens=1, completion_tokens=1, total_tokens=2)


class _CleanTokenGuardMixin:
    def setUp(self):
        for model in _TOUCHED_MODELS:
            token_guard._exhausted_models.pop(model, None)

    def tearDown(self):
        for model in _TOUCHED_MODELS:
            token_guard._exhausted_models.pop(model, None)


class TestFailoverHelpers(unittest.TestCase):
    def test_detects_real_quota_exhaustion(self):
        self.assertTrue(_is_quota_exhaustion(_GEMINI_DAILY_QUOTA_ERROR))
        self.assertTrue(_is_quota_exhaustion("Rate limit reached ... tokens per day (TPD): Limit 200000"))
        self.assertFalse(_is_quota_exhaustion("503 UNAVAILABLE: high demand"))

    def test_independent_providers_move_ahead_of_same_provider_stages(self):
        pending = ["gemini-3.6-flash", "groq:openai/gpt-oss-120b", "gemini-3.1-flash-lite", "deepseek:deepseek-chat"]
        self.assertEqual(
            _prefer_independent_providers(pending, failed_provider="gemini"),
            ["groq:openai/gpt-oss-120b", "deepseek:deepseek-chat", "gemini-3.6-flash", "gemini-3.1-flash-lite"],
        )

    def test_flash_lite_is_last_resort_for_non_lite_requests(self):
        candidates = _resolve_gemini_candidates("gemini-3.8-flash", allow_fallback=True)
        self.assertEqual(candidates[0], "gemini-3.8-flash")
        self.assertEqual(candidates[-1], "gemini-3.1-flash-lite")
        self.assertLess(candidates.index("groq:openai/gpt-oss-120b"), candidates.index("gemini-3.1-flash-lite"))

    def test_lite_request_and_pinned_calls_keep_their_order(self):
        self.assertEqual(_resolve_gemini_candidates("gemini-3.1-flash-lite", allow_fallback=True)[0], "gemini-3.1-flash-lite")
        self.assertEqual(_resolve_gemini_candidates("gemini-3.8-flash", allow_fallback=False), ["gemini-3.8-flash"])


class TestGeminiQuotaSwitchesProvider(_CleanTokenGuardMixin, unittest.TestCase):
    @patch("core.llm_factory.GEMINI_API_KEYS", ["test-key"])
    @patch("core.llm_factory.ANTHROPIC_API_KEY", "")
    @patch("core.llm_factory.DEEPSEEK_API_KEY", "")
    @patch("core.llm_factory.OPENROUTER_API_KEY", "")
    @patch("core.llm_factory.GROQ_API_KEY", "test-key")
    @patch("core.llm_factory.GroqClient.generate_with_tools", new_callable=AsyncMock)
    @patch("asyncio.sleep", new_callable=AsyncMock)
    @patch("core.llm_factory._gemini_rate_limiter")
    @patch("core.llm_factory._gemini_client")
    def test_quota_on_gemini_switches_to_groq_without_burning_other_gemini_stages(
        self, mock_gemini_client, mock_limiter, mock_sleep, mock_groq_tools, mock_gemini_keys=None,
    ):
        mock_limiter.acquire = AsyncMock()
        called_models: list[str] = []

        def fake_generate_content(model, contents, config):
            called_models.append(model)
            raise RuntimeError(_GEMINI_DAILY_QUOTA_ERROR)

        mock_gemini_client.models.generate_content = fake_generate_content
        mock_groq_tools.return_value = _response("groq:openai/gpt-oss-120b")

        result = asyncio.run(GeminiClient(model_name="gemini-3.8-flash").generate_with_tools(
            [AgentMessage(role="user", text="hi")], None, [],
        ))

        self.assertEqual(result.model_name, "groq:openai/gpt-oss-120b")
        # Genau EIN Gemini-Versuch: kein Retry bei echter Quota, keine weitere Gemini-Stufe vor Groq.
        self.assertEqual(called_models, ["gemini-3.8-flash"])
        mock_sleep.assert_not_awaited()
        self.assertTrue(token_guard.is_model_exhausted("gemini-3.8-flash"))


class TestProviderSelfFallbackPrefersIndependentProvider(_CleanTokenGuardMixin, unittest.TestCase):
    @patch("core.llm_factory.DEEPSEEK_API_KEY", "test-key")
    @patch("core.llm_factory.OPENROUTER_API_KEY", "")
    @patch("core.llm_factory.DeepSeekClient.generate_with_tools", new_callable=AsyncMock)
    @patch("core.llm_factory._gemini_client")
    @patch("core.llm_factory._groq_client")
    def test_groq_quota_for_heavy_role_goes_to_deepseek_not_gemini(
        self, mock_groq_client, mock_gemini_client, mock_deepseek_tools,
    ):
        mock_groq_client.chat.completions.create.side_effect = RuntimeError(
            "Error code: 429 - rate_limit_exceeded: tokens per day (TPD): Limit 200000, Used 199342"
        )
        mock_gemini_client.models.generate_content = MagicMock(
            side_effect=AssertionError("Gemini darf nicht vor DeepSeek versucht werden"),
        )
        mock_deepseek_tools.return_value = _response("deepseek:deepseek-chat")

        result = asyncio.run(GroqClient(model_name="groq:openai/gpt-oss-120b").generate_with_tools(
            [AgentMessage(role="user", text="hi")], None, [],
        ))

        self.assertEqual(result.model_name, "deepseek:deepseek-chat")
        self.assertEqual(mock_deepseek_tools.await_args.kwargs.get("_allow_self_fallback"), False)
        mock_gemini_client.models.generate_content.assert_not_called()
        self.assertTrue(token_guard.is_model_exhausted("groq:openai/gpt-oss-120b"))

    @patch("core.llm_factory.GROQ_API_KEY", "")
    @patch("core.llm_factory.DEEPSEEK_API_KEY", "")
    @patch("core.llm_factory.OPENROUTER_API_KEY", "")
    @patch("core.llm_factory.GeminiClient.generate_with_usage", new_callable=AsyncMock)
    def test_without_independent_provider_falls_back_to_gemini_chain(self, mock_gemini_usage):
        mock_gemini_usage.return_value = _response("gemini-3.8-flash")

        result = asyncio.run(DeepSeekClient().generate_with_usage("hi", None))

        self.assertEqual(result.model_name, "gemini-3.8-flash")
        mock_gemini_usage.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
