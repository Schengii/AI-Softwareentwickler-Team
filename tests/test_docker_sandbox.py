"""
tests/test_docker_sandbox.py – Container-Isolation für Agenten-Code (core/docker_sandbox.py)

Realer Fund (Framework-Analyse 2026-09-10): Von Agenten erzeugter Code (Tests, pip-/npm-
Installationsskripte, node/npx) lief direkt auf dem Host und konnte die `.env` des Frameworks
mit allen API-Keys vom Dateisystem lesen. Mit SANDBOX_BACKEND=docker darf der Container
ausschließlich das Projektverzeichnis sehen.

Der letzte Testfall startet einen ECHTEN Container und läuft nur mit erreichbarem Docker-Daemon
UND gesetztem AI_TEAM_DOCKER_INTEGRATION=1 (Image-Download, mehrere Sekunden Laufzeit).
"""

import asyncio
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import BASE_DIR
from core.agent_toolbox import AgentToolbox
from core.code_sandbox import ExecutionResult
from core.docker_sandbox import _CONTAINER_ENV, CONTAINER_VENV, CONTAINER_WORKDIR, DockerSandbox, _mount_arg
from core.verifier import ProjectVerifier


def _result(exit_code: int = 0, stdout: str = "", stderr: str = "", timed_out: bool = False) -> ExecutionResult:
    return ExecutionResult(exit_code=exit_code, stdout=stdout, stderr=stderr, duration_seconds=0.1, timed_out=timed_out)


def _option_values(command: list[str], option: str) -> list[str]:
    return [command[i + 1] for i, part in enumerate(command[:-1]) if part == option]


class _TempProjectMixin:
    def setUp(self):
        DockerSandbox.reset_state()
        self.temp_dir = tempfile.mkdtemp()
        self.project = Path(self.temp_dir).resolve()

    def tearDown(self):
        DockerSandbox.reset_state()
        shutil.rmtree(self.temp_dir, ignore_errors=True)


class TestActivation(_TempProjectMixin, unittest.TestCase):
    def test_local_backend_never_touches_docker(self):
        with patch("core.docker_sandbox.SANDBOX_BACKEND", "local"), \
             patch("core.docker_sandbox.CodeSandbox.run_command") as mock_run:
            self.assertFalse(DockerSandbox.is_active())
        mock_run.assert_not_called()

    def test_unreachable_daemon_warns_once_and_falls_back_to_local(self):
        with patch("core.docker_sandbox.SANDBOX_BACKEND", "docker"), \
             patch("core.docker_sandbox.shutil.which", return_value="docker"), \
             patch("core.docker_sandbox.CodeSandbox.run_command", return_value=_result(1, stderr="500 Internal Server Error")), \
             self.assertLogs("core.docker_sandbox", level="WARNING") as logs:
            self.assertFalse(DockerSandbox.is_active())
            self.assertFalse(DockerSandbox.is_active())
        self.assertEqual(len(logs.output), 1)
        self.assertIn("LOKAL", logs.output[0])

    def test_reachable_daemon_activates_and_is_cached(self):
        with patch("core.docker_sandbox.SANDBOX_BACKEND", "docker"), \
             patch("core.docker_sandbox.shutil.which", return_value="docker"), \
             patch("core.docker_sandbox.CodeSandbox.run_command", return_value=_result(0, "29.7.2\n")) as mock_run:
            self.assertTrue(DockerSandbox.is_active())
            self.assertTrue(DockerSandbox.is_active())
        mock_run.assert_called_once()


class TestCommandConstruction(_TempProjectMixin, unittest.TestCase):
    def test_only_the_project_is_mounted_and_no_host_environment_leaks(self):
        command = DockerSandbox.build_command(
            ["python", "-V"], self.project, image="python:3.12-slim",
            volumes=[("ai-team-pyenv-x", CONTAINER_VENV)], container_name="ai-team-sbx-test",
        )
        mounts = _option_values(command, "--mount")
        binds = [m for m in mounts if m.startswith("type=bind")]
        self.assertEqual(len(binds), 1)
        self.assertIn(str(self.project), binds[0])
        self.assertIn(f"target={CONTAINER_WORKDIR}", binds[0])
        self.assertNotIn(str(Path(BASE_DIR).resolve()), " ".join(mounts))

        env_names = {value.split("=", 1)[0] for value in _option_values(command, "-e")}
        self.assertEqual(env_names, set(_CONTAINER_ENV))
        self.assertIn("no-new-privileges", command)
        self.assertEqual(_option_values(command, "--cap-drop"), ["ALL"])
        self.assertEqual(command[-3:], ["python:3.12-slim", "python", "-V"])

    def test_mount_fields_with_commas_are_quoted(self):
        self.assertEqual(
            _mount_arg(type="bind", source=r"C:\a,b", target="/workspace"),
            'type=bind,"source=C:\\a,b",target=/workspace',
        )

    def test_volume_names_are_stable_per_project_and_image(self):
        first = DockerSandbox.volume_name("pyenv", self.project, "python:3.12-slim")
        self.assertEqual(first, DockerSandbox.volume_name("pyenv", self.project, "python:3.12-slim"))
        self.assertNotEqual(first, DockerSandbox.volume_name("pyenv", self.project, "python:3.13-slim"))
        self.assertRegex(first, r"^ai-team-pyenv-[a-z0-9_.-]+-[0-9a-f]{12}$")


