"""
core/llm_providers/_shared.py – Provider-neutrale Bausteine, die core/llm_factory.py und alle
Provider-Module unter core/llm_providers/ gemeinsam nutzen (P6-5, ROADMAP_TEMP.md).

Enthält NUR zustandslose Dataclasses, reine Funktionen und einen intern über einen
contextvars.ContextVar gekapselten Schalter (require_tool_call()) - nichts davon wird in der
Testsuite per @patch("core.llm_factory.<name>", ...) einzeln ausgetauscht, deshalb ist eine
echte Verschiebung hierher (statt nur ein Re-Export) sicher. Veränderlicher, PER-NAME
gepatchter oder direkt zugewiesener Modul-Zustand (Gemini-Key-Rotation, Claude-Billing-Flag,
API-Keys, Client-Singletons) bleibt bewusst in core/llm_factory.py selbst - siehe die
Moduldocstrings dort und in core/llm_providers/gemini.py für die Begründung.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

_TOOL_CALL_REQUIRED: contextvars.ContextVar[bool] = contextvars.ContextVar("tool_call_required", default=False)


def tool_call_required() -> bool:
    return _TOOL_CALL_REQUIRED.get()


def openai_tool_choice() -> str:
    return "required" if tool_call_required() else "auto"


@contextlib.contextmanager
def require_tool_call(active: bool = True):
    """Erzwingt für Aufrufe innerhalb des Blocks einen Werkzeug-Aufruf (sofern `active`)."""
    token = _TOOL_CALL_REQUIRED.set(bool(active))
    try:
        yield
    finally:
        _TOOL_CALL_REQUIRED.reset(token)


@dataclass
class ToolCall:
    """Ein vom Modell angeforderter Werkzeug-Aufruf innerhalb des agentischen Loops."""
    id: str
    name: str
    arguments: dict[str, Any]
    # Gemini verlangt die thought_signature des ORIGINALEN function_call-Parts unverändert im
    # Verlauf, sonst 400 "Function call is missing a thought_signature". Nur Gemini setzt sie.
    thought_signature: bytes | None = None


@dataclass
class AgentMessage:
    """
    Provider-neutraler Konversations-Turn des Werkzeug-Loops; jeder Client übersetzt ihn nativ.

    role: "user" (Eingabe), "assistant" (Text/tool_calls), "tool" (Ergebnis, via tool_call_id).
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
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    tool_calls: list[ToolCall] = field(default_factory=list)


# ── Gemeinsame Helfer für OpenAI-kompatible Clients (Groq, DeepSeek, OpenRouter) ──

def _openai_build_messages(messages: list[AgentMessage], system_prompt: str | None) -> list[dict]:
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
