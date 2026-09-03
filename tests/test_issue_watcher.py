"""
tests/test_issue_watcher.py – Testet core/issue_watcher.py (autonome, getriggerte Läufe über
GitHub-Issues)

GitHubAgent UND Orchestrator sind hier vollständig gemockt (echte Git-/gh-Interaktion ist
bereits an anderer Stelle abgedeckt: tests/test_github_agent_issue_methods.py für die
Primitiven, tests/test_pr_workflow.py für den echten Branch-Wechsel-Zyklus). Gegenstand
dieser Tests ist die ORCHESTRIERUNG: welche Reihenfolge, welche Labels, welcher
Sicherheits-Fallback in welchem Fall.
"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import core.backlog_store as backlog_store
from core.issue_watcher import run_issue_poll_cycle


def _fake_issue(number=1, title="Health-Check-Endpoint bauen", body="Bitte einen /health Endpoint hinzufügen."):
    return {"number": number, "title": title, "body": body, "labels": [{"name": "ai-team"}]}


class TestIssueWatcherOrchestration(unittest.TestCase):
    def setUp(self):
        self.fake_github = MagicMock()
        self.fake_github.gh_ready.return_value = True
        self.fake_github.list_actionable_issues.return_value = [_fake_issue()]
        self.fake_github.get_current_branch.return_value = "main"
        self.fake_github.get_status.return_value = "M app/main.py"
        self.fake_github.scan_for_secrets.return_value = []
        self.fake_github.build_feature_branch_name.return_value = "feat/health-check-endpoint-abc123"
        self.fake_github.create_branch.return_value = (True, "branch ok")
        self.fake_github.commit.return_value = (True, "commit ok")
        self.fake_github.push.return_value = (True, "push ok")
        self.fake_github.create_pull_request.return_value = (True, "https://github.com/x/y/pull/7")
        self.fake_github.checkout.return_value = (True, "checkout ok")
        # wait_for_ci_status() ist async (siehe agents/github_agent.py) - MagicMock kennt das
        # nicht automatisch, ohne AsyncMock würde `await` mit TypeError fehlschlagen.
        self.fake_github.wait_for_ci_status = AsyncMock(return_value=("no_run", "kein CI im Test"))

        self.fake_orchestrator = MagicMock()
        self.fake_orchestrator.process = AsyncMock(return_value="### Fertig\nHealth-Check gebaut.")
        self.fake_orchestrator.last_verification_ok = True
        # MagicMock generiert JEDES nicht explizit gesetzte Attribut als eigenes (truthy!)
        # Mock-Objekt - ohne diese beiden Zeilen würde core/issue_watcher.py's
        # `getattr(orchestrator, "last_needs_human_input", False)` fälschlich True liefern.
        self.fake_orchestrator.last_needs_human_input = False
        self.fake_orchestrator.last_clarification_questions = []
        # Dasselbe MagicMock-Fallstrick-Problem wie bei last_needs_human_input oben: ohne diese
        # explizite Zuweisung würde core/issue_watcher.py's
        # `getattr(orchestrator, "last_isolated_worktree", None)` ein truthy Mock-Objekt statt
        # None liefern und fälschlich einen (nicht existierenden) Worktree-Merge auslösen.
        self.fake_orchestrator.last_isolated_worktree = None

        self._gh_patcher = patch("core.issue_watcher.GitHubAgent", return_value=self.fake_github)
        self._orch_patcher = patch("core.issue_watcher.Orchestrator", return_value=self.fake_orchestrator)
        self._gh_patcher.start()
        self._orch_patcher.start()
        self.addCleanup(self._gh_patcher.stop)
        self.addCleanup(self._orch_patcher.stop)

        # core/issue_watcher.py schreibt jetzt auch ins Backlog (core/backlog_store.py) -
        # gegen ein temporäres Verzeichnis statt der echten memory/backlog.json, damit
        # Testläufe keine echten Daten hinterlassen (dasselbe Prinzip wie tests/test_cost_history.py).
        self.temp_dir = tempfile.mkdtemp()
        self._backlog_patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(self.temp_dir) / "backlog.json")
        self._backlog_patcher.start()
        self.addCleanup(self._backlog_patcher.stop)

    def test_skips_entirely_when_gh_not_ready(self):
        self.fake_github.gh_ready.return_value = False
        report = asyncio.run(run_issue_poll_cycle())
        self.assertFalse(report.gh_ready)
        self.assertEqual(report.results, [])
        self.fake_github.list_actionable_issues.assert_not_called()

    def test_no_actionable_issues_returns_empty_results(self):
        self.fake_github.list_actionable_issues.return_value = []
        report = asyncio.run(run_issue_poll_cycle())
        self.assertTrue(report.gh_ready)
        self.assertEqual(report.results, [])

    def test_happy_path_opens_pr_and_manages_labels_in_order(self):
        report = asyncio.run(run_issue_poll_cycle())

        self.assertEqual(len(report.results), 1)
        result = report.results[0]
        self.assertEqual(result.outcome, "pr_opened")
        self.assertEqual(result.detail, "https://github.com/x/y/pull/7")

        # in-progress VOR dem Lauf gesetzt (Reihenfolge relevant - siehe Docstring in
        # core/issue_watcher.py: Schutz vor Doppelbearbeitung bei überlappenden Zyklen).
        label_calls = [c.args for c in self.fake_github.add_issue_label.call_args_list]
        self.assertEqual(label_calls[0], (1, "ai-team-in-progress"))
        self.assertIn((1, "ai-team-done"), label_calls)
        self.fake_github.remove_issue_label.assert_any_call(1, "ai-team-in-progress")

        # Feature-Branch angelegt (explizit vom Hauptbranch abgezweigt), gepusht, PR gegen
        # den Hauptbranch geöffnet.
        self.fake_github.create_branch.assert_called_once_with("feat/health-check-endpoint-abc123", base="main")
        self.fake_github.push.assert_called_once_with(branch="feat/health-check-endpoint-abc123")
        pr_kwargs = self.fake_github.create_pull_request.call_args.kwargs
        self.assertEqual(pr_kwargs["base"], "main")
        self.assertEqual(pr_kwargs["head"], "feat/health-check-endpoint-abc123")
        self.assertIn("Closes #1", pr_kwargs["body"])

        # KEIN Zurückwechseln mehr zum Hauptbranch (realer Fund: das hätte gerade erst
        # generierte, nur auf dem Feature-Branch committete Dateien aus dem
        # Arbeitsverzeichnis entfernt) - siehe core/issue_watcher.py.
        self.fake_github.checkout.assert_not_called()
        self.fake_github.comment_on_issue.assert_called_once()
        self.assertIn("https://github.com/x/y/pull/7", self.fake_github.comment_on_issue.call_args[0][1])

        # Backlog-Ticket landet auf "review" (wartet auf Merge), nicht "done".
        tickets = backlog_store.list_tickets()
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0].id, "issue-1")
        self.assertEqual(tickets[0].status, "review")
        self.assertEqual(tickets[0].detail, "https://github.com/x/y/pull/7")

    def test_ticket_is_visible_as_in_progress_before_the_run_finishes(self):
        # Simuliert eine noch laufende Bearbeitung: process() hängt, das Ticket muss trotzdem
        # schon VOR Abschluss im Backlog sichtbar sein (sonst würde ein noch laufendes Issue
        # auf dem Kanban-Board gar nicht auftauchen).
        started = asyncio.Event()

        async def _slow_process(*_args, **_kwargs):
            started.set()
            await asyncio.sleep(3600)  # wird nie fertig - der Test bricht davor ab

        self.fake_orchestrator.process = _slow_process

        async def _run_and_check():
            task = asyncio.ensure_future(run_issue_poll_cycle())
            await started.wait()
            tickets = backlog_store.list_tickets()
            task.cancel()
            return tickets

        tickets = asyncio.run(_run_and_check())
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0].status, "in_progress")

    def test_isolated_worktree_changes_are_merged_back_before_diff_check(self):
        """Bugfix, dieselbe Ursache wie in tests/test_backlog_worker.py.
        test_isolated_worktree_changes_are_merged_back_before_diff_check - siehe dort und
        core/git_isolation.py.copy_worktree_changes_to_target()."""
        fake_worktree = MagicMock(path="/fake/worktree/path", branch="ai-team/fix-abc123")
        self.fake_orchestrator.last_isolated_worktree = fake_worktree

        with patch("core.issue_watcher.copy_worktree_changes_to_target", return_value=["app/main.py"]) as mock_copy, \
             patch("core.issue_watcher.remove_worktree") as mock_remove:
            report = asyncio.run(run_issue_poll_cycle())

        mock_copy.assert_called_once()
        self.assertIs(mock_copy.call_args.args[0], fake_worktree)
        mock_remove.assert_called_once_with(fake_worktree, force=True)
        self.assertEqual(report.results[0].outcome, "pr_opened")

    def test_no_isolated_worktree_skips_merge_step(self):
        with patch("core.issue_watcher.copy_worktree_changes_to_target") as mock_copy, \
             patch("core.issue_watcher.remove_worktree") as mock_remove:
            asyncio.run(run_issue_poll_cycle())

        mock_copy.assert_not_called()
        mock_remove.assert_not_called()

    def test_no_file_changes_skips_branch_creation_and_comments(self):
        self.fake_github.get_status.return_value = ""
        report = asyncio.run(run_issue_poll_cycle())

        self.assertEqual(report.results[0].outcome, "no_changes")
        self.fake_github.create_branch.assert_not_called()
        self.fake_github.remove_issue_label.assert_called_once_with(1, "ai-team-in-progress")
        self.fake_github.add_issue_label.assert_called_once_with(1, "ai-team-in-progress")  # kein "done"

    def test_secret_finding_blocks_hard_without_any_push(self):
        from core.secret_scanner import SecretFinding
        self.fake_github.scan_for_secrets.return_value = [
            SecretFinding(file_path="config.py", line_number=1, rule="AWS Access Key", snippet="***"),
        ]
        report = asyncio.run(run_issue_poll_cycle())

        self.assertEqual(report.results[0].outcome, "blocked_secret")
        self.fake_github.create_branch.assert_not_called()
        self.fake_github.push.assert_not_called()
        self.fake_github.create_pull_request.assert_not_called()
        self.fake_github.add_issue_label.assert_any_call(1, "ai-team-blocked")
        self.assertEqual(backlog_store.list_tickets()[0].status, "blocked")

    def test_failed_verification_still_opens_pr_but_flags_it(self):
        self.fake_orchestrator.last_verification_ok = False
        report = asyncio.run(run_issue_poll_cycle())

        self.assertEqual(report.results[0].outcome, "pr_opened")
        pr_body = self.fake_github.create_pull_request.call_args.kwargs["body"]
        self.assertIn("Verifikation nicht bestanden", pr_body)

    def test_open_clarification_question_opens_draft_pr_and_blocks_ticket(self):
        # Realer Fund: eine mitten in der Aufgabe aufgetretene Rückfrage (core/agent_toolbox.py.
        # ask_human_for_clarification) blieb im autonomen Issue-Watcher-Pfad bisher komplett
        # unsichtbar - anders als im interaktiven CLI-Pfad gibt es hier KEINEN Menschen, der
        # sie im Chat mitliest.
        self.fake_orchestrator.last_needs_human_input = True
        self.fake_orchestrator.last_clarification_questions = ["Welches Zahlungssystem soll genutzt werden?"]
        report = asyncio.run(run_issue_poll_cycle())

        self.assertEqual(report.results[0].outcome, "pr_opened_needs_clarification")
        pr_kwargs = self.fake_github.create_pull_request.call_args.kwargs
        self.assertTrue(pr_kwargs["draft"])
        self.assertIn("Zahlungssystem", pr_kwargs["body"])
        comment_text = self.fake_github.comment_on_issue.call_args.args[1]
        self.assertIn("Zahlungssystem", comment_text)

        tickets = backlog_store.list_tickets()
        self.assertEqual(tickets[0].status, "blocked")

    def test_pr_creation_failure_still_removes_in_progress_and_blocks(self):
        self.fake_github.create_pull_request.return_value = (False, "permission denied")
        report = asyncio.run(run_issue_poll_cycle())

        self.assertEqual(report.results[0].outcome, "error")
        self.fake_github.add_issue_label.assert_any_call(1, "ai-team-blocked")
        self.fake_github.remove_issue_label.assert_any_call(1, "ai-team-in-progress")

    def test_orchestrator_exception_is_caught_and_issue_is_blocked(self):
        self.fake_orchestrator.process = AsyncMock(side_effect=RuntimeError("LLM-Aufruf fehlgeschlagen"))
        report = asyncio.run(run_issue_poll_cycle())

        self.assertEqual(report.results[0].outcome, "error")
        self.assertIn("LLM-Aufruf fehlgeschlagen", report.results[0].detail)
        self.fake_github.add_issue_label.assert_any_call(1, "ai-team-blocked")

    def test_poll_cycle_also_runs_merge_detection_for_existing_review_tickets(self):
        # Ein aus einem FRÜHEREN Zyklus stammendes "review"-Ticket, dessen PR inzwischen
        # gemerged wurde - core/merge_watcher.py.check_merged_tickets() wird vom selben
        # Poll-Zyklus mitgenutzt (kein zusätzlicher Cron-Eintrag nötig).
        backlog_store.upsert_ticket(
            "issue-99", "Älteres Issue", "issue", "review", detail="https://github.com/x/y/pull/99",
        )
        self.fake_github.get_pr_status.return_value = ("merged", "2026-08-21T09:00:00Z")

        report = asyncio.run(run_issue_poll_cycle())

        self.assertEqual(report.merged_ticket_ids, ["issue-99"])
        merged_ticket = next(t for t in backlog_store.list_tickets() if t.id == "issue-99")
        self.assertEqual(merged_ticket.status, "done")

    def test_respects_max_issues_limit(self):
        self.fake_github.list_actionable_issues.return_value = [_fake_issue(1), _fake_issue(2), _fake_issue(3)]
        report = asyncio.run(run_issue_poll_cycle(max_issues=1))
        self.assertEqual(len(report.results), 1)

    def test_failed_ci_after_pr_pulls_ticket_to_blocked_but_keeps_done_label(self):
        """
        Realer Fund: die echte CI-Pipeline wurde nach einem eröffneten PR bisher gar nicht
        geprüft - anders als interface/cli.py._ask_for_git_push() (interaktiver Pfad).
        """
        self.fake_github.wait_for_ci_status = AsyncMock(return_value=("failed", "1 Job fehlgeschlagen"))
        report = asyncio.run(run_issue_poll_cycle())

        self.assertEqual(report.results[0].outcome, "pr_opened_ci_failed")
        # Label bleibt "ai-team-done" (ein PR WURDE eröffnet - das Label beschreibt genau das).
        self.fake_github.add_issue_label.assert_any_call(1, "ai-team-done")
        self.assertIn("CI-Pipeline ist fehlgeschlagen", self.fake_github.comment_on_issue.call_args[0][1])
        self.assertEqual(backlog_store.list_tickets()[0].status, "blocked")

    def test_passed_ci_after_pr_keeps_review_status(self):
        self.fake_github.wait_for_ci_status = AsyncMock(return_value=("passed", "https://x/y"))
        report = asyncio.run(run_issue_poll_cycle())

        self.assertEqual(report.results[0].outcome, "pr_opened")
        self.assertEqual(backlog_store.list_tickets()[0].status, "review")
        self.assertIn("CI grün", self.fake_github.comment_on_issue.call_args[0][1])

    @patch("core.issue_watcher.notify_external")
    def test_non_success_outcome_triggers_external_notification(self, mock_notify):
        self.fake_github.get_status.return_value = ""  # -> outcome "no_changes"
        asyncio.run(run_issue_poll_cycle())
        mock_notify.assert_called_once()
        self.assertIn("#1", mock_notify.call_args[0][1])

    @patch("core.issue_watcher.notify_external")
    def test_pr_opened_outcome_does_not_notify(self, mock_notify):
        asyncio.run(run_issue_poll_cycle())
        mock_notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
