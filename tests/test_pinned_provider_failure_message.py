"""
tests/test_pinned_provider_failure_message.py – Regressionstest für einen echten Fund aus
Probelauf 3 (verifizierte Fix #1 gegen main): governance_lead (HEAVY-Tier, kein
ANTHROPIC_API_KEY) war innerhalb einer Aufgabe bereits erfolgreich auf Groq gepinnt (siehe
agents/base_agent.py active_llm), verbrauchte über mehrere Iterationen genug Tokens, um
Groqs echtes Tageskontingent zu kippen ("tokens per day (TPD)") - und die Aufgabe scheiterte
mit dem ROHEN Groq-JSON-Fehlertext als AgentResult.error, statt einer verständlichen Meldung.

Das eigentliche Verhalten (kein weiterer Fallback-Hop NACH dem Pinning zu einem SCHEMA-FREMDEN
Provider wie Gemini) ist bewusst und bleibt unverändert - ein Hop dorthin würde exakt die
Provider-Historie-Korruption zurückbringen, die das Pinning verhindert (siehe
_run_agentic_loop-Docstring in agents/base_agent.py). Seit P7-1 (ROADMAP_TEMP.md, realer Fund:
webhook_sentinel/omnimetric_engine 2026-09-21/22, `tester` scheiterte gepinnt an Groqs TPM-Limit,
ohne dass DeepSeek/OpenRouter je versucht wurden) gibt es aber eine gezielte Ausnahme: ein Hop zu
einem SCHEMA-GLEICHEN Provider (DeepSeek/OpenRouter - beide teilen Groqs OpenAI-kompatibles
Tool-Call-Format, siehe core/llm_factory._same_schema_failover_with_tools()) ist auch gepinnt
sicher und wird jetzt versucht, BEVOR die hier getestete freundliche Fehlermeldung greift.

Die "still unwrapped" / "clear message"-Tests unten deaktivieren DeepSeek/OpenRouter bewusst
(keine Kandidaten), um weiterhin ausschließlich den ursprünglichen Fall zu prüfen: alle
schema-gleichen Ausweichmöglichkeiten sind erschöpft/nicht verfügbar. Der Erfolgsfall (ein
schema-gleicher Provider rettet den gepinnten Aufruf) hat eigene Tests weiter unten.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from config import GEMINI_STANDARD_MODEL
from core.llm_factory import ClaudeClient, GroqClient
from core.llm_providers._shared import LLMResponse
from core.token_guard import token_guard

RATE_LIMIT_ERROR = Exception(
    "Error code: 429 - {'error': {'message': \"Rate limit reached for model "
    "`openai/gpt-oss-120b` ... tokens per day (TPD): Limit 200000, Used 198410, "
    "Requested 5883.\", 'type': 'tokens', 'code': 'rate_limit_exceeded'}}"
)
NON_RATE_LIMIT_ERROR = Exception("Connection reset by peer")


class TestPinnedGroqFailureMessage(unittest.TestCase):
    def tearDown(self):
        for name in ("groq:openai/gpt-oss-120b", "deepseek:deepseek-chat", "openrouter:openrouter/auto"):
            token_guard._exhausted_models.pop(name, None)

    @patch("core.llm_factory.OPENROUTER_API_KEY", "")
    @patch("core.llm_factory.DEEPSEEK_API_KEY", "")
    @patch("core.llm_factory._groq_client")
    def test_pinned_groq_rate_limit_raises_clear_message_not_raw_json(self, mock_groq_client):
        """Kein schema-gleicher Ausweich-Provider konfiguriert (P7-1) -> die freundliche
        Pinning-Meldung greift wie vor P7-1 unverändert."""
        mock_groq_client.chat.completions.create.side_effect = RATE_LIMIT_ERROR
        client = GroqClient(model_name="openai/gpt-oss-120b")

        import asyncio
        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(client.generate_with_tools([], None, [], _allow_self_fallback=False))

        message = str(ctx.exception)
        self.assertIn("bereits fest eingeplant", message)
        self.assertIn("Groq", message)
        # Rohe Provider-Meldung bleibt zur Diagnose erhalten, nur nicht mehr die GANZE Antwort.
        self.assertIn("rate_limit_exceeded", message)

    @patch("core.llm_factory.OPENROUTER_API_KEY", "")
    @patch("core.llm_factory.DEEPSEEK_API_KEY", "")
    @patch("core.llm_factory._groq_client")
    def test_pinned_groq_non_rate_limit_error_stays_unwrapped(self, mock_groq_client):
        """Nur echte Kontingent-/Rate-Limit-Fehler bekommen die freundliche Hülle - andere
        Fehlerarten (z.B. Netzwerkfehler) unverändert durchreichen, da hier eine andere
        Diagnose nötig ist."""
        mock_groq_client.chat.completions.create.side_effect = NON_RATE_LIMIT_ERROR
        client = GroqClient(model_name="openai/gpt-oss-120b")

        import asyncio
        with self.assertRaises(Exception) as ctx:
            asyncio.run(client.generate_with_tools([], None, [], _allow_self_fallback=False))

        self.assertEqual(str(ctx.exception), "Connection reset by peer")

    @patch("core.llm_factory.OPENROUTER_API_KEY", "")
    @patch("core.llm_providers.deepseek.DeepSeekClient.generate_with_tools", new_callable=AsyncMock)
    @patch("core.llm_factory._groq_client")
    def test_pinned_groq_rate_limit_fails_over_to_deepseek(self, mock_groq_client, mock_deepseek_tools):
        """P7-1: ein GEPINNTER Groq-Aufruf, der an TPM scheitert, darf zu DeepSeek ausweichen -
        beide teilen dasselbe OpenAI-kompatible Tool-Call-Schema, ein Hop korrumpiert die
        Tool-Historie also nicht (siehe core/llm_factory._same_schema_failover_with_tools())."""
        mock_groq_client.chat.completions.create.side_effect = RATE_LIMIT_ERROR
        mock_deepseek_tools.return_value = LLMResponse(
            text="von DeepSeek gerettet", model_name="deepseek:deepseek-chat",
            prompt_tokens=10, completion_tokens=5, total_tokens=15,
        )
        client = GroqClient(model_name="openai/gpt-oss-120b")

        import asyncio
        result = asyncio.run(client.generate_with_tools([], None, [], _allow_self_fallback=False))

        self.assertEqual(result.model_name, "deepseek:deepseek-chat")
        # Der Ausweich-Aufruf selbst bleibt gepinnt (kein Ping-Pong über mehr als einen Hop).
        mock_deepseek_tools.assert_awaited_once()
        self.assertFalse(mock_deepseek_tools.await_args.kwargs.get("_allow_self_fallback", True))

    @patch("core.llm_factory.OPENROUTER_API_KEY", "")
    @patch("core.llm_factory.DEEPSEEK_API_KEY", "dummy-key-for-test")
    @patch("core.llm_providers.deepseek.DeepSeekClient.generate_with_tools", new_callable=AsyncMock)
    @patch("core.llm_factory._groq_client")
    def test_pinned_groq_rate_limit_still_raises_if_deepseek_also_fails(
        self, mock_groq_client, mock_deepseek_tools,
    ):
        """Scheitert auch der schema-gleiche Ausweich-Versuch, muss die ursprüngliche, verständliche
        Groq-Meldung erhalten bleiben - kein rohes DeepSeek-Fehlerobjekt stattdessen."""
        mock_groq_client.chat.completions.create.side_effect = RATE_LIMIT_ERROR
        mock_deepseek_tools.side_effect = RuntimeError("DeepSeek-Fehler innerhalb einer Fallback-Kette: auch erschöpft")
        client = GroqClient(model_name="openai/gpt-oss-120b")

        import asyncio
        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(client.generate_with_tools([], None, [], _allow_self_fallback=False))

        message = str(ctx.exception)
        self.assertIn("bereits fest eingeplant", message)
        self.assertIn("Groq", message)

    @patch("core.llm_factory.OPENROUTER_API_KEY", "")
    @patch("core.llm_providers.deepseek.DeepSeekClient.generate_with_usage", new_callable=AsyncMock)
    @patch("core.llm_factory._groq_client")
    def test_pinned_groq_rate_limit_fails_over_to_deepseek_non_tools_path(
        self, mock_groq_client, mock_deepseek_usage,
    ):
        """Dieselbe Ausweichmöglichkeit muss auch für generate_with_usage() (Nicht-Tool-Aufrufe,
        z.B. reine Text-/JSON-Generierung) gelten, nicht nur für generate_with_tools()."""
        mock_groq_client.chat.completions.create.side_effect = RATE_LIMIT_ERROR
        mock_deepseek_usage.return_value = LLMResponse(
            text="von DeepSeek gerettet", model_name="deepseek:deepseek-chat",
            prompt_tokens=10, completion_tokens=5, total_tokens=15,
        )
        client = GroqClient(model_name="openai/gpt-oss-120b")

        import asyncio
        result = asyncio.run(client.generate_with_usage("Hallo", None, _allow_self_fallback=False))

        self.assertEqual(result.model_name, "deepseek:deepseek-chat")
        mock_deepseek_usage.assert_awaited_once()

    @patch("core.llm_factory._groq_client")
    def test_not_yet_pinned_groq_rate_limit_still_falls_back_to_gemini(self, mock_groq_client):
        """Regression: die Klarheits-Meldung darf NUR beim gepinnten Scheitern greifen - vor
        dem Pinning muss der bestehende automatische Rettungs-Hop zu Gemini unverändert
        funktionieren."""
        mock_groq_client.chat.completions.create.side_effect = RATE_LIMIT_ERROR
        client = GroqClient(model_name="openai/gpt-oss-120b")

        with patch("core.llm_factory._gemini_client") as mock_gemini:
            class _FakeResponse:
                candidates = []
                text = "von Gemini gerettet"

            mock_gemini.models.generate_content.return_value = _FakeResponse()

            import asyncio
            result = asyncio.run(client.generate_with_tools([], None, [], _allow_self_fallback=True))

        # Realer Fund (Team-Retrospektive nach dem taskpulse-Lauf): dieser Test hatte den
        # Rettungs-Hop-Zielmodellnamen bisher als Literal ("gemini-3.6-flash") hartcodiert -
        # als GEMINI_STANDARD_MODEL (config.py) auf "gemini-3.8-flash" angehoben wurde, brach
        # der Test, obwohl das GETESTETE Verhalten (Fallback landet beim jeweils aktuellen
        # Gemini-Standardmodell) unverändert korrekt war. Der Vergleich gegen die Konstante
        # statt eines Literals hält den Test robust gegen zukünftige Modell-Updates.
        self.assertEqual(result.model_name, GEMINI_STANDARD_MODEL)


class TestPinnedClaudeFailureMessage(unittest.TestCase):
    def tearDown(self):
        token_guard._exhausted_models.pop("claude-sonnet-5", None)

    def test_pinned_claude_rate_limit_raises_clear_message_not_raw_json(self):
        client = ClaudeClient(model_name="claude-sonnet-5")
        client._client = MagicMock()
        client._client.messages.create = AsyncMock(side_effect=RATE_LIMIT_ERROR)

        import asyncio
        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(client.generate_with_tools([], None, [], _allow_self_fallback=False))

        message = str(ctx.exception)
        self.assertIn("bereits fest eingeplant", message)
        self.assertIn("Claude", message)
        self.assertIn("rate_limit_exceeded", message)


if __name__ == "__main__":
    unittest.main()
