"""
core/run_trace.py – Projektlokales, versioniertes Lauf-Protokoll unter `<projekt>/.ai_team_runs/`.

`core/run_logger.py` schreibt das vollständige Lauf-Log nach `logs/` im Framework-Verzeichnis -
das ist gitignored und damit auf jedem anderen Rechner (CI, Backlog-Worker) verloren.
`.ai_team_decisions.jsonl` enthielt bei fehlgeschlagenen Läufen oft nur einen einzigen Eintrag,
und `.ai_team_status.json` kappt Verifikations-Protokolle auf 500 Zeichen mitten im Satz.

Dieses Modul legt pro Lauf im Projektordner ab:
- `<stamp>_trace.jsonl`: Phasen, Agenten-Aufrufe (Tokens, Werkzeugaufrufe, Dateien, Ergebnis)
- `<stamp>_verification.md`: das VOLLSTÄNDIGE Verifikationsprotokoll inkl. strukturiertem
  Ergebnis je Prüfung

`summarize_trace()` verdichtet ein Trace zu Kennzahlen pro Phase/Agent - die Grundlage für
Root-Cause-Analyse, Team-Retrospektive und Modell-Routing.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RUNS_DIRNAME = ".ai_team_runs"
MAX_RUN_ARTIFACTS_KEPT = 20
_TRACE_SUFFIX = "_trace.jsonl"
_VERIFICATION_SUFFIX = "_verification.md"

logger = logging.getLogger(__name__)


def runs_dir(project_dir: str | Path) -> Path:
    return Path(project_dir) / RUNS_DIRNAME


def run_stamp(moment: datetime | None = None) -> str:
    return (moment or datetime.now(UTC)).strftime("%Y%m%d_%H%M%S")


def trace_path(project_dir: str | Path, stamp: str) -> Path:
    return runs_dir(project_dir) / f"{stamp}{_TRACE_SUFFIX}"


def append_trace_event(path: Path, record: dict[str, Any]) -> None:
    """Hängt ein Ereignis an. Fehler werden geloggt, nie geworfen (Protokoll ist additiv)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except (OSError, TypeError, ValueError) as e:
        logger.warning("Projekt-Trace konnte nicht geschrieben werden (%s): %r", path, e)


def write_verification_protocol(
    project_dir: str | Path,
    summary: str,
    outcome: dict | None = None,
    stamp: str | None = None,
) -> str | None:
    """Schreibt das ungekürzte Verifikationsprotokoll. Gibt den projektrelativen Pfad zurück."""
    if not (summary or "").strip():
        return None
    stamp = stamp or run_stamp()
    target = runs_dir(project_dir) / f"{stamp}{_VERIFICATION_SUFFIX}"
    parts = [summary.strip(), ""]
    if outcome:
        parts += ["### Strukturiertes Ergebnis", "", "```json", json.dumps(outcome, indent=2, ensure_ascii=False), "```", ""]
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(parts), encoding="utf-8")
    except OSError as e:
        logger.warning("Verifikationsprotokoll konnte nicht geschrieben werden (%s): %r", target, e)
        return None
    prune_run_artifacts(project_dir)
    return f"{RUNS_DIRNAME}/{target.name}"


def read_run_artifact(project_dir: str | Path, relative_path: str) -> str:
    """Liest ein Protokoll über seinen projektrelativen Pfad (leer bei Fehler/Pfad außerhalb)."""
    if not relative_path:
        return ""
    base = runs_dir(project_dir).resolve()
    candidate = (Path(project_dir) / relative_path).resolve()
    if base not in candidate.parents:
        return ""
    try:
        return candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def prune_run_artifacts(project_dir: str | Path, keep: int = MAX_RUN_ARTIFACTS_KEPT) -> int:
    """Behält je Artefakt-Art nur die `keep` jüngsten Dateien. Gibt die Anzahl gelöschter zurück."""
    directory = runs_dir(project_dir)
    if not directory.is_dir():
        return 0
    removed = 0
    for suffix in (_TRACE_SUFFIX, _VERIFICATION_SUFFIX):
        files = sorted(directory.glob(f"*{suffix}"), key=lambda p: p.name, reverse=True)
        for old in files[keep:]:
            try:
                old.unlink()
                removed += 1
            except OSError:
                continue
    return removed


