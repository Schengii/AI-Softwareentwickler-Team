"""
tests/test_deploy_command.py – Testet /deploy und /deploy-stop (interface/cli.py)

interface/cli.py._deploy_project_with_confirmation() zeigt eine Vorschau + Bestätigung
(analog zum Git-Push-Gate, siehe tests/test_cli_push_gate.py) und ruft dann echte
core/deployment.py-Funktionen auf – hier gemockt, da echtes Docker in der CI-Testumgebung
nicht garantiert verfügbar ist (core/deployment.py selbst ist in tests/test_deployment.py
gegen mockierte Docker-Kommandos getestet).
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.deployment import DeploymentResult
from interface.cli import CLIInterface


class TestDeployCommand(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()
        self.temp_workspace = tempfile.mkdtemp()
        self.cli._workspace.base_dir = Path(self.temp_workspace)
        (self.cli._workspace.base_dir / "demo_project").mkdir()
        (self.cli._workspace.base_dir / "demo_project" / "Dockerfile").write_text("FROM python:3.12\n")

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    @patch("interface.cli.console.print")
    def test_nonexistent_project_skips_confirmation_entirely(self, _mock_print):
        with patch("interface.cli.Confirm.ask") as mock_confirm, \
             patch("core.deployment.deploy_project") as mock_deploy:
            asyncio.run(self.cli._deploy_project_with_confirmation("does_not_exist"))
            mock_confirm.assert_not_called()
            mock_deploy.assert_not_called()

    @patch("interface.cli.console.print")
    def test_no_project_given_and_none_loaded_skips_confirmation(self, _mock_print):
        self.cli._loaded_project_dir = None
        with patch("interface.cli.Confirm.ask") as mock_confirm, \
             patch("core.deployment.deploy_project") as mock_deploy:
            asyncio.run(self.cli._deploy_project_with_confirmation(None))
            mock_confirm.assert_not_called()
            mock_deploy.assert_not_called()

    @patch("core.deployment.deploy_project")
    @patch("interface.cli.Confirm.ask", return_value=False)
    @patch("interface.cli.console.print")
    def test_declining_confirmation_never_deploys(self, _mock_print, _mock_confirm, mock_deploy):
        asyncio.run(self.cli._deploy_project_with_confirmation("demo_project"))
        mock_deploy.assert_not_called()

    @patch("core.production_monitor._check_url", return_value=(True, "HTTP 200"))
    @patch("core.deployment.deploy_project")
    @patch("interface.cli.Confirm.ask", return_value=True)
    @patch("interface.cli.console.print")
    def test_accepting_confirmation_deploys_and_reports_success(self, mock_print, _mock_confirm, mock_deploy, _mock_check_url):
        # core.production_monitor._check_url() gemockt statt des sofortigen Post-Deploy-
        # Health-Checks selbst (interface/cli.py._run_post_deploy_health_check(), KI-Team-
        # Analyse 07.09.2026, Punkt 8) - ohne diesen Mock würde real (mehrfach wiederholt)
        # gegen die nie wirklich laufende URL http://localhost:8000 verbunden.
        mock_deploy.return_value = DeploymentResult(
            attempted=True, success=True, method="docker", urls=["http://localhost:8000"],
        )
        asyncio.run(self.cli._deploy_project_with_confirmation("demo_project"))

        mock_deploy.assert_called_once()
        called_dir = mock_deploy.call_args.args[0]
        self.assertEqual(Path(called_dir).name, "demo_project")
        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        self.assertIn("http://localhost:8000", printed)

    @patch("core.deployment.deploy_project")
    @patch("interface.cli.Confirm.ask", return_value=True)
    @patch("interface.cli.console.print")
    def test_reports_failure_without_crashing(self, mock_print, _mock_confirm, mock_deploy):
        mock_deploy.return_value = DeploymentResult(attempted=True, success=False, method="docker", output="build failed: xyz")
        asyncio.run(self.cli._deploy_project_with_confirmation("demo_project"))

        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        self.assertIn("fehlgeschlagen", printed)
        self.assertIn("build failed: xyz", printed)

    @patch("core.deployment.deploy_project")
    @patch("interface.cli.Confirm.ask", return_value=True)
    @patch("interface.cli.console.print")
    def test_uses_loaded_project_when_no_name_given(self, _mock_print, _mock_confirm, mock_deploy):
        mock_deploy.return_value = DeploymentResult(attempted=True, success=True, method="compose", urls=[])
        self.cli._loaded_project_dir = str(self.cli._workspace.base_dir / "demo_project")

        asyncio.run(self.cli._deploy_project_with_confirmation(None))

        mock_deploy.assert_called_once()
        called_dir = mock_deploy.call_args.args[0]
        self.assertEqual(Path(called_dir).name, "demo_project")


class TestDeployStopCommand(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()
        self.temp_workspace = tempfile.mkdtemp()
        self.cli._workspace.base_dir = Path(self.temp_workspace)
        (self.cli._workspace.base_dir / "demo_project").mkdir()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    @patch("core.deployment.stop_deployment")
    @patch("interface.cli.console.print")
    def test_stops_without_needing_confirmation(self, mock_print, mock_stop):
        mock_stop.return_value = DeploymentResult(attempted=True, success=True, method="docker")
        asyncio.run(self.cli._stop_deployment("demo_project"))

        mock_stop.assert_called_once()
        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        self.assertIn("gestoppt", printed)

    @patch("interface.cli.console.print")
    def test_nonexistent_project_is_reported_without_crashing(self, _mock_print):
        with patch("core.deployment.stop_deployment") as mock_stop:
            asyncio.run(self.cli._stop_deployment("does_not_exist"))
            mock_stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
