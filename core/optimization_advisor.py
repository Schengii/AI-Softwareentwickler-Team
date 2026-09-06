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
from core.team_memory import read_team_lessons, record_lesson
from memory.run_history import (
    get_agent_model_performance,
    get_agent_success_rates,
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
# Team-Retrospektive nach dem taskpulse-Lauf: kleinere Stichprobe als MIN_SAMPLE_SIZE, weil ein
# GANZER Lauf (nicht ein einzelner Agenten-Aufruf) die Beobachtungseinheit ist - bei nur 1-2
# aufgezeichneten Läufen wäre jede Quote (0% oder 100%) noch reines Rauschen, ab 3 wird ein
# durchgehendes Scheitern aussagekräftig genug für einen Hinweis.
MIN_VERIFICATION_SAMPLE_SIZE = 3
VERIFICATION_SUCCESS_RATE_THRESHOLD = 50.0
VERIFICATION_TREND_WINDOW = 10
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
class OptimizationReport:
    """Ergebnis der datenbasierten Selbstoptimierungs-Analyse – reine Empfehlungen, keine
    automatisch angewandten Änderungen an config.py."""
    model_suggestions: list[ModelSuggestion] = field(default_factory=list)
    low_performing_agents: list[LowPerformingAgent] = field(default_factory=list)
    verification_trend: VerificationTrend | None = None
    recurring_lesson_categories: list[RecurringLessonCategory] = field(default_factory=list)
    sample_runs: int = 0

    def is_empty(self) -> bool:
        return (
            not self.model_suggestions
            and not self.low_performing_agents
            and self.verification_trend is None
            and not self.recurring_lesson_categories
        )


def analyze(limit_runs: int = 100) -> OptimizationReport:
    """
    Wertet die letzten `limit_runs` Läufe aus (memory/run_history.py) und erkennt zwei Arten
    datenbasierter Optimierungspotenziale:

    1. Modell-Vergleich je Agent: Läuft ein Agent bereits mit MEHREREN unterschiedlichen
       Modellen in der Historie (z.B. nach einem manuellen .env-Wechsel), wird das empirisch
       beste vorgeschlagen – NUR wenn beide Modelle die Mindest-Stichprobengröße erreichen UND
       der Unterschied deutlich genug ist (siehe MIN_SUCCESS_RATE_GAP). "Aktuell" ist dabei das
       unter den ausreichend geprüften Modellen am häufigsten genutzte – die Historie spiegelt
       bereits wider, was tatsächlich lief, ein Blick in config.py ist dafür nicht nötig. Ist das
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
        current = max(eligible, key=lambda e: e["calls"])
        if best["model"] == current["model"]:
            continue  # das häufigst genutzte Modell ist bereits das beste
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
    if verification["runs"] >= MIN_VERIFICATION_SAMPLE_SIZE and verification["rate"] < VERIFICATION_SUCCESS_RATE_THRESHOLD:
        report.verification_trend = VerificationTrend(
            runs=verification["runs"], passed=verification["passed"], rate=verification["rate"],
        )

    report.recurring_lesson_categories = _find_recurring_lesson_categories()

    return report


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
            f"- **{s.agent_id}**: aktuell überwiegend `{s.current_model}` "
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
                f"als mit dem aktuell überwiegend genutzten '{s.current_model}' "
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
