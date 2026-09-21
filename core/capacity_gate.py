"""
core/capacity_gate.py – Kapazitätsprüfung VOR dem ersten Agenten-Aufruf eines Laufs

Realer Fund (Analyse auditlog_sentinel, 2026-09-10): Die Konsole warnte vor dem zweiten Lauf,
dass Gemini bereits 548 % des geschätzten Tageskontingents verbraucht hatte – Groq stand im
Rate-Limit, DeepSeek meldete „Insufficient Balance“, OpenRouter „requires more credits“, ein
Anthropic-Key fehlte. Der Lauf startete trotzdem, verbrauchte 374 k Tokens und endete nach
13 Minuten als `budget_aborted`, mit einer kaputten `app/config.py` als einzigem Ergebnis.

Dieses Gate beantwortet vor dem Start zwei Fragen:
1. **Harte Blockade:** Hat jede eingeplante kritische Rolle (config.CRITICAL_AGENT_IDS) noch
   mindestens ein Modell oberhalb ihrer Mindeststufe (core/model_capability.py), dessen API-Key
   konfiguriert und das nicht nachweislich erschöpft ist (core/token_guard.py)? Wenn nein, würde
   die Rolle garantiert scheitern – der Lauf wird dann gar nicht erst gestartet.
2. **Warnung:** Hängen kritische Rollen ausschließlich an Anbietern, deren heutiger Verbrauch das
   geschätzte Tagesbudget bereits deutlich überschreitet? Das ist nur eine Schätzung (mehrere
   Gemini-Keys erhöhen das echte Kontingent), deshalb warnt es nur und blockiert nicht.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.model_capability import TIER_NAMES, filter_by_floor, min_tier_for_agent
from core.token_guard import token_guard

# Ab diesem Vielfachen des geschätzten Tagesbudgets gilt ein Anbieter als „stark überzogen“.
DAILY_OVERUSE_FACTOR = 2.0

# P5-1 Punkt 3 (ROADMAP_TEMP.md): Ab diesem Anteil der EINGEPLANTEN Rollen (nicht nur der
# kritischen), deren konfiguriertes Modell aktuell nicht erreichbar ist (Key fehlt/Kontingent
# erschöpft), gilt ein Lauf als "größtenteils herabgestuft" - ein Qualitätsrisiko für den
# GESAMTEN Lauf, nicht nur für einzelne blockierte Rollen. Bewusst eine eigene, informative
# Warnung statt einer harten Blockade wie oben: eine Herabstufung bedeutet nicht zwangsläufig
# Scheitern, nur ein erhöhtes Risiko.
MOSTLY_DOWNGRADED_THRESHOLD = 0.5

# core/llm_factory.py._provider_of() nennt Anthropic "anthropic", core/quota_estimator.py "claude".
_PROVIDER_TO_QUOTA_KEY = {"anthropic": "claude"}


@dataclass
class RoleCapacity:
    """Verfügbare Modelle EINER kritischen Rolle oberhalb ihrer Mindeststufe."""
    agent_id: str
    configured_model: str
    min_tier: int
    usable_models: list[str] = field(default_factory=list)


@dataclass
class CapacityAssessment:
    blocked_roles: list[RoleCapacity] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # P5-1 Punkt 3: Rollen, deren konfiguriertes Modell aktuell nicht erreichbar ist - über ALLE
    # eingeplanten Rollen, nicht nur die kritischen (siehe MOSTLY_DOWNGRADED_THRESHOLD).
    downgraded_agent_ids: list[str] = field(default_factory=list)
    planned_role_count: int = 0

    @property
    def blocked(self) -> bool:
        return bool(self.blocked_roles)

    @property
    def downgraded_ratio(self) -> float:
        return len(self.downgraded_agent_ids) / self.planned_role_count if self.planned_role_count else 0.0

    @property
    def mostly_downgraded(self) -> bool:
        return self.downgraded_ratio >= MOSTLY_DOWNGRADED_THRESHOLD

    def format_downgrade_warning(self) -> str:
        return (
            f"⚠️ {len(self.downgraded_agent_ids)} von {self.planned_role_count} eingeplanten Rollen "
            f"({self.downgraded_ratio * 100:.0f}%) würden mit einem herabgestuften Modell starten "
            f"(konfiguriertes Modell aktuell nicht erreichbar): {', '.join(self.downgraded_agent_ids)}. "
            "Qualitätsrisiko für den gesamten Lauf - Kontingent-Reset abwarten oder bewusst so starten."
        )

    def format_block_message(self) -> str:
        rollen = ", ".join(
            f"`{r.agent_id}` (Mindeststufe {TIER_NAMES.get(r.min_tier, r.min_tier)}, konfiguriert `{r.configured_model}`)"
            for r in self.blocked_roles
        )
        return (
            "🛑 Lauf nicht gestartet – Kapazitätsprüfung: Für die eingeplanten kritischen Rollen "
            f"{rollen} ist aktuell KEIN ausreichend starkes Modell verfügbar (API-Key fehlt oder "
            "Kontingent nachweislich erschöpft). Ein Start würde nur Tokens verbrauchen und an "
            "genau diesen Rollen scheitern. Optionen: Kontingent-Reset abwarten, einen weiteren "
            "API-Key in `.env` ergänzen, oder bewusst `CAPACITY_GATE_MODE=warn` bzw. "
            "`HEAVY_ROLE_MIN_TIER=lite` setzen."
        )


def _candidate_chain(configured_model: str) -> list[str]:
    """Alle Modelle, die ein Aufruf dieser Rolle über die Fallback-Ketten erreichen kann."""
    from core.llm_factory import _INDEPENDENT_FAILOVER_MODELS, GEMINI_STANDARD_MODEL, MODEL_FALLBACKS

    chain = [
        configured_model,
        *MODEL_FALLBACKS.get(configured_model, []),
        *_INDEPENDENT_FAILOVER_MODELS,
        GEMINI_STANDARD_MODEL,
        *MODEL_FALLBACKS.get(GEMINI_STANDARD_MODEL, []),
    ]
    return list(dict.fromkeys(chain))


def model_unreachable_reason(model: str) -> str | None:
    """Warum `model` gerade NICHT nutzbar ist - `None`, wenn es nutzbar ist.

    Beantwortet die Frage VOR einem Aufruf, statt sie hinterher am `model_used` des Ergebnisses
    abzulesen. Realer Fund (aetherqueue/eventforge_core, 2026-09-18/19): die Fix-Schleife in
    `agents/orchestrator/verification.py` verbrennt als letzten Rettungsanker einen kompletten
    Agenten-Aufruf mit HEAVY_MODEL. Lag dessen Kontingent auf Cooldown, fiel der Aufruf intern
    auf ein SCHWÄCHERES Modell zurück als das, mit dem der Fix zuvor schon zweimal gescheitert
    war - der Versuch konnte also gar nichts Neues bringen und kostete trotzdem Zeit und Budget.
    Im Protokoll von `eventforge_core` steht das wörtlich: "HEAVY_MODEL-Eskalation für tester
    griff nicht tatsächlich (Kontingent-Erschöpfung o.ä.)".

    Bewusst hier und nicht in core/token_guard.py: beide Teilfragen zusammen ("ist ein Key
    konfiguriert?" UND "ist das Kontingent gerade erschöpft?") beantwortet bisher nur
    `role_capacity()` unten, das sie für die Kapazitätsprüfung vor dem Lauf kombiniert.
    """
    from core.llm_factory import _provider_available

    if not model:
        return "kein Modell konfiguriert"
    if not _provider_available(model):
        return f"kein API-Key/Anbieter für '{model}' konfiguriert"
    if token_guard.is_model_exhausted(model):
        return token_guard.get_exhausted_reason(model) or f"Kontingent für '{model}' erschöpft"
    return None


def model_is_reachable(model: str) -> bool:
    """Kurzform von `model_unreachable_reason(model) is None`."""
    return model_unreachable_reason(model) is None


def role_capacity(agent_id: str) -> RoleCapacity:
    from config import get_model_for_agent

    configured = get_model_for_agent(agent_id)
    min_tier = min_tier_for_agent(agent_id, configured)
    usable = [
        model for model in filter_by_floor(_candidate_chain(configured), min_tier)
        if model_is_reachable(model)
    ]
    return RoleCapacity(agent_id=agent_id, configured_model=configured, min_tier=min_tier, usable_models=usable)


def _overused_providers(factor: float) -> dict[str, float]:
    """Anbieter-Schlüssel (core/quota_estimator.py) -> Verbrauchsquote, ab `factor` × Budget."""
    from core.quota_estimator import FREE_TIER_LIMITS, QuotaEstimator
    from memory.cost_history import get_today_totals

    usage = QuotaEstimator._bucket_usage_by_provider(get_today_totals())
    overused: dict[str, float] = {}
    for key, info in FREE_TIER_LIMITS.items():
        budget = info.get("approx_daily_budget", 0)
        if budget > 0 and usage.get(key, 0) >= factor * budget:
            overused[key] = usage[key] / budget
    return overused


def assess_run_capacity(agent_ids: list[str], overuse_factor: float = DAILY_OVERUSE_FACTOR) -> CapacityAssessment:
    """Bewertet die Kapazität für die in einem Plan eingeplanten Rollen (Duplikate egal)."""
    from config import CRITICAL_AGENT_IDS
    from core.llm_factory import _provider_of

    assessment = CapacityAssessment()
    all_roles = sorted(set(agent_ids))
    assessment.planned_role_count = len(all_roles)
    if all_roles:
        from config import get_model_for_agent

        assessment.downgraded_agent_ids = [
            a for a in all_roles if not model_is_reachable(get_model_for_agent(a))
        ]
        if assessment.mostly_downgraded:
            assessment.warnings.append(assessment.format_downgrade_warning())

    critical = sorted({a for a in agent_ids if a in CRITICAL_AGENT_IDS})
    if not critical:
        return assessment

    capacities = [role_capacity(agent_id) for agent_id in critical]
    assessment.blocked_roles = [c for c in capacities if not c.usable_models]

    try:
        overused = _overused_providers(overuse_factor)
    except Exception:  # Schätzung ist rein informativ – eine defekte Kostenhistorie blockiert nie
        overused = {}
    if overused:
        starved = [
            c.agent_id for c in capacities
            if c.usable_models and all(
                _PROVIDER_TO_QUOTA_KEY.get(_provider_of(m), _provider_of(m)) in overused for m in c.usable_models
            )
        ]
        if starved:
            quoten = ", ".join(f"{k} {ratio * 100:.0f}%" for k, ratio in sorted(overused.items()))
            assessment.warnings.append(
                f"⚠️ Kapazität knapp: Die kritischen Rollen {', '.join(starved)} hängen ausschließlich an "
                f"Anbietern, deren heutiger Verbrauch das geschätzte Tagesbudget bereits deutlich "
                f"überschreitet ({quoten}). Mit Abbrüchen durch 429/RESOURCE_EXHAUSTED ist zu rechnen – "
                "kleinere Aufgabe wählen oder später starten."
            )
    return assessment
