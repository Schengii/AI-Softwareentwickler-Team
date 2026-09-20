"""
core/team_health.py – Projektübergreifender Health-Rollup über workspace/

Realer Fund: jedes Projekt in workspace/<projekt>/ trägt seine eigene Lauf-Historie in
.ai_team_status.json (core/project_status.py), aber es gab bisher KEINEN Befehl, der über ALLE
Projekte hinweg einen Überblick gibt. Um ein systemisches Muster zu erkennen - z.B. "3 Projekte
scheitern gerade alle am selben Frontend-404-Muster, weil ein gemeinsamer Baustein kaputt ist" -
musste bisher jedes .ai_team_status.json einzeln von Hand gelesen werden. `/team-health`
(interface/cli.py) nutzt diesen Rollup, um das sichtbar zu machen.
"""

from dataclasses import dataclass, field
from pathlib import Path

from core.project_status import STATUS_FILENAME, read_full_detail, read_status

# Kategorisierungs-Marker für failure_detail-Texte, wie sie tatsächlich von
# agents/orchestrator.py._run_verification_loop() in verification_summary erzeugt werden (siehe
# summary_lines.append(...) dort) - bewusst die ECHTEN, im Projekt bereits konsistent genutzten
# Icons/Präfixe wiederverwendet statt eigene Marker zu erfinden. Reihenfolge ist Priorität: der
# erste zutreffende Marker gewinnt, falls ein failure_detail mehrere Zeilen/Kategorien enthält.
#
# Realer Fund (Roadmap P0-5, 2026-09-20): die Liste kannte die drei Fehlerarten nicht, die die
# Verifikation heute am häufigsten erzeugt - offene Sicherheits-Übergabe, Vollständigkeits-Veto
# und Pre-Flight-Abbruch. 8 von 12 roten Projekten landeten dadurch im Sammeltopf "Sonstiger
# Fehler" (aegisflow, cachegrid_proxy, devpulse, ecotrack_ai, eventstream_zero,
# nexus_resilience_gateway, nexusforge, pipeline_pilot), obwohl aegisflow und ecotrack_ai
# nachweislich dasselbe Muster teilten. Genau dieses Muster sichtbar zu machen ist der Zweck
# von shared_patterns - für die dominanten Fehlerklassen war es blind.
#
# Die `❌ **Verifikations-Veto durch X`-Zeilen sind die verlässlichsten Marker: sie werden in
# agents/orchestrator/verification.py an genau einer Stelle je Veto-Art erzeugt und benennen den
# blockierenden Grund, während ein Icon wie `🔍` auch in rein informativen Fortschrittszeilen
# ("Pre-Flight-Check, Versuch 1: 2 Problem(e) → zur Korrektur zurückgespielt") vorkommt und
# deshalb allein nichts über einen Fehlschlag aussagt.
#
# Lint steht bewusst GANZ HINTEN: `lint` ist ein informativer Check (siehe
# agents/orchestrator/verification_checks.py.INFORMATIONAL_CHECK_KEYS) und beeinflusst
# `verification_ok` nie. Vor `Testfehler` platziert, hätte eine harmlose ruff-Warnung einen
# echten Testfehlschlag als Kategorie verdrängt.
_CATEGORY_MARKERS: list[tuple[str, str]] = [
    # Blockierende Vetos zuerst - sie benennen den tatsächlichen Grund für den roten Lauf.
    ("Verifikations-Veto durch offene Sicherheits-Übergabe", "Sicherheits-Übergabe offen"),
    ("Verifikations-Veto durch Completeness-Check", "Vollständigkeit (Stub/Platzhalter)"),
    ("Verifikations-Veto durch Test-Schrumpfung", "Test-Schrumpfung (Tests statt Fehler entfernt)"),
    ("Verifikations-Veto durch Browser-UI-Check", "Frontend/UI-Check"),
    ("Verifikations-Veto durch Runtime-Smoke-Test", "Runtime-Smoke-Test"),
    ("Verifikations-Veto durch Lastentest", "Lastentest"),
    ("Verifikations-Veto durch Coverage-Check", "Testabdeckung unter Schwelle"),
    ("🌐 ❌", "Frontend/UI-Check"),
    ("🚀 ❌", "Runtime-Smoke-Test"),
    ("🏋️ ❌", "Lastentest"),
    ("🐳 ❌", "Docker-Build"),
    ("🔓 ❌", "Dependency-Audit (Schwachstellen)"),
    ("📊 ❌", "Testabdeckung unter Schwelle"),
    # Abbruch-Marker der Fix-Schleifen: "dieselben Fund(e) wie nach dem vorherigen Fixversuch".
    ("🔍 🛑", "Pre-Flight-Check (Schleife ohne Fortschritt)"),
    ("🧩 🛑", "Vorab-/Vollständigkeits-Check (Schleife ohne Fortschritt)"),
    ("🔍 ❌", "Pre-Flight-Check (ungelöste Funde)"),
    ("🚫 ", "Token-Budget erreicht"),
    ("Testfehler", "Testsuite"),
    ("🎨", "Lint"),
    ("ruff:", "Lint (ruff)"),
]
_FALLBACK_CATEGORY = "Sonstiger Fehler"


def categorize_failure(failure_detail: str) -> str:
    """Ordnet einen failure_detail-Text (aus .ai_team_status.json) einer groben Fehlerkategorie
    zu, anhand der Icons/Präfixe, die die Verifikation tatsächlich erzeugt (siehe
    _CATEGORY_MARKERS oben). Leerer Text oder kein bekannter Marker → _FALLBACK_CATEGORY, damit
    das Projekt trotzdem sichtbar bleibt statt stillschweigend zu verschwinden."""
    if not failure_detail:
        return _FALLBACK_CATEGORY
    for marker, category in _CATEGORY_MARKERS:
        if marker in failure_detail:
            return category
    return _FALLBACK_CATEGORY


