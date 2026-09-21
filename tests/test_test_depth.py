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

from core.test_depth import analyze_domain_logic_depth, analyze_test_depth, collect_test_function_names


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


class TestAnalyzeDomainLogicDepth(unittest.TestCase):
    """P4-3 (ROADMAP_TEMP.md): ergänzendes Fachlogik-Signal - misst, ob öffentliche Funktionen
    in core/services/domain/logic in einem Test importiert UND aufgerufen werden, nicht nur, ob
    API-Routen getestet sind (real gemessen an cachegrid_proxy: 100% Routenabdeckung, aber
    komplett ungetestete Fachlogik)."""

    def test_not_applicable_without_domain_symbols(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = analyze_domain_logic_depth(tmp)
            self.assertFalse(report.applicable)
            self.assertTrue(report.passed)

    def test_not_applicable_without_any_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app" / "core").mkdir(parents=True)
            (project_dir / "app" / "core" / "cache.py").write_text(
                "def evict_lru():\n    pass\n", encoding="utf-8",
            )
            report = analyze_domain_logic_depth(project_dir)
            self.assertFalse(report.applicable)

    def test_detects_untested_domain_function(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app" / "core").mkdir(parents=True)
            (project_dir / "app" / "core" / "cache.py").write_text(
                "def evict_lru():\n    pass\n\ndef tag_key():\n    pass\n", encoding="utf-8",
            )
            (project_dir / "tests").mkdir()
            (project_dir / "tests" / "test_cache.py").write_text(
                "from app.core.cache import evict_lru\n\n"
                "def test_evict_lru():\n    evict_lru()\n",
                encoding="utf-8",
            )
            report = analyze_domain_logic_depth(project_dir, min_ratio=0.6)
            self.assertTrue(report.applicable)
            labels = [r.label() for r in report.untested_symbols]
            self.assertTrue(any("tag_key" in label for label in labels))
            self.assertFalse(any("evict_lru" in label for label in labels))

    def test_import_without_call_does_not_count_as_tested(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app" / "services").mkdir(parents=True)
            (project_dir / "app" / "services" / "billing.py").write_text(
                "def charge_customer():\n    pass\n", encoding="utf-8",
            )
            (project_dir / "tests").mkdir()
            (project_dir / "tests" / "test_billing.py").write_text(
                "from app.services.billing import charge_customer\n\n"
                "def test_placeholder():\n    pass\n",  # importiert, aber nie aufgerufen
                encoding="utf-8",
            )
            report = analyze_domain_logic_depth(project_dir)
            labels = [r.label() for r in report.untested_symbols]
            self.assertTrue(any("charge_customer" in label for label in labels))

    def test_private_symbols_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app" / "domain").mkdir(parents=True)
            (project_dir / "app" / "domain" / "orders.py").write_text(
                "def _internal_helper():\n    pass\n", encoding="utf-8",
            )
            (project_dir / "tests").mkdir()
            (project_dir / "tests" / "test_orders.py").write_text(
                "def test_something():\n    pass\n", encoding="utf-8",
            )
            report = analyze_domain_logic_depth(project_dir)
            self.assertFalse(report.applicable)  # kein öffentliches Symbol -> nichts zu messen

    def test_detects_domain_symbol_by_filename_stem(self):
        """Prüft, dass Dateien wie app/engine.py auch ohne core/services-Verzeichnis als Domain erfasst werden."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "app").mkdir(parents=True)
            (project_dir / "app" / "engine.py").write_text(
                "class MetricEngine:\n    def calculate(self):\n        pass\n", encoding="utf-8",
            )
            (project_dir / "tests").mkdir()
            (project_dir / "tests" / "test_engine.py").write_text(
                "from app.engine import MetricEngine\n\n"
                "def test_engine():\n    e = MetricEngine()\n    e.calculate()\n",
                encoding="utf-8",
            )
            report = analyze_domain_logic_depth(project_dir)
            self.assertTrue(report.applicable)
            self.assertTrue(report.passed)
            self.assertEqual(len(report.untested_symbols), 0)


if __name__ == "__main__":
    unittest.main()
