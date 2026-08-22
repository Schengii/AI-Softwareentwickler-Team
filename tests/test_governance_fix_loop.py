"""
tests/test_governance_fix_loop.py – Testet agents/orchestrator.py._run_governance_fix_loop()

Realer Fund bei einer Bestandsaufnahme des eigenen Teams: code_reviewer/security/compliance
(REVIEW_ONLY_AGENT_IDS) kategorisieren Befunde selbst nach Schweregrad ("Kritisch"), aber das
löste bisher NIE einen Korrekturauftrag aus - nur ein echter Testfehler (_run_verification_loop)
tat das. Dieser Test beweist per vollem Orchestrator.process()-Lauf, dass ein kritischer Fund
jetzt gezielt an den zuständigen Datei-Owner zur Korrektur zurückgespielt wird, BEVOR die echte
Testverifikation läuft - exakt nach dem Muster von test_dependency_audit_integration.py.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

import agents.orchestrator as orch_module
from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse, ToolCall
from core.message_bus import AgentResult, AgentTask
from core.token_guard import TokenGuard
from core.verifier import VerificationReport
from core.workspace import WorkspaceManager

CRITICAL_CODE_REVIEWER_REPORT = """## Code-Review Report

### Gesamtbewertung
⭐⭐⭐ Funktioniert, aber mit einem Sicherheitsproblem.

### 🔴 Kritische Probleme (müssen behoben werden)
SQL-Injection in `backend/db.py`: die Funktion `get_user()` baut die Query per
String-Concatenation statt parametrisiert.

### 🟡 Mittlere Probleme (sollten behoben werden)
Keine.
"""

CLEAN_CODE_REVIEWER_REPORT = """## Code-Review Report

### Gesamtbewertung
⭐⭐⭐⭐⭐ Sehr sauberer Code.

