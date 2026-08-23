"""
tests/test_visual_verifier.py – Testet visuelle Verifikation und Screenshots in core/browser_verifier.py
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.browser_verifier import BrowserVerificationReport, BrowserVerifier


class TestVisualVerifier(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        self.verifier = BrowserVerifier(self.project_dir)

    def test_browser_verification_report_fields(self):
        report = BrowserVerificationReport(
            attempted=True,
            passed=True,
            engine="playwright",
            visual_layout_issues=[],
            screenshot_path="/path/to/screenshot.png"
        )
        self.assertTrue(report.passed)
        self.assertEqual(report.screenshot_path, "/path/to/screenshot.png")
        self.assertEqual(len(report.visual_layout_issues), 0)

    def test_playwright_mock_layout_issues(self):
        (self.project_dir / "index.html").write_text("<!DOCTYPE html><html><head><title>Test</title></head><body><h1>Hello</h1></body></html>", encoding="utf-8")
        
        mock_output = '{"success": true, "errors": [], "missing": [], "title": "Test", "blank_canvases": [], "layout_issues": ["Horizontales Scroll-Overflow erkannt: Seiteninhalt ragt über den Viewport hinaus."], "screenshot_path": ""}'
        mock_proc = MagicMock()
        mock_proc.stdout = mock_output

        with patch("importlib.util.find_spec", return_value=True), \
             patch("subprocess.run", return_value=mock_proc):
            report = self.verifier.verify_frontend(timeout_seconds=1.0)
            self.assertTrue(report.attempted)
            self.assertFalse(report.passed)  # Fehlgeschlagen wegen Layout Issue
            self.assertEqual(len(report.visual_layout_issues), 1)
            self.assertIn("Horizontales Scroll-Overflow", report.visual_layout_issues[0])
