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

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

# ── Lebenszyklus (append-only) ──────────────────────────────────────────────────────────────
# Lektionen wurden bisher nur angehängt - nie als erledigt markiert. Dieselbe Empfehlung
# ("`jwt` durch PyJWT ersetzen") entstand dadurch an zwei aufeinanderfolgenden Tagen erneut,
# obwohl sie längst umgesetzt war, und belegte weiter die knappen Prompt-Plätze.
# Statusänderungen und Wiederholungen werden als eigene Ereigniszeilen angehängt (die
# Nachvollziehbarkeit des append-only-Logs bleibt erhalten); `read_lesson_index()` fasst sie
# je Signatur zusammen.
LESSON_STATUSES = ("open", "implemented", "verified", "archived")
# Diese Status gelten als abgeschlossen und werden Agenten nicht mehr als Warnung gezeigt.
CLOSED_LESSON_STATUSES = frozenset({"verified", "archived"})
_EVENT_STATUS = "lesson_status"
_EVENT_RECURRENCE = "lesson_recurrence"

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
            # Wiederholung zählen statt still verwerfen - Häufigkeit ist ein Relevanzsignal,
            # und eine bereits als erledigt markierte Lektion wird dadurch wieder geöffnet.
            # Höchstens ein Ereignis je Signatur, Projekt und Tag, damit die Datei nicht wächst,
            # wenn derselbe Lauf dieselbe Lektion mehrfach meldet.
            signature = lesson_signature(category, detail)
            if not _recurrence_recorded_today(signature, project_slug):
                _append_event({"event": _EVENT_RECURRENCE, "signature": signature, "project_slug": project_slug})
            return
    try:
        TEAM_MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "project_slug": project_slug,
            "category": category,
            "detail": detail,
            "signature": lesson_signature(category, detail),
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
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Ereigniszeilen (Status/Wiederholung) sind keine eigenständigen Lektionen.
                if isinstance(record, dict) and "event" not in record:
                    lessons.append(record)
    except OSError:
        return []
    return lessons[-limit:][::-1]


def format_team_lessons_for_agents(
    limit: int = MAX_LESSONS_SHOWN, prioritize_slug: str = "", context: str = "",
) -> str:
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
    # Abgeschlossene Lektionen (verifiziert/archiviert) sind kein Warnsignal mehr.
    index = read_lesson_index()
    pool = [
        entry for entry in pool
        if index.get(_entry_signature(entry), {}).get("status", "open") not in CLOSED_LESSON_STATUSES
    ]
    if context.strip():
        # Relevanz statt reiner Aktualität: Lektionen, die fachlich zum Auftrag passen (Stack,
        # Rolle, Dateitypen), kommen zuerst; bei Gleichstand bleibt die Rezenz-Reihenfolge.
        pool = rank_lessons_by_relevance(pool, context, index)
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


# ── Lebenszyklus & Relevanz ─────────────────────────────────────────────────────────────────
_TOKEN_RE = re.compile(r"[a-zA-ZäöüÄÖÜß_][\w.-]{2,}")
_STOPWORDS = frozenset({
    "der", "die", "das", "und", "oder", "nicht", "mit", "für", "von", "den", "dem", "ein", "eine",
    "ist", "sind", "wird", "werden", "bei", "auf", "aus", "als", "auch", "noch", "nur", "wenn",
    "the", "and", "for", "with", "this", "that", "from", "agent", "agents", "projekt", "datei",
})


def lesson_signature(category: str, detail: str) -> str:
    """Stabile Kennung einer Lektion (Kategorie + normalisierter Kern)."""
    return hashlib.sha1(f"{category}|{_normalize(detail)}".encode()).hexdigest()[:16]


def _entry_signature(entry: dict) -> str:
    return str(entry.get("signature") or lesson_signature(str(entry.get("category", "")), str(entry.get("detail", ""))))


