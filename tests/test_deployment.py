"""
tests/test_deployment.py – Testet core/deployment.py (echtes lokales Docker-Deployment)

`docker`/`docker compose` sind in der CI-Testumgebung nicht garantiert installiert -
CodeSandbox.run_command() und shutil.which() werden deshalb gemockt (dasselbe Prinzip wie
core/verifier.py.check_docker_build() in tests/test_verifier.py). Gegenstand ist die
Entscheidungslogik (Compose vs. Dockerfile vs. nichts gefunden) und die tatsächlich gebauten
Docker-Kommandos, nicht die echte Docker-Ausführung selbst.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.code_sandbox import ExecutionResult
from core.deployment import deploy_project, stop_deployment


def _ok(stdout: str = "") -> ExecutionResult:
    return ExecutionResult(exit_code=0, stdout=stdout, stderr="", duration_seconds=0.1)


def _fail(stderr: str = "boom") -> ExecutionResult:
    return ExecutionResult(exit_code=1, stdout="", stderr=stderr, duration_seconds=0.1)


class TestDeployProjectWithoutDocker(unittest.TestCase):
    def test_skips_cleanly_when_docker_not_installed(self):
        with patch("core.deployment.shutil.which", return_value=None):
            result = deploy_project("/irrelevant/path")
        self.assertFalse(result.attempted)
        self.assertFalse(result.success)
        self.assertIn("nicht installiert", result.reason_skipped)


class TestDeployProjectWithoutDeployableFiles(unittest.TestCase):
    def test_skips_cleanly_when_neither_compose_nor_dockerfile_exists(self):
        project_dir = tempfile.mkdtemp()
        with patch("core.deployment.shutil.which", return_value="/usr/bin/docker"):
            result = deploy_project(project_dir)
        shutil.rmtree(project_dir, ignore_errors=True)
        self.assertFalse(result.attempted)
        self.assertIn("Weder eine Compose-Datei", result.reason_skipped)


class TestDeployProjectWithCompose(unittest.TestCase):
    def setUp(self):
        self.project_dir = Path(tempfile.mkdtemp())
        (self.project_dir / "docker-compose.yml").write_text("services:\n  web:\n    build: .\n", encoding="utf-8")
        self._which_patcher = patch("core.deployment.shutil.which", return_value="/usr/bin/docker")
        self._which_patcher.start()
        self.addCleanup(self._which_patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)

    @patch("core.deployment.CodeSandbox.run_command")
    def test_runs_compose_up_and_reports_published_ports(self, mock_run):
        ps_json = '{"Publishers": [{"PublishedPort": 8000}]}'
        mock_run.side_effect = [_ok("Container started"), _ok(ps_json)]

        result = deploy_project(self.project_dir)

        self.assertTrue(result.attempted)
        self.assertTrue(result.success)
        self.assertEqual(result.method, "compose")
        self.assertEqual(result.urls, ["http://localhost:8000"])

        up_call = mock_run.call_args_list[0]
        self.assertEqual(
            up_call.args[0],
            ["docker", "compose", "-f", "docker-compose.yml", "up", "-d", "--build"],
        )
        self.assertEqual(up_call.kwargs["cwd"], self.project_dir)

    @patch("core.deployment.CodeSandbox.run_command")
    def test_up_failure_is_reported_without_querying_ports(self, mock_run):
        mock_run.return_value = _fail("build failed: syntax error in Dockerfile")

        result = deploy_project(self.project_dir)

        self.assertTrue(result.attempted)
        self.assertFalse(result.success)
        self.assertIn("syntax error", result.output)
        mock_run.assert_called_once()  # kein "docker compose ps" nach fehlgeschlagenem up

    @patch("core.deployment.CodeSandbox.run_command")
    def test_malformed_ps_output_yields_empty_urls_without_crashing(self, mock_run):
        mock_run.side_effect = [_ok("Container started"), _ok("not json")]

        result = deploy_project(self.project_dir)

        self.assertTrue(result.success)
        self.assertEqual(result.urls, [])


class TestDeployProjectWithPlainDockerfile(unittest.TestCase):
    def setUp(self):
        self.project_dir = Path(tempfile.mkdtemp())
        self._which_patcher = patch("core.deployment.shutil.which", return_value="/usr/bin/docker")
        self._which_patcher.start()
        self.addCleanup(self._which_patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)

    @patch("core.deployment.CodeSandbox.run_command")
    def test_build_and_run_with_exposed_port(self, mock_run):
        (self.project_dir / "Dockerfile").write_text(
            "FROM python:3.12\nEXPOSE 8000\nCMD [\"python\", \"app.py\"]\n", encoding="utf-8",
        )
        # Reihenfolge: docker build -> docker rm -f (Aufräumen, Fehler egal) -> docker run
        mock_run.side_effect = [_ok("build ok"), _fail("no such container"), _ok("container-id-123")]

        result = deploy_project(self.project_dir)

        self.assertTrue(result.success)
        self.assertEqual(result.method, "docker")
        self.assertEqual(result.urls, ["http://localhost:8000"])

        run_call = mock_run.call_args_list[2]
        self.assertIn("-p", run_call.args[0])
        self.assertIn("8000:8000", run_call.args[0])

    @patch("core.deployment.CodeSandbox.run_command")
    def test_build_and_run_without_exposed_port_has_no_port_mapping(self, mock_run):
        (self.project_dir / "Dockerfile").write_text("FROM python:3.12\nCMD [\"python\", \"app.py\"]\n", encoding="utf-8")
        mock_run.side_effect = [_ok("build ok"), _fail("no such container"), _ok("container-id-456")]

        result = deploy_project(self.project_dir)

        self.assertTrue(result.success)
        self.assertEqual(result.urls, [])
        run_call = mock_run.call_args_list[2]
        self.assertNotIn("-p", run_call.args[0])

    @patch("core.deployment.CodeSandbox.run_command")
    def test_build_failure_never_attempts_to_run(self, mock_run):
        (self.project_dir / "Dockerfile").write_text("FROM python:3.12\nEXPOSE 8000\n", encoding="utf-8")
        mock_run.return_value = _fail("pip install failed")

        result = deploy_project(self.project_dir)

        self.assertFalse(result.success)
        mock_run.assert_called_once()

    @patch("core.deployment.CodeSandbox.run_command")
    def test_service_name_is_sanitized_from_project_dir_name(self, mock_run):
        weird_dir = self.project_dir / "My Weird_Project!!"
        weird_dir.mkdir()
        (weird_dir / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")
        mock_run.side_effect = [_ok("build ok"), _fail(), _ok("id")]

        deploy_project(weird_dir)

        build_call = mock_run.call_args_list[0]
        tag = build_call.args[0][build_call.args[0].index("-t") + 1]
        self.assertRegex(tag, r"^ai-team-deploy-[a-z0-9-]+$")
        self.assertNotIn(" ", tag)
        self.assertNotIn("!", tag)


class TestStopDeployment(unittest.TestCase):
    def setUp(self):
        self._which_patcher = patch("core.deployment.shutil.which", return_value="/usr/bin/docker")
        self._which_patcher.start()
        self.addCleanup(self._which_patcher.stop)

    @patch("core.deployment.CodeSandbox.run_command")
    def test_stop_with_compose_file_runs_compose_down(self, mock_run):
        project_dir = Path(tempfile.mkdtemp())
        (project_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
        mock_run.return_value = _ok("Stopped")

        result = stop_deployment(project_dir)
        shutil.rmtree(project_dir, ignore_errors=True)

        self.assertTrue(result.success)
        self.assertEqual(result.method, "compose")
        mock_run.assert_called_once_with(
            ["docker", "compose", "-f", "docker-compose.yml", "down"],
            cwd=project_dir, timeout_seconds=60.0,
        )

    @patch("core.deployment.CodeSandbox.run_command")
    def test_stop_without_compose_file_removes_single_container(self, mock_run):
        project_dir = Path(tempfile.mkdtemp())
        mock_run.return_value = _ok("Removed")

        result = stop_deployment(project_dir)
        shutil.rmtree(project_dir, ignore_errors=True)

        self.assertTrue(result.success)
        self.assertEqual(result.method, "docker")
        call_args = mock_run.call_args.args[0]
        self.assertEqual(call_args[:3], ["docker", "rm", "-f"])

    def test_skips_cleanly_when_docker_not_installed(self):
        with patch("core.deployment.shutil.which", return_value=None):
            result = stop_deployment("/irrelevant/path")
        self.assertFalse(result.attempted)


if __name__ == "__main__":
    unittest.main()
