"""
tests/test_failure_triage.py – Strukturelle Fehler-Triage im Test-Fix-Loop

Sichert core/failure_triage.py und dessen Anbindung an
agents/orchestrator/verification._route_failure_owners() ab:
- Schnittstellen-Drift (Klasse EncryptionService vs. `from ... import encrypt`) geht an den
  Konsumenten, ein vertraglich vereinbartes, aber fehlendes Symbol an den Anbieter.
- SyntaxError, Settings ohne Dev-Defaults und lokale ModuleNotFoundErrors landen nie beim
  Manifest-Owner (requirements.txt).
- pytest-Collection-Blöcke werden vollständig geparst, Manifeste bei Strukturfehlern zurückgesetzt.
"""

import json
import tempfile
import unittest
from pathlib import Path

from agents.orchestrator.verification import _route_failure_owners
from core.code_sandbox import ExecutionResult
from core.failure_triage import (
    KIND_INTERFACE_DRIFT,
    KIND_MISSING_LOCAL_MODULE,
    KIND_MISSING_SYMBOL,
    KIND_SETTINGS_DEFAULTS,
    KIND_SYNTAX_ERROR,
    KIND_TEST_IMPORT_PATH,
    blocking_failures_first,
    find_contract_violations,
    restore_dependency_manifests,
    snapshot_dependency_manifests,
    triage_structural_failure,
)
from core.verifier.models import TestFailure
from core.verifier.testrunner import TestRunnerMixin

_ENCRYPTION_MODULE = '''
class EncryptionService:
    def __init__(self, key: bytes) -> None:
        self._key = key

    def encrypt(self, data: bytes) -> bytes:
        return data[::-1]

    def decrypt(self, token: bytes) -> bytes:
        return token[::-1]
'''
_IMPORT_ENCRYPT_MESSAGE = (
    "ERROR collecting tests/unit/test_encryption.py\n"
    "ImportError while importing test module 'tests/unit/test_encryption.py'.\n"
    "tests\\unit\\test_encryption.py:3: in <module>\n"
    "    from app.core.encryption import encrypt\n"
    "E   ImportError: cannot import name 'encrypt' from 'app.core.encryption' (app\\core\\encryption.py)"
)
_OWNERS = {
    "app/core/encryption.py": "backend",
    "app/core/config.py": "backend",
    "tests/unit/test_encryption.py": "tester",
    "requirements.txt": "refactoring",
}
_AGENTS = {"backend", "tester", "refactoring", "database"}


class _ProjectMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel: str, content: str = "") -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def route(self, message, files, owners=None):
        return _route_failure_owners(
            message, files, _OWNERS if owners is None else owners, _AGENTS, True, project_dir=str(self.root),
        )


