"""
tests/test_browser_verifier_visual.py – Tests für Visual Feedback & Screenshot-Erweiterung im BrowserVerifier.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.browser_verifier import BrowserVerificationReport, BrowserVerifier


class TestBrowserVerifierVisual(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_report_visual_fields(self):
        report = BrowserVerificationReport(
            attempted=True,
            passed=True,
            engine="playwright",
            screenshot_path=str(self.project_dir / "ui_screenshot.png"),
            visual_overflows=["div#main-container", "table.data-table"],
        )
        self.assertTrue(report.passed)
        self.assertEqual(len(report.visual_overflows), 2)
        self.assertTrue(report.screenshot_path.endswith("ui_screenshot.png"))

    def test_run_playwright_mocked_success(self):
        verifier = BrowserVerifier(self.project_dir)
        html_file = self.project_dir / "index.html"
        html_file.write_text("<!DOCTYPE html><html><body><h1>Hello</h1></body></html>", encoding="utf-8")

        mock_json_out = (
            '{"success": true, "errors": [], "missing": [], "title": "Hello", '
            '"blank_canvases": [], "visual_overflows": ["div.wide"], "screenshot": "ui_screenshot.png"}'
        )

        mock_proc = MagicMock()
        mock_proc.stdout = mock_json_out
        mock_proc.returncode = 0

        with patch("subprocess.run", return_value=mock_proc), \
             patch("importlib.util.find_spec", return_value=True), \
             patch.object(verifier, "_start_backend", return_value=(None, None)):

            report = verifier._run_playwright_check(html_file, timeout=5.0)

            self.assertIsNotNone(report)
            self.assertTrue(report.attempted)
            self.assertEqual(report.visual_overflows, ["div.wide"])
            self.assertTrue(any("Visual Overflow" in w for w in report.warnings))


if __name__ == "__main__":
    unittest.main()
