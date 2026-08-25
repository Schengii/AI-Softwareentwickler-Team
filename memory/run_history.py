"""
memory/run_history.py – Persistente, framework-weite Lauf-Historie für Observability über Zeit

Realer Fund bei einer Bestandsaufnahme des eigenen Teams: core/project_status.py speichert
Lauf-Historie NUR pro Projekt (im jeweiligen Projektverzeichnis selbst) und
memory/cost_history.py NUR kumulierte SUMMEN pro Modell – es gab keine Möglichkeit zu sehen,
welche Agenten über die Zeit häufiger scheitern oder wie sich Tokenverbrauch/Dauer pro Lauf
PROJEKTÜBERGREIFEND entwickeln. Das Web-Dashboard zeigte bisher nur den aktuellen/letzten
Job, keine Trends – genau die natürliche Fortsetzung der bereits bestehenden kumulierten
Kosten-Historie (`/tokens`).

Dieselbe Lade-/Speicher-Konvention wie core/backlog_store.py/memory/cost_history.py: Modul-
Konstante für den Dateipfad (in Tests per patch.object() austauschbar), gedeckelt auf
MAX_RUNS_KEPT gegen unbegrenztes Wachstum über viele Sitzungen hinweg.

Zweiter realer Fund: zahlreiche Integrationstests (u.a. test_governance_fix_loop.py,
test_lint_integration.py, test_sast_integration.py) rufen den vollen Orchestrator.process()-Pfad
auf, ohne selbst per patch.object() ein eigenes RUN_HISTORY_FILE zu setzen – ein zunächst
versuchter zentraler Patch in tests/__init__.py griff dabei NICHT: `python -m unittest discover
-s tests` (die von README/CI dokumentierte Art, die Suite auszuführen) importiert jede
Testdatei als eigenständiges Top-Level-Modul, nicht als `tests.test_x` – tests/__init__.py wird
dabei nachweislich nie ausgeführt (verifiziert: `"tests" in sys.modules` bleibt False). Jeder
Testlauf schrieb dadurch Fake-Einträge direkt in die echte, produktive memory/run_history.json –
genau die Datei, die core/optimization_advisor.py als empirische Grundlage für
Modell-/Erfolgsquoten-Vorschläge auswertet.

_default_run_history_file() greift deshalb an der Stelle, die JEDER Testlauf garantiert
durchläuft (Modul-Import-Zeit dieser Datei, lange bevor eine einzelne Testdatei geladen wird):
läuft der Prozess erkennbar unter unittest/pytest (beide Module bereits in sys.modules geladen,
sobald `-m unittest`/`pytest` überhaupt startet), zeigt der Standardpfad auf eine Datei im
System-Temp-Verzeichnis statt auf die echte memory/run_history.json. Ein Test, der die echte
Datei gezielt prüfen will, patcht RUN_HISTORY_FILE weiterhin wie bisher explizit per
patch.object() – das überschreibt diesen Wert einfach erneut, kein Konflikt.
"""

import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from config import BASE_DIR


def _default_run_history_file() -> Path:
    if "unittest" in sys.modules or "pytest" in sys.modules:
        return Path(tempfile.gettempdir()) / "ai_team_test_run_history.json"
    return Path(BASE_DIR) / "memory" / "run_history.json"


RUN_HISTORY_FILE = _default_run_history_file()
MAX_RUNS_KEPT = 200


def record_run(
    project_slug: str, task_summary: str, verification_ok: bool,
    total_tokens: int, duration_seconds: float, agent_results: list[dict],
) -> None:
    """
    Speichert eine kompakte Zusammenfassung EINES abgeschlossenen Laufs. `agent_results` ist
    eine Liste aus `{"agent_id": str, "success": bool, "total_tokens": int}` – ein Eintrag JE
    tatsächlichem Agenten-Aufruf dieses Laufs (Delegation/Konsolidierung/Fachteam-Mitglieder
    zählen dabei getrennt, genau wie sie im Ergebnis-Protokoll erscheinen). Rein additiv wie
    core/project_status.py.record_run() – ein I/O-Fehler beim Schreiben darf einen sonst
    erfolgreichen Lauf nie zum Scheitern bringen (siehe _save()).
    """
    runs = _load()
    runs.append({
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "project_slug": project_slug,
        "task_summary": task_summary[:120],
        "verification_ok": verification_ok,
        "total_tokens": total_tokens,
        "duration_seconds": round(duration_seconds, 1),
        "agent_results": agent_results,
    })
    runs = runs[-MAX_RUNS_KEPT:]
    _save(runs)


