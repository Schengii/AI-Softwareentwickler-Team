"""
tests/test_polyglot_verifier.py – Testet Multi-Sprachen-Erweiterungen (Java, C#, PHP, Flutter) in core/verifier.py
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.code_sandbox import ExecutionResult
from core.verifier import ProjectVerifier


class TestPolyglotVerifier(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        self.verifier = ProjectVerifier(self.project_dir)

    def test_java_detection_and_environment(self):
        (self.project_dir / "pom.xml").write_text("<project></project>", encoding="utf-8")
        self.assertTrue(self.verifier._has_java_project())
        self.assertFalse(self.verifier._has_dotnet_project())

        with patch("shutil.which", return_value="/usr/bin/mvn"), \
             patch("core.code_sandbox.CodeSandbox.run_command", return_value=ExecutionResult(exit_code=0, stdout="Resolved", stderr="", timed_out=False, duration_seconds=0.1)):
            env_log = self.verifier.ensure_environment()
            self.assertIn("mvn dependency:resolve", env_log)
            self.assertIn("✅", env_log)

    def test_dotnet_detection_and_test(self):
        (self.project_dir / "MyProject.csproj").write_text("<Project></Project>", encoding="utf-8")
        self.assertTrue(self.verifier._has_dotnet_project())

        with patch("shutil.which", return_value="/usr/bin/dotnet"), \
             patch("core.code_sandbox.CodeSandbox.run_command", return_value=ExecutionResult(exit_code=0, stdout="Passed!  - Failed:     0, Passed:     5", stderr="", timed_out=False, duration_seconds=0.1)):
            report = self.verifier.run_tests()
            self.assertTrue(report.ran)
            self.assertTrue(report.passed)
            self.assertIn(".NET test", report.stdout)

    def test_php_detection_and_test(self):
        (self.project_dir / "composer.json").write_text("{}", encoding="utf-8")
        self.assertTrue(self.verifier._has_php_project())

        with patch("shutil.which", return_value="/usr/bin/phpunit"), \
             patch("core.code_sandbox.CodeSandbox.run_command", return_value=ExecutionResult(exit_code=0, stdout="OK (4 tests, 4 assertions)", stderr="", timed_out=False, duration_seconds=0.1)):
            report = self.verifier.run_tests()
            self.assertTrue(report.ran)
            self.assertTrue(report.passed)
            self.assertIn("PHPUnit", report.stdout)

    def test_flutter_detection_and_test(self):
        (self.project_dir / "pubspec.yaml").write_text("name: my_app", encoding="utf-8")
        self.assertTrue(self.verifier._has_flutter_project())

        with patch("shutil.which", return_value="/usr/bin/flutter"), \
             patch("core.code_sandbox.CodeSandbox.run_command", return_value=ExecutionResult(exit_code=0, stdout="All tests passed!", stderr="", timed_out=False, duration_seconds=0.1)):
            report = self.verifier.run_tests()
            self.assertTrue(report.ran)
            self.assertTrue(report.passed)
            self.assertIn("flutter test", report.stdout)
