"""
core/llm_factory.py – Erstellt und verwaltet LLM-Instanzen (Gemini, Groq, DeepSeek, OpenRouter, HuggingFace & Claude)
mit präziser Token-Messung und automatischer Failover-Kette.
"""

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
from google import genai
from google.genai import types as genai_types

from config import (
    ANTHROPIC_API_KEY,
    DEEPSEEK_API_KEY,
    GEMINI_API_KEY,
    GEMINI_MAX_CALLS_PER_MINUTE,
    GROQ_API_KEY,
    GROQ_HEAVY_MODEL,
    MAX_OUTPUT_TOKENS,
    OPENROUTER_API_KEY,
    TEMPERATURE,
)
from core.rate_limiter import RateLimiter
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

# Fallback-Kette bei Ausfall / Quota-Erschöpfung: primär echtes Claude<->Gemini-Failover
# (die stärkeren Anbieter zuerst untereinander, erst danach auf eine kleinere Modellstufe
# ausweichen) – Groq/DeepSeek/OpenRouter/HuggingFace bleiben als Provider verfügbar
# (core/llm_factory.py-Clients existieren weiter), werden aber standardmäßig nicht mehr
# zugewiesen (siehe config.AGENT_MODELS) und daher hier nicht mehr als erste Wahl gelistet.
#
# Realer Fund aus einem echten End-to-End-Testlauf ohne ANTHROPIC_API_KEY: die
# STANDARD/LITE-Gemini-Ketten endeten bisher NACH dem Claude-Versuch (der ohne Schlüssel
# sofort scheitert) – ein Agent mit einer echten Gemini-Störung (nicht nur Quota, sondern
# z.B. ein Function-Calling-Fehler) hatte dann KEINE weitere Rettung mehr, obwohl Groq im
# SELBEN Lauf für andere Rollen (HEAVY-Tier, siehe GROQ_HEAVY_MODEL in config.py) einwandfrei
# funktionierte. Groq/openai/gpt-oss-120b jetzt als letzte Stufe auch in den STANDARD/LITE-
# Ketten ergänzt – kein Endlosloop möglich, da _allow_self_fallback=False verhindert, dass
# Groq bei eigenem Scheitern zurück zu Gemini zurückspringt (siehe generate_with_tools()).
MODEL_FALLBACKS = {
    # Gemini erschöpft/fehlerhaft -> auf das jeweils gleichwertige Claude-Modell ausweichen,
    # dann eine kleinere Gemini-Stufe, zuletzt Groq als kostenloser Backstop.
    "gemini-pro-latest":    ["claude-opus-5", "claude-sonnet-5", "gemini-3.6-flash"],
    "gemini-3.6-flash":     ["claude-sonnet-5", "gemini-3.1-flash-lite", "groq:openai/gpt-oss-120b"],
    "gemini-3.1-flash-lite": ["claude-haiku-4-5-20251001", "gemini-3.6-flash", "groq:openai/gpt-oss-120b"],
    # Ältere/abweichende Konfigurationswerte (falls per .env manuell gesetzt) ebenfalls abdecken.
    "gemini-3.5-flash":     ["claude-sonnet-5", "gemini-3.6-flash", "gemini-3.1-flash-lite", "groq:openai/gpt-oss-120b"],
    # Legacy-Provider-Fallbacks (nur relevant, falls ein Agent per .env explizit auf sie gesetzt wird).
    "huggingface:auto": ["gemini-3.6-flash", "gemini-3.1-flash-lite"],
    "openrouter:auto": ["gemini-3.6-flash", "gemini-3.1-flash-lite"],
    "deepseek:deepseek-chat": ["gemini-3.6-flash", "gemini-3.1-flash-lite"],
    "deepseek:deepseek-reasoner": ["deepseek:deepseek-chat", "gemini-3.6-flash"],
    "groq:openai/gpt-oss-120b": ["gemini-3.6-flash", "gemini-3.1-flash-lite"],
}

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 1.5

# Realer Fund aus einem echten Lauf: als an einem Tag alle Gemini-Kontingente gleichzeitig
# an ihrem Minutenlimit hingen (kein ANTHROPIC_API_KEY als Backstop), scheiterten praktisch
# alle Agenten sofort - jeder einzelne Aufruf kassierte denselben 429 nochmal, ohne je den
# (oft nur Sekunden entfernten) Cooldown abzuwarten. Ist die GESAMTE Fallback-Kette eines
# Aufrufs aktuell erschöpft, wird auf den kürzesten bekannten Cooldown gewartet – gedeckelt,
# damit ein Lauf dadurch nie unbegrenzt hängt.
MAX_EXHAUSTION_WAIT_SECONDS = 20.0

