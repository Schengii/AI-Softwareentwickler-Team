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
    check_tier,
    format_preflight_report,
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
        with patch("core.llm_factory.LLMFactory.create_for_model", return_value=_FakeClient("x")):
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
