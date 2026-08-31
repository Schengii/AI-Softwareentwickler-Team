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
CHECKPOINT_FILENAME = ".ai_team_checkpoint.json"
STATE_MD_FILENAME = "PROJECT_STATE.md"
MAX_HISTORY_ENTRIES = 10

# Wie viele Zeichen des rohen Verifikations-Reports (verification_summary aus
# agents/orchestrator.py) in der Lauf-Historie gespeichert werden. Realer Fund: bisher wurde
# nur der Boolean verification_ok persistiert - bei wiederholt fehlschlagenden Läufen an
# demselben Projekt (z.B. api_health_monitor: 4 Läufe in Folge, davon einer per Budget
# abgebrochen) hatte kein künftiger Agent Zugriff auf die KONKRETE Fehlermeldung des letzten
# Versuchs und wiederholte denselben vollen (kostenpflichtigen) Lauf, statt gezielt den
# bekannten Fehler zu beheben. Gedeckelt wie MAX_RULE_LENGTH in
# memory/agent_knowledge_base.py, aus demselben Grund (Tokenverbrauch bei jeder künftigen
# Injektion in format_context_for_agents).
MAX_FAILURE_DETAIL_CHARS = 500


def _status_path(project_dir: str) -> Path:
    return Path(project_dir) / STATUS_FILENAME


def _checkpoint_path(project_dir: str) -> Path:
    return Path(project_dir) / CHECKPOINT_FILENAME


def _state_md_path(project_dir: str) -> Path:
    return Path(project_dir) / STATE_MD_FILENAME


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


def read_project_state_md(project_dir: str) -> str:
    """Liest die PROJECT_STATE.md des Projekts ein – leerer String, falls noch keine existiert."""
    path = _state_md_path(project_dir)
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def generate_project_state_md(
    project_dir: str,
    task_summary: str = "",
    verification_ok: bool = False,
    budget_aborted: bool = False,
    cancelled: bool = False,
    files_written: list[str] | None = None,
    next_steps: list[str] | None = None,
) -> str:
    """Generiert einen kompakten, token-effizienten PROJECT_STATE.md-Bericht für das Projekt."""
    p_path = Path(project_dir)
    project_name = p_path.name or "Projekt"

    # Status-Badge
    if verification_ok:
        status_label = "✅ Vollständig verifiziert & einsatzbereit"
    elif cancelled:
        status_label = "⏹️ Lauf manuell pausiert"
    elif budget_aborted:
        status_label = "🚫 Lauf-Budget erreicht (Teilstand gesichert)"
    else:
        status_label = "⚠️ In Entwicklung / Verifikation ausstehend"

    # Dateien ermitteln
    existing_files: list[str] = []
    try:
        for f in p_path.rglob("*"):
            if f.is_file() and not any(part.startswith((".", "__pycache__", "node_modules", "venv")) for part in f.parts):
                rel = f.relative_to(p_path).as_posix()
                if rel != STATE_MD_FILENAME and rel != STATUS_FILENAME and rel != CHECKPOINT_FILENAME:
                    existing_files.append(rel)
    except OSError:
        pass

    now_iso = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        f"# 📌 {project_name} – Projekt-Status & Checkpoint",
        "",
        f"- **Letzte Aktualisierung:** `{now_iso}`",
        f"- **Aktueller Status:** {status_label}",
        f"- **Zuletzt bearbeitete Aufgabe:** {task_summary or 'Projekt-Initialisierung'}",
        "",
        "## 📁 Wichtige Projektkomponenten & Dateien",
    ]

    if existing_files:
        for f in sorted(existing_files)[:20]:
            lines.append(f"- `{f}`")
        if len(existing_files) > 20:
            lines.append(f"- *... und {len(existing_files) - 20} weitere Dateien*")
    else:
        lines.append("- *(Noch keine Quellcodedateien angelegt)*")

    lines += [
        "",
        "## 🧪 Verifikations- & Test-Status",
        f"- **Tests bestanden:** {'Ja ✅' if verification_ok else 'Ausstehend / Fehlgeschlagen ⚠️'}",
    ]

    lines += [
        "",
        "## 🎯 Nächste empfohlene Schritte (Next Actions)",
    ]

    if next_steps:
        for i, step in enumerate(next_steps, start=1):
            lines.append(f"{i}. {step}")
    else:
        if not verification_ok:
            lines.append("1. Testsuite ausführen und offene Fehler beheben (`/run-tests`).")
            lines.append("2. Fehlende REST-/WebSocket-Endpunkte und Validierungen komplettieren.")
        else:
            lines.append("1. Anwendung lokal per Docker oder Uvicorn starten (`/deploy`).")
            lines.append("2. Nächstes Feature im Frontend oder Backend implementieren.")

    return "\n".join(lines) + "\n"