# Proaktive Rate-Begrenzung (core/rate_limiter.py): reduziert, WIE OFT ein Minutenlimit
# überhaupt erst erreicht wird – ergänzt MAX_EXHAUSTION_WAIT_SECONDS oben (das nur REAGIERT,
# nachdem das Limit schon erreicht ist). Realer Fund: 3+-Mitglieder-Fachbereiche schicken über
# asyncio.gather (agents/orchestrator.py) ihre erste Anfrage praktisch zeitgleich los – ohne
# Entzerrung stürmen alle Agenten gleichzeitig denselben Provider an. EINE geteilte Instanz für
# alle Gemini-Aufrufe dieses Prozesses (nicht pro Client), da sich alle dasselbe Kontingent
# teilen.
_gemini_rate_limiter = RateLimiter(max_calls=GEMINI_MAX_CALLS_PER_MINUTE, window_seconds=60.0)

# Realer Fund aus einem echten End-to-End-Lauf: governance_lead (HEAVY-Tier, kein
# ANTHROPIC_API_KEY) war innerhalb EINER Aufgabe bereits erfolgreich auf Groq gepinnt
# (siehe agents/base_agent.py active_llm), verbrauchte über mehrere Iterationen genug
# Tokens, um Groqs echtes Tageskontingent zu kippen ("tokens per day (TPD)") - und scheiterte
# dann mit dem ROHEN Groq-JSON-Fehlertext als AgentResult.error. Das Verhalten selbst (kein
# weiterer Hop zu Gemini NACH dem Pinning) ist bewusst und bleibt unverändert – ein Hop hier
# würde exakt die Provider-Historie-Korruption zurückbringen, die das Pinning verhindert
# (siehe _run_agentic_loop-Docstring). Nur die Fehlermeldung selbst war unnötig kryptisch.
_RATE_LIMIT_ERROR_MARKERS = ("429", "rate_limit", "resource_exhausted", "quota")


def _is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _RATE_LIMIT_ERROR_MARKERS)


def _pinned_provider_failure(provider_label: str, model_name: str, exc: Exception) -> Exception:
    """
    Baut eine verständliche Fehlermeldung für den Fall, dass ein bereits GEPINNTER Provider
    (kein weiterer Fallback-Hop innerhalb dieser Aufgabe mehr erlaubt, siehe
    _allow_self_fallback=False) mit einem erkennbaren Kontingent-/Rate-Limit-Fehler scheitert.
    Ersetzt NICHT die ursprüngliche Exception als Fehlerursache (siehe `raise ... from exc`),
    macht aber die für den Nutzer sichtbare AgentResult.error-Zeile sofort verständlich statt
    rohes Provider-JSON zu zeigen.
    """
    return RuntimeError(
        f"{provider_label} ({model_name}) ist für diese Aufgabe bereits fest eingeplant "
        f"und gerade nicht verfügbar (Kontingent erschöpft oder Rate-Limit erreicht) – kein "
        f"weiterer automatischer Wechsel innerhalb dieser Aufgabe, um die Konversation nicht "
        f"zu beschädigen. Kurz warten oder einen zusätzlichen API-Key ergänzen. "
        f"Rohe Provider-Meldung: {exc}"
    )


@dataclass
class ToolCall:
    """Ein vom Modell angeforderter Werkzeug-Aufruf innerhalb des agentischen Loops."""
    id: str
    name: str
    arguments: dict[str, Any]
    # Gemini verlangt bei mehrstufigem Function-Calling, dass die thought_signature des
    # ORIGINALEN function_call-Parts unverändert mitgeschickt wird, wenn dieser Aufruf als
    # Verlaufs-Nachricht in den nächsten Request eingebettet wird – sonst 400 INVALID_ARGUMENT
    # ("Function call is missing a thought_signature"). Andere Provider setzen dies nicht.
    thought_signature: bytes | None = None


