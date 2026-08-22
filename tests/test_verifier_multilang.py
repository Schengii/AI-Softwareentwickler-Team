"""
tests/test_verifier_multilang.py – Testet Multi-Sprachen-Unterstützung (Rust & Go) in core/verifier.py
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.code_sandbox import ExecutionResult
from core.verifier import ProjectVerifier


class TestVerifierMultiLang(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        self.verifier = ProjectVerifier(self.project_dir)

    def test_rust_detection_and_environment(self):
        (self.project_dir / "Cargo.toml").write_text("[package]\nname = 'test-app'\nversion = '0.1.0'", encoding="utf-8")
        self.assertTrue(self.verifier._has_rust_project())
        self.assertFalse(self.verifier._has_go_project())

        with patch("shutil.which", return_value="/usr/bin/cargo"), \
             patch("core.code_sandbox.CodeSandbox.run_command", return_value=ExecutionResult(exit_code=0, stdout="Checked", stderr="", timed_out=False, duration_seconds=0.1)):
            env_log = self.verifier.ensure_environment()
            self.assertIn("cargo check", env_log)
            self.assertIn("✅", env_log)

    def test_go_detection_and_environment(self):
        (self.project_dir / "go.mod").write_text("module testapp\ngo 1.21", encoding="utf-8")
        self.assertTrue(self.verifier._has_go_project())
        self.assertFalse(self.verifier._has_rust_project())

        with patch("shutil.which", return_value="/usr/bin/go"), \
             patch("core.code_sandbox.CodeSandbox.run_command", return_value=ExecutionResult(exit_code=0, stdout="", stderr="", timed_out=False, duration_seconds=0.1)):
            env_log = self.verifier.ensure_environment()
            self.assertIn("go mod download", env_log)
            self.assertIn("✅", env_log)

    def test_rust_test_execution_pass_and_fail(self):
        (self.project_dir / "Cargo.toml").write_text("[package]\nname = 'test'", encoding="utf-8")

        with patch("shutil.which", return_value="/usr/bin/cargo"), \
             patch("core.code_sandbox.CodeSandbox.run_command", return_value=ExecutionResult(exit_code=0, stdout="test result: ok. 3 passed", stderr="", timed_out=False, duration_seconds=0.1)):
            report = self.verifier.run_tests()
            self.assertTrue(report.ran)
            self.assertTrue(report.passed)
            self.assertIn("cargo test", report.stdout)

        with patch("shutil.which", return_value="/usr/bin/cargo"), \
             patch("core.code_sandbox.CodeSandbox.run_command", return_value=ExecutionResult(exit_code=101, stdout="", stderr="FAILED: test_math", timed_out=False, duration_seconds=0.1)):
            report = self.verifier.run_tests()
            self.assertTrue(report.ran)
            self.assertFalse(report.passed)
            self.assertEqual(len(report.failures), 1)

    def test_go_test_execution_pass(self):
        (self.project_dir / "go.mod").write_text("module testapp", encoding="utf-8")

        with patch("shutil.which", return_value="/usr/bin/go"), \
             patch("core.code_sandbox.CodeSandbox.run_command", return_value=ExecutionResult(exit_code=0, stdout="PASS\nok  testapp 0.05s", stderr="", timed_out=False, duration_seconds=0.1)):
            report = self.verifier.run_tests()
            self.assertTrue(report.ran)
            self.assertTrue(report.passed)
            self.assertIn("go test", report.stdout)

    def test_rust_and_go_lint_and_audit(self):
        (self.project_dir / "Cargo.toml").write_text("[package]\nname = 'test'", encoding="utf-8")
        (self.project_dir / "go.mod").write_text("module testapp", encoding="utf-8")

        with patch("shutil.which", return_value="/usr/bin/cargo"), \
             patch("core.code_sandbox.CodeSandbox.run_command", return_value=ExecutionResult(exit_code=0, stdout="", stderr="", timed_out=False, duration_seconds=0.1)):
            lint_reports = self.verifier.check_lint()
            self.assertTrue(any(r.tool == "clippy" for r in lint_reports))

            audit_reports = self.verifier.check_dependency_vulnerabilities()
            self.assertTrue(any(r.tool == "cargo-audit" for r in audit_reports))


if __name__ == "__main__":
    unittest.main()
