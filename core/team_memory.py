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
import re
from datetime import UTC, datetime
from pathlib import Path

TEAM_MEMORY_FILE = Path(__file__).resolve().parent.parent / "memory" / "team_lessons.jsonl"
MAX_LESSONS_SHOWN = 5

# Wie viele der zuletzt aufgezeichneten Lektionen beim Schreiben auf ein Beinahe-Duplikat
# geprüft werden - bewusst klein und nur die jüngste Vergangenheit, kein voller Datei-Scan bei
# jedem Aufruf (die Datei kann über viele Läufe/Projekte hinweg beliebig wachsen).
_DEDUP_LOOKBACK = 50
_NORMALIZE_RE = re.compile(r"[^\w]+")

# Team-Optimierung (vollständige Umsetzung einer KI-Team-Retrospektive, echter Fund): diese
# Kategorien markieren reine Team-Selbstoptimierungs-Buchführung
# (core/optimization_advisor.py.record_suggestions_as_lessons()) - KEINEN konkreten Code-Defekt
# an einem echten Projekt. Ein einzelner Optimierungslauf kann davon viele auf einmal schreiben
# (real beobachtet: 11 `unused_agent`-Funde in derselben Sekunde) und hätte damit ohne Gewichtung
# die knappen MAX_LESSONS_SHOWN-Plätze in format_team_lessons_for_agents() rein wegen ihrer
# Rezenz für seltenere, wichtigere Befunde (echte Governance-/Verifikations-Blocker wie
# `unresolved_governance_critical`) verdrängt - genau das ist nach dem event_relay-Lauf am
# 2026-09-06 passiert.
# "deterministic_check_suggestion" (Team-Optimierung 2026-09-07, siehe
# agents/orchestrator/retrospective.py._extract_and_store_check_suggestions()) ist wie
# "unused_agent" reine TEAM-Selbstoptimierungs-Buchführung, kein konkreter Code-Defekt an einem
# Projekt - gehört deshalb ebenfalls zu den niedrigschwelligen Kategorien, damit ein einzelner
# Trainer-Report mit mehreren Vorschlägen nicht die knappen Plätze für echte Governance-Funde
# verdrängt.
_LOW_SEVERITY_CATEGORIES = frozenset({
    "model_performance", "low_performing_agent", "unused_agent", "deterministic_check_suggestion",
})
# Wie viele der MAX_LESSONS_SHOWN-Plätze mindestens für die jüngsten NICHT-niedrigschwelligen
# Lektionen reserviert sind (siehe _LOW_SEVERITY_CATEGORIES-Docstring und
# _select_with_severity_reservation()) - der Rest wird ganz normal der Reihe nach aufgefüllt,
# auch mit niedrigschwelligen Lektionen, falls nicht genug hochschwellige vorhanden sind.
_RESERVED_HIGH_SEVERITY_SLOTS = 2


def _normalize(detail: str) -> str:
    """Grobe Normalisierung für den Ähnlichkeitsvergleich - Groß/Kleinschreibung und
    Interpunktion ignorieren, nur die ersten ~80 Zeichen (der fachliche Kern einer Lektion
    steht praktisch immer am Anfang, Variationen meist erst danach)."""
    return _NORMALIZE_RE.sub(" ", detail.lower()).strip()[:80]


def record_lesson(project_slug: str, category: str, detail: str) -> None:
    """Hängt eine neue Lektion an - append-only, keine Bearbeitung/Löschung bestehender
    Einträge (dieselbe Nachvollziehbarkeits-Überlegung wie bei core/project_status.py's
    Lauf-Historie). Best-Effort: ein Schreibfehler hier darf niemals einen laufenden
    Team-Lauf zum Absturz bringen, deshalb wird jede OSError-Ausnahme verschluckt.

    Überspringt (fast-)identische Lektionen derselben Kategorie, die unter den zuletzt
    aufgezeichneten `_DEDUP_LOOKBACK` Einträgen schon vorkommen - eine wiederkehrende Regel
    (z.B. "vergisst CORS-Header bei FastAPI") soll das Muster bestätigen, nicht bei jedem
    weiteren Fund denselben Prompt-Text erneut in format_team_lessons_for_agents() aufblähen.

    Realer Fund (Analyse 2026-09-06): record_lesson() wurde mit leerem detail-String aufgerufen
    und persistierte trotzdem einen wertlosen Eintrag (leeres {"detail": ""} in team_lessons.jsonl).
    Der Selbstlern-Loop verpuffte dadurch: format_team_lessons_for_agents() sendete leere Bullet-
    Points an die Agenten, agent_trainer/retrospective lernten nichts. Leere oder nur aus
    Whitespace bestehende detail-Strings werden jetzt vor der Duplikat-Prüfung abgelehnt -
    dieselbe Validierungsphilosophie wie core/backlog_store.py beim Titel eines Tickets."""
    detail = detail[:400]
    # Kein Lerneffekt ohne Inhalt: leere/whitespace-only detail-Strings, fehlende category
    # oder project_slug werden vor der teuren Duplikat-Prüfung (read_team_lessons) abgelehnt.
    if not detail.strip():
        return
    if not category.strip():
        return
    if not project_slug.strip():
        return
    normalized = _normalize(detail)
    for recent in read_team_lessons(limit=_DEDUP_LOOKBACK):
        if recent.get("category") == category and _normalize(recent.get("detail", "")) == normalized:
            return
    try:
        TEAM_MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "project_slug": project_slug,
            "category": category,
            "detail": detail,
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


