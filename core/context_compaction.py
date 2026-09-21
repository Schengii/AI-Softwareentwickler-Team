"""
core/context_compaction.py – Verdichtet alte Werkzeug-Ergebnisse im agentischen Loop

Die LLM-APIs sind zustandslos: jede Iteration schickt den kompletten Verlauf erneut. Analyse
2026-09-15: ~95 % aller Tokens waren Prompt-Tokens (tester: 128.649 Prompt- für 1.659
Completion-Tokens), weil Dateiinhalte aus frühen `read_file`-Aufrufen in jeder weiteren Iteration
erneut bezahlt wurden.

`compact_tool_results()` ersetzt große Werkzeug-Ergebnisse, die älter als die letzten
`keep_recent_rounds` Modell-Runden sind, durch eine kurze Vorschau mit Hinweis zum erneuten
Abruf. Ein einmal verdichteter Eintrag bleibt stabil (gleicher Text) – das hält den gecachten
Präfix für nachfolgende Iterationen konstant. Assistant-Nachrichten (inkl. Gemini
thought_signature) werden nie verändert.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

COMPACTION_MARKER = "\"compacted\": true"
PREVIEW_CHARS = 300
_READ_TOOL_NAMES = frozenset({"read_file", "search_code", "search_component_library", "list_files", "run_tests"})
_READ_TOOL_MIN_CHARS = 400


@dataclass
class CompactionStats:
    messages_compacted: int = 0
    chars_saved: int = 0


def _summary_for(tool_name: str, original: str) -> str:
    detail: dict = {}
    preview_text = original[:PREVIEW_CHARS]
    try:
        data = json.loads(original)
        if isinstance(data, dict):
            for key in ("path", "status", "error", "exit_code", "bytes_written", "total_lines"):
                if key in data:
                    detail[key] = data[key]
            if "files" in data and isinstance(data["files"], list):
                detail["files_count"] = len(data["files"])
            if tool_name == "read_file" and "path" in data:
                content = str(data.get("content", ""))
                line_count = len(content.splitlines()) if content else 0
                detail["lines_count"] = line_count
                preview_text = f"[{tool_name}: {data.get('path')} ({line_count} Zeilen, {len(content)} Zeichen)]"
    except ValueError:
        pass
    payload = {
        "compacted": True,
        "tool": tool_name,
        **detail,
        "preview": preview_text,
        "note": (
            f"Ergebnis aus einer früheren Iteration gekürzt ({len(original)} Zeichen), um Tokens zu sparen. "
            "Rufe das Werkzeug erneut auf, falls du den vollständigen Inhalt noch brauchst."
        ),
    }
    return json.dumps(payload, ensure_ascii=False)


def _extract_read_file_path(text: str) -> str | None:
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "path" in data:
            return str(data["path"])
    except ValueError:
        pass
    return None


def _stale_summary_for_read_file(path: str, original: str) -> str:
    payload = {
        "compacted": True,
        "tool": "read_file",
        "path": path,
        "stale": True,
        "note": (
            f"Veralteter Inhalt dieser Datei ({len(original)} Zeichen) ersetzt durch einen neueren "
            "Aufruf in einer späteren Runde."
        ),
    }
    return json.dumps(payload, ensure_ascii=False)


def compact_tool_results(
    turns: list,
    *,
    keep_recent_rounds: int = 2,
    min_chars: int = 800,
    deduplicate_reads: bool = False,
) -> CompactionStats:
    """Verdichtet in-place alle großen `tool`-Nachrichten vor den letzten `keep_recent_rounds` Runden.

    Ist `deduplicate_reads=True`, werden frühere `read_file`-Ergebnisse derselben Datei sofort auf
    einen schlanken Verweis reduziert, sobald die Datei in einer späteren Runde erneut gelesen wird.
    """
    stats = CompactionStats()

    if deduplicate_reads:
        last_read_indices: dict[str, int] = {}
        for i, msg in enumerate(turns):
            if getattr(msg, "role", "") == "tool" and getattr(msg, "tool_name", "") == "read_file":
                p = _extract_read_file_path(msg.text or "")
                if p:
                    last_read_indices[p] = i

        for p, last_idx in last_read_indices.items():
            for i in range(last_idx):
                msg = turns[i]
                if getattr(msg, "role", "") == "tool" and getattr(msg, "tool_name", "") == "read_file":
                    text = msg.text or ""
                    if COMPACTION_MARKER in text[:60]:
                        continue
                    if _extract_read_file_path(text) == p:
                        summary = _stale_summary_for_read_file(p, text)
                        if len(summary) < len(text):
                            stats.messages_compacted += 1
                            stats.chars_saved += len(text) - len(summary)
                            msg.text = summary

    if keep_recent_rounds < 1:
        keep_recent_rounds = 1
    assistant_indices = [i for i, msg in enumerate(turns) if getattr(msg, "role", "") == "assistant"]
    if len(assistant_indices) <= keep_recent_rounds:
        return stats
    boundary = assistant_indices[-keep_recent_rounds]
    for index in range(boundary):
        msg = turns[index]
        if getattr(msg, "role", "") != "tool":
            continue
        text = msg.text or ""
        tool_name = getattr(msg, "tool_name", "") or ""
        threshold = min(min_chars, _READ_TOOL_MIN_CHARS) if tool_name in _READ_TOOL_NAMES else min_chars
        if len(text) < threshold or COMPACTION_MARKER in text[:60]:
            continue
        summary = _summary_for(tool_name, text)
        if len(summary) >= len(text):
            continue
        stats.messages_compacted += 1
        stats.chars_saved += len(text) - len(summary)
        msg.text = summary
    return stats
