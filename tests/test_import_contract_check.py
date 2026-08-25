"""
tests/test_import_contract_check.py – Testet die statische Import-Vertragsprüfung
(core/verifier.py.check_import_contracts())

Realer Fund: eine Testdatei importierte `import App from './App'` und rief `render(<App />)`
auf - `App.jsx` exportierte aber nur eine gleichnamige Utility-Funktion, keinen React-
Komponenten-Default-Export. Der echte Testlauf schlug zwar fehl, der Traceback zeigte aber nur
die Testdatei selbst (dort schlägt render() zur Laufzeit fehl), nie die Zieldatei mit dem
fehlenden Export - deren Autor wurde nie zur Korrektur aufgefordert. check_import_contracts()
erkennt genau diese Fehlerklasse VOR dem eigentlichen Testlauf, rein statisch.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from core.verifier import ProjectVerifier


class TestImportContractCheck(unittest.TestCase):
    def setUp(self):
        self.project_dir = tempfile.mkdtemp()
        self.verifier = ProjectVerifier(self.project_dir)

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)

    def _write(self, rel_path: str, content: str) -> None:
        path = Path(self.project_dir) / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_no_js_test_files_is_not_attempted(self):
        report = self.verifier.check_import_contracts()
        self.assertFalse(report.attempted)
        self.assertTrue(report.ok)

    def test_missing_default_export_is_detected(self):
        # Realer Fund, nachgebaut: App.jsx exportiert nur eine Utility-Funktion, keinen
        # Default-Export - App.test.jsx erwartet aber genau den.
        self._write("src/App.jsx", "export const validateUploadedFile = (file) => ({ valid: true });\n")
        self._write(
            "src/App.test.jsx",
            "import App from './App';\nimport { render } from '@testing-library/react';\n"
            "test('rendert', () => { render(<App />); });\n",
        )
        report = self.verifier.check_import_contracts()

        self.assertTrue(report.attempted)
        self.assertFalse(report.ok)
        self.assertEqual(len(report.issues), 1)
        issue = report.issues[0]
        self.assertEqual(issue.test_file, "src/App.test.jsx")
        self.assertEqual(issue.imported_file, "src/App.jsx")
        self.assertEqual(issue.missing_export, "default")

    def test_present_default_export_is_not_flagged(self):
        self._write("src/App.jsx", "export default function App() { return null; }\n")
        self._write(
            "src/App.test.jsx",
            "import App from './App';\ntest('rendert', () => { App(); });\n",
        )
        report = self.verifier.check_import_contracts()

        self.assertTrue(report.attempted)
        self.assertTrue(report.ok)
        self.assertEqual(report.issues, [])

    def test_missing_named_export_is_detected(self):
        self._write("src/utils.js", "export const foo = () => 1;\n")
        self._write(
            "src/utils.test.js",
            "import { bar } from './utils';\ntest('x', () => { bar(); });\n",
        )
        report = self.verifier.check_import_contracts()

        self.assertFalse(report.ok)
        self.assertEqual(report.issues[0].missing_export, "bar")

    def test_present_named_export_is_not_flagged(self):
        self._write("src/utils.js", "export const bar = () => 1;\n")
        self._write(
            "src/utils.test.js",
            "import { bar } from './utils';\ntest('x', () => { bar(); });\n",
        )
        report = self.verifier.check_import_contracts()

        self.assertTrue(report.ok)

    def test_import_target_missing_entirely_is_not_flagged_here(self):
        # Ein komplett fehlendes Ziel ist eine andere Fehlerklasse (echter Testlauf/Traceback
        # deckt das bereits ab) - check_import_contracts() prüft nur EXISTIERENDE Zieldateien.
        self._write(
            "src/App.test.jsx",
            "import App from './DoesNotExist';\ntest('x', () => { App(); });\n",
        )
        report = self.verifier.check_import_contracts()

        self.assertTrue(report.ok)
        self.assertEqual(report.issues, [])


if __name__ == "__main__":
    unittest.main()
