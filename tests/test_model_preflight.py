"""
tests/test_model_preflight.py – Ehrliche Bestandsaufnahme der nutzbaren Modelle

Regressionsschutz für den Kernbefund der KI-Team-Masterplan-Analyse: Live wurden Aufrufe gegen
`claude-sonnet-5` (HEAVY), `gemini-3.8-flash` (STANDARD) und `gemini-3.1-flash-lite` (LITE)
ALLE DREI von demselben Modell beantwortet (`groq:openai/gpt-oss-120b`) – die Drei-Stufen-
Zuordnung war zur Laufzeit wirkungslos, ohne dass es irgendwo auffiel.
"""

from unittest.mock import MagicMock, patch

import pytest

from core.llm_factory import LLMResponse
from core.model_preflight import (
    TierStatus,
    assess_run_readiness,
    check_tier,
    format_preflight_report,
    format_recovery_outlook,
    format_run_readiness,
    run_model_preflight,
)


def _antwort(model_name: str) -> LLMResponse:
    return LLMResponse(text="OK", model_name=model_name, prompt_tokens=5, completion_tokens=1, total_tokens=6)


class _FakeClient:
    def __init__(self, antwort_modell: str | None = None, fehler: Exception | None = None):
        self._antwort_modell = antwort_modell
        self._fehler = fehler

    async def generate_with_usage(self, *args, **kwargs):
        if self._fehler:
            raise self._fehler
        return _antwort(self._antwort_modell)


class TestCheckTier:
    @pytest.mark.asyncio
    async def test_erkennt_erreichbares_modell(self):
        with patch("core.llm_factory.LLMFactory.create_for_model", return_value=_FakeClient("gemini-3.1-flash-lite")):
            status = await check_tier("LITE", "gemini-3.1-flash-lite")
        assert status.reachable is True
        assert status.downgraded is False
        assert status.effective_model == "gemini-3.1-flash-lite"

    @pytest.mark.asyncio
    async def test_erkennt_stille_abwertung(self):
        """Der eigentliche Befund: angefordert wird Claude, geantwortet hat Groq."""
        with patch("core.llm_factory.LLMFactory.create_for_model", return_value=_FakeClient("groq:openai/gpt-oss-120b")):
            status = await check_tier("HEAVY", "claude-sonnet-5")
        assert status.reachable is True
        assert status.downgraded is True
        assert status.effective_model == "groq:openai/gpt-oss-120b"

    @pytest.mark.asyncio
    async def test_nicht_erreichbares_modell_wird_als_fehler_gemeldet(self):
        with patch("core.llm_factory.LLMFactory.create_for_model", return_value=_FakeClient(fehler=RuntimeError("429 quota"))):
            status = await check_tier("STANDARD", "gemini-3.8-flash")
        assert status.reachable is False
        assert status.downgraded is False
        assert "429" in status.error

    @pytest.mark.asyncio
    async def test_listener_wird_danach_wieder_abgeraeumt(self):
        """Der Downgrade-Listener ist global – er darf nach dem Preflight nicht gesetzt bleiben."""
        import core.llm_factory as lf
        with patch("core.llm_factory.LLMFactory.create_for_model", return_value=_FakeClient("m")):
            await check_tier("LITE", "m")
        assert lf._model_downgrade_listener is None

    @pytest.mark.asyncio
    async def test_listener_auch_nach_fehler_abgeraeumt(self):
        import core.llm_factory as lf
        with patch("core.llm_factory.LLMFactory.create_for_model", side_effect=RuntimeError("kaputt")):
            status = await check_tier("LITE", "m")
        assert status.reachable is False
        assert lf._model_downgrade_listener is None


class TestReport:
    def test_meldet_wenn_alle_stufen_auf_einem_modell_landen(self):
        """Genau der Zustand, der die Analyse ausgelöst hat."""
        ergebnisse = [
            TierStatus("LITE", "gemini-3.1-flash-lite", "groq:openai/gpt-oss-120b", reachable=True),
            TierStatus("STANDARD", "gemini-3.8-flash", "groq:openai/gpt-oss-120b", reachable=True),
            TierStatus("HEAVY", "claude-sonnet-5", "groq:openai/gpt-oss-120b", reachable=True),
        ]
        bericht = format_preflight_report(ergebnisse)
        assert "ALLE Stufen laufen auf demselben Modell" in bericht
        assert "wirkungslos" in bericht

    def test_meldet_sauberen_zustand(self):
        ergebnisse = [
            TierStatus("LITE", "a", "a", reachable=True),
            TierStatus("HEAVY", "b", "b", reachable=True),
        ]
        bericht = format_preflight_report(ergebnisse)
        assert "Alle Stufen antworten mit dem konfigurierten Modell" in bericht
        assert "ALLE Stufen laufen auf demselben Modell" not in bericht

    def test_meldet_unerreichbare_stufen(self):
        ergebnisse = [TierStatus("HEAVY", "claude-sonnet-5", error="401 Unauthorized")]
        bericht = format_preflight_report(ergebnisse)
        assert "nicht erreichbar" in bericht
        assert "HEAVY" in bericht

    def test_einzelne_stufe_loest_keine_gleichheitswarnung_aus(self):
        """Bei nur einer geprüften Stufe ist 'alle auf einem Modell' trivial wahr, aber kein Befund."""
        bericht = format_preflight_report([TierStatus("LITE", "a", "a", reachable=True)])
        assert "ALLE Stufen laufen auf demselben Modell" not in bericht


