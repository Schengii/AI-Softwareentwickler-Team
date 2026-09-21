"""
tests/test_interface_contract.py – Testet P4-4 (ROADMAP_TEMP.md, Rest): "interface_contract.json
entsteht für Backend-only-Projekte nicht zuverlässig"

Realer Fund `synapsegate`: kein Frontend, die von agents/team_directives.py.ARCHITECT_CONTRACT_
DIRECTIVE geforderte interface_contract.json fehlte komplett, weil das eine reine LLM-Anweisung
ohne Garantie ist. core/interface_contract.py.ensure_interface_contract() trägt sie deterministisch
aus dem tatsächlich geschriebenen Code nach - NUR wenn sie noch fehlt, nie als Überschreibung
einer bereits vom architect geschriebenen Datei.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from core.interface_contract import INTERFACE_CONTRACT_FILE, ensure_interface_contract, generate_interface_contract


class TestGenerateInterfaceContract(unittest.TestCase):
    def setUp(self):
        self.project_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)

    def test_collects_top_level_classes_and_functions(self):
        (self.project_dir / "app").mkdir()
        (self.project_dir / "app" / "cache.py").write_text(
            "class CacheService:\n    def evict(self):\n        pass\n\n"
            "def build_cache():\n    pass\n",
            encoding="utf-8",
        )
        contract = generate_interface_contract(self.project_dir)
        self.assertEqual(contract["modules"]["app/cache.py"], {"CacheService": "class", "build_cache": "function"})

    def test_methods_and_private_symbols_are_excluded(self):
        (self.project_dir / "app").mkdir()
        (self.project_dir / "app" / "cache.py").write_text(
            "class CacheService:\n    def evict(self):\n        pass\n\n"
            "def _internal():\n    pass\n",
            encoding="utf-8",
        )
        contract = generate_interface_contract(self.project_dir)
        self.assertEqual(contract["modules"]["app/cache.py"], {"CacheService": "class"})

    def test_test_files_are_excluded(self):
        (self.project_dir / "tests").mkdir()
        (self.project_dir / "tests" / "test_cache.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
        contract = generate_interface_contract(self.project_dir)
        self.assertEqual(contract["modules"], {})

    def test_missing_project_dir_returns_empty_contract(self):
        contract = generate_interface_contract(self.project_dir / "nope")
        self.assertEqual(contract, {"modules": {}})


class TestEnsureInterfaceContract(unittest.TestCase):
    def setUp(self):
        self.project_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)

    def test_writes_contract_when_missing(self):
        (self.project_dir / "app").mkdir()
        (self.project_dir / "app" / "billing.py").write_text("def charge():\n    pass\n", encoding="utf-8")

        written = ensure_interface_contract(self.project_dir)

        self.assertTrue(written)
        path = self.project_dir / INTERFACE_CONTRACT_FILE
        self.assertTrue(path.exists())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["modules"]["app/billing.py"], {"charge": "function"})

    def test_never_overwrites_an_existing_contract(self):
        (self.project_dir / "app").mkdir()
        (self.project_dir / "app" / "billing.py").write_text("def charge():\n    pass\n", encoding="utf-8")
        existing = {"modules": {"app/billing.py": {"charge": "function", "Invoice": "class"}}}
        (self.project_dir / INTERFACE_CONTRACT_FILE).write_text(json.dumps(existing), encoding="utf-8")

        written = ensure_interface_contract(self.project_dir)

        self.assertFalse(written)
        data = json.loads((self.project_dir / INTERFACE_CONTRACT_FILE).read_text(encoding="utf-8"))
        self.assertEqual(data, existing)

    def test_no_symbols_means_no_file_written(self):
        # Leeres Projekt (z.B. reine Doku/Config) - kein Vertrag ableitbar, kein leeres Rauschen.
        written = ensure_interface_contract(self.project_dir)
        self.assertFalse(written)
        self.assertFalse((self.project_dir / INTERFACE_CONTRACT_FILE).exists())

    def test_never_writes_into_the_framework_root(self):
        # Realer Fund: ein Test mit project_dir="." (Framework-Root, siehe department.py-Docstring
        # "Tests rufen diese Methode mehrfach mit project_dir=\".\" auf") schrieb sonst eine
        # interface_contract.json mit dem gesamten Framework-Quellcode direkt ins Repo-Root.
        from config import BASE_DIR

        written = ensure_interface_contract(BASE_DIR)
        self.assertFalse(written)
        self.assertFalse((Path(BASE_DIR) / INTERFACE_CONTRACT_FILE).exists())


if __name__ == "__main__":
    unittest.main()
