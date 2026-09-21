"""
core/team_trend.py – Trendbericht über Läufe hinweg (P3-2): "Werden wir besser?"

`--team-retro` und `--weekly-digest` (core/team_retro.py) beantworten "was liegt gerade an",
aber keine der beiden beantwortet die wichtigste Frage: wird das Team über die Zeit besser oder
schlechter? Bisher musste eine Zahl wie "13% grün über 152 Läufe" (siehe ROADMAP_TEMP.md) von
Hand aus memory/run_history.json ausgerechnet werden.

`python main.py --team-trend [--days N]` baut ausschließlich aus bereits vorhandenen,
strukturierten Datenquellen (kein LLM-Aufruf):

- memory/run_history.json: rollierende Wochen-Erfolgsquote, Ø Tokens/Lauf, Regressions-Warnung.
- workspace/*/.ai_team_status.json (core/project_status.py) + core/team_health.categorize_
  failure() (P0-5): Top-5-Blocker nach Häufigkeit über ALLE Läufe im Zeitfenster, nicht nur den
  jeweils neuesten je Projekt wie core/team_health.build_team_health_rollup().
- memory/agent_learnings.json (memory/agent_knowledge_base.py, P2-1): welche Regeln ihre
  gemessene Wirksamkeit (violations_after / injections) bereits belegt haben und welche nicht.
- workspace/*/.ai_team_runs/*_postmortem.md (core/run_postmortem.py, P3-1): Ø Reparatur-Aufrufe
  je Lauf, soweit für das Projekt bereits Post-Mortem-Berichte vorliegen (das Feld existiert erst
  seit P3-1 - ältere Läufe tragen dafür keine Daten, das wird im Bericht offen ausgewiesen statt
  stillschweigend mit 0 aufzufüllen).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

DEFAULT_TREND_WINDOW_DAYS = 30
# Für die Regressions-Warnung verglichene Fenstergröße - bewusst dieselbe kleine, feste Zahl wie
# core/project_status.has_repeated_failure() für "Serie", damit ein einzelner Ausreißer keine
# Warnung auslöst, ein echter Trend über mehrere Läufe aber schon.
_REGRESSION_WINDOW_RUNS = 10
_REPAIR_CALLS_RE = re.compile(r"Reparatur[^:]*:\s*[\d,]+\s*Tokens\s*\((\d+)\s*Aufruf")


def _parse_timestamp(raw: str) -> datetime | None:
    try:
        ts = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


@dataclass
class TeamTrend:
    window_days: int
    weekly_success: list[dict] = field(default_factory=list)  # [{"week": "2026-W38", "runs": int, "passed": int, "rate": float}]
    avg_tokens_per_run: float = 0.0
    total_runs_in_window: int = 0
    top_blockers: list[tuple[str, int]] = field(default_factory=list)
    effective_learnings: list[dict] = field(default_factory=list)
    ineffective_learnings: list[dict] = field(default_factory=list)
    avg_repair_calls_per_run: float | None = None
    postmortems_seen: int = 0
    regression_warning: str | None = None

    def format_for_humans(self) -> str:
        lines = [f"📈 Team-Trend (letzte {self.window_days} Tage)", ""]
        if not self.weekly_success:
            lines.append("Keine Läufe in diesem Zeitraum aufgezeichnet.")
            return "\n".join(lines)

        lines.append("## Erfolgsquote pro Woche (rollierend)")
        for week in self.weekly_success:
            lines.append(f"- {week['week']}: {week['passed']}/{week['runs']} ({week['rate']}%)")
        lines.append("")
        lines.append(
            f"Ø Tokens/Lauf: {self.avg_tokens_per_run:,.0f} · Läufe gesamt im Zeitfenster: "
            f"{self.total_runs_in_window}"
        )
        if self.avg_repair_calls_per_run is not None:
            lines.append(
                f"Ø Reparatur-Aufrufe/Lauf: {self.avg_repair_calls_per_run:.1f} "
                f"(aus {self.postmortems_seen} Post-Mortem-Bericht(en), P3-1)"
            )
        else:
            lines.append("Ø Reparatur-Aufrufe/Lauf: keine Post-Mortem-Berichte im Zeitfenster gefunden.")

        if self.regression_warning:
            lines.append("")
            lines.append(f"⚠️ {self.regression_warning}")

        lines.append("")
        lines.append("## Top-5-Blocker nach Häufigkeit")
        if self.top_blockers:
            for category, count in self.top_blockers:
                lines.append(f"- {category}: {count}×")
        else:
            lines.append("Keine fehlgeschlagenen Läufe mit erkennbarer Kategorie im Zeitfenster.")

        lines.append("")
        lines.append("## Wirksamkeit der Learnings (P2-1)")
        if self.effective_learnings:
            lines.append("Wirksam (Verletzung nach Injektion selten):")
            for e in self.effective_learnings[:5]:
                lines.append(f"- [{e['agent_id']}] {e['rule'][:100]} ({e['effectiveness']:.0f}% wirksam)")
        if self.ineffective_learnings:
            lines.append("Wirkungslos (häufig weiter verletzt trotz Injektion):")
            for e in self.ineffective_learnings[:5]:
                lines.append(f"- [{e['agent_id']}] {e['rule'][:100]} ({e['effectiveness']:.0f}% wirksam)")
        if not self.effective_learnings and not self.ineffective_learnings:
            lines.append("Noch keine Regel mit ausreichend Injektionen für eine Wirksamkeitsaussage.")
        return "\n".join(lines)


def _weekly_success_rates(runs: list[dict]) -> list[dict]:
    buckets: dict[str, dict[str, int]] = {}
    for run in runs:
        ts = _parse_timestamp(run.get("timestamp", ""))
        if ts is None:
            continue
        iso = ts.isocalendar()
        week_key = f"{iso[0]}-W{iso[1]:02d}"
        entry = buckets.setdefault(week_key, {"runs": 0, "passed": 0})
        entry["runs"] += 1
        if run.get("verification_ok"):
            entry["passed"] += 1
    return [
        {"week": week, "runs": stats["runs"], "passed": stats["passed"], "rate": round(100 * stats["passed"] / stats["runs"], 1)}
        for week, stats in sorted(buckets.items())
    ]


def _regression_warning(runs_newest_first: list[dict]) -> str | None:
    """Vergleicht die letzten _REGRESSION_WINDOW_RUNS Läufe mit den _REGRESSION_WINDOW_RUNS davor
    - erst ab genug Läufen für beide Fenster, sonst kein Urteil (siehe Docstring oben)."""
    needed = 2 * _REGRESSION_WINDOW_RUNS
    if len(runs_newest_first) < needed:
        return None
    recent = runs_newest_first[:_REGRESSION_WINDOW_RUNS]
    previous = runs_newest_first[_REGRESSION_WINDOW_RUNS:needed]
    recent_rate = 100 * sum(1 for r in recent if r.get("verification_ok")) / len(recent)
    previous_rate = 100 * sum(1 for r in previous if r.get("verification_ok")) / len(previous)
    if recent_rate < previous_rate:
        return (
            f"Erfolgsquote der letzten {_REGRESSION_WINDOW_RUNS} Läufe ({recent_rate:.0f}%) liegt "
            f"unter den {_REGRESSION_WINDOW_RUNS} davor ({previous_rate:.0f}%) - mögliche Regression."
        )
    return None


def _top_blockers(workspace_dir: str, cutoff: datetime, limit: int = 5) -> list[tuple[str, int]]:
    from core.project_status import read_full_detail, read_status
    from core.team_health import categorize_failure

    counts: dict[str, int] = {}
    base = Path(workspace_dir)
    if not base.exists():
        return []
    for entry_dir in base.iterdir():
        if not entry_dir.is_dir():
            continue
        for run_entry in read_status(str(entry_dir)):
            if run_entry.get("verification_ok") or run_entry.get("cancelled") or run_entry.get("budget_aborted"):
                continue
            ts = _parse_timestamp(run_entry.get("timestamp", ""))
            if ts is None or ts < cutoff:
                continue
            detail = read_full_detail(str(entry_dir), run_entry) or run_entry.get("failure_detail", "")
            category = categorize_failure(detail)
            counts[category] = counts.get(category, 0) + 1
    return sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]


def _learning_effectiveness(kb=None) -> tuple[list[dict], list[dict]]:
    """Liefert (wirksam, wirkungslos) - je eine Liste von {"agent_id", "rule", "effectiveness"},
    `effectiveness` bereits als "% wirksam" (0-100, höher = besser), analog zur Anzeige in
    interface/cli.py._show_learnings(). memory/agent_knowledge_base.py._effectiveness_rate()
    liefert das GEGENTEIL (violations_after / injections, 0-1, niedriger = besser) - hier
    umgerechnet, damit dieser Bericht und die CLI-Anzeige dasselbe Vorzeichen verwenden."""
    from memory.agent_knowledge_base import MIN_INJECTIONS_FOR_EFFECTIVENESS, agent_knowledge_base

    kb = kb if kb is not None else agent_knowledge_base
    measured: list[dict] = []
    for agent_id in kb.get_all_learnings():
        for detail in kb.get_learning_details(agent_id):
            violation_rate = detail.get("effectiveness")
            if violation_rate is None or detail.get("injections", 0) < MIN_INJECTIONS_FOR_EFFECTIVENESS:
                continue
            measured.append({"agent_id": agent_id, "rule": detail["rule"], "effectiveness": 100 * (1 - violation_rate)})
    measured.sort(key=lambda e: e["effectiveness"], reverse=True)
    effective = [e for e in measured if e["effectiveness"] >= 80]
    ineffective = sorted((e for e in measured if e["effectiveness"] < 50), key=lambda e: e["effectiveness"])
    return effective, ineffective


def _avg_repair_calls(workspace_dir: str, cutoff: datetime) -> tuple[float | None, int]:
    """Liest `Reparatur (...): N Tokens (M Aufruf(e))` aus allen Post-Mortem-Berichten
    (core/run_postmortem.py, P3-1) im Zeitfenster. None, wenn keiner gefunden wurde - ein
    Framework ohne bereits erzeugte Post-Mortems hat dafür schlicht noch keine Daten."""
    base = Path(workspace_dir)
    if not base.exists():
        return None, 0
    total_calls = 0
    seen = 0
    for postmortem in base.glob("*/.ai_team_runs/*_postmortem.md"):
        stamp = postmortem.name.split("_postmortem.md")[0]
        try:
            ts = datetime.strptime(stamp, "%Y%m%d_%H%M%S").replace(tzinfo=UTC)
        except ValueError:
            continue
        if ts < cutoff:
            continue
        try:
            text = postmortem.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        match = _REPAIR_CALLS_RE.search(text)
        if not match:
            continue
        total_calls += int(match.group(1))
        seen += 1
    if seen == 0:
        return None, 0
    return total_calls / seen, seen


def build_team_trend(
    window_days: int = DEFAULT_TREND_WINDOW_DAYS, workspace_dir: str | None = None, knowledge_base=None,
) -> TeamTrend:
    """Baut den Trendbericht aus bereits bestehenden Datenquellen - jede Quelle best-effort (ein
    Fehler in einer Quelle darf den Rest des Berichts nicht verwerfen). `knowledge_base` ist
    injizierbar (Standard: der echte Singleton), damit Tests nicht auf memory/agent_learnings.json
    zugreifen müssen."""
    if workspace_dir is None:
        from config import WORKSPACE_DIR
        workspace_dir = WORKSPACE_DIR

    from memory.run_history import get_recent_runs

    cutoff = datetime.now(UTC) - timedelta(days=window_days)
    all_recent = get_recent_runs(limit=200)  # neueste zuerst, memory.run_history.MAX_RUNS_KEPT
    runs_in_window = [r for r in all_recent if (_parse_timestamp(r.get("timestamp", "")) or cutoff) >= cutoff]

    total_tokens = sum(r.get("total_tokens", 0) for r in runs_in_window)

    try:
        top_blockers = _top_blockers(workspace_dir, cutoff)
    except Exception:
        top_blockers = []

    try:
        effective, ineffective = _learning_effectiveness(kb=knowledge_base)
    except Exception:
        effective, ineffective = [], []

    try:
        avg_repair_calls, postmortems_seen = _avg_repair_calls(workspace_dir, cutoff)
    except Exception:
        avg_repair_calls, postmortems_seen = None, 0

    return TeamTrend(
        window_days=window_days,
        weekly_success=_weekly_success_rates(runs_in_window),
        avg_tokens_per_run=(total_tokens / len(runs_in_window)) if runs_in_window else 0.0,
        total_runs_in_window=len(runs_in_window),
        top_blockers=top_blockers,
        effective_learnings=effective,
        ineffective_learnings=ineffective,
        avg_repair_calls_per_run=avg_repair_calls,
        postmortems_seen=postmortems_seen,
        regression_warning=_regression_warning(all_recent),
    )
