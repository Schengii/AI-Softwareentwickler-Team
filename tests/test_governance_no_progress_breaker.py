"""
tests/test_governance_no_progress_breaker.py – Testet den Zirkuit-Breaker in
agents/orchestrator/verification.py._run_governance_fix_loop(): wenn ein Fixversuch dieselben
kritischen Governance-Befunde unverändert lässt, bricht die Schleife SOFORT ab und eröffnet
direkt ein Ticket, statt den verpflichtenden Re-Review + einen zweiten, ebenso wirkungslosen
Fix-Dispatch zu verbrauchen.

Erweiterung derselben Team-Retrospektive (taskpulse-Projekt) wie
tests/test_verification_no_progress_breaker.py, hier für die Governance- statt die
Test-Fix-Schleife - dasselbe Integrationsmuster wie tests/test_governance_fix_loop.py.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core import team_memory
from core.llm_factory import LLMResponse, ToolCall
from core.message_bus import AgentTask
from core.verifier import VerificationReport
from core.workspace import WorkspaceManager

CRITICAL_CODE_REVIEWER_REPORT = """## Code-Review Report

### 🔴 Kritische Probleme (müssen behoben werden)
SQL-Injection in `backend/db.py`: die Funktion `get_user()` baut die Query per
String-Concatenation statt parametrisiert.
"""

DIFFERENT_CRITICAL_CODE_REVIEWER_REPORT = """## Code-Review Report

### 🔴 Kritische Probleme (müssen behoben werden)
Hartcodiertes Secret in `backend/config.py`: der API-Key steht im Klartext im Quellcode.
"""


class _ScriptedLLM:
    def __init__(self, text: str = "Fertig.", written_file: str | None = None):
        self._text = text
        self._written_file = written_file
        self._call_count = 0
        self.model_name = "fake-model"

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        self._call_count += 1
        tool_calls = []
        if self._written_file and self._call_count == 1:
            tool_calls = [ToolCall(id="call_1", name="write_file",
                                    arguments={"path": self._written_file, "content": "# fix\n"})]
        text = "" if tool_calls else self._text
        return LLMResponse(text=text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=tool_calls)

    async def generate_with_usage(self, prompt, system_prompt=None):
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15)


class _FakeToolCapableLLM:
    def __init__(self, text: str = "Fertig."):
        self._text = text
        self.model_name = "fake-model"

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[])

    async def generate_with_usage(self, prompt, system_prompt=None):
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15)


class TestGovernanceNoProgressBreaker(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()
        self._team_memory_patch = patch.object(team_memory, "TEAM_MEMORY_FILE", Path(self.temp_workspace) / "team_lessons.jsonl")
        self._team_memory_patch.start()

    def tearDown(self):
        self._team_memory_patch.stop()
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, code_reviewer_llm):
        self.orchestrator._agents["backend"]._llm = _ScriptedLLM(written_file="backend/db.py")
        self.orchestrator._agents["code_reviewer"]._llm = code_reviewer_llm

        @patch("agents.orchestrator.verification.upsert_ticket")
        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls, mock_upsert_ticket):
            tasks = [
                AgentTask(task_id="t1", agent_id="backend", description="Baue etwas"),
                AgentTask(task_id="t2", agent_id="code_reviewer", description="Review durchführen"),
            ]
            mock_decompose.return_value = ("Kurze Aufgabe", "gov_no_progress_test_proj", tasks)
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
            )
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_lint.return_value = []

            status_logs: list[str] = []
            result = asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return result, status_logs, mock_upsert_ticket

        return _inner()

    def test_identical_critical_finding_after_fix_stops_early(self):
        # code_reviewer meldet bei JEDEM Aufruf (initial + Recheck) denselben kritischen Fund -
        # der Fixversuch hat also erkennbar nichts verändert.
        result, logs, mock_upsert_ticket = self._run(_ScriptedLLM(text=CRITICAL_CODE_REVIEWER_REPORT))

        self.assertTrue(any("Kein Fortschritt" in line for line in logs))
        self.assertIn("keine Veränderung", result)
        mock_upsert_ticket.assert_called()
        # Der verpflichtende, teure finale Re-Review (nach MAX_REVIEW_ITERATIONS) darf durch den
        # frühen Abbruch NICHT mehr ausgelöst werden.
        self.assertNotIn("Verpflichtender Re-Review", "".join(logs))

    def test_different_critical_findings_do_not_trigger_breaker(self):
        # Erster Aufruf liefert Fund A, jeder weitere Aufruf Fund B - echter Fortschritt
        # (anderes Problem gefunden), der Zirkuit-Breaker darf NICHT greifen.
        class _AlternatingLLM:
            def __init__(self):
                self._n = 0
                self.model_name = "fake-model"

            async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
                self._n += 1
                text = CRITICAL_CODE_REVIEWER_REPORT if self._n == 1 else DIFFERENT_CRITICAL_CODE_REVIEWER_REPORT
                return LLMResponse(text=text, model_name=self.model_name,
                                    prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[])

            async def generate_with_usage(self, prompt, system_prompt=None):
                return LLMResponse(text=CRITICAL_CODE_REVIEWER_REPORT, model_name=self.model_name,
                                    prompt_tokens=10, completion_tokens=5, total_tokens=15)

        result, logs, mock_upsert_ticket = self._run(_AlternatingLLM())

        self.assertFalse(any("Kein Fortschritt" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
