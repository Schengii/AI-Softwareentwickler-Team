"""
tests/test_self_targeting_isolation.py – Testet die Worktree-Isolation in Orchestrator.process()

Realer Fund: Ein Selbstverbesserungslauf (forced_project_dir == config.BASE_DIR) schrieb
bisher DIREKT im echten Arbeitsverzeichnis des Nutzers - genau das ließ main.py UND
interface/cli.py mit kaputtem Inhalt überschrieben werden. Orchestrator.process() muss
für diesen Fall jetzt einen isolierten Git-Worktree verwenden (core/git_isolation.py)
statt BASE_DIR direkt als project_dir durchzureichen - und bei fehlgeschlagener
Isolation den Lauf lieber ABBRECHEN als unsicher fortzufahren.
"""

import asyncio
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agents.orchestrator as orch_module
from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.verifier import VerificationReport


def _run_git(args: list[str], cwd: str):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30)


class _FakeToolCapableLLM:
    def __init__(self, text: str = "Fertig."):
        self._text = text
        self.model_name = "fake-model"

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[])

    async def generate_with_usage(self, prompt, system_prompt=None):
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15)


class TestSelfTargetingUsesIsolatedWorktree(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp()
        self.fake_base_dir = str(Path(self.temp_root) / "framework_repo")
        Path(self.fake_base_dir).mkdir()
        _run_git(["init", "-b", "main"], cwd=self.fake_base_dir)
        _run_git(["config", "user.email", "test@example.com"], cwd=self.fake_base_dir)
        _run_git(["config", "user.name", "Test"], cwd=self.fake_base_dir)
        (Path(self.fake_base_dir) / "main.py").write_text("print('original')\n", encoding="utf-8")
        _run_git(["add", "-A"], cwd=self.fake_base_dir)
        _run_git(["commit", "-m", "initial"], cwd=self.fake_base_dir)

        self.orchestrator = Orchestrator()
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _run(self, forced_project_dir: str):
        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            task = AgentTask(task_id="t1", agent_id="backend", description="Etwas bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "irrelevant_slug", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=False, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.0,
                reason_skipped="simuliert",
            )
            status_logs: list[str] = []
            asyncio.run(self.orchestrator.process(
                "Baue etwas", status_callback=status_logs.append, forced_project_dir=forced_project_dir,
            ))
            return task, status_logs

        return _inner()

    def test_self_targeting_run_uses_isolated_worktree_not_real_dir(self):
        with patch.object(orch_module, "BASE_DIR", self.fake_base_dir):
            task, logs = self._run(self.fake_base_dir)

        self.assertIsNotNone(self.orchestrator.last_isolated_worktree)
        worktree_path = self.orchestrator.last_isolated_worktree.path
        # Die Agenten-Aufgabe muss auf den WORKTREE zeigen, NICHT auf das echte BASE_DIR.
        self.assertEqual(str(Path(task.project_dir).resolve()), str(Path(worktree_path).resolve()))
        self.assertNotEqual(str(Path(task.project_dir).resolve()), str(Path(self.fake_base_dir).resolve()))
        self.assertTrue(any("Isolierter Git-Worktree" in line for line in logs))

    def test_loading_a_different_project_does_not_trigger_isolation(self):
        other_project = str(Path(self.temp_root) / "some_other_project")
        Path(other_project).mkdir()

        with patch.object(orch_module, "BASE_DIR", self.fake_base_dir):
            task, logs = self._run(other_project)

        self.assertIsNone(self.orchestrator.last_isolated_worktree)
        self.assertEqual(str(Path(task.project_dir).resolve()), str(Path(other_project).resolve()))
        self.assertFalse(any("Isolierter Git-Worktree" in line for line in logs))

    def test_self_targeting_aborts_safely_if_isolation_fails(self):
        """Kein Git-Repo -> Isolation nicht möglich -> Lauf MUSS abbrechen statt direkt
        im echten Verzeichnis zu schreiben."""
        non_git_base_dir = str(Path(self.temp_root) / "not_a_git_repo")
        Path(non_git_base_dir).mkdir()

        with patch.object(orch_module, "BASE_DIR", non_git_base_dir):
            task, logs = self._run(non_git_base_dir)

        self.assertIsNone(self.orchestrator.last_isolated_worktree)
        # Die Aufgabe darf NIE ein project_dir bekommen haben (Lauf brach vor der Zuweisung ab).
        self.assertIsNone(task.project_dir)


if __name__ == "__main__":
    unittest.main()
