"""
tests/test_no_progress_signature_helpers.py – Testet die gemeinsame Signatur-/Fortschritts-
Erkennung (agents/orchestrator/verification.py._issue_signature()/_no_progress()), auf die
seit der zweiten taskpulse-Retrospektive alle vier "identische Funde -> abbrechen"-Fix-
Schleifen (Test-, Governance-, Vorab-Import-, Vollständigkeits-Schleife) zurückgreifen, statt
die Signatur-Bildung/den -Vergleich viermal wortgleich zu kopieren.
"""

import unittest

from agents.orchestrator.verification import _issue_signature, _no_progress


class TestIssueSignature(unittest.TestCase):
    def test_same_items_produce_equal_signature_regardless_of_order(self):
        a = _issue_signature(["x", "y"], lambda s: (s, s))
        b = _issue_signature(["y", "x"], lambda s: (s, s))
        self.assertEqual(a, b)

    def test_different_items_produce_different_signature(self):
        a = _issue_signature(["x"], lambda s: (s, s))
        b = _issue_signature(["y"], lambda s: (s, s))
        self.assertNotEqual(a, b)

    def test_empty_items_produce_empty_signature(self):
        self.assertEqual(_issue_signature([], lambda s: (s, s)), frozenset())

    def test_key_fn_applied_per_item(self):
        sig = _issue_signature([{"a": 1, "b": "msg"}], lambda d: (d["a"], d["b"]))
        self.assertEqual(sig, frozenset({(1, "msg")}))


class TestNoProgress(unittest.TestCase):
    def test_first_attempt_is_never_no_progress(self):
        current = _issue_signature(["x"], lambda s: (s, s))
        self.assertFalse(_no_progress(None, current))

    def test_identical_signature_is_no_progress(self):
        sig = _issue_signature(["x"], lambda s: (s, s))
        self.assertTrue(_no_progress(sig, sig))

    def test_changed_signature_is_progress(self):
        previous = _issue_signature(["x"], lambda s: (s, s))
        current = _issue_signature(["y"], lambda s: (s, s))
        self.assertFalse(_no_progress(previous, current))

    def test_fewer_or_more_items_counts_as_progress(self):
        previous = _issue_signature(["x", "y"], lambda s: (s, s))
        current = _issue_signature(["x"], lambda s: (s, s))
        self.assertFalse(_no_progress(previous, current))


if __name__ == "__main__":
    unittest.main()
