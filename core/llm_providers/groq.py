"""
core/llm_providers/groq.py – GroqClient (P6-5, ROADMAP_TEMP.md, aus core/llm_factory.py
extrahiert). Verweist auf geteilten Zustand/Konfiguration in core/llm_factory.py AUSSCHLIESSLICH
über `import core.llm_factory as _lf; _lf.NAME` (niemals `from core.llm_factory import NAME`) -
so bleibt jeder bestehende `@patch("core.llm_factory.NAME", ...)`-Testaufruf wirksam, weil dieser
Code nie eine eigene, unabhängige Kopie des Namens hält, sondern ihn bei jedem Zugriff frisch vom
Modul-Objekt liest. Eine vergessene Umstellung wird laut (NameError/ruff F821), nie eine stille
Verhaltensabweichung.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import replace

from core.llm_providers._shared import (
    AgentMessage,
    LLMResponse,
    ToolCall,
    _openai_build_messages,
    _openai_build_tools,
    openai_tool_choice,
)
from core.token_guard import token_guard

_CHARS_PER_TOKEN_ESTIMATE = 4


def _budget_chars() -> int:
    import core.llm_factory as _lf
    return _lf.GROQ_PROMPT_TOKEN_BUDGET * _CHARS_PER_TOKEN_ESTIMATE


def _compress_text_for_groq(text: str, budget_chars: int) -> str:
    """Kürzt einen Text auf `budget_chars` durch Entfernen der Mitte - Anfang (Aufgabe) und Ende
    (oft die entscheidende Format-Anweisung) bleiben erhalten."""
    if budget_chars <= 0:
        return ""
    if len(text) <= budget_chars:
        return text
    marker = "\n…[wegen Groq-TPM-Limit gekürzt]…\n"
    head = int(budget_chars * 0.65)
    tail = budget_chars - head - len(marker)
    if tail <= 0:
        return text[:budget_chars]
    return text[:head] + marker + text[-tail:]


def _compress_prompt_for_groq(prompt: str, system_prompt: str | None) -> tuple[str, str | None]:
    """Komprimiert `prompt`/`system_prompt` gemeinsam auf GROQ_PROMPT_TOKEN_BUDGET."""
    budget_chars = _budget_chars()
    if len(prompt) + len(system_prompt or "") <= budget_chars:
        return prompt, system_prompt
    system_budget = budget_chars // 3 if system_prompt else 0
    compressed_system = _compress_text_for_groq(system_prompt, system_budget) if system_prompt else None
    prompt_budget = max(budget_chars - len(compressed_system or ""), budget_chars // 3)
    compressed_prompt = _compress_text_for_groq(prompt, prompt_budget)
    return compressed_prompt, compressed_system


def _compress_messages_for_groq(
    messages: list[AgentMessage], system_prompt: str | None,
) -> tuple[list[AgentMessage], str | None]:
    """Komprimiert die Werkzeug-Loop-History auf GROQ_PROMPT_TOKEN_BUDGET. Gekürzt wird nur `text`
    (gleiches Budget pro Turn); tool_calls/tool_call_id bleiben intakt, sonst bricht das Tool-Protokoll."""
    budget_chars = _budget_chars()
    total_len = len(system_prompt or "") + sum(len(m.text or "") for m in messages)
    if total_len <= budget_chars:
        return messages, system_prompt

    compressed_system = _compress_text_for_groq(system_prompt, budget_chars // 3) if system_prompt else None
    remaining = max(budget_chars - len(compressed_system or ""), 0)
    if remaining <= 0 or not messages:
        return messages, compressed_system

    per_message_budget = max(remaining // max(len(messages), 1), 200)
    compressed: list[AgentMessage] = []
    for msg in messages:
        if msg.text and len(msg.text) > per_message_budget:
            msg = replace(msg, text=_compress_text_for_groq(msg.text, per_message_budget))
        compressed.append(msg)
    return compressed, compressed_system


class GroqClient:
    """High-Speed Groq Inferenz Client (Llama 3, Qwen, GPT-OSS)."""

    def __init__(self, model_name: str = "openai/gpt-oss-120b"):
        self.model_name = model_name.replace("groq:", "")

    async def generate_with_usage(
        self, prompt: str, system_prompt: str | None = None, _allow_self_fallback: bool = True,
        _tried_groq_models: frozenset[str] = frozenset(),
    ) -> LLMResponse:
        import core.llm_factory as _lf

        if not _lf._groq_client:
            if not _allow_self_fallback:
                raise RuntimeError("Groq innerhalb einer Fallback-Kette nicht verfügbar (kein Key).")
            return await _lf._cross_provider_failover_with_usage("groq", prompt, system_prompt)
        # Bereits erkannte Key-/Kontingent-Fehler aus token_guard vor dem Live-Aufruf abfangen.
        if token_guard.is_model_exhausted(f"groq:{self.model_name}"):
            if not _allow_self_fallback:
                raise _lf._pinned_provider_failure(
                    "Groq", self.model_name,
                    RuntimeError(token_guard.get_exhausted_reason(f"groq:{self.model_name}") or "bekannt nicht verfügbar"),
                )
            return await _lf._cross_provider_failover_with_usage("groq", prompt, system_prompt)

        # Prompt-Kompression vor dem Senden wegen Groqs TPM-Limit.
        prompt, system_prompt = _compress_prompt_for_groq(prompt, system_prompt)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = await asyncio.to_thread(
                _lf._groq_client.chat.completions.create,
                model=self.model_name,
                messages=messages,
                temperature=_lf.TEMPERATURE,
                max_tokens=_lf.MAX_OUTPUT_TOKENS,
            )
            raw_text = response.choices[0].message.content or ""

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
            is_rate_limit = _lf._is_rate_limit_error(e)
            is_too_large = _lf._is_request_too_large_error(e)
            is_not_found = _lf._is_model_not_found_error(e)
            is_auth_error = _lf.is_authentication_error(e)
            if is_not_found:
                # Dauerhaft ungültiger Modellname -> langer Cooldown.
                token_guard.mark_model_exhausted(
                    f"groq:{self.model_name}", f"Groq Modell nicht gefunden (404): {_lf._short_error(e, 200)}",
                    cooldown_seconds=_lf._MODEL_NOT_FOUND_COOLDOWN_SECONDS,
                )
            elif is_rate_limit or is_too_large:
                token_guard.mark_model_exhausted(
                    f"groq:{self.model_name}", f"Groq Rate Limit/TPM: {_lf._short_error(e, 200)}",
                    cooldown_seconds=_lf._exhaustion_cooldown_seconds(str(e)),
                )
            elif is_auth_error:
                token_guard.mark_model_exhausted(
                    f"groq:{self.model_name}", f"Groq Auth-Fehler (ungültiger/abgelehnter API-Key): {_lf._short_error(e, 160)}",
                    cooldown_seconds=_lf.AUTH_FAILURE_COOLDOWN_SECONDS,
                )
            # TPM-/Größen-Fehler und 404 betreffen nur DIESES Groq-Modell: erst das nächste
            # Modell aus config.GROQ_FALLBACK_MODELS probieren, ohne Provider-Wechsel.
            if is_too_large or is_not_found:
                next_model = _lf._next_groq_fallback_model(self.model_name, _tried_groq_models)
                if next_model:
                    return await GroqClient(model_name=next_model).generate_with_usage(
                        prompt, system_prompt, _allow_self_fallback=_allow_self_fallback,
                        _tried_groq_models=_tried_groq_models | {self.model_name},
                    )
            if not _allow_self_fallback:
                if _lf._is_tool_call_json_error(e):
                    return await _lf._cross_provider_failover_with_usage("groq", prompt, system_prompt)
                if is_rate_limit or is_auth_error or is_too_large or is_not_found:
                    # Groqs eigene Modellkette (oben) ist erschöpft - schema-gleicher Ausweich-
                    # Versuch (DeepSeek/OpenRouter, siehe core/llm_factory.py P7-1), bevor endgültig
                    # aufgegeben wird.
                    try:
                        return await _lf._same_schema_failover_with_usage("groq", prompt, system_prompt)
                    except Exception:
                        raise _lf._pinned_provider_failure("Groq", self.model_name, e) from e
                raise
            return await _lf._cross_provider_failover_with_usage("groq", prompt, system_prompt)

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        res = await self.generate_with_usage(prompt, system_prompt)
        return res.text

    async def generate_with_tools(
        self, messages: list[AgentMessage], system_prompt: str | None, tools: list[dict],
        _allow_self_fallback: bool = True, _tried_groq_models: frozenset[str] = frozenset(),
    ) -> LLMResponse:
        import core.llm_factory as _lf

        if not _lf._groq_client:
            if not _allow_self_fallback:
                raise RuntimeError("Groq innerhalb einer Fallback-Kette nicht verfügbar (kein Key).")
            return await _lf._cross_provider_failover_with_tools("groq", messages, system_prompt, tools)
        if token_guard.is_model_exhausted(f"groq:{self.model_name}"):
            if not _allow_self_fallback:
                raise _lf._pinned_provider_failure(
                    "Groq", self.model_name,
                    RuntimeError(token_guard.get_exhausted_reason(f"groq:{self.model_name}") or "bekannt nicht verfügbar"),
                )
            return await _lf._cross_provider_failover_with_tools("groq", messages, system_prompt, tools)

        # Prompt-Kompression vor dem Senden (siehe _compress_messages_for_groq).
        messages, system_prompt = _compress_messages_for_groq(messages, system_prompt)

        try:
            response = await asyncio.to_thread(
                _lf._groq_client.chat.completions.create,
                model=self.model_name,
                messages=_openai_build_messages(messages, system_prompt),
                tools=_openai_build_tools(tools),
                tool_choice=openai_tool_choice(),
                temperature=_lf.TEMPERATURE,
                max_tokens=_lf.MAX_OUTPUT_TOKENS,
            )
            message = response.choices[0].message
            raw_text = message.content or ""
            clean_text = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL).strip()

            tool_calls = []
            for call in (getattr(message, "tool_calls", None) or []):
                try:
                    args = json.loads(call.function.arguments) if call.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(id=call.id, name=call.function.name, arguments=args))

            usage = getattr(response, "usage", None)
            p_tok = usage.prompt_tokens if usage else 0
            c_tok = usage.completion_tokens if usage else 0
            token_guard.record_usage(f"groq:{self.model_name}", p_tok, c_tok)

            return LLMResponse(
                text=clean_text, model_name=f"groq:{self.model_name}",
                prompt_tokens=p_tok, completion_tokens=c_tok, total_tokens=p_tok + c_tok,
                tool_calls=tool_calls,
            )
        except Exception as e:
            is_rate_limit = _lf._is_rate_limit_error(e)
            is_too_large = _lf._is_request_too_large_error(e)
            is_not_found = _lf._is_model_not_found_error(e)
            is_auth_error = _lf.is_authentication_error(e)
            if is_not_found:
                token_guard.mark_model_exhausted(
                    f"groq:{self.model_name}", f"Groq Modell nicht gefunden (404): {_lf._short_error(e, 200)}",
                    cooldown_seconds=_lf._MODEL_NOT_FOUND_COOLDOWN_SECONDS,
                )
            elif is_rate_limit or is_too_large:
                token_guard.mark_model_exhausted(
                    f"groq:{self.model_name}", f"Groq Rate Limit/TPM: {_lf._short_error(e, 200)}",
                    cooldown_seconds=_lf._exhaustion_cooldown_seconds(str(e)),
                )
            elif is_auth_error:
                token_guard.mark_model_exhausted(
                    f"groq:{self.model_name}", f"Groq Auth-Fehler (ungültiger/abgelehnter API-Key): {_lf._short_error(e, 160)}",
                    cooldown_seconds=_lf.AUTH_FAILURE_COOLDOWN_SECONDS,
                )
            # Innerhalb-Groq-Ausweichkette, wie in generate_with_usage().
            if is_too_large or is_not_found:
                next_model = _lf._next_groq_fallback_model(self.model_name, _tried_groq_models)
                if next_model:
                    return await GroqClient(model_name=next_model).generate_with_tools(
                        messages, system_prompt, tools, _allow_self_fallback=_allow_self_fallback,
                        _tried_groq_models=_tried_groq_models | {self.model_name},
                    )
            if not _allow_self_fallback:
                # Ungültiges Tool-Call-JSON: auch gepinnt failovern (siehe _TOOL_CALL_JSON_ERROR_MARKERS).
                if _lf._is_tool_call_json_error(e):
                    return await _lf._cross_provider_failover_with_tools("groq", messages, system_prompt, tools)
                if is_rate_limit or is_auth_error or is_too_large or is_not_found:
                    # Groqs eigene Modellkette (oben) ist erschöpft - schema-gleicher Ausweich-
                    # Versuch (DeepSeek/OpenRouter, siehe core/llm_factory.py P7-1), bevor endgültig
                    # aufgegeben wird.
                    try:
                        return await _lf._same_schema_failover_with_tools("groq", messages, system_prompt, tools)
                    except Exception:
                        raise _lf._pinned_provider_failure("Groq", self.model_name, e) from e
                raise
            return await _lf._cross_provider_failover_with_tools("groq", messages, system_prompt, tools)

    async def generate_json(self, prompt: str, system_prompt: str | None = None) -> str:
        json_instruction = "\n\nAntworte AUSSCHLIESSLICH mit einem gültigen JSON-Objekt, ohne Markdown-Codeblock, ohne Erklärungen davor oder danach."
        res = await self.generate_with_usage(prompt, (system_prompt or "") + json_instruction)
        return res.text
