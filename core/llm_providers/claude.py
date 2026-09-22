"""
core/llm_providers/claude.py – ClaudeClient (P6-5, ROADMAP_TEMP.md, aus core/llm_factory.py
extrahiert). Siehe core/llm_providers/groq.py-Moduldocstring für die
`import core.llm_factory as _lf; _lf.NAME`-Konvention.

`_get_shared_anthropic_client()`/`mark_claude_billing_exhausted()` und ihr Zustand
(`_shared_anthropic_client`, `_claude_billing_exhausted_reason` - Letzteres wird von
`tests/test_claude_billing_exhaustion.py` direkt über den Modulnamen `core.llm_factory`
zugewiesen) bleiben unverändert in core/llm_factory.py, aus demselben Grund wie beim
Gemini-Key-Pool (siehe core/llm_providers/gemini.py-Moduldocstring).
"""

from __future__ import annotations

from core.llm_providers._shared import AgentMessage, LLMResponse, ToolCall, tool_call_required
from core.llm_providers.deepseek import DeepSeekClient
from core.llm_providers.gemini import GeminiClient
from core.llm_providers.groq import GroqClient
from core.llm_providers.openrouter import OpenRouterClient
from core.token_guard import token_guard


class ClaudeClient:
    """Wrapper für die Anthropic Claude API mit Token-Tracking & Fallback."""

    def __init__(self, model_name: str = "claude-sonnet-5"):
        import core.llm_factory as _lf

        self.model_name = model_name
        self._client = None
        if _lf.ANTHROPIC_API_KEY:
            try:
                self._client = _lf._get_shared_anthropic_client()
            except ImportError:
                self._client = None

    @staticmethod
    def _free_heavy_fallback_client():
        """
        Ausweichstufe, wenn Claude nicht verfügbar ist: Groq, DeepSeek, OpenRouter (jeweils nur,
        wenn Key vorhanden und nicht erschöpft), zuletzt die schwächere Gemini-Standardstufe.
        """
        import core.llm_factory as _lf

        if _lf.GROQ_API_KEY and not token_guard.is_model_exhausted(_lf.GROQ_HEAVY_MODEL):
            return GroqClient(model_name=_lf.GROQ_HEAVY_MODEL)
        if _lf.DEEPSEEK_API_KEY and not token_guard.is_model_exhausted("deepseek:deepseek-chat"):
            return DeepSeekClient()
        if _lf.OPENROUTER_API_KEY and not token_guard.is_model_exhausted("openrouter:openrouter/auto"):
            return OpenRouterClient()
        return GeminiClient(model_name=_lf.GEMINI_STANDARD_MODEL)

    async def generate_with_usage(
        self, prompt: str, system_prompt: str | None = None, _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        import core.llm_factory as _lf

        if not self._client:
            if not _allow_self_fallback:
                raise RuntimeError("Claude innerhalb einer Fallback-Kette nicht verfügbar (kein ANTHROPIC_API_KEY).")
            return await self._free_heavy_fallback_client().generate_with_usage(prompt, system_prompt)
        # `self._client` existiert auch bei ungültigem Key; bereits erkannte Auth-/Limit-Fehler
        # aus token_guard vor dem nächsten, sicher scheiternden Live-Aufruf abfangen.
        if token_guard.is_model_exhausted(self.model_name):
            if not _allow_self_fallback:
                raise _lf._pinned_provider_failure(
                    "Claude", self.model_name,
                    RuntimeError(token_guard.get_exhausted_reason(self.model_name) or "bekannt nicht verfügbar"),
                )
            return await self._free_heavy_fallback_client().generate_with_usage(prompt, system_prompt)

        messages = [{"role": "user", "content": prompt}]
        kwargs: dict = {
            "model": self.model_name,
            "max_tokens": _lf.MAX_OUTPUT_TOKENS,
            "messages": messages,
        }
        if system_prompt:
            # Anthropic Prompt Caching für den System-Prompt
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        try:
            response = await self._client.messages.create(**kwargs)
            text = response.content[0].text if response.content else ""
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "input_tokens", len(prompt) // 4) if usage else len(prompt) // 4
            comp_tokens = getattr(usage, "output_tokens", len(text) // 4) if usage else len(text) // 4
            cache_read_tokens = getattr(usage, "cache_read_input_tokens", 0) or 0 if usage else 0
            cache_write_tokens = getattr(usage, "cache_creation_input_tokens", 0) or 0 if usage else 0
            total = prompt_tokens + comp_tokens + cache_read_tokens + cache_write_tokens

            token_guard.record_usage(
                self.model_name, prompt_tokens, comp_tokens,
                cache_read_tokens=cache_read_tokens, cache_write_tokens=cache_write_tokens,
            )

            return LLMResponse(
                text=text,
                model_name=self.model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=comp_tokens,
                total_tokens=total,
                cache_read_tokens=cache_read_tokens,
                cache_write_tokens=cache_write_tokens,
            )
        except Exception as e:
            is_rate_limit = _lf._is_rate_limit_error(e)
            is_auth_error = _lf.is_authentication_error(e)
            is_billing_exhausted = _lf.is_billing_exhaustion_error(e)
            if is_rate_limit:
                token_guard.mark_model_exhausted(self.model_name, "Claude Rate Limit")
            elif is_auth_error:
                token_guard.mark_model_exhausted(
                    self.model_name, f"Claude Auth-Fehler (ungültiger/abgelehnter API-Key): {_lf._short_error(e, 160)}",
                    cooldown_seconds=_lf.AUTH_FAILURE_COOLDOWN_SECONDS,
                )
            elif is_billing_exhausted:
                # 400 "API usage limits reached": weder Rate-Limit noch Auth-Fehler, gilt für alle Claude-Modelle.
                reason = f"Claude Nutzungslimit erschöpft: {_lf._short_error(e, 160)}"
                _lf.mark_claude_billing_exhausted(reason)
                token_guard.mark_model_exhausted(
                    self.model_name, reason,
                    cooldown_seconds=_lf._exhaustion_cooldown_seconds(str(e)) or _lf.BILLING_EXHAUSTION_COOLDOWN_SECONDS,
                )
            if not _allow_self_fallback:
                if is_rate_limit or is_auth_error or is_billing_exhausted:
                    raise _lf._pinned_provider_failure("Claude", self.model_name, e) from e
                raise
            return await self._free_heavy_fallback_client().generate_with_usage(prompt, system_prompt)

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        res = await self.generate_with_usage(prompt, system_prompt)
        return res.text

    async def generate_with_tools(
        self, messages: list[AgentMessage], system_prompt: str | None, tools: list[dict],
        _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        import core.llm_factory as _lf

        if not self._client:
            if not _allow_self_fallback:
                raise RuntimeError("Claude innerhalb einer Fallback-Kette nicht verfügbar (kein ANTHROPIC_API_KEY).")
            return await self._free_heavy_fallback_client().generate_with_tools(messages, system_prompt, tools)
        if token_guard.is_model_exhausted(self.model_name):
            if not _allow_self_fallback:
                raise _lf._pinned_provider_failure(
                    "Claude", self.model_name,
                    RuntimeError(token_guard.get_exhausted_reason(self.model_name) or "bekannt nicht verfügbar"),
                )
            return await self._free_heavy_fallback_client().generate_with_tools(messages, system_prompt, tools)

        anthropic_messages = self._build_anthropic_messages(messages)
        anthropic_tools = [
            {"name": t["name"], "description": t.get("description", ""), "input_schema": t.get("parameters", {"type": "object", "properties": {}})}
            for t in tools
        ]
        # Prompt Caching: Letztes Werkzeug im Katalog cachen
        if anthropic_tools:
            anthropic_tools[-1]["cache_control"] = {"type": "ephemeral"}

        kwargs: dict = {
            "model": self.model_name,
            "max_tokens": _lf.MAX_OUTPUT_TOKENS,
            "messages": anthropic_messages,
            "tools": anthropic_tools,
        }
        if anthropic_tools and tool_call_required():
            kwargs["tool_choice"] = {"type": "any"}
        if system_prompt:
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        try:
            response = await self._client.messages.create(**kwargs)
            text_parts = []
            tool_calls = []
            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input) if block.input else {}))

            usage = getattr(response, "usage", None)
            p_tok = getattr(usage, "input_tokens", 0) if usage else 0
            c_tok = getattr(usage, "output_tokens", 0) if usage else 0
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0 if usage else 0
            cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0 if usage else 0
            tot = p_tok + c_tok + cache_read + cache_write

            token_guard.record_usage(
                self.model_name, p_tok, c_tok,
                cache_read_tokens=cache_read, cache_write_tokens=cache_write,
            )

            return LLMResponse(
                text="\n".join(text_parts), model_name=self.model_name,
                prompt_tokens=p_tok, completion_tokens=c_tok, total_tokens=tot,
                cache_read_tokens=cache_read, cache_write_tokens=cache_write,
                tool_calls=tool_calls,
            )
        except Exception as e:
            is_rate_limit = _lf._is_rate_limit_error(e)
            is_auth_error = _lf.is_authentication_error(e)
            is_billing_exhausted = _lf.is_billing_exhaustion_error(e)
            if is_rate_limit:
                token_guard.mark_model_exhausted(self.model_name, "Claude Rate Limit")
            elif is_auth_error:
                token_guard.mark_model_exhausted(
                    self.model_name, f"Claude Auth-Fehler (ungültiger/abgelehnter API-Key): {_lf._short_error(e, 160)}",
                    cooldown_seconds=_lf.AUTH_FAILURE_COOLDOWN_SECONDS,
                )
            elif is_billing_exhausted:
                # Wie in generate_with_usage(): Nutzungslimit gilt für alle Claude-Modelle.
                reason = f"Claude Nutzungslimit erschöpft: {_lf._short_error(e, 160)}"
                _lf.mark_claude_billing_exhausted(reason)
                token_guard.mark_model_exhausted(
                    self.model_name, reason,
                    cooldown_seconds=_lf._exhaustion_cooldown_seconds(str(e)) or _lf.BILLING_EXHAUSTION_COOLDOWN_SECONDS,
                )
            if not _allow_self_fallback:
                if is_rate_limit or is_auth_error or is_billing_exhausted:
                    raise _lf._pinned_provider_failure("Claude", self.model_name, e) from e
                raise
            return await self._free_heavy_fallback_client().generate_with_tools(messages, system_prompt, tools)

    @staticmethod
    def _build_anthropic_messages(messages: list[AgentMessage]) -> list[dict]:
        anthropic_messages: list[dict] = []
        for msg in messages:
            if msg.role == "user":
                anthropic_messages.append({"role": "user", "content": msg.text})
            elif msg.role == "assistant":
                content = []
                if msg.text:
                    content.append({"type": "text", "text": msg.text})
                for tc in msg.tool_calls:
                    content.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
                anthropic_messages.append({"role": "assistant", "content": content})
            elif msg.role == "tool":
                anthropic_messages.append({
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": msg.tool_call_id, "content": msg.text}],
                })
        return anthropic_messages

    async def generate_json(self, prompt: str, system_prompt: str | None = None) -> str:
        json_instruction = "\n\nAntworte AUSSCHLIESSLICH mit einem gültigen JSON-Objekt, ohne Markdown-Codeblock, ohne Erklärungen davor oder danach."
        res = await self.generate_with_usage(prompt, (system_prompt or "") + json_instruction)
        return res.text
