"""
tests/test_cross_run_ticket_context.py – Testet das Cross-Run-Gedächtnis in
agents/orchestrator/verification.py: ein offenes ("blocked") Ticket aus einem VORHERIGEN Lauf
desselben Projekts (core/backlog_store.py) fließt jetzt als Kontext in den ersten Fix-Auftrag
DIESES Laufs ein (_prior_run_context()) und wird automatisch als gelöst geschlossen, sobald die
Testsuite/das Governance-Review in DIESEM Lauf tatsächlich grün wird - statt dass ein
"blocked"-Ticket auf unbestimmte Zeit liegen bleibt, obwohl das Problem längst behoben ist.

Team-Retrospektive nach dem taskpulse-Lauf, zweite Runde: bisher startete JEDER neue Lauf bei
Null, ohne zu wissen, dass ein Fixversuch für ein ähnliches Problem im letzten Lauf bereits
gescheitert war.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import core.backlog_store as backlog_store
from agents.orchestrator import Orchestrator
from agents.orchestrator.verification import _prior_run_context
from core import team_memory
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.verifier import LintReport, VerificationReport
from core.workspace import WorkspaceManager

CLEAN_CODE_REVIEWER_REPORT = """## Code-Review Report

### 🔴 Kritische Probleme (müssen behoben werden)
Keine kritischen Probleme gefunden.
"""

PASSED_REPORT = VerificationReport(
    ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
)


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


class TestPriorRunContextHelper(unittest.TestCase):
    """Testet _prior_run_context() direkt, ohne den vollen Orchestrator-Lauf - dieselbe
    hermetische Umleitung (patch.object auf BACKLOG_FILE) wie tests/test_backlog_store.py."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(self.temp_dir) / "backlog.json")
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_no_ticket_returns_empty_string(self):
        self.assertEqual(_prior_run_context("recurring-failure-does-not-exist"), "")

    def test_blocked_ticket_returns_context_with_detail(self):
        backlog_store.upsert_ticket(
            "recurring-failure-proj", "X", "orchestrator", "blocked",
            detail="Fixversuch änderte nichts an 2 Testfehler(n).", project_slug="proj",
        )

        context = _prior_run_context("recurring-failure-proj")

        self.assertIn("VORHERIGER Lauf", context)
        self.assertIn("Fixversuch änderte nichts", context)

    def test_done_ticket_returns_empty_string(self):
        # Ein bereits geschlossenes Ticket ist kein offenes Problem mehr - kein Kontext nötig.
        backlog_store.upsert_ticket("recurring-failure-proj", "X", "orchestrator", "done", detail="behoben")

        self.assertEqual(_prior_run_context("recurring-failure-proj"), "")


