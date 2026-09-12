"""
tests/test_gemini_key_pool.py – Validiert den Gemini API-Key-Pool und automatisches Failover auf Reserve-Keys.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from config import _collect_gemini_api_keys
from core.llm_factory import (
    AgentMessage,
    GeminiClient,
    _gemini_clients_by_key,
    _gemini_exhausted_keys,
    _get_gemini_client,
    _mark_gemini_key_exhausted,
)


class TestGeminiKeyPoolConfig(unittest.TestCase):
    def test_collect_single_key(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "key1"}):
            keys = _collect_gemini_api_keys()
            self.assertEqual(keys, ["key1"])

    def test_collect_comma_separated_keys(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "key1, key2 ,key3"}):
            keys = _collect_gemini_api_keys()
            self.assertEqual(keys, ["key1", "key2", "key3"])

    def test_collect_fallback_indexed_keys(self):
        with patch.dict("os.environ", {
            "GEMINI_API_KEY": "key1",
            "GEMINI_API_KEY_FALLBACK_1": "key2",
            "GEMINI_API_KEY_2": "key3",
        }):
            keys = _collect_gemini_api_keys()
            self.assertEqual(keys, ["key1", "key2", "key3"])


class TestGeminiKeyFailover(unittest.TestCase):
    def setUp(self):
        _gemini_clients_by_key.clear()
        _gemini_exhausted_keys.clear()

    def tearDown(self):
        _gemini_clients_by_key.clear()
        _gemini_exhausted_keys.clear()

    @patch("core.llm_factory.GEMINI_API_KEYS", ["key_primary", "key_backup"])
    def test_key_rotation_on_quota_exhaustion(self):
        # Initialer Key ist key_primary
        client1, key1 = _get_gemini_client()
        self.assertEqual(key1, "key_primary")

        # Markiere primary als erschöpft
        has_next = _mark_gemini_key_exhausted("key_primary", cooldown_seconds=3600.0)
        self.assertTrue(has_next)

        # Neuer aktiver Key ist key_backup
        client2, key2 = _get_gemini_client()
        self.assertEqual(key2, "key_backup")

        # Markiere auch backup als erschöpft
        has_next2 = _mark_gemini_key_exhausted("key_backup", cooldown_seconds=3600.0)
        self.assertFalse(has_next2)

    @patch("core.llm_factory.GEMINI_API_KEYS", ["key_1", "key_2"])
    @patch("core.llm_factory.asyncio.sleep", new_callable=AsyncMock)
    @patch("core.llm_factory._gemini_rate_limiter")
    def test_generate_with_tools_switches_to_second_gemini_key_on_429(
        self, mock_limiter, mock_sleep,
    ):
        mock_limiter.acquire = AsyncMock()
        used_keys: list[str] = []

        def fake_generate_content(model, contents, config):
            _, current_key = _get_gemini_client()
            used_keys.append(current_key)
            if current_key == "key_1":
                raise RuntimeError("429 RESOURCE_EXHAUSTED Quota exceeded for metric: free_tier_requests")
            # key_2 antwortet erfolgreich
            part = MagicMock()
            part.text = "Success with key 2"
            part.function_call = None
            candidate = MagicMock()
            candidate.content.parts = [part]
            resp = MagicMock()
            resp.candidates = [candidate]
            resp.usage_metadata = None
            return resp

        mock_c1 = MagicMock()
        mock_c1.models.generate_content = fake_generate_content
        mock_c2 = MagicMock()
        mock_c2.models.generate_content = fake_generate_content
        _gemini_clients_by_key["key_1"] = mock_c1
        _gemini_clients_by_key["key_2"] = mock_c2

        client = GeminiClient(model_name="gemini-3.8-flash")
        res = asyncio.run(client.generate_with_tools(
            [AgentMessage(role="user", text="hello")], None, [],
        ))

        self.assertEqual(res.text, "Success with key 2")
        self.assertEqual(used_keys, ["key_1", "key_2"])

    @patch("core.llm_factory.GEMINI_API_KEYS", ["single_key"])
    def test_model_specific_quota_exhaustion_preserves_other_models_on_same_key(self):
        # Initialer Key verfügbar
        _, key = _get_gemini_client(model="gemini-3.8-flash")
        self.assertEqual(key, "single_key")

        # Markiere single_key NUR für gemini-3.8-flash als erschöpft (Tageslimit 20 Requests)
        has_next = _mark_gemini_key_exhausted("single_key", cooldown_seconds=3600.0, model="gemini-3.8-flash")
        self.assertFalse(has_next)  # Keine weiteren Keys für dieses Modell

        # Für gemini-3.6-flash ist derselbe Key weiterhin voll verfügbar!
        _, key_36 = _get_gemini_client(model="gemini-3.6-flash")
        self.assertEqual(key_36, "single_key")

        # Für gemini-3.1-flash-lite ist er ebenfalls verfügbar!
        _, key_lite = _get_gemini_client(model="gemini-3.1-flash-lite")
        self.assertEqual(key_lite, "single_key")


if __name__ == "__main__":
    unittest.main()

