"""
tests/test_failure_classification.py – Trennung echter Agentenfehler von Infrastruktur-Ausfällen

Regressionsschutz für den zentralen Befund der KI-Team-Masterplan-Analyse (09.09.2026):
memory/run_history.json wies 160 Fehlschläge unter `claude-sonnet-5` aus – für ein Modell, das
laut memory/cost_history.json nie einen einzigen Call gemacht hat (ANTHROPIC_API_KEY war leer).
Diese reinen Kontingent-/Konfigurations-Ausfälle flossen als Qualitätsmängel in die
Erfolgsquoten und damit in die Selbstoptimierung (core/optimization_advisor.py,
core/team_retro.py) ein.
"""

from unittest.mock import patch

import pytest

from core.provider_exhaustion import (
    FAILURE_CLASS_AGENT_ERROR,
    FAILURE_CLASS_PROVIDER_EXHAUSTED,
    FAILURE_CLASS_PROVIDER_UNAVAILABLE,
    FAILURE_CLASS_TIMEOUT,
    classify_failure,
    is_infrastructure_failure,
)
from memory import run_history


class TestClassifyFailure:
    @pytest.mark.parametrize("error", [
        "429 RESOURCE_EXHAUSTED: quota exceeded",
        "google.rpc.QuotaFailure: GenerateRequestsPerDayPerProjectPerModel-FreeTier",
        "Error code: 429 - rate limit reached",
    ])
    def test_kontingent_erschoepfung(self, error):
        assert classify_failure(error) == FAILURE_CLASS_PROVIDER_EXHAUSTED

    @pytest.mark.parametrize("error", [
        "Claude innerhalb einer Fallback-Kette nicht verfügbar (kein ANTHROPIC_API_KEY).",
        "AuthenticationError: invalid_api_key",
        "401 Unauthorized",
    ])
    def test_provider_nicht_verfuegbar(self, error):
        assert classify_failure(error) == FAILURE_CLASS_PROVIDER_UNAVAILABLE

    def test_timeout(self):
        assert classify_failure("Request timed out after 120s") == FAILURE_CLASS_TIMEOUT

    @pytest.mark.parametrize("error", [
        "AttributeError: 'NoneType' object has no attribute 'text'",
        "ValueError: ungültiges JSON in der Antwort",
        "",
        None,
    ])
    def test_echter_agentenfehler(self, error):
        assert classify_failure(error) == FAILURE_CLASS_AGENT_ERROR

    def test_erschoepfung_schlaegt_timeout(self):
        """Enthält eine 429-Meldung zusätzlich das Wort 'timeout', bleibt die Erschöpfung der
        handlungsleitende Befund – sonst würde ein Kontingentproblem als Agentenfehler zählen."""
        assert classify_failure("429 quota exceeded, request timed out") == FAILURE_CLASS_PROVIDER_EXHAUSTED

    def test_nur_infrastruktur_klassen_gelten_als_infrastruktur(self):
        assert is_infrastructure_failure(FAILURE_CLASS_PROVIDER_EXHAUSTED)
        assert is_infrastructure_failure(FAILURE_CLASS_PROVIDER_UNAVAILABLE)
        assert not is_infrastructure_failure(FAILURE_CLASS_AGENT_ERROR)
        assert not is_infrastructure_failure(FAILURE_CLASS_TIMEOUT)
        assert not is_infrastructure_failure("")


class TestErfolgsquotenOhneInfrastruktur:
    """Der eigentliche Regressionsschutz: Infrastruktur-Ausfälle dürfen die Erfolgsquote eines
    Agenten nicht mehr drücken."""

    @staticmethod
    def _run(agent_results):
        return [{
            "timestamp": "2026-09-09T10:00:00+00:00",
            "project_slug": "demo",
            "task_summary": "t",
            "verification_ok": False,
            "total_tokens": 100,
            "duration_seconds": 1.0,
            "agent_results": agent_results,
        }]

    def test_kontingent_ausfall_zaehlt_nicht_als_fehlversuch(self):
        runs = self._run([
            {"agent_id": "backend", "success": True, "total_tokens": 50, "model_used": "gemini-3.1-flash-lite"},
            {"agent_id": "backend", "success": False, "total_tokens": 0, "model_used": "",
             "failure_class": FAILURE_CLASS_PROVIDER_EXHAUSTED},
            {"agent_id": "backend", "success": False, "total_tokens": 0, "model_used": "",
             "failure_class": FAILURE_CLASS_PROVIDER_UNAVAILABLE},
        ])
        with patch.object(run_history, "_load", return_value=runs):
            rates = {r["agent_id"]: r for r in run_history.get_agent_success_rates(10)}
        assert rates["backend"]["calls"] == 1
        assert rates["backend"]["success_rate"] == 100.0
        assert rates["backend"]["infrastructure_failures"] == 2

    def test_echter_fehler_zaehlt_weiterhin(self):
        runs = self._run([
            {"agent_id": "tester", "success": True, "total_tokens": 10, "model_used": "m"},
            {"agent_id": "tester", "success": False, "total_tokens": 10, "model_used": "m",
             "failure_class": FAILURE_CLASS_AGENT_ERROR},
        ])
        with patch.object(run_history, "_load", return_value=runs):
            rates = {r["agent_id"]: r for r in run_history.get_agent_success_rates(10)}
        assert rates["tester"]["calls"] == 2
        assert rates["tester"]["success_rate"] == 50.0
        assert rates["tester"]["infrastructure_failures"] == 0

    def test_agent_nur_mit_infrastruktur_ausfaellen_erscheint_nicht(self):
        """Sonst stünde er mit 0.0% als schlechtester Agent des Teams da, obwohl er nie lief."""
        runs = self._run([
            {"agent_id": "architect", "success": False, "total_tokens": 0, "model_used": "",
             "failure_class": FAILURE_CLASS_PROVIDER_EXHAUSTED},
        ])
        with patch.object(run_history, "_load", return_value=runs):
            rates = {r["agent_id"]: r for r in run_history.get_agent_success_rates(10)}
        assert "architect" not in rates

    def test_altbestand_ohne_failure_class_wird_ueber_fehlermeldung_klassifiziert(self):
        runs = self._run([
            {"agent_id": "security", "success": True, "total_tokens": 10, "model_used": "m"},
            {"agent_id": "security", "success": False, "total_tokens": 0, "model_used": "claude-sonnet-5",
             "error": "429 RESOURCE_EXHAUSTED"},
        ])
        with patch.object(run_history, "_load", return_value=runs):
            rates = {r["agent_id"]: r for r in run_history.get_agent_success_rates(10)}
        assert rates["security"]["calls"] == 1
        assert rates["security"]["infrastructure_failures"] == 1

    def test_modell_performance_ignoriert_nie_kontaktierte_modelle(self):
        """Kernbefund: `claude-sonnet-5` darf keine Fehlerstatistik erben, wenn nie ein Call lief."""
        runs = self._run([
            {"agent_id": "backend", "success": True, "total_tokens": 100, "model_used": "gemini-3.1-flash-lite"},
            {"agent_id": "backend", "success": False, "total_tokens": 0, "model_used": "",
             "failure_class": FAILURE_CLASS_PROVIDER_UNAVAILABLE},
        ])
        with patch.object(run_history, "_load", return_value=runs):
            perf = run_history.get_agent_model_performance(10)
        modelle = {r["model"] for r in perf}
        assert modelle == {"gemini-3.1-flash-lite"}
        assert "unbekannt" not in modelle
