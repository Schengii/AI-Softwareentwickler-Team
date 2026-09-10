"""
tests/test_agent_toolbox_run_command.py – run_command: Windows-Pfade & Projekt-venv-Bindung

Realer Fund (Framework-Analyse 2026-09-10):
1. `shlex.split()` (POSIX) machte aus `pytest tests\\test_auth.py` auf Windows `teststest_auth.py`.
2. `pip`/`python` wurden auf `sys.executable` gemappt - jedes `pip install` eines Agenten landete in
   der globalen Python-Installation des Nutzers statt in der Projekt-venv.
"""

import asyncio
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.agent_toolbox import AgentToolbox, split_command_line
from core.verifier.models import VENV_DIRNAME

_PYTHON_REL = Path("Scripts/python.exe") if sys.platform == "win32" else Path("bin/python")


def _ok(**_kwargs):
    return SimpleNamespace(exit_code=0, stdout="", stderr="", timed_out=False)


class TestSplitCommandLine(unittest.TestCase):
    def test_windows_mode_keeps_backslashes_and_strips_quotes(self):
        self.assertEqual(
            split_command_line(r'pytest tests\test_auth.py -k "login and not slow"', windows=True),
            ["pytest", r"tests\test_auth.py", "-k", "login and not slow"],
        )

    def test_windows_mode_keeps_absolute_paths(self):
        self.assertEqual(
            split_command_line(r"python -m pytest C:\proj\tests", windows=True),
            ["python", "-m", "pytest", r"C:\proj\tests"],
        )

    def test_posix_mode_is_unchanged(self):
        self.assertEqual(split_command_line("pytest 'a b' -q", windows=False), ["pytest", "a b", "-q"])


class TestProjectInterpreterBinding(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project = Path(self.temp_dir).resolve()
        self.toolbox = AgentToolbox(project_dir=self.temp_dir, agent_id="backend")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_venv(self, name: str = VENV_DIRNAME) -> Path:
        python = self.project / name / _PYTHON_REL
        python.parent.mkdir(parents=True)
        python.write_text("", encoding="utf-8")
        return python

    def test_pip_uses_existing_project_venv_never_framework_interpreter(self):
        python = self._create_venv()
        parts = self.toolbox._split_command("pip install requests")
        self.assertEqual(parts, [str(python), "-m", "pip", "install", "requests"])
        self.assertNotEqual(Path(parts[0]), Path(sys.executable))

    def test_python_uses_project_venv_when_present(self):
        python = self._create_venv(".venv")
        self.assertEqual(self.toolbox._split_command("python -m pytest -q")[0], str(python))

    def test_python_without_venv_falls_back_to_current_interpreter(self):
        with patch("core.agent_toolbox.CodeSandbox.run_command") as mock_run:
            parts = self.toolbox._split_command("python -m pytest")
        self.assertEqual(parts[0], str(Path(sys.executable)))
        mock_run.assert_not_called()  # kein venv-Anlegen für reine Test-/Skriptaufrufe

    def test_pip_without_venv_creates_verifier_venv_first(self):
        calls: list[list[str]] = []

        def fake_run(command, cwd=None, timeout_seconds=30.0, **_kwargs):
            calls.append(list(command))
            if command[1:3] == ["-m", "venv"]:
                self._create_venv()
            return _ok()

        with patch("core.agent_toolbox.CodeSandbox.run_command", side_effect=fake_run):
            result = asyncio.run(self.toolbox.dispatch("run_command", {"command": "pip install requests"}))

        self.assertEqual(result.get("exit_code"), 0, result)
        self.assertEqual(calls[0][:3], [sys.executable, "-m", "venv"])
        self.assertEqual(Path(calls[0][3]).name, VENV_DIRNAME)
        self.assertEqual(calls[1], [str(self.project / VENV_DIRNAME / _PYTHON_REL), "-m", "pip", "install", "requests"])

    def test_pip_aborts_when_venv_cannot_be_created(self):
        with patch(
            "core.agent_toolbox.CodeSandbox.run_command",
            return_value=SimpleNamespace(exit_code=1, stdout="", stderr="venv kaputt", timed_out=False),
        ) as mock_run:
            result = asyncio.run(self.toolbox.dispatch("run_command", {"command": "pip install requests"}))

        self.assertIn("Framework-Interpreter", result.get("error", ""))
        self.assertEqual(mock_run.call_count, 1)  # nur der venv-Versuch, nie ein pip install

    @unittest.skipUnless(os.name == "nt", "Windows-Pfad-Regression nur unter Windows relevant")
    def test_windows_test_path_reaches_sandbox_intact(self):
        captured: list[list[str]] = []

        def fake_run(command, cwd=None, timeout_seconds=30.0, **_kwargs):
            captured.append(list(command))
            return _ok()

        with patch("core.agent_toolbox.CodeSandbox.run_command", side_effect=fake_run):
            asyncio.run(self.toolbox.dispatch("run_command", {"command": r"pytest tests\test_auth.py"}))

        self.assertEqual(captured[0], ["pytest", r"tests\test_auth.py"])


if __name__ == "__main__":
    unittest.main()
