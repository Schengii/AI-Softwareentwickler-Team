"""
tests/test_verifier.py – Testet die echte Verifikationsschleife (core/verifier.py)

Nutzt bewusst KEINE requirements.txt in den Testprojekten, damit ensure_environment()
kein venv anlegt / kein pip install ausführt (offline, schnell) – run_tests() läuft
direkt mit dem aktuellen Interpreter gegen echten, temporären Testcode.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.code_sandbox import ExecutionResult
from core.verifier import ProjectVerifier


class TestProjectVerifier(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_skips_when_no_test_files_present(self):
        (self.project_dir / "app.py").write_text("def add(a, b):\n    return a + b\n")
        verifier = ProjectVerifier(self.project_dir)
        report = verifier.run_tests()
        self.assertFalse(report.ran)
        self.assertTrue(report.passed)
        self.assertIn("Keine Testdateien", report.reason_skipped)

    def test_incomplete_backend_without_entrypoint_fails_instead_of_skipping(self):
        """
        Realer Fund (Workspace-Audit): ein Projekt mit requirements.txt und mehreren
        Python-Modulen, aber ohne jeden Einstiegspunkt (main.py/app.py/...), sah bisher
        wie ein bestandenes "keine Tests gefunden" aus - dabei war der Lauf offenbar
        mitten in der Generierung abgebrochen.
        """
        (self.project_dir / "requirements.txt").write_text("fastapi\n")
        (self.project_dir / "models.py").write_text("class Item:\n    pass\n")
        (self.project_dir / "security.py").write_text("def hash_password(pw):\n    return pw\n")
        report = ProjectVerifier(self.project_dir).run_tests()
        self.assertFalse(report.ran)
        self.assertFalse(report.passed)
        self.assertIn("Unvollständiges Projekt", report.reason_skipped)

    def test_incomplete_test_suite_with_only_conftest_fails_instead_of_skipping(self):
        """Realer Fund: tests/conftest.py existierte, aber keine einzige echte Testdatei."""
        (self.project_dir / "app.py").write_text("def add(a, b):\n    return a + b\n")
        tests_dir = self.project_dir / "tests"
        tests_dir.mkdir()
        (tests_dir / "conftest.py").write_text("import pytest\n")
        report = ProjectVerifier(self.project_dir).run_tests()
        self.assertFalse(report.ran)
        self.assertFalse(report.passed)
        self.assertIn("Unvollständiges Projekt", report.reason_skipped)

    def test_single_script_without_manifest_is_still_a_legitimate_skip(self):
        """Grenzfall: EIN Modul + ein zweites Hilfsmodul, aber ohne requirements.txt, ist
        weiterhin ein legitimes kleines Skript, kein erkennbar abgebrochenes Backend."""
        (self.project_dir / "app.py").write_text("def add(a, b):\n    return a + b\n")
        (self.project_dir / "helpers.py").write_text("def double(x):\n    return x * 2\n")
        report = ProjectVerifier(self.project_dir).run_tests()
        self.assertFalse(report.ran)
        self.assertTrue(report.passed)
        self.assertIn("Keine Testdateien", report.reason_skipped)

    def test_real_passing_test_is_detected(self):
        (self.project_dir / "app.py").write_text("def add(a, b):\n    return a + b\n")
        (self.project_dir / "test_app.py").write_text(
            "import unittest\nfrom app import add\n\n"
            "class TestAdd(unittest.TestCase):\n"
            "    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n"
        )
        verifier = ProjectVerifier(self.project_dir)
        report = verifier.run_tests()
        self.assertTrue(report.ran)
        self.assertTrue(report.passed, msg=f"stdout={report.stdout}\nstderr={report.stderr}")
        self.assertEqual(report.failures, [])

    def test_real_failing_test_is_parsed_with_implicated_file(self):
        (self.project_dir / "app.py").write_text("def add(a, b):\n    return a - b  # Bug: sollte + sein\n")
        (self.project_dir / "test_app.py").write_text(
            "import unittest\nfrom app import add\n\n"
            "class TestAdd(unittest.TestCase):\n"
            "    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n"
        )
        verifier = ProjectVerifier(self.project_dir)
        report = verifier.run_tests()

        self.assertTrue(report.ran)
        self.assertFalse(report.passed)
        self.assertGreater(len(report.failures), 0)
        # Der echte Traceback muss auf die Testdatei zeigen (kein Keyword-Raten).
        all_implicated = {f for failure in report.failures for f in failure.files}
        self.assertTrue(any("test_app.py" in f for f in all_implicated))

    def test_none_stderr_from_subprocess_does_not_crash_run_tests(self):
        """Realer Fund (P1-3, ROADMAP_TEMP.md): drei Backlog-Tickets (cli-c1f46a6e,
        cli-d93dccc6, cli-3972afbe) crashten mit identischem Traceback -
        `"\\n".join(stderr_chunks)` warf `TypeError: sequence item 0: expected str instance,
        NoneType found`, weil `ExecutionResult.stderr` (als `str` typisiert, aber zur Laufzeit
        nicht erzwungen) mindestens einmal `None` statt eines echten Strings ankam. `stderr`
        wurde bisher ROH angehängt statt wie `stdout` über ein f-String (das `None` unbemerkt
        in den Text "None" verwandelt hätte) - ein einzelnes `None` in der Liste reichte, um den
        GESAMTEN Verifikations-Lauf abstürzen zu lassen."""
        (self.project_dir / "test_app.py").write_text("def test_ok():\n    assert True\n")

        def fake_run_command(*args, **kwargs):
            return ExecutionResult(exit_code=0, stdout="1 passed", stderr=None, duration_seconds=0.1)

        with patch("core.verifier.testrunner.CodeSandbox.run_command", side_effect=fake_run_command):
            verifier = ProjectVerifier(self.project_dir)
            report = verifier.run_tests()  # darf NICHT werfen

        self.assertTrue(report.ran)
        self.assertTrue(report.passed)

    def test_ensure_environment_is_noop_without_requirements(self):
        (self.project_dir / "app.py").write_text("x = 1\n")
        verifier = ProjectVerifier(self.project_dir)
        result = verifier.ensure_environment()
        self.assertEqual(result, "")

    def test_ensure_environment_skips_pytest_check_without_python_test_files(self):
        # Team-Optimierung (echter Fund: memory/backlog.json `recurring-failure-event_relay`/
        # `recurring-failure-service_bookmark_monitor`) - _ensure_pytest_available() darf nur
        # laufen, wenn überhaupt echte Python-Testdateien existieren, sonst unnötiger
        # zusätzlicher pip-Aufruf für Projekte ohne Python-Tests.
        (self.project_dir / "requirements.txt").write_text("flask\n")
        (self.project_dir / "app.py").write_text("x = 1\n")
        verifier = ProjectVerifier(self.project_dir)
        with patch.object(ProjectVerifier, "_ensure_python_environment", return_value="") as mock_env, \
             patch.object(ProjectVerifier, "_ensure_pytest_available") as mock_pytest:
            verifier.ensure_environment()
        mock_env.assert_called_once()
        mock_pytest.assert_not_called()

    def test_ensure_environment_checks_pytest_when_python_test_files_present(self):
        (self.project_dir / "requirements.txt").write_text("flask\n")
        (self.project_dir / "test_app.py").write_text("def test_ok():\n    assert True\n")
        verifier = ProjectVerifier(self.project_dir)
        with patch.object(ProjectVerifier, "_ensure_python_environment", return_value=""), \
             patch.object(ProjectVerifier, "_ensure_pytest_available", return_value="✅ ok") as mock_pytest:
            result = verifier.ensure_environment()
        mock_pytest.assert_called_once()
        self.assertIn("✅ ok", result)

    def test_ensure_pytest_available_noop_when_already_importable(self):
        verifier = ProjectVerifier(self.project_dir)
        with patch("core.verifier.environment.CodeSandbox.run_command", return_value=ExecutionResult(
            exit_code=0, stdout="", stderr="", duration_seconds=0.01,
        )) as mock_run:
            result = verifier._ensure_pytest_available(timeout_seconds=10.0)
        self.assertEqual(result, "")
        mock_run.assert_called_once()  # nur der `import pytest`-Check, KEIN pip install

    def test_ensure_pytest_available_installs_missing_pytest(self):
        # Realer Fund: core/verifier/testrunner.py._run_pytest_or_unittest() fällt bei fehlendem
        # `pytest` still auf `unittest discover` zurück, das generierten pytest-Stil-Testcode
        # (einfache def test_...()-Funktionen ohne unittest.TestCase) nicht erkennt und "Ran 0
        # tests" meldet - der Fix-Loop konnte das bisher keinem Agenten sinnvoll zuordnen.
        verifier = ProjectVerifier(self.project_dir)
        calls = []

        def _fake_run(cmd, **kwargs):
            calls.append(cmd)
            if any("import pytest" in part for part in cmd):
                return ExecutionResult(exit_code=1, stdout="", stderr="ModuleNotFoundError", duration_seconds=0.01)
            return ExecutionResult(exit_code=0, stdout="Successfully installed pytest", stderr="", duration_seconds=0.5)

        with patch("core.verifier.environment.CodeSandbox.run_command", side_effect=_fake_run):
            result = verifier._ensure_pytest_available(timeout_seconds=10.0)

        self.assertIn("nachinstalliert", result)
        self.assertEqual(len(calls), 2)
        self.assertIn("pip", calls[1])
        self.assertIn("pytest", calls[1])
        # Schwachstelle 1 (Analysebericht 20260913): pytest-asyncio wird IMMER zusammen mit
        # pytest installiert, damit async def test_...-Funktionen out-of-the-box laufen.
        self.assertIn("pytest-asyncio", calls[1])

    def test_docker_build_skipped_without_dockerfile(self):
        verifier = ProjectVerifier(self.project_dir)
        report = verifier.check_docker_build()
        self.assertFalse(report.attempted)
        self.assertTrue(report.success)
        self.assertIn("Kein Dockerfile", report.reason_skipped)

    @patch("core.verifier.shutil.which", return_value=None)
    def test_docker_build_skipped_when_docker_not_installed(self, mock_which):
        (self.project_dir / "Dockerfile").write_text("FROM python:3.12\n")
        verifier = ProjectVerifier(self.project_dir)
        report = verifier.check_docker_build()
        self.assertFalse(report.attempted)
        self.assertTrue(report.success)
        self.assertIn("nicht installiert", report.reason_skipped)

    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/docker")
    def test_docker_build_success_is_reported(self, mock_which, mock_run):
        (self.project_dir / "Dockerfile").write_text("FROM python:3.12\n")
        mock_run.return_value = ExecutionResult(exit_code=0, stdout="Successfully built abc123", stderr="", duration_seconds=1.0)

        verifier = ProjectVerifier(self.project_dir)
        report = verifier.check_docker_build()

        self.assertTrue(report.attempted)
        self.assertTrue(report.success)
        mock_run.assert_called_once()
        self.assertEqual(mock_run.call_args[0][0][:2], ["docker", "build"])

    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/docker")
    def test_docker_build_failure_is_reported_with_real_output(self, mock_which, mock_run):
        (self.project_dir / "Dockerfile").write_text("FROM does-not-exist:latest\n")
        mock_run.return_value = ExecutionResult(exit_code=1, stdout="", stderr="pull access denied", duration_seconds=1.0)

        verifier = ProjectVerifier(self.project_dir)
        report = verifier.check_docker_build()

        self.assertTrue(report.attempted)
        self.assertFalse(report.success)
        self.assertIn("pull access denied", report.output)

    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/docker")
    def test_docker_build_daemon_unavailable_is_not_a_failure(self, mock_which, mock_run):
        # Realer Fund (incidentpilot-Projekt): Docker war installiert, aber der Daemon (Docker
        # Desktop) lief lokal nicht - der Build schlägt dann fehl, obwohl das nichts über die
        # Codequalität aussagt. Muss wie ein fehlendes Dockerfile/nicht installiertes Docker als
        # attempted=False (nur nicht prüfbar), NICHT als echter Fehlschlag gemeldet werden.
        (self.project_dir / "Dockerfile").write_text("FROM python:3.12\n")
        mock_run.return_value = ExecutionResult(
            exit_code=1, stdout="", stderr=(
                "error during connect: this error may indicate that the docker daemon is not "
                "running: Get \"http://%2F%2F.%2Fpipe%2Fdocker_engine/v1.24/...\""
            ),
            duration_seconds=1.0,
        )

        verifier = ProjectVerifier(self.project_dir)
        report = verifier.check_docker_build()

        self.assertFalse(report.attempted)
        self.assertTrue(report.success)
        self.assertIn("Daemon", report.reason_skipped)

    @patch("core.verifier.CodeSandbox.run_command")
    def test_pytest_timeout_is_parsed_as_specific_failure(self, mock_run):
        """Wenn ein Testprozess im Timeout abbricht (timed_out=True), muss dies strukturiert
        als pytest (timeout) TestFailure mit aussagekräftigem Hinweis gemeldet werden."""
        (self.project_dir / "test_worker.py").write_text("def test_hang(): pass\n")
        # Simuliere Timeout im Subprozess
        mock_run.return_value = ExecutionResult(
            exit_code=1,
            stdout="running tests...\n",
            stderr="",
            duration_seconds=15.0,
            timed_out=True,
        )

        verifier = ProjectVerifier(self.project_dir)
        report = verifier.run_tests()

        self.assertTrue(report.ran)
        self.assertFalse(report.passed)
        self.assertEqual(len(report.failures), 1)
        fail = report.failures[0]
        self.assertEqual(fail.test_id, "pytest (timeout)")
        self.assertIn("TIMEOUT", fail.message)
        self.assertIn("Deadlock", fail.message)


if __name__ == "__main__":
    unittest.main()
