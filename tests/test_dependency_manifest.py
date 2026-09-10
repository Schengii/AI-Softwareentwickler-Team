"""
tests/test_dependency_manifest.py – Testet core/dependency_manifest.py.

Realer Fund (auditlog_sentinel, 2026-09-10): requirements.txt wurde von 6 Agenten-Aufrufen
innerhalb von 73 Sekunden per write_file komplett überschrieben, die jeweils letzte Fassung
gewann - `alembic` fehlte am Ende trotzdem. core/dependency_manifest.add_requirement() trägt
stattdessen EIN Paket idempotent ein, ohne die Datei neu zu schreiben.
"""

import tempfile
import unittest
from pathlib import Path

from core.dependency_manifest import (
    add_requirement,
    is_valid_requirement_spec,
    listed_requirements,
    normalize_package_name,
    package_from_finding,
    primary_python_manifest,
    requirement_name,
)


class TestNormalizeAndParse(unittest.TestCase):
    def test_normalize_treats_dash_underscore_dot_as_equal(self):
        self.assertEqual(normalize_package_name("Foo_Bar.Baz"), "foo-bar-baz")
        self.assertEqual(normalize_package_name("foo-bar-baz"), "foo-bar-baz")

    def test_requirement_name_extracts_from_versioned_spec(self):
        self.assertEqual(requirement_name("SQLAlchemy>=2.0,<3.0"), "sqlalchemy")
        self.assertEqual(requirement_name("python-jose[cryptography]==3.3.0"), "python-jose")

    def test_requirement_name_ignores_comments_and_options(self):
        self.assertIsNone(requirement_name("# a comment"))
        self.assertIsNone(requirement_name(""))
        self.assertIsNone(requirement_name("-e ."))
        self.assertIsNone(requirement_name("git+https://example.com/foo.git"))

    def test_is_valid_requirement_spec(self):
        self.assertTrue(is_valid_requirement_spec("alembic"))
        self.assertTrue(is_valid_requirement_spec("sqlalchemy>=2.0"))
        self.assertTrue(is_valid_requirement_spec("python-jose[cryptography]==3.3.0"))
        self.assertTrue(is_valid_requirement_spec('uvicorn; python_version >= "3.8"'))
        self.assertFalse(is_valid_requirement_spec(""))
        self.assertFalse(is_valid_requirement_spec("rm -rf /"))
        self.assertFalse(is_valid_requirement_spec("git+https://example.com/foo.git"))


class TestAddRequirement(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.manifest = Path(self.tmp.name) / "requirements.txt"

    def tearDown(self):
        self.tmp.cleanup()

    def test_adds_to_new_file(self):
        added = add_requirement(self.manifest, "alembic")
        self.assertTrue(added)
        self.assertIn("alembic", listed_requirements(self.manifest))

    def test_appends_without_touching_existing_lines(self):
        self.manifest.write_text("fastapi\nuvicorn\n", encoding="utf-8")
        add_requirement(self.manifest, "asyncpg")
        text = self.manifest.read_text(encoding="utf-8")
        self.assertEqual(text, "fastapi\nuvicorn\nasyncpg\n")

    def test_adds_final_newline_before_appending_if_missing(self):
        self.manifest.write_text("fastapi", encoding="utf-8")
        add_requirement(self.manifest, "uvicorn")
        self.assertEqual(self.manifest.read_text(encoding="utf-8"), "fastapi\nuvicorn\n")

    def test_idempotent_same_package_twice(self):
        add_requirement(self.manifest, "alembic")
        added_again = add_requirement(self.manifest, "alembic")
        self.assertFalse(added_again)
        self.assertEqual(self.manifest.read_text(encoding="utf-8").count("alembic"), 1)

    def test_idempotent_across_naming_variants(self):
        add_requirement(self.manifest, "python-jose")
        added_again = add_requirement(self.manifest, "python_jose==3.3.0")
        self.assertFalse(added_again)

    def test_rejects_invalid_spec_without_writing(self):
        with self.assertRaises(ValueError):
            add_requirement(self.manifest, "rm -rf /")
        self.assertFalse(self.manifest.exists())

    def test_simulated_parallel_writers_all_survive(self):
        # Realer Fund: 6 parallele write_file-Aufrufe überschrieben sich gegenseitig.
        # add_requirement() für dieselbe Datei nacheinander darf keinen Eintrag verlieren.
        for pkg in ("alembic", "asyncpg", "greenlet", "httpx", "greenlet", "alembic"):
            add_requirement(self.manifest, pkg)
        listed = listed_requirements(self.manifest)
        for pkg in ("alembic", "asyncpg", "greenlet", "httpx"):
            self.assertIn(pkg, listed)


class TestPackageFromFinding(unittest.TestCase):
    def test_extracts_from_completeness_message(self):
        msg = (
            "Projekt importiert `alembic` (erwartetes PyPI-Paket `alembic`), aber kein "
            "Dependency-Manifest listet es auf - pip install ..."
        )
        self.assertEqual(package_from_finding(msg), "alembic")

    def test_extracts_from_pre_flight_suggestion(self):
        self.assertEqual(package_from_finding("Fuege `httpx` zu requirements.txt hinzu."), "httpx")

    def test_returns_none_for_unstructured_text(self):
        self.assertIsNone(package_from_finding("Irgendein anderes Problem, kein Paketname."))

    def test_returns_none_for_invalid_extracted_spec(self):
        self.assertIsNone(package_from_finding("Fuege `; rm -rf /` zu requirements.txt hinzu."))


class TestPrimaryPythonManifest(unittest.TestCase):
    def test_none_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(primary_python_manifest(Path(tmp)))

    def test_found_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "requirements.txt"
            path.write_text("fastapi\n", encoding="utf-8")
            self.assertEqual(primary_python_manifest(Path(tmp)), path)


if __name__ == "__main__":
    unittest.main()
