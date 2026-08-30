"""
tests/test_backlog_worker.py – Testet core/backlog_worker.py (selbstgesteuertes Abarbeiten
des eigenen Backlogs, ohne externen GitHub-Issue-Trigger)

GitHubAgent UND Orchestrator sind hier vollständig gemockt - dasselbe Prinzip wie
tests/test_issue_watcher.py. Gegenstand ist die ORCHESTRIERUNG: welches Ticket wird
aufgegriffen, in welcher Reihenfolge, welcher Sicherheits-Fallback in welchem Fall.
"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import core.backlog_store as backlog_store
from core.backlog_worker import run_backlog_poll_cycle


class TestBacklogWorkerOrchestration(unittest.TestCase):
    def setUp(self):
        self.fake_github = MagicMock()
        self.fake_github.gh_ready.return_value = True
        self.fake_github.get_current_branch.return_value = "main"
        self.fake_github.get_status.return_value = "M app/main.py"
        self.fake_github.scan_for_secrets.return_value = []
        self.fake_github.build_feature_branch_name.return_value = "feat/backlog-ticket-abc123"
        self.fake_github.create_branch.return_value = (True, "branch ok")
        self.fake_github.commit.return_value = (True, "commit ok")
        self.fake_github.push.return_value = (True, "push ok")
        self.fake_github.create_pull_request.return_value = (True, "https://github.com/x/y/pull/9")
        self.fake_github.wait_for_ci_status = AsyncMock(return_value=("no_run", "kein CI im Test"))

        self.fake_orchestrator = MagicMock()
        self.fake_orchestrator.process = AsyncMock(return_value="### Fertig\nAufgabe erledigt.")
        self.fake_orchestrator.last_verification_ok = True
        self.fake_orchestrator.last_needs_human_input = False
        self.fake_orchestrator.last_clarification_questions = []

        self._gh_patcher = patch("core.backlog_worker.GitHubAgent", return_value=self.fake_github)
        self._orch_patcher = patch("core.backlog_worker.Orchestrator", return_value=self.fake_orchestrator)
        self._merge_patcher = patch("core.backlog_worker.check_merged_tickets", return_value=[])
        self._gh_patcher.start()
        self._orch_patcher.start()
        self._merge_patcher.start()
        self.addCleanup(self._gh_patcher.stop)
        self.addCleanup(self._orch_patcher.stop)
        self.addCleanup(self._merge_patcher.stop)

        self.temp_dir = tempfile.mkdtemp()
        self._backlog_patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(self.temp_dir) / "backlog.json")
        self._backlog_patcher.start()
        self.addCleanup(self._backlog_patcher.stop)

    def test_happy_path_picks_up_ready_todo_ticket(self):
        backlog_store.upsert_ticket("cli-1", "Login-Seite bauen", "cli", "todo")
        report = asyncio.run(run_backlog_poll_cycle())

        self.assertEqual(len(report.results), 1)
        self.assertEqual(report.results[0].outcome, "pr_opened")
        self.fake_orchestrator.process.assert_called_once()
        self.assertEqual(self.fake_orchestrator.process.call_args.args[0], "Login-Seite bauen")

        ticket = backlog_store.list_tickets()[0]
        self.assertEqual(ticket.status, "review")

    def test_highest_priority_ticket_is_picked_first(self):
        backlog_store.upsert_ticket("cli-1", "Niedrige Priorität", "cli", "todo", priority=3)
        backlog_store.upsert_ticket("cli-2", "Hohe Priorität", "cli", "todo", priority=1)
        asyncio.run(run_backlog_poll_cycle(max_tickets=1))

        self.fake_orchestrator.process.assert_called_once()
        self.assertEqual(self.fake_orchestrator.process.call_args.args[0], "Hohe Priorität")

    def test_ticket_with_unmet_dependency_is_not_picked_up(self):
        backlog_store.upsert_ticket("cli-0", "Vorher nötig", "cli", "in_progress")
        backlog_store.upsert_ticket("cli-1", "Danach", "cli", "todo", depends_on=["cli-0"])
        report = asyncio.run(run_backlog_poll_cycle())

        self.assertEqual(report.results, [])
        self.assertIn("Kein abhängigkeitsfreies", report.skipped_reason)
        self.fake_orchestrator.process.assert_not_called()

    def test_issue_and_pr_review_sourced_tickets_are_ignored(self):
        # Beide Quellen werden von JEWEILS eigenen, spezialisierten Zyklen verwaltet (siehe
        # Modul-Docstring core/backlog_worker.py) - ein zweiter Aufgreif-Mechanismus für
        # dieselbe Quelle würde Doppelarbeit riskieren.
        backlog_store.upsert_ticket("issue-1", "Aus GitHub-Issue", "issue", "todo")
        backlog_store.upsert_ticket("pr_review-1", "Aus PR-Kommentar", "pr_review", "todo")
        report = asyncio.run(run_backlog_poll_cycle())

        self.assertEqual(report.results, [])
        self.fake_orchestrator.process.assert_not_called()

    def test_wip_limit_blocks_new_work_when_reached(self):
        backlog_store.upsert_ticket("cli-0", "Läuft bereits", "cli", "in_progress")
        backlog_store.upsert_ticket("cli-1", "Wartet", "cli", "todo")

        with patch("core.backlog_worker.BACKLOG_WORKER_WIP_LIMIT", 1):
            report = asyncio.run(run_backlog_poll_cycle())

        self.assertEqual(report.results, [])
        self.assertIn("WIP-Limit", report.skipped_reason)
        self.fake_orchestrator.process.assert_not_called()

    def test_no_diff_reports_no_changes_without_opening_a_pr(self):
        self.fake_github.get_status.return_value = ""
        backlog_store.upsert_ticket("cli-1", "Unklarer Titel", "cli", "todo")
        report = asyncio.run(run_backlog_poll_cycle())

        self.assertEqual(report.results[0].outcome, "no_changes")
        self.fake_github.create_pull_request.assert_not_called()

    def test_secret_finding_blocks_hard_without_any_push(self):
        self.fake_github.scan_for_secrets.return_value = ["AWS_SECRET_ACCESS_KEY=..."]
        backlog_store.upsert_ticket("cli-1", "Ticket", "cli", "todo")
        report = asyncio.run(run_backlog_poll_cycle())

        self.assertEqual(report.results[0].outcome, "blocked_secret")
        self.fake_github.push.assert_not_called()
        ticket = backlog_store.list_tickets()[0]
        self.assertEqual(ticket.status, "blocked")

    def test_open_clarification_question_opens_draft_pr_and_blocks_ticket(self):
        self.fake_orchestrator.last_needs_human_input = True
        self.fake_orchestrator.last_clarification_questions = ["Welches Zahlungssystem soll genutzt werden?"]
        backlog_store.upsert_ticket("cli-1", "Zahlungsabwicklung bauen", "cli", "todo")
        report = asyncio.run(run_backlog_poll_cycle())

        self.assertEqual(report.results[0].outcome, "pr_opened_needs_clarification")
        pr_kwargs = self.fake_github.create_pull_request.call_args.kwargs
        self.assertTrue(pr_kwargs["draft"])
        self.assertIn("Zahlungssystem", pr_kwargs["body"])
        ticket = backlog_store.list_tickets()[0]
        self.assertEqual(ticket.status, "blocked")

    def test_gh_not_ready_skips_cycle_without_crashing(self):
        self.fake_github.gh_ready.return_value = False
        backlog_store.upsert_ticket("cli-1", "Ticket", "cli", "todo")
        report = asyncio.run(run_backlog_poll_cycle())

        self.assertEqual(report.results, [])
        self.assertIn("gh", report.skipped_reason)
        self.fake_orchestrator.process.assert_not_called()

    def test_max_tickets_limits_how_many_are_processed_per_cycle(self):
        backlog_store.upsert_ticket("cli-1", "A", "cli", "todo")
        backlog_store.upsert_ticket("cli-2", "B", "cli", "todo")
        report = asyncio.run(run_backlog_poll_cycle(max_tickets=1))
        self.assertEqual(len(report.results), 1)


if __name__ == "__main__":
    unittest.main()
