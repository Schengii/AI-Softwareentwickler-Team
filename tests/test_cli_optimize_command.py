"""
tests/test_cli_optimize_command.py – Testet /optimize in interface/cli.py

Nutzerwunsch: die datenbasierten Selbstoptimierungs-Vorschläge (core/optimization_advisor.py)
sollen jederzeit ohne einen neuen Lauf abrufbar sein, nicht nur automatisch am Ende jedes
Laufs sichtbar werden.
"""

import asyncio
import unittest
from unittest.mock import patch

from core.optimization_advisor import LowPerformingAgent, ModelSuggestion, OptimizationReport
from interface.cli import CLIInterface


class TestOptimizeCommand(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()

    def _handle(self, command: str):
        with patch("interface.cli.console.print") as mock_print:
            asyncio.run(self.cli._handle_command(command))
        return mock_print

    @patch("core.optimization_advisor.analyze", return_value=OptimizationReport())
    def test_empty_report_shows_hint_not_crash(self, mock_analyze):
        mock_print = self._handle("/optimize")
        mock_print.assert_called_once()
        printed = str(mock_print.call_args[0][0])
        self.assertIn("keine auffälligen", printed)

    @patch(
        "core.optimization_advisor.analyze",
        return_value=OptimizationReport(low_performing_agents=[
            LowPerformingAgent(agent_id="backend", success_rate=20.0, calls=5, team_average=85.0),
        ]),
    )
    def test_non_empty_report_is_printed(self, mock_analyze):
        mock_print = self._handle("/optimize")
        mock_print.assert_called_once()


class TestApplyTuningCommand(unittest.TestCase):
    """
    Testet Punkt 4 der Team-Retrospektive (2026-09-06): `/apply-tuning <agent_id>` übernimmt
    GEZIELT genau einen der bei `/optimize` angezeigten Modell-Vorschläge - der manuelle
    Mittelweg zwischen "Vorschlag ignorieren" und dem globalen ENABLE_AUTO_MODEL_TUNING-Schalter.
    """

    def setUp(self):
        self.cli = CLIInterface()

    def _handle(self, command: str):
        with patch("interface.cli.console.print") as mock_print:
            asyncio.run(self.cli._handle_command(command))
        return mock_print

    def test_missing_agent_id_shows_usage_hint(self):
        mock_print = self._handle("/apply-tuning")
        printed = str(mock_print.call_args[0][0])
        self.assertIn("agent_id", printed)

    @patch("core.optimization_advisor.analyze", return_value=OptimizationReport())
    def test_unknown_agent_shows_hint_not_crash(self, mock_analyze):
        mock_print = self._handle("/apply-tuning does-not-exist")
        printed = str(mock_print.call_args[0][0])
        self.assertIn("Kein Modell-Vorschlag", printed)

    @patch("core.optimization_advisor.apply_single_suggestion")
    @patch("core.optimization_advisor.analyze")
    def test_valid_agent_applies_and_confirms(self, mock_analyze, mock_apply):
        suggestion = ModelSuggestion(
            agent_id="backend", current_model="model-a", current_success_rate=20.0,
            current_calls=5, current_avg_tokens=100.0, suggested_model="model-b",
            suggested_success_rate=80.0, suggested_calls=5, suggested_avg_tokens=100.0,
        )
        mock_analyze.return_value = OptimizationReport(model_suggestions=[suggestion])
        mock_apply.return_value = suggestion

        mock_print = self._handle("/apply-tuning backend")

        mock_apply.assert_called_once()
        printed = str(mock_print.call_args[0][0])
        self.assertIn("backend", printed)
        self.assertIn("model-b", printed)


if __name__ == "__main__":
    unittest.main()