def get_recent_runs(limit: int = 20) -> list[dict]:
    """Neueste Läufe zuerst, gedeckelt auf `limit`."""
    return list(reversed(_load()))[:limit]


def get_agent_success_rates(limit_runs: int = 50) -> list[dict]:
    """
    Erfolgsquote je Agent über die letzten `limit_runs` Läufe – sortiert nach Anzahl der
    Aufrufe absteigend (die aktivsten Agenten zuerst, statt alphabetisch). Ein Agent, der nie
    aufgerufen wurde, taucht schlicht nicht auf (kein künstlicher 0-Eintrag).
    """
    runs = _load()[-limit_runs:]
    stats: dict[str, dict[str, int]] = {}
    for run in runs:
        for res in run.get("agent_results", []):
            agent_id = res.get("agent_id", "?")
            entry = stats.setdefault(agent_id, {"calls": 0, "successes": 0})
            entry["calls"] += 1
            if res.get("success"):
                entry["successes"] += 1

    result = [
        {
            "agent_id": agent_id,
            "calls": s["calls"],
            "successes": s["successes"],
            "success_rate": round(100 * s["successes"] / s["calls"], 1) if s["calls"] else 0.0,
        }
        for agent_id, s in stats.items()
    ]
    return sorted(result, key=lambda r: r["calls"], reverse=True)


def get_agent_model_performance(limit_runs: int = 100) -> list[dict]:
    """
    Erfolgsquote und durchschnittlicher Tokenverbrauch je (Agent, tatsächlich genutztem Modell)-
    Kombination über die letzten `limit_runs` Läufe – anders als get_agent_success_rates()
    (Erfolgsquote NUR je Agent) macht das sichtbar, OB die aktuell in config.py konfigurierte
    Modellzuweisung eines Agenten tatsächlich die empirisch beste ist, z. B. nach einem
    manuellen Modellwechsel in der .env. Grundlage für core/optimization_advisor.py.

    `agent_results`-Einträge aus Läufen VOR dieser Erweiterung enthalten noch kein
    `model_used` – werden unter "unbekannt" gruppiert statt zu crashen oder verworfen zu werden
    (Rückwärtskompatibilität mit bereits bestehenden memory/run_history.json-Einträgen).
    """
    runs = _load()[-limit_runs:]
    stats: dict[tuple[str, str], dict[str, int]] = {}
    for run in runs:
        for res in run.get("agent_results", []):
            agent_id = res.get("agent_id", "?")
            model = res.get("model_used") or "unbekannt"
            entry = stats.setdefault((agent_id, model), {"calls": 0, "successes": 0, "total_tokens": 0})
            entry["calls"] += 1
            if res.get("success"):
                entry["successes"] += 1
            entry["total_tokens"] += res.get("total_tokens", 0)

    result = [
        {
            "agent_id": agent_id,
            "model": model,
            "calls": s["calls"],
            "successes": s["successes"],
            "success_rate": round(100 * s["successes"] / s["calls"], 1) if s["calls"] else 0.0,
            "avg_tokens": round(s["total_tokens"] / s["calls"], 0) if s["calls"] else 0.0,
        }
        for (agent_id, model), s in stats.items()
    ]
    return sorted(result, key=lambda r: (r["agent_id"], -r["calls"]))


def get_total_tokens_for_project(project_slug: str) -> int:
    """
    Summiert `total_tokens` über ALLE bisher aufgezeichneten Läufe eines Projekts (bereits
    vorhandene Lauf-Historie, nur gefiltert) – Grundlage für das Pro-Projekt-Kostenbudget
    (`/constitution` `max_project_tokens`, agents/orchestrator.py): MAX_RUN_TOKENS begrenzt nur
    EINEN einzelnen Lauf, ein Projekt mit vielen aufeinanderfolgenden Läufen hatte bisher kein
    Limit über ALLE Läufe hinweg. Läuft dieses Projekt noch nie/über MAX_RUNS_KEPT hinaus
    gealtert -> 0 (unterschätzt in diesem Randfall eher, statt fälschlich zu blockieren).
    """
    return sum(run.get("total_tokens", 0) for run in _load() if run.get("project_slug") == project_slug)


def _load() -> list[dict]:
    if not RUN_HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(RUN_HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save(runs: list[dict]) -> None:
    try:
        RUN_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        RUN_HISTORY_FILE.write_text(json.dumps(runs, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
