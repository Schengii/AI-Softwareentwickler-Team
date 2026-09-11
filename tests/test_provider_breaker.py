"""
tests/test_provider_breaker.py – Circuit Breaker bei Massen-Ausfall der Provider

Regressionsschutz für einen Fund der KI-Team-Masterplan-Analyse: Im Lauf
workspace/event_ticket_api (09.09.2026, 14:43) scheiterten 19 von 21 Agenten-Aufrufen an
erschöpften API-Kontingenten. `files_written_count` war 0 – trotzdem lief der Lauf komplett
weiter, startete die Verifikation, dispatchte einen Fix-Auftrag "keine Tests gefunden" und
schrieb PROJECT_STATE.md mit dem Status "In Entwicklung". Beide Folgeaktionen beschrieben ein
Problem, das es nicht gab: Es fehlten keine Tests, es fehlte das Kontingent.
"""

from types import SimpleNamespace

import pytest

from core.provider_exhaustion import (
    FAILURE_CLASS_AGENT_ERROR,
    FAILURE_CLASS_PROVIDER_EXHAUSTED,
    infrastructure_failure_ratio,
    should_trip_breaker,
)


def _ok():
    return SimpleNamespace(success=True, error=None, failure_class="")


def _kontingent():
    return SimpleNamespace(success=False, error="429 RESOURCE_EXHAUSTED",
                           failure_class=FAILURE_CLASS_PROVIDER_EXHAUSTED)


def _echter_fehler():
    return SimpleNamespace(success=False, error="AttributeError: kaputt",
                           failure_class=FAILURE_CLASS_AGENT_ERROR)


class TestQuote:
    def test_leere_welle_ergibt_null(self):
        assert infrastructure_failure_ratio([]) == 0.0

    def test_quote_wird_korrekt_berechnet(self):
        assert infrastructure_failure_ratio([_kontingent(), _kontingent(), _ok(), _ok()]) == 0.5

    def test_echte_fehler_zaehlen_nicht_zur_infrastrukturquote(self):
        assert infrastructure_failure_ratio([_echter_fehler(), _echter_fehler()]) == 0.0

    def test_altbestand_ohne_failure_class_wird_ueber_fehlermeldung_erkannt(self):
        alt = SimpleNamespace(success=False, error="429 quota exceeded")
        assert infrastructure_failure_ratio([alt]) == 1.0


class TestBreaker:
    def test_loest_bei_ueberschreiten_der_schwelle_aus(self):
        """Der reale Fall: 19 von 21 Aufrufen infrastrukturbedingt gescheitert."""
        welle = [_kontingent()] * 19 + [_ok()] * 2
        assert should_trip_breaker(welle, 0.6) is True

    def test_loest_bei_vereinzelten_ausfaellen_nicht_aus(self):
        welle = [_kontingent()] + [_ok()] * 9
        assert should_trip_breaker(welle, 0.6) is False

    def test_genau_auf_der_schwelle_loest_aus(self):
        welle = [_kontingent()] * 6 + [_ok()] * 4
        assert should_trip_breaker(welle, 0.6) is True

    def test_schwelle_null_schaltet_den_breaker_ab(self):
        """Rückfallebene auf das alte Verhalten, falls jemand den Breaker nicht will."""
        assert should_trip_breaker([_kontingent()] * 10, 0.0) is False

    def test_leere_welle_loest_nie_aus(self):
        assert should_trip_breaker([], 0.6) is False

    def test_reine_agentenfehler_loesen_den_breaker_nicht_aus(self):
        """Wichtig: Ein Lauf mit echten Bugs muss weiterlaufen und diese beheben dürfen."""
        assert should_trip_breaker([_echter_fehler()] * 10, 0.6) is False


class TestOrchestratorIntegration:
    def test_dispatch_setzt_die_flagge(self):
        """Prüft die tatsächliche Verdrahtung in agents/orchestrator/dispatch.py."""
        import asyncio
        from unittest.mock import patch

        from agents.orchestrator.dispatch import DispatchMixin

        class _Orchestrator(DispatchMixin):
            def __init__(self):
                self._agents = {}
                self._dept_leads = {}
                self._provider_exhausted_this_run = False
                self._provider_breaker_tripped = False

            def _status_notify_line(self, *a, **k):
                return ""

        orch = _Orchestrator()
        welle = [_kontingent()] * 19 + [_ok()] * 2

        async def _fake_gather(*args, **kwargs):
            return welle

        meldungen = []
        with patch("agents.orchestrator.dispatch.asyncio.gather", _fake_gather):
            asyncio.run(orch._run_agents_parallel([], notify=meldungen.append))

        assert orch._provider_breaker_tripped is True
        assert orch._provider_exhausted_this_run is True
        assert any("sauber beendet" in m for m in meldungen)

    def test_dispatch_setzt_die_flagge_bei_echten_fehlern_nicht(self):
        import asyncio
        from unittest.mock import patch

        from agents.orchestrator.dispatch import DispatchMixin

        class _Orchestrator(DispatchMixin):
            def __init__(self):
                self._agents = {}
                self._dept_leads = {}
                self._provider_exhausted_this_run = False
                self._provider_breaker_tripped = False

            def _status_notify_line(self, *a, **k):
                return ""

        orch = _Orchestrator()

        async def _fake_gather(*args, **kwargs):
            return [_echter_fehler()] * 10

        with patch("agents.orchestrator.dispatch.asyncio.gather", _fake_gather):
            asyncio.run(orch._run_agents_parallel([], notify=lambda m: None))

        assert orch._provider_breaker_tripped is False


