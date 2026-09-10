"""
tests/test_write_guard.py – Testet core/write_guard.py.

Realer Fund (auditlog_sentinel, 2026-09-10):
1. Rollengrenzen: architect überschrieb app/config.py, frontend app/main.py, documentation
   app/models.py -> check_write_scope() (config.AGENT_WRITE_SCOPES).
2. Schnittstellen-Drift: eine Neufassung von app/config.py entfernte `settings`, das drei
   andere Dateien importierten - das Projekt war danach nicht mehr importierbar ->
   check_contract_preserved().
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.write_guard import check_contract_preserved, check_write_scope, find_importers_of, top_level_symbols


class TestWriteScope(unittest.TestCase):
    def test_documentation_may_not_write_python(self):
        error = check_write_scope("documentation", "app/main.py")
        self.assertIsNotNone(error)
        self.assertIn("documentation", error)

    def test_documentation_may_write_markdown(self):
        self.assertIsNone(check_write_scope("documentation", "README.md"))

    def test_frontend_may_not_write_python(self):
        self.assertIsNotNone(check_write_scope("frontend", "app/main.py"))

    def test_frontend_may_write_frontend_files(self):
        self.assertIsNone(check_write_scope("frontend", "src/App.tsx"))
        self.assertIsNone(check_write_scope("frontend", "package.json"))

    def test_architect_may_write_adr_and_openapi_not_arbitrary_python(self):
        self.assertIsNone(check_write_scope("architect", "openapi.yaml"))
        self.assertIsNone(check_write_scope("architect", "docs/adr/0001-foo.md"))
        self.assertIsNotNone(check_write_scope("architect", "app/main.py"))

    def test_backend_is_unrestricted(self):
        # backend hat KEINEN Eintrag in AGENT_WRITE_SCOPES -> unbeschränkt.
        self.assertIsNone(check_write_scope("backend", "app/main.py"))
        self.assertIsNone(check_write_scope("backend", "anything/at/all.py"))

    def test_gate_can_be_disabled_via_config(self):
        with patch("config.ENABLE_ROLE_WRITE_SCOPES", False):
            self.assertIsNone(check_write_scope("documentation", "app/main.py"))

    def test_unknown_agent_is_unrestricted(self):
        self.assertIsNone(check_write_scope("some_future_agent", "app/main.py"))


class TestTopLevelSymbols(unittest.TestCase):
    def test_finds_functions_classes_and_assignments(self):
        source = "def foo(): pass\nclass Bar: pass\nBAZ = 1\n"
        self.assertEqual(top_level_symbols(source), {"foo", "Bar", "BAZ"})

    def test_finds_instance_assignment_pattern(self):
        source = "class Settings: pass\nsettings = Settings()\n"
        self.assertIn("settings", top_level_symbols(source))

    def test_returns_none_on_syntax_error(self):
        self.assertIsNone(top_level_symbols("def foo(:\n"))

    def test_returns_none_on_star_import(self):
        self.assertIsNone(top_level_symbols("from os import *\n"))

    def test_symbols_inside_try_except_are_found(self):
        source = "try:\n    import orjson as json\nexcept ImportError:\n    import json\n"
        self.assertIn("json", top_level_symbols(source))


class TestContractPreserved(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "app").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, rel_path: str, content: str) -> None:
        target = self.root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def test_removing_symbol_still_imported_elsewhere_is_rejected(self):
        self._write("app/config.py", "class Settings:\n    pass\n\nsettings = Settings()\n")
        self._write("app/auth.py", "from app.config import settings\n")
        old = (self.root / "app/config.py").read_text(encoding="utf-8")
        new = "class Settings:\n    pass\n"  # `settings` entfernt
        error = check_contract_preserved(self.root, "app/config.py", old, new)
        self.assertIsNotNone(error)
        self.assertIn("app/auth.py", error)
        self.assertIn("settings", error)

    def test_removing_unused_symbol_is_allowed(self):
        self._write("app/config.py", "class Settings:\n    pass\n\nUNUSED = 1\n")
        old = (self.root / "app/config.py").read_text(encoding="utf-8")
        new = "class Settings:\n    pass\n"
        self.assertIsNone(check_contract_preserved(self.root, "app/config.py", old, new))

    def test_keeping_symbol_as_alias_is_allowed(self):
        self._write("app/config.py", "class Settings:\n    pass\n\nsettings = Settings()\n")
        self._write("app/auth.py", "from app.config import settings\n")
        old = (self.root / "app/config.py").read_text(encoding="utf-8")
        new = "class Settings:\n    pass\n\nsettings = Settings()\nextra = 1\n"
        self.assertIsNone(check_contract_preserved(self.root, "app/config.py", old, new))

    def test_non_python_files_are_never_checked(self):
        self.assertIsNone(check_contract_preserved(self.root, "README.md", "old", "new"))

    def test_find_importers_of_matches_relative_imports(self):
        self._write("app/__init__.py", "")
        self._write("app/config.py", "settings = 1\n")
        self._write("app/auth.py", "from .config import settings\n")
        hits = find_importers_of(self.root, "app/config.py", {"settings"})
        self.assertIn(("app/auth.py", "settings"), hits)


if __name__ == "__main__":
    unittest.main()
