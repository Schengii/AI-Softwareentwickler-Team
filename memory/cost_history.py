"""
memory/cost_history.py – Persistenter Tokenverbrauch über ALLE Läufe hinweg

Realer Fund: core/token_guard.py ist eine reine In-Memory-Instanz – bei jedem Neustart
(neues CLI-Terminal, neuer Dashboard-Prozess) beginnt der gezeigte Tokenverbrauch wieder bei
Null (core/quota_estimator.py zeigt deshalb nur die AKTUELLE Sitzung). Es gab keinen Weg zu
sehen, wie viele Tokens das Team INSGESAMT seit Beginn der Nutzung verbraucht hat – der
eigentlich relevante Wert für die Kosteneinschätzung eines wiederkehrend genutzten Teams.

Bewusst nur TOKEN-Zahlen, keine geschätzten $-Beträge: echte Preise unterscheiden sich pro
Modell/Provider und ändern sich laufend – ein erfundener $-Betrag ohne verlässliche, aktuelle
Preistabelle wäre eine Falschaussage (dieselbe "echt statt geraten"-Philosophie wie beim
Dependency-Audit/Docker-Build – lieber ehrliche Tokenzahlen als ein plausibel klingender,
aber erfundener Kostenwert).
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from config import BASE_DIR

COST_HISTORY_FILE = Path(BASE_DIR) / "memory" / "cost_history.json"

_STAT_KEYS = ("total_calls", "prompt_tokens", "completion_tokens", "total_tokens")


def record_run_usage(model_deltas: dict[str, dict[str, int]]) -> None:
    """
    Addiert den Tokenverbrauch EINES einzelnen Laufs zur persistenten Gesamt-Historie.
    model_deltas ist bereits als Delta SEIT Laufbeginn berechnet (siehe
    Orchestrator._model_usage_deltas()) – nicht der volle Prozess-Gesamtzähler, sonst würde
    ein zweiter Lauf in derselben Sitzung den ersten doppelt zählen. Läufe ohne echten
    Tokenverbrauch (z. B. sofortiger Abbruch bei einer Rückfrage) erzeugen keinen Eintrag.
    """
    total = sum(stat.get("total_tokens", 0) for stat in model_deltas.values())
    if total <= 0:
        return

    data = _load()
    totals = data.setdefault("models", {})
    for model_name, delta in model_deltas.items():
        if delta.get("total_tokens", 0) <= 0:
            continue
        entry = totals.setdefault(model_name, dict.fromkeys(_STAT_KEYS, 0))
        for key in _STAT_KEYS:
            entry[key] += delta.get(key, 0)

    data["runs_recorded"] = data.get("runs_recorded", 0) + 1
    now = datetime.now(UTC).isoformat(timespec="seconds")
    data["last_recorded_at"] = now
    data.setdefault("first_recorded_at", now)

    _save(data)


def get_lifetime_totals() -> dict:
    """Gibt die kumulierten Werte über ALLE bisher aufgezeichneten Läufe zurück (leeres dict,
    falls noch nie ein Lauf mit echtem Tokenverbrauch aufgezeichnet wurde – kein Crash)."""
    return _load()


def _load() -> dict:
    if not COST_HISTORY_FILE.exists():
        return {}
    try:
        data = json.loads(COST_HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    try:
        COST_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        COST_HISTORY_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
