"""
tests/test_verifier_lint.py – Testet die echte Lint-/Type-Check-Prüfung generierten Codes
(core/verifier.py.check_lint())

Realer Fund: ruff.toml lief bisher AUSSCHLIESSLICH gegen den Framework-Code selbst -
workspace/ ist dort bewusst ausgeschlossen. Generierter Code (den das Team tatsächlich
ausliefert) hatte dadurch überhaupt keine automatische Stil-/Fehlerprüfung.

`ruff`/`eslint`/`tsc` werden dabei ECHT über `shutil.which()`/`CodeSandbox.run_command`
gemockt (wie bei den bestehenden Docker-Build-/Dependency-Audit-Tests) - die Fixture-JSON-
Strings sind wortgetreu aus echten `ruff --output-format=json`- bzw. `eslint --format=json`-
Läufen übernommen, das tsc-Fixture aus einem echten `tsc --pretty false`-Lauf, damit der
Parser gegen die tatsächliche Tool-Ausgabe geprüft wird, ohne dass diese Tools in der CI
installiert sein müssen.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.code_sandbox import ExecutionResult
from core.verifier import ProjectVerifier
from core.verifier.models import VerificationReport


def _VerificationReport(passed: bool) -> VerificationReport:
    return VerificationReport(ran=True, passed=passed, exit_code=0 if passed else 1, stdout="", stderr="", duration_seconds=0.1)


# Wortgetreue Fixture-Struktur aus einem echten `ruff check --isolated --output-format=json`-
# Lauf (siehe tests/test_verifier_dependency_audit.py für dasselbe Vorgehen bei pip-audit/npm
# audit). "filename" wird pro Test mit dem tatsächlichen Projektpfad gefüllt (echte ruff-/
# ESLint-Läufe liefern immer ABSOLUTE Pfade), damit die Pfad-Relativierungslogik selbst
# echt mitgeprüft wird, statt sie durch einen bereits-relativen Fixture-Pfad zu umgehen.
def _ruff_json(project_dir: Path, filename: str = "app.py") -> str:
    return json.dumps([
        {
            "filename": str(project_dir / filename),
            "location": {"row": 1, "column": 8},
            "code": "F401",
            "message": "`os` imported but unused",
        },
    ])


def _eslint_json(project_dir: Path, filename: str = "bad.js") -> str:
    return json.dumps([
        {
            "filePath": str(project_dir / filename),
            "messages": [
                {"ruleId": "no-unused-vars", "severity": 2, "message": "'x' is assigned a value but never used.", "line": 1, "column": 7},
                {"ruleId": "no-console", "severity": 1, "message": "Unexpected console statement.", "line": 2, "column": 1},
            ],
        },
    ])


_REAL_ESLINT_CLEAN = json.dumps([{"filePath": "clean.js", "messages": []}])


def _tsc_output(filename: str = "bad.ts") -> str:
    # tsc gibt Pfade relativ zum cwd des Aufrufs aus (hier: node_dir) - genau das simuliert
    # dieses Fixture wortgetreu (echter Lauf: "bad.ts(1,7): error TS2322: ...").
    return f"{filename}(1,7): error TS2322: Type 'string' is not assignable to type 'number'.\n"


class TestPythonLintViaRuff(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        (self.project_dir / "app.py").write_text("import os\nx = 1\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/ruff")
    def test_reports_real_ruff_issues(self, mock_which, mock_run):
        mock_run.return_value = ExecutionResult(
            exit_code=1, stdout=_ruff_json(self.project_dir.resolve()), stderr="", duration_seconds=0.2,
        )
        verifier = ProjectVerifier(self.project_dir)

        reports = verifier.check_lint()

        self.assertEqual(len(reports), 1)
        report = reports[0]
        self.assertTrue(report.attempted)
        self.assertFalse(report.passed)
        self.assertEqual(report.tool, "ruff")
        self.assertEqual(len(report.issues), 1)
        self.assertEqual(report.issues[0].rule, "F401")
        # Der absolute Pfad aus dem echten ruff-Output wird auf einen Projekt-relativen
        # Pfad zurückgerechnet (nicht der rohe absolute Pfad durchgereicht).
        self.assertEqual(report.issues[0].file_path, "app.py")
        # --isolated darf niemals fehlen - sonst würde die Framework-eigene ruff.toml
        # (E501-Ausnahme etc.) generierten Projekten aufgezwungen.
        self.assertIn("--isolated", mock_run.call_args[0][0])

    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/ruff")
    def test_runs_safe_autofix_before_the_actual_check(self, mock_which, mock_run):
        # Realer Fund (Bestandsaufnahme cloudvault-Projekt): Lint-Funde standen bisher nur im
        # Protokoll, wurden aber nie behoben. `_lint_python()` führt jetzt VOR dem eigentlichen
        # Check-Lauf `ruff check --fix` (NUR sichere Autofixes, kein `--unsafe-fixes`) aus.
        mock_run.return_value = ExecutionResult(exit_code=0, stdout="[]", stderr="", duration_seconds=0.1)
        verifier = ProjectVerifier(self.project_dir)

        verifier.check_lint()

        self.assertEqual(mock_run.call_count, 2)
        fix_call_args = mock_run.call_args_list[0][0][0]
        check_call_args = mock_run.call_args_list[1][0][0]
        self.assertIn("--fix", fix_call_args)
        self.assertNotIn("--unsafe-fixes", fix_call_args)
        self.assertNotIn("--fix", check_call_args)

    @patch("core.verifier.lint.ENABLE_AUTO_LINT_FIX", False)
    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/ruff")
    def test_autofix_disabled_via_config_flag(self, mock_which, mock_run):
        mock_run.return_value = ExecutionResult(exit_code=0, stdout="[]", stderr="", duration_seconds=0.1)
        verifier = ProjectVerifier(self.project_dir)

        verifier.check_lint()

        self.assertEqual(mock_run.call_count, 1)
        self.assertNotIn("--fix", mock_run.call_args[0][0])

    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/ruff")
    def test_reports_clean_when_no_issues_found(self, mock_which, mock_run):
        mock_run.return_value = ExecutionResult(exit_code=0, stdout="[]", stderr="", duration_seconds=0.1)
        verifier = ProjectVerifier(self.project_dir)

        report = verifier.check_lint()[0]

        self.assertTrue(report.attempted)
        self.assertTrue(report.passed)
        self.assertEqual(report.issues, [])

    @patch("core.verifier.shutil.which", return_value=None)
    def test_skipped_gracefully_when_ruff_not_installed(self, mock_which):
        verifier = ProjectVerifier(self.project_dir)
        report = verifier.check_lint()[0]

        self.assertFalse(report.attempted)
        self.assertIn("nicht installiert", report.reason_skipped)

    def test_no_report_without_python_files(self):
        empty_project = tempfile.mkdtemp()
        try:
            verifier = ProjectVerifier(empty_project)
            self.assertEqual(verifier.check_lint(), [])
        finally:
            shutil.rmtree(empty_project, ignore_errors=True)

    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/ruff")
    def test_b008_ignored_for_detected_fastapi_project(self, mock_which, mock_run):
        # Team-Optimierung (Retrospektive, zeiterfassung_app-Lauf): B008 ("kein Funktionsaufruf
        # in Default-Argumenten") schlägt bei JEDEM FastAPI-`Depends()`-Parameter an - dem von
        # FastAPI selbst vorgeschriebenen Dependency-Injection-Idiom, keine echte Fehlerquelle.
        # Ein als FastAPI erkanntes Projekt (hier: "fastapi" in requirements.txt) muss die Regel
        # deshalb per --ignore=B008 ausnehmen.
        (self.project_dir / "requirements.txt").write_text("fastapi==0.110.2\n", encoding="utf-8")
        mock_run.return_value = ExecutionResult(exit_code=0, stdout="[]", stderr="", duration_seconds=0.1)
        verifier = ProjectVerifier(self.project_dir)

        verifier.check_lint()

        check_call_args = mock_run.call_args_list[-1][0][0]
        self.assertIn("--ignore=B008", check_call_args)

    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/ruff")
    def test_b008_not_ignored_for_non_fastapi_project(self, mock_which, mock_run):
        mock_run.return_value = ExecutionResult(exit_code=0, stdout="[]", stderr="", duration_seconds=0.1)
        verifier = ProjectVerifier(self.project_dir)  # setUp() legt nur ein plain app.py an

        verifier.check_lint()

        check_call_args = mock_run.call_args_list[-1][0][0]
        self.assertNotIn("--ignore=B008", check_call_args)

    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/ruff")
    def test_technical_failure_is_never_reported_as_clean(self, mock_which, mock_run):
        mock_run.return_value = ExecutionResult(exit_code=2, stdout="", stderr="ruff: internal error", duration_seconds=0.1)
        verifier = ProjectVerifier(self.project_dir)

        report = verifier.check_lint()[0]

        self.assertFalse(report.attempted)
        self.assertTrue(report.passed)  # neutraler Skip-Default, keine echte Aussage


class TestPythonUnsafeAutofix(unittest.TestCase):
    """P0-6 Teil 2 (ROADMAP_TEMP.md): zweiter, separat protokollierter `--unsafe-fixes`-Durchlauf,
    nur dauerhaft übernommen, wenn die eigene Testsuite danach weiterhin grün ist."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        self.app_file = self.project_dir / "app.py"
        self.app_file.write_text("import os\nx = 1\n", encoding="utf-8")
        (self.project_dir / "test_app.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("core.verifier.lint.ENABLE_AUTO_LINT_UNSAFE_FIX", True)
    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/ruff")
    def test_unsafe_fix_kept_when_tests_still_pass(self, mock_which, mock_run):
        def _side_effect(command, **_kwargs):
            if "--unsafe-fixes" in command:
                self.app_file.write_text("x = 1\n", encoding="utf-8")  # simuliert F401-Fix
            return ExecutionResult(exit_code=0, stdout="[]", stderr="", duration_seconds=0.1)

        mock_run.side_effect = _side_effect
        verifier = ProjectVerifier(self.project_dir)
        with patch.object(verifier, "run_tests", return_value=_VerificationReport(passed=True)):
            report = verifier.check_lint()[0]

        self.assertEqual(report.unsafe_fixes_applied, 1)
        self.assertFalse(report.unsafe_fixes_reverted)
        self.assertEqual(self.app_file.read_text(encoding="utf-8"), "x = 1\n")

    @patch("core.verifier.lint.ENABLE_AUTO_LINT_UNSAFE_FIX", True)
    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/ruff")
    def test_unsafe_fix_reverted_when_tests_fail(self, mock_which, mock_run):
        original = self.app_file.read_text(encoding="utf-8")

        def _side_effect(command, **_kwargs):
            if "--unsafe-fixes" in command:
                self.app_file.write_text("x = 1\n", encoding="utf-8")
            return ExecutionResult(exit_code=0, stdout="[]", stderr="", duration_seconds=0.1)

        mock_run.side_effect = _side_effect
        verifier = ProjectVerifier(self.project_dir)
        with patch.object(verifier, "run_tests", return_value=_VerificationReport(passed=False)):
            report = verifier.check_lint()[0]

        self.assertEqual(report.unsafe_fixes_applied, 1)
        self.assertTrue(report.unsafe_fixes_reverted)
        self.assertEqual(self.app_file.read_text(encoding="utf-8"), original)

    @patch("core.verifier.lint.ENABLE_AUTO_LINT_UNSAFE_FIX", True)
    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/ruff")
    def test_unsafe_fix_skipped_without_own_test_suite(self, mock_which, mock_run):
        (self.project_dir / "test_app.py").unlink()
        mock_run.return_value = ExecutionResult(exit_code=0, stdout="[]", stderr="", duration_seconds=0.1)
        verifier = ProjectVerifier(self.project_dir)

        report = verifier.check_lint()[0]

        self.assertEqual(report.unsafe_fixes_applied, 0)
        for call in mock_run.call_args_list:
            self.assertNotIn("--unsafe-fixes", call[0][0])

    @patch("core.verifier.lint.ENABLE_AUTO_LINT_UNSAFE_FIX", False)
    @patch("core.verifier.CodeSandbox.run_command")
    @patch("core.verifier.shutil.which", return_value="/usr/bin/ruff")
    def test_unsafe_fix_disabled_via_config_flag_by_default(self, mock_which, mock_run):
        mock_run.return_value = ExecutionResult(exit_code=0, stdout="[]", stderr="", duration_seconds=0.1)
        verifier = ProjectVerifier(self.project_dir)

        report = verifier.check_lint()[0]

        self.assertEqual(report.unsafe_fixes_applied, 0)
        self.assertFalse(report.unsafe_fixes_reverted)
        for call in mock_run.call_args_list:
            self.assertNotIn("--unsafe-fixes", call[0][0])


class TestNodeEslintIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        (self.project_dir / "package.json").write_text(
            json.dumps({"name": "sample", "scripts": {"test": "node test.js"}}), encoding="utf-8",
        )
        (self.project_dir / "test.js").write_text("process.exit(0);\n", encoding="utf-8")
        (self.project_dir / "package-lock.json").write_text("{}", encoding="utf-8")
        (self.project_dir / ".eslintrc.json").write_text("{}", encoding="utf-8")
        bin_dir = self.project_dir / "node_modules" / ".bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "eslint").write_text("#!/bin/sh\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("core.verifier.CodeSandbox.run_command")
    def test_reports_real_eslint_issues_ignoring_warnings(self, mock_run):
        mock_run.return_value = ExecutionResult(
            exit_code=1, stdout=_eslint_json(self.project_dir.resolve()), stderr="", duration_seconds=0.2,
        )
        verifier = ProjectVerifier(self.project_dir)

        reports = [r for r in verifier.check_lint() if r.tool == "eslint"]

        self.assertEqual(len(reports), 1)
        report = reports[0]
        self.assertTrue(report.attempted)
        self.assertFalse(report.passed)
        # Nur severity=2 (Fehler) zählt - severity=1 (Warnung, no-console) darf NICHT
        # als "nicht bestanden" durchgehen.
        self.assertEqual(len(report.issues), 1)
        self.assertEqual(report.issues[0].rule, "no-unused-vars")
        self.assertEqual(report.issues[0].file_path, "bad.js")

    @patch("core.verifier.CodeSandbox.run_command")
    def test_reports_clean_when_only_warnings_or_nothing_found(self, mock_run):
        mock_run.return_value = ExecutionResult(exit_code=0, stdout=_REAL_ESLINT_CLEAN, stderr="", duration_seconds=0.1)
        verifier = ProjectVerifier(self.project_dir)

        report = next(r for r in verifier.check_lint() if r.tool == "eslint")

        self.assertTrue(report.attempted)
        self.assertTrue(report.passed)

    def test_skipped_when_no_eslint_config_present(self):
        (self.project_dir / ".eslintrc.json").unlink()
        verifier = ProjectVerifier(self.project_dir)

        self.assertFalse(any(r.tool == "eslint" for r in verifier.check_lint()))

    def test_skipped_gracefully_when_eslint_not_locally_installed(self):
        shutil.rmtree(self.project_dir / "node_modules")
        verifier = ProjectVerifier(self.project_dir)

        report = next(r for r in verifier.check_lint() if r.tool == "eslint")
        self.assertFalse(report.attempted)
        self.assertIn("nicht", report.reason_skipped)


class TestNodeTscIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        (self.project_dir / "package.json").write_text(
            json.dumps({"name": "sample", "scripts": {"test": "node test.js"}}), encoding="utf-8",
        )
        (self.project_dir / "test.js").write_text("process.exit(0);\n", encoding="utf-8")
        (self.project_dir / "package-lock.json").write_text("{}", encoding="utf-8")
        (self.project_dir / "tsconfig.json").write_text("{}", encoding="utf-8")
        bin_dir = self.project_dir / "node_modules" / ".bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "tsc").write_text("#!/bin/sh\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("core.verifier.CodeSandbox.run_command")
    def test_reports_real_tsc_type_errors(self, mock_run):
        mock_run.return_value = ExecutionResult(exit_code=2, stdout=_tsc_output(), stderr="", duration_seconds=0.3)
        verifier = ProjectVerifier(self.project_dir)

        report = next(r for r in verifier.check_lint() if r.tool == "tsc")

        self.assertTrue(report.attempted)
        self.assertFalse(report.passed)
        self.assertEqual(len(report.issues), 1)
        self.assertEqual(report.issues[0].rule, "TS2322")
        self.assertEqual(report.issues[0].line_number, 1)
        # tsc gibt den Pfad relativ zum cwd (node_dir) aus - muss auf den Projekt-relativen
        # Pfad zurückgerechnet werden (node_dir == project_dir in diesem Testfall).
        self.assertEqual(report.issues[0].file_path, "bad.ts")

    @patch("core.verifier.CodeSandbox.run_command")
    def test_reports_clean_on_empty_output_and_exit_zero(self, mock_run):
        mock_run.return_value = ExecutionResult(exit_code=0, stdout="", stderr="", duration_seconds=0.1)
        verifier = ProjectVerifier(self.project_dir)

        report = next(r for r in verifier.check_lint() if r.tool == "tsc")

        self.assertTrue(report.attempted)
        self.assertTrue(report.passed)

    def test_skipped_when_no_tsconfig_present(self):
        (self.project_dir / "tsconfig.json").unlink()
        verifier = ProjectVerifier(self.project_dir)

        self.assertFalse(any(r.tool == "tsc" for r in verifier.check_lint()))

    def test_skipped_gracefully_when_tsc_not_locally_installed(self):
        shutil.rmtree(self.project_dir / "node_modules")
        verifier = ProjectVerifier(self.project_dir)

        report = next(r for r in verifier.check_lint() if r.tool == "tsc")
        self.assertFalse(report.attempted)


if __name__ == "__main__":
    unittest.main()