@dataclass
class AgentMessage:
    """
    Ein neutraler, provider-unabhängiger Konversations-Turn für den agentischen
    Werkzeug-Loop. Wird von jedem Client-Wrapper in sein natives Nachrichtenformat
    (Gemini Content, OpenAI-Style Messages, Anthropic Messages) übersetzt.

    role:
    - "user"      – Aufgabenstellung / Werkzeug-Ergebnis wird als Folgeeingabe gesendet
    - "assistant" – Modellantwort (Text und/oder angeforderte tool_calls)
    - "tool"      – Ergebnis eines ausgeführten Werkzeug-Aufrufs (verweist per tool_call_id zurück)
    """
    role: str
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str = ""
    tool_name: str = ""


@dataclass
class LLMResponse:
    """Antwort eines LLM-Aufrufs mit Metriken."""
    text: str
    model_name: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    tool_calls: list[ToolCall] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────
# Gemeinsame Helfer für alle OpenAI-kompatiblen REST-Clients (Groq, DeepSeek,
# OpenRouter) – bauen den Nachrichtenverlauf und Tool-Katalog im OpenAI-Format
# auf und parsen die Antwort (Text ODER tool_calls) einheitlich.
# ──────────────────────────────────────────────────────────────────────────

def _openai_build_messages(messages: list["AgentMessage"], system_prompt: str | None) -> list[dict]:
    payload_messages: list[dict] = []
    if system_prompt:
        payload_messages.append({"role": "system", "content": system_prompt})

    for msg in messages:
        if msg.role == "user":
            payload_messages.append({"role": "user", "content": msg.text})
        elif msg.role == "assistant":
            entry: dict = {"role": "assistant", "content": msg.text or None}
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)},
                    }
                    for tc in msg.tool_calls
                ]
            payload_messages.append(entry)
        elif msg.role == "tool":
            payload_messages.append({"role": "tool", "tool_call_id": msg.tool_call_id, "content": msg.text})

    return payload_messages


