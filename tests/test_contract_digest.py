"""
tests/test_contract_digest.py – core/contract_digest.py: deterministischer Backend-Vertrags-
Auszug (Enum-Werte, Pydantic-Feldnamen) für den tester-Agenten.

Regressionstest für den realen pulse_queue-Fund (2026-09-22,
FEHLERANALYSE_PULSE_QUEUE_20260922_TEMP.md, Problem 2): der Tester schrieb Tests gegen erfundene
Enum-Werte (`JobType.DATA_EXPORT` statt `JobType.data_export`) und einen erfundenen Feldnamen
(`job_type` statt `type`), obwohl der reale Backend-Code bereits im Workspace lag.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.contract_digest import build_backend_contract_digest


class TestBuildBackendContractDigest(unittest.TestCase):
    def test_extracts_enum_members_and_model_fields(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            models_dir = root / "app" / "models"
            models_dir.mkdir(parents=True)
            (models_dir / "job.py").write_text(
                "import enum\n"
                "from pydantic import BaseModel\n\n"
                "class JobType(str, enum.Enum):\n"
                "    email_dispatch = \"email_dispatch\"\n"
                "    data_export = \"data_export\"\n\n"
                "class JobCreate(BaseModel):\n"
                "    type: JobType\n"
                "    priority: int = 1\n",
                encoding="utf-8",
            )
            digest = build_backend_contract_digest(root)
            self.assertIn("JobType", digest)
            self.assertIn("data_export", digest)
            self.assertIn("email_dispatch", digest)
            self.assertIn("type: JobType", digest)
            # Nicht die verkürzte SCREAMING_SNAKE-Form, die der Tester real erfunden hatte.
            self.assertNotIn("DATA_EXPORT", digest)

    def test_ignores_test_files(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "tests").mkdir()
            (root / "tests" / "test_models.py").write_text(
                "import enum\n\nclass FakeType(enum.Enum):\n    A = 1\n", encoding="utf-8",
            )
            self.assertEqual(build_backend_contract_digest(root), "")

    def test_empty_project_returns_empty_string(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(build_backend_contract_digest(d), "")

    def test_missing_directory_returns_empty_string(self) -> None:
        self.assertEqual(build_backend_contract_digest("/does/not/exist"), "")


if __name__ == "__main__":
    unittest.main()
