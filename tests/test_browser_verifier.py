"""
tests/test_browser_verifier.py – Testet die Headless-Browser & Frontend-Validierung (core/browser_verifier.py)
"""

import tempfile
import unittest
from pathlib import Path

from core.browser_verifier import BrowserVerificationReport, BrowserVerifier


class TestBrowserVerifier(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        self.verifier = BrowserVerifier(self.project_dir)

    def test_no_html_files_is_skipped(self):
        report = self.verifier.verify_frontend()
        self.assertFalse(report.attempted)
        self.assertIn("Keine HTML-Dateien", report.reason_skipped)

    def test_valid_html_static_dom_passes(self):
        # Create HTML with valid local CSS/JS files
        (self.project_dir / "styles.css").write_text("body { background: #000; }", encoding="utf-8")
        (self.project_dir / "app.js").write_text("console.log('ready');", encoding="utf-8")
        (self.project_dir / "index.html").write_text(
            "<!DOCTYPE html><html><head><title>App</title><link rel='stylesheet' href='styles.css'></head>"
            "<body><h1>Hello</h1><script src='app.js'></script></body></html>",
            encoding="utf-8",
        )

        report = self.verifier.verify_frontend()
        self.assertTrue(report.attempted)
        self.assertTrue(report.passed)
        self.assertEqual(report.missing_assets, [])

    def test_missing_asset_fails_and_reports_missing_file(self):
        # HTML references missing CSS & JS
        (self.project_dir / "index.html").write_text(
            "<!DOCTYPE html><html><head><title>App</title><link rel='stylesheet' href='missing_theme.css'></head>"
            "<body><script src='missing_bundle.js'></script></body></html>",
            encoding="utf-8",
        )

        report = self.verifier.verify_frontend()
        self.assertTrue(report.attempted)
        self.assertFalse(report.passed)
        self.assertEqual(len(report.missing_assets), 2)
        self.assertTrue(any("missing_theme.css" in m for m in report.missing_assets))
        self.assertTrue(any("missing_bundle.js" in m for m in report.missing_assets))

    def test_external_cdn_links_are_ignored_in_static_check(self):
        (self.project_dir / "index.html").write_text(
            "<!DOCTYPE html><html><head><title>App</title>"
            "<link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5/dist/css/bootstrap.min.css'>"
            "<script src='https://cdn.jsdelivr.net/npm/chart.js'></script>"
            "</head><body></body></html>",
            encoding="utf-8",
        )

        report = self.verifier.verify_frontend()
        self.assertTrue(report.attempted)
        self.assertTrue(report.passed)
        self.assertEqual(report.missing_assets, [])


if __name__ == "__main__":
    unittest.main()
