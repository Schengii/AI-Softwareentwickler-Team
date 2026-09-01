"""
core/team_memory.py – Team-weites, projektübergreifendes Lessons-Learned-Gedächtnis.

core/project_status.py hält Lauf-Historie NUR pro Projekt - ein Muster, das sich über mehrere,
unabhängige Projekte hinweg wiederholt (z.B. "vergisst regelmäßig CORS-Header bei FastAPI-
Projekten"), blieb bisher unsichtbar, weil jedes Projekt bei null anfing. Dieses Modul sammelt
kurze, faktenbasierte Lektionen (ausgelöst durch dieselben Backlog-Ticket-Momente wie
has_repeated_failure() in agents/orchestrator/__init__.py und die verpflichtenden Re-Review-
Eskalationen in agents/orchestrator/verification.py) in einer EINZIGEN, repo-weiten Datei und
speist die letzten paar davon über format_team_lessons_for_agents() in
core/project_status.py.format_context_for_agents() ein - aus Einzelfällen an einem Projekt
werden so über die Zeit wiederkehrende Regeln, die künftigen Läufen (auch an ANDEREN Projekten)
direkt mitgegeben werden, statt dass jedes Projekt bei null anfängt.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

TEAM_MEMORY_FILE = Path(__file__).resolve().parent.parent / "memory" / "team_lessons.jsonl"
MAX_LESSONS_SHOWN = 5


def record_lesson(project_slug: str, category: str, detail: str) -> None:
    """Hängt eine neue Lektion an - append-only, keine Bearbeitung/Löschung bestehender
    Einträge (dieselbe Nachvollziehbarkeits-Überlegung wie bei core/project_status.py's
    Lauf-Historie). Best-Effort: ein Schreibfehler hier darf niemals einen laufenden
    Team-Lauf zum Absturz bringen, deshalb wird jede OSError-Ausnahme verschluckt."""
    try:
        TEAM_MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "project_slug": project_slug,
            "category": category,
            "detail": detail[:400],
        }
        with open(TEAM_MEMORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def read_team_lessons(limit: int = MAX_LESSONS_SHOWN) -> list[dict]:
    """Neueste zuerst. Leere Liste, falls noch keine Lektion je aufgezeichnet wurde (der
    Normalfall für ein frisches Setup) oder die Datei nicht lesbar ist."""
    if not TEAM_MEMORY_FILE.exists():
        return []
    lessons = []
    try:
        with open(TEAM_MEMORY_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    lessons.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return lessons[-limit:][::-1]


def format_team_lessons_for_agents(limit: int = MAX_LESSONS_SHOWN) -> str:
    """Leerer String, wenn es noch keine Lektionen gibt (kein unnötiger Prompt-Text für den
    Normalfall eines frischen Setups ohne aufgezeichnete Muster)."""
    lessons = read_team_lessons(limit)
    if not lessons:
        return ""
    lines = ["## 🧠 Team-weite Lektionen aus früheren Projekten (nicht nur diesem hier):"]
    for lesson in lessons:
        lines.append(f"- [{lesson.get('project_slug', '?')}] {lesson.get('detail', '')}")
    return "\n".join(lines)
