"""
core/llm_factory.py – Erstellt und verwaltet LLM-Instanzen (Gemini & Claude) mit Token-Tracking & Fallbacks
"""

import asyncio
from dataclasses import dataclass
from typing import Optional
from google import genai
from google.genai import types as genai_types
from config import (
    GEMINI_API_KEY,
    ANTHROPIC_API_KEY,
    MAX_OUTPUT_TOKENS,
    TEMPERATURE,
)
from core.token_guard import token_guard

# Globaler Gemini-Client
_gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# Fallback-Kette: Von High-End über Standard bis Lite/Alternative
MODEL_FALLBACKS = {
    "claude-3-7-sonnet": ["claude-3-5-haiku", "gemini-2.5-pro", "gemini-2.5-flash"],
    "claude-3-5-sonnet": ["claude-3-5-haiku", "gemini-2.5-pro", "gemini-2.5-flash"],
    "gemini-2.5-pro": ["gemini-2.5-flash", "gemini-2.5-flash-lite"],
    "gemini-3.6-flash": ["gemini-2.5-flash", "gemini-2.5-flash-lite"],
    "gemini-2.5-flash": ["gemini-2.5-flash-lite"],
    "gemini-2.5-flash-lite": ["gemini-2.0-flash"],
}

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 1.5


@dataclass
class LLMResponse:
    """Antwort eines LLM-Aufrufs mit Metriken."""
    text: str
    model_name: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class GeminiClient:
    """Wrapper für die Google Gemini API."""

    def __init__(self, model_name: str = "gemini-2.5-flash"):
        self.model_name = model_name

    async def generate_with_usage(
        self, prompt: str, system_prompt: Optional[str] = None
    ) -> LLMResponse:
        config = genai_types.GenerateContentConfig(
            temperature=TEMPERATURE,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            system_instruction=system_prompt if system_prompt else None,
        )
        return await self._call_with_retry_and_usage(prompt, config)

    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        res = await self.generate_with_usage(prompt, system_prompt)
        return res.text

    async def _call_with_retry_and_usage(
        self,
        contents: str,
        config: genai_types.GenerateContentConfig,
    ) -> LLMResponse:
        if not _gemini_client:
            raise RuntimeError("Gemini Client nicht initialisiert. Bitte GEMINI_API_KEY setzen.")

        # Prüfe, ob das aktuelle Modell als erschöpft markiert ist
        start_model = self.model_name
        models_to_try = [start_model] + MODEL_FALLBACKS.get(start_model, [])
        models_to_try = [m for m in models_to_try if not token_guard.is_model_exhausted(m)] or [start_model]

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
                    text = response.text or ""

                    prompt_tokens = 0
                    completion_tokens = 0
                    total_tokens = 0

                    if hasattr(response, "usage_metadata") and response.usage_metadata:
                        meta = response.usage_metadata
                        prompt_tokens = getattr(meta, "prompt_token_count", 0) or 0
                        completion_tokens = getattr(meta, "candidates_token_count", 0) or 0
                        total_tokens = getattr(meta, "total_token_count", 0) or (prompt_tokens + completion_tokens)
                    else:
                        prompt_tokens = len(contents) // 4
                        completion_tokens = len(text) // 4
                        total_tokens = prompt_tokens + completion_tokens

                    token_guard.record_usage(model, prompt_tokens, completion_tokens)

                    return LLMResponse(
                        text=text,
                        model_name=model,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                    )

                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    # Quota / ResourceExhausted Fehler erkennen
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "Quota" in err_str:
                        token_guard.mark_model_exhausted(model, "429 Quota Exceeded")
                        break  # Sofort zum nächsten günstigeren Modell in der Fallback-Kette
                    elif "503" in err_str or "UNAVAILABLE" in err_str:
                        wait = RETRY_DELAY_SECONDS * (attempt + 1)
                        await asyncio.sleep(wait)
                        continue
                    else:
                        break

        raise RuntimeError(
            f"Gemini API Fehler nach allen Versuchen ({self.model_name}): {last_error}"
        ) from last_error

    async def generate_json(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        config = genai_types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            system_instruction=system_prompt if system_prompt else None,
            response_mime_type="application/json",
        )
        res = await self._call_with_retry_and_usage(prompt, config)
        return res.text


class ClaudeClient:
    """Wrapper für die Anthropic Claude API mit Token-Tracking & Fallback."""

    def __init__(self, model_name: str = "claude-3-5-sonnet-20241022"):
        self.model_name = model_name
        self._client = None
        if ANTHROPIC_API_KEY:
            try:
                import anthropic
                self._client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            except ImportError:
                self._client = None

    async def generate_with_usage(
        self, prompt: str, system_prompt: Optional[str] = None
    ) -> LLMResponse:
        if not self._client:
            # Fallback zu Gemini wenn Claude SDK/Key nicht bereitsteht
            gemini_fallback = GeminiClient(model_name="gemini-2.5-flash")
            return await gemini_fallback.generate_with_usage(prompt, system_prompt)

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
            text = response.content[0].text if response.content else ""
            prompt_tokens = response.usage.input_tokens if hasattr(response, "usage") else len(prompt) // 4
            comp_tokens = response.usage.output_tokens if hasattr(response, "usage") else len(text) // 4
            total = prompt_tokens + comp_tokens

            token_guard.record_usage(self.model_name, prompt_tokens, comp_tokens)

            return LLMResponse(
                text=text,
                model_name=self.model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=comp_tokens,
                total_tokens=total,
            )
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "rate_limit" in err_str:
                token_guard.mark_model_exhausted(self.model_name, "Claude Rate Limit")
            # Automatischer Failover zu Gemini
            gemini_client = GeminiClient(model_name="gemini-2.5-flash")
            return await gemini_client.generate_with_usage(prompt, system_prompt)

    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        res = await self.generate_with_usage(prompt, system_prompt)
        return res.text


class LLMFactory:
    """Factory zum Erstellen von LLM-Instanzen basierend auf Konfiguration."""

    @staticmethod
    def create_gemini(model_name: str = "gemini-2.5-flash") -> GeminiClient:
        return GeminiClient(model_name=model_name)

    @staticmethod
    def create_claude(model_name: str = "claude-3-5-sonnet-20241022") -> ClaudeClient:
        return ClaudeClient(model_name=model_name)

    @staticmethod
    def create_for_agent(agent_id: str):
        from config import AGENT_MODELS, DEFAULT_AGENT_MODEL
        model_name = AGENT_MODELS.get(agent_id, DEFAULT_AGENT_MODEL)
        if "claude" in model_name.lower():
            return ClaudeClient(model_name=model_name)
        return GeminiClient(model_name=model_name)