class TestGesamtlauf:
    @pytest.mark.asyncio
    async def test_prueft_alle_vier_stufen(self):
        # DeepSeek/OpenRouter werden nur angepingt, wenn ein Key konfiguriert ist (siehe
        # check_independent_failover_providers) - hier bewusst ohne Key, damit dieser Test
        # unabhängig von der lokalen .env exakt die vier Kern-Stufen prüft.
        with patch("core.llm_factory.LLMFactory.create_for_model", return_value=_FakeClient("x")), \
             patch("core.model_preflight.config.DEEPSEEK_API_KEY", ""), \
             patch("core.model_preflight.config.OPENROUTER_API_KEY", ""):
            ergebnisse = await run_model_preflight()
        assert [r.tier for r in ergebnisse] == ["LITE", "STANDARD", "HEAVY", "ORCHESTRATOR"]

    @pytest.mark.asyncio
    async def test_zeitueberschreitung_blockiert_den_start_nicht(self):
        import asyncio

        class _HaengenderClient:
            async def generate_with_usage(self, *a, **k):
                await asyncio.sleep(10)

        with patch("core.llm_factory.LLMFactory.create_for_model", return_value=_HaengenderClient()):
            status = await check_tier("LITE", "m", timeout_seconds=0.05)
        assert status.reachable is False
        assert "Zeitüberschreitung" in status.error

    @pytest.mark.asyncio
    async def test_defekte_factory_wirft_nicht_durch(self):
        with patch("core.llm_factory.LLMFactory.create_for_model", side_effect=ValueError("unbekanntes Modell")):
            ergebnisse = await run_model_preflight()
        assert all(not r.reachable for r in ergebnisse)
        assert format_preflight_report(ergebnisse)


def test_magicmock_client_wird_nicht_faelschlich_als_erreichbar_gewertet():
    """Absicherung gegen Testfehler: Ein MagicMock ohne await-bare Antwort muss scheitern."""
    import asyncio
    with patch("core.llm_factory.LLMFactory.create_for_model", return_value=MagicMock()):
        status = asyncio.run(check_tier("LITE", "m"))
    assert status.reachable is False


class TestPraefixFehlalarm:
    """
    Regressionsschutz gegen einen Fehlalarm, der bei der Verdrahtungspruefung auffiel: Die
    Provider-Wrapper entfernen ihr Praefix beim Anlegen ("groq:openai/gpt-oss-120b" wird zu
    "openai/gpt-oss-120b"). Ein direkter Namensvergleich meldete deshalb bei JEDEM Groq-,
    OpenRouter- und DeepSeek-Aufruf faelschlich eine Modell-Abwertung.
    """

    def test_praefixunterschied_ist_keine_abwertung(self):
        status = TierStatus(
            "HEAVY", requested_model="openai/gpt-oss-120b",
            effective_model="groq:openai/gpt-oss-120b", reachable=True,
        )
        assert status.downgraded is False

    def test_echte_abwertung_wird_weiterhin_erkannt(self):
        status = TierStatus(
            "HEAVY", requested_model="claude-sonnet-5",
            effective_model="groq:openai/gpt-oss-120b", reachable=True,
        )
        assert status.downgraded is True

    def test_gleichheitswarnung_ignoriert_praefixunterschiede(self):
        """Sonst bliebe der wichtigste Befund genau dann aus, wenn er zutrifft."""
        ergebnisse = [
            TierStatus("LITE", "openai/gpt-oss-120b", "openai/gpt-oss-120b", reachable=True),
            TierStatus("HEAVY", "groq:openai/gpt-oss-120b", "groq:openai/gpt-oss-120b", reachable=True),
        ]
        assert "ALLE Stufen laufen auf demselben Modell" in format_preflight_report(ergebnisse)


