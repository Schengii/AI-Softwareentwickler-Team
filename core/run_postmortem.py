"""
core/run_postmortem.py – Deterministischer Projekt-Abschlussbericht pro Lauf (P3-1).

Pro Lauf entstehen bereits `.ai_team_runs/<ts>_verification.md` (Prüfprotokoll),
`.ai_team_dod.json` (Kriterien), `.ai_team_status.json` (Historie) und `<ts>_trace.jsonl`
(core/run_trace.py). Was fehlte, war die Zusammenführung zu EINEM Abschlussbericht, der die
Frage beantwortet: "Warum ist dieses Projekt (nicht) fertig geworden und was hat es gekostet?"

Bewusst ganz ohne LLM-Aufruf (wie die deterministische Retrospektive, P2-4) - alle Kennzahlen
liegen bereits strukturiert vor (AgentResult-Liste, VerificationOutcome, DefinitionOfDoneResult,
Projekt-Trace). `generate_postmortem()` wird für JEDEN Lauf aufgerufen, auch für grüne, damit ein
Trendbericht (P3-2) über Läufe hinweg vergleichbare Artefakte vorfindet.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.run_trace import format_trace_summary, latest_trace, run_stamp, runs_dir, summarize_trace

logger = logging.getLogger(__name__)

# Task-IDs aus dem Verifikations-/Governance-Fixloop tragen konsistent eines dieser Muster
# (agents/orchestrator/verification.py, governance.py, integration.py) - alles, was NICHT auf
# den ursprünglichen Fachbereichs-Auftrag zurückgeht, sondern eine Reparatur eines bereits
# gelieferten Ergebnisses ist. Ein einzelner Lauf, der 3 von 3 Verifikations-Runden in Fixes
# statt Produktion steckt (realer Fund `sentinedge`), war bisher nirgends als Kennzahl sichtbar.
_REPAIR_TASK_ID_MARKERS = (
    "fix", "recheck", "escalation", "governance_", "verify_", "autofix",
)


def _is_repair_task(task_id: str) -> bool:
    lowered = (task_id or "").lower()
    return any(marker in lowered for marker in _REPAIR_TASK_ID_MARKERS)


def _fix_economy(results: list) -> dict[str, int]:
    production_tokens = 0
    repair_tokens = 0
    repair_calls = 0
    for r in results:
        tokens = int(getattr(r, "total_tokens", 0) or 0)
        if _is_repair_task(getattr(r, "task_id", "")):
            repair_tokens += tokens
            repair_calls += 1
        else:
            production_tokens += tokens
    return {
        "production_tokens": production_tokens,
        "repair_tokens": repair_tokens,
        "repair_calls": repair_calls,
        "total_calls": len(results),
    }


def _role_balance(results: list, planned_agent_ids: list[str] | None) -> list[dict[str, Any]]:
    """Geplant vs. tatsächlich eingesetzt vs. Dateien geschrieben, je Rolle."""
    planned = list(dict.fromkeys(planned_agent_ids or []))
    actual: dict[str, dict] = {}
    for r in results:
        agent_id = getattr(r, "agent_id", "") or "?"
        entry = actual.setdefault(agent_id, {"calls": 0, "files": set(), "success": 0})
        entry["calls"] += 1
        entry["success"] += 1 if getattr(r, "success", False) else 0
        entry["files"].update(getattr(r, "files_written", None) or [])
    rows: list[dict[str, Any]] = []
    for agent_id in planned:
        stats = actual.pop(agent_id, None)
        rows.append({
            "agent_id": agent_id, "planned": True,
            "calls": stats["calls"] if stats else 0,
            "success": stats["success"] if stats else 0,
            "files": len(stats["files"]) if stats else 0,
        })
    for agent_id, stats in actual.items():
        rows.append({
            "agent_id": agent_id, "planned": False,
            "calls": stats["calls"], "success": stats["success"], "files": len(stats["files"]),
        })
    return rows


def _related_root_cause_tickets(project_slug: str) -> list[Any]:
    """Offene Root-Cause-Tickets desselben Projekts (siehe core/backlog_store.py). Best-Effort:
    ein Fehler hier darf den restlichen Bericht nicht verhindern."""
    try:
        from core.backlog_store import list_tickets
        return [
            t for t in list_tickets()
            if t.source == "root_cause_analysis" and t.project_slug == project_slug and t.status != "done"
        ]
    except Exception:
        return []


def generate_postmortem(
    project_dir: str | Path,
    project_slug: str,
    *,
    results: list,
    planned_agent_ids: list[str] | None,
    total_duration: float,
    verification_ok: bool,
    outcome: Any = None,
    stamp: str | None = None,
) -> str | None:
    """Schreibt `<projekt>/.ai_team_runs/<stamp>_postmortem.md` und liefert den projektrelativen
    Pfad zurück (None bei I/O-Fehler). Kein LLM-Aufruf, kein zusätzliches Token-Budget."""
    stamp = stamp or run_stamp()
    total_tokens = sum(int(getattr(r, "total_tokens", 0) or 0) for r in results)
    files_written = sorted({f for r in results for f in (getattr(r, "files_written", None) or [])})
    failed = [r for r in results if not getattr(r, "success", False)]

    from core.verification_outcome import VerificationOutcome
    blocking = sorted(outcome.blocking_failed_checks) if isinstance(outcome, VerificationOutcome) else []
    informational = sorted(outcome.informational_failed_checks) if isinstance(outcome, VerificationOutcome) else []

    lines = [
        f"# Projekt-Abschlussbericht – {project_slug}",
        "",
        f"*Deterministisch erzeugt, kein LLM-Aufruf. Lauf-Stempel: `{stamp}`.*",
        "",
        "## Ergebnis",
        "",
        f"- Verifikation: {'✅ bestanden' if verification_ok else '❌ nicht bestanden'}",
        f"- Dauer gesamt: {total_duration:.1f}s | Agenten-Aufrufe: {len(results)} "
        f"({len(results) - len(failed)}/{len(results)} erfolgreich) | Tokens gesamt: {total_tokens:,}",
        f"- Dateien geschrieben: {len(files_written)}",
    ]
    if blocking:
        lines.append(f"- Blockierende Prüfungen fehlgeschlagen: {', '.join(blocking)}")
    if informational:
        lines.append(f"- Nur informativ fehlgeschlagen (kein Blocker): {', '.join(informational)}")
    if failed:
        lines.append("")
        lines.append("### Fehlgeschlagene Agenten-Aufrufe")
        for r in failed:
            lines.append(f"- ❌ {getattr(r, 'agent_name', '?')} ({getattr(r, 'agent_id', '?')}): {getattr(r, 'error', '') or '(kein Fehlertext)'}")

    fix_econ = _fix_economy(results)
    lines += [
        "",
        "## Fix-Ökonomie",
        "",
        f"- Produktion: {fix_econ['production_tokens']:,} Tokens "
        f"({fix_econ['total_calls'] - fix_econ['repair_calls']} Aufruf(e))",
        f"- Reparatur (Verifikations-/Governance-Fixloop): {fix_econ['repair_tokens']:,} Tokens "
        f"({fix_econ['repair_calls']} Aufruf(e))",
    ]
    if fix_econ["total_calls"]:
        repair_share = 100 * fix_econ["repair_calls"] / fix_econ["total_calls"]
        lines.append(f"- Anteil Reparatur an allen Aufrufen: {repair_share:.0f}%")

    lines += ["", "## Rollen-Bilanz (geplant vs. eingesetzt)", "", "| Rolle | geplant | Aufrufe | erfolgreich | Dateien |", "|---|---|---|---|---|"]
    for row in _role_balance(results, planned_agent_ids):
        lines.append(
            f"| {row['agent_id']} | {'✅' if row['planned'] else '—'} | {row['calls']} | "
            f"{row['success']} | {row['files']} |"
        )

    trace = latest_trace(project_dir)
    trace_text = format_trace_summary(summarize_trace(trace)) if trace else ""
    if trace_text:
        lines += ["", "## Zeitachse (Phasen & Agenten, aus Projekt-Trace)", "", trace_text]

    tickets = _related_root_cause_tickets(project_slug)
    if tickets:
        lines += ["", "## Offene Root-Cause-Tickets zu diesem Projekt", ""]
        for t in tickets:
            lines.append(f"- `{t.id}` ({t.status}): {t.title}")

    target = runs_dir(project_dir) / f"{stamp}_postmortem.md"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as e:
        logger.warning("Postmortem konnte nicht geschrieben werden (%s): %r", target, e)
        return None
    from core.run_trace import RUNS_DIRNAME
    return f"{RUNS_DIRNAME}/{target.name}"
