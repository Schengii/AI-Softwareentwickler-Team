"""
core/model_ab_trials.py – Kontrollierte A/B-Tests für Modellzuweisungen je Agent.

core/optimization_advisor.py erkannte bereits, wenn ein Agent mit einem anderen Modell
empirisch besser lief (z. B. `performance` mit gemini-3.1-flash-lite: 100% statt 76,9% bei
weniger Tokens). Umgesetzt wurde das aber nur als Lektion bzw. als harter, globaler Wechsel
hinter dem standardmäßig deaktivierten ENABLE_AUTO_MODEL_TUNING - also praktisch nie.

Ablauf hier:
1. `start_trials_from_report()`: Aus einem Modell-Vorschlag wird ein Test - nur ein Anteil
   (MODEL_AB_TRIAL_SHARE) der Läufe nutzt das Kandidatenmodell, der Rest bleibt beim bisherigen.
2. `evaluate_trials()`: Sobald der Kandidat genug echte Aufrufe hat, wird er übernommen
   (mindestens gleich gute Erfolgsquote bei vertretbaren Tokens) oder verworfen.
3. Übernommene Modelle werden weiter beobachtet und bei messbarer Verschlechterung automatisch
   zurückgenommen.

Ein expliziter .env-Rollen- oder Fachbereichs-Override hat immer Vorrang (config.get_model_for_agent).
"""

from __future__ import annotations

import json
import logging
import random
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

TRIAL_STATUS_ACTIVE = "trial"
TRIAL_STATUS_PROMOTED = "promoted"
TRIAL_STATUS_REJECTED = "rejected"
TRIAL_STATUS_ROLLED_BACK = "rolled_back"

MAX_TOKEN_RATIO_FOR_PROMOTION = 1.3


def _trials_path() -> Path:
    import config

    return Path(config.MODEL_AB_TRIALS_FILE)


def load_trials() -> dict[str, dict]:
    path = _trials_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_trials(data: dict[str, dict]) -> bool:
    path = _trials_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except OSError as e:
        logger.warning("A/B-Test-Datei konnte nicht geschrieben werden (%s): %r", path, e)
        return False


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _has_explicit_override(agent_id: str) -> bool:
    import os

    import config

    return bool(os.getenv(config.get_model_env_key(agent_id)))


def start_trials_from_report(report) -> list[str]:
    """Legt für jeden Modell-Vorschlag ohne laufenden Test einen neuen A/B-Test an."""
    import config

    if not config.ENABLE_MODEL_AB_TRIALS:
        return []
    trials = load_trials()
    started: list[str] = []
    for s in getattr(report, "model_suggestions", []) or []:
        existing = trials.get(s.agent_id, {})
        if existing.get("status") in (TRIAL_STATUS_ACTIVE, TRIAL_STATUS_PROMOTED):
            continue
        if existing.get("status") == TRIAL_STATUS_REJECTED and existing.get("candidate") == s.suggested_model:
            continue
        if _has_explicit_override(s.agent_id):
            continue
        trials[s.agent_id] = {
            "status": TRIAL_STATUS_ACTIVE,
            "candidate": s.suggested_model,
            "baseline": s.current_model,
            "share": config.MODEL_AB_TRIAL_SHARE,
            "started_at": _now(),
            "candidate_calls_at_start": s.suggested_calls,
            "reason": (
                f"Vorschlag: {s.suggested_success_rate}% vs. {s.current_success_rate}% Erfolgsquote "
                f"(⌀{s.suggested_avg_tokens:.0f} vs. ⌀{s.current_avg_tokens:.0f} Tokens)."
            ),
        }
        started.append(s.agent_id)
    if started:
        _save_trials(trials)
    return started


