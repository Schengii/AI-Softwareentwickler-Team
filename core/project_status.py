"""
core/project_status.py – Persistenter Projekt-Status für Kontinuität über mehrere Sitzungen

Realer Fund: memory/conversation_history.py ist SITZUNGS-gebunden (memory/history_<session>.json)
– startet der Nutzer eine neue Sitzung (neues Terminal), ist jeglicher Kontext über ein
Projekt weg, selbst wenn er per `/load` dasselbe Projekt erneut öffnet. Ein Mensch, der ein
Projekt nach Tagen wieder aufmacht, hat wenigstens ein Commit-Log oder eigene Notizen – das
Team hatte bisher nur die rohen Quelldateien, ohne jede Historie oder Hinweis auf offene
Punkte (z.B. "Lauf-Budget während der Verifikation erreicht, letzter Stand nicht grün").

Schreibt/liest eine kompakte JSON-Historie direkt im Projektverzeichnis (bewusst NICHT
gitignored – im Unterschied zu .ai_team_venv/.ai_team_rag ist das echte, wertvolle
Projekt-Historie, kein Build-Artefakt, und soll mitversioniert werden).
"""

import json
from datetime import UTC, datetime
from pathlib import Path

STATUS_FILENAME = ".ai_team_status.json"
MAX_HISTORY_ENTRIES = 10


def _status_path(project_dir: str) -> Path:
    return Path(project_dir) / STATUS_FILENAME


def read_status(project_dir: str) -> list[dict]:
    """Gibt die protokollierte Lauf-Historie dieses Projekts zurück (neueste zuerst) – leere
    Liste, falls noch keine existiert oder die Datei beschädigt ist (kein Crash)."""
    path = _status_path(project_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def record_run(
    project_dir: str,
    task_summary: str,
    verification_ok: bool,
    budget_aborted: bool,
    files_written_count: int,
    cancelled: bool = False,
) -> None:
    """Fügt diesen Lauf vorne in die Historie ein (neueste zuerst), gedeckelt auf
    MAX_HISTORY_ENTRIES (älteste fällt raus – dieselbe Deckelungslogik wie
    memory/agent_knowledge_base.py, damit die Datei nicht unbegrenzt wächst).

    cancelled: True, wenn der Lauf manuell abgebrochen wurde (Strg+C in der CLI, Cancel-
    Button im Dashboard) – separat von budget_aborted, damit eine künftige Sitzung den
    ehrlichen Grund sieht (siehe format_context_for_agents()) statt "Budget erreicht" zu
    unterstellen, wo der Mensch den Lauf bewusst gestoppt hat.
    """
    history = read_status(project_dir)
    entry = {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "task_summary": task_summary,
        "verification_ok": verification_ok,
        "budget_aborted": budget_aborted,
        "cancelled": cancelled,
        "files_written_count": files_written_count,
    }
    history.insert(0, entry)
    history = history[:MAX_HISTORY_ENTRIES]
    try:
        _status_path(project_dir).write_text(
            json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8",
        )
    except OSError:
        pass


def count_consecutive_failed_runs(project_dir: str) -> int:
    """
    Zählt, wie viele der ZULETZT protokollierten Läufe (neueste zuerst) OHNE Unterbrechung
    `verification_ok=False` waren - Grundlage für eine deutlichere Warnung in
    agents/orchestrator.py, wenn dieselbe Aufgabe wiederholt an derselben Hürde scheitert,
    statt nur informativ auf `/load` hinzuweisen.

    Ein manuell abgebrochener Lauf (`cancelled=True`) zählt NICHT als Fehlschlag und
    UNTERBRICHT die Zählung - ein bewusster menschlicher Stopp sagt nichts über die
    Qualität der Aufgabe/des Agenten-Teams aus, im Unterschied zu einer nicht bestandenen
    Verifikation oder einem erreichten Budget.
    """
    count = 0
    for entry in read_status(project_dir):
        if entry.get("cancelled"):
            break
        if entry.get("verification_ok"):
            break
        count += 1
    return count


def format_context_for_agents(project_dir: str, max_entries: int = 3) -> str:
    """
    Formatiert die letzten `max_entries` Läufe als kompakten, token-effizienten Kontext-Block
    für die Aufgabenbeschreibung der Agenten – leer, wenn keine Historie existiert (kein
    leerer/unnötiger Abschnitt im Prompt). Gibt dem Team echte Kontinuität über Sitzungen
    hinweg: sieht z.B. sofort, dass der letzte Lauf am Lauf-Budget abgebrochen wurde, statt
    das nur aus den rohen Quelldateien zu erraten.
    """
    history = read_status(project_dir)[:max_entries]
    if not history:
        return ""

    lines = ["## 📜 Bisherige Läufe an diesem Projekt (neueste zuerst):"]
    for entry in history:
        if entry.get("verification_ok"):
            status_icon = "✅"
        elif entry.get("cancelled"):
            status_icon = "⏹️"
        elif entry.get("budget_aborted"):
            status_icon = "🚫"
        else:
            status_icon = "⚠️"
        lines.append(f"- {status_icon} [{entry.get('timestamp', '?')}] {entry.get('task_summary', '?')}")
    return "\n".join(lines)
