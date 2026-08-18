"""
core/llm_factory.py – Erstellt und verwaltet LLM-Instanzen (Gemini & Claude)

Verwendet das neue google-genai SDK (v2+).
"""

import asyncio
import time
from typing import Optional
from google import genai
from google.genai import types as genai_types
from config import (
    GEMINI_API_KEY,
    ANTHROPIC_API_KEY,
    MAX_OUTPUT_TOKENS,
    TEMPERATURE,
)

# Globaler Gemini-Client (einmalig initialisiert)
_gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# Fallback-Modelle falls das primäre Modell nicht verfügbar ist
MODEL_FALLBACKS = {
    "gemini-3.6-flash": ["gemini-2.5-flash", "gemini-2.5-flash-lite"],
    "gemini-2.5-flash": ["gemini-2.5-flash-lite"],
}

# Maximale Retry-Versuche bei 503-Fehlern
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2.0


class GeminiClient:
    """Wrapper für die Google Gemini API (google-genai SDK v2+)."""

    def __init__(self, model_name: str = "gemini-2.0-flash"):
        self.model_name = model_name

    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Sendet einen Prompt an Gemini und gibt die Antwort zurueck.
        Nutzt asyncio.to_thread() fuer nicht-blockierende Ausfuehrung.
        Automatisches Retry + Fallback bei 503-Fehlern.
        """
        config = genai_types.GenerateContentConfig(
            temperature=TEMPERATURE,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            system_instruction=system_prompt if system_prompt else None,
        )
        return await self._call_with_retry(prompt, config)

    async def _call_with_retry(
        self,
        contents: str,
        config: genai_types.GenerateContentConfig,
    ) -> str:
        """Interner Aufruf mit automatischem Retry und Modell-Fallback."""
        models_to_try = [self.model_name] + MODEL_FALLBACKS.get(self.model_name, [])

        last_error: Exception | None = None
        for model in models_to_try:
            for attempt in range(MAX_RETRIES):
                try:
                    response = await asyncio.to_thread(
                        _gemini_client.models.generate_content,
                        model=model,
                        contents=contents,
                        config=config,
                    )
                    return response.text or ""
                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    if "503" in err_str or "UNAVAILABLE" in err_str:
                        # Warte und versuche es erneut
                        wait = RETRY_DELAY_SECONDS * (attempt + 1)
                        await asyncio.sleep(wait)
                        continue
                    else:
                        # Anderer Fehler: direkt zum naechsten Modell
                        break

        raise RuntimeError(
            f"Gemini API Fehler nach allen Versuchen ({self.model_name}): {last_error}"
        ) from last_error

    async def generate_json(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Sendet einen Prompt und erwartet JSON-Antwort.
        Nutzt application/json MIME-Type fuer zuverlaessige JSON-Ausgabe.
        """
        config = genai_types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            system_instruction=system_prompt if system_prompt else None,
            response_mime_type="application/json",
        )
        return await self._call_with_retry(prompt, config)


class ClaudeClient:
    """Wrapper für die Anthropic Claude API (optional)."""

    def __init__(self, model_name: str = "claude-sonnet-4-5"):
        if not ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY nicht gesetzt. Claude ist nicht verfuegbar."
            )
        try:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        except ImportError:
            raise ImportError(
                "'anthropic' Paket nicht installiert. Fuehre 'pip install anthropic' aus."
            )
        self.model_name = model_name

    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Sendet einen Prompt an Claude und gibt die Antwort zurueck."""
        messages = [{"role": "user", "content": prompt}]
        kwargs: dict = {
            "model": self.model_name,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "messages": messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        try:
            response = await self._client.messages.create(**kwargs)
            return response.content[0].text
        except Exception as e:
            raise RuntimeError(f"Claude API Fehler ({self.model_name}): {e}") from e


class LLMFactory:
    """Factory zum Erstellen von LLM-Instanzen basierend auf Konfiguration."""

    @staticmethod
    def create_gemini(model_name: str = "gemini-2.0-flash") -> GeminiClient:
        """Erstellt eine Gemini-Client-Instanz."""
        return GeminiClient(model_name=model_name)

    @staticmethod
    def create_claude(model_name: str = "claude-sonnet-4-5") -> ClaudeClient:
        """Erstellt eine Claude-Client-Instanz (erfordert ANTHROPIC_API_KEY)."""
        return ClaudeClient(model_name=model_name)

    @staticmethod
    def create_for_agent(agent_id: str) -> GeminiClient:
        """Erstellt den passenden LLM-Client fuer einen bestimmten Agenten."""
        from config import AGENT_MODELS
        model_name = AGENT_MODELS.get(agent_id, "gemini-2.0-flash")
        return GeminiClient(model_name=model_name)
