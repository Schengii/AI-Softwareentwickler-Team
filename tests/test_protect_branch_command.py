"""
tests/test_protect_branch_command.py – Testet /protect-branch (interface/cli.py)

interface/cli.py._protect_branch_with_confirmation() zeigt eine Vorschau + Bestätigung
(analog zum Git-Push-Gate/Deploy-Gate, siehe tests/test_deploy_command.py) und ruft dann
agents/github_agent.py.set_branch_protection() auf – hier gemockt auf der realen
GitHubAgent-Instanz des Orchestrators, da die echte `gh`-CLI in der CI-Testumgebung nicht
garantiert installiert ist (die HTTP-Aufruf-Konstruktion selbst ist bereits vollständig in
tests/test_github_agent_issue_methods.py::TestSetBranchProtection abgedeckt).
"""

import asyncio
import unittest
from unittest.mock import MagicMock, patch

from interface.cli import CLIInterface


class TestProtectBranchCommand(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()
        self.github_agent = self.cli._orchestrator._agents["github"]
        self.github_agent.gh_ready = MagicMock(return_value=True)
        self.github_agent.set_branch_protection = MagicMock(return_value=(True, ""))

    @patch("interface.cli.console.print")
    def test_gh_not_ready_skips_confirmation_entirely(self, _mock_print):
        self.github_agent.gh_ready.return_value = False
        with patch("interface.cli.Confirm.ask") as mock_confirm:
            asyncio.run(self.cli._protect_branch_with_confirmation(None))
            mock_confirm.assert_not_called()
        self.github_agent.set_branch_protection.assert_not_called()

    @patch("interface.cli.Confirm.ask", return_value=False)
    @patch("interface.cli.console.print")
    def test_declining_confirmation_never_applies_protection(self, _mock_print, _mock_confirm):
        asyncio.run(self.cli._protect_branch_with_confirmation(None))
        self.github_agent.set_branch_protection.assert_not_called()

    @patch("interface.cli.Confirm.ask", return_value=True)
    @patch("interface.cli.console.print")
    def test_accepting_confirmation_applies_protection_to_default_branch(self, mock_print, _mock_confirm):
        asyncio.run(self.cli._protect_branch_with_confirmation(None))

        self.github_agent.set_branch_protection.assert_called_once()
        called_branch = self.github_agent.set_branch_protection.call_args.args[0]
        self.assertEqual(called_branch, "main")  # erster GIT_PROTECTED_BRANCHES-Eintrag
        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        self.assertIn("aktiviert", printed)

    @patch("interface.cli.Confirm.ask", return_value=True)
    @patch("interface.cli.console.print")
    def test_explicit_branch_argument_is_used(self, _mock_print, _mock_confirm):
        asyncio.run(self.cli._protect_branch_with_confirmation("develop"))
        called_branch = self.github_agent.set_branch_protection.call_args.args[0]
        self.assertEqual(called_branch, "develop")

    @patch("interface.cli.Confirm.ask", return_value=True)
    @patch("interface.cli.console.print")
    def test_reports_failure_without_crashing(self, mock_print, _mock_confirm):
        self.github_agent.set_branch_protection.return_value = (False, "HTTP 403: Must have admin rights")
        asyncio.run(self.cli._protect_branch_with_confirmation(None))

        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        self.assertIn("Fehlgeschlagen", printed)
        self.assertIn("admin rights", printed)


if __name__ == "__main__":
    unittest.main()
