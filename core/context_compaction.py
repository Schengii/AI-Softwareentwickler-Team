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


@dataclass
class CompactionStats:
    messages_compacted: int = 0
    chars_saved: int = 0


def _summary_for(tool_name: str, original: str) -> str:
    detail: dict = {}
    try:
        data = json.loads(original)
        if isinstance(data, dict):
            for key in ("path", "status", "error", "exit_code", "bytes_written", "total_lines"):
                if key in data:
                    detail[key] = data[key]
            if "files" in data and isinstance(data["files"], list):
                detail["files_count"] = len(data["files"])
    except ValueError:
        pass
    payload = {
        "compacted": True,
        "tool": tool_name,
        **detail,
        "preview": original[:PREVIEW_CHARS],
        "note": (
            f"Ergebnis aus einer früheren Iteration gekürzt ({len(original)} Zeichen), um Tokens zu sparen. "
            "Rufe das Werkzeug erneut auf, falls du den vollständigen Inhalt noch brauchst."
        ),
    }
    return json.dumps(payload, ensure_ascii=False)


def compact_tool_results(turns: list, *, keep_recent_rounds: int = 2, min_chars: int = 1500) -> CompactionStats:
    """Verdichtet in-place alle großen `tool`-Nachrichten vor den letzten `keep_recent_rounds` Runden."""
    stats = CompactionStats()
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
        if len(text) < min_chars or COMPACTION_MARKER in text[:60]:
            continue
        summary = _summary_for(getattr(msg, "tool_name", "") or "", text)
        if len(summary) >= len(text):
            continue
        stats.messages_compacted += 1
        stats.chars_saved += len(text) - len(summary)
        msg.text = summary
    return stats
