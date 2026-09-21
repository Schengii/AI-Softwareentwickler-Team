"""
tests/test_framework_backlog_worker.py – Testet P1-1 (ROADMAP_TEMP.md): "Root-Cause-Tickets
werden erzeugt, aber nie bearbeitet"

core/framework_backlog_worker.py greift `[framework]`-Root-Cause-Tickets auf, arbeitet in einem
isolierten Git-Worktree und verlangt einen MECHANISCHEN Beweis (rot ohne Fix, grün mit Fix) für
einen neuen Regressionstest, bevor überhaupt committet wird. Nutzt ein echtes temporäres
Git-Repo für die Rot/Grün-Probe (kein Mock - genau die Art Dateisystem-/Git-Interaktion, die ein
Mock nicht glaubwürdig simulieren kann), mockt aber den Agenten-Aufruf und GitHubAgent, um ohne
echte LLM-/Netzwerkaufrufe zu laufen.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.backlog_store import Ticket
from core.framework_backlog_worker import (
    TicketAttemptResult,
    _collect_changes,
    _verify_regression_test_proves_the_bug,
    attempt_ticket,
    find_framework_tickets,
)
from core.message_bus import AgentResult


def _run(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30)


def _make_ticket(**overrides) -> Ticket:
    base = {
        "id": "root-cause-framework-bug", "title": "Beispiel-Bug", "source": "root_cause_analysis",
        "status": "todo", "created_at": "2026-09-21T00:00:00+00:00", "updated_at": "2026-09-21T00:00:00+00:00",
        "detail": "[framework] Root Cause: ein Off-by-one-Fehler\n\nEmpfehlung: Grenzwert korrigieren",
    }
    base.update(overrides)
    return Ticket(**base)


class TestFindFrameworkTickets(unittest.TestCase):
    def test_filters_by_source_status_and_framework_prefix(self):
        tickets = [
            _make_ticket(id="a", status="todo"),
            _make_ticket(id="b", status="done"),  # erledigt - nicht mehr relevant
            _make_ticket(id="c", status="todo", detail="[projekt] gehört nicht zum Framework"),
            _make_ticket(id="d", status="blocked"),
            _make_ticket(id="e", status="todo", source="cli"),  # falsche Quelle
        ]
        with patch("core.framework_backlog_worker.list_tickets", return_value=tickets):
            found = find_framework_tickets()
        self.assertEqual({t.id for t in found}, {"a", "d"})


class TestVerifyRegressionTestProvesTheBug(unittest.TestCase):
    """Baut ein echtes temporäres Git-Repo mit einem Off-by-one-Bug nach."""

    def setUp(self):
        self.temp_root = tempfile.mkdtemp()
        self.repo_dir = str(Path(self.temp_root) / "repo")
        Path(self.repo_dir).mkdir()
        _run(["init", "-b", "main"], cwd=self.repo_dir)
        _run(["config", "user.email", "test@example.com"], cwd=self.repo_dir)
        _run(["config", "user.name", "Test"], cwd=self.repo_dir)
        (Path(self.repo_dir) / "buggy.py").write_text(
            "def clamp(x, hi):\n    return x if x < hi else hi - 1\n", encoding="utf-8",
        )
        (Path(self.repo_dir) / "tests").mkdir()
        _run(["add", "-A"], cwd=self.repo_dir)
        _run(["commit", "-m", "initial (mit Bug)"], cwd=self.repo_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _apply_agent_changes(self, fixed: bool) -> None:
        """Simuliert, was der refactoring-Agent geschrieben hätte: Test + (optional) Fix."""
        (Path(self.repo_dir) / "tests" / "test_clamp.py").write_text(
            "from buggy import clamp\n\ndef test_clamp_returns_hi_for_equal_value():\n"
            "    assert clamp(10, 10) == 10\n",
            encoding="utf-8",
        )
        if fixed:
            (Path(self.repo_dir) / "buggy.py").write_text(
                "def clamp(x, hi):\n    return x if x <= hi else hi\n", encoding="utf-8",
            )

    def test_proves_a_real_fix_with_a_real_new_test(self):
        self._apply_agent_changes(fixed=True)
        changes = _collect_changes(self.repo_dir)

        proven, reason, new_tests = _verify_regression_test_proves_the_bug(self.repo_dir, changes)

        self.assertTrue(proven, reason)
        self.assertEqual(new_tests, ["tests/test_clamp.py"])
        # Endstand (Fix + Test) muss nach der Probe wiederhergestellt sein.
        self.assertIn("x <= hi", (Path(self.repo_dir) / "buggy.py").read_text(encoding="utf-8"))

    def test_rejects_when_no_new_test_file_present(self):
        (Path(self.repo_dir) / "buggy.py").write_text(
            "def clamp(x, hi):\n    return x if x <= hi else hi\n", encoding="utf-8",
        )
        changes = _collect_changes(self.repo_dir)

        proven, reason, new_tests = _verify_regression_test_proves_the_bug(self.repo_dir, changes)

        self.assertFalse(proven)
        self.assertEqual(new_tests, [])
        self.assertIn("Kein neuer Testdatei-Fund", reason)

    def test_rejects_when_test_passes_even_without_the_fix(self):
        # Ein Test, der den Bug gar nicht trifft (kein echter Beweis).
        (Path(self.repo_dir) / "tests" / "test_trivial.py").write_text(
            "def test_true_is_true():\n    assert True\n", encoding="utf-8",
        )
        changes = _collect_changes(self.repo_dir)

        proven, reason, new_tests = _verify_regression_test_proves_the_bug(self.repo_dir, changes)

        self.assertFalse(proven)
        self.assertIn("schon OHNE den Fix nicht fehl", reason)

    def test_rejects_when_fix_does_not_actually_make_the_test_pass(self):
        self._apply_agent_changes(fixed=False)  # Test da, aber Fix fehlt/unwirksam
        changes = _collect_changes(self.repo_dir)

        proven, reason, new_tests = _verify_regression_test_proves_the_bug(self.repo_dir, changes)

        self.assertFalse(proven)
        self.assertIn("weiterhin rot", reason)


class TestAttemptTicket(unittest.TestCase):
    """End-to-End mit echtem Git-Repo, aber gemocktem Agenten-Aufruf und GitHubAgent - kein
    echter LLM-/Netzwerkaufruf."""

    def setUp(self):
        self.temp_root = tempfile.mkdtemp()
        self.repo_dir = str(Path(self.temp_root) / "repo")
        Path(self.repo_dir).mkdir()
        _run(["init", "-b", "main"], cwd=self.repo_dir)
        _run(["config", "user.email", "test@example.com"], cwd=self.repo_dir)
        _run(["config", "user.name", "Test"], cwd=self.repo_dir)
        (Path(self.repo_dir) / "buggy.py").write_text(
            "def clamp(x, hi):\n    return x if x < hi else hi - 1\n", encoding="utf-8",
        )
        (Path(self.repo_dir) / "tests").mkdir()
        # Git kennt keine leeren Verzeichnisse - ohne eine committete Datei existiert "tests/"
        # im neuen isolierten Worktree-Checkout unten sonst schlicht nicht.
        (Path(self.repo_dir) / "tests" / "__init__.py").write_text("", encoding="utf-8")
        _run(["add", "-A"], cwd=self.repo_dir)
        _run(["commit", "-m", "initial"], cwd=self.repo_dir)
        self._base_dir_patcher = patch("core.framework_backlog_worker.BASE_DIR", self.repo_dir)
        self._base_dir_patcher.start()

    def tearDown(self):
        self._base_dir_patcher.stop()
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _fake_orchestrator(self, worktree_dir_holder: dict):
        orch = type("O", (), {})()

        async def fake_run_single_agent(task):
            worktree_dir_holder["path"] = task.project_dir
            (Path(task.project_dir) / "tests" / "test_clamp.py").write_text(
                "from buggy import clamp\n\n\ndef test_clamp_returns_hi_for_equal_value():\n"
                "    assert clamp(10, 10) == 10\n",
                encoding="utf-8",
            )
            (Path(task.project_dir) / "buggy.py").write_text(
                "def clamp(x, hi):\n    return min(x, hi)\n", encoding="utf-8",
            )
            return AgentResult(task_id=task.task_id, agent_id="refactoring", agent_name="Refactoring", success=True, content="Fix erledigt")

        orch._run_single_agent = fake_run_single_agent
        return orch

    def test_successful_attempt_creates_draft_pr(self):
        ticket = _make_ticket()
        holder: dict = {}
        orch = self._fake_orchestrator(holder)

        with patch("agents.github_agent.GitHubAgent") as mock_github_cls:
            mock_github = mock_github_cls.return_value
            mock_github.gh_ready.return_value = True
            mock_github.push.return_value = (True, "pushed")
            mock_github.create_pull_request.return_value = (True, "https://github.com/example/repo/pull/1")

            result = asyncio.run(attempt_ticket(orch, ticket))

        self.assertIsInstance(result, TicketAttemptResult)
        self.assertTrue(result.success, result.reason)
        self.assertEqual(result.pr_url, "https://github.com/example/repo/pull/1")
        self.assertEqual(result.new_test_files, ["tests/test_clamp.py"])
        mock_github.create_pull_request.assert_called_once()
        _, kwargs = mock_github.create_pull_request.call_args
        self.assertTrue(kwargs["draft"])
        self.assertIn(f"Closes: {ticket.id}", kwargs["body"])

        # Der Commit landet auf dem isolierten Branch, NICHT im echten Arbeitsverzeichnis.
        self.assertIn("def clamp(x, hi):\n    return x if x < hi else hi - 1", (Path(self.repo_dir) / "buggy.py").read_text(encoding="utf-8"))

    def test_agent_failure_leaves_no_commit(self):
        ticket = _make_ticket()
        orch = type("O", (), {})()

        async def failing_agent(task):
            return AgentResult(task_id=task.task_id, agent_id="refactoring", agent_name="Refactoring", success=False, content="", error="LLM nicht erreichbar")

        orch._run_single_agent = failing_agent

        result = asyncio.run(attempt_ticket(orch, ticket))

        self.assertFalse(result.success)
        self.assertIn("Agent konnte den Fix nicht abschließen", result.reason)

    def test_no_new_test_blocks_the_commit_even_if_agent_reports_success(self):
        ticket = _make_ticket()
        orch = type("O", (), {})()

        async def fix_without_test(task):
            (Path(task.project_dir) / "buggy.py").write_text(
                "def clamp(x, hi):\n    return x if x <= hi else hi\n", encoding="utf-8",
            )
            return AgentResult(task_id=task.task_id, agent_id="refactoring", agent_name="Refactoring", success=True, content="Fix erledigt (angeblich)")

        orch._run_single_agent = fix_without_test

        result = asyncio.run(attempt_ticket(orch, ticket))

        self.assertFalse(result.success)
        self.assertIn("Kein neuer Testdatei-Fund", result.reason)


if __name__ == "__main__":
    unittest.main()
