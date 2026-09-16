"""
tests/test_verification_ok_reconciliation.py – Testet reconcile_verification_ok()
(agents/orchestrator/verification_checks.py).

Regressionsschutz für den EventForge-Fund (KI-Team-Analyse, Lauf entwickle_eventforge_ein_webhook
20260916_154524): mehrere Fix-Schleifen in verification.py (Vollständigkeit, Coverage,
Frontend-Build) setzten `verification_ok = False` bei jedem fehlschlagenden Versuch, aber nur
die Testsuite-Schleife setzte es nach einem erfolgreichen Fix explizit wieder auf True zurück.
Ein im ersten Versuch fehlgeschlagener, im zweiten Versuch aber behobener Completeness-Fund
ließ `verification_ok` dadurch dauerhaft False bleiben - das `.ai_team_dod.json` zeigte am Ende
`verification_ok: false, detail: "fehlgeschlagene Prüfungen: lint"`, obwohl Lint laut eigener
Dokumentation verification_ok nie beeinflussen soll und der eigentliche (Completeness-)Fund
längst behoben war.
"""

import unittest

from agents.orchestrator.verification_checks import (
    INFORMATIONAL_CHECK_KEYS,
    reconcile_verification_ok,
)
from core.verification_outcome import VerificationOutcome


class TestReconcileVerificationOk(unittest.TestCase):
    def test_resolved_completeness_failure_no_longer_blocks(self):
        """Der zentrale EventForge-Fund: ein zunächst gescheiterter, dann behobener
        Completeness-Check darf den Lauf nicht mehr rot färben - selbst wenn parallel ein
        rein informativer Lint-Fund weiterhin offen ist."""
        outcome = VerificationOutcome()
        # Reihenfolge wie im echten Lauf: Completeness scheitert zuerst ...
        outcome.record("completeness", False, "1 Fund")
        outcome.record("lint", False, "2 Funde")
        # ... wird dann behoben (überschreibt den Eintrag, siehe record()-Docstring) ...
        outcome.record("completeness", True)

        result = reconcile_verification_ok(outcome, tests_ran=True, tests_passed=True)
        self.assertTrue(result)

    def test_informational_only_failure_does_not_block(self):
        outcome = VerificationOutcome()
        outcome.record("lint", False, "2 Funde")
        outcome.record("sast", False, "1 Fund")
        result = reconcile_verification_ok(outcome, tests_ran=True, tests_passed=True)
        self.assertTrue(result)

    def test_unresolved_blocking_failure_still_blocks(self):
        outcome = VerificationOutcome()
        outcome.record("browser_ui", False, "Console-Fehler")
        result = reconcile_verification_ok(outcome, tests_ran=True, tests_passed=True)
        self.assertFalse(result)

    def test_test_regression_is_a_permanent_blocker(self):
        """Test-Schrumpfungs-Veto (siehe core.test_depth.collect_test_function_names): einmal
        erkannt, bleibt es blockierend, selbst wenn alle anderen Checks grün sind."""
        outcome = VerificationOutcome()
        outcome.record("test_regression", False, "1 Test entfernt statt behoben")
        result = reconcile_verification_ok(outcome, tests_ran=True, tests_passed=True)
        self.assertFalse(result)

    def test_no_failures_and_tests_never_ran_returns_none(self):
        """Kein Blocker, aber auch keine bestandene Kern-Testsuite - die aufrufende Stelle soll
        die bisherige Mitschrift unverändert lassen (z.B. weil noch keine Tests liefen)."""
        outcome = VerificationOutcome()
        result = reconcile_verification_ok(outcome, tests_ran=False, tests_passed=False)
        self.assertIsNone(result)

    def test_security_handoff_is_blocking_not_informational(self):
        self.assertNotIn("security_handoff", INFORMATIONAL_CHECK_KEYS)
        outcome = VerificationOutcome()
        outcome.record("security_handoff", False, "SSRF-Fix nicht umgesetzt")
        result = reconcile_verification_ok(outcome, tests_ran=True, tests_passed=True)
        self.assertFalse(result)

    def test_interface_fields_is_informational(self):
        self.assertIn("interface_fields", INFORMATIONAL_CHECK_KEYS)
        outcome = VerificationOutcome()
        outcome.record("interface_fields", False, "1 Fund")
        result = reconcile_verification_ok(outcome, tests_ran=True, tests_passed=True)
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
