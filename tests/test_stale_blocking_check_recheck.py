"""
tests/test_stale_blocking_check_recheck.py – Neu-Messung blockierender Prüfungen am Laufende

Realer Fund (Roadmap P0-2/P0-3, 2026-09-20): `pre_flight` und `security_handoff` laufen früh im
Lauf, blockieren `verification_ok` hart und wurden danach nie wieder ausgewertet - auch dann
nicht, wenn spätere Fix-Runden die Ursache längst behoben hatten.

* `cachegrid_proxy` (20260919_012548) endete mit `failed: ["lint", "pre_flight"]`;
  `run_pre_flight_check()` gegen denselben Projektstand liefert heute `passed=True`.
* `aegisflow` (20260918_210427) endete mit `failed: ["lint", "security_handoff"]`, obwohl die
  Testsuite grün war - das Handoff-Veto blieb vom Schleifenanfang stehen.

`VerificationMixin._recheck_stale_blocking_checks()` misst beide am Ende erneut und zeichnet ein
inzwischen bestandenes Ergebnis neu auf. Ein weiterhin fehlschlagender Check bleibt unverändert
auf `failed` - die Neu-Messung darf ein echtes Veto nie verschlucken.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.pre_flight_check import PreFlightIssue, PreFlightReport
from core.verification_outcome import VerificationOutcome


def _clean_pre_flight() -> PreFlightReport:
    return PreFlightReport(project_dir="dummy", files_checked=3, issues=[])


def _failing_pre_flight() -> PreFlightReport:
    return PreFlightReport(
        project_dir="dummy",
        files_checked=3,
        issues=[PreFlightIssue(
            file="app/main.py", line=3, issue_type="missing_dependency",
            message="Paket `httpx` wird importiert, fehlt aber in requirements.txt.",
            suggestion="Füge `httpx` zu requirements.txt hinzu.",
        )],
    )


class TestStaleBlockingCheckRecheck(unittest.TestCase):
    def setUp(self):
        self.orchestrator = Orchestrator()
        self.outcome = VerificationOutcome()
        self.summary: list[str] = []
        self.logs: list[str] = []

    def _recheck(self):
        asyncio.run(self.orchestrator._recheck_stale_blocking_checks(
            "dummy_project", self.outcome, self.summary, self.logs.append,
        ))

    # ── pre_flight ────────────────────────────────────────────────────────────────────────

    @patch("agents.orchestrator.verification.unmet_requirements", return_value=[])
    @patch("agents.orchestrator.verification.run_pre_flight_check")
    def test_pre_flight_repaired_by_later_fix_rounds_is_recorded_as_passed(self, mock_pre_flight, _unmet):
        """cachegrid_proxy: 2 Funde vor der Testsuite, Circuit-Breaker-Abbruch, danach durch die
        Testsuite-Fix-Runde behoben - das Ergebnis blieb trotzdem veraltet auf `failed`."""
        self.outcome.record("pre_flight", False, "2 Fund(e)")
        mock_pre_flight.return_value = _clean_pre_flight()

        self._recheck()

        self.assertTrue(self.outcome.status("pre_flight"))
        self.assertNotIn("pre_flight", self.outcome.failed_checks)
        self.assertTrue(any("Pre-Flight-Check" in line for line in self.summary))

    @patch("agents.orchestrator.verification.unmet_requirements", return_value=[])
    @patch("agents.orchestrator.verification.run_pre_flight_check")
    def test_pre_flight_still_failing_stays_failed(self, mock_pre_flight, _unmet):
        """Gegenprobe: ein echter, weiterhin offener Fund darf nicht weggemessen werden."""
        self.outcome.record("pre_flight", False, "1 Fund(e)")
        mock_pre_flight.return_value = _failing_pre_flight()

        self._recheck()

        self.assertFalse(self.outcome.status("pre_flight"))
        self.assertIn("pre_flight", self.outcome.failed_checks)

    @patch("agents.orchestrator.verification.unmet_requirements", return_value=[])
    @patch("agents.orchestrator.verification.run_pre_flight_check")
    def test_passed_pre_flight_is_not_measured_again(self, mock_pre_flight, _unmet):
        """Nur ein FEHLGESCHLAGENER Check wird neu gemessen - ein bestandener kostet keinen
        zweiten Durchlauf über alle Projektdateien."""
        self.outcome.record("pre_flight", True, "")

        self._recheck()

        mock_pre_flight.assert_not_called()
        self.assertTrue(self.outcome.status("pre_flight"))

    @patch("agents.orchestrator.verification.unmet_requirements", return_value=[])
    @patch("agents.orchestrator.verification.run_pre_flight_check", side_effect=OSError("Projektverzeichnis weg"))
    def test_pre_flight_recheck_error_leaves_outcome_untouched(self, _pre_flight, _unmet):
        """Die Neu-Messung ist eine Korrektur, kein Gate - ein Fehler darf den Lauf nicht
        abbrechen und das bisherige Ergebnis nicht verfälschen."""
        self.outcome.record("pre_flight", False, "1 Fund(e)")

        self._recheck()

        self.assertFalse(self.outcome.status("pre_flight"))

    # ── security_handoff ──────────────────────────────────────────────────────────────────

    @patch("agents.orchestrator.verification.run_pre_flight_check", return_value=_clean_pre_flight())
    @patch("agents.orchestrator.verification.unmet_requirements", return_value=[])
    def test_security_handoff_fulfilled_in_the_meantime_is_recorded_as_passed(self, _unmet, _pre_flight):
        """aegisflow: das Veto stammte vom Schleifenanfang; spätere Fix-Runden erfüllten die
        Anforderung, ohne dass sie je erneut geprüft wurde."""
        self.outcome.record("security_handoff", False, "1 Anforderung(en)")
        self.orchestrator._security_unmet_requirements = [("security", "`backend` muss X beheben.")]

        self._recheck()

        self.assertTrue(self.outcome.status("security_handoff"))
        self.assertEqual(self.orchestrator._security_unmet_requirements, [])
        self.assertTrue(any("Sicherheits-Übergabe" in line for line in self.summary))

    @patch("agents.orchestrator.verification.run_pre_flight_check", return_value=_clean_pre_flight())
    @patch("agents.orchestrator.verification.unmet_requirements")
    def test_security_handoff_still_open_stays_failed(self, mock_unmet, _pre_flight):
        """Gegenprobe: eine weiterhin unerfüllte Anforderung des security-Agenten bleibt ein
        Veto (realer Fund aegisflow: `POST /api/v1/dlq/replay` existiert wirklich nicht)."""
        self.outcome.record("security_handoff", False, "1 Anforderung(en)")
        mock_unmet.return_value = [("security", "`POST /api/v1/dlq/replay` registrieren.")]

        self._recheck()

        self.assertFalse(self.outcome.status("security_handoff"))
        self.assertEqual(len(self.orchestrator._security_unmet_requirements), 1)

    @patch("agents.orchestrator.verification.run_pre_flight_check", return_value=_clean_pre_flight())
    @patch("agents.orchestrator.verification.unmet_requirements")
    def test_open_requirement_of_another_role_does_not_block_security_handoff(self, mock_unmet, _pre_flight):
        """Nur Anforderungen des `security`-Agenten bilden das `security_handoff`-Veto - die
        eines anderen Kollegen (hier `resilience_guard`) bleiben informativ."""
        self.outcome.record("security_handoff", False, "1 Anforderung(en)")
        mock_unmet.return_value = [("resilience_guard", "`backend` muss den CircuitBreaker einbinden.")]

        self._recheck()

        self.assertTrue(self.outcome.status("security_handoff"))


if __name__ == "__main__":
    unittest.main()