class TestCrossRunTicketClosing(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()
        self._team_memory_patch = patch.object(team_memory, "TEAM_MEMORY_FILE", Path(self.temp_workspace) / "team_lessons.jsonl")
        self._team_memory_patch.start()
        self._backlog_patch = patch.object(backlog_store, "BACKLOG_FILE", Path(self.temp_workspace) / "backlog.json")
        self._backlog_patch.start()

    def tearDown(self):
        self._team_memory_patch.stop()
        self._backlog_patch.stop()
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self):
        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            task = AgentTask(task_id="t1", agent_id="backend", description="Baue etwas")
            mock_decompose.return_value = ("Kurze Aufgabe", "cross_run_test_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = PASSED_REPORT
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_lint.return_value = []

            status_logs: list[str] = []
            result = asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return result, status_logs

        return _inner()

    def test_prior_blocked_test_ticket_closed_after_green_run(self):
        backlog_store.upsert_ticket(
            "recurring-failure-cross_run_test_proj", "Alter Testfehler", "orchestrator", "blocked",
            detail="War kaputt.", project_slug="cross_run_test_proj",
        )

        result, logs = self._run()

        ticket = backlog_store.get_ticket("recurring-failure-cross_run_test_proj")
        self.assertEqual(ticket.status, "done")
        self.assertTrue(any("Ticket für vorherigen Testfehlschlag als gelöst geschlossen" in line for line in logs))

    def test_no_prior_ticket_means_no_close_attempt(self):
        # Kein vorheriges Ticket -> kein "geschlossen"-Hinweis, kein Ticket wird künstlich
        # neu angelegt, nur weil die Testsuite grün war.
        result, logs = self._run()

        self.assertIsNone(backlog_store.get_ticket("recurring-failure-cross_run_test_proj"))
        self.assertFalse(any("als gelöst geschlossen" in line for line in logs))

    def test_prior_blocked_governance_ticket_closed_when_review_now_clean(self):
        backlog_store.upsert_ticket(
            "unresolved-governance-critical-cross_run_test_proj", "Alter Governance-Befund",
            "orchestrator", "blocked", detail="War kritisch.", project_slug="cross_run_test_proj",
        )
        self.orchestrator._agents["code_reviewer"]._llm = _FakeToolCapableLLM(text=CLEAN_CODE_REVIEWER_REPORT)

        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            tasks = [
                AgentTask(task_id="t1", agent_id="backend", description="Baue etwas"),
                AgentTask(task_id="t2", agent_id="code_reviewer", description="Review durchführen"),
            ]
            mock_decompose.return_value = ("Kurze Aufgabe", "cross_run_test_proj", tasks)
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = PASSED_REPORT
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_lint.return_value = []
            status_logs: list[str] = []
            asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return status_logs

        logs = _inner()

        ticket = backlog_store.get_ticket("unresolved-governance-critical-cross_run_test_proj")
        self.assertEqual(ticket.status, "done")
        self.assertTrue(any("Ticket für vorherigen Governance-Befund als gelöst geschlossen" in line for line in logs))

    def test_prior_blocked_lint_ticket_closed_after_clean_lint_run(self):
        # Team-Optimierung (Retrospektive, 2026-09-04): anders als "recurring-failure-" oben
        # wurde ein "recurring-lint-"-Ticket bisher NIE automatisch geschlossen, selbst wenn ein
        # späterer Lauf keine Lint-Funde mehr meldete - core/backlog_worker.py konnte es zwar
        # inzwischen erneut aufgreifen (siehe tests/test_backlog_worker.py), aber ohne diesen
        # Auto-Close blieb es trotz erfolgreichem Fix für immer "blocked".
        backlog_store.upsert_ticket(
            "recurring-lint-cross_run_test_proj", "Alter Lint-Fund", "orchestrator", "blocked",
            detail="ruff:app/main.py:B008", project_slug="cross_run_test_proj",
        )

        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            task = AgentTask(task_id="t1", agent_id="backend", description="Baue etwas")
            mock_decompose.return_value = ("Kurze Aufgabe", "cross_run_test_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = PASSED_REPORT
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            # attempted=True, aber keine issues -> "wirklich geprüft und sauber", nicht bloß
            # "Lint übersprungen" (siehe last_lint_attempted-Guard in verification.py).
            mock_verifier.check_lint.return_value = [
                LintReport(attempted=True, passed=True, tool="ruff", issues=[]),
            ]

            status_logs: list[str] = []
            asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return status_logs

        logs = _inner()

        ticket = backlog_store.get_ticket("recurring-lint-cross_run_test_proj")
        self.assertEqual(ticket.status, "done")
        self.assertTrue(any("Ticket für wiederkehrenden Lint-Fund als gelöst geschlossen" in line for line in logs))

    def test_lint_skipped_entirely_does_not_falsely_close_prior_ticket(self):
        # Bugfix-Absicherung: "keine Lint-Funde" (leere Liste) darf NUR schließen, wenn Lint
        # tatsächlich lief (attempted=True) - mock_verifier.check_lint.return_value = [] (wie in
        # den übrigen Tests dieser Datei) simuliert "gar nicht geprüft" und darf NICHT als
        # "Fund behoben" durchgehen.
        backlog_store.upsert_ticket(
            "recurring-lint-cross_run_test_proj", "Alter Lint-Fund", "orchestrator", "blocked",
            detail="ruff:app/main.py:B008", project_slug="cross_run_test_proj",
        )

        result, logs = self._run()

        ticket = backlog_store.get_ticket("recurring-lint-cross_run_test_proj")
        self.assertEqual(ticket.status, "blocked")
        self.assertFalse(any("Lint-Fund als gelöst geschlossen" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
