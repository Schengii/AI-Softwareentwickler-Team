"""
tests/test_runtime_failure_diagnosis.py – Testet _diagnose_runtime_failure() in
agents/orchestrator/verification.py sowie das gezielte Routing der vier dort erkannten
Laufzeit-Fehlerklassen (IntegrityError/NOT NULL, OperationalError/no such table,
AttributeError auf dict, doppelter Router-Prefix bei 404) an den fachlich zuständigen Agenten.

Team-Optimierung (ki_team_analyse_und_optimierungen.md, Punkt 1.2/2): bisher diagnostizierte
der Verifier fast ausschließlich ModuleNotFoundError/ImportError konkret; diese vier Muster
liefen zuvor als generischer Fix-Auftrag ohne konkrete Handlungsanweisung durch die Fix-Schleife
- siehe _diagnose_runtime_failure()-Docstring in verification.py für Details.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from agents.orchestrator.verification import _diagnose_runtime_failure
from core.message_bus import AgentResult
from core.verifier import TestFailure, VerificationReport
from core.workspace import WorkspaceManager


class TestDiagnoseRuntimeFailure(unittest.TestCase):
    def test_recognizes_integrity_error_not_null(self):
        message = (
            "sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError) NOT NULL constraint "
            "failed: webhooks.hmac_secret"
        )
        diag = _diagnose_runtime_failure(message)
        self.assertIsNotNone(diag)
        self.assertIn("hmac_secret", diag)
        self.assertIn("webhooks", diag)

    def test_recognizes_operational_error_no_such_table(self):
        message = "sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such table: users"
        diag = _diagnose_runtime_failure(message)
        self.assertIsNotNone(diag)
        self.assertIn("users", diag)
        self.assertIn("Base", diag)

    def test_recognizes_dict_attribute_error(self):
        message = "AttributeError: 'dict' object has no attribute 'email'"
        diag = _diagnose_runtime_failure(message)
        self.assertIsNotNone(diag)
        self.assertIn("email", diag)
        self.assertIn("Pydantic", diag)

    def test_recognizes_duplicate_router_prefix_404(self):
        message = "AssertionError: 404 != 200 for GET /api/v1/api/v1/users"
        diag = _diagnose_runtime_failure(message)
        self.assertIsNotNone(diag)
        self.assertIn("/api/v1", diag)

    def test_does_not_fire_on_unrelated_error(self):
        self.assertIsNone(_diagnose_runtime_failure("AssertionError: 3 != 4"))

    def test_does_not_fire_on_404_without_duplicate_prefix(self):
        self.assertIsNone(_diagnose_runtime_failure("AssertionError: 404 != 200 for GET /api/v1/users"))


class TestRuntimeFailureRouting(unittest.TestCase):
    """Realer Fund: IntegrityError/no such table treffen im Traceback oft nur eine
    unbeteiligte Aufrufer-Datei - die gezielte Routing-Logik muss trotzdem an den fachlich
    zuständigen Agenten (database bzw. backend) dispatchen, nicht an den zufälligen file_owner."""

    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        self.orchestrator.last_project_slug = "runtime_failure_proj"

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run_loop(self, message: str, files: list[str]) -> list[str]:
        no_tests_ran_report = VerificationReport(
            ran=True, passed=False, exit_code=1, stdout="", stderr="",
            duration_seconds=0.1,
            failures=[TestFailure(test_id="test_x", message=message, files=files)],
        )
        passed_report = VerificationReport(ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1)

        backend_result = AgentResult(task_id="t1", agent_id="backend", agent_name="Backend", success=True, content="ok")
        tester_result = AgentResult(task_id="t2", agent_id="tester", agent_name="Tester", success=True, content="ok")

        dispatched_agent_ids: list[str] = []

        async def _fake_run_agents_parallel(tasks, notify=None):
            dispatched_agent_ids.extend(t.agent_id for t in tasks)
            return [
                AgentResult(task_id=t.task_id, agent_id=t.agent_id, agent_name=t.agent_id, success=True, content="Fix versucht.")
                for t in tasks
            ]

        with patch("agents.orchestrator.verification.ProjectVerifier") as mock_verifier_cls, \
             patch.object(self.orchestrator, "_run_agents_parallel", side_effect=_fake_run_agents_parallel):
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.run_tests.side_effect = [no_tests_ran_report, passed_report]
            mock_verifier.check_completeness.return_value.attempted = False
            mock_verifier.check_coverage.return_value.attempted = False

            asyncio.run(
                self.orchestrator._run_verification_loop(
                    project_dir=self.temp_workspace,
                    all_results=[backend_result, tester_result],
                    file_owners={"app/routers/webhooks.py": "backend"},
                    notify=lambda msg: None,
                )
            )
        return dispatched_agent_ids

    def test_integrity_error_routes_to_database_agent(self):
        dispatched = self._run_loop(
            "sqlalchemy.exc.IntegrityError: NOT NULL constraint failed: webhooks.hmac_secret",
            ["app/routers/webhooks.py"],
        )
        self.assertIn("database", dispatched)
        self.assertNotIn("backend", dispatched)

    def test_no_such_table_routes_to_database_agent(self):
        dispatched = self._run_loop(
            "sqlalchemy.exc.OperationalError: no such table: webhooks",
            ["app/routers/webhooks.py"],
        )
        self.assertIn("database", dispatched)
        self.assertNotIn("backend", dispatched)

    def test_dict_attribute_error_routes_to_backend_agent(self):
        dispatched = self._run_loop(
            "AttributeError: 'dict' object has no attribute 'email'",
            ["app/services/user_service.py"],
        )
        self.assertIn("backend", dispatched)


if __name__ == "__main__":
    unittest.main()
