"""
tests/test_cli_optimize_command.py – Testet /optimize in interface/cli.py

Nutzerwunsch: die datenbasierten Selbstoptimierungs-Vorschläge (core/optimization_advisor.py)
sollen jederzeit ohne einen neuen Lauf abrufbar sein, nicht nur automatisch am Ende jedes
Laufs sichtbar werden.
"""

import asyncio
import unittest
from unittest.mock import patch

from core.optimization_advisor import LowPerformingAgent, OptimizationReport
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


if __name__ == "__main__":
    unittest.main()
