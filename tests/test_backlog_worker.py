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
import core.backlog_worker as backlog_worker
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
        # Dasselbe MagicMock-Fallstrick wie bei last_needs_human_input: ohne diese explizite
        # Zuweisung würde core/backlog_worker.py's
        # `getattr(orchestrator, "last_isolated_worktree", None)` ein truthy Mock-Objekt statt
        # None liefern und fälschlich einen (nicht existierenden) Worktree-Merge auslösen.
        self.fake_orchestrator.last_isolated_worktree = None

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


class TestGovernanceTicketRetryPool(unittest.TestCase):
    """
    Team-Optimierung (Retrospektive 2026-09-03): ein von agents/orchestrator/verification.py
    für einen ungelösten kritischen Befund eröffnetes "blocked"-Ticket (source="orchestrator")
    fiel bisher durch JEDES Filter dieses Pollers - `_governance_retry_pool()` macht es bis zu
    MAX_GOVERNANCE_TICKET_RETRIES-mal wieder aufgreifbar. Dasselbe Mock-Setup wie
    TestBacklogWorkerOrchestration oben.
    """

    def setUp(self):
        self.fake_github = MagicMock()
        self.fake_github.gh_ready.return_value = True
        self.fake_github.get_current_branch.return_value = "main"
        self.fake_github.get_status.return_value = "M app/middleware.py"
        self.fake_github.scan_for_secrets.return_value = []
        self.fake_github.build_feature_branch_name.return_value = "feat/backlog-ticket-abc123"
        self.fake_github.create_branch.return_value = (True, "branch ok")
        self.fake_github.commit.return_value = (True, "commit ok")
        self.fake_github.push.return_value = (True, "push ok")
        self.fake_github.create_pull_request.return_value = (True, "https://github.com/x/y/pull/9")
        self.fake_github.wait_for_ci_status = AsyncMock(return_value=("no_run", "kein CI im Test"))

        self.fake_orchestrator = MagicMock()
        self.fake_orchestrator.process = AsyncMock(return_value="### Fertig\nBehoben.")
        self.fake_orchestrator.last_verification_ok = True
        self.fake_orchestrator.last_needs_human_input = False
        self.fake_orchestrator.last_clarification_questions = []
        # Dasselbe MagicMock-Fallstrick wie bei last_needs_human_input: ohne diese explizite
        # Zuweisung würde core/backlog_worker.py's
        # `getattr(orchestrator, "last_isolated_worktree", None)` ein truthy Mock-Objekt statt
        # None liefern und fälschlich einen (nicht existierenden) Worktree-Merge auslösen.
        self.fake_orchestrator.last_isolated_worktree = None

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

    def test_blocked_governance_ticket_is_picked_up_and_retries_incremented(self):
        backlog_store.upsert_ticket(
            "unresolved-governance-critical-mockforge", "Ungelöster kritischer Governance-Befund",
            "orchestrator", "blocked", project_slug="mockforge", detail="DB-Session pro Request",
        )
        report = asyncio.run(run_backlog_poll_cycle())

        self.assertEqual(len(report.results), 1)
        self.fake_orchestrator.process.assert_awaited_once()
        ticket = backlog_store.get_ticket("unresolved-governance-critical-mockforge")
        self.assertEqual(ticket.retries, 1)

    def test_governance_ticket_detail_is_forwarded_to_orchestrator_as_task_text(self):
        backlog_store.upsert_ticket(
            "unresolved-governance-critical-mockforge", "Ungelöster kritischer Governance-Befund",
            "orchestrator", "blocked", project_slug="mockforge", detail="DB-Session pro Request in ProxyMiddleware",
        )
        asyncio.run(run_backlog_poll_cycle())

        task_text = self.fake_orchestrator.process.call_args.args[0]
        self.assertIn("DB-Session pro Request in ProxyMiddleware", task_text)

    def test_blocked_governance_ticket_still_blocked_keeps_retry_count_after_failed_retry(self):
        self.fake_github.get_status.return_value = ""  # keine Änderung -> "no_changes" -> bleibt "blocked"
        backlog_store.upsert_ticket(
            "unresolved-governance-critical-mockforge", "Ungelöster kritischer Governance-Befund",
            "orchestrator", "blocked", project_slug="mockforge", detail="...",
        )
        asyncio.run(run_backlog_poll_cycle())
        ticket = backlog_store.get_ticket("unresolved-governance-critical-mockforge")
        self.assertEqual(ticket.status, "blocked")
        self.assertEqual(ticket.retries, 1)

    def test_first_governance_retry_does_not_escalate_model(self):
        # Team-Optimierung (Retrospektive 2026-09-04): retries=0 beim Aufgreifen (Standardwert
        # eines frisch eröffneten Tickets) ist der ERSTE automatische Backlog-Retry - noch kein
        # Grund, das Modell hochzustufen.
        backlog_store.upsert_ticket(
            "unresolved-governance-critical-mockforge", "Ungelöster kritischer Governance-Befund",
            "orchestrator", "blocked", project_slug="mockforge", detail="...", retries=0,
        )
        asyncio.run(run_backlog_poll_cycle())

        backlog_worker.Orchestrator.assert_called_once_with(escalate_models=False)

    def test_second_governance_retry_escalates_model(self):
        # Team-Optimierung (Retrospektive 2026-09-04): real beobachtet - fast jedes zuletzt
        # bearbeitete Projekt blieb nach den ersten Fixversuchen rot und ein automatischer
        # Backlog-Retry griff DANACH mit exakt demselben Modell erneut (erfolglos) an. Ab
        # retries>=1 (schon mindestens ein Backlog-Retry gescheitert) wird jetzt eskaliert.
        backlog_store.upsert_ticket(
            "unresolved-governance-critical-mockforge", "Ungelöster kritischer Governance-Befund",
            "orchestrator", "blocked", project_slug="mockforge", detail="...", retries=1,
        )
        asyncio.run(run_backlog_poll_cycle())

        backlog_worker.Orchestrator.assert_called_once_with(escalate_models=True)

    def test_regular_todo_ticket_never_escalates_model(self):
        backlog_store.upsert_ticket("cli-1", "Login-Seite bauen", "cli", "todo")
        asyncio.run(run_backlog_poll_cycle())

        backlog_worker.Orchestrator.assert_called_once_with(escalate_models=False)

    def test_governance_ticket_exhausted_after_max_retries_is_no_longer_picked_up(self):
        from config import MAX_GOVERNANCE_TICKET_RETRIES
        backlog_store.upsert_ticket(
            "unresolved-governance-critical-mockforge", "Ungelöster kritischer Governance-Befund",
            "orchestrator", "blocked", project_slug="mockforge", detail="...",
            retries=MAX_GOVERNANCE_TICKET_RETRIES,
        )
        report = asyncio.run(run_backlog_poll_cycle())

        self.assertEqual(report.results, [])
        self.fake_orchestrator.process.assert_not_called()
        ticket = backlog_store.get_ticket("unresolved-governance-critical-mockforge")
        self.assertEqual(ticket.retries, MAX_GOVERNANCE_TICKET_RETRIES)  # unverändert

    def test_manually_blocked_non_governance_ticket_is_not_touched(self):
        # Ein Ticket, das ein MENSCH bewusst als "blocked" markiert hat (z.B. wartet auf eine
        # externe Entscheidung) - source/ID passen nicht auf das Governance-Retry-Muster und
        # dürfen deshalb NICHT automatisch erneut aufgegriffen werden.
        backlog_store.upsert_ticket("cli-42", "Wartet auf Kundenentscheidung", "cli", "blocked")
        report = asyncio.run(run_backlog_poll_cycle())

        self.assertEqual(report.results, [])
        self.fake_orchestrator.process.assert_not_called()

    def test_recurring_failure_ticket_is_picked_up_and_retries_incremented(self):
        # Team-Optimierung (Retrospektive, 2026-09-04): "recurring-failure-" (echte Testfehler,
        # die trotz Fixversuchen bestehen blieben, agents/orchestrator/verification.py) fehlte
        # ursprünglich im Retry-Muster - dieselbe Sackgasse wie einst bei den
        # "unresolved-..."-Tickets, nur für eine andere Ticket-Kategorie.
        backlog_store.upsert_ticket(
            "recurring-failure-mockforge", "Nicht behobener Verifikations-Fehler",
            "orchestrator", "blocked", project_slug="mockforge", detail="1 echter Testfehler",
        )
        report = asyncio.run(run_backlog_poll_cycle())

        self.fake_orchestrator.process.assert_called_once()
        self.assertEqual(len(report.results), 1)
        ticket = backlog_store.get_ticket("recurring-failure-mockforge")
        self.assertEqual(ticket.retries, 1)

    def test_recurring_lint_ticket_is_picked_up_and_retries_incremented(self):
        backlog_store.upsert_ticket(
            "recurring-lint-mockforge", "Wiederkehrender Lint-Fund",
            "orchestrator", "blocked", project_slug="mockforge", detail="ruff:app/main.py:B008",
        )
        report = asyncio.run(run_backlog_poll_cycle())

        self.fake_orchestrator.process.assert_called_once()
        self.assertEqual(len(report.results), 1)
        ticket = backlog_store.get_ticket("recurring-lint-mockforge")
        self.assertEqual(ticket.retries, 1)

    def test_unrelated_recurring_prefix_is_not_retried(self):
        # Nur die vier bekannten Präfixe werden erneut aufgegriffen - ein generisches "jedes
        # 'recurring-*'-Ticket erneut versuchen" würde auch ein Ticket treffen, das kein
        # Orchestrator-Fix-Loop-Muster ist (Absicherung gegen zu breite Übernahme).
        backlog_store.upsert_ticket(
            "recurring-something-else-mockforge", "Anderes Muster", "orchestrator", "blocked",
            project_slug="mockforge", detail="...",
        )
        report = asyncio.run(run_backlog_poll_cycle())

        self.assertEqual(report.results, [])
        self.fake_orchestrator.process.assert_not_called()

    def test_isolated_worktree_changes_are_merged_back_before_diff_check(self):
        """
        Bugfix (Team-Optimierung, real beobachtet in einem echten mockforge-Governance-Retry-
        Lauf): der Orchestrator isoliert JEDEN Lauf gegen ein bereits bestehendes Workspace-
        Projekt in einem separaten Git-Worktree (agents/orchestrator/__init__.py.
        _resolve_project_isolation) - ohne die Übertragung in core/backlog_worker.py sah
        github_agent.get_status() (läuft immer gegen BASE_DIR) das NIE, selbst wenn der
        Fix-Agent die Datei nachweislich korrekt bearbeitet hatte (echtes Ergebnis: "no_changes"
        trotz erfolgter Arbeit). Siehe core/git_isolation.py.copy_worktree_changes_to_target().
        """
        fake_worktree = MagicMock(path="/fake/worktree/path", branch="ai-team/fix-abc123")
        self.fake_orchestrator.last_isolated_worktree = fake_worktree
        backlog_store.upsert_ticket(
            "unresolved-governance-critical-mockforge", "Ungelöster kritischer Governance-Befund",
            "orchestrator", "blocked", project_slug="mockforge", detail="DB-Session pro Request",
        )

        with patch("core.backlog_worker.copy_worktree_changes_to_target", return_value=["app/middleware.py"]) as mock_copy, \
             patch("core.backlog_worker.remove_worktree") as mock_remove:
            report = asyncio.run(run_backlog_poll_cycle())

        mock_copy.assert_called_once()
        self.assertIs(mock_copy.call_args.args[0], fake_worktree)
        mock_remove.assert_called_once_with(fake_worktree, force=True)
        self.assertEqual(len(report.results), 1)
        self.assertEqual(report.results[0].outcome, "pr_opened")

    def test_no_isolated_worktree_skips_merge_step(self):
        backlog_store.upsert_ticket("cli-1", "Login-Seite bauen", "cli", "todo")

        with patch("core.backlog_worker.copy_worktree_changes_to_target") as mock_copy, \
             patch("core.backlog_worker.remove_worktree") as mock_remove:
            asyncio.run(run_backlog_poll_cycle())

        mock_copy.assert_not_called()
        mock_remove.assert_not_called()

    def test_falls_back_to_current_branch_when_project_missing_from_protected_branch(self):
        """
        Realer Fund: `git checkout -b <feature> main` scheiterte real mit "Your local changes
        ... would be overwritten by checkout", weil das mockforge-Projekt nur auf dem aktuell
        ausgecheckten (langlebigen Feature-)Branch existierte, nicht auf main. Ein Fallback
        auf original_branch als Basis vermeidet den Konflikt strukturell.
        """
        self.fake_github.get_current_branch.return_value = "feat/some-long-lived-branch"
        self.fake_github.path_exists_in_branch.return_value = False  # existiert NICHT auf main
        self.fake_orchestrator.last_project_slug = "mockforge"
        backlog_store.upsert_ticket(
            "unresolved-governance-critical-mockforge", "Ungelöster kritischer Governance-Befund",
            "orchestrator", "blocked", project_slug="mockforge", detail="...",
        )

        asyncio.run(run_backlog_poll_cycle())

        self.fake_github.path_exists_in_branch.assert_called_once_with("main", "workspace/mockforge")
        self.fake_github.create_branch.assert_called_once_with(
            "feat/backlog-ticket-abc123", base="feat/some-long-lived-branch",
        )

    def test_keeps_protected_branch_as_base_when_project_exists_there_too(self):
        self.fake_github.get_current_branch.return_value = "feat/some-long-lived-branch"
        self.fake_github.path_exists_in_branch.return_value = True  # existiert auch auf main
        self.fake_orchestrator.last_project_slug = "mockforge"
        backlog_store.upsert_ticket(
            "unresolved-governance-critical-mockforge", "Ungelöster kritischer Governance-Befund",
            "orchestrator", "blocked", project_slug="mockforge", detail="...",
        )

        asyncio.run(run_backlog_poll_cycle())

        self.fake_github.create_branch.assert_called_once_with("feat/backlog-ticket-abc123", base="main")

    def test_project_slug_survives_across_two_poll_cycles_of_the_same_governance_ticket(self):
        # Regressionstest für den realen mockforge-Fund: der ERSTE Zyklus scheitert (kein
        # Diff -> "no_changes"/"blocked"), project_slug MUSS trotzdem für den ZWEITEN Zyklus
        # erhalten bleiben, sonst würde forced_project_dir in _process_single_ticket() beim
        # zweiten Versuch nicht mehr greifen (siehe core/backlog_store.py-Bugfix).
        self.fake_github.get_status.return_value = ""  # -> "no_changes" im 1. Zyklus
        backlog_store.upsert_ticket(
            "unresolved-governance-critical-mockforge", "Ungelöster kritischer Governance-Befund",
            "orchestrator", "blocked", project_slug="mockforge", detail="...",
        )
        asyncio.run(run_backlog_poll_cycle())
        ticket_after_first_cycle = backlog_store.get_ticket("unresolved-governance-critical-mockforge")
        self.assertEqual(ticket_after_first_cycle.project_slug, "mockforge")

        asyncio.run(run_backlog_poll_cycle())
        ticket_after_second_cycle = backlog_store.get_ticket("unresolved-governance-critical-mockforge")
        self.assertEqual(ticket_after_second_cycle.project_slug, "mockforge")
        self.assertEqual(ticket_after_second_cycle.retries, 2)

    def test_regular_todo_ticket_is_preferred_over_governance_retry_at_equal_priority(self):
        backlog_store.upsert_ticket(
            "unresolved-governance-critical-mockforge", "Ungelöster kritischer Governance-Befund",
            "orchestrator", "blocked", project_slug="mockforge", detail="...",
        )
        backlog_store.upsert_ticket("cli-1", "Reguläres Ticket", "cli", "todo")
        report = asyncio.run(run_backlog_poll_cycle(max_tickets=1))

        self.assertEqual(len(report.results), 1)
        self.assertEqual(report.results[0].ticket_id, "cli-1")


if __name__ == "__main__":
    unittest.main()
