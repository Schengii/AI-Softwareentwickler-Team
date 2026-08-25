"""
tests/test_code_sandbox_encoding.py – Testet, dass CodeSandbox.run_command() echte UTF-8-
Ausgabe verarbeitet, unabhängig von der System-Codepage.

Realer Fund (echter Lauf gegen workspace/gui-enhancements): ein `npm test`-Lauf (Jest) lieferte
UTF-8-Bytes (✓/✗-Symbole), die auf einem deutschen Windows per Standard-Codepage (cp1252) NICHT
dekodierbar sind - subprocess.run(text=True) ohne explizites encoding= crashte dabei SCHWEIGEND
im internen Pipe-Reader-Thread und lieferte stdout/stderr als None zurück statt eines Strings,
was core/verifier.py.run_tests() beim anschließenden "\n".join(...) mit einem TypeError
abstürzen ließ - der komplette Orchestrator-Lauf brach hart ab, statt die Verifikation nur als
fehlgeschlagen zu melden.
"""

import sys
import unittest

from core.code_sandbox import CodeSandbox


class TestCodeSandboxEncoding(unittest.TestCase):
    def test_utf8_stdout_is_captured_without_crashing(self):
        # Schreibt bewusst Zeichen, die in cp1252 nicht existieren (z. B. das Jest-Häkchen ✓
        # und ostasiatische Zeichen), direkt als UTF-8-Bytes auf stdout - genau die Situation,
        # die den realen Absturz auslöste.
        script = "import sys; sys.stdout.buffer.write('✓ 世界 äöü'.encode('utf-8'))"
        result = CodeSandbox.run_command([sys.executable, "-c", script], timeout_seconds=10.0)

        self.assertEqual(result.exit_code, 0)
        self.assertIsInstance(result.stdout, str)
        self.assertIn("✓", result.stdout)
        self.assertIn("世界", result.stdout)

    def test_stderr_is_also_captured_without_crashing(self):
        script = "import sys; sys.stderr.buffer.write('Fehler: ✗ Ünïcödé'.encode('utf-8')); sys.exit(1)"
        result = CodeSandbox.run_command([sys.executable, "-c", script], timeout_seconds=10.0)

        self.assertEqual(result.exit_code, 1)
        self.assertIsInstance(result.stderr, str)
        self.assertIn("✗", result.stderr)


if __name__ == "__main__":
    unittest.main()