class TestRunReadiness:
    """
    Testet die Ampel-Empfehlung (Sicherheitsmaßnahme, KI-Team-Gesamtanalyse): vor jeder neuen
    Projektaufgabe soll sichtbar sein, ob sich ein Lauf gerade überhaupt lohnt - nicht nur,
    welches Modell konkret antwortet.
    """

    def _tier(self, tier: str, requested: str = "m", effective: str | None = None,
              reachable: bool = True, error: str = "", auth_error_marker: bool = False) -> TierStatus:
        status = TierStatus(
            tier=tier, requested_model=requested,
            effective_model=effective if effective is not None else (requested if reachable else ""),
            reachable=reachable, error=error,
        )
        return status

    def test_alle_kernstufen_erreichbar_und_unveraendert_ist_gruen(self):
        ergebnisse = [
            self._tier("LITE"), self._tier("STANDARD"), self._tier("HEAVY"), self._tier("ORCHESTRATOR"),
        ]
        readiness = assess_run_readiness(ergebnisse)
        assert readiness.level == "green"
        assert readiness.should_confirm is False
        assert "lohnt sich jetzt" in readiness.headline

    def test_keine_kernstufe_erreichbar_ist_rot(self):
        ergebnisse = [
            self._tier("LITE", reachable=False, error="429 quota"),
            self._tier("STANDARD", reachable=False, error="429 quota"),
            self._tier("HEAVY", reachable=False, error="401 invalid key"),
            self._tier("ORCHESTRATOR", reachable=False, error="timeout"),
        ]
        readiness = assess_run_readiness(ergebnisse)
        assert readiness.level == "red"
        assert readiness.should_confirm is True
        assert "KEIN neuer Projektlauf" in readiness.headline
        assert len(readiness.reasons) == 4

    def test_teilweise_erreichbar_ist_gelb(self):
        ergebnisse = [
            self._tier("LITE"),
            self._tier("STANDARD", reachable=False, error="429 quota"),
            self._tier("HEAVY"),
            self._tier("ORCHESTRATOR"),
        ]
        readiness = assess_run_readiness(ergebnisse)
        assert readiness.level == "yellow"
        assert readiness.should_confirm is False
        assert any("STANDARD" in r for r in readiness.reasons)

    def test_abwertung_ohne_ausfall_ist_ebenfalls_gelb(self):
        ergebnisse = [
            self._tier("LITE"),
            self._tier("STANDARD"),
            self._tier("HEAVY", requested="claude-sonnet-5", effective="groq:openai/gpt-oss-120b"),
            self._tier("ORCHESTRATOR"),
        ]
        readiness = assess_run_readiness(ergebnisse)
        assert readiness.level == "yellow"
        assert any("HEAVY" in r and "groq" in r for r in readiness.reasons)

    def test_unabhaengige_failover_provider_zaehlen_nicht_fuer_die_ampel(self):
        """DeepSeek/OpenRouter sind optionale Ausweichrouten, kein Kernbestandteil - ihr
        Ausfall allein darf die sonst grüne Ampel nicht auf gelb/rot ziehen."""
        ergebnisse = [
            self._tier("LITE"), self._tier("STANDARD"), self._tier("HEAVY"), self._tier("ORCHESTRATOR"),
            self._tier("DEEPSEEK", reachable=False, error="Insufficient Balance"),
        ]
        readiness = assess_run_readiness(ergebnisse)
        assert readiness.level == "green"

    def test_format_gibt_headline_und_gruende_aus(self):
        ergebnisse = [
            self._tier("LITE"),
            self._tier("STANDARD", reachable=False, error="429 quota"),
            self._tier("HEAVY"),
            self._tier("ORCHESTRATOR"),
        ]
        readiness = assess_run_readiness(ergebnisse)
        text = format_run_readiness(readiness)
        assert readiness.headline in text
        assert "STANDARD" in text


class _FakeGuard:
    """Minimaler Stand-in für core.token_guard.TokenGuard - nur get_exhausted_details() wird
    von format_recovery_outlook() gebraucht."""
    def __init__(self, details: list[dict]):
        self._details = details

    def get_exhausted_details(self) -> list[dict]:
        return self._details


