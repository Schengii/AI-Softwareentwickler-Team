"""
tests/test_capacity_gate.py – Testet core/capacity_gate.py.

Realer Fund (auditlog_sentinel, 2026-09-10): Ein Lauf startete, obwohl Gemini bereits bei 548 %
des geschätzten Tageskontingents lag, Groq im Rate-Limit war, DeepSeek "Insufficient Balance"
meldete, OpenRouter "requires more credits" und kein Anthropic-Key konfiguriert war - 13 Minuten
und 374k Tokens später brach der Lauf als budget_aborted ab, mit einer kaputten app/config.py
als einzigem Ergebnis. assess_run_capacity() soll das VOR dem ersten Agenten-Aufruf erkennen.
"""

import unittest
from unittest.mock import patch

from core.capacity_gate import assess_run_capacity, role_capacity


class TestRoleCapacity(unittest.TestCase):
    def test_non_critical_role_has_no_floor(self):
        cap = role_capacity("documentation")
        self.assertEqual(cap.min_tier, 0)

    def test_critical_role_with_available_provider_has_usable_models(self):
        with patch("config.get_model_for_agent", return_value="groq:openai/gpt-oss-120b"), \
             patch("core.llm_factory._provider_available", return_value=True), \
             patch("core.token_guard.token_guard.is_model_exhausted", return_value=False):
            cap = role_capacity("security")
        self.assertTrue(cap.usable_models)

    def test_critical_role_with_no_provider_available_has_no_usable_models(self):
        with patch("config.get_model_for_agent", return_value="groq:openai/gpt-oss-120b"), \
             patch("core.llm_factory._provider_available", return_value=False):
            cap = role_capacity("security")
        self.assertEqual(cap.usable_models, [])


class TestAssessRunCapacity(unittest.TestCase):
    def test_empty_agent_list_is_never_blocked(self):
        assessment = assess_run_capacity([])
        self.assertFalse(assessment.blocked)

    def test_non_critical_agents_only_are_never_blocked(self):
        assessment = assess_run_capacity(["documentation", "readme"])
        self.assertFalse(assessment.blocked)

    def test_blocked_when_no_provider_available_for_critical_role(self):
        with patch("core.llm_factory._provider_available", return_value=False):
            assessment = assess_run_capacity(["security", "backend"])
        self.assertTrue(assessment.blocked)
        blocked_ids = {r.agent_id for r in assessment.blocked_roles}
        self.assertIn("security", blocked_ids)
        self.assertIn("backend", blocked_ids)

    def test_block_message_names_blocked_roles(self):
        with patch("core.llm_factory._provider_available", return_value=False):
            assessment = assess_run_capacity(["security"])
        message = assessment.format_block_message()
        self.assertIn("security", message)
        self.assertIn("nicht gestartet", message)

    def test_not_blocked_when_at_least_one_provider_available(self):
        with patch("core.llm_factory._provider_available", return_value=True), \
             patch("core.token_guard.token_guard.is_model_exhausted", return_value=False):
            assessment = assess_run_capacity(["security"])
        self.assertFalse(assessment.blocked)

    def test_warns_when_every_reachable_provider_is_overused(self):
        # Alle Provider in der Fallback-Kette (auch die unabhängigen Ausweichziele Groq/DeepSeek/
        # OpenRouter), fuer die ueberhaupt ein Key konfiguriert ist, muessen ueberzogen sein,
        # damit die Warnung greift - sonst koennte die Kette noch auf einen frischen Anbieter
        # ausweichen und die Warnung waere irrefuehrend. Claude ohne ANTHROPIC_API_KEY (der reale
        # Standardfall) faellt bereits ueber _provider_available heraus, nicht ueber die Quote.
        overused = {"gemini": 3.0, "groq": 2.0, "deepseek": 2.0, "openrouter": 2.0}

        def _available(model_name: str) -> bool:
            return "claude" not in model_name.lower()

        with patch("core.capacity_gate._overused_providers", return_value=overused), \
             patch("config.get_model_for_agent", return_value="gemini-3.8-flash"), \
             patch("core.llm_factory._provider_available", side_effect=_available), \
             patch("core.token_guard.token_guard.is_model_exhausted", return_value=False):
            assessment = assess_run_capacity(["security"])
        self.assertFalse(assessment.blocked)
        self.assertTrue(assessment.warnings)

    def test_broken_cost_history_never_blocks(self):
        with patch("core.capacity_gate._overused_providers", side_effect=RuntimeError("boom")), \
             patch("core.llm_factory._provider_available", return_value=True), \
             patch("core.token_guard.token_guard.is_model_exhausted", return_value=False):
            assessment = assess_run_capacity(["security"])
        self.assertFalse(assessment.blocked)
        self.assertEqual(assessment.warnings, [])


class TestMostlyDowngradedWarning(unittest.TestCase):
    """P5-1 Punkt 3 (ROADMAP_TEMP.md): Warnung, wenn >= 50% der eingeplanten Rollen (nicht nur
    die kritischen) mit einem herabgestuften Modell starten müssten."""

    def test_warns_over_all_planned_roles_not_only_critical(self):
        # "documentation" ist NICHT kritisch, zählt aber für den Anteil mit.
        with patch("core.llm_factory._provider_available", return_value=False):
            assessment = assess_run_capacity(["documentation", "readme"])
        self.assertTrue(assessment.mostly_downgraded)
        self.assertEqual(set(assessment.downgraded_agent_ids), {"documentation", "readme"})
        self.assertTrue(any("herabgestuft" in w for w in assessment.warnings))

    def test_no_warning_below_threshold(self):
        def _available(model_name: str) -> bool:
            return True

        with patch("core.llm_factory._provider_available", side_effect=_available), \
             patch("core.token_guard.token_guard.is_model_exhausted", return_value=False):
            assessment = assess_run_capacity(["documentation", "readme"])
        self.assertFalse(assessment.mostly_downgraded)
        self.assertEqual(assessment.downgraded_agent_ids, [])

    def test_empty_plan_is_never_mostly_downgraded(self):
        assessment = assess_run_capacity([])
        self.assertFalse(assessment.mostly_downgraded)
        self.assertEqual(assessment.downgraded_ratio, 0.0)


if __name__ == "__main__":
    unittest.main()
