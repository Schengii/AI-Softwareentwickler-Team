"""
core/llm_factory.py – Erstellt und verwaltet LLM-Instanzen (Gemini, Groq, DeepSeek, OpenRouter, HuggingFace & Claude)
mit präziser Token-Messung und automatischer Failover-Kette.
"""

import asyncio
from dataclasses import dataclass
from typing import Optional
import httpx
from google import genai
from google.genai import types as genai_types
from config import (
    GEMINI_API_KEY,
    GROQ_API_KEY,
    DEEPSEEK_API_KEY,
    OPENROUTER_API_KEY,
    HUGGINGFACE_API_KEY,
    ANTHROPIC_API_KEY,
    MAX_OUTPUT_TOKENS,
    TEMPERATURE,
)
from core.token_guard import token_guard

# Globaler Gemini-Client
_gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# Globaler Groq-Client
_groq_client = None
if GROQ_API_KEY:
    try:
        from groq import Groq
        _groq_client = Groq(api_key=GROQ_API_KEY)
    except ImportError:
        _groq_client = None

# Fallback-Kette bei Ausfall / Token-Erschöpfung
MODEL_FALLBACKS = {
    "huggingface:auto": ["gemini-3.6-flash", "groq:openai/gpt-oss-120b", "gemini-3.1-flash-lite"],
    "openrouter:auto": ["gemini-3.6-flash", "groq:openai/gpt-oss-120b", "gemini-3.1-flash-lite"],
    "deepseek:deepseek-chat": ["gemini-3.6-flash", "groq:openai/gpt-oss-120b", "gemini-3.1-flash-lite"],
    "deepseek:deepseek-reasoner": ["deepseek:deepseek-chat", "gemini-3.6-flash", "groq:openai/gpt-oss-120b"],
    "claude-3-5-sonnet": ["deepseek:deepseek-chat", "gemini-3.6-flash", "gemini-3.1-flash-lite"],
    "gemini-3.6-flash": ["groq:openai/gpt-oss-120b", "gemini-3.1-flash-lite"],
    "gemini-3.1-flash-lite": ["gemini-3.6-flash", "groq:openai/gpt-oss-120b"],
    "groq:openai/gpt-oss-120b": ["gemini-3.6-flash", "gemini-3.1-flash-lite"],
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


class HuggingFaceClient:
    """Wrapper für Hugging Face Models & Inference mit Fallback."""

    def __init__(self, model_name: str = "huggingface:auto"):
        self.model_name = model_name

    async def generate_with_usage(
        self, prompt: str, system_prompt: Optional[str] = None
    ) -> LLMResponse:
        # Fallback auf Gemini für Text-/SVG-Generierung
        fallback = GeminiClient(model_name="gemini-3.6-flash")
        return await fallback.generate_with_usage(prompt, system_prompt)

    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        res = await self.generate_with_usage(prompt, system_prompt)
        return res.text


class OpenRouterClient:
    """Wrapper für OpenRouter API (Universal Multi-Model Gateway)."""

    def __init__(self, model_name: str = "openrouter/auto"):
        self.model_name = model_name.replace("openrouter:", "")
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"

    async def generate_with_usage(
        self, prompt: str, system_prompt: Optional[str] = None
    ) -> LLMResponse:
        if not OPENROUTER_API_KEY or token_guard.is_model_exhausted(f"openrouter:{self.model_name}"):
            fallback = GeminiClient(model_name="gemini-3.6-flash")
            return await fallback.generate_with_usage(prompt, system_prompt)

        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": "https://github.com/Schengii/AI-Softwareentwickler-Team",
            "X-Title": "AI Developer Team",
            "Content-Type": "application/json",
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model_name if self.model_name != "auto" else "google/gemini-2.5-flash",
            "messages": messages,
            "temperature": TEMPERATURE,
            "max_tokens": MAX_OUTPUT_TOKENS,
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(self.api_url, headers=headers, json=payload)
                data = response.json()

                if response.status_code == 200 and "choices" in data:
                    text = data["choices"][0]["message"]["content"]
                    usage = data.get("usage", {})
                    p_tok = usage.get("prompt_tokens", len(prompt) // 4)
                    c_tok = usage.get("completion_tokens", len(text) // 4)
                    tot = usage.get("total_tokens", p_tok + c_tok)

                    token_guard.record_usage(f"openrouter:{self.model_name}", p_tok, c_tok)

                    return LLMResponse(
                        text=text,
                        model_name=f"openrouter:{self.model_name}",
                        prompt_tokens=p_tok,
                        completion_tokens=c_tok,
                        total_tokens=tot,
                    )
                else:
                    err_msg = data.get("error", {}).get("message", "OpenRouter API Error")
                    if response.status_code in (401, 402, 429) or "balance" in err_msg.lower() or "limit" in err_msg.lower():
                        token_guard.mark_model_exhausted(f"openrouter:{self.model_name}", f"OpenRouter: {err_msg}")
                    
                    fallback = GeminiClient(model_name="gemini-3.6-flash")
                    return await fallback.generate_with_usage(prompt, system_prompt)

        except Exception as e:
            token_guard.mark_model_exhausted(f"openrouter:{self.model_name}", str(e))
            fallback = GeminiClient(model_name="gemini-3.6-flash")
            return await fallback.generate_with_usage(prompt, system_prompt)

    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        res = await self.generate_with_usage(prompt, system_prompt)
        return res.text


class DeepSeekClient:
    """Wrapper für die DeepSeek API (OpenAI-kompatibel via REST)."""

    def __init__(self, model_name: str = "deepseek-chat"):
        self.model_name = model_name.replace("deepseek:", "")
        self.api_url = "https://api.deepseek.com/chat/completions"

    async def generate_with_usage(
        self, prompt: str, system_prompt: Optional[str] = None
    ) -> LLMResponse:
        if not DEEPSEEK_API_KEY or token_guard.is_model_exhausted(f"deepseek:{self.model_name}"):
            fallback = GeminiClient(model_name="gemini-3.6-flash")
            return await fallback.generate_with_usage(prompt, system_prompt)

        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": TEMPERATURE,
            "max_tokens": MAX_OUTPUT_TOKENS,
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(self.api_url, headers=headers, json=payload)
                data = response.json()

                if response.status_code == 200 and "choices" in data:
                    text = data["choices"][0]["message"]["content"]
                    usage = data.get("usage", {})
                    p_tok = usage.get("prompt_tokens", len(prompt) // 4)
                    c_tok = usage.get("completion_tokens", len(text) // 4)
                    tot = usage.get("total_tokens", p_tok + c_tok)

                    token_guard.record_usage(f"deepseek:{self.model_name}", p_tok, c_tok)

                    return LLMResponse(
                        text=text,
                        model_name=f"deepseek:{self.model_name}",
                        prompt_tokens=p_tok,
                        completion_tokens=c_tok,
                        total_tokens=tot,
                    )
                else:
                    err_msg = data.get("error", {}).get("message", "DeepSeek API Error")
                    if response.status_code in (402, 429) or "balance" in err_msg.lower() or "quota" in err_msg.lower():
                        token_guard.mark_model_exhausted(f"deepseek:{self.model_name}", f"DeepSeek: {err_msg}")
                    
                    fallback = GeminiClient(model_name="gemini-3.6-flash")
                    return await fallback.generate_with_usage(prompt, system_prompt)

        except Exception as e:
            token_guard.mark_model_exhausted(f"deepseek:{self.model_name}", str(e))
            fallback = GeminiClient(model_name="gemini-3.6-flash")
            return await fallback.generate_with_usage(prompt, system_prompt)

    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        res = await self.generate_with_usage(prompt, system_prompt)
        return res.text


class GeminiClient:
    """Wrapper für die Google Gemini API."""

    def __init__(self, model_name: str = "gemini-3.6-flash"):
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
            if _groq_client:
                groq_fallback = GroqClient(model_name="openai/gpt-oss-120b")
                return await groq_fallback.generate_with_usage(contents, config.system_instruction)
            raise RuntimeError("Gemini Client nicht initialisiert. Bitte GEMINI_API_KEY setzen.")

        start_model = self.model_name
        models_to_try = [start_model] + MODEL_FALLBACKS.get(start_model, [])
        models_to_try = [m for m in models_to_try if not token_guard.is_model_exhausted(m)] or [start_model]

        last_error: Exception | None = None
        for model in models_to_try:
            if model.startswith("groq:"):
                groq_c = GroqClient(model_name=model)
                return await groq_c.generate_with_usage(contents, config.system_instruction)
            elif model.startswith("deepseek:"):
                ds_c = DeepSeekClient(model_name=model)
                return await ds_c.generate_with_usage(contents, config.system_instruction)
            elif model.startswith("openrouter:"):
                or_c = OpenRouterClient(model_name=model)
                return await or_c.generate_with_usage(contents, config.system_instruction)
            elif model.startswith("huggingface:"):
                hf_c = HuggingFaceClient(model_name=model)
                return await hf_c.generate_with_usage(contents, config.system_instruction)

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
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "Quota" in err_str:
                        token_guard.mark_model_exhausted(model, "429 Quota Exceeded")
                        break
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


class GroqClient:
    """High-Speed Groq Inferenz Client (Llama 3, Qwen, GPT-OSS)."""

    def __init__(self, model_name: str = "openai/gpt-oss-120b"):
        self.model_name = model_name.replace("groq:", "")

    async def generate_with_usage(
        self, prompt: str, system_prompt: Optional[str] = None
    ) -> LLMResponse:
        if not _groq_client:
            gemini_fallback = GeminiClient(model_name="gemini-3.6-flash")
            return await gemini_fallback.generate_with_usage(prompt, system_prompt)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = await asyncio.to_thread(
                _groq_client.chat.completions.create,
                model=self.model_name,
                messages=messages,
                temperature=TEMPERATURE,
                max_tokens=MAX_OUTPUT_TOKENS,
            )
            raw_text = response.choices[0].message.content or ""
            
            import re
            clean_text = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL).strip()

            prompt_tokens = response.usage.prompt_tokens if hasattr(response, "usage") and response.usage else len(prompt) // 4
            comp_tokens = response.usage.completion_tokens if hasattr(response, "usage") and response.usage else len(clean_text) // 4
            total = prompt_tokens + comp_tokens

            token_guard.record_usage(f"groq:{self.model_name}", prompt_tokens, comp_tokens)

            return LLMResponse(
                text=clean_text,
                model_name=f"groq:{self.model_name}",
                prompt_tokens=prompt_tokens,
                completion_tokens=comp_tokens,
                total_tokens=total,
            )
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "rate_limit" in err_str:
                token_guard.mark_model_exhausted(f"groq:{self.model_name}", "Groq Rate Limit")
            
            gemini_fallback = GeminiClient(model_name="gemini-3.6-flash")
            return await gemini_fallback.generate_with_usage(prompt, system_prompt)

    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        res = await self.generate_with_usage(prompt, system_prompt)
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
            gemini_fallback = GeminiClient(model_name="gemini-3.6-flash")
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
            gemini_client = GeminiClient(model_name="gemini-3.6-flash")
            return await gemini_client.generate_with_usage(prompt, system_prompt)

    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        res = await self.generate_with_usage(prompt, system_prompt)
        return res.text


class LLMFactory:
    """Factory zum Erstellen von LLM-Instanzen basierend auf Konfiguration."""

    @staticmethod
    def create_gemini(model_name: str = "gemini-3.6-flash") -> GeminiClient:
        return GeminiClient(model_name=model_name)

    @staticmethod
    def create_groq(model_name: str = "openai/gpt-oss-120b") -> GroqClient:
        return GroqClient(model_name=model_name)

    @staticmethod
    def create_deepseek(model_name: str = "deepseek-chat") -> DeepSeekClient:
        return DeepSeekClient(model_name=model_name)

    @staticmethod
    def create_openrouter(model_name: str = "openrouter/auto") -> OpenRouterClient:
        return OpenRouterClient(model_name=model_name)

    @staticmethod
    def create_huggingface(model_name: str = "huggingface:auto") -> HuggingFaceClient:
        return HuggingFaceClient(model_name=model_name)

    @staticmethod
    def create_claude(model_name: str = "claude-3-5-sonnet-20241022") -> ClaudeClient:
        return ClaudeClient(model_name=model_name)

    @staticmethod
    def create_for_agent(agent_id: str):
        from config import AGENT_MODELS, DEFAULT_AGENT_MODEL
        model_name = AGENT_MODELS.get(agent_id, DEFAULT_AGENT_MODEL)
        
        if model_name.startswith("huggingface:") or "huggingface" in model_name:
            return HuggingFaceClient(model_name=model_name)
        elif model_name.startswith("openrouter:") or "openrouter" in model_name:
            return OpenRouterClient(model_name=model_name)
        elif model_name.startswith("deepseek:") or "deepseek" in model_name:
            return DeepSeekClient(model_name=model_name)
        elif model_name.startswith("groq:") or "gpt-oss" in model_name or "qwen" in model_name:
            return GroqClient(model_name=model_name)
        elif "claude" in model_name.lower():
            return ClaudeClient(model_name=model_name)
        return GeminiClient(model_name=model_name)
