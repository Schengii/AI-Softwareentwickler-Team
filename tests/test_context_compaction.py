"""
tests/test_context_compaction.py - Deckt die Terminal-/Pytest-Ausgaben-Kürzung in
core/context_compaction.py ab (Team-Aufgabe "Token-Effizienz-/Budget-Flexibilisierung",
2026-09-22, Punkt 2): grosse `run_tests`/`run_command`-Ergebnisse aus früheren Iterationen
sollen auf die tatsächlich relevanten Fehlerzeilen (Traceback/FAILED/ERROR) gekürzt werden,
statt nur auf einen reinen Zeichen-Preview - die allgemeine Verdichtungs-/Dedup-Logik selbst
ist bereits durch tests/test_token_efficiency.py::TestCompaction abgedeckt.
"""

from __future__ import annotations

import json

from core.context_compaction import compact_tool_results
from core.llm_factory import AgentMessage, ToolCall


def _tool(text: str, name: str) -> AgentMessage:
    return AgentMessage(role="tool", tool_call_id="x", tool_name=name, text=text)


def _assistant() -> AgentMessage:
    return AgentMessage(role="assistant", text="", tool_calls=[ToolCall(id="x", name="run_tests", arguments={})])


def _big_pytest_output() -> str:
    noise = "\n".join(f"collecting... item_{i}.py" for i in range(200))
    failure = (
        "Traceback (most recent call last):\n"
        '  File "app/main.py", line 42, in handler\n'
        "    return foo(bar)\n"
        "AssertionError: expected 200, got 500\n"
        "FAILED tests/test_main.py::test_handler - AssertionError: expected 200, got 500"
    )
    return noise + "\n" + failure + "\n" + noise


class TestTerminalOutputTrimming:
    def test_old_run_tests_result_is_trimmed_to_error_lines(self):
        big = json.dumps({"exit_code": 1, "stdout": _big_pytest_output(), "stderr": ""})
        turns = [
            AgentMessage(role="user", text="Aufgabe"),
            _assistant(), _tool(big, name="run_tests"),
            _assistant(), _tool(big, name="run_tests"),
            _assistant(), _tool(big, name="run_tests"),
        ]
        stats = compact_tool_results(turns, keep_recent_rounds=2, min_chars=200)
        assert stats.messages_compacted == 1
        compacted = json.loads(turns[2].text)
        assert compacted["compacted"] is True
        assert "AssertionError: expected 200, got 500" in compacted["error_lines"]
        assert "FAILED tests/test_main.py::test_handler" in compacted["error_lines"]
        # Das Rauschen (Sammel-Zeilen) darf nicht mehr enthalten sein.
        assert "collecting... item_" not in compacted["error_lines"]
        # Deutlich kleiner als das Original.
        assert len(turns[2].text) < len(big) / 2
        # Die zwei jüngsten Aufrufe bleiben unverändert (voller Kontext für die aktuelle Iteration).
        assert turns[4].text == big and turns[6].text == big

    def test_old_run_command_result_is_trimmed(self):
        big = json.dumps({"exit_code": 1, "stdout": "", "stderr": _big_pytest_output()})
        turns = [
            _assistant(), _tool(big, name="run_command"),
            _assistant(), _tool(big, name="run_command"),
            _assistant(), _tool(big, name="run_command"),
        ]
        stats = compact_tool_results(turns, keep_recent_rounds=2, min_chars=200)
        assert stats.messages_compacted == 1
        compacted = json.loads(turns[1].text)
        assert compacted["compacted"] is True
        assert "AssertionError" in compacted["error_lines"]
        assert turns[3].text == big and turns[5].text == big

    def test_clean_passing_output_has_no_error_lines_but_still_compacts(self):
        clean_stdout = "\n".join(f"test_{i} PASSED" for i in range(300))
        big = json.dumps({"exit_code": 0, "stdout": clean_stdout, "stderr": ""})
        turns = [
            _assistant(), _tool(big, name="run_tests"),
            _assistant(), _tool(big, name="run_tests"),
            _assistant(), _tool(big, name="run_tests"),
        ]
        stats = compact_tool_results(turns, keep_recent_rounds=2, min_chars=200)
        assert stats.messages_compacted == 1
        compacted = json.loads(turns[1].text)
        assert compacted["compacted"] is True
        assert "error_lines" not in compacted

    def test_recent_run_tests_result_within_window_stays_full(self):
        big = json.dumps({"exit_code": 1, "stdout": _big_pytest_output(), "stderr": ""})
        turns = [_assistant(), _tool(big, name="run_tests")]
        stats = compact_tool_results(turns, keep_recent_rounds=2, min_chars=200)
        assert stats.messages_compacted == 0
        assert turns[1].text == big
