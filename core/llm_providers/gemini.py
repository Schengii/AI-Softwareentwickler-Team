"""
core/llm_providers/gemini.py – GeminiClient (P6-5, ROADMAP_TEMP.md, aus core/llm_factory.py
extrahiert). Siehe core/llm_providers/groq.py-Moduldocstring für die
`import core.llm_factory as _lf; _lf.NAME`-Konvention.

Bewusst NUR die Klasse selbst verschoben - `_get_gemini_client()`, `_mark_gemini_key_exhausted()`,
`_gemini_config_with_cache()`, `_gemini_cached_content_name()` und der gesamte Gemini-Key-Pool-
Zustand (`_gemini_active_key_index`, `_gemini_active_model`, `GEMINI_API_KEYS`,
`_gemini_clients_by_key`, `_gemini_exhausted_keys`, `_gemini_model_exhausted_keys`,
`_gemini_cache_registry`, `_gemini_cache_unsupported_models`, `_gemini_client`) bleiben
unverändert in core/llm_factory.py: `tests/conftest.py` schreibt `_gemini_active_key_index`/
`GEMINI_API_KEYS` direkt über den Modulnamen `core.llm_factory` zu, und mehrere Funktionen dort
verwenden `global` auf dieselben Namen - das funktioniert nur, solange sie in ihrem
ursprünglichen Modul bleiben (ein `global`-Statement bezieht sich immer auf das AKTUELLE Modul,
nie auf ein importiertes). GeminiClient ruft diese Funktionen deshalb über `_lf.funktionsname(...)`
auf, statt sie selbst zu besitzen.
"""

from __future__ import annotations

import asyncio
import uuid

from google.genai import types as genai_types

from config import GEMINI_STANDARD_MODEL
from core.llm_providers._shared import AgentMessage, LLMResponse, ToolCall, tool_call_required
from core.token_guard import token_guard


