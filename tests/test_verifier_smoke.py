"""
tests/test_verifier_smoke.py – Testet die Runtime-Smoke-Prüfung (core/verifier.py.check_runtime_smoke())
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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

    def test_fastapi_app_is_started_via_uvicorn_even_without_literal_uvicorn_string(self):
        """Realer Fund (nexus_mesh/aegisflow, 2026-09-18): eine idiomatische FastAPI-App wird
        NIE aus sich selbst heraus gestartet (kein `if __name__ == "__main__": uvicorn.run(...)`),
        sondern immer extern per `uvicorn <modul>:app` - das Wort "uvicorn" kommt im generierten
        Code deshalb oft gar nicht vor. Die alte Bedingung verlangte genau diesen String und griff
        praktisch nie: `python -m <modul>` importierte die App nur und beendete sich sofort, ohne
        je einen Server zu starten - der Smoke-Test hielt eine gesunde App fälschlich für tot."""
        (self.project_dir / "app").mkdir()
        (self.project_dir / "app" / "main.py").write_text(
            "from fastapi import FastAPI\n\napp = FastAPI(title='Test')\n\n@app.get('/health')\n"
            "async def health():\n    return {'status': 'ok'}\n",
            encoding="utf-8",
        )

        captured_cmd = {}

        def fake_popen(cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            proc = MagicMock()
            proc.poll.return_value = None  # bleibt "am Leben", bis der Test es beendet
            proc.communicate.return_value = ("", "")
            return proc

        with patch("core.verifier.runtime.subprocess.Popen", side_effect=fake_popen), \
             patch("core.verifier.runtime.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.status = 200
            report = self.verifier.check_runtime_smoke()

        self.assertTrue(report.attempted)
        self.assertTrue(report.passed)
        self.assertIn("uvicorn", captured_cmd["cmd"])
        self.assertIn("app.main:app", captured_cmd["cmd"])


if __name__ == "__main__":
    unittest.main()
