"""
tests/test_no_tests_ran_diagnosis.py – Testet die Erkennung/Behandlung eines "Ran 0 tests"/
"NO TESTS RAN"-Befunds in agents/orchestrator/verification.py und core/verifier/environment.py.

Realer Fund (memory/backlog.json-Tickets `recurring-failure-event_relay` und
`recurring-failure-service_bookmark_monitor`): core/verifier/testrunner.py._run_pytest_or_
unittest() fällt bei fehlendem `pytest` in der Umgebung STILLSCHWEIGEND auf
`python -m unittest discover` zurück - das findet generierten, im pytest-Stil geschriebenen
Testcode (einfache def test_...()-Funktionen ohne unittest.TestCase) nicht und meldet "Ran 0
tests in 0.000s / NO TESTS RAN". Ohne Datei-Bezug im Traceback landete der Fix-Auftrag bisher
blind beim `tester`-Agenten, der die eigentliche (meist umgebungsbedingte) Ursache strukturell
nie beheben konnte ("Fixversuch änderte nichts" - beide Tickets standen deshalb dauerhaft
"blocked"). Zwei Verteidigungslinien:
1. core/verifier/environment.py.ProjectVerifier._ensure_pytest_available() stellt `pytest` VOR
   jedem Testlauf sicher (siehe tests/test_verifier.py) - verhindert die Ursache meistens schon.
2. Falls sie trotzdem auftritt (z.B. Nachinstallation ohne Netzwerkzugriff fehlgeschlagen),
   erkennt _diagnose_no_tests_ran() das Muster und die Routing-Logik bevorzugt den Owner von
   requirements.txt vor dem blinden tester-Fallback (siehe unten).
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from agents.orchestrator.verification import _diagnose_no_tests_ran
from core.message_bus import AgentResult
from core.verifier import TestFailure, VerificationReport
from core.workspace import WorkspaceManager


class _FakeToolCapableLLM:
    def __init__(self, text: str = "Fertig."):
        self._text = text
        self.model_name = "fake-model"

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        return type("R", (), {
            "text": self._text, "model_name": self.model_name, "prompt_tokens": 10,
            "completion_tokens": 5, "total_tokens": 15, "tool_calls": [],
        })()

    async def generate_with_usage(self, prompt, system_prompt=None):
        return await self.generate_with_tools([], "", [])


class TestDiagnoseNoTestsRan(unittest.TestCase):
    def test_recognizes_unittest_no_tests_ran(self):
        message = "----------------------------------------------------------------------\nRan 0 tests in 0.000s\n\nNO TESTS RAN"
        diag = _diagnose_no_tests_ran(message)
        self.assertIsNotNone(diag)
        self.assertIn("fehlende Testabhängigkeit", diag)

    def test_recognizes_pytest_collected_zero_items(self):
        self.assertIsNotNone(_diagnose_no_tests_ran("collected 0 items"))

    def test_does_not_fire_on_a_real_assertion_failure(self):
        self.assertIsNone(_diagnose_no_tests_ran("AssertionError: 3 != 4"))


class TestNoTestsRanRouting(unittest.TestCase):
    """Realer Fund: ein Befund ohne Datei-Bezug (kein Traceback bei 'Ran 0 tests') landete
    blind beim tester, obwohl requirements.txt (die wahrscheinlichere Ursache) einen bekannten
    Owner hatte."""

    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        self.orchestrator.last_project_slug = "no_tests_ran_proj"
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def test_no_tests_ran_prefers_requirements_owner_over_blind_tester(self):
        no_tests_ran_report = VerificationReport(
            ran=True, passed=False, exit_code=5, stdout="", stderr="",
            duration_seconds=0.1,
            failures=[TestFailure(test_id="<Testlauf>", message="Ran 0 tests in 0.000s\n\nNO TESTS RAN", files=[])],
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

            results, summary, budget_aborted, cancelled, verification_ok = asyncio.run(
                self.orchestrator._run_verification_loop(
                    project_dir=self.temp_workspace,
                    all_results=[backend_result, tester_result],
                    file_owners={"requirements.txt": "backend"},
                    notify=lambda msg: None,
                )
            )

        self.assertIn("backend", dispatched_agent_ids)
        self.assertNotIn("tester", dispatched_agent_ids)
        self.assertTrue(verification_ok)


if __name__ == "__main__":
    unittest.main()
