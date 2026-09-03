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
sind bereits harte Zahlen aus memory/run_history.py) und bewusst NUR ein Vorschlag, KEINE
automatische Änderung an config.py: eine Modellzuweisung hat neben der reinen Erfolgsquote
weitere Faktoren (Kosten pro Token, Rate-Limits, bewusste Provider-Präferenzen des Nutzers),
die dieses Modul nicht kennt – dieselbe Linie wie die bereits im CHANGELOG dokumentierte
Entscheidung, Phasenreihenfolge-Änderungen nicht automatisch, sondern nur nach Rücksprache
umzusetzen.
"""

from dataclasses import dataclass, field

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
# Team-Retrospektive nach dem taskpulse-Lauf: kleinere Stichprobe als MIN_SAMPLE_SIZE, weil ein
# GANZER Lauf (nicht ein einzelner Agenten-Aufruf) die Beobachtungseinheit ist - bei nur 1-2
# aufgezeichneten Läufen wäre jede Quote (0% oder 100%) noch reines Rauschen, ab 3 wird ein
# durchgehendes Scheitern aussagekräftig genug für einen Hinweis.
MIN_VERIFICATION_SAMPLE_SIZE = 3
VERIFICATION_SUCCESS_RATE_THRESHOLD = 50.0
VERIFICATION_TREND_WINDOW = 10


@dataclass
class ModelSuggestion:
    """Ein einzelner, datenbasierter Vorschlag: Agent X könnte von Modell B statt A profitieren."""
    agent_id: str
    current_model: str
    current_success_rate: float
    current_calls: int
    suggested_model: str
    suggested_success_rate: float
    suggested_calls: int


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
class OptimizationReport:
    """Ergebnis der datenbasierten Selbstoptimierungs-Analyse – reine Empfehlungen, keine
    automatisch angewandten Änderungen an config.py."""
    model_suggestions: list[ModelSuggestion] = field(default_factory=list)
    low_performing_agents: list[LowPerformingAgent] = field(default_factory=list)
    verification_trend: VerificationTrend | None = None
    sample_runs: int = 0

    def is_empty(self) -> bool:
        return not self.model_suggestions and not self.low_performing_agents and self.verification_trend is None


def analyze(limit_runs: int = 100) -> OptimizationReport:
    """
    Wertet die letzten `limit_runs` Läufe aus (memory/run_history.py) und erkennt zwei Arten
    datenbasierter Optimierungspotenziale:

    1. Modell-Vergleich je Agent: Läuft ein Agent bereits mit MEHREREN unterschiedlichen
       Modellen in der Historie (z.B. nach einem manuellen .env-Wechsel), wird das empirisch
       beste vorgeschlagen – NUR wenn beide Modelle die Mindest-Stichprobengröße erreichen UND
       der Unterschied deutlich genug ist (siehe MIN_SUCCESS_RATE_GAP). "Aktuell" ist dabei das
       unter den ausreichend geprüften Modellen am häufigsten genutzte – die Historie spiegelt
       bereits wider, was tatsächlich lief, ein Blick in config.py ist dafür nicht nötig.
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
        report.model_suggestions.append(ModelSuggestion(
            agent_id=agent_id,
            current_model=current["model"], current_success_rate=current["success_rate"], current_calls=current["calls"],
            suggested_model=best["model"], suggested_success_rate=best["success_rate"], suggested_calls=best["calls"],
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

    return report


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
        "*Rein informativ, keine automatische Änderung an config.py – bitte manuell prüfen.*",
    ]
    for s in report.model_suggestions:
        lines.append(
            f"- **{s.agent_id}**: aktuell überwiegend `{s.current_model}` "
            f"({s.current_success_rate}% Erfolgsquote über {s.current_calls} Aufrufe) – "
            f"`{s.suggested_model}` lief historisch besser "
            f"({s.suggested_success_rate}% Erfolgsquote über {s.suggested_calls} Aufrufe)."
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
    return "\n".join(lines)
