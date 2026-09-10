"""
tests/test_capability_floor.py – Mindest-Modellstufe für kritische Rollen

Realer Fund (logipulse-/vaultguard-Läufe): Bei erschöpftem Groq-Tageslimit liefen architect,
security und backend über die Fallback-Ketten still auf gemini-flash-lite weiter. Diese Tests
sichern ab, dass kritische Rollen nie unter ihre Mindeststufe fallen, ein fehlendes starkes
Modell als Infrastruktur-Erschöpfung gemeldet wird und Abstufungen sichtbar bleiben.
"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from core.llm_factory import AgentMessage, GeminiClient, _resolve_gemini_candidates
from core.model_capability import (
    TIER_HEAVY,
    TIER_LITE,
    TIER_STANDARD,
    CapabilityFloorError,
    capability_floor,
    current_capability_floor,
    describe_degraded_results,
    min_tier_for_agent,
    model_capability_tier,
    parse_tier,
    record_downgrade,
)
from core.provider_exhaustion import FAILURE_CLASS_PROVIDER_EXHAUSTED, classify_failure
from core.token_guard import token_guard

_QUOTA_ERROR = "429 RESOURCE_EXHAUSTED. You exceeded your current quota (GenerateRequestsPerDay)"
_TOUCHED_MODELS = ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.1-flash-lite")


class TestModelTiers(unittest.TestCase):
    def test_tier_classification(self):
        for model in ("gemini-3.1-flash-lite", "claude-haiku-4-5-20251001", "huggingface:auto"):
            self.assertEqual(model_capability_tier(model), TIER_LITE, model)
        for model in ("gemini-3.8-flash", "deepseek:deepseek-chat", "openrouter:openrouter/auto"):
            self.assertEqual(model_capability_tier(model), TIER_STANDARD, model)
        for model in ("claude-opus-5", "claude-sonnet-5", "gemini-pro-latest", "groq:openai/gpt-oss-120b"):
            self.assertEqual(model_capability_tier(model), TIER_HEAVY, model)

    def test_parse_tier(self):
        self.assertEqual(parse_tier("lite"), TIER_LITE)
        self.assertEqual(parse_tier(" Heavy "), TIER_HEAVY)
        self.assertEqual(parse_tier("1"), TIER_STANDARD)
        with self.assertLogs("core.model_capability", "WARNING"):
            self.assertEqual(parse_tier("turbo"), TIER_STANDARD)


class TestFloorInFallbackChains(unittest.TestCase):
    def test_floor_removes_lite_models_from_gemini_chain(self):
        with capability_floor(TIER_STANDARD, owner="architect"):
            candidates = _resolve_gemini_candidates("gemini-3.8-flash", allow_fallback=True)
        self.assertTrue(candidates)
        self.assertFalse([m for m in candidates if model_capability_tier(m) == TIER_LITE])
        self.assertEqual(current_capability_floor(), TIER_LITE)

    def test_without_floor_lite_stays_last_resort(self):
        self.assertEqual(_resolve_gemini_candidates("gemini-3.8-flash", allow_fallback=True)[-1], "gemini-3.1-flash-lite")

    def test_no_capable_model_raises_infrastructure_error(self):
        with capability_floor(TIER_STANDARD, owner="security"):
            with self.assertRaises(CapabilityFloorError) as ctx:
                _resolve_gemini_candidates("gemini-3.1-flash-lite", allow_fallback=False)
        self.assertIn("security", str(ctx.exception))
        self.assertEqual(classify_failure(str(ctx.exception)), FAILURE_CLASS_PROVIDER_EXHAUSTED)


class TestGeminiChainRespectsFloor(unittest.TestCase):
    def setUp(self):
        for model in _TOUCHED_MODELS:
            token_guard._exhausted_models.pop(model, None)

    tearDown = setUp

    @patch("core.llm_factory._provider_available", lambda model: model.startswith("gemini"))
    @patch("core.llm_factory.asyncio.sleep", new_callable=AsyncMock)
    @patch("core.llm_factory._gemini_rate_limiter")
    @patch("core.llm_factory._gemini_client")
    def test_quota_exhaustion_never_reaches_flash_lite_for_critical_role(self, mock_client, mock_limiter, _sleep):
        mock_limiter.acquire = AsyncMock()
        called: list[str] = []

        def fake_generate_content(model, contents, config):
            called.append(model)
            raise RuntimeError(_QUOTA_ERROR)

        mock_client.models.generate_content = fake_generate_content

        async def run():
            with capability_floor(TIER_STANDARD, owner="backend"):
                return await GeminiClient(model_name="gemini-3.8-flash").generate_with_tools(
                    [AgentMessage(role="user", text="hi")], None, [],
                )

        with self.assertRaises(RuntimeError):
            asyncio.run(run())
        self.assertIn("gemini-3.8-flash", called)
        self.assertNotIn("gemini-3.1-flash-lite", called)


class TestAgentFloorAndVisibility(unittest.TestCase):
    @patch("config.HEAVY_ROLE_MIN_TIER", "standard")
    def test_min_tier_for_agent(self):
        self.assertEqual(min_tier_for_agent("architect", "groq:openai/gpt-oss-120b"), TIER_STANDARD)
        self.assertEqual(min_tier_for_agent("copywriter", "gemini-3.8-flash"), TIER_LITE)
        # Bewusst auf lite konfigurierte kritische Rolle bleibt lauffähig.
        self.assertEqual(min_tier_for_agent("architect", "gemini-3.1-flash-lite"), TIER_LITE)

    @patch("config.HEAVY_ROLE_MIN_TIER", "lite")
    def test_floor_can_be_disabled(self):
        self.assertEqual(min_tier_for_agent("security", "claude-opus-5"), TIER_LITE)

    @patch("config.get_model_for_agent", return_value="groq:openai/gpt-oss-120b")
    def test_degraded_critical_results_are_reported(self, _model):
        results = [
            SimpleNamespace(agent_id="architect", model_used="deepseek:deepseek-chat", success=True),
            SimpleNamespace(agent_id="architect", model_used="deepseek:deepseek-chat", success=True),
            SimpleNamespace(agent_id="copywriter", model_used="gemini-3.1-flash-lite", success=True),
            SimpleNamespace(agent_id="security", model_used="gemini-3.8-flash", success=False),
            SimpleNamespace(agent_id="backend", model_used="claude-sonnet-5", success=True),
        ]
        lines = describe_degraded_results(results)
        self.assertEqual(len(lines), 1)
        self.assertIn("architect", lines[0])

    def test_tier_loss_is_logged(self):
        with self.assertLogs("core.model_capability", "WARNING") as logs:
            with capability_floor(TIER_STANDARD, owner="refactoring"):
                record_downgrade("groq:openai/gpt-oss-120b", "gemini-3.8-flash", "Test")
        self.assertIn("refactoring", logs.output[0])


if __name__ == "__main__":
    unittest.main()
