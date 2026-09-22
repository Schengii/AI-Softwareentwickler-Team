"""
agents/orchestrator/budget.py – BudgetMixin: Budget-/Kosten-Tracking über zwei unabhängige
Budgets hinweg – das harte, globale Lauf-Budget (config.MAX_RUN_TOKENS, ggf. per
`--max-tokens`/Komplexitäts-Stufe überschrieben) und das optionale, projektspezifische
Kostenbudget aus `/constitution` (self._project_token_budget).
"""

from contextlib import contextmanager
from contextvars import ContextVar

from config import (
    MAX_RUN_TOKENS,
    MIN_VERIFICATION_TOKEN_RESERVE,
    OPTIONAL_PHASE_IDS,
    PHASE_TOKEN_SHARES,
    VERIFICATION_TOKEN_RESERVE_RATIO,
)
from core.token_guard import token_guard

# Lauf-Budget-Override (Team-Aufgabe "Budget-Flexibilisierung", 2026-09-22): entweder ein
# expliziter `--max-tokens`-Wert (main.py `--goal`, `/goal`-Befehl) oder die zur Aufgaben-
# Komplexität passende Stufe aus config.TASK_COMPLEXITY_TOKEN_BUDGETS (siehe
# agents/orchestrator/department.py). Als ContextVar statt Instanz-Attribut, aus demselben
# Grund wie core/model_capability.py.complex_run(): jede Methode unten liest weiterhin
# `MAX_RUN_TOKENS` als MODUL-globalen Namen (nicht als eingefrorenen Wert), damit bestehende
# Tests, die `patch.object(agents.orchestrator.budget, "MAX_RUN_TOKENS", ...)` direkt auf
# diesem Modul patchen, unverändert funktionieren - der Override greift NUR, wenn diese
# ContextVar explizit gesetzt wurde (process()/department.py), sonst bleibt exakt das alte
# Verhalten (klassenmethoden-basiert, kein Instanz-Zustand nötig).
_max_run_tokens_override: ContextVar[int | None] = ContextVar("_max_run_tokens_override", default=None)


@contextmanager
def max_run_tokens_scope(value: int):
    """Setzt das harte Lauf-Budget für die Dauer des Kontexts (siehe `_max_run_tokens_override`
    oben) - asyncio-Tasks/`asyncio.to_thread()` übernehmen den Kontext automatisch."""
    token = _max_run_tokens_override.set(value)
    try:
        yield
    finally:
        _max_run_tokens_override.reset(token)


def _effective_max_run_tokens() -> int:
    override = _max_run_tokens_override.get()
    return MAX_RUN_TOKENS if override is None else override


