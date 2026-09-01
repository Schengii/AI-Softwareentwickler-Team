"""
tests/test_prompt_caching.py – Tests für Prompt Caching und Token-Tracking
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm_factory import ClaudeClient, LLMResponse
from core.token_guard import TokenGuard


def test_token_guard_cache_tokens():
    guard = TokenGuard()
    guard.record_usage(
        model_name="claude-sonnet-5",
        prompt_tokens=100,
        completion_tokens=50,
        cache_read_tokens=400,
        cache_write_tokens=200,
    )
    summary = guard.get_summary()
    stat = summary["models"]["claude-sonnet-5"]
    assert stat["prompt_tokens"] == 100
    assert stat["completion_tokens"] == 50
    assert stat["total_tokens"] == 150
    assert stat["cache_read_tokens"] == 400
    assert stat["cache_write_tokens"] == 200


def test_llm_response_cache_fields():
    resp = LLMResponse(
        text="OK",
        model_name="claude-sonnet-5",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=750,
        cache_read_tokens=500,
        cache_write_tokens=100,
    )
    assert resp.cache_read_tokens == 500
    assert resp.cache_write_tokens == 100


@pytest.mark.anyio
async def test_claude_client_prompt_caching_format():
    client = ClaudeClient(model_name="claude-sonnet-5")
    mock_anthropic = MagicMock()
    client._client = mock_anthropic

    mock_usage = MagicMock(
        input_tokens=50,
        output_tokens=30,
        cache_read_input_tokens=1200,
        cache_creation_input_tokens=300,
    )
    mock_resp = MagicMock(
        content=[MagicMock(type="text", text="Cache-Antwort")],
        usage=mock_usage,
    )
    mock_anthropic.messages.create = AsyncMock(return_value=mock_resp)

    res = await client.generate_with_usage("Test Prompt", system_prompt="System Prompt Text")
    assert res.text == "Cache-Antwort"
    assert res.cache_read_tokens == 1200
    assert res.cache_write_tokens == 300
    assert res.total_tokens == 50 + 30 + 1200 + 300

    # Überprüfe, dass system prompt mit cache_control übergeben wurde
    call_kwargs = mock_anthropic.messages.create.call_args.kwargs
    assert "system" in call_kwargs
    assert call_kwargs["system"] == [
        {"type": "text", "text": "System Prompt Text", "cache_control": {"type": "ephemeral"}}
    ]