@pytest.mark.parametrize("schwelle,erwartet", [(0.5, True), (0.9, False), (1.0, False)])
def test_schwelle_ist_konfigurierbar(schwelle, erwartet):
    welle = [_kontingent()] * 6 + [_ok()] * 4
    assert should_trip_breaker(welle, schwelle) is erwartet


class TestVerificationSummaryPrioritaet:
    """
    Regressionsschutz (Bugfix, chronos_queue-Nacharbeit 20260911): Der neue Fast Circuit
    Breaker in agents/orchestrator/department.py setzt beim Auslösen bewusst ZUSÄTZLICH
    budget_aborted=True (um Governance-Fix-/Klärungs-Schleifen ebenfalls zu überspringen).
    agents/orchestrator/__init__.py prüfte `budget_aborted or manually_cancelled` bisher VOR
    `_provider_breaker_tripped` - die viel genauere, provider-spezifische Verifikations-
    Meldung war dadurch für genau den Fall, für den sie geschrieben wurde, unerreichbar; der
    Nutzer sah stattdessen die irreführende generische "Lauf-Budget erreicht"-Meldung, obwohl
    real kein Token-Budget, sondern ein API-Kontingent erschöpft war.
    """

    def test_provider_meldung_hat_vorrang_vor_generischer_budget_meldung(self):
        import asyncio
        import shutil
        import tempfile
        import unittest.mock as mock

        from agents.orchestrator import Orchestrator
        from core.llm_factory import LLMResponse
        from core.message_bus import AgentTask
        from core.workspace import WorkspaceManager

        class _FakeLLM:
            model_name = "fake-model"

            async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
                return LLMResponse(text="Fertig.", model_name=self.model_name,
                                    prompt_tokens=1, completion_tokens=1, total_tokens=2, tool_calls=[])

            async def generate_with_usage(self, prompt, system_prompt=None):
                return LLMResponse(text="Fertig.", model_name=self.model_name,
                                    prompt_tokens=1, completion_tokens=1, total_tokens=2)

        temp_workspace = tempfile.mkdtemp()
        try:
            orchestrator = Orchestrator()
            orchestrator._workspace = WorkspaceManager(temp_workspace)
            for agent in list(orchestrator._agents.values()) + list(orchestrator._dept_leads.values()):
                agent._llm = _FakeLLM()

            async def _fake_hierarchy(self, **kwargs):
                # Simuliert exakt das, was der Fast Circuit Breaker in department.py beim
                # Auslösen tut: BEIDE Flags setzen, budget_aborted=True zurückgeben.
                self._provider_exhausted_this_run = True
                self._provider_breaker_tripped = True
                return [], {}, True, False

            with mock.patch("core.task_manager.TaskManager.decompose") as mock_decompose, \
                 mock.patch.object(Orchestrator, "_run_department_hierarchy", _fake_hierarchy), \
                 mock.patch("core.result_aggregator.ResultAggregator.synthesize") as mock_synth, \
                 mock.patch("agents.orchestrator.record_lesson"):
                # record_lesson gemockt: dieser Test triggert absichtlich den "infrastructure_
                # blocker"-Lesson-Eintrag (agents/orchestrator/__init__.py) - ohne Mock würde ein
                # echter Eintrag in memory/team_lessons.jsonl landen (dieselbe reale Datei, die
                # auch echte Läufe schreiben), statt in einem isolierten Test-Fixture zu bleiben.
                mock_decompose.return_value = (
                    "Kurze Aufgabe", "test_proj_breaker_prio",
                    [AgentTask(task_id="t1", agent_id="backend", description="Etwas bauen")],
                )
                mock_synth.return_value = ("### Fertig", 1)
                asyncio.run(orchestrator.process("Baue etwas"))

            assert "erschöpften API-Kontingenten" in orchestrator.last_verification_summary
            assert "Lauf-Budget" not in orchestrator.last_verification_summary
        finally:
            shutil.rmtree(temp_workspace, ignore_errors=True)
