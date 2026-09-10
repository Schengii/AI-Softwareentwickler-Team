"""
tests/test_preflight_deterministic_dependency_fix.py – Testet den deterministischen
Kurzschluss für "missing_dependency"-Funde in agents/orchestrator/verification.py
(_run_verification_loop, Pre-Flight-Fix-Schleife).

Realer Fund (auditlog_sentinel, 2026-09-10): drei Läufe in Folge scheiterten an exakt derselben
Fehlerklasse (fehlendes `alembic`/`asyncpg`/`greenlet` in requirements.txt) - ein triviales
"Paket X fehlt" wurde bisher trotzdem als vollwertiger LLM-Agenten-Auftrag verschickt. Ein exakt
benanntes Paket wird jetzt direkt über core/dependency_manifest.add_requirement() eingetragen,
OHNE einen Agenten zu beauftragen.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.pre_flight_check import PreFlightIssue, PreFlightReport
from core.verifier import CompletenessReport, VerificationReport
from core.workspace import WorkspaceManager

PASSED_REPORT = VerificationReport(ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1)
CLEAN_COMPLETENESS = CompletenessReport(attempted=True, passed=True, issues=[])


class _FakeLLM:
    def __init__(self, text: str = "Fertig."):
        self._text = text
        self.model_name = "fake-model"

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[])

    async def generate_with_usage(self, prompt, system_prompt=None):
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15)


def _missing_dependency_report(package: str) -> PreFlightReport:
    return PreFlightReport(
        project_dir="dummy",
        files_checked=3,
        issues=[PreFlightIssue(
            file="app/main.py", line=3, issue_type="missing_dependency",
            message=f"Paket `{package}` wird importiert, fehlt aber in requirements.txt.",
            suggestion=f"Fuege `{package}` zu requirements.txt hinzu.",
        )],
    )


def _clean_report() -> PreFlightReport:
    return PreFlightReport(project_dir="dummy", files_checked=3, issues=[])


class TestPreflightDeterministicDependencyFix(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, pre_flight_side_effect):
        @patch("agents.orchestrator.verification.run_pre_flight_check")
        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls, mock_pre_flight):
            task = AgentTask(task_id="t1", agent_id="backend", description="app/main.py bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "preflight_det_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = PASSED_REPORT
            mock_verifier.check_completeness.return_value = CLEAN_COMPLETENESS
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_lint.return_value = []
            mock_pre_flight.side_effect = pre_flight_side_effect

            status_logs: list[str] = []
            result = asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return result, status_logs

        return _inner()

    def test_named_package_added_without_any_agent_dispatch(self):
        project_dir = Path(self.temp_workspace) / "preflight_det_proj"
        project_dir.mkdir(parents=True)
        (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")

        result, logs = self._run([
            _missing_dependency_report("alembic"),
            _clean_report(),
        ])

        self.assertTrue(any("Deterministisch ergänzt" in line and "alembic" in line for line in logs))
        self.assertFalse(any("Beauftrage" in line and "Pre-Flight-Check" in line for line in logs))
        self.assertEqual(
            (project_dir / "requirements.txt").read_text(encoding="utf-8"),
            "fastapi\nalembic\n",
        )
        self.assertTrue(self.orchestrator.last_verification_ok)

    def test_falls_back_to_agent_dispatch_without_manifest_on_disk(self):
        # Kein requirements.txt im Projektverzeichnis -> primary_python_manifest() findet
        # nichts, der reguläre Agenten-Auftrag bleibt Fallback (kein stilles Nichtstun).
        result, logs = self._run([
            _missing_dependency_report("alembic"),
            _clean_report(),
        ])

        self.assertFalse(any("Deterministisch ergänzt" in line for line in logs))
        self.assertTrue(any("Beauftrage" in line and "Pre-Flight-Check" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
