"""
tests/test_token_efficiency.py – Kontext-Verdichtung, deterministische Konsolidierung, sichtbare Abwertungen

Analyse 2026-09-15: ~95 % Prompt-Tokens durch erneut mitgeschickte Werkzeug-Ergebnisse, 10k-18k
Tokens je LLM-Konsolidierung eines Fachbereichsleiters, stille Modell-Abwertung pro → flash.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agents.backend_agent import BackendAgent
from agents.orchestrator import Orchestrator
from core import team_board
from core.context_compaction import compact_tool_results
from core.llm_factory import AgentMessage, LLMResponse, ToolCall
from core.message_bus import AgentResult, AgentTask


def _tool(text: str, name: str = "read_file") -> AgentMessage:
    return AgentMessage(role="tool", tool_call_id="x", tool_name=name, text=text)


def _assistant() -> AgentMessage:
    return AgentMessage(role="assistant", text="", tool_calls=[ToolCall(id="x", name="read_file", arguments={"path": "a.py"})])


class TestCompaction:
    def test_old_large_results_are_compacted_recent_ones_kept(self):
        big = json.dumps({"path": "app/main.py", "content": "x" * 5000})
        turns = [
            AgentMessage(role="user", text="Aufgabe"),
            _assistant(), _tool(big),
            _assistant(), _tool(big),
            _assistant(), _tool(big),
        ]
        stats = compact_tool_results(turns, keep_recent_rounds=2, min_chars=1500)
        assert stats.messages_compacted == 1 and stats.chars_saved > 4000
        compacted = json.loads(turns[2].text)
        assert compacted["compacted"] is True and compacted["path"] == "app/main.py"
        assert turns[4].text == big and turns[6].text == big

    def test_compaction_is_stable_and_ignores_small_results_and_assistant_messages(self):
        big = "y" * 3000
        turns = [_assistant(), _tool(big), _tool("klein"), _assistant(), _assistant()]
        compact_tool_results(turns, keep_recent_rounds=2)
        first = turns[1].text
        again = compact_tool_results(turns, keep_recent_rounds=2)
        assert again.messages_compacted == 0 and turns[1].text == first
        assert turns[2].text == "klein"
        assert turns[0].tool_calls[0].arguments == {"path": "a.py"}

    def test_nothing_happens_with_few_rounds(self):
        turns = [_assistant(), _tool("z" * 9000)]
        assert compact_tool_results(turns, keep_recent_rounds=2).messages_compacted == 0

    def test_agent_loop_sends_compacted_history_and_reports_savings(self, tmp_path):
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "big.py").write_text("# " + "a" * 6000 + "\n", encoding="utf-8")
        sent: list[list[AgentMessage]] = []

        class _LLM:
            model_name = "m"
            calls = 0

            async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
                sent.append([AgentMessage(role=m.role, text=m.text) for m in messages])
                self.calls += 1
                if self.calls <= 3:
                    return LLMResponse(text="", model_name="m", prompt_tokens=1, completion_tokens=1, total_tokens=2,
                                       tool_calls=[ToolCall(id=str(self.calls), name="read_file", arguments={"path": "app/big.py", "force": True})])
                if self.calls == 4:
                    return LLMResponse(text="", model_name="m", prompt_tokens=1, completion_tokens=1, total_tokens=2,
                                       tool_calls=[ToolCall(id="w", name="write_file", arguments={"path": "app/x.py", "content": "X = 1\n"})])
                return LLMResponse(text="Fertig.", model_name="m", prompt_tokens=1, completion_tokens=1, total_tokens=2, tool_calls=[])

        agent = BackendAgent()
        agent._llm = _LLM()
        result = asyncio.run(agent.execute(AgentTask(task_id="t", agent_id="backend", description="x",
                                                     project_dir=str(tmp_path), max_tool_iterations=8)))
        assert result.success
        assert result.context_chars_compacted > 0
        last_history = sent[-1]
        tool_texts = [m.text for m in last_history if m.role == "tool"]
        assert any('"compacted": true' in t for t in tool_texts)


@pytest.fixture
def orchestrator():
    return Orchestrator()


class TestDeterministicConsolidation:
    def test_consolidation_uses_no_llm_and_summarizes_board(self, orchestrator, tmp_path):
        lead = orchestrator._dept_leads["dev_lead"]
        lead.execute = AsyncMock(side_effect=AssertionError("kein LLM-Aufruf erwartet"))
        team_board.record_handoff(tmp_path, team_board.Handoff(
            agent_id="frontend", files=["static/index.html"], requires=["Route /api/alerts"], open_issues=["Dark Mode fehlt"],
        ))
        results = [
            AgentResult(task_id="a", agent_id="backend", agent_name="Backend", success=True, content="ok", files_written=["app/main.py"]),
            AgentResult(task_id="b", agent_id="frontend", agent_name="Frontend", success=False, content="", error="Hard Delivery Gate"),
        ]
        consolidation = asyncio.run(orchestrator._run_department_consolidation(lead, results, str(tmp_path)))
        assert consolidation.success and consolidation.total_tokens == 0
        first_line = consolidation.content.splitlines()[0]
        assert "1/2 Mitglieder erfolgreich" in first_line and "1 unerfüllte" in first_line
        assert "Hard Delivery Gate" in consolidation.content and "Dark Mode fehlt" in consolidation.content


class TestEfficiencyReporting:
    def test_downgrade_is_recorded_and_reported(self, orchestrator):
        orchestrator._begin_efficiency_tracking()
        agent = orchestrator._agents["backend"]
        agent._llm.model_name = "gemini-pro-latest"
        result = AgentResult(task_id="t", agent_id="backend", agent_name="Backend", success=True, content="", model_used="gemini-3.8-flash",
                             context_chars_compacted=8000)
        orchestrator._note_agent_call(agent, result)
        section = orchestrator._build_efficiency_section([result])
        assert "backend (gemini-pro-latest → gemini-3.8-flash)" in section
        snapshot = orchestrator._efficiency_snapshot([result])
        assert snapshot["model_downgrades"] == 1 and snapshot["downgraded_agents"] == ["backend"]
        assert snapshot["context_chars_compacted"] == 8000

    def test_same_model_and_deterministic_results_are_not_downgrades(self, orchestrator):
        orchestrator._begin_efficiency_tracking()
        agent = orchestrator._agents["backend"]
        agent._llm.model_name = "gemini-3.8-flash"
        orchestrator._note_agent_call(agent, AgentResult(task_id="t", agent_id="backend", agent_name="B", success=True, content="", model_used="gemini-3.8-flash"))
        lead = orchestrator._dept_leads["dev_lead"]
        orchestrator._note_agent_call(lead, AgentResult(task_id="t", agent_id="dev_lead", agent_name="L", success=True, content="", model_used="deterministisch"))
        assert orchestrator._efficiency_snapshot([])["model_downgrades"] == 0

    def test_run_trace_contains_efficiency_fields(self, orchestrator, tmp_path, monkeypatch):
        from core import run_logger as run_logger_module

        monkeypatch.setattr(run_logger_module, "RUN_LOGS_DIR", tmp_path / "runs")
        logger = run_logger_module.RunLogger(project_slug="p")
        orchestrator._begin_efficiency_tracking()
        logger.close(verification_ok=True, **orchestrator._efficiency_snapshot([]))
        closed = [json.loads(line) for line in Path(logger.run_log_path).read_text(encoding="utf-8").splitlines()][-1]
        assert {"cache_hit_ratio", "model_downgrades", "context_chars_compacted"} <= closed.keys()
