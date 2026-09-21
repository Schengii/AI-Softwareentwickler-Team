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

    def test_recognizes_instance_attribute_error(self):
        message = "AttributeError: 'AnomalyDetector' object has no attribute 'record_metric'"
        diag = _diagnose_runtime_failure(message)
        self.assertIsNotNone(diag)
        self.assertIn("record_metric", diag)
        self.assertIn("AnomalyDetector", diag)

    def test_recognizes_duplicate_router_prefix_404(self):
        message = "AssertionError: 404 != 200 for GET /api/v1/api/v1/users"
        diag = _diagnose_runtime_failure(message)
        self.assertIsNotNone(diag)
        self.assertIn("/api/v1", diag)

    def test_does_not_fire_on_unrelated_error(self):
        self.assertIsNone(_diagnose_runtime_failure("AssertionError: 3 != 4"))

    def test_plain_404_gets_route_not_registered_diagnosis_not_duplicate_prefix(self):
        # Ohne wiederholten Prefix ist die Ursache ein nicht gemounteter Router (logipulse-Lauf
        # 2026-09-10), kein doppelter Prefix - siehe _ROUTE_NOT_FOUND_RE in verification.py.
        diag = _diagnose_runtime_failure("AssertionError: 404 != 200 for GET /api/v1/users")
        self.assertIsNotNone(diag)
        self.assertIn("include_router", diag)
        self.assertNotIn("doppelter Router-Prefix", diag)

    def test_404_assertion_detected_as_route_not_found(self):
        # Pytest meldet bei fehlgeschlagenem assert response.status_code == 200:
        # assert 404 == 200 / where 404 = <Response [404]>.status_code
        diag1 = _diagnose_runtime_failure("AssertionError: assert 404 == 200\nwhere 404 = <Response [404]>.status_code")
        self.assertIsNotNone(diag1)
        self.assertIn("include_router", diag1)

        diag2 = _diagnose_runtime_failure("httpx.HTTPStatusError: 404 Client Error: Not Found for url: http://test/api/v1/metrics")
        self.assertIsNotNone(diag2)
        self.assertIn("include_router", diag2)

        # Wenn der Server 200 lieferte, aber der Test 404 erwartete, ist die Route VORHANDEN (kein Route Not Found)
        diag3 = _diagnose_runtime_failure("AssertionError: assert 200 == 404")
        self.assertIsNone(diag3)


class TestFailurePruning(unittest.TestCase):
    def test_short_message_not_pruned(self):
        from agents.orchestrator.failure_diagnosis import _prune_failure_message
        msg = "AssertionError: short error message"
        self.assertEqual(_prune_failure_message(msg, max_chars=500), msg)

    def test_long_message_pruned_retaining_head_and_tail(self):
        from agents.orchestrator.failure_diagnosis import _prune_failure_message
        head = "HEAD: Error occurred in tests/test_api.py:42"
        middle = "X" * 3000
        tail = "TAIL: AssertionError: assert response.status_code == 200 where 404 == 200"
        long_msg = f"{head}\n{middle}\n{tail}"

        pruned = _prune_failure_message(long_msg, max_chars=500)
        self.assertLessEqual(len(pruned), 520)
        self.assertIn("HEAD:", pruned)
        self.assertIn("TAIL:", pruned)
        self.assertIn("[Traceback gekürzt für Token-Budget]", pruned)

    def test_format_failures_for_agent_limits_count_and_prunes(self):
        from agents.orchestrator.failure_diagnosis import _format_failures_for_agent
        failures = [
            TestFailure(test_id=f"test_{i}", message="E" * 2000, files=[f"file_{i}.py"])
            for i in range(10)
        ]
        formatted = _format_failures_for_agent(failures, max_failures=3, max_msg_chars=400)
        self.assertIn("test_0", formatted)
        self.assertIn("test_2", formatted)
        self.assertNotIn("test_3", formatted)
        self.assertIn("und 7 weitere Testfehler", formatted)
        self.assertIn("[Traceback gekürzt für Token-Budget]", formatted)


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
                    file_owners={"app/routers/webhooks.py": "backend", "tests/test_api.py": "tester"},
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

    def test_route_not_found_routes_to_backend_even_when_only_test_in_traceback(self):
        # Omnimetric Engine: im Traceback stand nur tests/test_api.py, Ursache war aber der fehlende Endpoint
        dispatched = self._run_loop(
            "AssertionError: assert 404 == 200\nwhere 404 = <Response [404]>.status_code",
            ["tests/test_api.py"],
        )
        self.assertIn("backend", dispatched)


if __name__ == "__main__":
    unittest.main()
