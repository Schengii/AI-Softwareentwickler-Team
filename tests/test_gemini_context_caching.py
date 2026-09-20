"""
tests/test_gemini_context_caching.py – Explizites Gemini-Context-Caching (P5-2, ROADMAP_TEMP.md)

Realer Fund 2026-09-20: core/llm_factory.py hat `cached_content_token_count` nur aus der
Gemini-Antwort GELESEN, aber nie ein Cache-Objekt ERZEUGT (`client.caches.create(...)` kam im
gesamten Modul nicht vor) - anders als der Anthropic-Pfad, der `cache_control: ephemeral` aktiv
setzt. Scan über alle 264 `agent_call`-Events in `workspace/*/.ai_team_runs/*_trace.jsonl`: 0%
Cache-Trefferquote, ausnahmslos (`cache_read_tokens` fehlte im Event komplett statt gemessen zu
werden). Diese Tests decken die neue Erzeugungsseite ab, mit besonderem Fokus darauf, dass eine
fehlschlagende Cache-Erstellung NIE den eigentlichen `generate_content`-Aufruf verhindert oder
verfälscht - das Feature ist reiner Best-Effort.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from core.llm_factory import (
    AgentMessage,
    GeminiClient,
    _gemini_cache_registry,
    _gemini_cache_unsupported_models,
    _gemini_cached_content_name,
    _gemini_clients_by_key,
    _gemini_config_with_cache,
    _gemini_exhausted_keys,
    genai_types,
)

LONG_SYSTEM_PROMPT = "Du bist ein hilfreicher Softwareentwickler-Agent. " * 300  # deutlich > Mindestlänge
SHORT_SYSTEM_PROMPT = "Kurzer Prompt."


def _fake_cache(name: str = "cachedContents/abc123") -> MagicMock:
    cache = MagicMock()
    cache.name = name  # NICHT MagicMock(name=...) - das setzt den Mock-eigenen Debug-Namen, nicht .name
    return cache


class TestGeminiCachedContentName(unittest.TestCase):
    def setUp(self):
        _gemini_clients_by_key.clear()
        _gemini_exhausted_keys.clear()
        _gemini_cache_registry.clear()
        _gemini_cache_unsupported_models.clear()

    tearDown = setUp

    @patch("core.llm_factory.GEMINI_API_KEYS", ["key_1"])
    def test_short_prompt_never_attempts_cache_creation(self):
        mock_client = MagicMock()
        _gemini_clients_by_key["key_1"] = mock_client

        result = _gemini_cached_content_name("gemini-3.8-flash", SHORT_SYSTEM_PROMPT)

        self.assertIsNone(result)
        mock_client.caches.create.assert_not_called()

    def test_none_prompt_returns_none(self):
        self.assertIsNone(_gemini_cached_content_name("gemini-3.8-flash", None))

    @patch("core.llm_factory.GEMINI_API_KEYS", ["key_1"])
    def test_long_prompt_creates_cache_and_returns_name(self):
        mock_client = MagicMock()
        mock_client.caches.create.return_value = _fake_cache("cachedContents/xyz")
        _gemini_clients_by_key["key_1"] = mock_client

        result = _gemini_cached_content_name("gemini-3.8-flash", LONG_SYSTEM_PROMPT)

        self.assertEqual(result, "cachedContents/xyz")
        mock_client.caches.create.assert_called_once()
        _, kwargs = mock_client.caches.create.call_args
        self.assertEqual(kwargs["model"], "gemini-3.8-flash")

    @patch("core.llm_factory.GEMINI_API_KEYS", ["key_1"])
    def test_second_call_with_identical_prompt_reuses_cache_without_new_api_call(self):
        mock_client = MagicMock()
        mock_client.caches.create.return_value = _fake_cache("cachedContents/reuse-me")
        _gemini_clients_by_key["key_1"] = mock_client

        first = _gemini_cached_content_name("gemini-3.8-flash", LONG_SYSTEM_PROMPT)
        second = _gemini_cached_content_name("gemini-3.8-flash", LONG_SYSTEM_PROMPT)

        self.assertEqual(first, "cachedContents/reuse-me")
        self.assertEqual(second, "cachedContents/reuse-me")
        # Der eigentliche Sinn des Caching: EIN Erstellungsaufruf reicht für beide Verwendungen.
        mock_client.caches.create.assert_called_once()

    @patch("core.llm_factory.GEMINI_API_KEYS", ["key_1"])
    def test_cache_creation_failure_returns_none_without_raising(self):
        """Kernanforderung: ein Modell/eine Free-Tier-Stufe ohne Cache-Unterstützung darf den
        Aufrufer NIE crashen lassen - nur den Fallback (kein Caching) auslösen."""
        mock_client = MagicMock()
        mock_client.caches.create.side_effect = RuntimeError("400 INVALID_ARGUMENT: caching not supported")
        _gemini_clients_by_key["key_1"] = mock_client

        result = _gemini_cached_content_name("gemini-3.1-flash-lite", LONG_SYSTEM_PROMPT)

        self.assertIsNone(result)

    @patch("core.llm_factory.GEMINI_API_KEYS", ["key_1"])
    def test_cache_creation_failure_is_not_retried_immediately_for_same_model(self):
        mock_client = MagicMock()
        mock_client.caches.create.side_effect = RuntimeError("caching not supported")
        _gemini_clients_by_key["key_1"] = mock_client

        _gemini_cached_content_name("gemini-3.1-flash-lite", LONG_SYSTEM_PROMPT)
        _gemini_cached_content_name("gemini-3.1-flash-lite", LONG_SYSTEM_PROMPT)

        # Zweiter Aufruf hätte ohne Cooldown erneut versucht - hier bleibt es bei EINEM Versuch.
        self.assertEqual(mock_client.caches.create.call_count, 1)

    def test_non_string_system_prompt_is_ignored_safely(self):
        """Defensive Typprüfung: kommt hier (z.B. über eine zurückgelesene SDK-Struktur statt
        eines rohen Strings) kein `str` an, darf das nicht mit einem TypeError crashen."""
        result = _gemini_cached_content_name("gemini-3.8-flash", object())  # type: ignore[arg-type]
        self.assertIsNone(result)


class TestGeminiConfigWithCache(unittest.TestCase):
    def setUp(self):
        _gemini_clients_by_key.clear()
        _gemini_exhausted_keys.clear()
        _gemini_cache_registry.clear()
        _gemini_cache_unsupported_models.clear()

    tearDown = setUp

    def test_returns_base_config_unchanged_when_no_cache_available(self):
        base = genai_types.GenerateContentConfig(system_instruction=SHORT_SYSTEM_PROMPT)
        result = _gemini_config_with_cache(base, "gemini-3.8-flash", SHORT_SYSTEM_PROMPT)
        self.assertIs(result, base)

    @patch("core.llm_factory.GEMINI_API_KEYS", ["key_1"])
    def test_sets_cached_content_and_clears_inline_system_instruction(self):
        mock_client = MagicMock()
        mock_client.caches.create.return_value = _fake_cache("cachedContents/config-test")
        _gemini_clients_by_key["key_1"] = mock_client

        base = genai_types.GenerateContentConfig(system_instruction=LONG_SYSTEM_PROMPT)
        result = _gemini_config_with_cache(base, "gemini-3.8-flash", LONG_SYSTEM_PROMPT)

        self.assertEqual(result.cached_content, "cachedContents/config-test")
        self.assertIsNone(result.system_instruction)


class TestGenerateWithToolsUsesCache(unittest.TestCase):
    """End-to-End: generate_with_tools() reicht ein bei der Cache-Erstellung erhaltenes
    cached_content tatsächlich an models.generate_content() weiter."""

    def setUp(self):
        _gemini_clients_by_key.clear()
        _gemini_exhausted_keys.clear()
        _gemini_cache_registry.clear()
        _gemini_cache_unsupported_models.clear()

    tearDown = setUp

    @patch("core.llm_factory.GEMINI_API_KEYS", ["key_1"])
    @patch("core.llm_factory._gemini_rate_limiter")
    def test_long_system_prompt_reaches_generate_content_with_cached_content(self, mock_limiter):
        mock_limiter.acquire = AsyncMock()

        captured_configs = []

        def fake_generate_content(model, contents, config):
            captured_configs.append(config)
            part = MagicMock()
            part.text = "ok"
            part.function_call = None
            candidate = MagicMock()
            candidate.content.parts = [part]
            resp = MagicMock()
            resp.candidates = [candidate]
            resp.usage_metadata = None
            return resp

        mock_client = MagicMock()
        mock_client.models.generate_content = fake_generate_content
        mock_client.caches.create.return_value = _fake_cache("cachedContents/e2e")
        _gemini_clients_by_key["key_1"] = mock_client

        client = GeminiClient(model_name="gemini-3.8-flash")
        res = asyncio.run(client.generate_with_tools(
            [AgentMessage(role="user", text="hello")], LONG_SYSTEM_PROMPT, [],
        ))

        self.assertEqual(res.text, "ok")
        self.assertEqual(len(captured_configs), 1)
        self.assertEqual(captured_configs[0].cached_content, "cachedContents/e2e")
        self.assertIsNone(captured_configs[0].system_instruction)

    @patch("core.llm_factory.GEMINI_API_KEYS", ["key_1"])
    @patch("core.llm_factory._gemini_rate_limiter")
    def test_cache_creation_failure_still_delivers_inline_system_instruction(self, mock_limiter):
        mock_limiter.acquire = AsyncMock()
        captured_configs = []

        def fake_generate_content(model, contents, config):
            captured_configs.append(config)
            part = MagicMock()
            part.text = "ok trotz Cache-Fehler"
            part.function_call = None
            candidate = MagicMock()
            candidate.content.parts = [part]
            resp = MagicMock()
            resp.candidates = [candidate]
            resp.usage_metadata = None
            return resp

        mock_client = MagicMock()
        mock_client.models.generate_content = fake_generate_content
        mock_client.caches.create.side_effect = RuntimeError("caching not supported for this model")
        _gemini_clients_by_key["key_1"] = mock_client

        client = GeminiClient(model_name="gemini-3.1-flash-lite")
        res = asyncio.run(client.generate_with_tools(
            [AgentMessage(role="user", text="hello")], LONG_SYSTEM_PROMPT, [],
        ))

        self.assertEqual(res.text, "ok trotz Cache-Fehler")
        self.assertEqual(len(captured_configs), 1)
        self.assertIsNone(captured_configs[0].cached_content)
        self.assertEqual(captured_configs[0].system_instruction, LONG_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
