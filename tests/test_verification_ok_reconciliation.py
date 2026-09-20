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


class TestBlockingVsInformationalFailures(unittest.TestCase):
    """Roadmap P0-6 (2026-09-20): `failed_checks` mischte blockierende und informative
    Fehlschläge. Bei cachegrid_proxy nannte die Definition of Done deshalb "fehlgeschlagene
    Prüfungen: lint, pre_flight", obwohl allein `pre_flight` blockierte - irreführend genau an
    der Stelle, an der jede spätere Analyse nach dem Grund sucht. In 5 von 6 der letzten Läufe
    stand `lint` in `failed`."""

    def _cachegrid_outcome(self) -> VerificationOutcome:
        outcome = VerificationOutcome()
        outcome.record("lint", False, "ruff: 1 Fund(e)")
        outcome.record("pre_flight", False, "2 Fund(e)")
        outcome.record("tests", True)
        outcome.record("smoke", True)
        return outcome

    def test_blocking_failed_checks_excludes_informational_ones(self):
        outcome = self._cachegrid_outcome()
        self.assertEqual(outcome.failed_checks, ["lint", "pre_flight"])
        self.assertEqual(outcome.blocking_failed_checks, ["pre_flight"])
        self.assertEqual(outcome.informational_failed_checks, ["lint"])

    def test_only_informational_failures_means_no_blocking_failure(self):
        """Ein Lauf, dessen einziger Fehlschlag informativ ist, hat keinen blockierenden Grund -
        genau der Fall von nexus_mesh (`failed: ["lint"]`, Lauf trotzdem grün)."""
        outcome = VerificationOutcome()
        outcome.record("lint", False, "ruff: 1 Fund(e)")
        outcome.record("tests", True)
        self.assertEqual(outcome.blocking_failed_checks, [])
        self.assertTrue(reconcile_verification_ok(outcome, tests_ran=True, tests_passed=True))

    def test_to_dict_reports_both_groups_and_keeps_failed_for_compatibility(self):
        data = self._cachegrid_outcome().to_dict()
        self.assertEqual(data["failed"], ["lint", "pre_flight"])
        self.assertEqual(data["failed_blocking"], ["pre_flight"])
        self.assertEqual(data["failed_informational"], ["lint"])

    def test_round_trip_through_from_dict_preserves_the_split(self):
        restored = VerificationOutcome.from_dict(self._cachegrid_outcome().to_dict())
        self.assertEqual(restored.blocking_failed_checks, ["pre_flight"])
        self.assertEqual(restored.informational_failed_checks, ["lint"])

    def test_blocking_set_matches_the_one_reconciliation_uses(self):
        """Die Einteilung darf nicht an zwei Stellen auseinanderlaufen: beide nutzen jetzt
        dieselbe Definition aus core/verification_outcome.py."""
        from core.verification_outcome import INFORMATIONAL_CHECK_KEYS as core_keys
        self.assertIs(INFORMATIONAL_CHECK_KEYS, core_keys)


if __name__ == "__main__":
    unittest.main()
