"""
tests/test_budget_aborted_after_verification_ok.py – Testet die budget_aborted/verification_ok-
Inkonsistenz aus dem HyperionSentinel-Analysebericht (2026-09-13).

Realer Fund: `run_closed` meldete gleichzeitig `verification_ok: true` UND
`budget_aborted: true`. Ursache: der Resilienz-Puffer (`_run_budget_within_confirmation_
buffer`, agents/orchestrator/budget.py) erlaubt genau EINEN letzten Testlauf, auch wenn das
harte Lauf-Budget knapp (< 10%) überschritten ist - besteht dieser Testlauf, wird
verification_ok = True gesetzt. Eine NACHGELAGERTE, rein optionale Prüfung (hier: der
Vollständigkeits-Check) prüft das Budget aber ERNEUT und setzte budget_aborted bisher
unbedingt auf True, weil dieselbe Tokenüberschreitung natürlich immer noch besteht - der Lauf
galt dadurch fälschlich als abgebrochen, obwohl die Kern-Testsuite bereits bestätigt grün war.
agents/orchestrator/verification.py._run_verification_loop() muss budget_aborted deshalb
zurücksetzen, wenn verification_ok am Ende der Schleife noch True ist.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

import agents.orchestrator.budget as orch_budget_module
from agents.orchestrator import Orchestrator
from core.message_bus import AgentResult
from core.token_guard import TokenGuard
from core.verifier import VerificationReport
from core.workspace import WorkspaceManager


class TestBudgetNotAbortedAfterConfirmedVerification(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        self.orchestrator.last_project_slug = "budget_confirmation_proj"

        # Frischer, isolierter Token-Zähler statt des globalen Singletons (siehe
        # tests/test_run_budget_cap.py) - direkt auf einen Stand GERINGFÜGIG (< 10%) über
        # einem kleinen MAX_RUN_TOKENS gesetzt, damit sowohl _run_budget_exceeded() als auch
        # _run_budget_within_confirmation_buffer() für den kompletten Testlauf konstant True
        # bleiben (kein reales Token-Aufzeichnen durch Agenten-Aufrufe nötig).
        self._fresh_guard = TokenGuard()
        self._fresh_guard.record_usage("fake-model", 10_400, 0)  # 10.400 von 10.000 = +4%
        guard_patch = patch.object(orch_budget_module, "token_guard", self._fresh_guard)
        guard_patch.start()
        self.addCleanup(guard_patch.stop)

        max_run_tokens_patch = patch.object(orch_budget_module, "MAX_RUN_TOKENS", 10_000)
        max_run_tokens_patch.start()
        self.addCleanup(max_run_tokens_patch.stop)

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def test_completeness_check_hitting_budget_does_not_override_confirmed_verification_ok(self):
        passed_report = VerificationReport(
            ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
        )
        backend_result = AgentResult(task_id="t1", agent_id="backend", agent_name="Backend", success=True, content="ok")

        with patch("agents.orchestrator.verification.ProjectVerifier") as mock_verifier_cls:
            mock_verifier = mock_verifier_cls.return_value
            # Kern-Testsuite besteht direkt im ersten Versuch (Resilienz-Puffer greift, siehe
            # oben) -> verification_ok wird True, OHNE dass budget_aborted dabei gesetzt wird.
            mock_verifier.run_tests.return_value = passed_report
            # Alle unbedingt (unabhängig vom Budget) ausgeführten, rein informativen Checks
            # VOR dem Vollständigkeits-Check bewusst als "nicht durchgeführt" mocken, damit sie
            # in dieser isolierten Testumgebung keine echten `docker`/`npm`/`pip-audit`-
            # Unterprozesse starten.
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_frontend_build.return_value = []
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_sast.return_value = []
            mock_verifier.check_licenses.return_value = []
            mock_verifier.check_lint.return_value = []
            # Der Vollständigkeits-Check ist die erste Prüfung NACH der bestandenen
            # Kern-Testsuite, die das (weiterhin überschrittene) Budget selbst erneut abfragt -
            # genau hier trat der reale Bug auf: die erste Schleifen-Iteration bricht schon VOR
            # dem eigentlichen Check wegen des Budgets ab (siehe agents/orchestrator/
            # verification.py, Zeile ~2172ff.).
            mock_verifier.check_runtime_smoke.return_value.attempted = False
            mock_verifier.check_browser_ui.return_value.attempted = False
            mock_verifier.check_accessibility.return_value.attempted = False

            results, summary, budget_aborted, manually_cancelled, verification_ok = asyncio.run(
                self.orchestrator._run_verification_loop(
                    project_dir=self.temp_workspace,
                    all_results=[backend_result],
                    file_owners={},
                    run_start_tokens=0,
                    notify=lambda msg: None,
                )
            )

        self.assertTrue(verification_ok)
        self.assertFalse(
            budget_aborted,
            "budget_aborted darf nicht True bleiben, wenn die Kern-Testsuite bereits über den "
            "Resilienz-Puffer erfolgreich bestätigt wurde (verification_ok == True).",
        )
        self.assertFalse(manually_cancelled)
        self.assertIn("optionale Prüfungen wurden übersprungen", summary)


if __name__ == "__main__":
    unittest.main()