def _append_event(record: dict) -> None:
    try:
        TEAM_MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TEAM_MEMORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": datetime.now(UTC).isoformat(), **record}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _read_raw_records() -> list[dict]:
    if not TEAM_MEMORY_FILE.exists():
        return []
    records: list[dict] = []
    try:
        with open(TEAM_MEMORY_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    records.append(record)
    except OSError:
        return []
    return records


def _recurrence_recorded_today(signature: str, project_slug: str) -> bool:
    today = datetime.now(UTC).date().isoformat()
    for record in reversed(_read_raw_records()):
        if not str(record.get("timestamp", "")).startswith(today):
            if record.get("event") != _EVENT_RECURRENCE:
                break
            continue
        if (
            record.get("event") == _EVENT_RECURRENCE
            and record.get("signature") == signature
            and record.get("project_slug") == project_slug
        ):
            return True
    return False


def update_lesson_status(signature: str, status: str, resolution: str = "") -> bool:
    """Setzt den Status einer Lektion (append-only Ereignis). False bei unbekannter Signatur/Status."""
    if status not in LESSON_STATUSES:
        return False
    if signature not in read_lesson_index():
        return False
    _append_event({"event": _EVENT_STATUS, "signature": signature, "status": status, "resolution": resolution[:300]})
    return True


def read_lesson_index() -> dict[str, dict]:
    """Aggregierte Sicht je Signatur: erste Lektion + occurrences, projects, status, resolution."""
    index: dict[str, dict] = {}
    for record in _read_raw_records():
        event = record.get("event")
        if event is None:
            if not str(record.get("detail", "")).strip():
                continue
            signature = _entry_signature(record)
            entry = index.get(signature)
            if entry is None:
                index[signature] = {
                    **record, "signature": signature, "occurrences": 1, "status": "open", "resolution": "",
                    "last_seen": record.get("timestamp", ""), "projects": sorted({str(record.get("project_slug", ""))}),
                }
            else:
                entry["occurrences"] += 1
                entry["last_seen"] = record.get("timestamp", entry["last_seen"])
                entry["projects"] = sorted(set(entry["projects"]) | {str(record.get("project_slug", ""))})
        elif event == _EVENT_RECURRENCE:
            entry = index.get(str(record.get("signature")))
            if entry is not None:
                entry["occurrences"] += 1
                entry["last_seen"] = record.get("timestamp", entry["last_seen"])
                entry["projects"] = sorted(set(entry["projects"]) | {str(record.get("project_slug", ""))})
                # Ein erneut auftretender Fehler öffnet eine nur "umgesetzte" Lektion wieder -
                # die Umsetzung hat offenbar nicht gegriffen.
                if entry["status"] in ("implemented", "verified"):
                    entry["status"] = "open"
                    entry["resolution"] = f"wieder aufgetreten nach: {entry['resolution']}".strip()
        elif event == _EVENT_STATUS:
            entry = index.get(str(record.get("signature")))
            if entry is not None and record.get("status") in LESSON_STATUSES:
                entry["status"] = record["status"]
                entry["resolution"] = str(record.get("resolution") or "")
    return index


def _tokens(text: str) -> set[str]:
    return {t.lower().strip(".-") for t in _TOKEN_RE.findall(text or "")} - _STOPWORDS


def rank_lessons_by_relevance(lessons: list[dict], context: str, index: dict[str, dict] | None = None) -> list[dict]:
    """Sortiert Lektionen nach fachlicher Nähe zum Kontext (stabil, Rezenz bleibt Tiebreaker)."""
    context_tokens = _tokens(context)
    if not context_tokens:
        return list(lessons)
    index = index if index is not None else {}

    def score(item: tuple[int, dict]) -> tuple[float, int]:
        position, entry = item
        overlap = len(context_tokens & _tokens(str(entry.get("detail", ""))))
        occurrences = int(index.get(_entry_signature(entry), {}).get("occurrences", 1))
        severity = 0.0 if entry.get("category") in _LOW_SEVERITY_CATEGORIES else 1.0
        return (-(overlap * 3.0 + min(occurrences, 5) * 0.5 + severity), position)

    return [entry for _, entry in sorted(enumerate(lessons), key=score)]


def auto_link_lessons_to_rules() -> list[tuple[str, str]]:
    """Markiert offene Lektionen als "implemented", deren Kern bereits durch eine Regel im
    zentralen Regelwerk (core/known_pitfalls.PITFALL_CATALOG) abgedeckt ist.

    Rückgabe: Liste (Signatur, rule_id) der neu verknüpften Lektionen. Tritt der Fehler danach
    erneut auf, öffnet `read_lesson_index()` die Lektion automatisch wieder.
    """
    from core.known_pitfalls import PITFALL_CATALOG

    linked: list[tuple[str, str]] = []
    for signature, entry in read_lesson_index().items():
        if entry.get("status") != "open":
            continue
        detail = str(entry.get("detail", "")).lower()
        matching = [
            rule for rule in PITFALL_CATALOG
            if rule.match_keywords and all(k.lower() in detail for k in rule.match_keywords)
        ]
        if not matching:
            continue
        # Spezifischste Regel gewinnt (meiste Schlüsselbegriffe), z. B. "Re-Export in __init__.py"
        # vor der allgemeinen __init__.py-Regel.
        rule = max(matching, key=lambda r: len(r.match_keywords))
        if update_lesson_status(signature, "implemented", f"Regel {rule.rule_id} ({rule.enforced_by})"):
            linked.append((signature, rule.rule_id))
    return linked


def format_lesson_board(limit: int = 30) -> str:
    """Übersicht für Menschen (CLI/Dashboard): offene Lektionen zuerst, nach Häufigkeit."""
    index = read_lesson_index()
    if not index:
        return "Noch keine Team-Lektionen aufgezeichnet."
    order = {"open": 0, "implemented": 1, "verified": 2, "archived": 3}
    entries = sorted(index.values(), key=lambda e: (order.get(e["status"], 9), -e["occurrences"], e.get("last_seen", "")))
    lines = ["| Status | ×  | Kategorie | Projekte | Lektion | Signatur |", "|---|---|---|---|---|---|"]
    for e in entries[:limit]:
        detail = str(e.get("detail", "")).replace("\n", " ").replace("|", "/")[:90]
        projects = ", ".join(e.get("projects", [])[:3])
        lines.append(f"| {e['status']} | {e['occurrences']} | {e.get('category', '')} | {projects} | {detail} | `{e['signature']}` |")
    open_count = sum(1 for e in index.values() if e["status"] == "open")
    lines.append(f"\n{open_count} von {len(index)} Lektionen offen.")
    return "\n".join(lines)