class TestExecution(_TempProjectMixin, unittest.TestCase):
    def test_run_python_bootstraps_venv_normalizes_paths_and_maps_output(self):
        with patch.object(DockerSandbox, "ensure_image", return_value=None), \
             patch("core.docker_sandbox.CodeSandbox.run_command",
                   return_value=_result(1, f"{CONTAINER_WORKDIR}/tests/test_a.py:3: AssertionError")) as mock_run:
            result = DockerSandbox.run_python(["pytest", r"tests\test_a.py"], self.project, 30)

        command = mock_run.call_args.args[0]
        self.assertEqual(command[:2], ["docker", "run"])
        self.assertIn("sh", command)
        self.assertEqual(command[-1], "tests/test_a.py")
        self.assertTrue(any(m.endswith(f"target={CONTAINER_VENV}") for m in _option_values(command, "--mount")))
        self.assertEqual(result.stdout, "tests/test_a.py:3: AssertionError")

    def test_timeout_force_removes_the_container(self):
        with patch.object(DockerSandbox, "ensure_image", return_value=None), \
             patch("core.docker_sandbox.CodeSandbox.run_command",
                   side_effect=[_result(-1, timed_out=True), _result(0)]) as mock_run:
            result = DockerSandbox.run_python(["python", "-m", "pytest"], self.project, 5)

        self.assertTrue(result.timed_out)
        container_name = _option_values(mock_run.call_args_list[0].args[0], "--name")[0]
        self.assertEqual(mock_run.call_args_list[1].args[0], ["docker", "rm", "-f", container_name])

    def test_image_pull_failure_is_reported_without_starting_a_container(self):
        with patch("core.docker_sandbox.CodeSandbox.run_command",
                   side_effect=[_result(1, stderr="No such image"), _result(1, stderr="kein Netzwerk")]) as mock_run:
            result = DockerSandbox.run_python(["python", "-V"], self.project, 30)

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("python:", result.stderr)
        self.assertEqual(mock_run.call_count, 2)  # inspect + pull, kein docker run

    def test_run_node_keeps_node_modules_in_a_volume_for_subdirectories(self):
        frontend = self.project / "frontend"
        frontend.mkdir()
        with patch.object(DockerSandbox, "ensure_image", return_value=None), \
             patch("core.docker_sandbox.CodeSandbox.run_command", return_value=_result(0)) as mock_run:
            DockerSandbox.run_node(["npm", "ci"], self.project, frontend, 30)

        command = mock_run.call_args.args[0]
        self.assertEqual(_option_values(command, "-w"), [f"{CONTAINER_WORKDIR}/frontend"])
        self.assertTrue(any(
            m.startswith("type=volume") and m.endswith(f"target={CONTAINER_WORKDIR}/frontend/node_modules")
            for m in _option_values(command, "--mount")
        ))