@dataclass
class ProjectHealth:
    """Zusammengefasster Gesundheitszustand EINES Projekts, aus seinem neuesten
    .ai_team_status.json-Eintrag plus der Streak-Länge an der Historie-Spitze."""

    name: str
    status: str  # "ok" | "failed" | "budget_aborted" | "cancelled" | "unknown"
    timestamp: str
    task_summary: str
    red_streak: int  # wie viele Läufe in Folge (an der Historie-Spitze) nicht "ok" waren
    failure_detail: str = ""
    failure_category: str = ""


@dataclass
class TeamHealthRollup:
    """Ergebnis von build_team_health_rollup(): pro Projekt der aktuelle Zustand, sortiert nach
    Dringlichkeit, sowie erkannte gemeinsame Fehlermuster über mehrere Projekte hinweg."""

    projects: list[ProjectHealth] = field(default_factory=list)
    shared_patterns: dict[str, list[str]] = field(default_factory=dict)  # Kategorie -> Projektnamen


def _latest_status(entry: dict) -> str:
    if entry.get("verification_ok"):
        return "ok"
    if entry.get("cancelled"):
        return "cancelled"
    if entry.get("budget_aborted"):
        return "budget_aborted"
    return "failed"


def _red_streak(history: list[dict]) -> int:
    """Zählt, wie viele Läufe in Folge an der Historie-Spitze NICHT verifiziert waren. Ein
    manueller Abbruch (cancelled) oder Budget-Stop zählt bewusst NICHT als "rot" - dieselbe
    Ausnahme wie in core/project_status.has_repeated_failure(), aus demselben Grund: der Mensch
    hat den Lauf beendet, das Team hat nicht versagt."""
    streak = 0
    for entry in history:
        if entry.get("verification_ok"):
            break
        if entry.get("cancelled") or entry.get("budget_aborted"):
            break
        streak += 1
    return streak


def build_team_health_rollup(workspace_dir: str) -> TeamHealthRollup:
    """Durchsucht alle Unterverzeichnisse von workspace_dir nach .ai_team_status.json, baut pro
    Projekt einen ProjectHealth-Eintrag und gruppiert Projekte mit derselben erkannten
    Fehlerkategorie zu shared_patterns (nur Kategorien mit >= 2 betroffenen Projekten - ein
    einzelnes rotes Projekt ist kein "Muster"). Projekte sortiert nach Dringlichkeit: am
    längsten rot zuerst, dann nach Fehlerkategorie gruppiert (damit zusammengehörige Ausfälle
    in der Ausgabe auch nebeneinander stehen), dann alphabetisch nach Namen für stabile
    Reihenfolge."""
    base = Path(workspace_dir)
    projects: list[ProjectHealth] = []

    if base.exists():
        for entry_dir in sorted(base.iterdir(), key=lambda p: p.name):
            if not entry_dir.is_dir():
                continue
            if not (entry_dir / STATUS_FILENAME).exists():
                continue
            history = read_status(str(entry_dir))
            if not history:
                continue
            latest = history[0]
            status = _latest_status(latest)
            # Nur ein echtes "failed" (verification_ok=False, weder budget_aborted noch
            # cancelled) bekommt eine Fehlerkategorie - ein Budget-Abbruch oder manueller
            # Abbruch ist kein inhaltlicher Fehler und hat oft gar kein failure_detail, würde
            # sonst fälschlich mit anderen Projekten unter "Sonstiger Fehler" zusammengelegt.
            failure_detail = latest.get("failure_detail", "") if status == "failed" else ""
            # Kategorisiert gegen das VOLLSTÄNDIGE Protokoll, nicht gegen den in
            # .ai_team_status.json auf MAX_FAILURE_DETAIL_CHARS (500) gekürzten Auszug:
            # das Verifikationsprotokoll beginnt mit den frühen, informativen Schritten
            # (Manifest-Ergänzungen, Pre-Flight-Runden) - die blockierende Veto-Zeile steht
            # am ENDE und fiel damit genau aus dem gespeicherten Ausschnitt heraus. Real
            # beobachtet bei devpulse, eventstream_zero, nexus_resilience_gateway und
            # nexusforge: alle vier trugen exakt 500 Zeichen Detail, endeten mitten in einer
            # Erfolgsmeldung und landeten deshalb unter "Sonstiger Fehler", obwohl der echte
            # Grund im vollständigen Protokoll (.ai_team_runs/<ts>_verification.md) steht.
            # `failure_detail` selbst bleibt der gekürzte Text - er wird angezeigt, und die
            # volle Fassung gehört nicht in eine Übersicht.
            detail_for_category = (
                read_full_detail(str(entry_dir), latest) or failure_detail
            ) if status == "failed" else ""
            projects.append(
                ProjectHealth(
                    name=entry_dir.name,
                    status=status,
                    timestamp=latest.get("timestamp", "?"),
                    task_summary=latest.get("task_summary", "?"),
                    red_streak=_red_streak(history),
                    failure_detail=failure_detail,
                    failure_category=categorize_failure(detail_for_category) if status == "failed" else "",
                )
            )

    shared_patterns: dict[str, list[str]] = {}
    for p in projects:
        if p.status == "ok" or not p.failure_category:
            continue
        shared_patterns.setdefault(p.failure_category, []).append(p.name)
    shared_patterns = {cat: names for cat, names in shared_patterns.items() if len(names) >= 2}

    projects.sort(key=lambda p: (-p.red_streak, p.failure_category or "", p.name))

    return TeamHealthRollup(projects=projects, shared_patterns=shared_patterns)