def format_team_lessons_for_agents(limit: int = MAX_LESSONS_SHOWN, prioritize_slug: str = "") -> str:
    """Leerer String, wenn es noch keine Lektionen gibt (kein unnötiger Prompt-Text für den
    Normalfall eines frischen Setups ohne aufgezeichnete Muster).

    Team-Optimierung (Retrospektive 2026-09-04): bisher immer genau die `limit` JÜNGSTEN
    Lektionen über ALLE Projekte hinweg, unabhängig davon, ob eine davon ausgerechnet FÜR
    DAS AKTUELL BEARBEITETE PROJEKT aufgezeichnet wurde. Real beobachtet an `zeiterfassung_app`:
    zwei separate "unresolved_governance_critical"-Lektionen an DEMSELBEN Projekt innerhalb
    weniger Stunden - bei wachsendem, projektübergreifendem Log droht genau die für dieses
    Projekt relevanteste Lektion aus den `limit` jüngsten herauszufallen, sobald andere
    Projekte zwischenzeitlich weitere Lektionen erzeugen. `prioritize_slug` (Standard: "" -
    Verhalten unverändert) stellt Lektionen DESSELBEN project_slug voran (jeweils intern nach
    Aktualität sortiert), der Rest der `limit` Plätze wird mit den übrigen jüngsten Lektionen
    aufgefüllt - eine bereits einmal für dieses Projekt gemachte Lektion geht so nicht mehr im
    allgemeinen Rauschen unter.

    Reserviert zusätzlich Plätze für nicht-niedrigschwellige Lektionen (siehe
    _select_with_severity_reservation()), damit ein Schwall Team-Meta-Funde (z.B. viele
    `unused_agent`-Einträge aus einem einzigen Optimierungslauf) nicht die knappen Plätze für
    seltenere, wichtigere Befunde verdrängt."""
    # read_team_lessons(limit=0) wäre "keine" (Slice-Semantik), nicht "alle" - deshalb hier ein
    # bewusst großzügiger, aber endlicher Deckel statt limit für die volle Vorauswahl, aus der
    # anschließend sowohl nach project_slug als auch nach Schweregrad ausgewählt wird.
    pool = read_team_lessons(limit=max(limit * 20, 200))
    if not prioritize_slug:
        candidates = pool
    else:
        own_project = [entry for entry in pool if entry.get("project_slug") == prioritize_slug]
        others = [entry for entry in pool if entry.get("project_slug") != prioritize_slug]
        candidates = own_project + others
    lessons = _select_with_severity_reservation(candidates, limit)
    if not lessons:
        return ""
    lines = ["## 🧠 Team-weite Lektionen aus früheren Projekten (nicht nur diesem hier):"]
    for lesson in lessons:
        lines.append(f"- [{lesson.get('project_slug', '?')}] {lesson.get('detail', '')}")
    return "\n".join(lines)


def _select_with_severity_reservation(candidates: list[dict], limit: int) -> list[dict]:
    """Wählt bis zu `limit` Lektionen aus `candidates` (bereits nach Priorität/Rezenz sortiert)
    aus - reserviert dabei zuerst bis zu _RESERVED_HIGH_SEVERITY_SLOTS Plätze für die jüngsten
    NICHT-niedrigschwelligen Lektionen (siehe _LOW_SEVERITY_CATEGORIES-Docstring), füllt die
    restlichen Plätze dann ganz normal der Reihe nach auf (auch mit niedrigschwelligen, falls
    nicht genug hochschwellige vorhanden sind). Die Ausgabe bleibt in der ursprünglichen
    Reihenfolge von `candidates` (Priorität/Rezenz) - nur die AUSWAHL ist gewichtet, kein
    zusätzliches Umsortieren, das die bestehende prioritize_slug-Reihenfolge durcheinanderbringen
    würde."""
    if limit <= 0 or not candidates:
        return []
    selected_indices: set[int] = set()
    reserved_remaining = _RESERVED_HIGH_SEVERITY_SLOTS
    for i, entry in enumerate(candidates):
        if len(selected_indices) >= limit or reserved_remaining <= 0:
            break
        if entry.get("category") not in _LOW_SEVERITY_CATEGORIES:
            selected_indices.add(i)
            reserved_remaining -= 1
    for i in range(len(candidates)):
        if len(selected_indices) >= limit:
            break
        selected_indices.add(i)
    return [candidates[i] for i in sorted(selected_indices)]
