"""
core/llm_providers/huggingface.py – HuggingFaceClient (P6-5, ROADMAP_TEMP.md, aus
core/llm_factory.py extrahiert). Siehe core/llm_providers/groq.py-Moduldocstring für die
`import core.llm_factory as _lf; _lf.NAME`-Konvention.
"""

from __future__ import annotations

from config import GEMINI_STANDARD_MODEL
from core.llm_providers._shared import AgentMessage, LLMResponse


class HuggingFaceClient:
    """Wrapper für Hugging Face Models & Inference mit Fallback."""

    def __init__(self, model_name: str = "huggingface:auto"):
        self.model_name = model_name

    async def generate_with_usage(
        self, prompt: str, system_prompt: str | None = None, _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        from core.llm_providers.gemini import GeminiClient

        # Fallback auf Gemini; _allow_self_fallback=False verhindert Gemini<->HF-Endlosschleifen.
        if not _allow_self_fallback:
            raise RuntimeError("HuggingFace-Provider innerhalb einer Fallback-Kette nicht verfügbar.")
        fallback = GeminiClient(model_name=GEMINI_STANDARD_MODEL)
        return await fallback.generate_with_usage(prompt, system_prompt)

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        res = await self.generate_with_usage(prompt, system_prompt)
        return res.text

    async def generate_with_tools(
        self, messages: list[AgentMessage], system_prompt: str | None, tools: list[dict],
        _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        from core.llm_providers.gemini import GeminiClient

        # Kein natives Function-Calling für HuggingFace - Gemini übernimmt.
        if not _allow_self_fallback:
            raise RuntimeError("HuggingFace-Provider innerhalb einer Fallback-Kette nicht verfügbar.")
        fallback = GeminiClient(model_name=GEMINI_STANDARD_MODEL)
        return await fallback.generate_with_tools(messages, system_prompt, tools)

    async def generate_json(self, prompt: str, system_prompt: str | None = None) -> str:
        from core.llm_providers.gemini import GeminiClient

        fallback = GeminiClient(model_name=GEMINI_STANDARD_MODEL)
        return await fallback.generate_json(prompt, system_prompt)
