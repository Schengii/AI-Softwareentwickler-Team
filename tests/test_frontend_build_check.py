"""
tests/test_frontend_build_check.py – Testet ProjectVerifier.check_frontend_build()

Realer Fund (KI-Team-Analyse, Punkt 1): bisher lief für ein Frontend-Projekt NUR `npm test`
(sofern überhaupt ein "test"-Skript existierte) - ein TypeScript-Typfehler, ein ungelöster
Import oder ungültiges JSX/CSS, das den PRODUKTIONS-Build (`npm run build`) bricht, blieb dabei
unentdeckt. check_frontend_build() führt jetzt einen echten `npm run build` für jedes gefundene
Frontend-Projekt aus (package.json mit "build"-Skript, z.B. unter frontend/ oder im Root).
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from core.verifier import ProjectVerifier


def _write_frontend_project(root: Path, build_script: str, subdir: str = "frontend") -> Path:
    project_dir = root if subdir == "." else root / subdir
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "package.json").write_text(
        json.dumps({"name": "sample-frontend", "version": "1.0.0", "private": True,
                    "scripts": {"build": build_script}}),
        encoding="utf-8",
    )
    (project_dir / "node_modules").mkdir(exist_ok=True)  # simuliert bereits installierte Abhängigkeiten
    return project_dir


class TestFindNodeBuildProjects(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_finds_package_json_with_build_script_under_frontend_dir(self):
        _write_frontend_project(self.project_dir, "vite build")
        verifier = ProjectVerifier(self.project_dir)
        found = verifier._find_node_build_projects()
        self.assertEqual(found, [(self.project_dir / "frontend").resolve()])

    def test_ignores_package_json_without_build_script(self):
        (self.project_dir / "package.json").write_text(
            json.dumps({"name": "no-build", "scripts": {"test": "echo test"}}), encoding="utf-8",
        )
        verifier = ProjectVerifier(self.project_dir)
        self.assertEqual(verifier._find_node_build_projects(), [])

    def test_project_with_both_test_and_build_script_is_found_by_both_finders(self):
        (self.project_dir / "package.json").write_text(
            json.dumps({"name": "full", "scripts": {"test": "echo test", "build": "vite build"}}),
            encoding="utf-8",
        )
        verifier = ProjectVerifier(self.project_dir)
        self.assertEqual(verifier._find_node_projects(), [self.project_dir.resolve()])
        self.assertEqual(verifier._find_node_build_projects(), [self.project_dir.resolve()])


class TestCheckFrontendBuild(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_real_successful_build_is_detected(self):
        # Echter, abhängigkeitsfreier Build ohne echtes Bundler-Tool: das "build"-Skript ist
        # bewusst ein einfacher Node-Einzeiler statt eines echten Vite-Builds (kein Netzwerk-
        # zugriff nötig) - genug, um exit_code 0 echt über `npm run build` laufen zu lassen.
        _write_frontend_project(self.project_dir, "node -e \"console.log('build ok')\"")
        verifier = ProjectVerifier(self.project_dir)

        reports = verifier.check_frontend_build()

        self.assertEqual(len(reports), 1)
        self.assertTrue(reports[0].attempted)
        self.assertTrue(reports[0].passed, msg=reports[0].output)
        self.assertEqual(reports[0].directory, "frontend")

    def test_real_failing_build_is_captured_with_output(self):
        _write_frontend_project(
            self.project_dir, "node -e \"console.error('TS2304: Cannot find name X'); process.exit(1);\"",
        )
        verifier = ProjectVerifier(self.project_dir)

        reports = verifier.check_frontend_build()

        self.assertEqual(len(reports), 1)
        self.assertTrue(reports[0].attempted)
        self.assertFalse(reports[0].passed)
        self.assertIn("TS2304", reports[0].output)

    def test_missing_node_modules_is_not_attempted(self):
        project_dir = self.project_dir / "frontend"
        project_dir.mkdir(parents=True)
        (project_dir / "package.json").write_text(
            json.dumps({"name": "no-deps", "scripts": {"build": "vite build"}}), encoding="utf-8",
        )
        verifier = ProjectVerifier(self.project_dir)

        reports = verifier.check_frontend_build()

        self.assertEqual(len(reports), 1)
        self.assertFalse(reports[0].attempted)
        self.assertTrue(reports[0].passed)  # nicht prüfbar != Fehlschlag
        self.assertIn("node_modules", reports[0].reason_skipped)

    def test_no_build_script_yields_no_reports(self):
        (self.project_dir / "app.py").write_text("x = 1\n", encoding="utf-8")
        verifier = ProjectVerifier(self.project_dir)
        self.assertEqual(verifier.check_frontend_build(), [])

    def test_missing_npm_is_reported_but_not_an_error(self):
        from unittest.mock import patch
        _write_frontend_project(self.project_dir, "vite build")
        with patch("core.verifier.runtime.shutil.which", return_value=None):
            verifier = ProjectVerifier(self.project_dir)
            reports = verifier.check_frontend_build()
        self.assertEqual(len(reports), 1)
        self.assertFalse(reports[0].attempted)
        self.assertTrue(reports[0].passed)
        self.assertIn("nicht installiert", reports[0].reason_skipped)


if __name__ == "__main__":
    unittest.main()
