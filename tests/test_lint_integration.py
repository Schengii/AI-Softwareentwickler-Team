"""
tests/test_lint_integration.py – Testet die Lint-/Type-Check-Prüfung im Verifikationslauf

Realer Fund: ruff.toml lief bisher AUSSCHLIESSLICH gegen den Framework-Code selbst -
workspace/ ist dort bewusst ausgeschlossen. agents/orchestrator.py._run_verification_loop()
ruft jetzt echte ProjectVerifier.check_lint() auf und macht das Ergebnis sichtbar - exakt
dasselbe Integrationsmuster wie test_docker_build_integration.py/
test_dependency_audit_integration.py.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.verifier import LintIssue, LintReport, VerificationReport
from core.workspace import WorkspaceManager


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


class TestLintInVerificationLoop(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, lint_reports: list[LintReport]):
        @patch("agents.orchestrator.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            task = AgentTask(task_id="t1", agent_id="backend", description="Etwas bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "lint_test_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1,
            )
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_lint.return_value = lint_reports

            status_logs: list[str] = []
            result = asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return result, status_logs, mock_verifier

        return _inner()

    def test_found_lint_issues_are_reported_in_summary(self):
        report = LintReport(
            attempted=True, passed=False, tool="ruff",
            issues=[LintIssue(file_path="app.py", line_number=3, message="unused import", rule="F401")],
        )
        result, logs, mock_verifier = self._run([report])

        mock_verifier.check_lint.assert_called_once()
        self.assertIn("ruff", result)
        self.assertIn("app.py", result)
        self.assertIn("F401", result)
        self.assertTrue(any("Lint-Fund" in line for line in logs))

    def test_clean_lint_is_reported_in_summary(self):
        report = LintReport(attempted=True, passed=True, tool="eslint")
        result, logs, mock_verifier = self._run([report])

        self.assertIn("eslint", result)
        self.assertIn("keine Lint-Funde", result)

    def test_skipped_lint_adds_no_noise_to_summary(self):
        report = LintReport(
            attempted=False, passed=True, tool="ruff",
            reason_skipped="`ruff` ist auf diesem System nicht installiert/verfügbar.",
        )
        result, logs, mock_verifier = self._run([report])

        self.assertNotIn("Lint-Fund", result)

    def test_multiple_tool_reports_are_all_included(self):
        reports = [
            LintReport(attempted=True, passed=True, tool="ruff"),
            LintReport(
                attempted=True, passed=False, tool="tsc",
                issues=[LintIssue(file_path="bad.ts", line_number=1, message="Type error", rule="TS2322")],
            ),
        ]
        result, logs, mock_verifier = self._run(reports)

        self.assertIn("ruff", result)
        self.assertIn("tsc", result)
        self.assertIn("bad.ts", result)


if __name__ == "__main__":
    unittest.main()