def save_project_checkpoint(
    project_dir: str,
    task_summary: str = "",
    verification_ok: bool = False,
    budget_aborted: bool = False,
    cancelled: bool = False,
    files_written_count: int = 0,
    files_written: list[str] | None = None,
    next_steps: list[str] | None = None,
    verification_summary: str = "",
    clarification_questions: list[str] | None = None,
) -> None:
    """Speichert sowohl .ai_team_status.json als auch die lesbare PROJECT_STATE.md im Projektordner."""
    # 1. Update .ai_team_status.json
    record_run(
        project_dir=project_dir,
        task_summary=task_summary,
        verification_ok=verification_ok,
        budget_aborted=budget_aborted,
        files_written_count=files_written_count,
        cancelled=cancelled,
        verification_summary=verification_summary,
        clarification_questions=clarification_questions,
    )

    # 2. Update PROJECT_STATE.md
    state_content = generate_project_state_md(
        project_dir=project_dir,
        task_summary=task_summary,
        verification_ok=verification_ok,
        budget_aborted=budget_aborted,
        cancelled=cancelled,
        files_written=files_written,
        next_steps=next_steps,
    )

    try:
        _state_md_path(project_dir).write_text(state_content, encoding="utf-8")
    except OSError:
        pass


def record_run(
    project_dir: str,
    task_summary: str,
    verification_ok: bool,
    budget_aborted: bool,
    files_written_count: int,
    cancelled: bool = False,
    verification_summary: str = "",
    clarification_questions: list[str] | None = None,
) -> None:
    """Fügt diesen Lauf vorne in die Historie ein (neueste zuerst), gedeckelt auf
    MAX_HISTORY_ENTRIES."""
    history = read_status(project_dir)
    entry = {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "task_summary": task_summary,
        "verification_ok": verification_ok,
        "budget_aborted": budget_aborted,
        "cancelled": cancelled,
        "files_written_count": files_written_count,
    }
    if verification_summary.strip():
        # Bei Fehlschlag als failure_detail (siehe format_context_for_agents-Eskalation unten),
        # bei Erfolg als success_detail - Punkt 5 einer Team-Retrospektive: bisher wurde ein
        # verification_summary NUR bei Fehlschlag gespeichert. Für spätere Regressionsanalyse
        # ("lief der letzte grüne Lauf wirklich durch Lint/SAST/Coverage/Smoke, oder nur durch
        # nackte Tests?") fehlte dieselbe Information beim Erfolgsfall komplett.
        key = "failure_detail" if not verification_ok else "success_detail"
        entry[key] = verification_summary.strip()[:MAX_FAILURE_DETAIL_CHARS]
    # Realer Fund: ask_human_for_clarification-Rückfragen (core/agent_toolbox.py) wurden bisher
    # NUR im Chat-Verlauf der jeweiligen Sitzung sichtbar, nie in der projektübergreifenden
    # Historie - ein späterer Lauf (ggf. andere Sitzung) wusste nichts von einer offenen Frage
    # und wiederholte denselben Rateversuch, statt sie erneut zu stellen oder gezielt
    # aufzugreifen. Wie failure_detail gedeckelt (max. 3 Fragen, je auf MAX_FAILURE_DETAIL_CHARS).
    if clarification_questions:
        entry["open_questions"] = [q.strip()[:MAX_FAILURE_DETAIL_CHARS] for q in clarification_questions if q.strip()][:3]
    history.insert(0, entry)
    history = history[:MAX_HISTORY_ENTRIES]
    try:
        _status_path(project_dir).write_text(
            json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8",
        )
    except OSError:
        pass


