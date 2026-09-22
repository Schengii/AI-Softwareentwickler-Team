"""
tests/test_token_budget_config.py - Team-Aufgabe "Token-Effizienz-/Budget-Flexibilisierung"
(2026-09-22), Punkt 1: deckt das flexible, komplexitäts-basierte Lauf-Budget ab.

- config.TASK_COMPLEXITY_TOKEN_BUDGETS/MIN_VERIFICATION_TOKEN_RESERVE existieren mit den
  erwarteten Defaults.
- Ein expliziter `--max-tokens`-Wert (main.py `--goal`, `/goal`-Befehl) überschreibt sowohl
  config.MAX_RUN_TOKENS als auch die automatische Komplexitäts-Stufe für JEDEN
  orchestrator.process()-Aufruf.
- Ohne Override wählt agents/orchestrator/department.py die zur erkannten Aufgaben-Komplexität
  passende Stufe (micro/standard/complex) - siehe agents/orchestrator/budget.py.
- Die Mindest-Verifikationsreserve (MIN_VERIFICATION_TOKEN_RESERVE) greift auch bei einem
  kleinen Lauf-Budget, für das der reine Anteils-Prozentsatz (VERIFICATION_TOKEN_RESERVE_RATIO)
  nicht ausreichen würde.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import config
from agents.orchestrator import Orchestrator
from agents.orchestrator.budget import BudgetMixin, max_run_tokens_scope
from core.goal_loop import GoalLoopRunner


class TestComplexityBudgetConfig(unittest.TestCase):
    def test_complexity_tiers_exist_with_expected_defaults(self):
        # Werte lesen die jeweilige Umgebungsvariable (MICRO_TASK_TOKEN_BUDGET/...) - hier wird
        # nur die aufsteigende Größenordnung geprüft, nicht ein env-abhängiger Fixwert, da eine
        # lokale .env (z.B. MAX_RUN_TOKENS) diese Fallbacks überschreiben darf.
        self.assertLess(config.TASK_COMPLEXITY_TOKEN_BUDGETS["micro"], config.TASK_COMPLEXITY_TOKEN_BUDGETS["standard"])
        self.assertLess(config.TASK_COMPLEXITY_TOKEN_BUDGETS["standard"], config.TASK_COMPLEXITY_TOKEN_BUDGETS["complex"])
        self.assertGreater(config.TASK_COMPLEXITY_TOKEN_BUDGETS["micro"], 0)

    def test_min_verification_reserve_has_a_sane_default(self):
        self.assertEqual(config.MIN_VERIFICATION_TOKEN_RESERVE, 200_000)


class TestMaxRunTokensScope(unittest.TestCase):
    """max_run_tokens_scope() (agents/orchestrator/budget.py) ist der Mechanismus, über den
    sowohl der `--max-tokens`-Override als auch die automatische Komplexitäts-Stufe das Budget
    für die Dauer eines Laufs setzen, OHNE das Modul-Attribut MAX_RUN_TOKENS dauerhaft zu
    verändern - bestehende Tests, die MAX_RUN_TOKENS direkt patchen, dürfen dadurch nicht
    beeinflusst werden."""

    def test_scope_overrides_and_resets(self):
        self.assertFalse(BudgetMixin._run_budget_exceeded(0))
        with max_run_tokens_scope(1000):
            with patch("core.token_guard.token_guard.get_summary", return_value={"grand_total_tokens": 2000}):
                self.assertTrue(BudgetMixin._run_budget_exceeded(0))
        # Nach Verlassen des Scopes gilt wieder das reguläre (Standard: deaktivierte oder
        # sehr viel größere) Budget - derselbe Verbrauch überschreitet es nicht mehr.
        with patch("core.token_guard.token_guard.get_summary", return_value={"grand_total_tokens": 2000}):
            self.assertFalse(BudgetMixin._run_budget_exceeded(0))

    def test_module_level_max_run_tokens_patch_still_works_without_scope(self):
        """Regressionsschutz: tests/test_run_budget_cap.py patcht MAX_RUN_TOKENS direkt auf dem
        Budget-Modul - das muss weiterhin greifen, wenn KEIN expliziter Scope aktiv ist."""
        import agents.orchestrator.budget as budget_module

        with patch.object(budget_module, "MAX_RUN_TOKENS", 1000):
            with patch("core.token_guard.token_guard.get_summary", return_value={"grand_total_tokens": 2000}):
                self.assertTrue(BudgetMixin._run_budget_exceeded(0))


class TestExplicitMaxTokensOverride(unittest.TestCase):
    """process(max_tokens_override=...) - main.py `--goal ... --max-tokens N` und der
    `/goal`-Befehl reichen diesen Wert genau hierhin durch (core/goal_loop.py)."""

    def test_process_sets_overridden_flag_and_scope_for_positive_value(self):
        orchestrator = Orchestrator()
        orchestrator._process_impl = AsyncMock(return_value="### ok")
        asyncio.run(orchestrator.process(user_request="Baue etwas", max_tokens_override=777_000))
        self.assertTrue(orchestrator._max_run_tokens_overridden)

    def test_process_leaves_flag_false_without_override(self):
        orchestrator = Orchestrator()
        orchestrator._process_impl = AsyncMock(return_value="### ok")
        asyncio.run(orchestrator.process(user_request="Baue etwas"))
        self.assertFalse(orchestrator._max_run_tokens_overridden)

    def test_override_is_visible_as_effective_budget_inside_process_impl(self):
        orchestrator = Orchestrator()
        seen: dict = {}

        async def _fake_impl(*args, **kwargs):
            import agents.orchestrator.budget as budget_module
            seen["effective"] = budget_module._effective_max_run_tokens()
            return "### ok"

        orchestrator._process_impl = _fake_impl
        asyncio.run(orchestrator.process(user_request="Baue etwas", max_tokens_override=999_000))
        self.assertEqual(seen["effective"], 999_000)

    def test_zero_or_none_override_does_not_activate_scope(self):
        orchestrator = Orchestrator()
        seen: dict = {}

        async def _fake_impl(*args, **kwargs):
            import agents.orchestrator.budget as budget_module
            seen["effective"] = budget_module._effective_max_run_tokens()
            return "### ok"

        orchestrator._process_impl = _fake_impl
        asyncio.run(orchestrator.process(user_request="Baue etwas", max_tokens_override=0))
        self.assertEqual(seen["effective"], config.MAX_RUN_TOKENS)
        self.assertFalse(orchestrator._max_run_tokens_overridden)


class TestGoalLoopPassesOverrideThrough(unittest.IsolatedAsyncioTestCase):
    """core/goal_loop.py - main.py `--goal` und der `/goal`-Befehl rufen GoalLoopRunner.run()
    auf; der Override muss an JEDE Iteration von orchestrator.process() durchgereicht werden."""

    async def test_run_forwards_max_tokens_override_to_orchestrator_process(self):
        mock_orchestrator = AsyncMock()
        mock_orchestrator.process = AsyncMock(return_value="Fertig, alle Tests grün.")
        mock_orchestrator.get_workspace_manager = MagicMock()
        runner = GoalLoopRunner(orchestrator=mock_orchestrator)

        with patch("core.goal_loop.read_status", return_value=[]), \
             patch.object(GoalLoopRunner, "_evaluate_and_synthesize_next_step", new=AsyncMock(
                 return_value={"goal_reached": True, "reason": "ok", "next_prompt": ""}
             )):
            await runner.run(
                goal="Baue etwas Kleines",
                project_dir="workspace/irgendein_projekt",
                max_iterations=1,
                max_tokens_override=1_234_000,
            )

        mock_orchestrator.process.assert_awaited_once()
        self.assertEqual(
            mock_orchestrator.process.call_args.kwargs.get("max_tokens_override"), 1_234_000,
        )


if __name__ == "__main__":
    unittest.main()
