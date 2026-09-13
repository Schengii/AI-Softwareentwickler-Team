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

import config
from agents.orchestrator import Orchestrator
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


if __name__ == "__main__":
    unittest.main()
