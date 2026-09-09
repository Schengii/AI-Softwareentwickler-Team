"""
tests/test_agent_model_env_keys.py – Rollen-Override muss den Fachbereichs-Override schlagen

Regressionsschutz für einen Fund der KI-Team-Masterplan-Analyse: config.get_model_for_agent()
prüfte in Schritt 1 hart `f"{agent_id.upper()}_MODEL"`. Bei sieben Rollen heißt die tatsächlich
in AGENT_MODELS ausgewertete Umgebungsvariable jedoch anders (z.B. `PO_MODEL` statt
`PRODUCT_OWNER_MODEL`). Für diese Rollen wurde ein ausdrücklich gesetzter Rollen-Override still
von einem Fachbereichs-Override überstimmt – die Vorrang-Regel kehrte sich um.

Der erste Test hält AGENT_MODEL_ENV_KEYS automatisch mit dem echten Quelltext synchron, damit
eine künftig hinzugefügte Rolle mit abweichendem Variablennamen nicht erneut unbemerkt
durchrutscht.
"""

import importlib
import re
from pathlib import Path

import pytest

import config


def _env_keys_aus_quelltext() -> dict[str, str]:
    """Liest die tatsächlich in AGENT_MODELS verwendeten os.getenv-Namen aus config.py."""
    quelle = Path(config.__file__).read_text(encoding="utf-8")
    block = quelle.split("AGENT_MODELS: dict[str, str] = {")[1].split("\n}")[0]
    return {
        m.group(1): m.group(2)
        for m in re.finditer(r'"([a-z_]+)":\s*os\.getenv\("([A-Z_0-9]+)"', block)
    }


class TestEnvKeyMapping:
    def test_jede_abweichende_rolle_ist_erfasst(self):
        """Der eigentliche Regressionsschutz gegen die sieben stillen Fehlzuordnungen."""
        abweichend = {
            agent: env
            for agent, env in _env_keys_aus_quelltext().items()
            if env != f"{agent.upper()}_MODEL"
        }
        assert abweichend == config.AGENT_MODEL_ENV_KEYS

    def test_konventionelle_rollen_brauchen_keinen_eintrag(self):
        for agent, env in _env_keys_aus_quelltext().items():
            if agent not in config.AGENT_MODEL_ENV_KEYS:
                assert config.get_model_env_key(agent) == env

    @pytest.mark.parametrize("agent_id,erwartet", [
        ("product_owner", "PO_MODEL"),
        ("accessibility", "A11Y_MODEL"),
        ("documentation", "DOCS_MODEL"),
        ("backend", "BACKEND_MODEL"),
    ])
    def test_get_model_env_key(self, agent_id, erwartet):
        assert config.get_model_env_key(agent_id) == erwartet


class TestVorrangRegel:
    def test_rollen_override_schlaegt_fachbereichs_override(self, monkeypatch):
        """`product_owner` gehört zum Fachbereich 'planning'. Ein per PO_MODEL gesetzter
        Rollen-Override muss den Fachbereichs-Override schlagen – zuvor gewann fälschlich der
        Fachbereich, weil auf `PRODUCT_OWNER_MODEL` geprüft wurde."""
        monkeypatch.setenv("PO_MODEL", "rollen-modell")
        monkeypatch.setenv("DEPARTMENT_PLANNING_MODEL", "fachbereichs-modell")
        neu = importlib.reload(config)
        try:
            assert neu.get_model_for_agent("product_owner") == "rollen-modell"
        finally:
            monkeypatch.undo()
            importlib.reload(config)

    def test_ohne_rollen_override_gewinnt_der_fachbereich(self, monkeypatch):
        monkeypatch.delenv("PO_MODEL", raising=False)
        monkeypatch.setenv("DEPARTMENT_PLANNING_MODEL", "fachbereichs-modell")
        neu = importlib.reload(config)
        try:
            assert neu.get_model_for_agent("product_owner") == "fachbereichs-modell"
        finally:
            monkeypatch.undo()
            importlib.reload(config)


class TestTierZuordnungFolgtVerfuegbarenKeys:
    """Kernbefund: HEAVY_MODEL zeigte bedingungslos auf Claude, auch ohne ANTHROPIC_API_KEY –
    13 Rollen und der Orchestrator hatten damit kein funktionierendes Primärmodell."""

    def test_heavy_meidet_provider_ohne_schluessel(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        monkeypatch.setenv("GROQ_API_KEY", "groq-key")
        monkeypatch.delenv("HEAVY_MODEL", raising=False)
        neu = importlib.reload(config)
        try:
            assert "claude" not in neu.HEAVY_MODEL.lower()
            assert neu.HEAVY_MODEL == neu.GROQ_HEAVY_MODEL
        finally:
            monkeypatch.undo()
            importlib.reload(config)

    def test_heavy_nutzt_claude_sobald_ein_schluessel_da_ist(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
        monkeypatch.delenv("HEAVY_MODEL", raising=False)
        neu = importlib.reload(config)
        try:
            assert neu.HEAVY_MODEL == neu.CLAUDE_STANDARD_MODEL
            assert neu.ORCHESTRATOR_MODEL == neu.CLAUDE_HEAVY_MODEL
        finally:
            monkeypatch.undo()
            importlib.reload(config)

    def test_expliziter_env_override_hat_immer_vorrang(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        monkeypatch.setenv("HEAVY_MODEL", "mein-wunschmodell")
        neu = importlib.reload(config)
        try:
            assert neu.HEAVY_MODEL == "mein-wunschmodell"
        finally:
            monkeypatch.undo()
            importlib.reload(config)

    def test_orchestrator_meidet_provider_ohne_schluessel(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        monkeypatch.setenv("GROQ_API_KEY", "groq-key")
        monkeypatch.delenv("ORCHESTRATOR_MODEL", raising=False)
        neu = importlib.reload(config)
        try:
            assert "claude" not in neu.ORCHESTRATOR_MODEL.lower()
        finally:
            monkeypatch.undo()
            importlib.reload(config)

    def test_ohne_jeden_schluessel_bleibt_ein_gueltiger_name_stehen(self, monkeypatch):
        """Ein leerer Modellname dürfte nie durch das Framework wandern."""
        for key in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "DEEPSEEK_API_KEY",
                    "OPENROUTER_API_KEY", "GEMINI_API_KEY"):
            monkeypatch.setenv(key, "")
        monkeypatch.delenv("HEAVY_MODEL", raising=False)
        neu = importlib.reload(config)
        try:
            assert neu.HEAVY_MODEL
            assert neu.LITE_MODEL
            assert neu.STANDARD_MODEL
        finally:
            monkeypatch.undo()
            importlib.reload(config)
