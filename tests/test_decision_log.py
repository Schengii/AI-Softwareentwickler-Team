"""
tests/test_decision_log.py – Testet core/decision_log.py (Punkt 5 einer Team-Retrospektive):
live, strukturiertes Protokoll der wesentlichen Orchestrator-Entscheidungen INNERHALB eines
Laufs, lesbar noch während der Lauf läuft, statt erst aus dem Abschlussbericht rekonstruierbar.
"""

import tempfile
import unittest

from core.decision_log import log_decision, read_decisions


class TestDecisionLog(unittest.TestCase):
    def test_read_without_any_logged_decision_returns_empty(self):
        with tempfile.TemporaryDirectory() as project_dir:
            self.assertEqual(read_decisions(project_dir), [])

    def test_log_then_read_roundtrip_newest_first(self):
        with tempfile.TemporaryDirectory() as project_dir:
            log_decision(project_dir, "governance_fix_dispatched", "erster Eintrag")
            log_decision(project_dir, "budget_or_cancel_aborted", "zweiter Eintrag")

            decisions = read_decisions(project_dir)
            self.assertEqual(len(decisions), 2)
            self.assertEqual(decisions[0]["event"], "budget_or_cancel_aborted")
            self.assertEqual(decisions[1]["event"], "governance_fix_dispatched")

    def test_extra_fields_are_preserved(self):
        with tempfile.TemporaryDirectory() as project_dir:
            log_decision(project_dir, "architect_forced_reescalation", "Kontext", agents=["backend"])
            decisions = read_decisions(project_dir)
            self.assertEqual(decisions[0]["agents"], ["backend"])

    def test_log_decision_never_raises_on_nonexistent_project_dir(self):
        # project_dir, das nicht angelegt werden kann - log_decision() ist best-effort und darf
        # einen laufenden Team-Lauf nie zum Absturz bringen.
        try:
            log_decision("Z:\\definitiv\\nicht\\vorhanden", "event", "detail")
        except OSError:
            self.fail("log_decision() darf niemals eine OSError durchreichen (best-effort).")


if __name__ == "__main__":
    unittest.main()
