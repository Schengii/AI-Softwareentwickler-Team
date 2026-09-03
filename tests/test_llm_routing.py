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

from config import GEMINI_STANDARD_MODEL
from core.llm_factory import GeminiClient, LLMResponse
from core.token_guard import token_guard


class _FakeGenAIResponse:
    def __init__(self, text: str):
        self.text = text


class TestLLMRouting(unittest.TestCase):
    def tearDown(self):
        # Global geteilten TokenGuard-Zustand nicht in andere Tests durchsickern lassen.
        for model in ("gemini-3.6-flash", GEMINI_STANDARD_MODEL, "gemini-3.1-flash-lite", "claude-sonnet-5", "groq:openai/gpt-oss-120b"):
            token_guard._exhausted_models.pop(model, None)

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

    @patch("core.llm_factory.asyncio.sleep")
    @patch("core.llm_factory._gemini_client")
    def test_waits_briefly_when_entire_fallback_chain_is_exhausted(self, mock_gemini_client, mock_sleep):
        """
        Realer Fund aus einem echten Lauf: als ALLE Modelle einer Fallback-Kette gleichzeitig
        als erschöpft markiert waren (kein ANTHROPIC_API_KEY als Backstop), scheiterte jeder
        einzelne Agenten-Aufruf sofort mit demselben 429 - ohne je den (oft nur Sekunden
        entfernten) Cooldown abzuwarten. Jetzt wird kurz gewartet (gedeckelt via
        MAX_EXHAUSTION_WAIT_SECONDS), dann erneut versucht.
        """
        # Die GESAMTE Kette von gemini-3.6-flash (sich selbst + claude-sonnet-5 +
        # gemini-3.1-flash-lite + groq, siehe MODEL_FALLBACKS) muss als erschöpft markiert
        # sein, damit die Wartelogik greift - nicht nur ein einzelnes Glied. Realer Fund (Team-
        # Retrospektive nach dem taskpulse-Lauf): als MODEL_FALLBACKS um "gemini-3.8-flash" als
        # zusätzlichen Hop erweitert wurde (siehe core/llm_factory.py), fehlte dieser Test hier
        # in der Liste - die Kette fand dadurch einen freien Hop und die Wartelogik griff nie
        # (mock_sleep wurde 0x statt 1x aufgerufen), obwohl das GETESTETE Verhalten selbst
        # unverändert korrekt war.
        token_guard.mark_model_exhausted("gemini-3.6-flash", "Test", cooldown_seconds=3.0)
        token_guard.mark_model_exhausted(GEMINI_STANDARD_MODEL, "Test", cooldown_seconds=3.0)
        token_guard.mark_model_exhausted("claude-sonnet-5", "Test", cooldown_seconds=3.0)
        token_guard.mark_model_exhausted("gemini-3.1-flash-lite", "Test", cooldown_seconds=3.0)
        token_guard.mark_model_exhausted("groq:openai/gpt-oss-120b", "Test", cooldown_seconds=3.0)

        mock_gemini_client.models.generate_content.return_value = _FakeGenAIResponse(text="ok")

        client = GeminiClient(model_name="gemini-3.6-flash")

        async def run():
            return await client.generate_with_usage("Sag nur 'ok'.", None)

        import asyncio
        result = asyncio.run(run())

        self.assertEqual(result.text, "ok")
        mock_sleep.assert_called_once()
        # Wartezeit muss gedeckelt UND positiv sein (kürzester bekannter Cooldown, hier 3s).
        waited = mock_sleep.call_args[0][0]
        self.assertGreater(waited, 0.0)
        self.assertLessEqual(waited, 3.0)

    @patch("core.llm_factory._gemini_rate_limiter")
    @patch("core.llm_factory._gemini_client")
    def test_real_gemini_calls_go_through_the_proactive_rate_limiter(self, mock_gemini_client, mock_limiter):
        """
        Realer Fund: 3+-Mitglieder-Fachbereiche schicken über asyncio.gather ihre erste
        Anfrage praktisch zeitgleich an Gemini - core/rate_limiter.py entzerrt das. Stellt
        sicher, dass jeder ECHTE Gemini-API-Aufruf tatsächlich durch den Rate-Limiter geht,
        nicht nur, dass die Klasse irgendwo existiert.
        """
        from unittest.mock import AsyncMock
        mock_limiter.acquire = AsyncMock()
        mock_gemini_client.models.generate_content.return_value = _FakeGenAIResponse(text="ok")

        client = GeminiClient(model_name="gemini-3.6-flash")

        async def run():
            return await client.generate_with_usage("Sag nur 'ok'.", None)

        import asyncio
        result = asyncio.run(run())

        self.assertEqual(result.text, "ok")
        mock_limiter.acquire.assert_called_once()

    @patch("core.llm_factory.LLMFactory.create_for_model")
    @patch("core.llm_factory._gemini_client")
    def test_falls_back_to_groq_when_gemini_and_claude_both_fail(self, mock_gemini_client, mock_create_for_model):
        """
        Realer Fund aus einem echten End-to-End-Testlauf ohne ANTHROPIC_API_KEY: der
        QA-Tester scheiterte komplett ("Gemini Function-Calling Fehler nach allen
        Fallback-Modellen (gemini-3.1-flash-lite): Claude ... nicht verfügbar"), obwohl Groq
        im SELBEN Lauf für andere Rollen einwandfrei funktionierte - die STANDARD/LITE-Ketten
        hatten bisher keinen Groq-Backstop (siehe MODEL_FALLBACKS). Simuliert: Gemini
        schlägt für JEDEN Kandidaten fehl (nicht nur Quota, ein echter Fehler), Claude hat
        keinen Schlüssel -> Groq muss als letzte Stufe erreicht werden.
        """
        def fake_generate_content(model, contents, config):
            raise RuntimeError("simulierter Gemini-Fehler (z.B. Function-Calling)")
        mock_gemini_client.models.generate_content = fake_generate_content

        fake_groq_client = AsyncMock()
        fake_groq_client.generate_with_tools = AsyncMock(return_value=LLMResponse(
            text="von Groq gerettet", model_name="groq:openai/gpt-oss-120b",
            prompt_tokens=5, completion_tokens=3, total_tokens=8, tool_calls=[],
        ))

        def fake_create_for_model(model_name):
            if model_name == "groq:openai/gpt-oss-120b":
                return fake_groq_client
            raise RuntimeError(f"kein API-Key für {model_name}")

        mock_create_for_model.side_effect = fake_create_for_model

        client = GeminiClient(model_name="gemini-3.1-flash-lite")

        async def run():
            return await client.generate_with_tools([], None, [])

        import asyncio
        result = asyncio.run(run())

        self.assertEqual(result.text, "von Groq gerettet")
        fake_groq_client.generate_with_tools.assert_called_once()

    @patch("core.llm_factory.LLMFactory.create_for_model")
    @patch("core.llm_factory._gemini_client")
    def test_generate_with_usage_falls_back_to_groq_when_gemini_and_claude_both_fail(
        self, mock_gemini_client, mock_create_for_model,
    ):
        """
        Gegenstück zu test_falls_back_to_groq_when_gemini_and_claude_both_fail für den
        Nicht-Tool-Calling-Pfad (_call_with_retry_and_usage): dieselbe Struktur (models_to_try-
        Schleife, Nicht-Gemini-Kandidaten via LLMFactory.create_for_model delegieren) existiert
        hier separat und war bisher ungetestet - eine Regression, die nur diesen Pfad betrifft
        (z.B. ein reiner Text-Aufruf ohne Werkzeuge), wäre vom Tools-Test allein nicht erkannt
        worden.
        """
        def fake_generate_content(model, contents, config):
            raise RuntimeError("simulierter Gemini-Fehler (z.B. Function-Calling)")
        mock_gemini_client.models.generate_content = fake_generate_content

        fake_groq_client = AsyncMock()
        fake_groq_client.generate_with_usage = AsyncMock(return_value=LLMResponse(
            text="von Groq gerettet", model_name="groq:openai/gpt-oss-120b",
            prompt_tokens=5, completion_tokens=3, total_tokens=8,
        ))

        def fake_create_for_model(model_name):
            if model_name == "groq:openai/gpt-oss-120b":
                return fake_groq_client
            raise RuntimeError(f"kein API-Key für {model_name}")

        mock_create_for_model.side_effect = fake_create_for_model

        client = GeminiClient(model_name="gemini-3.1-flash-lite")

        async def run():
            return await client.generate_with_usage("Sag nur 'ok'.", None)

        import asyncio
        result = asyncio.run(run())

        self.assertEqual(result.text, "von Groq gerettet")
        fake_groq_client.generate_with_usage.assert_called_once()


if __name__ == "__main__":
    unittest.main()