class TestInterfaceDriftRouting(_ProjectMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.write("app/__init__.py")
        self.write("app/core/__init__.py")
        self.write("app/core/encryption.py", _ENCRYPTION_MODULE)

    def test_method_imported_as_free_function_goes_to_consumer(self):
        files = ["tests/unit/test_encryption.py"]
        triage = triage_structural_failure(_IMPORT_ENCRYPT_MESSAGE, files, _OWNERS, self.root)
        self.assertEqual(triage.kind, KIND_INTERFACE_DRIFT)
        self.assertEqual(triage.responsible_file, "tests/unit/test_encryption.py")
        self.assertIn("EncryptionService", triage.diagnosis)
        self.assertIn("requirements", triage.diagnosis)
        self.assertEqual(self.route(_IMPORT_ENCRYPT_MESSAGE, files), {"tester"})

    def test_contract_listing_the_symbol_makes_the_provider_responsible(self):
        self.write("interface_contract.json", json.dumps({"modules": {"app.core.encryption": {"encrypt": "function"}}}))
        triage = triage_structural_failure(_IMPORT_ENCRYPT_MESSAGE, ["tests/unit/test_encryption.py"], _OWNERS, self.root)
        self.assertEqual(triage.kind, KIND_MISSING_SYMBOL)
        self.assertEqual(self.route(_IMPORT_ENCRYPT_MESSAGE, ["tests/unit/test_encryption.py"]), {"backend"})

    def test_contract_without_the_symbol_keeps_consumer_responsible(self):
        self.write("interface_contract.json", json.dumps(
            {"modules": {"app/core/encryption.py": {"EncryptionService": "class"}}}
        ))
        triage = triage_structural_failure(_IMPORT_ENCRYPT_MESSAGE, ["tests/unit/test_encryption.py"], _OWNERS, self.root)
        self.assertEqual(triage.kind, KIND_INTERFACE_DRIFT)
        self.assertIn("EncryptionService", triage.diagnosis)

    def test_typo_of_existing_symbol_goes_to_consumer(self):
        message = "E   ImportError: cannot import name 'EncryptionServce' from 'app.core.encryption'"
        self.assertEqual(self.route(message, ["tests/unit/test_encryption.py"]), {"tester"})

    def test_symbol_missing_without_alternative_goes_to_provider(self):
        message = "E   ImportError: cannot import name 'rotate_keys' from 'app.core.encryption'"
        triage = triage_structural_failure(message, ["tests/unit/test_encryption.py"], _OWNERS, self.root)
        self.assertEqual(triage.kind, KIND_MISSING_SYMBOL)
        self.assertEqual(self.route(message, ["tests/unit/test_encryption.py"]), {"backend"})

    def test_consumer_in_production_code_goes_to_its_owner(self):
        owners = {**_OWNERS, "app/api/routes.py": "backend", "tests/test_api.py": "tester"}
        message = "E   ImportError: cannot import name 'encrypt' from 'app.core.encryption'"
        self.assertEqual(self.route(message, ["tests/test_api.py", "app/api/routes.py"], owners), {"backend"})

    def test_contract_violations_are_listed(self):
        self.write("interface_contract.json", json.dumps({"modules": {
            "app/core/encryption.py": {"EncryptionService": "class", "encryption_service": "instance", "decrypt": "function"},
        }}))
        violations = find_contract_violations(self.root)
        self.assertEqual(len(violations), 2)
        self.assertTrue(any("encryption_service" in v for v in violations))
        self.assertTrue(any("Methode von `EncryptionService`" in v for v in violations))


class TestSyntaxAndSettingsRouting(_ProjectMixin, unittest.TestCase):
    def test_syntax_error_goes_to_owner_of_broken_file(self):
        self.write("app/core/auth.py", "def create_token(data: dict -> str:\n    pass\n")
        owners = {**_OWNERS, "app/core/auth.py": "backend", "tests/test_auth.py": "tester"}
        message = (
            "ERROR collecting tests/test_auth.py\n"
            "tests\\test_auth.py:1: in <module>\n"
            "    from app.core.auth import create_token\n"
            f"E     File \"{self.root / 'app' / 'core' / 'auth.py'}\", line 1\n"
            "E       def create_token(data: dict -> str:\n"
            "E   SyntaxError: '(' was never closed"
        )
        triage = triage_structural_failure(message, ["tests/test_auth.py"], owners, self.root)
        self.assertEqual(triage.kind, KIND_SYNTAX_ERROR)
        self.assertEqual(triage.responsible_file, "app/core/auth.py")
        self.assertEqual(self.route(message, ["tests/test_auth.py"], owners), {"backend"})

    def test_compile_style_syntax_error_without_project_dir(self):
        owners = {"app/core/auth.py": "database", "tests/test_auth.py": "tester"}
        message = "E   SyntaxError: invalid syntax (auth.py, line 12)"
        self.assertEqual(_route_failure_owners(message, [], owners, _AGENTS, True), {"database"})

    def test_settings_without_defaults_goes_to_config_owner(self):
        self.write("app/core/config.py", (
            "from pydantic_settings import BaseSettings\n\n"
            "class Settings(BaseSettings):\n"
            "    SECRET_KEY: str\n"
            "    DATABASE_URL: str\n"
            "    DEBUG: bool = False\n"
        ))
        message = (
            "E   pydantic_core._pydantic_core.ValidationError: 2 validation errors for Settings\n"
            "E   SECRET_KEY\n"
            "E     Field required [type=missing, input_value={}, input_type=dict]\n"
            "E   DATABASE_URL\n"
            "E     Field required [type=missing, input_value={}, input_type=dict]"
        )
        owners = {**_OWNERS, "tests/conftest.py": "tester"}
        triage = triage_structural_failure(message, ["tests/conftest.py"], owners, self.root)
        self.assertEqual(triage.kind, KIND_SETTINGS_DEFAULTS)
        self.assertEqual(triage.responsible_file, "app/core/config.py")
        self.assertIn("`SECRET_KEY`", triage.diagnosis)
        self.assertIn("`DATABASE_URL`", triage.diagnosis)
        self.assertEqual(self.route(message, ["tests/conftest.py"], owners), {"backend"})

    def test_request_model_validation_is_not_a_settings_problem(self):
        message = "E   pydantic_core._pydantic_core.ValidationError: 1 validation error for UserCreate"
        self.assertIsNone(triage_structural_failure(message, [], _OWNERS, self.root))


class TestLocalModuleNotFound(_ProjectMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.write("app/__init__.py")
        self.write("app/services/__init__.py")
        self.write("app/services/encryption.py", "def encrypt(data: bytes) -> bytes:\n    return data\n")
        self.owners = {"requirements.txt": "refactoring", "tests/test_x.py": "tester"}

    def test_missing_project_module_is_not_a_dependency_problem(self):
        message = "E   ModuleNotFoundError: No module named 'app.services.billing'"
        triage = triage_structural_failure(message, ["tests/test_x.py"], self.owners, self.root)
        self.assertEqual(triage.kind, KIND_MISSING_LOCAL_MODULE)
        self.assertEqual(self.route(message, ["tests/test_x.py"], self.owners), {"backend"})

    def test_misspelled_project_module_goes_to_importer(self):
        message = "E   ModuleNotFoundError: No module named 'app.services.encryptoin'"
        self.assertEqual(self.route(message, ["tests/test_x.py"], self.owners), {"tester"})

    def test_existing_top_level_package_points_to_test_import_path(self):
        message = "E   ModuleNotFoundError: No module named 'app'"
        triage = triage_structural_failure(message, ["tests/test_x.py"], self.owners, self.root)
        self.assertEqual(triage.kind, KIND_TEST_IMPORT_PATH)
        self.assertIn("pythonpath", triage.diagnosis)
        self.assertEqual(self.route(message, ["tests/test_x.py"], self.owners), {"tester"})

    def test_third_party_module_still_goes_to_manifest_owner(self):
        message = "E   ModuleNotFoundError: No module named 'jose'"
        self.assertIsNone(triage_structural_failure(message, [], self.owners, self.root))
        self.assertEqual(self.route(message, ["tests/test_x.py"], self.owners), {"refactoring"})


class TestFixLoopControls(_ProjectMixin, unittest.TestCase):
    def test_collection_failures_are_dispatched_first(self):
        collection = TestFailure(test_id="tests/test_a.py", message=_IMPORT_ENCRYPT_MESSAGE)
        assertion = TestFailure(test_id="tests/test_b.py::test_x", message="assert 1 == 2")
        self.assertEqual(blocking_failures_first([assertion, collection]), [collection])
        self.assertEqual(blocking_failures_first([assertion]), [assertion])

    def test_manifest_changes_are_rolled_back(self):
        self.write("requirements.txt", "fastapi\n")
        snapshot = snapshot_dependency_manifests(self.root)
        self.write("requirements.txt", "fastapi\ncryptography-encrypt\n")
        self.write("requirements-dev.txt", "pytest\n")
        restored = restore_dependency_manifests(self.root, snapshot)
        self.assertEqual(restored, ["requirements-dev.txt", "requirements.txt"])
        self.assertEqual((self.root / "requirements.txt").read_text(encoding="utf-8"), "fastapi\n")
        self.assertFalse((self.root / "requirements-dev.txt").exists())
        self.assertEqual(restore_dependency_manifests(self.root, snapshot), [])


class _Runner(TestRunnerMixin):
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir


class TestPytestCollectionParsing(_ProjectMixin, unittest.TestCase):
    def test_collection_error_block_becomes_its_own_failure(self):
        warnings = "\n".join(f"app/x.py:{i}: DeprecationWarning: noisy warning line {i}" for i in range(60))
        output = (
            "==================================== ERRORS ====================================\n"
            "_______________ ERROR collecting tests/unit/test_encryption.py ________________\n"
            "ImportError while importing test module 'tests/unit/test_encryption.py'.\n"
            "Traceback:\n"
            "tests\\unit\\test_encryption.py:3: in <module>\n"
            "    from app.core.encryption import encrypt\n"
            "E   ImportError: cannot import name 'encrypt' from 'app.core.encryption'\n"
            "=============================== warnings summary ===============================\n"
            f"{warnings}\n"
            "=========================== short test summary info ============================\n"
            "ERROR tests/unit/test_encryption.py\n"
            "ERROR tests/test_db.py::test_insert - fixture 'db' not found\n"
            "!!!!!!!!!!!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!!!!!!!!!!!\n"
        )
        failures = _Runner(self.root)._parse_python_failures(
            ExecutionResult(exit_code=2, stdout=output, stderr="", duration_seconds=1.0),
        )
        by_id = {f.test_id: f for f in failures}
        self.assertEqual(set(by_id), {"tests/unit/test_encryption.py", "tests/test_db.py::test_insert"})
        collection = by_id["tests/unit/test_encryption.py"]
        self.assertIn("cannot import name 'encrypt'", collection.message)
        self.assertEqual(collection.files, ["tests/unit/test_encryption.py"])
        self.assertIn("fixture 'db' not found", by_id["tests/test_db.py::test_insert"].message)


if __name__ == "__main__":
    unittest.main()