def trial_model_for_agent(agent_id: str, rand: Callable[[], float] = random.random) -> str | None:
    """Kandidatenmodell, falls für diesen Lauf der A/B-Test-Arm gezogen wird, sonst None."""
    import config

    if not config.ENABLE_MODEL_AB_TRIALS:
        return None
    trial = load_trials().get(agent_id)
    if not trial or trial.get("status") != TRIAL_STATUS_ACTIVE:
        return None
    share = float(trial.get("share", config.MODEL_AB_TRIAL_SHARE))
    return str(trial.get("candidate")) if rand() < share else None


def _perf_by_model(performance: list[dict], agent_id: str) -> dict[str, dict]:
    return {p["model"]: p for p in performance if p.get("agent_id") == agent_id}


def evaluate_trials(performance: list[dict] | None = None) -> dict[str, list[str]]:
    """Übernimmt, verwirft oder nimmt Modellzuweisungen zurück. Rückgabe: Agenten je Ergebnis."""
    import config
    from core.optimization_advisor import MIN_SUCCESS_RATE_GAP, _load_auto_tuned_models, _save_auto_tuned_models

    outcome: dict[str, list[str]] = {"promoted": [], "rejected": [], "rolled_back": []}
    trials = load_trials()
    if not trials:
        return outcome
    if performance is None:
        from memory.run_history import get_agent_model_performance

        performance = get_agent_model_performance(100)

    tuned = _load_auto_tuned_models()
    changed = False
    for agent_id, trial in trials.items():
        stats = _perf_by_model(performance, agent_id)
        candidate = stats.get(str(trial.get("candidate")))
        baseline = stats.get(str(trial.get("baseline")))
        if trial.get("status") == TRIAL_STATUS_ACTIVE:
            new_calls = (candidate or {}).get("calls", 0) - int(trial.get("candidate_calls_at_start", 0))
            if candidate is None or baseline is None or new_calls < config.MODEL_AB_MIN_TRIAL_CALLS:
                continue
            token_ratio = (candidate["avg_tokens"] / baseline["avg_tokens"]) if baseline["avg_tokens"] else 1.0
            if candidate["success_rate"] >= baseline["success_rate"] and token_ratio <= MAX_TOKEN_RATIO_FOR_PROMOTION:
                tuned[agent_id] = {
                    "model": trial["candidate"],
                    "previous_model": trial["baseline"],
                    "success_rate": candidate["success_rate"],
                    "avg_tokens": candidate["avg_tokens"],
                    "applied_at": _now(),
                    "manual": False,
                    "ab_promoted": True,
                    "reason": (
                        f"A/B-Test bestanden: {candidate['success_rate']}% vs. {baseline['success_rate']}% "
                        f"({candidate['calls']} vs. {baseline['calls']} Aufrufe, Token-Verhältnis {token_ratio:.2f})."
                    ),
                }
                trial.update(status=TRIAL_STATUS_PROMOTED, decided_at=_now())
                outcome["promoted"].append(agent_id)
                changed = True
            elif candidate["success_rate"] + MIN_SUCCESS_RATE_GAP <= baseline["success_rate"] or token_ratio > MAX_TOKEN_RATIO_FOR_PROMOTION * 1.5:
                trial.update(status=TRIAL_STATUS_REJECTED, decided_at=_now())
                outcome["rejected"].append(agent_id)
                changed = True
        elif trial.get("status") == TRIAL_STATUS_PROMOTED:
            entry = tuned.get(agent_id, {})
            if not entry.get("ab_promoted") or candidate is None or baseline is None:
                continue
            if candidate["calls"] >= config.MODEL_AB_MIN_TRIAL_CALLS and candidate["success_rate"] + MIN_SUCCESS_RATE_GAP <= baseline["success_rate"]:
                tuned.pop(agent_id, None)
                trial.update(status=TRIAL_STATUS_ROLLED_BACK, decided_at=_now())
                outcome["rolled_back"].append(agent_id)
                changed = True
    if changed:
        _save_trials(trials)
        _save_auto_tuned_models(tuned)
    return outcome