def format_context_for_agents(project_dir: str, max_entries: int = 3) -> str:
    """
    Formatiert den aktuellen Projekt-Checkpoint (PROJECT_STATE.md) sowie die letzten Läufe
    als kompakten, token-effizienten Kontext-Block für die Aufgabenbeschreibung der Agenten.
    """
    sections = []
    state_md = read_project_state_md(project_dir)
    if state_md:
        sections.append(f"## 📌 Aktueller Projekt-Checkpoint (`{STATE_MD_FILENAME}`):\n{state_md}")

    history = read_status(project_dir)[:max_entries]
    if history:
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
        sections.append("\n".join(lines))

        # Realer Fund: ein Projekt (api_health_monitor) scheiterte 4 Läufe in Folge an
        # verwandten Ursachen, u.a. weil jeder neue Lauf blind erneut das komplette Feature
        # anging statt gezielt den zuvor protokollierten Fehler zu beheben - das verbrauchte
        # wiederholt Budget, ohne die eigentliche Ursache zu schließen (siehe
        # memory/diagnosing-verification-failures.md). Sind die letzten beiden Läufe BEIDE
        # nicht verifiziert, wird die konkrete Fehlermeldung des jüngsten fehlgeschlagenen
        # Laufs explizit vorangestellt statt nur der Status-Icon-Liste - macht "wiederhole
        # nicht denselben Fehler" konkret statt generisch.
        if has_repeated_failure(project_dir):
            last_detail = next((e.get("failure_detail") for e in history if e.get("failure_detail")), "")
            escalation = (
                "⚠️ **Wiederholtes Scheitern:** Die letzten 2 Läufe an diesem Projekt waren BEIDE nicht "
                "verifiziert. Starte NICHT einfach einen weiteren vollständigen Versuch - lies zuerst den "
                "konkreten Fehler des letzten Laufs unten und behebe GEZIELT diese Ursache, bevor du "
                "irgendetwas anderes am Projekt änderst."
            )
            if last_detail:
                escalation += f"\n\nLetzter konkreter Fehler:\n```\n{last_detail}\n```"
            sections.append(escalation)

        # Anders als die "wiederholtes Scheitern"-Eskalation oben (erst nach 2 Fehlschlägen in
        # Folge) wird eine offene Rückfrage schon nach dem EINEN Lauf angezeigt, der sie
        # aufgeworfen hat - eine ungeklärte, für die Aufgabe entscheidende Unklarheit blockiert
        # sofort sinnvolle Weiterarbeit, nicht erst nach einer Wiederholung.
        last_open_questions = history[0].get("open_questions") if history else None
        if last_open_questions:
            questions_text = "\n".join(f"- {q}" for q in last_open_questions)
            sections.append(
                "❓ **Offene Rückfrage(n) aus dem letzten Lauf:** Ein vorheriger Agent hat diese Fragen "
                f"als entscheidend markiert, aber noch keine Antwort erhalten:\n{questions_text}\n\n"
                "Kläre sie (per erneutem `ask_human_for_clarification` oder, falls inzwischen eindeutig "
                "beantwortbar, direkt in deiner Umsetzung), statt sie stillschweigend zu ignorieren."
            )

    return "\n\n".join(sections)


def has_repeated_failure(project_dir: str, streak: int = 2) -> bool:
    """True, wenn die letzten `streak` Läufe an diesem Projekt ALLE nicht verifiziert waren -
    dasselbe Kriterium, das format_context_for_agents() für die Eskalations-Warnung nutzt,
    hier auch für agents/orchestrator.py nutzbar, um vor einem weiteren vollen Lauf ein
    härteres Gate zu ziehen (siehe _run_governance_fix_loop dort), statt sich allein auf den
    Prompt-Text zu verlassen."""
    recent = read_status(project_dir)[:streak]
    return len(recent) == streak and all(not e.get("verification_ok") for e in recent)


