"""
tests/test_model_name_normalization.py – Kanonische Modellnamen & respektiertes Provider-Pinning

Zwei Funde der KI-Team-Masterplan-Analyse:

1. Provider-Wrapper (GroqClient/OpenRouterClient/DeepSeekClient) entfernen beim Anlegen das
   Provider-Präfix, weil die jeweilige API den reinen Modellnamen erwartet. Vergleiche der Form
   `agent._llm.model_name == HEAVY_MODEL` sind dadurch strukturell falsch, sobald HEAVY_MODEL
   präfixbehaftet ist – _escalate_agent_models() hielte dann JEDEN Agenten für nicht
   hochgestuft. Solange HEAVY_MODEL auf Claude zeigte, fiel das nie auf.

2. `_allow_self_fallback=False` steuerte in GeminiClient nur den Groq-Hop am Methodenanfang,
   nicht die eigentliche Fallback-Kette. Live reproduziert: Ein auf `gemini-3.8-flash`
   gepinnter Aufruf wurde von `gemini-3.6-flash` beantwortet. Damit war das Provider-Pinning
   aus agents/base_agent.py für Gemini-Modelle wirkungslos – genau der Zustand, den der dortige
   Kommentar als Ursache des "missing thought_signature"-Abbruchs beschreibt.
"""

import pytest

from core.llm_factory import (
    MODEL_FALLBACKS,
    _resolve_gemini_candidates,
    is_same_model,
    normalize_model_name,
)


class TestNormalisierung:
    @pytest.mark.parametrize("eingabe,erwartet", [
        ("groq:openai/gpt-oss-120b", "openai/gpt-oss-120b"),
        ("openrouter:openrouter/auto", "openrouter/auto"),
        ("deepseek:deepseek-chat", "deepseek-chat"),
        ("huggingface:meta/llama", "meta/llama"),
        ("gemini-3.1-flash-lite", "gemini-3.1-flash-lite"),
        ("claude-sonnet-5", "claude-sonnet-5"),
        ("", ""),
    ])
    def test_praefixe_werden_entfernt(self, eingabe, erwartet):
        assert normalize_model_name(eingabe) == erwartet

    def test_nur_ein_fuehrendes_praefix_wird_entfernt(self):
        """Ein Doppelpunkt im eigentlichen Modellnamen darf nicht mit abgeschnitten werden."""
        assert normalize_model_name("groq:anbieter:modell") == "anbieter:modell"

    def test_leerraum_wird_toleriert(self):
        assert normalize_model_name("  groq:openai/gpt-oss-120b  ") == "openai/gpt-oss-120b"

    def test_none_faellt_auf_leerstring_zurueck(self):
        assert normalize_model_name(None) == ""

    @pytest.mark.parametrize("a,b", [
        ("groq:openai/gpt-oss-120b", "openai/gpt-oss-120b"),
        ("openai/gpt-oss-120b", "groq:openai/gpt-oss-120b"),
        ("gemini-3.6-flash", "gemini-3.6-flash"),
    ])
    def test_is_same_model_erkennt_gleichheit(self, a, b):
        assert is_same_model(a, b) is True

    @pytest.mark.parametrize("a,b", [
        ("groq:openai/gpt-oss-120b", "gemini-3.6-flash"),
        ("claude-sonnet-5", "claude-opus-5"),
    ])
    def test_is_same_model_erkennt_unterschiede(self, a, b):
        assert is_same_model(a, b) is False


class TestPinning:
    def test_gepinnter_aufruf_baut_keine_ersatzkette(self):
        """Der Kernbefund: _allow_self_fallback=False muss auf GENAU ein Modell begrenzen."""
        assert _resolve_gemini_candidates("gemini-3.8-flash", False) == ["gemini-3.8-flash"]

    def test_freier_aufruf_nutzt_die_volle_kette(self):
        kandidaten = _resolve_gemini_candidates("gemini-3.8-flash", True)
        assert kandidaten[0] == "gemini-3.8-flash"
        assert kandidaten[1:] == MODEL_FALLBACKS["gemini-3.8-flash"]

    def test_unbekanntes_modell_bleibt_alleinstehend(self):
        assert _resolve_gemini_candidates("gemini-experimentell", True) == ["gemini-experimentell"]

    def test_gepinnt_gilt_auch_fuer_unbekannte_modelle(self):
        assert _resolve_gemini_candidates("gemini-experimentell", False) == ["gemini-experimentell"]


class TestDowngradeListener:
    def test_listener_wird_bei_abwertung_gerufen(self):
        from core.llm_factory import _notify_model_downgrade, set_model_downgrade_listener
        gemeldet = []
        set_model_downgrade_listener(lambda a, b, g: gemeldet.append((a, b, g)))
        try:
            _notify_model_downgrade("gemini-3.8-flash", "gemini-3.1-flash-lite", "Test")
            assert gemeldet == [("gemini-3.8-flash", "gemini-3.1-flash-lite", "Test")]
        finally:
            set_model_downgrade_listener(None)

    def test_kein_ruf_ohne_echte_abwertung(self):
        from core.llm_factory import _notify_model_downgrade, set_model_downgrade_listener
        gemeldet = []
        set_model_downgrade_listener(lambda a, b, g: gemeldet.append((a, b, g)))
        try:
            _notify_model_downgrade("gemini-3.6-flash", "gemini-3.6-flash", "Test")
            assert gemeldet == []
        finally:
            set_model_downgrade_listener(None)

    def test_fehlerhafter_listener_bricht_den_aufruf_nicht_ab(self):
        """Eine reine Benachrichtigung darf nie einen laufenden LLM-Aufruf kippen."""
        from core.llm_factory import _notify_model_downgrade, set_model_downgrade_listener

        def _kaputt(*args):
            raise RuntimeError("Listener defekt")

        set_model_downgrade_listener(_kaputt)
        try:
            _notify_model_downgrade("a", "b", "Test")  # darf nicht werfen
        finally:
            set_model_downgrade_listener(None)
