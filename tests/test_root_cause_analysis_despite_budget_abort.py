"""
tests/test_root_cause_analysis_despite_budget_abort.py – Testet
Orchestrator._root_cause_analysis_worthwhile_despite_budget_abort() (agents/orchestrator/
retrospective.py).

Realer Fund (sentinel_shield-Projekt, 2026-09-22): der Lauf scheiterte an zwei echten,
über zwei Fix-Versuche hinweg unveränderten Testfehlern (mock-Objekt lieferte nach dem ersten
Fehlschlag bei jedem weiteren Aufruf denselben `httpx.ConnectError`, ein Interface-Mismatch
`TokenBucketRateLimiter.clients`), erreichte dabei aber `MAX_RUN_TOKENS` und landete deshalb im
`if budget_aborted:`-Zweig von Orchestrator.process(). Dort lief bisher NUR die Provider-
Erschöpfungs-Behandlung, nicht core/root_cause_analyst.py - der wertvolle Befund tauchte in
keinem Backlog-Ticket auf, obwohl der Postmortem ihn im Rohlog längst dokumentiert hatte.
"""

import unittest

from agents.orchestrator import Orchestrator


class TestRootCauseAnalysisDespiteBudgetAbort(unittest.TestCase):
    def test_runs_when_real_test_failures_caused_the_budget_abort(self):
        self.assertTrue(
            Orchestrator._root_cause_analysis_worthwhile_despite_budget_abort(
                provider_exhausted_this_run=False,
                verification_summary="2 Testfehler nach zwei Fix-Versuchen unverändert",
                verification_ok=False,
            )
        )

    def test_skipped_when_the_run_only_failed_on_provider_exhaustion(self):
        """Ein weiterer LLM-Aufruf würde hier nur am selben, gerade erschöpften Kontingent
        scheitern - reine Tokenverschwendung ohne Erkenntnisgewinn (siehe infrastructure_blocker-
        Lesson direkt oberhalb dieses Zweigs)."""
        self.assertFalse(
            Orchestrator._root_cause_analysis_worthwhile_despite_budget_abort(
                provider_exhausted_this_run=True,
                verification_summary="Alle Agenten scheiterten an 429/RESOURCE_EXHAUSTED",
                verification_ok=False,
            )
        )

    def test_skipped_when_verification_actually_passed(self):
        self.assertFalse(
            Orchestrator._root_cause_analysis_worthwhile_despite_budget_abort(
                provider_exhausted_this_run=False,
                verification_summary="Alle Prüfungen bestanden",
                verification_ok=True,
            )
        )

    def test_skipped_when_verification_never_ran(self):
        self.assertFalse(
            Orchestrator._root_cause_analysis_worthwhile_despite_budget_abort(
                provider_exhausted_this_run=False,
                verification_summary="",
                verification_ok=False,
            )
        )


if __name__ == "__main__":
    unittest.main()
