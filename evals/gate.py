"""
evals/gate.py – Regressions-Gate für Framework-Änderungen auf Basis der Benchmark-Historie.

Die Benchmark-Suite existierte, wurde aber nie dauerhaft ausgewertet (keine eval_history.json).
Framework-Änderungen wurden dadurch nach Einzelfällen beurteilt ("dieser Lauf ging jetzt"),
nicht danach, ob das Team insgesamt besser oder schlechter wurde.

`evaluate_gate()` vergleicht den jüngsten Suite-Lauf mit einer Baseline (Median der vorherigen
Läufe derselben Aufgaben) und meldet eine Regression, wenn
- die Erfolgsquote um mehr als `max_pass_rate_drop` Prozentpunkte sinkt,
- der Token-Verbrauch je Aufgabe um mehr als `max_token_increase` (relativ) steigt, oder
- eine Aufgabe, die in der Baseline mehrheitlich bestand, jetzt scheitert.

`python main.py --eval-gate` gibt bei einer Regression den Exit-Code 1 zurück (CI-tauglich).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

from evals.runner import EVALS_HISTORY_FILE

DEFAULT_BASELINE_RUNS = 5
DEFAULT_MAX_PASS_RATE_DROP = 10.0
DEFAULT_MAX_TOKEN_INCREASE = 0.25


@dataclass
class GateResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    baseline_runs: int = 0

    def format_report(self) -> str:
        head = "✅ Eval-Gate bestanden" if self.passed else "❌ Eval-Gate: Regression erkannt"
        lines = [f"{head} (Baseline: {self.baseline_runs} Lauf/Läufe)"]
        lines += [f"- ❌ {r}" for r in self.reasons]
        lines += [f"- ℹ️ {n}" for n in self.notes]
        return "\n".join(lines)


def load_history(path: Path = EVALS_HISTORY_FILE) -> list[dict]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _task_passed(result: dict) -> bool:
    return bool(result.get("success")) and bool(result.get("verification_ok"))


def evaluate_gate(
    history: list[dict],
    baseline_runs: int = DEFAULT_BASELINE_RUNS,
    max_pass_rate_drop: float = DEFAULT_MAX_PASS_RATE_DROP,
    max_token_increase: float = DEFAULT_MAX_TOKEN_INCREASE,
) -> GateResult:
    """Bewertet den jüngsten Lauf gegen die Baseline. Ohne Baseline: bestanden mit Hinweis."""
    if not history:
        return GateResult(passed=True, notes=["Keine Benchmark-Historie vorhanden - erst `python main.py --eval` ausführen."])
    latest = history[-1]
    latest_results = {r.get("slug"): r for r in latest.get("results", []) if r.get("slug")}
    if not latest_results:
        return GateResult(passed=False, reasons=["Jüngster Benchmark-Lauf enthält keine Aufgaben-Ergebnisse."])

    previous = history[:-1][-baseline_runs:]
    baseline_by_task: dict[str, list[dict]] = {}
    for run in previous:
        for r in run.get("results", []):
            if r.get("slug") in latest_results:
                baseline_by_task.setdefault(r["slug"], []).append(r)
    result = GateResult(passed=True, baseline_runs=len(previous))
    if not baseline_by_task:
        result.notes.append("Keine vergleichbare Baseline für die gelaufenen Aufgaben - Lauf wird als neue Baseline gespeichert.")
        return result

    comparable = sorted(baseline_by_task)
    latest_rate = 100.0 * sum(_task_passed(latest_results[s]) for s in comparable) / len(comparable)
    baseline_rates = [
        100.0 * sum(_task_passed(r) for r in runs) / len(runs) for runs in baseline_by_task.values()
    ]
    baseline_rate = sum(baseline_rates) / len(baseline_rates)
    if baseline_rate - latest_rate > max_pass_rate_drop:
        result.reasons.append(
            f"Erfolgsquote {latest_rate:.0f}% liegt {baseline_rate - latest_rate:.0f} Prozentpunkte unter der Baseline ({baseline_rate:.0f}%)."
        )

    for slug in comparable:
        runs = baseline_by_task[slug]
        current = latest_results[slug]
        pass_share = sum(_task_passed(r) for r in runs) / len(runs)
        if pass_share > 0.5 and not _task_passed(current):
            detail = ", ".join(current.get("failed_checks") or []) or current.get("error") or "nicht verifiziert"
            result.reasons.append(f"`{slug}` bestand in der Baseline mehrheitlich, scheitert jetzt ({detail}).")
        baseline_tokens = median([int(r.get("total_tokens") or 0) for r in runs])
        current_tokens = int(current.get("total_tokens") or 0)
        if baseline_tokens > 0 and current_tokens > baseline_tokens * (1 + max_token_increase):
            increase = (current_tokens / baseline_tokens - 1) * 100
            result.reasons.append(
                f"`{slug}` verbraucht {current_tokens:,} Tokens (+{increase:.0f}% ggü. Median {int(baseline_tokens):,})."
            )
        elif baseline_tokens > 0 and current_tokens < baseline_tokens * 0.8:
            result.notes.append(f"`{slug}` spart Tokens: {current_tokens:,} statt Median {int(baseline_tokens):,}.")

    result.passed = not result.reasons
    return result
