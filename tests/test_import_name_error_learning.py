"""
tests/test_import_name_error_learning.py – Testet die gezielte Fix-Dispatch- und
Selbstlern-Logik für `ImportError: cannot import name 'X' from 'Y'` in
agents/orchestrator/verification.py.

Realer Fund (`workspace/opspilot`): `app/api/auth.py` importierte `create_access_token` aus
`app/core/security.py`, obwohl die Funktion dort nie definiert war. Der Traceback zeigt bei
diesem Fehlerbild nur die IMPORTIERENDE Datei (app/api/auth.py), nicht das Zielmodul
`app/core/security.py`, in dem das Symbol tatsächlich fehlt – die generische, rein
Traceback-basierte Owner-Ermittlung adressierte deshalb potenziell den falschen Agenten oder
fiel auf den `tester`-Fallback zurück, der das fehlende Symbol strukturell nicht ergänzen kann.
_import_name_error_target()/_record_verification_learning() lösen den Owner von `Y` selbst auf
und hinterlegen zusätzlich eine persistente, dauerhaft in den System-Prompt des zuständigen
Agenten injizierte Lern-Regel (memory/agent_learnings.json), damit dieselbe Fehlerklasse
künftig seltener entsteht.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from agents.orchestrator.verification import (
    _import_name_error_target,
    _record_verification_learning,
)
from core.message_bus import AgentResult
from core.verifier import TestFailure, VerificationReport
from core.workspace import WorkspaceManager
from memory.agent_knowledge_base import AgentKnowledgeBase


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


class TestImportNameErrorTarget(unittest.TestCase):
    def test_extracts_symbol_and_module(self):
        message = "ImportError: cannot import name 'create_access_token' from 'app.core.security'"
        target = _import_name_error_target(message)
        self.assertEqual(target, ("create_access_token", "app.core.security"))

    def test_returns_none_for_unrelated_message(self):
        self.assertIsNone(_import_name_error_target("AssertionError: 3 != 4"))


class TestRecordVerificationLearning(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.kb_file = Path(self.temp_dir) / "agent_learnings.json"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_persists_a_concrete_rule_for_the_backend_agent(self):
        kb = AgentKnowledgeBase(file_path=self.kb_file)
        with patch("agents.orchestrator.verification.agent_knowledge_base", kb):
            _record_verification_learning(
                "ImportError: cannot import name 'create_access_token' from 'app.core.security'"
            )
        learnings = kb.get_learnings("backend")
        self.assertEqual(len(learnings), 1)
        self.assertIn("create_access_token", learnings[0])
        self.assertIn("app.core.security", learnings[0])

    def test_does_nothing_for_unrelated_message(self):
        kb = AgentKnowledgeBase(file_path=self.kb_file)
        with patch("agents.orchestrator.verification.agent_knowledge_base", kb):
            _record_verification_learning("AssertionError: 3 != 4")
        self.assertEqual(kb.get_learnings("backend"), [])


class TestImportNameErrorRouting(unittest.TestCase):
    """Realer Fund: der Traceback für diesen Fehlerbild-Typ nennt nur die importierende Datei
    (app/api/auth.py), nicht das Zielmodul (app/core/security.py), in dem das Symbol fehlt -
    die Fix-Aufgabe muss trotzdem beim Owner des ZIELMODULS landen, nicht blind beim tester."""

    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        self.orchestrator.last_project_slug = "import_name_error_proj"
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def test_dispatches_to_target_module_owner_not_tester(self):
        import_error_report = VerificationReport(
            ran=True, passed=False, exit_code=2, stdout="", stderr="",
            duration_seconds=0.1,
            failures=[TestFailure(
                test_id="<Testlauf>",
                message=(
                    "ImportError: cannot import name 'create_access_token' from "
                    "'app.core.security'"
                ),
                files=["app/api/auth.py"],
            )],
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
            mock_verifier.run_tests.side_effect = [import_error_report, passed_report]
            mock_verifier.check_completeness.return_value.attempted = False
            mock_verifier.check_coverage.return_value.attempted = False

            results, summary, budget_aborted, cancelled, verification_ok = asyncio.run(
                self.orchestrator._run_verification_loop(
                    project_dir=self.temp_workspace,
                    all_results=[backend_result, tester_result],
                    # Owner nur für die IMPORTIERENDE Datei bekannt (tester) - der Owner des
                    # ZIELMODULS (backend, app/core/security.py) muss trotzdem gewinnen.
                    file_owners={"app/api/auth.py": "tester", "app/core/security.py": "backend"},
                    notify=lambda msg: None,
                )
            )

        self.assertIn("backend", dispatched_agent_ids)
        self.assertNotIn("tester", dispatched_agent_ids)
        self.assertTrue(verification_ok)


if __name__ == "__main__":
    unittest.main()
