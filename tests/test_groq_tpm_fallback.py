"""
tests/test_groq_tpm_fallback.py – Regressionstest für die Innerhalb-Groq-Ausweichkette.

Realer Fund (logs/runs/20260911_211719_chronos_queue.jsonl): Groqs Free-Tier für
`openai/gpt-oss-120b` erlaubt nur 8.000 Tokens PRO MINUTE (TPM). Ein großer System-Prompt +
Werkzeugkatalog überschritt dieses Limit bereits bei einem einzelnen Aufruf und scheiterte mit
HTTP 413 "Request too large" - ohne Ausweichkette lief der Fehler direkt in einen
Provider-Wechsel bzw. (bei bereits gepinntem Provider) in einen kompletten Fehlschlag, obwohl
`llama-3.3-70b-versatile` auf demselben, bereits konfigurierten Groq-Key ein 4-8x
großzügigeres TPM-Limit hat und den Aufruf ohne jeden Provider-Wechsel gerettet hätte.
"""

import asyncio
import unittest
from unittest.mock import MagicMock, patch

from core.llm_factory import GroqClient
from core.token_guard import token_guard

REQUEST_TOO_LARGE_ERROR = Exception(
    "Error code: 413 - {'error': {'message': 'Request too large for model "
    "`openai/gpt-oss-120b` in organization `org_x` service tier `on_demand` on tokens per "
    "minute (TPM): Limit 8000, Requested 8685, please reduce your message size and try "
    "again.', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}"
)


class TestGroqTpmFallback(unittest.TestCase):
    def tearDown(self):
        for model in ("groq:openai/gpt-oss-120b", "groq:llama-3.3-70b-versatile", "groq:llama-3.1-8b-instant"):
            token_guard._exhausted_models.pop(model, None)

    @patch("core.llm_factory._groq_client")
    def test_413_on_heavy_model_retries_with_fallback_model_not_cross_provider(self, mock_groq_client):
        """Ein 413/TPM-Fehler auf `openai/gpt-oss-120b` muss ZUERST das nächste
        GROQ_FALLBACK_MODELS-Modell versuchen (weiterhin Groq, kein Provider-Wechsel), bevor
        überhaupt eine Cross-Provider-Kette in Betracht kommt."""
        call_models: list[str] = []

        def fake_create(**kwargs):
            call_models.append(kwargs["model"])
            if kwargs["model"] == "openai/gpt-oss-120b":
                raise REQUEST_TOO_LARGE_ERROR
            response = MagicMock()
            response.choices[0].message.content = "Gerettet von llama-3.3-70b-versatile"
            response.usage.prompt_tokens = 10
            response.usage.completion_tokens = 5
            return response

        mock_groq_client.chat.completions.create.side_effect = fake_create
        client = GroqClient(model_name="openai/gpt-oss-120b")

        result = asyncio.run(client.generate_with_usage("hi", None))

        self.assertEqual(call_models, ["openai/gpt-oss-120b", "llama-3.3-70b-versatile"])
        self.assertEqual(result.model_name, "groq:llama-3.3-70b-versatile")
        self.assertIn("Gerettet", result.text)

    @patch("core.llm_factory._groq_client")
    def test_413_when_pinned_still_tries_fallback_model_before_giving_up(self, mock_groq_client):
        """Auch innerhalb einer bereits gepinnten Aufgabe (_allow_self_fallback=False) muss die
        Innerhalb-Groq-Kette zuerst greifen - das ist kein Provider-Wechsel und gefährdet daher
        nicht die Konversationshistorie, die das Pinning eigentlich schützt."""
        def fake_create(**kwargs):
            if kwargs["model"] == "openai/gpt-oss-120b":
                raise REQUEST_TOO_LARGE_ERROR
            response = MagicMock()
            response.choices[0].message.content = "Gerettet trotz Pinning"
            response.usage.prompt_tokens = 10
            response.usage.completion_tokens = 5
            return response

        mock_groq_client.chat.completions.create.side_effect = fake_create
        client = GroqClient(model_name="openai/gpt-oss-120b")

        result = asyncio.run(client.generate_with_tools([], None, [], _allow_self_fallback=False))
        self.assertEqual(result.model_name, "groq:llama-3.3-70b-versatile")


if __name__ == "__main__":
    unittest.main()