def _openai_build_tools(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


def _openai_parse_tool_calls(message: dict) -> list[ToolCall]:
    raw_calls = message.get("tool_calls") or []
    parsed: list[ToolCall] = []
    for call in raw_calls:
        fn = call.get("function", {})
        raw_args = fn.get("arguments", "{}")
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        except json.JSONDecodeError:
            args = {}
        parsed.append(ToolCall(id=call.get("id") or str(uuid.uuid4())[:8], name=fn.get("name", ""), arguments=args))
    return parsed


class HuggingFaceClient:
    """Wrapper für Hugging Face Models & Inference mit Fallback."""

    def __init__(self, model_name: str = "huggingface:auto"):
        self.model_name = model_name

    async def generate_with_usage(
        self, prompt: str, system_prompt: str | None = None, _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        # Fallback auf Gemini für Text-/SVG-Generierung. _allow_self_fallback=False wird von
        # GeminiClient gesetzt, wenn dieser Client bereits ALS Fallback-Ziel innerhalb einer
        # Provider-Kette aufgerufen wird – verhindert eine Endlosschleife (Gemini -> HF -> Gemini
        # -> ...), falls HuggingFace irgendwann als MODEL_FALLBACKS-Ziel eingetragen wird.
        if not _allow_self_fallback:
            raise RuntimeError("HuggingFace-Provider innerhalb einer Fallback-Kette nicht verfügbar.")
        fallback = GeminiClient(model_name="gemini-3.6-flash")
        return await fallback.generate_with_usage(prompt, system_prompt)

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        res = await self.generate_with_usage(prompt, system_prompt)
        return res.text

    async def generate_with_tools(
        self, messages: list["AgentMessage"], system_prompt: str | None, tools: list[dict],
        _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        # HuggingFace-Modelle werden hier nicht mit nativem Function-Calling angebunden –
        # Fallback auf Gemini, das die Werkzeug-Schleife vollständig unterstützt.
        if not _allow_self_fallback:
            raise RuntimeError("HuggingFace-Provider innerhalb einer Fallback-Kette nicht verfügbar.")
        fallback = GeminiClient(model_name="gemini-3.6-flash")
        return await fallback.generate_with_tools(messages, system_prompt, tools)

    async def generate_json(self, prompt: str, system_prompt: str | None = None) -> str:
        fallback = GeminiClient(model_name="gemini-3.6-flash")
        return await fallback.generate_json(prompt, system_prompt)


class OpenRouterClient:
    """Wrapper für OpenRouter API (Universal Multi-Model Gateway)."""

    def __init__(self, model_name: str = "openrouter/auto"):
        self.model_name = model_name.replace("openrouter:", "")
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"

    async def generate_with_usage(
        self, prompt: str, system_prompt: str | None = None, _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        if not OPENROUTER_API_KEY or token_guard.is_model_exhausted(f"openrouter:{self.model_name}"):
            if not _allow_self_fallback:
                raise RuntimeError("OpenRouter innerhalb einer Fallback-Kette nicht verfügbar (kein Key/erschöpft).")
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
                    if not _allow_self_fallback:
                        raise RuntimeError(f"OpenRouter-Fehler innerhalb einer Fallback-Kette: {err_msg}")
                    fallback = GeminiClient(model_name="gemini-3.6-flash")
                    return await fallback.generate_with_usage(prompt, system_prompt)

        except Exception as e:
            token_guard.mark_model_exhausted(f"openrouter:{self.model_name}", str(e))
            if not _allow_self_fallback:
                raise
            fallback = GeminiClient(model_name="gemini-3.6-flash")
            return await fallback.generate_with_usage(prompt, system_prompt)

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        res = await self.generate_with_usage(prompt, system_prompt)
        return res.text

    async def generate_with_tools(
        self, messages: list["AgentMessage"], system_prompt: str | None, tools: list[dict],
        _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        if not OPENROUTER_API_KEY or token_guard.is_model_exhausted(f"openrouter:{self.model_name}"):
            if not _allow_self_fallback:
                raise RuntimeError("OpenRouter innerhalb einer Fallback-Kette nicht verfügbar (kein Key/erschöpft).")
            fallback = GeminiClient(model_name="gemini-3.6-flash")
            return await fallback.generate_with_tools(messages, system_prompt, tools)

        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": "https://github.com/Schengii/AI-Softwareentwickler-Team",
            "X-Title": "AI Developer Team",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model_name if self.model_name != "auto" else "google/gemini-2.5-flash",
            "messages": _openai_build_messages(messages, system_prompt),
            "tools": _openai_build_tools(tools),
            "tool_choice": "auto",
            "temperature": TEMPERATURE,
            "max_tokens": MAX_OUTPUT_TOKENS,
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
                    token_guard.record_usage(f"openrouter:{self.model_name}", p_tok, c_tok)

                    return LLMResponse(
                        text=message.get("content") or "",
                        model_name=f"openrouter:{self.model_name}",
                        prompt_tokens=p_tok,
                        completion_tokens=c_tok,
                        total_tokens=usage.get("total_tokens", p_tok + c_tok),
                        tool_calls=_openai_parse_tool_calls(message),
                    )

                err_msg = data.get("error", {}).get("message", "OpenRouter API Error")
                if response.status_code in (401, 402, 429) or "balance" in err_msg.lower() or "limit" in err_msg.lower():
                    token_guard.mark_model_exhausted(f"openrouter:{self.model_name}", f"OpenRouter: {err_msg}")
                if not _allow_self_fallback:
                    raise RuntimeError(f"OpenRouter-Fehler innerhalb einer Fallback-Kette: {err_msg}")
                fallback = GeminiClient(model_name="gemini-3.6-flash")
                return await fallback.generate_with_tools(messages, system_prompt, tools)

        except Exception as e:
            token_guard.mark_model_exhausted(f"openrouter:{self.model_name}", str(e))
            if not _allow_self_fallback:
                raise
            fallback = GeminiClient(model_name="gemini-3.6-flash")
            return await fallback.generate_with_tools(messages, system_prompt, tools)

    async def generate_json(self, prompt: str, system_prompt: str | None = None) -> str:
        json_instruction = "\n\nAntworte AUSSCHLIESSLICH mit einem gültigen JSON-Objekt, ohne Markdown-Codeblock, ohne Erklärungen davor oder danach."
        res = await self.generate_with_usage(prompt, (system_prompt or "") + json_instruction)
        return res.text


class DeepSeekClient:
    """Wrapper für die DeepSeek API (OpenAI-kompatibel via REST)."""

    def __init__(self, model_name: str = "deepseek-chat"):
        self.model_name = model_name.replace("deepseek:", "")
        self.api_url = "https://api.deepseek.com/chat/completions"

    async def generate_with_usage(
        self, prompt: str, system_prompt: str | None = None, _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        if not DEEPSEEK_API_KEY or token_guard.is_model_exhausted(f"deepseek:{self.model_name}"):
            if not _allow_self_fallback:
                raise RuntimeError("DeepSeek innerhalb einer Fallback-Kette nicht verfügbar (kein Key/erschöpft).")
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
                    if not _allow_self_fallback:
                        raise RuntimeError(f"DeepSeek-Fehler innerhalb einer Fallback-Kette: {err_msg}")
                    fallback = GeminiClient(model_name="gemini-3.6-flash")
                    return await fallback.generate_with_usage(prompt, system_prompt)

        except Exception as e:
            token_guard.mark_model_exhausted(f"deepseek:{self.model_name}", str(e))
            if not _allow_self_fallback:
                raise
            fallback = GeminiClient(model_name="gemini-3.6-flash")
            return await fallback.generate_with_usage(prompt, system_prompt)

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        res = await self.generate_with_usage(prompt, system_prompt)
        return res.text

    async def generate_with_tools(
        self, messages: list["AgentMessage"], system_prompt: str | None, tools: list[dict],
        _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        if not DEEPSEEK_API_KEY or token_guard.is_model_exhausted(f"deepseek:{self.model_name}"):
            if not _allow_self_fallback:
                raise RuntimeError("DeepSeek innerhalb einer Fallback-Kette nicht verfügbar (kein Key/erschöpft).")
            fallback = GeminiClient(model_name="gemini-3.6-flash")
            return await fallback.generate_with_tools(messages, system_prompt, tools)

        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": self.model_name,
            "messages": _openai_build_messages(messages, system_prompt),
            "tools": _openai_build_tools(tools),
            "tool_choice": "auto",
            "temperature": TEMPERATURE,
            "max_tokens": MAX_OUTPUT_TOKENS,
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
                    token_guard.mark_model_exhausted(f"deepseek:{self.model_name}", f"DeepSeek: {err_msg}")
                if not _allow_self_fallback:
                    raise RuntimeError(f"DeepSeek-Fehler innerhalb einer Fallback-Kette: {err_msg}")
                fallback = GeminiClient(model_name="gemini-3.6-flash")
                return await fallback.generate_with_tools(messages, system_prompt, tools)

        except Exception as e:
            token_guard.mark_model_exhausted(f"deepseek:{self.model_name}", str(e))
            if not _allow_self_fallback:
                raise
            fallback = GeminiClient(model_name="gemini-3.6-flash")
            return await fallback.generate_with_tools(messages, system_prompt, tools)

    async def generate_json(self, prompt: str, system_prompt: str | None = None) -> str:
        json_instruction = "\n\nAntworte AUSSCHLIESSLICH mit einem gültigen JSON-Objekt, ohne Markdown-Codeblock, ohne Erklärungen davor oder danach."
        res = await self.generate_with_usage(prompt, (system_prompt or "") + json_instruction)
        return res.text


class GeminiClient:
    """Wrapper für die Google Gemini API."""

    def __init__(self, model_name: str = "gemini-3.6-flash"):
        self.model_name = model_name

    async def generate_with_usage(
        self, prompt: str, system_prompt: str | None = None, _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        config = genai_types.GenerateContentConfig(
            temperature=TEMPERATURE,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            system_instruction=system_prompt if system_prompt else None,
        )
        return await self._call_with_retry_and_usage(prompt, config, _allow_self_fallback=_allow_self_fallback)

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        res = await self.generate_with_usage(prompt, system_prompt)
        return res.text

    async def generate_with_tools(
        self, messages: list["AgentMessage"], system_prompt: str | None, tools: list[dict],
        _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        """
        Führt einen Function-Calling-fähigen Gemini-Aufruf aus. Gibt entweder finalen
        Text (response.tool_calls == []) oder angeforderte Werkzeug-Aufrufe zurück,
        die der Aufrufer ausführen und per Folge-Message zurückspielen muss.

        _allow_self_fallback=False wird gesetzt, wenn DIESER Aufruf bereits selbst ein
        Fallback-Hop innerhalb einer Provider-Kette ist (siehe unten) – verhindert eine
        Endlosschleife der Form Gemini -> Claude (kein Key) -> Gemini -> Claude -> ...,
        indem hier dann sofort ein Fehler geworfen wird, statt selbst weiterzureichen.
        Der AUFRUFER (die models_to_try-Schleife, die diesen Hop ausgelöst hat) fängt
        den Fehler ab und versucht stattdessen den nächsten Kandidaten der Kette.
        """
        if not _gemini_client:
            if _groq_client and _allow_self_fallback:
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
        config = genai_types.GenerateContentConfig(
            temperature=TEMPERATURE,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            system_instruction=system_prompt if system_prompt else None,
            tools=[genai_tool] if genai_tool else None,
        )

        all_candidates = [self.model_name] + MODEL_FALLBACKS.get(self.model_name, [])
        models_to_try = [m for m in all_candidates if not token_guard.is_model_exhausted(m)]
        if not models_to_try:
            # Komplette Kette gerade erschöpft (siehe MAX_EXHAUSTION_WAIT_SECONDS oben) -
            # kurz auf den kürzesten bekannten Cooldown warten statt sofort denselben
            # Fehler erneut zu kassieren.
            wait_s = min(token_guard.seconds_until_available(all_candidates), MAX_EXHAUSTION_WAIT_SECONDS)
            if wait_s > 0:
                await asyncio.sleep(wait_s)
            models_to_try = [m for m in all_candidates if not token_guard.is_model_exhausted(m)] or [self.model_name]

        last_error: Exception | None = None
        for model in models_to_try:
            if not model.startswith("gemini"):
                # Nicht-Gemini-Fallback-Ziel (Claude/Groq/DeepSeek/OpenRouter/HuggingFace) an den
                # passenden Provider-Client delegieren – zentral über LLMFactory, damit hier NIE
                # versehentlich ein Fremd-Modellname direkt an die Gemini-API durchgereicht wird
                # (das würde 400/404 werfen und die Fallback-Kette bis zur letzten Gemini-Stufe
                # durchreichen, ohne den eigentlich vorgesehenen Provider je zu erreichen).
                # _allow_self_fallback=False: dieser Provider darf bei eigenem Scheitern NICHT
                # selbst wieder zu Gemini zurückspringen (Endlosschleife) – stattdessen fliegt
                # eine Exception, die wir hier abfangen und zum nächsten Kandidaten weiterziehen.
                try:
                    return await LLMFactory.create_for_model(model).generate_with_tools(
                        messages, system_prompt, tools, _allow_self_fallback=False
                    )
                except Exception as e:
                    last_error = e
                    continue

            try:
                await _gemini_rate_limiter.acquire()
                response = await asyncio.to_thread(
                    _gemini_client.models.generate_content, model=model, contents=contents, config=config,
                )
                return self._parse_gemini_tool_response(response, model)
            except Exception as e:
                last_error = e
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "Quota" in err_str:
                    token_guard.mark_model_exhausted(model, "429 Quota Exceeded")
                continue

        raise RuntimeError(f"Gemini Function-Calling Fehler nach allen Fallback-Modellen ({self.model_name}): {last_error}") from last_error

    @staticmethod
    def _build_gemini_contents(messages: list["AgentMessage"]) -> list:
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
                    # thought_signature MUSS beim Zurückspielen erhalten bleiben (siehe ToolCall-Feld oben),
                    # sonst lehnt Gemini den Folgeaufruf mit 400 INVALID_ARGUMENT ab.
                    if tc.thought_signature:
                        fc_part.thought_signature = tc.thought_signature
                    parts.append(fc_part)
                contents.append(genai_types.Content(role="model", parts=parts))
            elif msg.role == "tool":
                # Gemini kennt keine eigene "tool"-Rolle in Content – die Funktionsantwort
                # wird als "user"-Content mit einem function_response-Part gesendet.
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

        prompt_tokens = completion_tokens = total_tokens = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            meta = response.usage_metadata
            prompt_tokens = getattr(meta, "prompt_token_count", 0) or 0
            completion_tokens = getattr(meta, "candidates_token_count", 0) or 0
            total_tokens = getattr(meta, "total_token_count", 0) or (prompt_tokens + completion_tokens)

        token_guard.record_usage(model, prompt_tokens, completion_tokens)

        return LLMResponse(
            text="\n".join(text_parts),
            model_name=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            tool_calls=tool_calls,
        )

    async def _call_with_retry_and_usage(
        self,
        contents: str,
        config: genai_types.GenerateContentConfig,
        _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        if not _gemini_client:
            if _groq_client and _allow_self_fallback:
                groq_fallback = GroqClient(model_name="openai/gpt-oss-120b")
                return await groq_fallback.generate_with_usage(contents, config.system_instruction, _allow_self_fallback=False)
            raise RuntimeError("Gemini Client nicht initialisiert. Bitte GEMINI_API_KEY setzen.")

        start_model = self.model_name
        all_candidates = [start_model] + MODEL_FALLBACKS.get(start_model, [])
        models_to_try = [m for m in all_candidates if not token_guard.is_model_exhausted(m)]
        if not models_to_try:
            # Siehe generate_with_tools() weiter oben: kurz auf den kürzesten bekannten
            # Cooldown warten, statt sofort denselben Fehler erneut zu kassieren.
            wait_s = min(token_guard.seconds_until_available(all_candidates), MAX_EXHAUSTION_WAIT_SECONDS)
            if wait_s > 0:
                await asyncio.sleep(wait_s)
            models_to_try = [m for m in all_candidates if not token_guard.is_model_exhausted(m)] or [start_model]

        last_error: Exception | None = None
        for model in models_to_try:
            if not model.startswith("gemini"):
                # Siehe generate_with_tools() weiter oben: zentrale Provider-Delegation statt
                # eines Fremd-Modellnamens, der sonst versehentlich an die Gemini-API ginge.
                # _allow_self_fallback=False verhindert eine Endlosschleife, falls dieser Provider
                # ebenfalls scheitert (dann Exception -> hier abgefangen -> nächster Kandidat).
                try:
                    return await LLMFactory.create_for_model(model).generate_with_usage(
                        contents, config.system_instruction, _allow_self_fallback=False
                    )
                except Exception as e:
                    last_error = e
                    continue

            for attempt in range(MAX_RETRIES):
                try:
                    await _gemini_rate_limiter.acquire()
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

    async def generate_json(self, prompt: str, system_prompt: str | None = None) -> str:
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
        self, prompt: str, system_prompt: str | None = None, _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        if not _groq_client:
            if not _allow_self_fallback:
                raise RuntimeError("Groq innerhalb einer Fallback-Kette nicht verfügbar (kein Key).")
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
            is_rate_limit = _is_rate_limit_error(e)
            if is_rate_limit:
                token_guard.mark_model_exhausted(f"groq:{self.model_name}", "Groq Rate Limit")
            if not _allow_self_fallback:
                if is_rate_limit:
                    raise _pinned_provider_failure("Groq", self.model_name, e) from e
                raise
            gemini_fallback = GeminiClient(model_name="gemini-3.6-flash")
            return await gemini_fallback.generate_with_usage(prompt, system_prompt)

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        res = await self.generate_with_usage(prompt, system_prompt)
        return res.text

    async def generate_with_tools(
        self, messages: list["AgentMessage"], system_prompt: str | None, tools: list[dict],
        _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        if not _groq_client:
            if not _allow_self_fallback:
                raise RuntimeError("Groq innerhalb einer Fallback-Kette nicht verfügbar (kein Key).")
            gemini_fallback = GeminiClient(model_name="gemini-3.6-flash")
            return await gemini_fallback.generate_with_tools(messages, system_prompt, tools)

        try:
            response = await asyncio.to_thread(
                _groq_client.chat.completions.create,
                model=self.model_name,
                messages=_openai_build_messages(messages, system_prompt),
                tools=_openai_build_tools(tools),
                tool_choice="auto",
                temperature=TEMPERATURE,
                max_tokens=MAX_OUTPUT_TOKENS,
            )
            message = response.choices[0].message
            raw_text = message.content or ""
            import re
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
            is_rate_limit = _is_rate_limit_error(e)
            if is_rate_limit:
                token_guard.mark_model_exhausted(f"groq:{self.model_name}", "Groq Rate Limit")
            if not _allow_self_fallback:
                if is_rate_limit:
                    raise _pinned_provider_failure("Groq", self.model_name, e) from e
                raise
            gemini_fallback = GeminiClient(model_name="gemini-3.6-flash")
            return await gemini_fallback.generate_with_tools(messages, system_prompt, tools)

    async def generate_json(self, prompt: str, system_prompt: str | None = None) -> str:
        json_instruction = "\n\nAntworte AUSSCHLIESSLICH mit einem gültigen JSON-Objekt, ohne Markdown-Codeblock, ohne Erklärungen davor oder danach."
        res = await self.generate_with_usage(prompt, (system_prompt or "") + json_instruction)
        return res.text


class ClaudeClient:
    """Wrapper für die Anthropic Claude API mit Token-Tracking & Fallback."""

    def __init__(self, model_name: str = "claude-sonnet-5"):
        self.model_name = model_name
        self._client = None
        if ANTHROPIC_API_KEY:
            try:
                import anthropic
                self._client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            except ImportError:
                self._client = None

    @staticmethod
    def _free_heavy_fallback_client():
        """
        Kostenlose Ausweichstufe, wenn Claude nicht verfügbar ist (kein ANTHROPIC_API_KEY
        oder Fehler): Anthropic bietet – anders als Gemini – kein dauerhaftes Gratis-Kontingent.
        Bevorzugt daher Groq (echtes, kostenloses Rate-Limit-Kontingent mit einem starken
        Open-Weight-Modell) statt direkt auf die schwächere Gemini-Standardstufe abzurutschen.
        """
        if GROQ_API_KEY:
            return GroqClient(model_name=GROQ_HEAVY_MODEL)
        return GeminiClient(model_name="gemini-3.6-flash")

    async def generate_with_usage(
        self, prompt: str, system_prompt: str | None = None, _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        if not self._client:
            if not _allow_self_fallback:
                raise RuntimeError("Claude innerhalb einer Fallback-Kette nicht verfügbar (kein ANTHROPIC_API_KEY).")
            return await self._free_heavy_fallback_client().generate_with_usage(prompt, system_prompt)

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
            is_rate_limit = _is_rate_limit_error(e)
            if is_rate_limit:
                token_guard.mark_model_exhausted(self.model_name, "Claude Rate Limit")
            if not _allow_self_fallback:
                if is_rate_limit:
                    raise _pinned_provider_failure("Claude", self.model_name, e) from e
                raise
            return await self._free_heavy_fallback_client().generate_with_usage(prompt, system_prompt)

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        res = await self.generate_with_usage(prompt, system_prompt)
        return res.text

    async def generate_with_tools(
        self, messages: list["AgentMessage"], system_prompt: str | None, tools: list[dict],
        _allow_self_fallback: bool = True,
    ) -> LLMResponse:
        if not self._client:
            if not _allow_self_fallback:
                raise RuntimeError("Claude innerhalb einer Fallback-Kette nicht verfügbar (kein ANTHROPIC_API_KEY).")
            return await self._free_heavy_fallback_client().generate_with_tools(messages, system_prompt, tools)

        anthropic_messages = self._build_anthropic_messages(messages)
        anthropic_tools = [
            {"name": t["name"], "description": t.get("description", ""), "input_schema": t.get("parameters", {"type": "object", "properties": {}})}
            for t in tools
        ]

        kwargs: dict = {
            "model": self.model_name,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "messages": anthropic_messages,
            "tools": anthropic_tools,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        try:
            response = await self._client.messages.create(**kwargs)
            text_parts = []
            tool_calls = []
            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input) if block.input else {}))

            p_tok = response.usage.input_tokens if hasattr(response, "usage") else 0
            c_tok = response.usage.output_tokens if hasattr(response, "usage") else 0
            token_guard.record_usage(self.model_name, p_tok, c_tok)

            return LLMResponse(
                text="\n".join(text_parts), model_name=self.model_name,
                prompt_tokens=p_tok, completion_tokens=c_tok, total_tokens=p_tok + c_tok,
                tool_calls=tool_calls,
            )
        except Exception as e:
            is_rate_limit = _is_rate_limit_error(e)
            if is_rate_limit:
                token_guard.mark_model_exhausted(self.model_name, "Claude Rate Limit")
            if not _allow_self_fallback:
                if is_rate_limit:
                    raise _pinned_provider_failure("Claude", self.model_name, e) from e
                raise
            return await self._free_heavy_fallback_client().generate_with_tools(messages, system_prompt, tools)

    @staticmethod
    def _build_anthropic_messages(messages: list["AgentMessage"]) -> list[dict]:
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
    def create_claude(model_name: str = "claude-sonnet-5") -> ClaudeClient:
        return ClaudeClient(model_name=model_name)

    @staticmethod
    def create_for_model(model_name: str):
        """
        Erkennt anhand des Modellnamens den richtigen Provider-Client. Zentrale Stelle,
        damit ein beliebiger konfigurierter Modellname (Gemini ODER Claude ODER ein
        Legacy-Provider) immer beim passenden Client landet – unabhängig davon, ob er
        über config.AGENT_MODELS (create_for_agent) oder direkt (z.B. ORCHESTRATOR_MODEL
        für TaskManager/ResultAggregator) übergeben wird.
        """
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

    @staticmethod
    def create_for_agent(agent_id: str):
        from config import AGENT_MODELS, DEFAULT_AGENT_MODEL
        model_name = AGENT_MODELS.get(agent_id, DEFAULT_AGENT_MODEL)
        return LLMFactory.create_for_model(model_name)
