"""
tests/test_accessibility_verifier.py – Testet den echten axe-core-Accessibility-Scan
(core/browser_verifier.py.verify_accessibility())

Realer Fund: der accessibility-Agent konnte WCAG-Verstöße bisher nur "plausibel" einschätzen
(LLM-Freitext-Checkliste ohne konkreten Fundort), ohne echten Scan gegen eine gerenderte Seite.
Playwright/axe-core-python werden dabei ECHT über `importlib.util.find_spec`/
`subprocess.run` gemockt (dasselbe Muster wie beim bestehenden `_run_playwright_check()`-Test
in test_browser_verifier.py) – die Fixture-Struktur ist am realen axe-core-Ausgabeformat
orientiert (dieselbe stabile Struktur, die auch @axe-core/playwright, cypress-axe, jest-axe
zurückgeben, da alle nur denselben axe-core-Engine-Kern aufrufen).
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.browser_verifier import BrowserVerifier

_AXE_RESULT_WITH_VIOLATIONS = {
    "violations": [
        {
            "id": "color-contrast",
            "impact": "serious",
            "description": "Ensures the contrast between foreground and background colors meets WCAG 2 AA contrast ratio thresholds",
            "help": "Elements must meet minimum color contrast ratio thresholds",
            "helpUrl": "https://dequeuniversity.com/rules/axe/4.x/color-contrast",
            "nodes": [{"html": "<button>Los</button>", "target": [".btn-primary"], "failureSummary": "Fix: ..."}],
        },
        {
            "id": "image-alt",
            "impact": "critical",
            "description": "Ensures <img> elements have alternate text",
            "help": "Images must have alternate text",
            "helpUrl": "https://dequeuniversity.com/rules/axe/4.x/image-alt",
            "nodes": [{"html": "<img src='logo.png'>", "target": ["img.logo"], "failureSummary": "Fix: ..."}],
        },
    ],
    "passes": [], "incomplete": [], "inapplicable": [],
}

_AXE_RESULT_CLEAN = {"violations": [], "passes": [], "incomplete": [], "inapplicable": []}


def _find_spec_playwright_only(name, *a, **kw):
    return object() if name == "playwright" else None


def _find_spec_both_installed(name, *a, **kw):
    return object()


class TestVerifyAccessibility(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        self.verifier = BrowserVerifier(self.project_dir)

    def _write_index_html(self):
        (self.project_dir / "index.html").write_text(
            "<!DOCTYPE html><html><head><title>App</title></head><body><h1>Hallo</h1></body></html>",
            encoding="utf-8",
        )

    def test_no_html_files_is_skipped(self):
        report = self.verifier.verify_accessibility()
        self.assertFalse(report.attempted)
        self.assertIn("Keine HTML-Dateien", report.reason_skipped)

    @patch("importlib.util.find_spec", return_value=None)
    def test_skipped_gracefully_when_playwright_not_installed(self, mock_find_spec):
        self._write_index_html()
        report = self.verifier.verify_accessibility()
        self.assertFalse(report.attempted)
        self.assertIn("Playwright", report.reason_skipped)

    @patch("importlib.util.find_spec", side_effect=_find_spec_playwright_only)
    def test_skipped_gracefully_when_axe_core_python_not_installed(self, mock_find_spec):
        self._write_index_html()
        report = self.verifier.verify_accessibility()
        self.assertFalse(report.attempted)
        self.assertIn("axe-core-python", report.reason_skipped)

    @patch("core.browser_verifier.subprocess.run")
    @patch("importlib.util.find_spec", side_effect=_find_spec_both_installed)
    def test_reports_real_axe_core_violations(self, mock_find_spec, mock_run):
        self._write_index_html()
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({"success": True, "result": _AXE_RESULT_WITH_VIOLATIONS}), stderr="",
        )

        report = self.verifier.verify_accessibility()

        self.assertTrue(report.attempted)
        self.assertFalse(report.passed)
        self.assertEqual(len(report.violations), 2)
        contrast = next(v for v in report.violations if v.rule_id == "color-contrast")
        self.assertEqual(contrast.impact, "serious")
        self.assertEqual(contrast.target, ".btn-primary")
        self.assertIn("dequeuniversity.com", contrast.help_url)
        alt = next(v for v in report.violations if v.rule_id == "image-alt")
        self.assertEqual(alt.impact, "critical")

    @patch("core.browser_verifier.subprocess.run")
    @patch("importlib.util.find_spec", side_effect=_find_spec_both_installed)
    def test_reports_clean_when_no_violations(self, mock_find_spec, mock_run):
        self._write_index_html()
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({"success": True, "result": _AXE_RESULT_CLEAN}), stderr="",
        )

        report = self.verifier.verify_accessibility()

        self.assertTrue(report.attempted)
        self.assertTrue(report.passed)
        self.assertEqual(report.violations, [])

    @patch("core.browser_verifier.subprocess.run")
    @patch("importlib.util.find_spec", side_effect=_find_spec_both_installed)
    def test_internal_axe_error_is_never_reported_as_clean(self, mock_find_spec, mock_run):
        self._write_index_html()
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({"success": False, "error": "Page.goto: Timeout 10000ms exceeded"}), stderr="",
        )

        report = self.verifier.verify_accessibility()

        self.assertFalse(report.attempted)
        self.assertFalse(report.passed)
        self.assertIn("Timeout", report.reason_skipped)

    @patch("core.browser_verifier.subprocess.run")
    @patch("importlib.util.find_spec", side_effect=_find_spec_both_installed)
    def test_empty_output_is_never_reported_as_clean(self, mock_find_spec, mock_run):
        self._write_index_html()
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="crashed")

        report = self.verifier.verify_accessibility()

        self.assertFalse(report.attempted)
        self.assertFalse(report.passed)

    @patch("core.browser_verifier.subprocess.run", side_effect=subprocess.TimeoutExpired("python", 15))
    @patch("importlib.util.find_spec", side_effect=_find_spec_both_installed)
    def test_subprocess_timeout_does_not_crash(self, mock_find_spec, mock_run):
        self._write_index_html()
        report = self.verifier.verify_accessibility()
        self.assertFalse(report.attempted)
        self.assertFalse(report.passed)


class TestParseAxeResult(unittest.TestCase):
    def setUp(self):
        self.verifier = BrowserVerifier(tempfile.mkdtemp())

    def test_missing_violations_key_is_treated_as_clean(self):
        report = self.verifier._parse_axe_result({}, "http://x")
        self.assertTrue(report.attempted)
        self.assertTrue(report.passed)

    def test_non_dict_entries_are_skipped_instead_of_crashing(self):
        report = self.verifier._parse_axe_result({"violations": ["not-a-dict", 42]}, "http://x")
        self.assertTrue(report.attempted)
        self.assertEqual(report.violations, [])

    def test_missing_fields_degrade_gracefully(self):
        report = self.verifier._parse_axe_result({"violations": [{"id": "some-rule"}]}, "http://x")
        self.assertEqual(len(report.violations), 1)
        v = report.violations[0]
        self.assertEqual(v.rule_id, "some-rule")
        self.assertEqual(v.impact, "unbekannt")
        self.assertEqual(v.target, "?")


if __name__ == "__main__":
    unittest.main()
