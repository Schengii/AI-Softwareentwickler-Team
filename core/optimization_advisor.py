"""
core/optimization_advisor.py – Datenbasierte Selbstoptimierungs-Vorschläge über mehrere Läufe
hinweg

Nutzerwunsch: agent_trainer/retrospective analysieren bisher nur EINEN einzelnen Lauf per
LLM-Interpretation und passen einzelne Agenten-PROMPTS an (memory/agent_learnings.json). Es
fehlte eine Auswertung über VIELE Läufe hinweg: ob die aktuell konfigurierte Modellzuweisung
eines Agenten (config.py/.env) tatsächlich die empirisch beste ist, und ob ein Agent auffällig
oft scheitert – bisher gab es dafür keine Datengrundlage (memory/run_history.py zeigt
Erfolgsquote je Agent, aber nicht aufgeschlüsselt nach tatsächlich genutztem Modell).

Bewusst rein deterministisch (keine LLM-Interpretation nötig – Erfolgsquoten/Tokenverbrauch
sind bereits harte Zahlen aus memory/run_history.py). Standardmäßig NUR ein Vorschlag, KEINE
automatische Änderung an config.py: eine Modellzuweisung hat neben der reinen Erfolgsquote
weitere Faktoren (Rate-Limits, bewusste Provider-Präferenzen des Nutzers), die dieses Modul
nicht kennt – dieselbe Linie wie die bereits im CHANGELOG dokumentierte Entscheidung,
Phasenreihenfolge-Änderungen nicht automatisch, sondern nur nach Rücksprache umzusetzen.
apply_auto_tuning() unten ist die EINZIGE Ausnahme, und auch die nur, wenn der Nutzer das
explizit per config.ENABLE_AUTO_MODEL_TUNING freigeschaltet hat.

Team-Optimierung (Retrospektive 2026-09-04, Kosten-Nutzen-Abwägung): memory/run_history.py.
get_agent_model_performance() lieferte den durchschnittlichen Tokenverbrauch je (Agent, Modell)
schon immer mit, analyze() wertete ihn aber NIE aus - ein Modell konnte dadurch rein wegen einer
etwas höheren Erfolgsquote vorgeschlagen werden, selbst wenn es pro Aufruf deutlich mehr Tokens
kostet. Das widerspricht dem Ziel optimaler Tokennutzung direkt. TOKEN_COST_INCREASE_TOLERANCE/
SIGNIFICANT_SUCCESS_RATE_GAP unten verlangen von einem spürbar teureren Modell einen deutlich
größeren Erfolgsquoten-Vorsprung, bevor es trotzdem vorgeschlagen wird - dieselbe Abwägung, die
ein Mensch bei einer manuellen Modellwahl ohnehin anstellen würde.
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import config
from core.backlog_store import list_tickets, upsert_ticket
from core.task_manager import _DECOMPOSE_EXCLUDED_AGENT_IDS, AVAILABLE_AGENTS
from core.team_memory import read_team_lessons, record_lesson
from memory.run_history import (
    get_agent_model_performance,
    get_agent_success_rates,
    get_recent_runs,
    get_verification_success_rate,
)

# Ab dieser Mindest-Anzahl an Aufrufen gilt eine Erfolgsquote als statistisch aussagekräftig
# genug für einen Vorschlag - sonst zu viel Rauschen durch einzelne Zufallsausreißer bei z.B.
# nur 2-3 aufgezeichneten Aufrufen.
MIN_SAMPLE_SIZE = 5
# Ab diesem Unterschied in Prozentpunkten gilt eine Abweichung als meldenswert, kein triviales
# Rauschen (z.B. 88% vs. 90% wäre kein echter Hinweis, nur statistisches Rauschen).
MIN_SUCCESS_RATE_GAP = 15.0
# Kosten-Nutzen-Abwägung (siehe Moduldocstring): bis zu 20% mehr Tokens pro Aufruf gilt als
# "nicht spürbar teurer" - der normale MIN_SUCCESS_RATE_GAP reicht dann weiterhin aus. Erst
# darüber hinaus verlangt ein Vorschlag den deutlich größeren SIGNIFICANT_SUCCESS_RATE_GAP, um
# den Mehrverbrauch zu rechtfertigen.
TOKEN_COST_INCREASE_TOLERANCE = 1.2
SIGNIFICANT_SUCCESS_RATE_GAP = 30.0
# P2-2 (ROADMAP_TEMP.md, "Selbst-Degradierungs-Spirale"): success_rate misst nur, ob ein
# Agenten-Aufruf keine Exception warf - NICHT, ob der Lauf tatsächlich funktionierenden Code
# lieferte. memory/auto_tuned_models.json stufte mehrere Agenten allein wegen einer höheren
# success_rate herunter, während die tatsächliche Projekt-Erfolgsquote (verification_ok) im
# selben Zeitraum bei 13% lag - das schwächere Modell antwortete nur schneller/fehlerfreier,
# lieferte aber schlechteren Code. Ein Modellwechsel wird deshalb nur noch vorgeschlagen, wenn
# BEIDE Modelle genug quality_rate-Daten haben (siehe memory/run_history.MIN_QUALITY_SAMPLE_RUNS)
# UND das vorgeschlagene Modell dabei nicht schlechter abschneidet als das aktuelle.
MIN_QUALITY_SCORE_GAP_TO_BLOCK = 1.0
# Team-Retrospektive nach dem taskpulse-Lauf: kleinere Stichprobe als MIN_SAMPLE_SIZE, weil ein
# GANZER Lauf (nicht ein einzelner Agenten-Aufruf) die Beobachtungseinheit ist - bei nur 1-2
# aufgezeichneten Läufen wäre jede Quote (0% oder 100%) noch reines Rauschen, ab 3 wird ein
# durchgehendes Scheitern aussagekräftig genug für einen Hinweis.
MIN_VERIFICATION_SAMPLE_SIZE = 3
# Laufanalyse 2026-09-16: Die Warnung konnte praktisch nicht auslösen. Über die letzten 10 Läufe
# lag die Quote bei exakt 50,0% - und `rate < 50.0` ist damit False. Gleichzeitig lag sie über
# alle 134 aufgezeichneten Läufe bei 14,2% und über die letzten 30 bei 26,7%. Ein Fenster von 10
# Läufen ist für ein Signal, das STRUKTURELLE Probleme aufdecken soll, zu verrauscht: ein
# einziger grüner Lauf verschiebt die Quote um 10 Prozentpunkte. Fenster deshalb auf 25 (das
# entspricht bei der bisherigen Laufkadenz gut zwei Wochen) und die Grenze einschließend, damit
# ein Team, das jeden zweiten Lauf nicht grün bekommt, nicht unbemerkt bleibt.
VERIFICATION_SUCCESS_RATE_THRESHOLD = 50.0
VERIFICATION_TREND_WINDOW = 25
# Punkt 5 der Team-Retrospektive (2026-09-06): wie oft dieselbe Lektionen-Kategorie am selben
# Projekt in core/team_memory.py.team_lessons.jsonl wiederkehrt, bevor das als strukturelles
# Muster gemeldet wird (statt als isolierter Einzelfund, den record_lesson() ohnehin schon
# dedupliziert). 3, weil ein einmaliges Auftreten + eine Bestätigung noch kein verlässliches
# Muster ist - erst der DRITTE Fund derselben Kategorie am selben Projekt deutet auf eine
# Ursache hin, die der reguläre Fix-/Governance-Loop offenbar nicht dauerhaft behebt.
MIN_LESSON_RECURRENCE = 3
# Wie viele der jüngsten Lektionen für die Häufigkeitsauswertung herangezogen werden - bewusst
# begrenzt (dieselbe Überlegung wie team_memory._DEDUP_LOOKBACK), kein voller Datei-Scan bei
# beliebig wachsender Historie.
LESSON_RECURRENCE_LOOKBACK = 200
# Team-Optimierung (vollständige Umsetzung einer KI-Team-Retrospektive, echter Fund am
# event_relay-Lauf 2026-09-06): _find_recurring_lesson_categories() oben gruppiert nach
# (project_slug, category) und sieht daher NIE das größte real beobachtete Muster - dieselbe
# Kategorie (`unresolved_governance_critical`) trat in 9 von 15 Lektionen auf, aber an 9
# VERSCHIEDENEN project_slugs, weil jedes Projekt nur ein- oder zweimal vorkommt. Höher als
# MIN_LESSON_RECURRENCE, weil hier über beliebig viele verschiedene Projekte hinweg gezählt
# wird und daher mehr zufällige Kategorie-Überschneidungen zu erwarten sind, bevor ein echtes,
# strukturelles Muster im FRAMEWORK selbst (nicht nur an einem Projekt) vorliegt.
MIN_TEAMWIDE_LESSON_RECURRENCE = 5
# Nutzeranfrage (Team-Wachstums-Retrospektive 2026-09-06): "warum bestimmte Agentenrollen
# selten/nie zum Einsatz kommen" fehlte bisher als eigene Auswertungskategorie - analyze()
# erkannte bisher nur Agenten, die AUFGERUFEN wurden, aber schlecht abschnitten
# (LowPerformingAgent), nicht Agenten, die der Planer nie auswählt. Bei einem wachsenden Team
# (immer mehr Rollen) wird das relevanter, nicht weniger: eine neue Rolle ohne Nutzen bindet
# trotzdem Wartungsaufwand (Modellzuweisung, Fachbereichszugehörigkeit, System-Prompt-Pflege),
# ohne dass das je auffiele. Braucht eine deutlich GRÖSSERE Mindest-Lauf-Anzahl als
# MIN_SAMPLE_SIZE (das zählt AUFRUFE eines bereits gewählten Agenten) - bei wenigen Läufen
# insgesamt wäre "noch nie gewählt" für JEDE selten gebrauchte Rolle triviales Rauschen.
MIN_TOTAL_RUNS_FOR_UNUSED_CHECK = 20


@dataclass
class ModelSuggestion:
    """Ein einzelner, datenbasierter Vorschlag: Agent X könnte von Modell B statt A profitieren.
    current_avg_tokens/suggested_avg_tokens machen die Kosten-Seite der Abwägung sichtbar -
    eine höhere Erfolgsquote allein rechtfertigt nicht automatisch ein teureres Modell."""
    agent_id: str
    current_model: str
    current_success_rate: float
    current_calls: int
    current_avg_tokens: float
    suggested_model: str
    suggested_success_rate: float
    suggested_calls: int
    suggested_avg_tokens: float


@dataclass
class LowPerformingAgent:
    """Ein Agent mit auffällig niedriger Erfolgsquote gegenüber dem Team-Durchschnitt."""
    agent_id: str
    success_rate: float
    calls: int
    team_average: float


@dataclass
class VerificationTrend:
    """Anhaltend niedrige `verification_ok`-Erfolgsquote über die letzten Läufe hinweg - anders
    als LowPerformingAgent (EIN Agent scheitert auffällig oft) geht es hier um den gesamten
    LAUF: mehrere aufeinanderfolgende Projekte, die trotz vollständiger Fix-/Governance-Kaskade
    nicht grün werden (siehe MIN_VERIFICATION_SAMPLE_SIZE-Docstring)."""
    runs: int
    passed: int
    rate: float


@dataclass
class RecurringLessonCategory:
    """Dieselbe team_lessons.jsonl-Kategorie (z.B. `unresolved_governance_critical`) tritt am
    SELBEN Projekt mehrfach auf - anders als VerificationTrend (teamweiter Testerfolg über
    Läufe hinweg) oder LowPerformingAgent (ein Agent) geht es hier um ein Muster, das der
    reguläre Fix-/Governance-Loop an genau diesem Projekt offenbar nicht dauerhaft behebt."""
    project_slug: str
    category: str
    count: int
    latest_detail: str


@dataclass
class RecurringTeamWideCategory:
    """Dieselbe team_lessons.jsonl-Kategorie tritt an MEHREREN VERSCHIEDENEN Projekten auf -
    anders als RecurringLessonCategory (dieselbe Kategorie wiederholt sich an EINEM Projekt, das
    der reguläre Fix-Loop dort nicht dauerhaft behebt) deutet dieses Muster auf eine strukturelle
    Lücke im FRAMEWORK selbst hin (z.B. im Scaffolding, im Governance-Review oder im
    Verifikations-Loop), die jedes NEUE Projekt gleichermaßen trifft. Team-Retrospektive, echter
    Fund (2026-09-06): 9 von 15 Lektionen waren `unresolved_governance_critical`, aber an 9
    verschiedenen project_slugs - RecurringLessonCategory sah dieses dominante Muster nie, weil
    kaum ein Slug zweimal vorkam. `project_slugs` listet ALLE betroffenen Projekte (für die
    Nachvollziehbarkeit im Bericht), `count` ist bewusst die Anzahl VERSCHIEDENER Projekte, nicht
    die Gesamtzahl der Lektionen (mehrfache Funde am selben Projekt zählen für dieses
    teamweite Signal nur einmal - das deckt bereits RecurringLessonCategory ab)."""
    category: str
    count: int
    project_slugs: list[str]
    latest_detail: str


@dataclass
class UnusedAgent:
    """Eine im Planer wählbare Rolle (core.task_manager.AVAILABLE_AGENTS), die über die
    letzten `sample_runs` Läufe kein einziges Mal von der Aufgabenzerlegung ausgewählt wurde -
    anders als LowPerformingAgent (wird gewählt, schneidet aber schlecht ab) geht es hier um
    eine Rolle, die dem Team faktisch NIE Nutzen bringt, aber weiterhin Wartungsaufwand bindet
    (Modellzuweisung, Fachbereichszugehörigkeit, System-Prompt)."""
    agent_id: str
    configured_model: str
    sample_runs: int


@dataclass
class OptimizationReport:
    """Ergebnis der datenbasierten Selbstoptimierungs-Analyse – reine Empfehlungen, keine
    automatisch angewandten Änderungen an config.py."""
    model_suggestions: list[ModelSuggestion] = field(default_factory=list)
    low_performing_agents: list[LowPerformingAgent] = field(default_factory=list)
    verification_trend: VerificationTrend | None = None
    recurring_lesson_categories: list[RecurringLessonCategory] = field(default_factory=list)
    recurring_teamwide_categories: list[RecurringTeamWideCategory] = field(default_factory=list)
    unused_agents: list[UnusedAgent] = field(default_factory=list)
    sample_runs: int = 0

    def is_empty(self) -> bool:
        return (
            not self.model_suggestions
            and not self.low_performing_agents
            and self.verification_trend is None
            and not self.recurring_lesson_categories
            and not self.recurring_teamwide_categories
            and not self.unused_agents
        )


def _current_model_entry(agent_id: str, eligible: list[dict]) -> dict:
    """
    Das Modell, mit dem diese Rolle aktuell TATSÄCHLICH läuft - als Vergleichsbasis für einen
    Modell-Vorschlag.

    Realer Fund (Laufanalyse 2026-09-16): Als "aktuell" galt hier das in der Historie
    MEISTGENUTZTE Modell. Das ist etwas anderes als die geltende Zuweisung, sobald diese sich
    innerhalb des Auswertungsfensters geändert hat - und dann kippt die Auswertung ins
    Gegenteil. Konkret lief `tester` laut config.py auf gemini-3.8-flash (66,2% Erfolg,
    ⌀50.716 Tokens), während gemini-3.1-flash-lite aus älteren Läufen mehr Aufrufe gesammelt
    hatte (100% Erfolg, ⌀41.486 Tokens). Damit war `best == current`, die Funktion brach mit
    "das meistgenutzte Modell ist bereits das beste" ab - und der eine Vorschlag, der die Rolle
    gleichzeitig zuverlässiger UND billiger gemacht hätte, wurde nie erzeugt. Dasselbe Muster
    traf `frontend` (72,3% statt 100%).

    Die Zuweisung kommt deshalb aus config.get_model_for_agent() - ohne den Zufallsarm eines
    laufenden A/B-Tests, der die Basis sonst bei jedem Aufruf verschieben würde. Nur wenn zu
    diesem Modell keine ausreichend geprüften Messwerte vorliegen, bleibt das meistgenutzte
    Modell die Notlösung: Ein Vergleich braucht auf BEIDEN Seiten Zahlen.
    """
    try:
        konfiguriert = config.get_model_for_agent(agent_id, include_ab_trial=False)
    except Exception:  # noqa: BLE001 - eine Auswertung darf nie an der Modellauflösung scheitern
        konfiguriert = ""
    for eintrag in eligible:
        if eintrag["model"] == konfiguriert:
            return eintrag
    return max(eligible, key=lambda e: e["calls"])


def analyze(limit_runs: int = 100) -> OptimizationReport:
    """
    Wertet die letzten `limit_runs` Läufe aus (memory/run_history.py) und erkennt zwei Arten
    datenbasierter Optimierungspotenziale:

    1. Modell-Vergleich je Agent: Läuft ein Agent bereits mit MEHREREN unterschiedlichen
       Modellen in der Historie (z.B. nach einem manuellen .env-Wechsel), wird das empirisch
       beste vorgeschlagen – NUR wenn beide Modelle die Mindest-Stichprobengröße erreichen UND
       der Unterschied deutlich genug ist (siehe MIN_SUCCESS_RATE_GAP). "Aktuell" ist dabei die
       geltende Zuweisung aus config.get_model_for_agent() und NICHT das meistgenutzte Modell
       der Historie – siehe _current_model_entry() für den Lauf, an dem dieser Unterschied
       auffiel. Ist das
       vorgeschlagene Modell spürbar teurer (siehe TOKEN_COST_INCREASE_TOLERANCE), muss der
       Erfolgsquoten-Vorsprung den größeren SIGNIFICANT_SUCCESS_RATE_GAP erreichen.
    2. Auffällig niedrige Erfolgsquote: ein Agent, dessen Erfolgsquote deutlich unter dem
       Team-Durchschnitt liegt – unabhängig vom Modell (kann z.B. auf eine zu vage
       Aufgabenbeschreibung oder ein strukturelles Prompt-Problem hindeuten, nicht nur auf die
       Modellwahl).
    """
    report = OptimizationReport(sample_runs=limit_runs)

    by_agent: dict[str, list[dict]] = {}
    for entry in get_agent_model_performance(limit_runs):
        by_agent.setdefault(entry["agent_id"], []).append(entry)

    for agent_id, entries in by_agent.items():
        eligible = [e for e in entries if e["calls"] >= MIN_SAMPLE_SIZE and e["model"] != "unbekannt"]
        if len(eligible) < 2:
            continue  # nur EIN Modell in der Historie ausreichend geprüft - kein Vergleich möglich
        best = max(eligible, key=lambda e: e["success_rate"])
        current = _current_model_entry(agent_id, eligible)
        if best["model"] == current["model"]:
            continue  # das tatsächlich zugewiesene Modell ist bereits das beste
        gap = best["success_rate"] - current["success_rate"]
        if gap < MIN_SUCCESS_RATE_GAP:
            continue
        # Kosten-Nutzen-Abwägung (siehe Moduldocstring): ein spürbar teureres Modell (mehr als
        # TOKEN_COST_INCREASE_TOLERANCE mal so viele Tokens/Aufruf) braucht einen deutlich
        # größeren Erfolgsquoten-Vorsprung, sonst ist der Vorschlag reiner Mehrverbrauch ohne
        # verhältnismäßigen Nutzen - das Gegenteil von optimaler Tokennutzung.
        is_meaningfully_more_expensive = (
            current["avg_tokens"] > 0 and best["avg_tokens"] > current["avg_tokens"] * TOKEN_COST_INCREASE_TOLERANCE
        )
        if is_meaningfully_more_expensive and gap < SIGNIFICANT_SUCCESS_RATE_GAP:
            continue
        # P2-2: ohne Qualitäts-Daten auf BEIDEN Seiten (zu wenige Läufe, siehe
        # MIN_QUALITY_SAMPLE_RUNS) lässt sich "nicht schlechter" nicht belegen - dann lieber kein
        # Vorschlag als ein unbelegter Downgrade. Liegen Daten vor, darf das vorgeschlagene
        # Modell nicht spürbar schlechter verifizieren als das aktuelle.
        if current["quality_rate"] is None or best["quality_rate"] is None:
            continue
        if current["quality_rate"] - best["quality_rate"] >= MIN_QUALITY_SCORE_GAP_TO_BLOCK:
            continue
        report.model_suggestions.append(ModelSuggestion(
            agent_id=agent_id,
            current_model=current["model"], current_success_rate=current["success_rate"],
            current_calls=current["calls"], current_avg_tokens=current["avg_tokens"],
            suggested_model=best["model"], suggested_success_rate=best["success_rate"],
            suggested_calls=best["calls"], suggested_avg_tokens=best["avg_tokens"],
        ))

    eligible_agents = [a for a in get_agent_success_rates(limit_runs) if a["calls"] >= MIN_SAMPLE_SIZE]
    if eligible_agents:
        team_average = sum(a["success_rate"] for a in eligible_agents) / len(eligible_agents)
        for a in eligible_agents:
            if team_average - a["success_rate"] >= MIN_SUCCESS_RATE_GAP:
                report.low_performing_agents.append(LowPerformingAgent(
                    agent_id=a["agent_id"], success_rate=a["success_rate"], calls=a["calls"],
                    team_average=round(team_average, 1),
                ))

    verification = get_verification_success_rate(VERIFICATION_TREND_WINDOW)
    if verification["runs"] >= MIN_VERIFICATION_SAMPLE_SIZE and verification["rate"] <= VERIFICATION_SUCCESS_RATE_THRESHOLD:
        report.verification_trend = VerificationTrend(
            runs=verification["runs"], passed=verification["passed"], rate=verification["rate"],
        )

    report.recurring_lesson_categories = _find_recurring_lesson_categories()
    report.recurring_teamwide_categories = _find_recurring_teamwide_categories()

    total_runs_examined = len(get_recent_runs(limit_runs))
    if total_runs_examined >= MIN_TOTAL_RUNS_FOR_UNUSED_CHECK:
        report.unused_agents = _find_unused_agents(limit_runs, total_runs_examined)

    return report


def _find_unused_agents(limit_runs: int, total_runs_examined: int) -> list[UnusedAgent]:
    """Meldet jede im Planer wählbare Rolle, die über `limit_runs` Läufe (mindestens
    MIN_TOTAL_RUNS_FOR_UNUSED_CHECK insgesamt, sonst zu früh für eine belastbare Aussage) kein
    einziges Mal aufgerufen wurde - siehe UnusedAgent-Docstring. Fachbereichsleiter und die
    bewusst nicht direkt wählbaren Rollen (_DECOMPOSE_EXCLUDED_AGENT_IDS, z.B. `agent_trainer`,
    `retrospective` - werden intern/manuell statt vom Planer ausgelöst) sind kein Fund, wenn sie
    nie in agent_results auftauchen, und deshalb hier ausgenommen."""
    called_ids = {a["agent_id"] for a in get_agent_success_rates(limit_runs)}
    selectable_ids = set(AVAILABLE_AGENTS.keys()) - set(_DECOMPOSE_EXCLUDED_AGENT_IDS)
    unused_ids = sorted(selectable_ids - called_ids)
    return [
        UnusedAgent(
            agent_id=agent_id,
            configured_model=config.get_model_for_agent(agent_id),
            sample_runs=total_runs_examined,
        )
        for agent_id in unused_ids
    ]


def _find_recurring_lesson_categories() -> list[RecurringLessonCategory]:
    """Gruppiert die letzten LESSON_RECURRENCE_LOOKBACK Team-Lektionen nach (project_slug,
    category) und meldet Gruppen, die MIN_LESSON_RECURRENCE oder öfter auftreten - siehe
    RecurringLessonCategory-Docstring. Ergebnis absteigend nach Häufigkeit sortiert, damit das
    auffälligste Muster im Bericht zuerst erscheint."""
    lessons = read_team_lessons(limit=LESSON_RECURRENCE_LOOKBACK)
    counts: Counter[tuple[str, str]] = Counter()
    latest_detail: dict[tuple[str, str], str] = {}
    for entry in lessons:
        key = (entry.get("project_slug", "?"), entry.get("category", "?"))
        counts[key] += 1
        # read_team_lessons() liefert neueste zuerst - der erste Treffer je Key ist damit
        # bereits das jüngste Vorkommen, spätere Treffer dürfen ihn nicht überschreiben.
        latest_detail.setdefault(key, entry.get("detail", ""))

    findings = [
        RecurringLessonCategory(
            project_slug=project_slug, category=category, count=count,
            latest_detail=latest_detail[(project_slug, category)],
        )
        for (project_slug, category), count in counts.items()
        if count >= MIN_LESSON_RECURRENCE
    ]
    findings.sort(key=lambda f: f.count, reverse=True)
    return findings


def _find_recurring_teamwide_categories() -> list[RecurringTeamWideCategory]:
    """Gruppiert die letzten LESSON_RECURRENCE_LOOKBACK Team-Lektionen NUR nach `category`
    (projektübergreifend - project_slug wird nur zur Aufzählung betroffener Projekte
    mitgeführt) und meldet Kategorien, die an MIN_TEAMWIDE_LESSON_RECURRENCE oder mehr
    VERSCHIEDENEN Projekten auftreten - siehe RecurringTeamWideCategory-Docstring.
    project_slug="_team" (core.optimization_advisor.record_suggestions_as_lessons()-Meta-Funde
    wie `unused_agent`/`model_performance`) wird ausgeschlossen: das sind bereits Team-
    Selbstoptimierungs-Funde, kein wiederkehrender CODE-Defekt an echten Projekten, den dieser
    Detector aufdecken soll."""
    lessons = read_team_lessons(limit=LESSON_RECURRENCE_LOOKBACK)
    slugs_by_category: dict[str, list[str]] = {}
    latest_detail: dict[str, str] = {}
    for entry in lessons:
        project_slug = entry.get("project_slug", "?")
        if project_slug == "_team":
            continue
        category = entry.get("category", "?")
        slugs = slugs_by_category.setdefault(category, [])
        if project_slug not in slugs:
            slugs.append(project_slug)
        # lessons ist neueste zuerst - der erste Treffer je Kategorie ist damit bereits das
        # jüngste Vorkommen, spätere Treffer dürfen ihn nicht überschreiben.
        latest_detail.setdefault(category, entry.get("detail", ""))

    findings = [
        RecurringTeamWideCategory(
            category=category, count=len(slugs), project_slugs=slugs,
            latest_detail=latest_detail[category],
        )
        for category, slugs in slugs_by_category.items()
        if len(slugs) >= MIN_TEAMWIDE_LESSON_RECURRENCE
    ]
    findings.sort(key=lambda f: f.count, reverse=True)
    return findings


def format_report_for_humans(report: OptimizationReport) -> str:
    """
    Formatiert den Bericht als lesbaren Markdown-Abschnitt – leer, wenn es nichts zu berichten
    gibt (kein unnötiger Output für die Mehrheit der Läufe ohne auffällige Befunde, dasselbe
    Prinzip wie format_constitution_for_agents()/format_design_system_for_agents()).
    """
    if report.is_empty():
        return ""

    lines = [
        "### 🔧 Datenbasierte Selbstoptimierungs-Vorschläge",
        "*Automatische Anwendung nur, wenn ENABLE_AUTO_MODEL_TUNING aktiv ist (siehe config.py) – "
        "sonst rein informativ, bitte manuell prüfen.*",
    ]
    for s in report.model_suggestions:
        lines.append(
            f"- **{s.agent_id}**: aktuell zugewiesen `{s.current_model}` "
            f"({s.current_success_rate}% Erfolgsquote, ⌀{s.current_avg_tokens:.0f} Tokens/Aufruf, "
            f"{s.current_calls} Aufrufe) – `{s.suggested_model}` lief historisch besser "
            f"({s.suggested_success_rate}% Erfolgsquote, ⌀{s.suggested_avg_tokens:.0f} Tokens/Aufruf, "
            f"{s.suggested_calls} Aufrufe)."
        )
    for a in report.low_performing_agents:
        lines.append(
            f"- **{a.agent_id}**: Erfolgsquote {a.success_rate}% über {a.calls} Aufrufe, "
            f"deutlich unter dem Team-Durchschnitt ({a.team_average}%) – Prompt/Aufgabenzuschnitt prüfen."
        )
    if report.verification_trend is not None:
        v = report.verification_trend
        lines.append(
            f"- ⚠️ **Verifikations-Trend**: nur {v.passed}/{v.runs} der letzten Läufe (projektübergreifend) "
            f"endeten mit `verification_ok=True` ({v.rate}%) – ein anhaltendes, nicht nur einmaliges Muster. "
            "Deutet eher auf ein strukturelles Problem hin (z.B. zu ambitionierte Aufgaben, ein "
            "systematisch fehlender Agenten-Fähigkeitsbereich) als auf einzelne Projekt-Ausreißer."
        )
    for r in report.recurring_lesson_categories:
        lines.append(
            f"- 🔁 **Wiederkehrende Lektionen-Kategorie** `{r.category}` bei **{r.project_slug}**: "
            f"{r.count}× aufgezeichnet – jüngster Fund: {r.latest_detail[:120]}. Deutet auf eine "
            "Ursache hin, die der reguläre Fix-/Governance-Loop an diesem Projekt nicht dauerhaft behebt."
        )
    for t in report.recurring_teamwide_categories:
        shown_slugs = ", ".join(t.project_slugs[:5])
        more = f" (+{len(t.project_slugs) - 5} weitere)" if len(t.project_slugs) > 5 else ""
        lines.append(
            f"- 🏗️ **Team-weites strukturelles Muster** `{t.category}`: an {t.count} "
            f"VERSCHIEDENEN Projekten aufgetreten ({shown_slugs}{more}) – jüngster Fund: "
            f"{t.latest_detail[:120]}. Deutet auf eine Lücke im FRAMEWORK selbst hin (z.B. "
            "Scaffolding, Governance-Review oder Verifikations-Loop), die jedes neue Projekt "
            "gleichermaßen trifft - nicht auf einen Einzelfall."
        )
    for u in report.unused_agents:
        lines.append(
            f"- 💤 **{u.agent_id}** (Modell `{u.configured_model}`): über die letzten "
            f"{u.sample_runs} Läufe kein einziges Mal vom Planer ausgewählt – prüfen, ob die "
            "Rolle noch gebraucht wird, ihre Beschreibung im Planer-Prompt zu unspezifisch ist, "
            "oder ob echte Aufgaben dafür bisher schlicht nicht vorkamen."
        )
    return "\n".join(lines)


def get_recent_verification_trend_warning() -> str:
    """Kurzer, einzeiliger Warnhinweis für Kontexte außerhalb des vollen Berichts (z.B.
    core/goal_loop.py's Eval-Prompt) - leer, wenn kein teamweiter Verifikations-Trend
    vorliegt. Rein deterministisch, kein zusätzlicher LLM-Aufruf. Reagiert bewusst NUR auf
    verification_trend (nicht die anderen Report-Teile): der Goal-Loop arbeitet an EINEM
    Projekt und braucht hier nur das teamweite "Vorsicht, wir scheitern gerade häufig"-Signal,
    nicht die vollen Modell-/Agenten-Detailvorschläge, die den Eval-Prompt nur aufblähen
    würden."""
    trend = analyze().verification_trend
    if trend is None:
        return ""
    return (
        f"⚠️ Team-weiter Verifikations-Trend: nur {trend.passed}/{trend.runs} der letzten Läufe "
        f"(projektübergreifend, nicht nur dieses Projekt) endeten mit grüner Verifikation "
        f"({trend.rate}%). Plane entsprechend vorsichtiger (kleinere, klar abgegrenzte Schritte, "
        "explizite Tests je Änderung) statt große Sprünge zu riskieren."
    )


def record_suggestions_as_lessons(report: OptimizationReport) -> None:
    """Überführt Modell- und Underperformer-Vorschläge in das teamweite Lektionen-Gedächtnis
    (core/team_memory.py), damit ein erkanntes Muster auch dann sichtbar bleibt, wenn
    config.ENABLE_AUTO_MODEL_TUNING (bewusst) aus ist und niemand den Abschlussbericht eines
    einzelnen Laufs liest - insbesondere bei autonomen --work-backlog/Cron-Läufen ohne
    menschlichen Betrachter. record_lesson() dedupliziert intern bereits fast identische
    Einträge, ein wiederholter Aufruf mit demselben Fund bläht die Historie also nicht auf.
    project_slug="_team" markiert bewusst KEIN echtes Projekt (die Vorschläge sind
    teamweit/agentenweit, nicht projektspezifisch) - format_team_lessons_for_agents()
    priorisiert Lektionen des aktuell bearbeiteten Projekts ohnehin nur zusätzlich, verdrängt
    andere Kategorien also nicht."""
    for s in report.model_suggestions:
        record_lesson(
            project_slug="_team",
            category="model_performance",
            detail=(
                f"Agent '{s.agent_id}' lief mit '{s.suggested_model}' empirisch besser "
                f"({s.suggested_success_rate}% Erfolgsquote, ⌀{s.suggested_avg_tokens:.0f} Tokens/Aufruf) "
                f"als mit dem aktuell zugewiesenen '{s.current_model}' "
                f"({s.current_success_rate}%, ⌀{s.current_avg_tokens:.0f} Tokens/Aufruf) - Modellzuweisung prüfen."
            ),
        )
    for a in report.low_performing_agents:
        record_lesson(
            project_slug="_team",
            category="low_performing_agent",
            detail=(
                f"Agent '{a.agent_id}' liegt mit {a.success_rate}% Erfolgsquote über {a.calls} Aufrufe "
                f"deutlich unter dem Team-Durchschnitt ({a.team_average}%) - Prompt/Aufgabenzuschnitt prüfen."
            ),
        )
    for u in report.unused_agents:
        record_lesson(
            project_slug="_team",
            category="unused_agent",
            detail=(
                f"Agent '{u.agent_id}' (Modell '{u.configured_model}') wurde über die letzten "
                f"{u.sample_runs} Läufe kein einziges Mal vom Planer ausgewählt - Rollenbedarf, "
                "Planer-Prompt-Beschreibung oder Aufgabenzuschnitt prüfen."
            ),
        )


def record_unused_agent_tickets(report: OptimizationReport) -> list[str]:
    """
    Team-Optimierung (Fortsetzung der Analyse 2026-09-06): record_suggestions_as_lessons()
    schrieb `unused_agent`-Funde bisher NUR in memory/team_lessons.jsonl - dort teilen sie sich
    mit jeder anderen Kategorie dieselben MAX_LESSONS_SHOWN=5 Anzeigeplätze im Agenten-Prompt
    (core/team_memory.py) und sind sonst nirgends sichtbar. Ein realer Lauf (06.09.) erzeugte
    11 solcher Lektionen auf einmal - ohne diese Funktion blieben sie eine stille Zeile in einer
    JSONL-Datei, die niemand routinemäßig liest, statt ein sichtbares, verfolgbares Ticket wie
    bei `unresolved_governance_critical` (siehe agents/orchestrator/verification.py).

    Legt pro betroffener agent_id ein stabiles Ticket an/aktualisiert es (`unused-agent-<id>`,
    status="todo", source="optimization_advisor") - stabil, damit ein wiederholter Fund
    dasselbe Ticket nur auffrischt statt es zu duplizieren. `source="optimization_advisor"`
    ist bewusst NICHT in core/backlog_worker.py._AUTONOMOUS_SOURCES enthalten: ob eine Rolle
    wirklich überflüssig ist oder nur eine unklare Beschreibung hat, ist eine Abwägung, die ein
    Mensch treffen soll - das Ticket macht den Fund nur sichtbar und verfolgbar, statt ihn
    automatisch (und ggf. falsch) zu "beheben".

    Gibt die Liste der angelegten/aktualisierten Ticket-IDs zurück (für eine Erfolgsmeldung im
    Abschlussbericht, analog zu apply_auto_tuning()).
    """
    ticket_ids: list[str] = []
    for u in report.unused_agents:
        ticket_id = f"unused-agent-{u.agent_id}"
        try:
            upsert_ticket(
                ticket_id=ticket_id,
                title=f"Ungenutzte Agentenrolle: {u.agent_id}",
                source="optimization_advisor",
                status="todo",
                project_slug="_team",
                detail=(
                    f"Agent '{u.agent_id}' (Modell '{u.configured_model}') wurde über die "
                    f"letzten {u.sample_runs} Läufe kein einziges Mal vom Planer ausgewählt. "
                    "Prüfen: (1) ist die Rolle im Planer-Prompt (core/task_manager.py."
                    "AVAILABLE_AGENTS) konkret genug beschrieben - nennt sie WANN man sie "
                    "einsetzt, nicht nur WAS sie kann?, (2) kommen reale Aufgaben für diese "
                    "Rolle überhaupt vor, oder überschneidet sie sich mit einer anderen Rolle?, "
                    "(3) falls strukturell nie gebraucht: Konsolidierung mit einer verwandten "
                    "Rolle erwägen, statt weiterhin Wartungsaufwand ohne Nutzen zu binden."
                ),
            )
            ticket_ids.append(ticket_id)
        except Exception:
            # Dasselbe Prinzip wie beim Ticket für unresolved_governance_critical in
            # agents/orchestrator/verification.py: ein fehlgeschlagenes Ticket darf einen
            # laufenden Orchestrator-Lauf nie zum Absturz bringen - die Lektion in
            # team_lessons.jsonl (record_suggestions_as_lessons()) bleibt in dem Fall die
            # einzige Spur des Fundes.
            continue
    return ticket_ids


def close_resolved_unused_agent_tickets(report: OptimizationReport) -> list[str]:
    """
    Team-Optimierung (KI-Team-Zustandsbericht 2026-09-08, echter Fund): record_unused_agent_
    tickets() öffnet ein `unused-agent-<id>`-Ticket, sobald eine Rolle über die letzten Läufe nie
    gewählt wurde - schließt es aber NIE wieder, selbst wenn eine spätere Prompt-Schärfung
    (core/task_manager.py.AVAILABLE_AGENTS, siehe die "Analyse 2026-09-06"-Kommentare dort) genau
    das beheben sollte und die Rolle in einem späteren Lauf tatsächlich wieder gewählt wird. Real
    beobachtet: alle 10 zum Fund-Zeitpunkt offenen `unused-agent-*`-Tickets standen tagelang
    unverändert auf "todo", obwohl die zugehörige Beschreibung längst nachgeschärft war - eine rein
    mechanisch verifizierbare Tatsache (`agent_id` taucht wieder in `get_agent_success_rates()`
    auf) hätte das Ticket sofort schließen können, statt auf eine erneute menschliche Prüfung zu
    warten, die dieselbe Beobachtung nur wiederholt hätte.

    Bewusst NICHT die Kehrseite von record_unused_agent_tickets() (kein `source`-Ausschluss aus
    core/backlog_worker.py._AUTONOMOUS_SOURCES nötig): das Schließen eines Tickets, weil eine Rolle
    nachweislich wieder genutzt wird, ist eine rein mechanische Tatsachenfeststellung, keine
    Abwägung ("ist die Rolle überflüssig?") - dieselbe Unterscheidung wie beim bestehenden
    Auto-Close-Muster für `recurring-lint-`/`recurring-failure-`-Tickets
    (agents/orchestrator/__init__.py bzw. agents/orchestrator/verification.py).

    Gibt die Liste der geschlossenen Ticket-IDs zurück (für dieselbe Erfolgsmeldung im
    Abschlussbericht wie apply_auto_tuning()/record_unused_agent_tickets()).
    """
    still_unused_ids = {u.agent_id for u in report.unused_agents}
    closed_ids: list[str] = []
    for ticket in list_tickets(status="todo"):
        if ticket.source != "optimization_advisor" or not ticket.id.startswith("unused-agent-"):
            continue
        agent_id = ticket.id.removeprefix("unused-agent-")
        if agent_id in still_unused_ids:
            continue
        try:
            upsert_ticket(
                ticket_id=ticket.id, title=ticket.title, source=ticket.source,
                status="done", project_slug=ticket.project_slug,
                detail=(
                    f"Agent '{agent_id}' wurde in einem späteren Lauf wieder vom Planer "
                    "ausgewählt - automatisch geschlossen (kein manueller Konsolidierungsbedarf "
                    "mehr erkennbar)."
                ),
            )
            closed_ids.append(ticket.id)
        except Exception:
            # Wie oben: ein fehlgeschlagenes Ticket-Update darf den laufenden Orchestrator-Lauf
            # nie zum Absturz bringen - das Ticket bleibt dann einfach offen für den nächsten Lauf.
            continue
    return closed_ids


def _load_auto_tuned_models() -> dict:
    """Liest config.AUTO_TUNED_MODELS_FILE - leeres Dict, falls sie fehlt oder beschädigt ist
    (nie ein Absturz nur wegen dieser rein optionalen Optimierung)."""
    path = Path(config.AUTO_TUNED_MODELS_FILE)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def apply_auto_tuning(report: OptimizationReport) -> list[str]:
    """
    Schreibt die Modell-Vorschläge aus `report` in config.AUTO_TUNED_MODELS_FILE - macht sie
    damit für JEDEN künftigen Lauf über config.py.get_model_for_agent() sofort wirksam, ohne
    dass ein Mensch .env/config.py manuell anpassen muss. Schließt den in der Team-Retrospektive
    identifizierten Kreislauf: bisher blieb selbst eine glasklare, datenbasierte Empfehlung
    wirkungslos, solange niemand den Abschlussbericht liest.

    No-Op (gibt [] zurück), solange config.ENABLE_AUTO_MODEL_TUNING nicht explizit aktiviert
    ist - bewusst Opt-in, damit sich die Modellzuweisung eines Agenten nie überraschend ändert.
    Jeder Eintrag speichert genug Kontext (Vorher-Modell, Kennzahlen, Zeitstempel, Begründung),
    um die Datei jederzeit manuell nachvollziehen, korrigieren oder löschen zu können - eine
    normale, git-ignorierte memory/*.json wie jede andere Historie in diesem Projekt.

    Gibt die Liste der tatsächlich angepassten agent_id zurück (für eine Erfolgsmeldung im
    Abschlussbericht).
    """
    if not config.ENABLE_AUTO_MODEL_TUNING or not report.model_suggestions:
        return []

    data = _load_auto_tuned_models()
    now_iso = datetime.now(UTC).isoformat(timespec="seconds")
    for s in report.model_suggestions:
        data[s.agent_id] = _suggestion_to_entry(s, now_iso)

    if not _save_auto_tuned_models(data):
        return []
    return [s.agent_id for s in report.model_suggestions]


def _suggestion_to_entry(s: ModelSuggestion, now_iso: str, manual: bool = False) -> dict:
    """Baut den memory/auto_tuned_models.json-Eintrag für einen Vorschlag - gemeinsame Logik
    für apply_auto_tuning() (alle Vorschläge auf einmal, manual=False) und
    apply_single_suggestion() (gezielt EIN Agent, manual=True). `manual` lässt
    config.py.get_model_for_agent() den Eintrag auch dann anwenden, wenn
    config.ENABLE_AUTO_MODEL_TUNING (bewusst) aus ist - siehe dessen Docstring."""
    return {
        "model": s.suggested_model,
        "previous_model": s.current_model,
        "success_rate": s.suggested_success_rate,
        "avg_tokens": s.suggested_avg_tokens,
        "applied_at": now_iso,
        "manual": manual,
        "reason": (
            f"Empirisch bessere Erfolgsquote ({s.suggested_success_rate}% vs. "
            f"{s.current_success_rate}% über {s.suggested_calls} bzw. {s.current_calls} "
            f"Aufrufe) bei vertretbarem Tokenverbrauch (⌀{s.suggested_avg_tokens:.0f} vs. "
            f"⌀{s.current_avg_tokens:.0f} Tokens/Aufruf)."
        ),
    }


def _save_auto_tuned_models(data: dict) -> bool:
    """Schreibt memory/auto_tuned_models.json - True bei Erfolg, False bei einem I/O-Fehler
    (der Aufrufer meldet dann keine fälschlich 'angewendeten' agent_id zurück)."""
    try:
        path = Path(config.AUTO_TUNED_MODELS_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except OSError:
        return False


def apply_single_suggestion(report: OptimizationReport, agent_id: str) -> ModelSuggestion | None:
    """Übernimmt GEZIELT genau einen Modell-Vorschlag aus `report` in
    config.AUTO_TUNED_MODELS_FILE - der manuelle Mittelweg zwischen "alles ignorieren" und dem
    Alles-oder-nichts-Schalter config.ENABLE_AUTO_MODEL_TUNING (siehe /apply-tuning in
    interface/cli.py): der Nutzer behält die Kontrolle über JEDEN einzelnen Agenten, ohne dafür
    erst global automatische Selbstumkonfiguration erlauben zu müssen. Wirkt bewusst UNABHÄNGIG
    von config.ENABLE_AUTO_MODEL_TUNING - eine explizite, einzelne Bestätigung per Kommando ist
    per Definition kein überraschendes automatisches Verhalten.

    Gibt den angewendeten ModelSuggestion zurück (für eine Erfolgsmeldung), oder None, wenn
    kein Vorschlag für diese agent_id vorliegt oder das Schreiben fehlschlug.
    """
    suggestion = next((s for s in report.model_suggestions if s.agent_id == agent_id), None)
    if suggestion is None:
        return None

    data = _load_auto_tuned_models()
    now_iso = datetime.now(UTC).isoformat(timespec="seconds")
    data[suggestion.agent_id] = _suggestion_to_entry(suggestion, now_iso, manual=True)
    if not _save_auto_tuned_models(data):
        return None
    return suggestion
