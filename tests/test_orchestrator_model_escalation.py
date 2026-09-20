"""
tests/test_orchestrator_model_escalation.py – Testet Orchestrator(escalate_models=True)

Team-Optimierung (Retrospektive 2026-09-04): fast jedes zuletzt bearbeitete Projekt
(sentinelproxy, taskpulse, webhook_shield, mockforge, zeiterfassung_app) blieb nach den
standardmäßigen Fixversuchen rot, und core/backlog_worker.py griff einen dadurch entstandenen
Governance-/Verifikations-Retry-Ticket beim zweiten automatischen Versuch mit EXAKT demselben
Agenten/Modell erneut auf - ohne jede Eskalation. `escalate_models=True` stuft jeden Fachagenten,
der nicht ohnehin bereits auf HEAVY_MODEL läuft, für diesen Lauf hoch.
"""

import unittest
from unittest.mock import patch

import config
from agents.orchestrator import Orchestrator
from core.capacity_gate import model_is_reachable, model_unreachable_reason
from core.llm_factory import LLMFactory, is_same_model


class TestOrchestratorModelEscalation(unittest.TestCase):
    def test_default_does_not_escalate(self):
        orchestrator = Orchestrator()
        # Mindestens ein regulär auf STANDARD_MODEL/LITE_MODEL laufender Agent muss OHNE
        # escalate_models unverändert bleiben.
        self.assertFalse(
            is_same_model(orchestrator._agents["frontend"]._llm.model_name, config.HEAVY_MODEL)
        )

    def test_escalate_models_upgrades_non_heavy_agents(self):
        orchestrator = Orchestrator(escalate_models=True)
        for agent_id, agent in orchestrator._agents.items():
            # Kanonischer Vergleich: Groq-/OpenRouter-/DeepSeek-Clients entfernen das
            # Provider-Praefix beim Anlegen ("groq:openai/gpt-oss-120b" ->
            # "openai/gpt-oss-120b"). Ein direkter Vergleich schlaegt deshalb fehl, sobald
            # HEAVY_MODEL ein praefixbehaftetes Modell ist.
            self.assertTrue(
                is_same_model(agent._llm.model_name, config.HEAVY_MODEL),
                f"Agent '{agent_id}' wurde nicht auf HEAVY_MODEL hochgestuft "
                f"(ist: {agent._llm.model_name!r}, erwartet: {config.HEAVY_MODEL!r}).",
            )

    def test_escalate_models_leaves_already_heavy_agents_unchanged(self):
        # security/code_reviewer/refactoring/agent_trainer laufen bereits standardmäßig auf
        # HEAVY_MODEL (config.AGENT_MODELS) - _escalate_agent_models() darf sie nicht anfassen
        # (kein unnötiger Client-Neubau).
        #
        # Realer Fund (Team-Optimierung, 20260913): ein lokaler `.env`-Override wie
        # `SECURITY_MODEL=gemini-pro-latest` (bewusste Pro-Modell-Wahl für qualitätskritische
        # Rollen) lässt `security` schon VOR jeder Eskalation von HEAVY_MODEL abweichen - der
        # Test prüft dann faktisch das Verhalten bei EINEM abweichenden statt bereits-heavy
        # Agenten und schlägt in genau dieser lokalen Konfiguration fehl. Der Client wird
        # deshalb hier deterministisch auf HEAVY_MODEL gesetzt, statt sich auf die per `.env`
        # veränderliche AGENT_MODELS-Zuordnung zu verlassen - der eigentliche Prüfgegenstand
        # (kein unnötiger Client-Neubau für einen bereits korrekten Agenten) bleibt unverändert.
        orchestrator = Orchestrator()
        orchestrator._agents["security"]._llm = LLMFactory.create_for_model(config.HEAVY_MODEL)
        already_heavy = orchestrator._agents["security"]._llm
        orchestrator._escalate_agent_models()
        self.assertIs(orchestrator._agents["security"]._llm, already_heavy)


