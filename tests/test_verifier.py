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

    def test_ensure_environment_is_noop_without_requirements(self):
        (self.project_dir / "app.py").write_text("x = 1\n")
        verifier = ProjectVerifier(self.project_dir)
        result = verifier.ensure_environment()
        self.assertEqual(result, "")

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


if __name__ == "__main__":
    unittest.main()
