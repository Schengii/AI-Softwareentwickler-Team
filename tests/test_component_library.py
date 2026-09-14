"""
tests/test_component_library.py – Testet core/component_library.py (Cross-Projekt-Bibliothek
verifizierter, wiederverwendbarer Infrastruktur-Bausteine).

Gesamtsystem-Analyse 2026-09-14, Punkt 3.2: der chronospulse-Lauf lieferte einen 5-zeiligen
Kommentar-Stub statt eines echten CircuitBreaker - harvest_from_project() darf so einen Stub
NIEMALS übernehmen, muss aber eine echte, vollständige Implementierung erkennen und mit
Provenienz in die Bibliothek aufnehmen.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import core.component_library as component_library
from core.component_library import (
    MAX_LIBRARY_ENTRIES_PER_CATEGORY,
    get_snippet_content,
    harvest_from_project,
    search,
)

_REAL_CIRCUIT_BREAKER = '''
class CircuitBreaker:
    """Echter Circuit Breaker mit CLOSED/OPEN/HALF_OPEN-Zustand."""

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 30.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.failure_count = 0
        self.state = "CLOSED"
        self.opened_at = 0.0

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = "CLOSED"

    def record_failure(self) -> None:
        import time
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            self.opened_at = time.monotonic()

    def allow_request(self) -> bool:
        import time
        if self.state == "OPEN" and time.monotonic() - self.opened_at > self.cooldown_seconds:
            self.state = "HALF_OPEN"
        return self.state != "OPEN"


class UnrelatedHelper:
    def noop(self):
        pass
'''

_STUB_CIRCUIT_BREAKER = '''
class CircuitBreaker:
    # Auszug aus app/utils/resilience.py
    # - CircuitBreaker: Statusverwaltung (CLOSED, OPEN, HALF_OPEN), Failure Thresholds, Cooldown
    pass
'''


class TestHarvestFromProject(unittest.TestCase):
    def setUp(self):
        self.library_dir = tempfile.mkdtemp()
        self._patcher = patch.object(component_library, "LIBRARY_DIR", Path(self.library_dir) / "component_library")
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        manifest_patcher = patch.object(
            component_library, "MANIFEST_FILE",
            Path(self.library_dir) / "component_library" / "manifest.json",
        )
        manifest_patcher.start()
        self.addCleanup(manifest_patcher.stop)

        self.project_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.library_dir, ignore_errors=True)
        shutil.rmtree(self.project_dir, ignore_errors=True)

    def _write(self, rel_path: str, content: str) -> Path:
        path = Path(self.project_dir) / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_real_implementation_is_harvested(self):
        self._write("app/utils/resilience.py", _REAL_CIRCUIT_BREAKER)

        added = harvest_from_project(self.project_dir, "testprojekt")

        self.assertEqual(len(added), 1)
        results = search("circuit breaker")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["category"], "circuit_breaker")
        self.assertEqual(results[0]["source_project"], "testprojekt")
        content = get_snippet_content(results[0]["id"])
        self.assertIn("record_failure", content)

    def test_export_default_class_is_harvested(self):
        """Folgeanalyse 2026-09-14, Befund 4: 'export default class' (Standard-TS-Konvention
        für genau eine Hauptklasse pro Datei) wurde bisher NICHT erkannt, nur 'export class'."""
        ts_circuit_breaker = (
            "export default class CircuitBreaker {\n"
            "  private failureCount = 0;\n"
            "  private state = 'CLOSED';\n"
            "  constructor(private threshold = 5, private cooldownMs = 30000) {}\n"
            "  recordSuccess(): void {\n"
            "    this.failureCount = 0;\n"
            "    this.state = 'CLOSED';\n"
            "  }\n"
            "  recordFailure(): void {\n"
            "    this.failureCount += 1;\n"
            "    if (this.failureCount >= this.threshold) this.state = 'OPEN';\n"
            "  }\n"
            "}\n"
        )
        self._write("resilience.ts", ts_circuit_breaker)

        added = harvest_from_project(self.project_dir, "ts_projekt")
        self.assertEqual(len(added), 1)

    def test_export_abstract_class_is_harvested(self):
        self._write("base_repo.ts", "export abstract class Repository {\n" + "\n".join(f"  method{i}() {{}}" for i in range(10)) + "\n}\n")
        added = harvest_from_project(self.project_dir, "ts_projekt")
        self.assertEqual(len(added), 1)

    def test_leading_decorator_is_preserved_when_harvesting(self):
        """Folgeanalyse 2026-09-14, Befund 4: ein vorangehender Decorator (@dataclass) ist
        potenziell verhaltensrelevant (generiert z.B. automatisch __init__/__eq__) und darf
        beim Ernten nicht verloren gehen."""
        decorated = "@dataclass\n" + _REAL_CIRCUIT_BREAKER.strip()
        self._write("app/resilience.py", decorated)

        harvest_from_project(self.project_dir, "testprojekt")
        results = search("circuit breaker")
        self.assertEqual(len(results), 1)
        content = get_snippet_content(results[0]["id"])
        self.assertTrue(content.startswith("@dataclass"))

    def test_chronospulse_style_stub_is_rejected(self):
        """Der reale chronospulse-Fund: 5 Zeilen Kommentar statt Implementierung - darf NIE in
        die Bibliothek gelangen, sonst würde ein künftiges Projekt genau diesen Stub als
        vermeintlich verifizierten Baustein übernehmen."""
        self._write("app/utils/resilience.py", _STUB_CIRCUIT_BREAKER)

        added = harvest_from_project(self.project_dir, "chronospulse")

        self.assertEqual(added, [])
        self.assertEqual(search("circuit breaker"), [])

    def test_identical_component_from_second_project_is_not_duplicated(self):
        self._write("app/resilience.py", _REAL_CIRCUIT_BREAKER)
        first = harvest_from_project(self.project_dir, "projekt_eins")

        other_project = tempfile.mkdtemp()
        try:
            (Path(other_project) / "app").mkdir()
            (Path(other_project) / "app" / "resilience.py").write_text(_REAL_CIRCUIT_BREAKER, encoding="utf-8")
            second = harvest_from_project(other_project, "projekt_zwei")
        finally:
            import shutil
            shutil.rmtree(other_project, ignore_errors=True)

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])  # bytegleicher Inhalt -> kein Duplikat

    def test_nonexistent_project_dir_returns_empty_without_raising(self):
        added = harvest_from_project(Path(self.project_dir) / "existiert-nicht", "phantom")
        self.assertEqual(added, [])

    def test_category_is_pruned_beyond_max_entries(self):
        for i in range(MAX_LIBRARY_ENTRIES_PER_CATEGORY + 3):
            code = _REAL_CIRCUIT_BREAKER.replace("CircuitBreaker", f"CircuitBreakerV{i}")
            self._write(f"variant_{i}.py", code)
        harvest_from_project(self.project_dir, "vielfalt_projekt")

        results = search("circuit", limit=100)
        self.assertLessEqual(len(results), MAX_LIBRARY_ENTRIES_PER_CATEGORY)


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.library_dir = tempfile.mkdtemp()
        self._patcher = patch.object(component_library, "LIBRARY_DIR", Path(self.library_dir) / "component_library")
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        manifest_patcher = patch.object(
            component_library, "MANIFEST_FILE",
            Path(self.library_dir) / "component_library" / "manifest.json",
        )
        manifest_patcher.start()
        self.addCleanup(manifest_patcher.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.library_dir, ignore_errors=True)

    def test_empty_library_returns_empty_results(self):
        self.assertEqual(search("irgendwas"), [])

    def test_unreadable_manifest_does_not_raise(self):
        component_library.MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
        component_library.MANIFEST_FILE.write_text("{kaputtes json", encoding="utf-8")
        self.assertEqual(search("irgendwas"), [])


class TestAtomicManifestWrite(unittest.TestCase):
    """Folgeanalyse 2026-09-14, Befund 3: manifest.json wurde bisher NICHT atomar geschrieben
    (direktes write_text() statt Temp-Datei + os.replace() wie core/backlog_store.py) - bei den
    standardmäßig 2 parallelen Dashboard-Jobs (DASHBOARD_MAX_CONCURRENT_JOBS) ein reales
    Korruptions-/Datenverlustrisiko, siehe core/backlog_store.py._save_raw()-Docstring für den
    dort bereits einmal ECHT reproduzierten Vorfall."""

    def setUp(self):
        self.library_dir = tempfile.mkdtemp()
        self._patcher = patch.object(component_library, "LIBRARY_DIR", Path(self.library_dir) / "component_library")
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self._manifest_patcher = patch.object(
            component_library, "MANIFEST_FILE",
            Path(self.library_dir) / "component_library" / "manifest.json",
        )
        self._manifest_patcher.start()
        self.addCleanup(self._manifest_patcher.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.library_dir, ignore_errors=True)

    def test_no_leftover_temp_files_after_save(self):
        component_library._save_manifest([{"id": "x", "category": "circuit_breaker"}])
        tmp_files = list(component_library.MANIFEST_FILE.parent.glob("*.tmp-*"))
        self.assertEqual(tmp_files, [], "Temp-Datei wurde nicht per os.replace() aufgeräumt")
        self.assertTrue(component_library.MANIFEST_FILE.exists())

    def test_concurrent_reads_during_writes_never_see_a_torn_file(self):
        """Analog zu tests/test_backlog_store.py::test_concurrent_reads_during_writes_never_
        see_a_torn_file - bewusst NUR ein Writer-Thread (mehrere gleichzeitige Writer haben ein
        separates, hier nicht behobenes Lost-Update-Problem ohne Sperre, siehe dortiger
        Docstring). Der Writer schreibt DURCHGEHEND ein NICHT-leeres Manifest - ein Leser darf
        während eines laufenden Schreibvorgangs NIE eine leere Liste sehen (das wäre exakt das
        Symptom eines torn reads: kaputtes/abgeschnittenes JSON landet im JSONDecodeError-
        Fallback von _load_manifest(), der das - wie bei core/backlog_store.py._load_raw() -
        STILLSCHWEIGEND als 'keine Einträge' behandelt statt als Fehler)."""
        import threading
        import time as time_module

        component_library._save_manifest([{"id": "seed", "category": "circuit_breaker", "preview": ""}])
        stop = threading.Event()
        saw_empty = threading.Event()
        big_preview = "x" * 200_000

        def _writer():
            i = 0
            while not stop.is_set():
                entry = {"id": f"writer-{i % 5}", "category": "circuit_breaker", "preview": big_preview}
                component_library._save_manifest([entry])
                i += 1

        def _reader():
            while not stop.is_set():
                if component_library._load_manifest() == []:
                    saw_empty.set()
                    return

        writer_thread = threading.Thread(target=_writer)
        reader_threads = [threading.Thread(target=_reader) for _ in range(5)]
        for t in [writer_thread, *reader_threads]:
            t.start()
        time_module.sleep(1.0)
        stop.set()
        for t in [writer_thread, *reader_threads]:
            t.join(timeout=5)

        self.assertFalse(saw_empty.is_set(), "_load_manifest() sah während gleichzeitiger Writes eine leere/kaputte Datei")


if __name__ == "__main__":
    unittest.main()