class TestEscalationSkippedWhenTierUnreachable(unittest.TestCase):
    """Roadmap P5-1 (2026-09-20): die Fix-Schleife verbrennt als letzten Rettungsanker einen
    kompletten Agenten-Aufruf mit HEAVY_MODEL. Lag dessen Kontingent auf Cooldown, fiel der
    Aufruf intern auf ein SCHWÄCHERES Modell zurück als das, mit dem der Fix zuvor schon
    zweimal gescheitert war - der Versuch konnte nichts Neues bringen und kostete trotzdem
    Zeit und Budget. Im Protokoll von `eventforge_core` (20260919_003629) steht das wörtlich:
    "HEAVY_MODEL-Eskalation für tester griff nicht tatsächlich (Kontingent-Erschöpfung o.ä.)".
    `LLMFactory.create_for_model()` allein merkt davon nichts - es liefert auch für ein
    erschöpftes Modell erfolgreich ein Client-Objekt."""

    def test_no_agent_is_escalated_while_heavy_tier_is_exhausted(self):
        orchestrator = Orchestrator()
        before = orchestrator._agents["frontend"]._llm
        with patch(
            "core.capacity_gate.model_unreachable_reason",
            return_value="Kontingent für 'gemini-pro-latest' erschöpft",
        ):
            escalated = orchestrator._escalate_agent_models({"frontend", "tester"})
        self.assertEqual(escalated, set())
        # Kein Client-Neubau: der Agent bleibt exakt auf seinem bisherigen Modell.
        self.assertIs(orchestrator._agents["frontend"]._llm, before)

    def test_blocked_reason_is_exposed_for_the_protocol_and_the_ticket(self):
        """Der Grund muss der Fix-Schleife zur Verfügung stehen - ohne ihn liest sich das
        Ergebnis wie ein Agenten-/Prompt-Problem statt als Infrastruktur-Befund."""
        orchestrator = Orchestrator()
        with patch(
            "core.capacity_gate.model_unreachable_reason",
            return_value="kein API-Key/Anbieter für 'gemini-pro-latest' konfiguriert",
        ):
            orchestrator._escalate_agent_models({"tester"})
        self.assertIn("kein API-Key", orchestrator.last_model_escalation_blocked_reason)

    def test_reachable_tier_still_escalates_and_clears_the_reason(self):
        """Gegenprobe: bei erreichbarer Stufe bleibt die Eskalation unverändert erhalten."""
        orchestrator = Orchestrator()
        with patch("core.capacity_gate.model_unreachable_reason", return_value=None):
            escalated = orchestrator._escalate_agent_models({"frontend"})
        self.assertEqual(escalated, {"frontend"})
        self.assertIsNone(orchestrator.last_model_escalation_blocked_reason)
        self.assertTrue(
            is_same_model(orchestrator._agents["frontend"]._llm.model_name, config.HEAVY_MODEL)
        )


class TestModelReachability(unittest.TestCase):
    """core/capacity_gate.py.model_unreachable_reason() - beantwortet VOR einem Aufruf, ob eine
    Modellstufe überhaupt erreichbar ist, statt es hinterher am `model_used` abzulesen."""

    def test_exhausted_model_reports_its_reason(self):
        with patch("core.token_guard.token_guard.is_model_exhausted", return_value=True), \
             patch("core.token_guard.token_guard.get_exhausted_reason", return_value="429 Quota Exceeded"), \
             patch("core.llm_factory._provider_available", return_value=True):
            self.assertEqual(model_unreachable_reason("gemini-pro-latest"), "429 Quota Exceeded")
            self.assertFalse(model_is_reachable("gemini-pro-latest"))

    def test_missing_provider_is_reported_before_the_quota_check(self):
        with patch("core.llm_factory._provider_available", return_value=False):
            reason = model_unreachable_reason("claude-opus-5")
        self.assertIn("kein API-Key", reason)

    def test_empty_model_is_unreachable(self):
        self.assertEqual(model_unreachable_reason(""), "kein Modell konfiguriert")

    def test_available_model_has_no_reason(self):
        with patch("core.token_guard.token_guard.is_model_exhausted", return_value=False), \
             patch("core.llm_factory._provider_available", return_value=True):
            self.assertIsNone(model_unreachable_reason("gemini-3.8-flash"))
            self.assertTrue(model_is_reachable("gemini-3.8-flash"))


if __name__ == "__main__":
    unittest.main()
