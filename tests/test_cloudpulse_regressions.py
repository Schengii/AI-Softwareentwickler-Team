"""
tests/test_cloudpulse_regressions.py – Regressionen aus der Fehleranalyse des cloudpulse-Laufs
(logs/FEHLERANALYSE_KI_TEAM_20260916.md, 16.09.2026).

Abgedeckt werden die dort belegten Framework-Fehler, die den Lauf auf
`verification_ok: false` kippen liessen bzw. Agentenaufrufe verbrannt haben:
- root-relative Asset-Pfade in einem `static/`-Frontend (P0, browser_verifier)
- `pytest.ini` mit eingerueckter erster Zeile (Pre-Flight-Erkennung + Selbstreparatur)
- `__init__.py` mit einer einzigen Kommentarzeile als angebliches Vollstaendigkeits-Veto
- fehlende Schreibgrenze der Rolle `security` (foreign_changes an Backend-Dateien)
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.browser_verifier import BrowserVerifier
from core.pre_flight_check import run_pre_flight_check
from core.verifier.completeness import CompletenessMixin
from core.write_guard import check_write_scope


def _static_frontend_project(base: Path) -> Path:
    """Baut die reale cloudpulse-Struktur nach: FastAPI mountet `static/` als Web-Root."""
    static = base / "static"
    static.mkdir(parents=True)
    (static / "index.html").write_text(
        '<!doctype html><html><head><title>CloudPulse</title>'
        '<link rel="stylesheet" href="/style.css"></head>'
        '<body><script src="/app.js"></script></body></html>',
        encoding="utf-8",
    )
    (static / "app.js").write_text("console.log('ok');\n", encoding="utf-8")
    (static / "style.css").write_text("body{margin:0}\n", encoding="utf-8")
    return static / "index.html"


class TestRootRelativeAssetsInStaticDir(unittest.TestCase):
    def test_root_relative_assets_resolve_against_static_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            entry = _static_frontend_project(base)
            verifier = BrowserVerifier(base)
            serve_root = verifier._serve_root_for(entry)
            self.assertEqual(serve_root, entry.parent)
            missing, _ = verifier._validate_static_assets(entry, serve_root)
            self.assertEqual(missing, [])

    def test_genuinely_missing_asset_is_still_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            entry = _static_frontend_project(base)
            (entry.parent / "app.js").unlink()
            verifier = BrowserVerifier(base)
            missing, _ = verifier._validate_static_assets(entry, verifier._serve_root_for(entry))
            self.assertTrue(any("app.js" in m for m in missing), missing)

    def test_project_root_html_keeps_project_dir_as_web_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            entry = base / "index.html"
            entry.write_text('<html><title>x</title><script src="/assets/app.js"></script></html>', encoding="utf-8")
            (base / "assets").mkdir()
            (base / "assets" / "app.js").write_text("", encoding="utf-8")
            verifier = BrowserVerifier(base)
            self.assertEqual(verifier._serve_root_for(entry), base)
            missing, _ = verifier._validate_static_assets(entry, verifier._serve_root_for(entry))
            self.assertEqual(missing, [])


class TestMalformedPytestIni(unittest.TestCase):
    BROKEN = "    [pytest]\n    pythonpath = .\n    asyncio_mode = auto\n"

    def test_pre_flight_reports_value_continuation(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "pytest.ini").write_text(self.BROKEN, encoding="utf-8")
            report = run_pre_flight_check(tmp)
            types = {i.issue_type for i in report.issues}
            self.assertIn("malformed_ini_continuation", types)

    def test_valid_ini_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "pytest.ini").write_text("[pytest]\npythonpath = .\n", encoding="utf-8")
            report = run_pre_flight_check(tmp)
            self.assertEqual([i for i in report.issues if i.issue_type.startswith("malformed_ini")], [])

    def test_environment_repairs_indentation_deterministically(self):
        from core.verifier.environment import EnvironmentMixin

        with tempfile.TemporaryDirectory() as tmp:
            ini = Path(tmp, "pytest.ini")
            ini.write_text(self.BROKEN, encoding="utf-8")
            preparer = EnvironmentMixin(tmp)
            log = preparer._ensure_pytest_ini()
            self.assertIn("repariert", log)
            self.assertEqual(ini.read_text(encoding="utf-8"), "[pytest]\npythonpath = .\nasyncio_mode = auto\n")
            # Idempotent: eine bereits gesunde Datei wird nicht erneut angefasst.
            self.assertEqual(preparer._ensure_pytest_ini(), "")

    def test_repair_preserves_multiline_values(self):
        from core.verifier.environment import EnvironmentMixin

        with tempfile.TemporaryDirectory() as tmp:
            ini = Path(tmp, "pytest.ini")
            content = "[pytest]\naddopts =\n    -q\n    --strict-markers\n"
            ini.write_text(content, encoding="utf-8")
            preparer = EnvironmentMixin(tmp)
            self.assertEqual(preparer._ensure_pytest_ini(), "")
            self.assertEqual(ini.read_text(encoding="utf-8"), content)


class TestPackageMarkerIsNoStub(unittest.TestCase):
    def test_comment_only_init_is_not_flagged(self):
        checker = CompletenessMixin()
        self.assertEqual(checker._comment_only_stub_files("app/core/__init__.py", ".py", "# Core package\n"), [])

    def test_comment_only_module_is_still_flagged(self):
        checker = CompletenessMixin()
        issues = checker._comment_only_stub_files("app/utils/resilience.py", ".py", "# Auszug aus resilience.py\n")
        self.assertEqual(len(issues), 1)


class TestSecurityWriteScope(unittest.TestCase):
    def test_security_may_not_overwrite_backend_files(self):
        self.assertIsNotNone(check_write_scope("security", "app/main.py"))
        self.assertIsNotNone(check_write_scope("security", "app/api/endpoints.py"))

    def test_security_keeps_its_own_artifacts(self):
        for allowed in ("docs/SECURITY_AUDIT.md", "app/core/security.py", ".env.example", "requirements.txt"):
            self.assertIsNone(check_write_scope("security", allowed), allowed)


if __name__ == "__main__":
    unittest.main()
