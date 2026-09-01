"""
tests/test_deploy_cloud_command.py – Testet /deploy-cloud (interface/cli.py)

Realer Fund: core/cloud_deployment.py.CloudDeploymentManager existierte bereits vollständig
fertig implementiert (Manifest-Generierung + echter flyctl/vercel-Deploy), war aber nirgends
im CLI/Dashboard verdrahtet - README behauptete "CLI & Dashboard können per echtem Deploy-
Befehl eine Preview-URL bereitstellen", was schlicht nicht stimmte. Dasselbe Testmuster wie
tests/test_deploy_command.py (lokales Docker-Deployment) - CloudDeploymentManager wird hier
gemockt, core/cloud_deployment.py selbst ist bereits in tests/test_cloud_deployment.py gegen
mockierte Subprozesse getestet.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.cloud_deployment import CloudDeploymentResult
from interface.cli import CLIInterface


class TestDeployCloudCommand(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()
        self.temp_workspace = tempfile.mkdtemp()
        self.cli._workspace.base_dir = Path(self.temp_workspace)
        (self.cli._workspace.base_dir / "demo_project").mkdir()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    @patch("interface.cli.console.print")
    def test_missing_provider_shows_usage_hint_without_crashing(self, _mock_print):
        with patch("interface.cli.Confirm.ask") as mock_confirm:
            asyncio.run(self.cli._deploy_cloud_with_confirmation([]))
            mock_confirm.assert_not_called()

    @patch("interface.cli.console.print")
    def test_unknown_provider_is_rejected(self, _mock_print):
        with patch("interface.cli.Confirm.ask") as mock_confirm:
            asyncio.run(self.cli._deploy_cloud_with_confirmation(["heroku", "demo_project"]))
            mock_confirm.assert_not_called()

    @patch("interface.cli.console.print")
    def test_nonexistent_project_skips_confirmation_entirely(self, _mock_print):
        with patch("interface.cli.Confirm.ask") as mock_confirm:
            asyncio.run(self.cli._deploy_cloud_with_confirmation(["fly", "does_not_exist"]))
            mock_confirm.assert_not_called()

    @patch("interface.cli.Confirm.ask", return_value=False)
    @patch("interface.cli.console.print")
    def test_declining_confirmation_never_deploys(self, _mock_print, _mock_confirm):
        with patch("core.cloud_deployment.CloudDeploymentManager") as mock_cls:
            asyncio.run(self.cli._deploy_cloud_with_confirmation(["fly", "demo_project"]))
            mock_cls.return_value.deploy.assert_not_called()

    @patch("interface.cli.Confirm.ask", return_value=True)
    @patch("interface.cli.console.print")
    def test_default_mode_without_real_flag_runs_as_dry_run(self, _mock_print, _mock_confirm):
        with patch("core.cloud_deployment.CloudDeploymentManager") as mock_cls:
            mock_cls.return_value.deploy.return_value = CloudDeploymentResult(
                attempted=True, success=True, provider="fly", preview_url="https://demo.fly.dev",
            )
            asyncio.run(self.cli._deploy_cloud_with_confirmation(["fly", "demo_project"]))

            mock_cls.return_value.deploy.assert_called_once_with("fly", True)  # dry_run=True per Standard

    @patch("interface.cli.Confirm.ask", return_value=True)
    @patch("interface.cli.console.print")
    def test_real_flag_passes_dry_run_false(self, _mock_print, _mock_confirm):
        with patch("core.cloud_deployment.CloudDeploymentManager") as mock_cls:
            mock_cls.return_value.deploy.return_value = CloudDeploymentResult(
                attempted=True, success=True, provider="fly", preview_url="https://demo.fly.dev",
            )
            asyncio.run(self.cli._deploy_cloud_with_confirmation(["fly", "demo_project", "--real"]))

            mock_cls.return_value.deploy.assert_called_once_with("fly", False)

    @patch("interface.cli.Confirm.ask", return_value=True)
    @patch("interface.cli.console.print")
    def test_successful_real_deploy_records_deployment_status(self, mock_print, _mock_confirm):
        with patch("core.cloud_deployment.CloudDeploymentManager") as mock_cls, \
             patch("core.deployment_status.record_deployment") as mock_record:
            mock_cls.return_value.deploy.return_value = CloudDeploymentResult(
                attempted=True, success=True, provider="fly", preview_url="https://demo.fly.dev",
            )
            asyncio.run(self.cli._deploy_cloud_with_confirmation(["fly", "demo_project", "--real"]))

            mock_record.assert_called_once()
            self.assertEqual(mock_record.call_args.kwargs["url"], "https://demo.fly.dev")
            printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
            self.assertIn("https://demo.fly.dev", printed)

    @patch("interface.cli.Confirm.ask", return_value=True)
    @patch("interface.cli.console.print")
    def test_dry_run_success_does_not_record_deployment_status(self, _mock_print, _mock_confirm):
        # Realer Fund: eine per Dry-Run nur GERATENE URL wurde nie wirklich deployt - würde sie
        # trotzdem überwacht (core/production_monitor.py), entstünden falsche "nicht
        # erreichbar"-Alarme für etwas, das nie live war.
        with patch("core.cloud_deployment.CloudDeploymentManager") as mock_cls, \
             patch("core.deployment_status.record_deployment") as mock_record:
            mock_cls.return_value.deploy.return_value = CloudDeploymentResult(
                attempted=True, success=True, provider="fly", preview_url="https://demo.fly.dev",
            )
            asyncio.run(self.cli._deploy_cloud_with_confirmation(["fly", "demo_project"]))

            mock_record.assert_not_called()

    @patch("interface.cli.Confirm.ask", return_value=True)
    @patch("interface.cli.console.print")
    def test_reports_skip_reason_without_crashing(self, mock_print, _mock_confirm):
        with patch("core.cloud_deployment.CloudDeploymentManager") as mock_cls:
            mock_cls.return_value.deploy.return_value = CloudDeploymentResult(
                attempted=False, provider="render", reason_skipped="render bietet kein lokales CLI-Deploy-Kommando.",
            )
            asyncio.run(self.cli._deploy_cloud_with_confirmation(["render", "demo_project", "--real"]))

            printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
            self.assertIn("kein lokales CLI-Deploy-Kommando", printed)


if __name__ == "__main__":
    unittest.main()