class TestRoutingWhenSandboxIsActive(_TempProjectMixin, unittest.TestCase):
    def test_dependency_installation_runs_in_container_not_in_a_host_venv(self):
        (self.project / "requirements.txt").write_text("requests\n", encoding="utf-8")
        verifier = ProjectVerifier(self.project)
        with patch.object(DockerSandbox, "is_active", return_value=True), \
             patch.object(DockerSandbox, "run_python", return_value=_result(0)) as run_python, \
             patch("core.verifier.environment.CodeSandbox.run_command") as host_run:
            status = verifier._ensure_python_environment(self.project / "requirements.txt", 60)

        run_python.assert_called_once_with(["pip", "install", "-q", "-r", "requirements.txt"], verifier.project_dir, 60)
        host_run.assert_not_called()
        self.assertIn("Docker-Sandbox", status)
        self.assertFalse((self.project / ".ai_team_venv").exists())

    def test_tests_run_in_container_with_relative_paths(self):
        (self.project / "tests").mkdir()
        (self.project / "tests" / "test_x.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        with patch.object(DockerSandbox, "is_active", return_value=True), \
             patch.object(DockerSandbox, "run_python", side_effect=[_result(0), _result(0, "1 passed")]) as run_python, \
             patch("core.verifier.testrunner.CodeSandbox.run_command") as host_run:
            report = ProjectVerifier(self.project).run_tests()

        self.assertTrue(report.passed)
        self.assertEqual(
            run_python.call_args_list[1].args[0],
            ["python", "-m", "pytest", "-q", "--tb=short", "-o", "asyncio_mode=auto", "."],
        )
        host_run.assert_not_called()

    def test_frontend_build_runs_in_container_and_reports_missing_install(self):
        (self.project / "package.json").write_text('{"scripts": {"build": "vite build"}}', encoding="utf-8")
        verifier = ProjectVerifier(self.project)
        with patch.object(DockerSandbox, "is_active", return_value=True), \
             patch.object(DockerSandbox, "run_node", return_value=_result(90)):
            reports = verifier.check_frontend_build()
        self.assertFalse(reports[0].passed)
        self.assertIn("node_modules", reports[0].output)

        with patch.object(DockerSandbox, "is_active", return_value=True), \
             patch.object(DockerSandbox, "run_node", return_value=_result(0)) as run_node:
            reports = verifier.check_frontend_build()
        self.assertTrue(reports[0].passed)
        self.assertEqual(run_node.call_args.args[2], verifier.project_dir)

    def test_agent_run_command_executes_code_in_container(self):
        toolbox = AgentToolbox(project_dir=self.temp_dir, agent_id="backend")
        with patch.object(DockerSandbox, "is_active", return_value=True), \
             patch.object(DockerSandbox, "run_python", return_value=_result(0, "ok")) as run_python, \
             patch("core.agent_toolbox.CodeSandbox.run_command") as host_run:
            result = asyncio.run(toolbox.dispatch("run_command", {"command": "pip install requests"}))

        self.assertEqual(result.get("sandbox"), "docker")
        self.assertEqual(run_python.call_args.args[0], ["pip", "install", "requests"])
        host_run.assert_not_called()

    def test_static_analysis_tools_stay_local(self):
        toolbox = AgentToolbox(project_dir=self.temp_dir, agent_id="backend")
        with patch.object(DockerSandbox, "is_active", return_value=True), \
             patch.object(DockerSandbox, "run_python") as run_python, \
             patch("core.agent_toolbox.CodeSandbox.run_command", return_value=_result(0)) as host_run:
            asyncio.run(toolbox.dispatch("run_command", {"command": "ruff check ."}))

        run_python.assert_not_called()
        host_run.assert_called_once()


@unittest.skipUnless(
    os.getenv("AI_TEAM_DOCKER_INTEGRATION") == "1" and shutil.which("docker"),
    "Echter Container-Test nur mit AI_TEAM_DOCKER_INTEGRATION=1 und installiertem Docker",
)
class TestRealContainerIsolation(_TempProjectMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._backend_patch = patch("core.docker_sandbox.SANDBOX_BACKEND", "docker")
        self._backend_patch.start()
        if not DockerSandbox.is_active():
            self._backend_patch.stop()
            self.skipTest("Docker-Daemon nicht erreichbar")

    def tearDown(self):
        self._backend_patch.stop()
        super().tearDown()

    def test_container_sees_only_the_project_and_no_host_secrets(self):
        (self.project / "marker.txt").write_text("x", encoding="utf-8")
        probe = (
            "import json, os; "
            "print(json.dumps({'files': sorted(os.listdir('.')), "
            "'canary': os.environ.get('AI_TEAM_CANARY_API_KEY'), "
            "'mountinfo': open('/proc/self/mountinfo').read()}))"
        )
        with patch.dict(os.environ, {"AI_TEAM_CANARY_API_KEY": "darf-nie-im-container-landen"}):
            result = DockerSandbox.run_python(["python", "-c", probe], self.project, 600)

        self.assertEqual(result.exit_code, 0, result.stderr)
        data = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertIn("marker.txt", data["files"])
        self.assertIsNone(data["canary"])
        self.assertNotIn(Path(BASE_DIR).name, data["mountinfo"])
        self.assertFalse((self.project / ".ai_team_venv").exists())


if __name__ == "__main__":
    unittest.main()