class BudgetMixin:
    """Verfolgt Token-Verbrauch und prüft Lauf-/Projekt-Budgets."""

    @staticmethod
    def _tokens_used_since(start_tokens: int) -> int:
        """Tokenverbrauch SEIT dem Schnappschuss start_tokens (nicht der globale Gesamtzähler)."""
        return token_guard.get_summary()["grand_total_tokens"] - start_tokens

    @staticmethod
    def _model_usage_deltas(start_model_stats: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
        """
        Pro-Modell-Verbrauch SEIT dem Schnappschuss start_model_stats (Pendant zu
        _tokens_used_since(), nur pro Modell statt als einzelner Gesamtwert) – Grundlage für
        memory/cost_history.py.record_run_usage(). Ein Modell, das erst WÄHREND dieses Laufs
        zum ersten Mal genutzt wurde, hatte in start_model_stats naturgemäß noch keinen
        Eintrag (Delta = voller aktueller Wert, nicht 0).

        Realer Fund: "cache_read_tokens"/"cache_write_tokens" fehlten hier bisher komplett -
        record_run_usage() erhielt dadurch für jedes Modell IMMER ein Delta von 0 für beide
        Werte, selbst wenn Prompt-Caching (core/llm_factory.py) tatsächlich Cache-Treffer
        hatte. memory/cost_history.json blieb für diese beiden Spalten dauerhaft bei 0 stehen,
        obwohl core/token_guard.py sie längst korrekt mitzählt.
        """
        end_stats = token_guard.get_summary()["models"]
        deltas: dict[str, dict[str, int]] = {}
        for model_name, end_stat in end_stats.items():
            start_stat = start_model_stats.get(model_name, {})
            deltas[model_name] = {
                key: end_stat.get(key, 0) - start_stat.get(key, 0)
                for key in (
                    "total_calls", "prompt_tokens", "completion_tokens", "total_tokens",
                    "cache_read_tokens", "cache_write_tokens",
                )
            }
        return deltas

    @classmethod
    def _run_budget_exceeded(cls, start_tokens: int) -> bool:
        """<=0 deaktiviert das harte Budget (Standard) – siehe config.py."""
        max_run_tokens = _effective_max_run_tokens()
        if max_run_tokens <= 0:
            return False
        return cls._tokens_used_since(start_tokens) >= max_run_tokens

    @classmethod
    def _run_budget_within_confirmation_buffer(cls, start_tokens: int, buffer_ratio: float = 0.10) -> bool:
        """
        Resilienz-Puffer für die LETZTE Testlauf-Bestätigung (Team-Optimierung, siehe
        agents/orchestrator/verification.py._run_verification_loop): MAX_RUN_TOKENS<=0 deaktiviert
        das harte Budget ohnehin (siehe _run_budget_exceeded), dann ist kein Puffer nötig.
        True, wenn das harte Lauf-Budget zwar bereits überschritten ist, die Überschreitung aber
        UNTER `buffer_ratio` (Standard 10%) liegt. Gedacht NUR für den allerletzten Testlauf, der
        bereits angewandte Fixes bestätigt (kein neuer Fixversuch mehr nötig) - ein knapp
        verfehltes Budget soll dann nicht einen tatsächlich grünen Lauf kurz vor Schluss als
        "nicht verifiziert" beenden. Der Aufrufer stellt sicher, dass dieser Puffer höchstens
        EINMAL pro Lauf greift, damit daraus kein schleichendes, wiederholt genutztes Extra-Budget
        wird.
        """
        max_run_tokens = _effective_max_run_tokens()
        if max_run_tokens <= 0:
            return False
        used = cls._tokens_used_since(start_tokens)
        if used < max_run_tokens:
            return False
        return used <= max_run_tokens * (1.0 + buffer_ratio)

    @staticmethod
    def _generation_ceiling(max_run_tokens: int) -> float:
        """
        Obergrenze der Code-GENERIERUNGSPHASE: `max_run_tokens` abzüglich der Verifikations-
        Reserve - das Maximum aus dem anteiligen VERIFICATION_TOKEN_RESERVE_RATIO UND der
        absoluten MIN_VERIFICATION_TOKEN_RESERVE (siehe config.py-Docstring dort), gedeckelt auf
        90% von `max_run_tokens`, damit selbst bei einem sehr kleinen Budget noch ein sinnvoller
        Generierungsanteil übrig bleibt.
        """
        reserve_ratio = min(max(VERIFICATION_TOKEN_RESERVE_RATIO, 0.0), 0.9)
        reserve_tokens = max(max_run_tokens * reserve_ratio, MIN_VERIFICATION_TOKEN_RESERVE)
        reserve_tokens = min(reserve_tokens, max_run_tokens * 0.9)
        return max_run_tokens - reserve_tokens

    @classmethod
    def _generation_budget_exceeded(cls, start_tokens: int) -> bool:
        """
        Wie `_run_budget_exceeded`, aber für die Code-GENERIERUNGSPHASE
        (agents/orchestrator/department.py._run_department_hierarchy): prüft gegen ein um die
        Verifikations-Reserve (siehe `_generation_ceiling`) reduziertes Kontingent, damit die
        anschließende Verifikations-/Fix-Phase (die Autonomie erst beweist, siehe
        agents/orchestrator/verification.py) garantiert noch Budget übrig hat, statt dass ein
        einzelner Lauf sein komplettes Budget bereits beim Codeschreiben verbraucht (realer
        Fund: incidentpilot-Projekt, "Verifikation nach Versuch 0 abgebrochen"). Die
        Verifikations-/Fix-Schleifen selbst rufen weiterhin `_run_budget_exceeded` (volles
        Budget) auf, nicht diese Methode.
        """
        max_run_tokens = _effective_max_run_tokens()
        if max_run_tokens <= 0:
            return False
        return cls._tokens_used_since(start_tokens) >= cls._generation_ceiling(max_run_tokens)

    # Ein optionaler Fachbereich darf starten, solange danach noch mindestens dieser Anteil der
    # Budget-Anteile aller noch folgenden Kern-Fachbereiche übrig bleibt. Nicht 1.0, weil Phasen
    # ihren Anteil in der Praxis selten voll ausschöpfen.
    _CORE_PHASE_SAFETY_FACTOR = 0.5

    @classmethod
    def _phase_budget_allows(cls, dept_id: str, start_tokens: int, remaining_phase_ids: list[str]) -> bool:
        """Budget-Anteile je Fachbereich (config.PHASE_TOKEN_SHARES).

        Kern-Fachbereiche (Planung, Entwicklung, QA, Review) laufen immer - ihr Stopp regelt
        weiterhin `_generation_budget_exceeded()`. Ein OPTIONALER Fachbereich (Design, Content)
        wird übersprungen, wenn sein eigener Anteil plus die Mindestreserve für die noch
        folgenden Kern-Fachbereiche nicht mehr ins verbleibende Generierungsbudget passt -
        vorher konnte Content-/Doku-Arbeit das Budget verbrauchen, das danach für QA und die
        Verifikation fehlte (chronospulse: Tests liefen gar nicht).
        """
        max_run_tokens = _effective_max_run_tokens()
        if max_run_tokens <= 0 or dept_id not in OPTIONAL_PHASE_IDS:
            return True
        generation_ceiling = cls._generation_ceiling(max_run_tokens)
        remaining = generation_ceiling - cls._tokens_used_since(start_tokens)
        core_shares = sum(
            PHASE_TOKEN_SHARES.get(p, 0.0) for p in remaining_phase_ids if p not in OPTIONAL_PHASE_IDS
        )
        needed = (PHASE_TOKEN_SHARES.get(dept_id, 0.0) + core_shares * cls._CORE_PHASE_SAFETY_FACTOR) * generation_ceiling
        return remaining >= needed

    def _generation_reserve_is_hard_abort(self, start_tokens: int) -> bool:
        """
        Team-Optimierung (ChronosPulse-Analyse, 20260913, "Verification Reserve Paradox"):
        `_generation_budget_exceeded()` allein darf NIE einen ganzen Lauf abbrechen - ihr
        einziger Zweck ist, die Code-GENERIERUNGSPHASE rechtzeitig zu stoppen, damit die
        reservierten VERIFICATION_TOKEN_RESERVE_RATIO-Tokens (config.py) tatsächlich noch für
        die Verifikations-/Fix-Phase da sind (siehe _generation_budget_exceeded-Docstring).
        Vorher setzte agents/orchestrator/department.py beim Erreichen dieser Reserve
        fälschlich `budget_aborted=True` für den GESAMTEN Lauf - das übersprang in
        agents/orchestrator/__init__.py (`elif budget_aborted or manually_cancelled:`) exakt
        die Verifikation, für die die Reserve eigens geschaffen wurde (real beobachtet,
        ChronosPulse-Lauf: 852.222 von 1.000.000 Tokens verbraucht, ~150.000 Tokens Reserve
        ungenutzt verpufft, `verification_ok` nie ausgewertet).

        Ein echter, harter Lauf-Abbruch ist NUR gerechtfertigt, wenn zusätzlich zur
        Generierungsreserve auch (a) das volle harte Lauf-Budget (`_run_budget_exceeded()`,
        MAX_RUN_TOKENS OHNE Reserve-Abzug) ODER (b) das separate Pro-Projekt-Kostenbudget
        (`_project_budget_exceeded()`, `/constitution`, das keine eigene Reserve kennt)
        tatsächlich erschöpft ist. Der Aufrufer (department.py) bricht die Fachbereichs-Phase
        in JEDEM Fall ab, sobald hier ODER `_generation_budget_exceeded()` True liefert -
        dieser Wert entscheidet nur, OB er dabei zusätzlich `budget_aborted=True` für den
        gesamten restlichen Lauf setzen darf (True) oder nur `generation_budget_reached=True`
        (False, Verifikation läuft danach regulär mit dem verbleibenden Rest-Budget weiter).
        """
        return self._run_budget_exceeded(start_tokens) or self._project_budget_exceeded(start_tokens)

    def _project_budget_exceeded(self, start_tokens: int) -> bool:
        """
        Pro-Projekt-Kostenbudget (`/constitution` `max_project_tokens`) – unabhängig vom
        globalen MAX_RUN_TOKENS oben, das nur EINEN einzelnen Lauf begrenzt.
        self._project_token_budget<=0 (Standard, kein Feld in der Konstitution gesetzt)
        deaktiviert diese Prüfung vollständig.
        """
        if self._project_token_budget <= 0:
            return False
        total_for_project = self._project_tokens_before_run + self._tokens_used_since(start_tokens)
        return total_for_project >= self._project_token_budget

    def _budget_exceeded_label(self, start_tokens: int) -> str:
        """
        Menschlich lesbare Kennzeichnung, WELCHES der beiden unabhängigen Budgets (Lauf oder
        Projekt) eine Abbruch-Meldung ausgelöst hat – für ehrliche Kommunikation statt
        pauschal auf MAX_RUN_TOKENS zu verweisen, wenn tatsächlich das (u.U. strengere)
        Projekt-Budget bindend war. Nur sinnvoll aufrufbar, wenn mindestens eines von beiden
        tatsächlich überschritten ist.
        """
        if self._project_budget_exceeded(start_tokens):
            return f"Projekt-Budget (`/constitution`, `{self._project_token_budget:,}` Tokens für `{self.last_project_slug}`)"
        return f"Lauf-Budget (`MAX_RUN_TOKENS={_effective_max_run_tokens():,}`)"

    def _budget_or_cancel_reason(
        self, budget_aborted: bool, manually_cancelled: bool, stage: str, start_tokens: int | None = None,
    ) -> str:
        """
        Begründungstext für einen übersprungenen nachfolgenden Schritt (Governance-Fix-Schleife/
        Verifikation) – EIN gebündelter Ort statt der Budget-vs.-Abbruch-Fallunterscheidung
        mehrfach inline zu duplizieren. Nur sinnvoll aufrufbar, wenn budget_aborted ODER
        manually_cancelled bereits True ist (siehe process()).
        """
        if budget_aborted:
            label = self._budget_exceeded_label(start_tokens) if start_tokens is not None else f"Lauf-Budget (`MAX_RUN_TOKENS={_effective_max_run_tokens():,}`)"
            return f"{label} wurde bereits {stage} erreicht"
        assert manually_cancelled, "aufrufbar nur wenn budget_aborted ODER manually_cancelled True ist"
        return f"Lauf wurde bereits {stage} manuell abgebrochen"
