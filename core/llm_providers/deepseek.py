"""
core/llm_providers/deepseek.py – DeepSeekClient (P6-5, ROADMAP_TEMP.md, aus core/llm_factory.py
extrahiert). Siehe core/llm_providers/groq.py-Moduldocstring für die
`import core.llm_factory as _lf; _lf.NAME`-Konvention, die hier identisch angewendet wird.
"""

from __future__ import annotations

import httpx

from core.llm_providers._shared import (
    AgentMessage,
    LLMResponse,
    _openai_build_messages,
    _openai_build_tools,
    _openai_parse_tool_calls,
    openai_tool_choice,
)
from core.token_guard import token_guard


class DeepSeekClient:
    """Wrapper für die DeepSeek API (OpenAI-kompatibel via REST)."""

    def __init__(self, model_name: str = "deepseek-chat"):
        self.model_name = model_name.replace("deepseek:", "")
        self.api_url = "https://api.deepseek.com/chat/completions"

    async def generate_with_usage(
        self, prompt: str, system_prompt: str | None = None, _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        import core.llm_factory as _lf

        if not _lf.DEEPSEEK_API_KEY or token_guard.is_model_exhausted(f"deepseek:{self.model_name}"):
            if not _allow_self_fallback:
                raise RuntimeError("DeepSeek innerhalb einer Fallback-Kette nicht verfügbar (kein Key/erschöpft).")
            return await _lf._cross_provider_failover_with_usage("deepseek", prompt, system_prompt)

        headers = {
            "Authorization": f"Bearer {_lf.DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": _lf.TEMPERATURE,
            "max_tokens": _lf.MAX_OUTPUT_TOKENS,
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
                        token_guard.mark_model_exhausted(f"deepseek:{self.model_name}", f"DeepSeek: {err_msg}", cooldown_seconds=_lf._exhaustion_cooldown_seconds(err_msg))
                    if not _allow_self_fallback:
                        raise RuntimeError(f"DeepSeek-Fehler innerhalb einer Fallback-Kette: {err_msg}")
                    return await _lf._cross_provider_failover_with_usage("deepseek", prompt, system_prompt)

        except Exception as e:
            token_guard.mark_model_exhausted(f"deepseek:{self.model_name}", str(e), cooldown_seconds=_lf._exhaustion_cooldown_seconds(str(e)))
            if not _allow_self_fallback:
                raise
            return await _lf._cross_provider_failover_with_usage("deepseek", prompt, system_prompt)

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        res = await self.generate_with_usage(prompt, system_prompt)
        return res.text

    async def generate_with_tools(
        self, messages: list[AgentMessage], system_prompt: str | None, tools: list[dict],
        _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        import core.llm_factory as _lf

        if not _lf.DEEPSEEK_API_KEY or token_guard.is_model_exhausted(f"deepseek:{self.model_name}"):
            if not _allow_self_fallback:
                raise RuntimeError("DeepSeek innerhalb einer Fallback-Kette nicht verfügbar (kein Key/erschöpft).")
            return await _lf._cross_provider_failover_with_tools("deepseek", messages, system_prompt, tools)

        headers = {"Authorization": f"Bearer {_lf.DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": self.model_name,
            "messages": _openai_build_messages(messages, system_prompt),
            "tools": _openai_build_tools(tools),
            "tool_choice": openai_tool_choice(),
            "temperature": _lf.TEMPERATURE,
            "max_tokens": _lf.MAX_OUTPUT_TOKENS,
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(self.api_url, headers=headers, json=payload)
                data = response.json()

                if response.status_code == 200 and "choices" in data:
                    message = data["choices"][0]["message"]
                    usage = data.get("usage", {})
                    p_tok = usage.get("prompt_tokens", 0)
                    c_tok = usage.get("completion_tokens", 0)
                    token_guard.record_usage(f"deepseek:{self.model_name}", p_tok, c_tok)

                    return LLMResponse(
                        text=message.get("content") or "",
                        model_name=f"deepseek:{self.model_name}",
                        prompt_tokens=p_tok,
                        completion_tokens=c_tok,
                        total_tokens=usage.get("total_tokens", p_tok + c_tok),
                        tool_calls=_openai_parse_tool_calls(message),
                    )

                err_msg = data.get("error", {}).get("message", "DeepSeek API Error")
                if response.status_code in (402, 429) or "balance" in err_msg.lower() or "quota" in err_msg.lower():
                    token_guard.mark_model_exhausted(f"deepseek:{self.model_name}", f"DeepSeek: {err_msg}", cooldown_seconds=_lf._exhaustion_cooldown_seconds(err_msg))
                if not _allow_self_fallback:
                    raise RuntimeError(f"DeepSeek-Fehler innerhalb einer Fallback-Kette: {err_msg}")
                return await _lf._cross_provider_failover_with_tools("deepseek", messages, system_prompt, tools)

        except Exception as e:
            token_guard.mark_model_exhausted(f"deepseek:{self.model_name}", str(e), cooldown_seconds=_lf._exhaustion_cooldown_seconds(str(e)))
            if not _allow_self_fallback:
                raise
            return await _lf._cross_provider_failover_with_tools("deepseek", messages, system_prompt, tools)

    async def generate_json(self, prompt: str, system_prompt: str | None = None) -> str:
        json_instruction = "\n\nAntworte AUSSCHLIESSLICH mit einem gültigen JSON-Objekt, ohne Markdown-Codeblock, ohne Erklärungen davor oder danach."
        res = await self.generate_with_usage(prompt, (system_prompt or "") + json_instruction)
        return res.text
