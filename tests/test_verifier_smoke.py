"""
tests/test_verifier_smoke.py – Testet die Runtime-Smoke-Prüfung (core/verifier.py.check_runtime_smoke())
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.code_sandbox import ExecutionResult
from core.verifier import ProjectVerifier


class TestCheckRuntimeSmoke(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        self.verifier = ProjectVerifier(self.project_dir)

    def test_no_entrypoints_is_skipped(self):
        report = self.verifier.check_runtime_smoke()
        self.assertFalse(report.attempted)
        self.assertIn("Kein ausführbarer Einstiegspunkt", report.reason_skipped)

    def test_cli_script_help_successful(self):
        (self.project_dir / "main.py").write_text(
            "import argparse\n"
            "parser = argparse.ArgumentParser(description='Test-CLI')\n"
            "parser.add_argument('--version', action='version', version='1.0')\n"
            "args = parser.parse_args()\n",
            encoding="utf-8",
        )

        with patch("core.verifier.CodeSandbox.run_command") as mock_run:
            mock_run.return_value = ExecutionResult(
                exit_code=0, stdout="usage: main.py [-h] [--version]\nTest-CLI", stderr="", duration_seconds=0.1,
            )
            report = self.verifier.check_runtime_smoke()

        self.assertTrue(report.attempted)
        self.assertTrue(report.passed)
        self.assertEqual(report.app_type, "cli_script")
        self.assertEqual(report.entrypoint, "main.py")

    def test_cli_script_failing_reports_failure(self):
        (self.project_dir / "app.py").write_text("import sys\nsys.exit(1)\n", encoding="utf-8")

        with patch("core.verifier.CodeSandbox.run_command") as mock_run:
            mock_run.return_value = ExecutionResult(
                exit_code=1, stdout="", stderr="ImportError: missing module", duration_seconds=0.1,
            )
            report = self.verifier.check_runtime_smoke()

        self.assertTrue(report.attempted)
        self.assertFalse(report.passed)
        self.assertEqual(report.app_type, "cli_script")
        self.assertIn("ImportError", report.output)

    def test_node_entrypoint_syntax_check_passes(self):
        (self.project_dir / "index.js").write_text("console.log('hello world');\n", encoding="utf-8")

        with patch("core.verifier.CodeSandbox.run_command") as mock_run:
            mock_run.return_value = ExecutionResult(exit_code=0, stdout="", stderr="", duration_seconds=0.1)
            report = self.verifier.check_runtime_smoke()

        self.assertTrue(report.attempted)
        self.assertTrue(report.passed)
        self.assertEqual(report.app_type, "node_server")
        self.assertEqual(report.entrypoint, "index.js")

    def test_node_entrypoint_syntax_error_fails(self):
        (self.project_dir / "server.js").write_text("const a = ;\n", encoding="utf-8")

        with patch("core.verifier.CodeSandbox.run_command") as mock_run:
            mock_run.return_value = ExecutionResult(
                exit_code=1, stdout="", stderr="SyntaxError: Unexpected token", duration_seconds=0.1,
            )
            report = self.verifier.check_runtime_smoke()

        self.assertTrue(report.attempted)
        self.assertFalse(report.passed)
        self.assertEqual(report.app_type, "node_server")
        self.assertIn("SyntaxError", report.output)


if __name__ == "__main__":
    unittest.main()
