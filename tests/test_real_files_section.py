"""
tests/test_real_files_section.py – Testet Orchestrator._build_real_files_section()

Realer Fund (aus einem echten End-to-End-Testlauf): die finale LLM-Synthese
(ResultAggregator.synthesize()) zeigte Code, der NICHT mit der tatsächlich geschriebenen
Datei übereinstimmte – das Modell paraphrasierte/rekonstruierte Code aus den Agenten-
Berichten statt ihn wortgetreu zu übernehmen (bei zwei verschiedenen Aufrufen sogar zwei
UNTERSCHIEDLICHE, beide von der echten Datei abweichende Versionen). Ein echtes
Vertrauensproblem für jeden, der nur den Chat-Output liest, statt die Dateien selbst zu
prüfen. _build_real_files_section() liest die WIRKLICH geschriebenen Dateien direkt von der
Platte (kein LLM-Aufruf, daher immer exakt korrekt) und wird zusätzlich zur (jetzt bewusst
code-freien) LLM-Synthese in die finale Antwort eingefügt.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from agents.orchestrator import Orchestrator


class TestBuildRealFilesSection(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_empty_file_owners_returns_empty_string(self):
        self.assertEqual(self.orchestrator._build_real_files_section(self.temp_dir, {}), "")

    def test_reads_the_real_file_content_verbatim(self):
        real_code = "from fastapi import FastAPI\n\napp = FastAPI()\n"
        (Path(self.temp_dir) / "main.py").write_text(real_code, encoding="utf-8")

        section = self.orchestrator._build_real_files_section(self.temp_dir, {"main.py": "backend"})

        self.assertIn("main.py", section)
        self.assertIn(real_code.strip(), section)
        self.assertIn("```python", section)

    def test_multiple_files_all_appear_sorted(self):
        (Path(self.temp_dir) / "b_file.py").write_text("x = 2\n", encoding="utf-8")
        (Path(self.temp_dir) / "a_file.py").write_text("x = 1\n", encoding="utf-8")

        section = self.orchestrator._build_real_files_section(
            self.temp_dir, {"b_file.py": "backend", "a_file.py": "backend"},
        )

        self.assertLess(section.index("a_file.py"), section.index("b_file.py"))

    def test_picks_language_fence_from_extension(self):
        (Path(self.temp_dir) / "config.json").write_text('{"key": "value"}', encoding="utf-8")
        section = self.orchestrator._build_real_files_section(self.temp_dir, {"config.json": "backend"})
        self.assertIn("```json", section)

    def test_long_file_is_truncated_with_a_note(self):
        long_content = "x = 1\n" * 2000  # deutlich über MAX_CHARS_PER_REAL_FILE
        (Path(self.temp_dir) / "big.py").write_text(long_content, encoding="utf-8")

        section = self.orchestrator._build_real_files_section(self.temp_dir, {"big.py": "backend"})

        self.assertIn("gekürzt", section)
        self.assertLess(len(section), len(long_content))

    def test_missing_file_is_skipped_without_crashing(self):
        # file_owners kann eine Datei referenzieren, die zwischenzeitlich gelöscht wurde
        # (z.B. durch project_cleaner) - darf den ganzen Bericht nicht zum Absturz bringen.
        section = self.orchestrator._build_real_files_section(self.temp_dir, {"does_not_exist.py": "backend"})
        self.assertEqual(section, "### 📁 Tatsächlich geschriebene Dateien (direkt von der Platte gelesen, nicht vom LLM reproduziert)")

    def test_binary_file_is_skipped_without_crashing(self):
        (Path(self.temp_dir) / "image.bin").write_bytes(bytes(range(256)))
        section = self.orchestrator._build_real_files_section(self.temp_dir, {"image.bin": "backend"})
        self.assertNotIn("image.bin", section)  # konnte nicht als Text gelesen werden -> übersprungen

    def test_many_files_respect_total_char_budget(self):
        file_owners = {}
        for i in range(20):
            name = f"file_{i}.py"
            (Path(self.temp_dir) / name).write_text("y = 1\n" * 1000, encoding="utf-8")
            file_owners[name] = "backend"

        section = self.orchestrator._build_real_files_section(self.temp_dir, file_owners)

        self.assertIn("weitere Dateien gekürzt", section)
        self.assertLessEqual(len(section), self.orchestrator.MAX_TOTAL_REAL_FILES_CHARS + 5000)


if __name__ == "__main__":
    unittest.main()
