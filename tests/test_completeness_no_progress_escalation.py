"""
tests/test_completeness_no_progress_escalation.py - Testet die Team-Optimierung 2026-09-17
(hyperion_metrics-Root-Cause "Backend-Agent remediierte den Completeness-Befund im Fix-Zyklus
nicht"): die Vollständigkeits-Fix-Schleife in
agents/orchestrator/verification.py._run_verification_loop_impl() gab bisher beim ERSTEN
identischen Wiederholungsfund sofort auf (Veto + Ticket), ohne - anders als die parallele
Test-Fehlerschleife - je ein stärkeres Modell zu versuchen. Jetzt: ein Versuch, dann GENAU EIN
Eskalationsversuch mit HEAVY_MODEL für die stecken gebliebenen Agenten, erst danach aufgeben.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.verifier import VerificationReport
from core.verifier.models import CompletenessIssue, CompletenessReport
from core.workspace import WorkspaceManager
from tests.helpers import ScriptedWriteFileLLM as _ScriptedLLM

PASSING_TESTS = VerificationReport(
    ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1, failures=[],
)
_ISSUE = CompletenessIssue(
    file_path="app/main.py", line_number=5,
    message="Schreibender Routen-Handler „delete_alert_rule“ ohne erkennbaren I/O-Aufruf.",
    kind="",
)
FAILING_COMPLETENESS = CompletenessReport(attempted=True, passed=False, issues=[_ISSUE])
PASSING_COMPLETENESS = CompletenessReport(attempted=True, passed=True, issues=[])


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


class TestCompletenessNoProgressEscalation(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()
        self.orchestrator._agents["backend"]._llm = _ScriptedLLM(written_file="app/main.py")

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, check_completeness_side_effect):
        @patch("core.llm_factory.LLMFactory.create_for_model")
        @patch("agents.orchestrator.verification.upsert_ticket")
        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls, mock_upsert_ticket, mock_create_for_model):
            mock_create_for_model.side_effect = lambda model_name: _ScriptedLLM(written_file="app/main.py")
            task = AgentTask(task_id="t1", agent_id="backend", description="app/main.py bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "completeness_escalation_test_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = PASSING_TESTS
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_lint.return_value = []
            mock_verifier.check_completeness.side_effect = check_completeness_side_effect

            status_logs: list[str] = []
            result = asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return result, status_logs, mock_verifier, mock_upsert_ticket

        return _inner()

    def test_identical_completeness_finding_triggers_model_escalation_before_giving_up(self):
        # Aufruf 1: statischer Vorab-Import-Check (bricht sofort ab, `kind=""` ist keiner der
        # dort geprüften _PREIMPORT_ISSUE_KINDS). Aufrufe 2+3: die zwei regulären Versuche der
        # eigentlichen Vollständigkeits-Schleife (MAX_VERIFICATION_ITERATIONS Standard = 3,
        # aber Versuch 2 erkennt bereits "kein Fortschritt" gegen Versuch 1 und eskaliert, statt
        # regulär weiterzulaufen). Aufruf 4: der Eskalations-Recheck mit HEAVY_MODEL, der hier
        # ebenfalls fehlschlägt.
        result, logs, mock_verifier, mock_upsert_ticket = self._run(
            [FAILING_COMPLETENESS, FAILING_COMPLETENESS, FAILING_COMPLETENESS, FAILING_COMPLETENESS],
        )

        self.assertEqual(mock_verifier.check_completeness.call_count, 4)
        self.assertFalse(self.orchestrator.last_verification_ok)
        self.assertTrue(any("stärkerem Modell" in line for line in logs))
        self.assertTrue(any("Kein Fortschritt" in line for line in logs))

    def test_model_escalation_recovers_completeness_finding(self):
        result, logs, mock_verifier, mock_upsert_ticket = self._run(
            [FAILING_COMPLETENESS, FAILING_COMPLETENESS, FAILING_COMPLETENESS, PASSING_COMPLETENESS],
        )

        self.assertEqual(mock_verifier.check_completeness.call_count, 4)
        self.assertTrue(self.orchestrator.last_verification_ok)
        self.assertTrue(any("Eskalation erfolgreich" in line for line in logs))