def latest_trace(project_dir: str | Path) -> Path | None:
    directory = runs_dir(project_dir)
    if not directory.is_dir():
        return None
    traces = sorted(directory.glob(f"*{_TRACE_SUFFIX}"), key=lambda p: p.name)
    return traces[-1] if traces else None


def summarize_trace(path: str | Path | None) -> dict[str, Any]:
    """Verdichtet ein Trace zu Kennzahlen je Phase und Agent."""
    summary: dict[str, Any] = {"phases": [], "agents": {}, "total_tokens": 0, "failed_agents": [], "events": 0}
    if not path:
        return summary
    agents: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"calls": 0, "successes": 0, "tokens": 0, "tool_calls": 0, "files": set(), "models": set()}
    )
    phases: dict[str, dict[str, Any]] = {}
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return summary
    for line in lines:
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        summary["events"] += 1
        event = record.get("event")
        if event == "agent_call":
            stats = agents[str(record.get("agent_id") or "?")]
            stats["calls"] += 1
            stats["successes"] += 1 if record.get("success") else 0
            stats["tokens"] += int(record.get("total_tokens") or 0)
            stats["tool_calls"] += int(record.get("tool_calls_count") or 0)
            stats["files"].update(record.get("files_written") or [])
            if record.get("effective_model"):
                stats["models"].add(record["effective_model"])
            summary["total_tokens"] += int(record.get("total_tokens") or 0)
            if not record.get("success"):
                summary["failed_agents"].append(
                    {"agent_id": record.get("agent_id"), "failure_class": record.get("failure_class", ""), "error": str(record.get("error", ""))[:300]}
                )
        elif event == "phase_started":
            phases[str(record.get("phase_id"))] = {"phase_id": record.get("phase_id"), "agents": record.get("agents", []), "tokens": 0}
        elif event == "phase_finished":
            entry = phases.setdefault(str(record.get("phase_id")), {"phase_id": record.get("phase_id"), "agents": []})
            entry.update({k: record.get(k) for k in ("tokens", "successes", "failures", "duration_seconds") if k in record})
    summary["phases"] = list(phases.values())
    summary["agents"] = {
        agent_id: {**stats, "files": sorted(stats["files"]), "models": sorted(stats["models"])}
        for agent_id, stats in agents.items()
    }
    return summary


def format_trace_summary(summary: dict[str, Any], max_agents: int = 15) -> str:
    """Kompakte Textform für Analyse-Prompts."""
    if not summary.get("events"):
        return ""
    lines = [f"Gesamt-Tokens: {summary.get('total_tokens', 0):,}"]
    for phase in summary.get("phases", []):
        lines.append(
            f"- Phase {phase.get('phase_id')}: {phase.get('tokens', 0):,} Tokens, "
            f"{phase.get('successes', '?')} ok / {phase.get('failures', '?')} fehlgeschlagen"
        )
    ranked = sorted(summary.get("agents", {}).items(), key=lambda kv: kv[1]["tokens"], reverse=True)
    for agent_id, stats in ranked[:max_agents]:
        lines.append(
            f"- {agent_id}: {stats['calls']} Aufruf(e), {stats['successes']} ok, {stats['tokens']:,} Tokens, "
            f"{stats['tool_calls']} Werkzeugaufrufe, {len(stats['files'])} Datei(en)"
        )
    for failure in summary.get("failed_agents", [])[:10]:
        lines.append(f"- ❌ {failure['agent_id']} [{failure['failure_class']}]: {failure['error']}")
    return "\n".join(lines)