### 🔴 Kritische Probleme (müssen behoben werden)
Keine kritischen Probleme gefunden.
"""


class _ScriptedLLM:
    """
    Ruft beim ERSTEN generate_with_tools()-Aufruf write_file (falls `written_file` gesetzt ist)
    auf, liefert ab dem zweiten Aufruf `text` als finale Antwort - simuliert das realistische
    "erst Werkzeug, dann Zusammenfassung"-Muster statt denselben Tool-Call endlos zu wiederholen.
    """

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
        return LLMResponse(
            text=text, model_name=self.model_name,
            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=tool_calls,
        )

    async def generate_with_usage(self, prompt, system_prompt=None):
        return LLMResponse(
            text=self._text, model_name=self.model_name,
            prompt_tokens=10, completion_tokens=5, total_tokens=15,
        )


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


class TestGovernanceFixLoop(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, code_reviewer_text: str, backend_written_file: str = "backend/db.py"):
        # backend "schreibt" die Datei, deren Owner der Fund-Router treffen muss.
        self.orchestrator._agents["backend"]._llm = _ScriptedLLM(written_file=backend_written_file)
        self.orchestrator._agents["code_reviewer"]._llm = _ScriptedLLM(text=code_reviewer_text)

        @patch("agents.orchestrator.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            tasks = [
                AgentTask(task_id="t1", agent_id="backend", description="Baue etwas"),
                AgentTask(task_id="t2", agent_id="code_reviewer", description="Review durchführen"),
            ]
            mock_decompose.return_value = ("Kurze Aufgabe", "gov_fix_test_proj", tasks)
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
            )
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_lint.return_value = []

            status_logs: list[str] = []
            result = asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return result, status_logs

        return _inner()

    def test_critical_finding_dispatches_fix_to_file_owner(self):
        result, logs = self._run(CRITICAL_CODE_REVIEWER_REPORT)

        self.assertIn("Governance-Fix-Protokoll", result)
        self.assertIn("1 kritische(r) Governance-Befund(e)", result)
        self.assertIn("an backend zurückgespielt", result)
        self.assertTrue(any("Governance-Fix" in line for line in logs))

    def test_no_critical_finding_confirms_clean_report_without_dispatch(self):
        result, logs = self._run(CLEAN_CODE_REVIEWER_REPORT)

        self.assertIn("Governance-Fix-Protokoll", result)
        self.assertIn("Keine kritischen Befunde", result)
        self.assertNotIn("zurückgespielt", result)

    def test_review_only_agent_absent_adds_no_section(self):
        # Kein code_reviewer/security/compliance im Plan -> die Schleife hat nichts zu prüfen,
        # keine zusätzliche Sektion im Ergebnis (kein Rauschen für den Alltagsfall).
        @patch("agents.orchestrator.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            self.orchestrator._agents["backend"]._llm = _ScriptedLLM(written_file="backend/db.py")
            tasks = [AgentTask(task_id="t1", agent_id="backend", description="Baue etwas")]
            mock_decompose.return_value = ("Kurze Aufgabe", "no_review_proj", tasks)
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
            )
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_lint.return_value = []
            return asyncio.run(self.orchestrator.process("Baue etwas"))

        result = _inner()
        self.assertNotIn("Governance-Fix-Protokoll", result)

    def test_disabled_flag_reproduces_old_behavior(self):
        with patch("agents.orchestrator.ENABLE_GOVERNANCE_FIX_LOOP", False):
            result, logs = self._run(CRITICAL_CODE_REVIEWER_REPORT)

        self.assertNotIn("Governance-Fix-Protokoll", result)

    def test_budget_exceeded_skips_fix_dispatch(self):
        # Direkter Aufruf von _run_governance_fix_loop() (statt über den vollen process()-Lauf)
        # mit einem frischen TokenGuard, dessen Zähler bereits über dem gepatchten Budget liegt -
        # exakt das Muster aus tests/test_run_budget_cap.py für dieselbe Art Budget-Test.
        fresh_guard = TokenGuard()
        fresh_guard.record_usage("fake-model", 5, 0)
        code_reviewer_result = AgentResult(
            task_id="t2", agent_id="code_reviewer", agent_name="Code-Reviewer", success=True,
            content=CRITICAL_CODE_REVIEWER_REPORT,
        )

        with patch.object(orch_module, "token_guard", fresh_guard), \
             patch.object(orch_module, "MAX_RUN_TOKENS", 1):
            results, summary, budget_aborted, cancelled = asyncio.run(self.orchestrator._run_governance_fix_loop(
                project_dir=self.temp_workspace,
                all_results=[code_reviewer_result],
                file_owners={"backend/db.py": "backend"},
                notify=lambda msg: None,
                run_start_tokens=0,
            ))

        self.assertTrue(budget_aborted)
        self.assertFalse(cancelled)
        self.assertIn("Lauf-Budget", summary)
        self.assertNotIn("zurückgespielt", summary)

    def test_second_iteration_rechecks_review_roles(self):
        # MAX_REVIEW_ITERATIONS=2: nach dem ersten Fix-Dispatch wird code_reviewer erneut
        # aufgerufen - hier liefert der (gescriptete) code_reviewer beim zweiten Aufruf einen
        # sauberen Report, die Schleife muss das als "keine weiteren Befunde" erkennen.
        call_count = {"n": 0}

        class _TwoStageLLM(_ScriptedLLM):
            async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
                call_count["n"] += 1
                self._text = CRITICAL_CODE_REVIEWER_REPORT if call_count["n"] == 1 else CLEAN_CODE_REVIEWER_REPORT
                return await super().generate_with_tools(messages, system_prompt, tools, _allow_self_fallback)

        self.orchestrator._agents["backend"]._llm = _ScriptedLLM(written_file="backend/db.py")
        self.orchestrator._agents["code_reviewer"]._llm = _TwoStageLLM()

        with patch("agents.orchestrator.MAX_REVIEW_ITERATIONS", 2):
            @patch("agents.orchestrator.ProjectVerifier")
            @patch("core.task_manager.TaskManager.decompose")
            @patch("core.result_aggregator.ResultAggregator.synthesize")
            def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
                tasks = [
                    AgentTask(task_id="t1", agent_id="backend", description="Baue etwas"),
                    AgentTask(task_id="t2", agent_id="code_reviewer", description="Review durchführen"),
                ]
                mock_decompose.return_value = ("Kurze Aufgabe", "gov_fix_test_proj2", tasks)
                mock_synthesize.return_value = ("### Fertig", 5)
                mock_verifier = mock_verifier_cls.return_value
                mock_verifier.ensure_environment.return_value = ""
                mock_verifier.run_tests.return_value = VerificationReport(
                    ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
                )
                mock_verifier.check_docker_build.return_value.attempted = False
                mock_verifier.check_dependency_vulnerabilities.return_value = []
                mock_verifier.check_lint.return_value = []
                return asyncio.run(self.orchestrator.process("Baue etwas"))

            result = _inner()

        self.assertGreaterEqual(call_count["n"], 2)
        self.assertIn("Keine kritischen Befunde", result)


if __name__ == "__main__":
    unittest.main()