class TestRecoveryOutlook:
    """
    Nutzerwunsch: neben der reinen Ampel soll sichtbar sein, WANN genau die aktuell nicht
    erreichbaren Modelle voraussichtlich wieder verfügbar sind - und ab wann das Team wieder
    VOLLSTÄNDIG einsatzbereit ist.
    """

    def test_leer_wenn_alle_kernstufen_erreichbar(self):
        ergebnisse = [
            TierStatus("LITE", "a", "a", reachable=True),
            TierStatus("STANDARD", "b", "b", reachable=True),
        ]
        assert format_recovery_outlook(ergebnisse, guard=_FakeGuard([])) == ""

    def test_bekannter_cooldown_zeigt_uhrzeit_und_gesamt_prognose(self):
        ergebnisse = [
            TierStatus("STANDARD", "gemini-3.8-flash", reachable=False, error="429 quota"),
        ]
        guard = _FakeGuard([{
            "model_name": "gemini-3.8-flash",
            "reason": "429 RESOURCE_EXHAUSTED",
            "remaining_seconds": 120.0,
            "available_at": "14:32:10",
        }])
        text = format_recovery_outlook(ergebnisse, guard=guard)
        assert "STANDARD" in text
        assert "gemini-3.8-flash" in text
        assert "14:32:10 Uhr" in text
        assert "VOLLSTÄNDIG einsatzbereit ab 14:32:10 Uhr" in text

    def test_unbekannter_cooldown_verweigert_gesamt_prognose(self):
        """Ein Auth-Fehler (falscher Key) setzt sich NIE von selbst zurück - dafür darf keine
        Uhrzeit versprochen werden, die es nicht gibt."""
        ergebnisse = [
            TierStatus("HEAVY", "claude-sonnet-5", reachable=False, error="401 Unauthorized"),
        ]
        text = format_recovery_outlook(ergebnisse, guard=_FakeGuard([]))
        assert "HEAVY" in text
        assert "kein automatischer Reset-Zeitpunkt bekannt" in text
        assert "✅" not in text  # keine positive Gesamt-Prognose

    def test_gemischt_bekannt_und_unbekannt_verweigert_ebenfalls_gesamt_prognose(self):
        ergebnisse = [
            TierStatus("STANDARD", "gemini-3.8-flash", reachable=False, error="429 quota"),
            TierStatus("HEAVY", "claude-sonnet-5", reachable=False, error="401 Unauthorized"),
        ]
        guard = _FakeGuard([{
            "model_name": "gemini-3.8-flash", "reason": "429", "remaining_seconds": 60.0,
            "available_at": "10:00:00",
        }])
        text = format_recovery_outlook(ergebnisse, guard=guard)
        assert "10:00:00 Uhr" in text  # einzelne bekannte Stufe wird trotzdem gezeigt
        assert "✅" not in text  # aber keine positive Gesamt-Prognose

    def test_praefixierte_modellnamen_werden_gefunden(self):
        """core/llm_factory.py hinterlegt manche Provider mit Präfix (z.B. 'groq:...') -
        die Zuordnung muss auch dann noch klappen."""
        ergebnisse = [TierStatus("STANDARD", "openai/gpt-oss-120b", reachable=False, error="429")]
        guard = _FakeGuard([{
            "model_name": "groq:openai/gpt-oss-120b", "reason": "429", "remaining_seconds": 30.0,
            "available_at": "09:00:00",
        }])
        text = format_recovery_outlook(ergebnisse, guard=guard)
        assert "09:00:00 Uhr" in text

    def test_reine_stufenlisten_ohne_unerreichbare_kernstufe_bleiben_leer(self):
        """DeepSeek/OpenRouter (kein CORE_TIER) zählen nicht mit, selbst wenn unerreichbar."""
        ergebnisse = [
            TierStatus("LITE", "a", "a", reachable=True),
            TierStatus("DEEPSEEK", "deepseek-chat", reachable=False, error="Insufficient Balance"),
        ]
        assert format_recovery_outlook(ergebnisse, guard=_FakeGuard([])) == ""


class TestRunLoggerPraefix:
    def test_run_logger_meldet_keine_abwertung_bei_praefixunterschied(self, tmp_path):
        import json
        from unittest.mock import patch

        from core import run_logger as rl
        from core.message_bus import AgentResult

        with patch.object(rl, "RUN_LOGS_DIR", tmp_path / "runs"), \
             patch.object(rl, "VERIFICATION_LOGS_DIR", tmp_path / "verif"):
            logger = rl.RunLogger(project_slug="demo")
            logger.log_agent_result(
                AgentResult(task_id="t", agent_id="backend", agent_name="Backend", success=True,
                            content="x", model_used="groq:openai/gpt-oss-120b"),
                requested_model="openai/gpt-oss-120b",
            )
            eintrag = json.loads(logger.run_log_path.read_text(encoding="utf-8").splitlines()[0])
        assert eintrag["model_downgraded"] is False