class GeminiClient:
    """Wrapper für die Google Gemini API."""

    def __init__(self, model_name: str = GEMINI_STANDARD_MODEL):
        self.model_name = model_name

    async def generate_with_usage(
        self, prompt: str, system_prompt: str | None = None, _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        import core.llm_factory as _lf

        config = genai_types.GenerateContentConfig(
            temperature=_lf.TEMPERATURE,
            max_output_tokens=_lf.MAX_OUTPUT_TOKENS,
            system_instruction=system_prompt if system_prompt else None,
        )
        return await self._call_with_retry_and_usage(prompt, config, _allow_self_fallback=_allow_self_fallback)

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        res = await self.generate_with_usage(prompt, system_prompt)
        return res.text

    async def generate_with_tools(
        self, messages: list[AgentMessage], system_prompt: str | None, tools: list[dict],
        _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        """
        Function-Calling-fähiger Gemini-Aufruf: liefert finalen Text oder tool_calls.

        _allow_self_fallback=False (Aufruf ist selbst ein Fallback-Hop) wirft sofort, statt
        weiterzureichen - verhindert Endlosschleifen; der Aufrufer nimmt den nächsten Kandidaten.
        """
        import core.llm_factory as _lf
        from core.llm_providers.groq import GroqClient

        if not _lf._gemini_client:
            if _lf._groq_client and _allow_self_fallback:
                groq_fallback = GroqClient(model_name="openai/gpt-oss-120b")
                return await groq_fallback.generate_with_tools(messages, system_prompt, tools, _allow_self_fallback=False)
            raise RuntimeError("Gemini Client nicht initialisiert. Bitte GEMINI_API_KEY setzen.")

        genai_tool = genai_types.Tool(function_declarations=[
            genai_types.FunctionDeclaration(
                name=t["name"],
                description=t.get("description", ""),
                parameters_json_schema=t.get("parameters", {"type": "object", "properties": {}}),
            )
            for t in tools
        ]) if tools else None

        contents = self._build_gemini_contents(messages)
        tool_config = (
            genai_types.ToolConfig(function_calling_config=genai_types.FunctionCallingConfig(mode="ANY"))
            if genai_tool and tool_call_required() else None
        )

        def _build_config(for_model: str) -> genai_types.GenerateContentConfig:
            # P5-2 (ROADMAP_TEMP.md): system_instruction UND der Werkzeugkatalog sind bei jeder
            # Iteration des Agentic-Loops identisch (nur `contents` wächst) - Best-Effort
            # explizites Gemini-Context-Caching statt sie bei jedem Aufruf erneut komplett zu
            # senden. Live an der echten API gefunden (siehe _gemini_cached_content_name()-
            # Docstring): `cached_content` verträgt sich NICHT mit gleichzeitig gesetztem
            # `system_instruction`, `tools` ODER `tool_config` im selben Request - alle drei
            # müssen deshalb, wenn ein Cache existiert, NUR im Cache-Objekt stehen und hier
            # weggelassen werden. Schlägt die Cache-Erstellung fehl, bleiben alle drei inline
            # wie vor dieser Optimierung.
            cache_name = _lf._gemini_cached_content_name(
                for_model, system_prompt, tools=[genai_tool] if genai_tool else None, tool_config=tool_config,
            )
            if cache_name:
                return genai_types.GenerateContentConfig(
                    temperature=_lf.TEMPERATURE,
                    max_output_tokens=_lf.MAX_OUTPUT_TOKENS,
                    cached_content=cache_name,
                )
            return genai_types.GenerateContentConfig(
                temperature=_lf.TEMPERATURE,
                max_output_tokens=_lf.MAX_OUTPUT_TOKENS,
                system_instruction=system_prompt if system_prompt else None,
                tools=[genai_tool] if genai_tool else None,
                tool_config=tool_config,
            )

        all_candidates = _lf._resolve_gemini_candidates(self.model_name, _allow_self_fallback)
        models_to_try = [m for m in all_candidates if _lf._provider_available(m) and not token_guard.is_model_exhausted(m)]
        if not models_to_try:
            # Ganze Kette erschöpft: kurz auf den kürzesten Cooldown warten. Kandidaten ohne Key
            # bleiben aussortiert - ein Cooldown behebt keinen fehlenden API-Key.
            wait_s = min(token_guard.seconds_until_available(all_candidates), _lf.MAX_EXHAUSTION_WAIT_SECONDS)
            if wait_s > 0:
                await asyncio.sleep(wait_s)
            # all_candidates[:1] statt self.model_name: das angeforderte Modell kann unter der
            # Mindeststufe liegen (core/model_capability.py) und wurde dann bereits aussortiert.
            models_to_try = [m for m in all_candidates if _lf._provider_available(m) and not token_guard.is_model_exhausted(m)] or all_candidates[:1]

        last_error: Exception | None = None
        chain_errors: dict[str, str] = {}
        pending = list(models_to_try)
        while pending:
            model = pending.pop(0)
            if not model.startswith("gemini"):
                # Fremd-Provider über LLMFactory delegieren, nie an die Gemini-API. Mit
                # _allow_self_fallback=False wirft er bei Scheitern -> nächster Kandidat.
                try:
                    return await _lf.LLMFactory.create_for_model(model).generate_with_tools(
                        messages, system_prompt, tools, _allow_self_fallback=False
                    )
                except Exception as e:
                    last_error = e
                    chain_errors[model] = _lf._short_error(e)
                    continue

            _lf._gemini_active_model = model
            config = await asyncio.to_thread(_build_config, model)
            for attempt in range(_lf.MAX_RETRIES):
                try:
                    await _lf._gemini_rate_limiter.acquire()
                    response = await asyncio.to_thread(
                        _lf._gemini_client.models.generate_content, model=model, contents=contents, config=config,
                    )
                    _lf._notify_model_downgrade(self.model_name, model, "Fallback-Kette (generate_with_tools)")
                    return self._parse_gemini_tool_response(response, model)
                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower()
                    is_unavailable = "503" in err_str or "UNAVAILABLE" in err_str or "high demand" in err_str.lower()
                    # Echte Quota-Erschöpfung: kein Retry, sofort unabhängiger Provider.
                    is_quota_exhausted = is_rate_limit and _lf._is_quota_exhaustion(err_str)

                    if (is_rate_limit or is_unavailable) and not is_quota_exhausted and attempt < _lf.MAX_RETRIES - 1:
                        wait = _lf.RETRY_DELAY_SECONDS * (attempt + 1) * 1.5
                        await asyncio.sleep(wait)
                        continue

                    if is_rate_limit:
                        if is_quota_exhausted:
                            _, active_key = _lf._get_gemini_client(model=model)
                            has_next_gemini_key = _lf._mark_gemini_key_exhausted(
                                active_key, cooldown_seconds=_lf._exhaustion_cooldown_seconds(err_str) or 86400.0,
                                model=model,
                            )
                            if has_next_gemini_key:
                                # Weiterer Key im Pool: dasselbe Modell sofort erneut versuchen
                                continue
                            # Alle Keys erschöpft -> Modell sperren, andere Provider vorziehen
                            token_guard.mark_model_exhausted(
                                model, "429 Quota Exceeded (alle Gemini-Keys erschöpft)", cooldown_seconds=_lf._exhaustion_cooldown_seconds(err_str),
                            )
                            pending = _lf._prefer_independent_providers(pending, failed_provider="gemini")
                        else:
                            token_guard.mark_model_exhausted(
                                model, "429 Quota Exceeded", cooldown_seconds=_lf._exhaustion_cooldown_seconds(err_str),
                            )
                    elif is_unavailable:
                        token_guard.mark_model_exhausted(model, "503 High Demand", cooldown_seconds=20.0)
                    break
            chain_errors[model] = _lf._short_error(last_error)

        raise RuntimeError(
            f"Gemini Function-Calling Fehler nach allen Fallback-Modellen ({self.model_name}): {last_error}"
            + _lf._describe_chain_failures(all_candidates, chain_errors)
        ) from last_error

    @staticmethod
    def _build_gemini_contents(messages: list[AgentMessage]) -> list:
        """Übersetzt neutrale AgentMessage-Turns in Gemini Content-Objekte."""
        contents = []
        for msg in messages:
            if msg.role == "user":
                contents.append(genai_types.Content(role="user", parts=[genai_types.Part(text=msg.text)]))
            elif msg.role == "assistant":
                parts = []
                if msg.text:
                    parts.append(genai_types.Part(text=msg.text))
                for tc in msg.tool_calls:
                    fc_part = genai_types.Part.from_function_call(name=tc.name, args=tc.arguments)
                    # thought_signature MUSS erhalten bleiben, sonst 400 INVALID_ARGUMENT (siehe ToolCall).
                    if tc.thought_signature:
                        fc_part.thought_signature = tc.thought_signature
                    parts.append(fc_part)
                contents.append(genai_types.Content(role="model", parts=parts))
            elif msg.role == "tool":
                # Gemini hat keine "tool"-Rolle: function_response geht als "user"-Content.
                contents.append(genai_types.Content(
                    role="user",
                    parts=[genai_types.Part.from_function_response(name=msg.tool_name, response={"result": msg.text})],
                ))
        return contents

    @staticmethod
    def _parse_gemini_tool_response(response, model: str) -> LLMResponse:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        candidate = response.candidates[0] if getattr(response, "candidates", None) else None
        parts = candidate.content.parts if candidate and candidate.content else []
        for part in parts or []:
            if getattr(part, "function_call", None):
                fc = part.function_call
                call_id = getattr(fc, "id", None) or str(uuid.uuid4())[:8]
                tool_calls.append(ToolCall(
                    id=call_id, name=fc.name, arguments=dict(fc.args) if fc.args else {},
                    thought_signature=getattr(part, "thought_signature", None),
                ))
            elif getattr(part, "text", None):
                text_parts.append(part.text)

        prompt_tokens = completion_tokens = total_tokens = cache_read_tokens = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            meta = response.usage_metadata
            prompt_tokens = getattr(meta, "prompt_token_count", 0) or 0
            completion_tokens = getattr(meta, "candidates_token_count", 0) or 0
            total_tokens = getattr(meta, "total_token_count", 0) or (prompt_tokens + completion_tokens)
            cache_read_tokens = getattr(meta, "cached_content_token_count", 0) or 0

        token_guard.record_usage(model, prompt_tokens, completion_tokens, cache_read_tokens=cache_read_tokens)

        return LLMResponse(
            text="\n".join(text_parts),
            model_name=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cache_read_tokens=cache_read_tokens,
            tool_calls=tool_calls,
        )

    async def _call_with_retry_and_usage(
        self,
        contents: str,
        config: genai_types.GenerateContentConfig,
        _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        import core.llm_factory as _lf
        from core.llm_providers.groq import GroqClient

        if not _lf._gemini_client:
            if _lf._groq_client and _allow_self_fallback:
                groq_fallback = GroqClient(model_name="openai/gpt-oss-120b")
                return await groq_fallback.generate_with_usage(contents, config.system_instruction, _allow_self_fallback=False)
            raise RuntimeError("Gemini Client nicht initialisiert. Bitte GEMINI_API_KEY setzen.")

        start_model = self.model_name
        all_candidates = _lf._resolve_gemini_candidates(start_model, _allow_self_fallback)
        models_to_try = [m for m in all_candidates if _lf._provider_available(m) and not token_guard.is_model_exhausted(m)]
        if not models_to_try:
            # Wie in generate_with_tools(): kurz auf den kürzesten Cooldown warten.
            wait_s = min(token_guard.seconds_until_available(all_candidates), _lf.MAX_EXHAUSTION_WAIT_SECONDS)
            if wait_s > 0:
                await asyncio.sleep(wait_s)
            models_to_try = [m for m in all_candidates if _lf._provider_available(m) and not token_guard.is_model_exhausted(m)] or all_candidates[:1]

        last_error: Exception | None = None
        chain_errors: dict[str, str] = {}
        pending = list(models_to_try)
        while pending:
            model = pending.pop(0)
            if not model.startswith("gemini"):
                # Wie in generate_with_tools(): Delegation an den Fremd-Provider ohne Self-Fallback.
                try:
                    return await _lf.LLMFactory.create_for_model(model).generate_with_usage(
                        contents, config.system_instruction, _allow_self_fallback=False
                    )
                except Exception as e:
                    last_error = e
                    chain_errors[model] = _lf._short_error(e)
                    continue

            _lf._gemini_active_model = model
            # P5-2 (ROADMAP_TEMP.md): Best-Effort Context-Caching, siehe _gemini_config_with_cache().
            # Wiederholte Aufrufe derselben Rolle (z.B. über mehrere Verifikations-Fixrunden) teilen
            # sich denselben system_instruction-Text und profitieren so ohne weiteres Zutun.
            model_config = await asyncio.to_thread(
                _lf._gemini_config_with_cache, config, model, config.system_instruction,
            )
            for attempt in range(_lf.MAX_RETRIES):
                try:
                    await _lf._gemini_rate_limiter.acquire()
                    response = await asyncio.to_thread(
                        _lf._gemini_client.models.generate_content,
                        model=model,
                        contents=contents,
                        config=model_config,
                    )
                    text = response.text or ""

                    prompt_tokens = 0
                    completion_tokens = 0
                    total_tokens = 0
                    cache_read_tokens = 0

                    if hasattr(response, "usage_metadata") and response.usage_metadata:
                        meta = response.usage_metadata
                        prompt_tokens = getattr(meta, "prompt_token_count", 0) or 0
                        completion_tokens = getattr(meta, "candidates_token_count", 0) or 0
                        total_tokens = getattr(meta, "total_token_count", 0) or (prompt_tokens + completion_tokens)
                        cache_read_tokens = getattr(meta, "cached_content_token_count", 0) or 0
                    else:
                        prompt_tokens = len(contents) // 4
                        completion_tokens = len(text) // 4
                        total_tokens = prompt_tokens + completion_tokens

                    token_guard.record_usage(model, prompt_tokens, completion_tokens, cache_read_tokens=cache_read_tokens)
                    _lf._notify_model_downgrade(start_model, model, "Fallback-Kette (generate_with_usage)")

                    return LLMResponse(
                        text=text,
                        model_name=model,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        cache_read_tokens=cache_read_tokens,
                    )

                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower()
                    is_unavailable = "503" in err_str or "UNAVAILABLE" in err_str or "high demand" in err_str.lower()
                    # Echte Quota-Erschöpfung: kein Retry, sofort unabhängiger Provider.
                    is_quota_exhausted = is_rate_limit and _lf._is_quota_exhaustion(err_str)

                    if (is_rate_limit or is_unavailable) and not is_quota_exhausted and attempt < _lf.MAX_RETRIES - 1:
                        wait = _lf.RETRY_DELAY_SECONDS * (attempt + 1) * 1.5
                        await asyncio.sleep(wait)
                        continue

                    if is_rate_limit:
                        if is_quota_exhausted:
                            _, active_key = _lf._get_gemini_client(model=model)
                            has_next_gemini_key = _lf._mark_gemini_key_exhausted(
                                active_key, cooldown_seconds=_lf._exhaustion_cooldown_seconds(err_str) or 86400.0,
                                model=model,
                            )
                            if has_next_gemini_key:
                                # Weiterer Key im Pool: dasselbe Modell sofort erneut versuchen
                                continue
                            # Alle Keys erschöpft -> Modell sperren, andere Provider vorziehen
                            token_guard.mark_model_exhausted(
                                model, "429 Quota Exceeded (alle Gemini-Keys erschöpft)", cooldown_seconds=_lf._exhaustion_cooldown_seconds(err_str),
                            )
                            pending = _lf._prefer_independent_providers(pending, failed_provider="gemini")
                        else:
                            token_guard.mark_model_exhausted(
                                model, "429 Quota Exceeded", cooldown_seconds=_lf._exhaustion_cooldown_seconds(err_str),
                            )
                    elif is_unavailable:
                        token_guard.mark_model_exhausted(model, "503 High Demand", cooldown_seconds=20.0)
                    break
            chain_errors[model] = _lf._short_error(last_error)

        raise RuntimeError(
            f"Gemini API Fehler nach allen Versuchen ({self.model_name}): {last_error}"
            + _lf._describe_chain_failures(all_candidates, chain_errors)
        ) from last_error

    async def generate_json(self, prompt: str, system_prompt: str | None = None) -> str:
        import core.llm_factory as _lf

        config = genai_types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=_lf.MAX_OUTPUT_TOKENS,
            system_instruction=system_prompt if system_prompt else None,
            response_mime_type="application/json",
        )
        res = await self._call_with_retry_and_usage(prompt, config)
        return res.text
