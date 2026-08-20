"""
tests/test_general_worktree_isolation.py – Testet die Worktree-Isolation für ALLE Läufe

Erweitert die bisher nur für Selbstverbesserungsläufe geltende Git-Worktree-Isolation
(tests/test_self_targeting_isolation.py) auf JEDEN Lauf gegen bereits vorhandenen Inhalt -
z.B. ein per /load geladenes bestehendes Projekt. Ein brandneues, leeres Projekt hat
nichts zu verlieren und wird bewusst weiterhin direkt geschrieben.

Nutzt echte temporäre Git-Repos (kein Mock) - Worktree-Isolation ist genau die Art von
Git-Interaktion, die ein Mock nicht glaubwürdig simulieren kann.
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
from core.workspace import WorkspaceManager


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
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


class TestGeneralWorktreeIsolation(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp()
        self.repo_dir = str(Path(self.temp_root) / "repo")
        Path(self.repo_dir).mkdir()
        _run_git(["init", "-b", "main"], cwd=self.repo_dir)
        _run_git(["config", "user.email", "test@example.com"], cwd=self.repo_dir)
        _run_git(["config", "user.name", "Test"], cwd=self.repo_dir)
        (Path(self.repo_dir) / "README.md").write_text("init\n", encoding="utf-8")
        _run_git(["add", "-A"], cwd=self.repo_dir)
        _run_git(["commit", "-m", "initial"], cwd=self.repo_dir)

        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.repo_dir)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _run(self, forced_project_dir: str | None, project_slug: str):
        @patch("agents.orchestrator.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            task = AgentTask(task_id="t1", agent_id="backend", description="Etwas bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", project_slug, [task])
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

    def test_loading_an_existing_committed_project_uses_isolated_worktree(self):
        existing = Path(self.repo_dir) / "existing_project"
        existing.mkdir(parents=True)
        (existing / "main.py").write_text("print('existing')\n", encoding="utf-8")
        _run_git(["add", "-A"], cwd=self.repo_dir)
        _run_git(["commit", "-m", "add existing project"], cwd=self.repo_dir)

        task, logs = self._run(str(existing), "irrelevant")

        self.assertIsNotNone(self.orchestrator.last_isolated_worktree)
        self.assertNotEqual(str(Path(task.project_dir).resolve()), str(existing.resolve()))
        self.assertTrue((Path(task.project_dir) / "main.py").exists())
        self.assertTrue(any("Isolierter Git-Worktree" in line for line in logs))

    def test_brand_new_empty_project_writes_directly_no_worktree_overhead(self):
        task, logs = self._run(None, "brand_new_project")

        self.assertIsNone(self.orchestrator.last_isolated_worktree)
        expected = str(Path(self.repo_dir) / "brand_new_project")
        self.assertEqual(str(Path(task.project_dir).resolve()), str(Path(expected).resolve()))
        self.assertFalse(any("Isolierter Git-Worktree" in line for line in logs))

    def test_existing_project_with_uncommitted_changes_skips_isolation(self):
        existing = Path(self.repo_dir) / "dirty_project"
        existing.mkdir(parents=True)
        (existing / "main.py").write_text("print('committed')\n", encoding="utf-8")
        _run_git(["add", "-A"], cwd=self.repo_dir)
        _run_git(["commit", "-m", "add dirty_project"], cwd=self.repo_dir)
        # Uncommittete Änderung NACH dem Commit - darf im Worktree (letzter Commit) nicht
        # unsichtbar verschwinden.
        (existing / "main.py").write_text("print('uncommitted edit')\n", encoding="utf-8")

        task, logs = self._run(str(existing), "irrelevant")

        self.assertIsNone(self.orchestrator.last_isolated_worktree)
        self.assertEqual(str(Path(task.project_dir).resolve()), str(existing.resolve()))
        self.assertTrue(any("unkommittete Änderungen" in line for line in logs))


class TestSelfTargetingStillWorksAfterGeneralization(unittest.TestCase):
    """Regressions-Gegenprobe: die Verallgemeinerung darf das bestehende Selbstverbesserungs-
    Verhalten (Abbruch bei fehlgeschlagener Isolation) nicht verändert haben."""

    def setUp(self):
        self.temp_root = tempfile.mkdtemp()
        self.non_git_base_dir = str(Path(self.temp_root) / "not_a_repo")
        Path(self.non_git_base_dir).mkdir()

        self.orchestrator = Orchestrator()
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_self_targeting_still_aborts_without_git_repo(self):
        @patch("agents.orchestrator.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            task = AgentTask(task_id="t1", agent_id="backend", description="Etwas bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "irrelevant", [task])
            with patch.object(orch_module, "BASE_DIR", self.non_git_base_dir):
                result = asyncio.run(self.orchestrator.process(
                    "Baue etwas", forced_project_dir=self.non_git_base_dir,
                ))
            self.assertIsNone(task.project_dir)
            self.assertIn("abgebrochen", result)

        _inner()


if __name__ == "__main__":
    unittest.main()
