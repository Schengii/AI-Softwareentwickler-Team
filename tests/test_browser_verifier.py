"""
tests/test_browser_verifier.py – Testet die Headless-Browser & Frontend-Validierung (core/browser_verifier.py)
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.browser_verifier import BrowserVerifier


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


class TestPlaywrightSysExecutableRegression(unittest.TestCase):
    """Regression-Test für einen Code-Review-Fund: `_run_playwright_check()` verwendete
    `sys.executable`, obwohl `import sys` im Modul fehlte. Der daraus resultierende
    `NameError` wurde vom breiten `except Exception: return None` lautlos verschluckt – der
    Playwright-Check fiel dadurch IMMER unbemerkt auf die statische Prüfung zurück, selbst
    wenn Playwright installiert war (`engine` blieb fälschlich `"static_dom"` statt
    `"playwright"`)."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        (self.project_dir / "index.html").write_text(
            "<!DOCTYPE html><html><head><title>App</title></head><body></body></html>",
            encoding="utf-8",
        )
        self.verifier = BrowserVerifier(self.project_dir)

    def test_playwright_check_invokes_subprocess_with_sys_executable(self):
        fake_completed = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({"success": True, "errors": [], "missing": [], "title": "App"}),
            stderr="",
        )
        with patch("importlib.util.find_spec", return_value=object()), \
             patch("core.browser_verifier.subprocess.run", return_value=fake_completed) as mock_run:
            report = self.verifier.verify_frontend()

        # Vorher (Bug): NameError -> except Exception: return None -> Fallback auf "static_dom".
        self.assertEqual(report.engine, "playwright")
        self.assertTrue(report.attempted)
        self.assertTrue(report.passed)
        mock_run.assert_called_once()
        called_command = mock_run.call_args[0][0]
        self.assertEqual(called_command[0], sys.executable)


class TestBlankCanvasDetection(unittest.TestCase):
    """
    Realer Fund (Pong-Projekt): eine Seite ohne Konsolenfehler und ohne fehlende Assets kann
    trotzdem funktional komplett tot sein, wenn nie tatsächlich in ein <canvas>-Element
    gezeichnet wird (fehlender Game-Loop/draw()-Aufruf). _run_playwright_check() erkennt das
    jetzt zusätzlich über einen Pixelvergleich mit einem frisch erzeugten leeren Canvas
    gleicher Größe - dieser Test deckt beide Fälle (erkannt / nicht fälschlich gemeldet) ab,
    ohne einen echten Browser zu brauchen (subprocess.run wird gemockt, siehe
    TestPlaywrightSysExecutableRegression oben für dasselbe Prinzip).
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        (self.project_dir / "index.html").write_text(
            "<!DOCTYPE html><html><head><title>App</title></head>"
            "<body><canvas id='game'></canvas><script src='game.js'></script></body></html>",
            encoding="utf-8",
        )
        (self.project_dir / "game.js").write_text("// noop", encoding="utf-8")
        self.verifier = BrowserVerifier(self.project_dir)

    def test_blank_canvas_fails_verification_despite_no_console_errors(self):
        fake_completed = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({
                "success": True, "errors": [], "missing": [], "title": "App",
                "blank_canvases": ["game"],
            }),
            stderr="",
        )
        with patch("importlib.util.find_spec", return_value=object()), \
             patch("core.browser_verifier.subprocess.run", return_value=fake_completed):
            report = self.verifier.verify_frontend()

        self.assertTrue(report.attempted)
        self.assertEqual(report.engine, "playwright")
        self.assertFalse(report.passed)
        self.assertEqual(report.blank_canvases, ["game"])

    def test_drawn_canvas_passes_verification(self):
        fake_completed = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({
                "success": True, "errors": [], "missing": [], "title": "App",
                "blank_canvases": [],
            }),
            stderr="",
        )
        with patch("importlib.util.find_spec", return_value=object()), \
             patch("core.browser_verifier.subprocess.run", return_value=fake_completed):
            report = self.verifier.verify_frontend()

        self.assertTrue(report.passed)
        self.assertEqual(report.blank_canvases, [])


class TestMissingAssetDeduplication(unittest.TestCase):
    """
    Realer Fund: mit tatsächlich installiertem Playwright+Chromium (statt des in CI/vielen
    Dev-Umgebungen üblichen static_dom-Fallbacks) wurde jede fehlende Datei DOPPELT gemeldet -
    einmal von playwright's echter HTTP-404-Erkennung, einmal vom zusätzlich angehängten
    Regex-basierten statischen Scan (verify_frontend() hängte static_missing bisher
    ungefiltert an). Erst sichtbar, sobald der Playwright-Pfad wirklich ausgeführt wird, siehe
    TestPlaywrightSysExecutableRegression oben für dasselbe Mocking-Prinzip.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        (self.project_dir / "index.html").write_text(
            "<!DOCTYPE html><html><head><title>App</title>"
            "<link rel='stylesheet' href='missing.css'></head><body></body></html>",
            encoding="utf-8",
        )
        self.verifier = BrowserVerifier(self.project_dir)

    def test_asset_already_caught_by_playwright_is_not_reported_twice(self):
        fake_completed = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({
                "success": True, "errors": [], "title": "App", "blank_canvases": [],
                "missing": ["HTTP 404: http://127.0.0.1:1234/missing.css"],
            }),
            stderr="",
        )
        with patch("importlib.util.find_spec", return_value=object()), \
             patch("core.browser_verifier.subprocess.run", return_value=fake_completed):
            report = self.verifier.verify_frontend()

        self.assertEqual(len(report.missing_assets), 1)
        self.assertFalse(report.passed)


if __name__ == "__main__":
    unittest.main()
