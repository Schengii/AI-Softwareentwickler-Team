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

_STAT_KEYS = ("total_calls", "prompt_tokens", "completion_tokens", "total_tokens", "cache_read_tokens", "cache_write_tokens")

# Team-Optimierung (Retrospektive 2026-09-07): core/quota_estimator.py.
# get_proactive_budget_warnings() sah bisher NUR core/token_guard.py - eine reine In-Memory-
# Instanz DIESES EINEN Prozesses (siehe Moduldocstring oben). Mehrere kurze CLI-Sitzungen am
# selben Tag (der real übliche Nutzungs-Rhythmus, nicht ein einziger durchgehender Dauerlauf)
# ließen den Verbrauchszähler bei jedem Neustart wieder bei Null beginnen - eine Provider-
# Erschöpfung, die sich über den TAG hinweg (nicht nur innerhalb einer Sitzung) anbahnt, blieb
# dadurch bis zum tatsächlichen 429 unsichtbar. `daily` bucketet denselben Verbrauch zusätzlich
# nach Kalendertag (UTC), unabhängig von Sitzungsgrenzen - `get_today_totals()` macht daraus
# die Grundlage für eine über den ganzen Tag hinweg wirksame Warnung.
_MAX_DAILY_BUCKETS_KEPT = 14


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
        # Realer Fund aus einem echten Lauf: setdefault() oben füllt einen Standardwert NUR,
        # wenn model_name INSGESAMT noch fehlt - ein bereits vorhandener Eintrag aus einer
        # Zeit VOR "cache_read_tokens"/"cache_write_tokens" in _STAT_KEYS (jedes Modell in der
        # echten memory/cost_history.json war betroffen) hatte diese beiden Schlüssel nicht,
        # entry[key] += ... schlug dann mit KeyError('cache_read_tokens') fehl - fälschlich
        # lange als SDK-Eigenheit vermutet, tatsächlich ein simples Schema-Migrations-Loch.
        # entry.setdefault(key, 0) backfillt fehlende Schlüssel an bestehenden Einträgen.
        for key in _STAT_KEYS:
            entry.setdefault(key, 0)
            entry[key] += delta.get(key, 0)

    day_key = datetime.now(UTC).strftime("%Y-%m-%d")
    daily = data.setdefault("daily", {})
    day_totals = daily.setdefault(day_key, {})
    for model_name, delta in model_deltas.items():
        if delta.get("total_tokens", 0) <= 0:
            continue
        entry = day_totals.setdefault(model_name, dict.fromkeys(_STAT_KEYS, 0))
        for key in _STAT_KEYS:
            entry.setdefault(key, 0)
            entry[key] += delta.get(key, 0)
    _prune_old_daily_buckets(daily)

    data["runs_recorded"] = data.get("runs_recorded", 0) + 1
    now = datetime.now(UTC).isoformat(timespec="seconds")
    data["last_recorded_at"] = now
    data.setdefault("first_recorded_at", now)

    _save(data)


def _prune_old_daily_buckets(daily: dict) -> None:
    """Behält nur die jüngsten `_MAX_DAILY_BUCKETS_KEPT` Kalendertage - verhindert
    unbegrenztes Wachstum von memory/cost_history.json über Monate/Jahre der Nutzung hinweg
    (Token-/Speicher-Effizienz), ohne die für die proaktive Tages-Budget-Warnung relevante
    jüngste Vergangenheit zu verlieren. Tages-Schlüssel im Format "YYYY-MM-DD" sortieren sich
    lexikografisch identisch zur chronologischen Reihenfolge - kein Datums-Parsing nötig."""
    if len(daily) <= _MAX_DAILY_BUCKETS_KEPT:
        return
    for old_day in sorted(daily.keys())[:-_MAX_DAILY_BUCKETS_KEPT]:
        del daily[old_day]


def get_lifetime_totals() -> dict:
    """Gibt die kumulierten Werte über ALLE bisher aufgezeichneten Läufe zurück (leeres dict,
    falls noch nie ein Lauf mit echtem Tokenverbrauch aufgezeichnet wurde – kein Crash)."""
    return _load()


def get_today_totals(day: str | None = None) -> dict[str, dict[str, int]]:
    """Gibt die kumulierten Pro-Modell-Werte für EINEN Kalendertag zurück (Standard: heute,
    UTC) - siehe _MAX_DAILY_BUCKETS_KEPT-Docstring oben für die volle Herleitung. Leeres dict,
    falls für diesen Tag noch kein Lauf mit echtem Tokenverbrauch aufgezeichnet wurde (der
    Normalfall für den ersten Lauf eines neuen Tages) oder die Historie-Datei nicht lesbar ist."""
    day = day or datetime.now(UTC).strftime("%Y-%m-%d")
    data = _load()
    return data.get("daily", {}).get(day, {})


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
