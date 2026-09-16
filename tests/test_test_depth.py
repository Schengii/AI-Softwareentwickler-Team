"""
tests/test_test_depth.py – Testet core/test_depth.py: Testtiefe-Analyse und den
Test-Schrumpfungs-Wächter (collect_test_function_names()).

Regressionsschutz für zwei reale Funde der KI-Team-Analyse (Lauf
entwickle_eventforge_ein_webhook, 20260916_154524):

1. `analyze_test_depth()` wurde in verification.py NICHT mehr aufgerufen, sobald der letzte
   Verifikations-Versuch über den "Abschlussprüfung nach letztem Fixversuch"-Sonderpfad (z.B.
   nach einer HEAVY_MODEL-Eskalation) erfolgreich war - das Kriterium `test_depth` blieb dadurch
   fälschlich `applicable: false`, obwohl das Projekt echte, ungetestete API-Routen hatte.
2. Eine Fix-Runde "behob" einen Testfehler, indem sie den fehlschlagenden Test ERSATZLOS
   LÖSCHTE, statt den zugrunde liegenden Fehler zu beheben (3 von 7 Tests verschwanden,
   darunter der einzige Test für die Kernfunktion des Projekts). `collect_test_function_names()`
   ist die Grundlage des Wächters in verification.py, der genau das erkennt.
"""

import tempfile
import unittest
from pathlib import Path

from core.test_depth import analyze_test_depth, collect_test_function_names


class TestCollectTestFunctionNames(unittest.TestCase):
    def test_collects_names_from_test_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "tests").mkdir()
            (project_dir / "tests" / "test_api.py").write_text(
                "def test_health():\n    pass\n\n"
                "async def test_create_bucket():\n    pass\n",
                encoding="utf-8",
            )
            names = collect_test_function_names(project_dir)
            self.assertEqual(names, {"test_health", "test_create_bucket"})

    def test_ignores_non_test_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app.py").write_text(
                "def test_looking_helper():\n    pass\n", encoding="utf-8",
            )
            names = collect_test_function_names(project_dir)
            self.assertEqual(names, set())

    def test_detects_shrinkage_between_two_snapshots(self):
        """Simuliert exakt den EventForge-Fund: eine Fix-Runde entfernt einen Test, statt den
        Fehler zu beheben - der Aufrufer in verification.py vergleicht zwei solche Snapshots."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            test_file = project_dir / "tests" / "test_api.py"
            test_file.parent.mkdir()
            test_file.write_text(
                "def test_health():\n    pass\n\n"
                "def test_forwarding_worker_mock():\n    pass\n",
                encoding="utf-8",
            )
            before = collect_test_function_names(project_dir)

            # Fix-Agent "behebt" den Fehler durch Löschen des betroffenen Tests.
            test_file.write_text("def test_health():\n    pass\n", encoding="utf-8")
            after = collect_test_function_names(project_dir)

            lost = before - after
            self.assertEqual(lost, {"test_forwarding_worker_mock"})
            self.assertLess(len(after), len(before))


class TestAnalyzeTestDepth(unittest.TestCase):
    def test_not_applicable_without_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = analyze_test_depth(tmp)
            self.assertFalse(report.applicable)
            self.assertTrue(report.passed)

    def test_detects_untested_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "main.py").write_text(
                '@app.get("/health")\ndef health(): pass\n\n'
                '@app.post("/api/buckets")\ndef create_bucket(): pass\n',
                encoding="utf-8",
            )
            (project_dir / "tests").mkdir()
            (project_dir / "tests" / "test_api.py").write_text(
                'def test_health():\n    client.get("/health")\n', encoding="utf-8",
            )
            report = analyze_test_depth(project_dir, min_ratio=0.6)
            self.assertTrue(report.applicable)
            labels = [r.label() for r in report.untested_routes]
            self.assertTrue(any("/api/buckets" in label for label in labels))


if __name__ == "__main__":
    unittest.main()
