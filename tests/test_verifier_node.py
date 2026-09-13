"""
tests/test_verifier_node.py – Testet die npm-Verifikation für Node/JS-Projekte (core/verifier.py)

Realer Fund: core/verifier.py verifizierte bisher AUSSCHLIESSLICH Python-Projekte
(test_*.py) – ein vom frontend/mobile-Agenten erzeugtes JS/TS-Projekt lief nie durch einen
echten `npm test`. "Keine Tests gefunden" tauchte selbst dann auf, wenn eine vollständige,
echt ausführbare npm-Testsuite existierte.

Nutzt für die npm-install/-test-Läufe bewusst ECHTE, aber abhängigkeitsfreie Node-Projekte
(kein Netzwerkzugriff nötig, `npm install` mit leeren "dependencies" ist offline-sicher) –
denselben Realitäts-Anspruch wie test_verifier.py für Python. Nur `npm ci` (das eine exakt
zum package.json passende package-lock.json voraussetzt) wird gemockt, analog zu den
bestehenden Docker-Build-Tests.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.code_sandbox import ExecutionResult
from core.verifier import ProjectVerifier


def _write_node_project(root: Path, test_script_body: str, subdir: str = ".") -> Path:
    project_dir = root if subdir == "." else root / subdir
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "package.json").write_text(
        json.dumps({"name": "sample", "version": "1.0.0", "private": True,
                    "scripts": {"test": "node test.js"}}),
        encoding="utf-8",
    )
    (project_dir / "test.js").write_text(test_script_body, encoding="utf-8")
    return project_dir


class TestFindNodeProjects(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_finds_package_json_with_test_script(self):
        _write_node_project(self.project_dir, "process.exit(0);")
        verifier = ProjectVerifier(self.project_dir)
        found = verifier._find_node_projects()
        self.assertEqual(found, [self.project_dir.resolve()])

    def test_ignores_package_json_without_test_script(self):
        (self.project_dir / "package.json").write_text(
            json.dumps({"name": "no-tests", "scripts": {"build": "echo build"}}), encoding="utf-8",
        )
        verifier = ProjectVerifier(self.project_dir)
        self.assertEqual(verifier._find_node_projects(), [])

    def test_ignores_package_json_inside_node_modules(self):
        nested = self.project_dir / "node_modules" / "some-dep"
        nested.mkdir(parents=True)
        (nested / "package.json").write_text(
            json.dumps({"name": "dep", "scripts": {"test": "echo hi"}}), encoding="utf-8",
        )
        verifier = ProjectVerifier(self.project_dir)
        self.assertEqual(verifier._find_node_projects(), [])


class TestRunTestsWithoutAnyStack(unittest.TestCase):
    def test_skips_when_neither_python_nor_node_tests_present(self):
        temp_dir = tempfile.mkdtemp()
        try:
            (Path(temp_dir) / "app.py").write_text("x = 1\n", encoding="utf-8")
            verifier = ProjectVerifier(temp_dir)
            report = verifier.run_tests()
            self.assertFalse(report.ran)
            self.assertTrue(report.passed)
            self.assertIn("npm-Test-Skript", report.reason_skipped)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestRealNpmTestExecution(unittest.TestCase):
    """Führt echtes `npm install` (ohne Abhängigkeiten, offline-sicher) + `npm test` aus."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_real_passing_npm_test_is_detected(self):
        _write_node_project(self.project_dir, 'console.log("ok"); process.exit(0);')
        verifier = ProjectVerifier(self.project_dir)
        verifier.ensure_environment()
        report = verifier.run_tests()

        self.assertTrue(report.ran)
        self.assertTrue(report.passed, msg=f"stdout={report.stdout}\nstderr={report.stderr}")
        self.assertIn("npm test", report.stdout)
        self.assertEqual(report.failures, [])

    def test_real_failing_npm_test_is_captured_with_output(self):
        _write_node_project(
            self.project_dir, 'console.error("Expected 3, got 2"); process.exit(1);',
        )
        verifier = ProjectVerifier(self.project_dir)
        verifier.ensure_environment()
        report = verifier.run_tests()

        self.assertTrue(report.ran)
        self.assertFalse(report.passed)
        self.assertGreater(len(report.failures), 0)
        # Kein Jest-artiges "FAIL <datei>"-Muster im rohen node-Skript -> generischer Fallback,
        # der den echten Output trägt (kein Keyword-Raten, siehe _parse_node_failures).
        self.assertIn("Expected 3, got 2", report.failures[0].message)

    def test_ensure_environment_installs_npm_dependencies(self):
        _write_node_project(self.project_dir, "process.exit(0);")
        verifier = ProjectVerifier(self.project_dir)
        result = verifier.ensure_environment()

        self.assertIn("npm install", result)
        self.assertIn("exit_code=0", result)
        # Ein abhängigkeitsfreies Projekt legt kein node_modules an (nichts zu installieren),
        # aber ein echt gelaufenes `npm install` schreibt IMMER eine package-lock.json.
        self.assertTrue((self.project_dir / "package-lock.json").exists())

    def test_combined_python_and_node_projects_both_run_and_and_semantics_apply(self):
        (self.project_dir / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        (self.project_dir / "test_app.py").write_text(
            "import unittest\nfrom app import add\n\n"
            "class TestAdd(unittest.TestCase):\n"
            "    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n",
            encoding="utf-8",
        )
        _write_node_project(self.project_dir, 'console.error("boom"); process.exit(1);', subdir="frontend")

        verifier = ProjectVerifier(self.project_dir)
        verifier.ensure_environment()
        report = verifier.run_tests()

        self.assertTrue(report.ran)
        # Python-Teil bestand, Node-Teil scheiterte -> Gesamtergebnis muss FALSE sein, ein
        # grüner Backend-Test darf ein rotes Frontend nicht überdecken.
        self.assertFalse(report.passed)
        self.assertIn("--- Python", report.stdout)
        self.assertIn("--- npm test (frontend)", report.stdout)


class TestNodeInstallCommandSelection(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("core.verifier.CodeSandbox.run_command")
    def test_uses_npm_ci_when_lockfile_present(self, mock_run):
        _write_node_project(self.project_dir, "process.exit(0);")
        (self.project_dir / "package-lock.json").write_text("{}", encoding="utf-8")
        mock_run.return_value = ExecutionResult(exit_code=0, stdout="", stderr="", duration_seconds=0.1)

        verifier = ProjectVerifier(self.project_dir)
        verifier.ensure_environment()

        mock_run.assert_called_once()
        self.assertEqual(mock_run.call_args[0][0][:2], ["npm", "ci"])

    @patch("core.verifier.CodeSandbox.run_command")
    def test_uses_npm_install_without_lockfile(self, mock_run):
        _write_node_project(self.project_dir, "process.exit(0);")
        mock_run.return_value = ExecutionResult(exit_code=0, stdout="", stderr="", duration_seconds=0.1)

        verifier = ProjectVerifier(self.project_dir)
        verifier.ensure_environment()

        mock_run.assert_called_once()
        self.assertEqual(mock_run.call_args[0][0][:2], ["npm", "install"])

    @patch("core.verifier.shutil.which", return_value=None)
    def test_missing_npm_is_reported_but_not_an_error(self, mock_which):
        _write_node_project(self.project_dir, "process.exit(0);")
        verifier = ProjectVerifier(self.project_dir)

        install_log = verifier.ensure_environment()
        self.assertIn("nicht installiert", install_log)

        report = verifier.run_tests()
        self.assertFalse(report.ran)
        self.assertIn("npm", report.reason_skipped)


class TestParseNodeFailures(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)
        (self.project_dir / "src").mkdir()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_jest_style_fail_line_and_stack_trace_are_parsed(self):
        output = (
            "FAIL src/App.test.js\n"
            "  ✕ renders correctly (5 ms)\n\n"
            "  at Object.<anonymous> (src/App.test.js:12:5)\n"
        )
        exec_result = ExecutionResult(exit_code=1, stdout=output, stderr="", duration_seconds=1.0)
        verifier = ProjectVerifier(self.project_dir)

        failures = verifier._parse_node_failures(exec_result, self.project_dir)

        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].test_id, "src/App.test.js")
        self.assertIn("src/App.test.js", failures[0].files)

    def test_fail_entry_message_carries_real_output_not_empty_string(self):
        # Regression: message wurde für per "FAIL <datei>"-Header erkannte Einträge bisher
        # IMMER als "" gesetzt - der Fix-Agent im Verifikations-Fix-Loop bekam dadurch nie die
        # tatsächliche Fehlermeldung zu sehen (siehe agents/orchestrator.py._run_verification_loop,
        # das failure.message direkt in die Fix-Task-Beschreibung einbettet).
        output = (
            "FAIL src/App.test.js\n"
            "  ● Test suite failed to run\n\n"
            "    SyntaxError: Cannot use import statement outside a module\n"
        )
        exec_result = ExecutionResult(exit_code=1, stdout=output, stderr="", duration_seconds=1.0)
        verifier = ProjectVerifier(self.project_dir)

        failures = verifier._parse_node_failures(exec_result, self.project_dir)

        self.assertEqual(len(failures), 1)
        self.assertNotEqual(failures[0].message, "")
        self.assertIn("Cannot use import statement outside a module", failures[0].message)

    def test_module_syntax_error_additionally_implicates_package_json(self):
        # Realer Fund (Pong-Projekt): ein Jest-ESM-Konfigurationsfehler ("Cannot use import
        # statement outside a module") wurde bisher AUSSCHLIESSLICH der Testdatei
        # zugeschrieben und landete deshalb beim tester-Agenten - die eigentliche Ursache
        # liegt aber in der Node-Projekt-Konfiguration (package.json), nicht in der
        # Testlogik. package.json muss deshalb zusätzlich in failure.files auftauchen, damit
        # der Fix-Loop auch dessen Owner (i.d.R. frontend/devops) adressiert.
        (self.project_dir / "package.json").write_text('{"name": "x"}', encoding="utf-8")
        output = (
            "FAIL ./game.test.js\n"
            "  ● Test suite failed to run\n\n"
            "    SyntaxError: Cannot use import statement outside a module\n"
        )
        exec_result = ExecutionResult(exit_code=1, stdout=output, stderr="", duration_seconds=1.0)
        verifier = ProjectVerifier(self.project_dir)

        failures = verifier._parse_node_failures(exec_result, self.project_dir)

        self.assertEqual(len(failures), 1)
        self.assertIn("package.json", failures[0].files)

    def test_windows_cmd_command_not_found_implicates_package_json(self):
        # Team-Optimierung (Logs-Tiefenanalyse logs/runs/ und logs/verification/): scheitert
        # `npm test` unter Windows bereits VOR jedem Testlauf, weil ein im npm-Skript
        # aufgerufener Befehl nicht gefunden wird, meldet cmd.exe das deutsch als "Der Befehl
        # "<x>" ist entweder falsch geschrieben oder konnte nicht gefunden werden." - dieses
        # Fehlerbild hat KEIN "FAIL <datei>"-Muster, landet also im generischen <npm test>-
        # Fallback, muss dabei aber trotzdem zwingend package.json implizieren, sonst landet
        # der Fix-Auftrag beim tester statt bei frontend/devops (siehe _route_failure_owners).
        (self.project_dir / "package.json").write_text('{"name": "x"}', encoding="utf-8")
        output = (
            "'vite' ist entweder falsch geschrieben oder konnte nicht gefunden werden.\n"
        )
        exec_result = ExecutionResult(exit_code=1, stdout=output, stderr="", duration_seconds=1.0)
        verifier = ProjectVerifier(self.project_dir)

        failures = verifier._parse_node_failures(exec_result, self.project_dir)

        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].test_id, "<npm test>")
        self.assertIn("package.json", failures[0].files)

    def test_windows_cmd_der_befehl_variant_implicates_package_json(self):
        # Variante mit dem Befehlsnamen in Anführungszeichen VOR "ist entweder falsch
        # geschrieben" (die tatsächliche cmd.exe-Formulierung, z.B. bei einem fehlenden
        # `npx`/`vitest` im PATH).
        (self.project_dir / "package.json").write_text('{"name": "x"}', encoding="utf-8")
        output = 'Der Befehl "vitest" ist entweder falsch geschrieben oder\n' \
                 "konnte nicht gefunden werden.\n"
        exec_result = ExecutionResult(exit_code=1, stdout=output, stderr="", duration_seconds=1.0)
        verifier = ProjectVerifier(self.project_dir)

        failures = verifier._parse_node_failures(exec_result, self.project_dir)

        self.assertIn("package.json", failures[0].files)

    def test_posix_command_not_found_implicates_package_json(self):
        (self.project_dir / "package.json").write_text('{"name": "x"}', encoding="utf-8")
        output = "sh: 1: vitest: command not found\n"
        exec_result = ExecutionResult(exit_code=127, stdout=output, stderr="", duration_seconds=1.0)
        verifier = ProjectVerifier(self.project_dir)

        failures = verifier._parse_node_failures(exec_result, self.project_dir)

        self.assertIn("package.json", failures[0].files)

    def test_windows_not_recognized_variant_implicates_package_json(self):
        (self.project_dir / "package.json").write_text('{"name": "x"}', encoding="utf-8")
        output = "'vitest' is not recognized as an internal or external command,\n" \
                 "operable program or batch file.\n"
        exec_result = ExecutionResult(exit_code=1, stdout=output, stderr="", duration_seconds=1.0)
        verifier = ProjectVerifier(self.project_dir)

        failures = verifier._parse_node_failures(exec_result, self.project_dir)

        self.assertIn("package.json", failures[0].files)

    def test_ordinary_assertion_failure_does_not_implicate_package_json(self):
        # Gegenprobe: ein ganz normaler Assertion-Fehlschlag (keine Konfigurations-
        # Fehlersignatur) darf package.json NICHT zusätzlich implizieren - sonst würde JEDER
        # Node-Testfehler künftig (auch) an frontend/devops zurückgespielt.
        (self.project_dir / "package.json").write_text('{"name": "x"}', encoding="utf-8")
        output = (
            "FAIL src/App.test.js\n"
            "  ✕ renders correctly (5 ms)\n\n"
            "    Expected 3, received 2\n"
            "  at Object.<anonymous> (src/App.test.js:12:5)\n"
        )
        exec_result = ExecutionResult(exit_code=1, stdout=output, stderr="", duration_seconds=1.0)
        verifier = ProjectVerifier(self.project_dir)

        failures = verifier._parse_node_failures(exec_result, self.project_dir)

        self.assertNotIn("package.json", failures[0].files)


if __name__ == "__main__":
    unittest.main()
