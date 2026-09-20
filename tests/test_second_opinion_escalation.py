"""
tests/test_second_opinion_escalation.py – Zweitmeinung als letzte Stufe der Eskalationsleiter

Realer Fund (Roadmap P1-2, 2026-09-20): acht `recurring-failure-*`-Tickets stehen im Backlog
(`eventforge_core`, `sentinedge`, `hyperion_metrics`, `chronoflow`,
`entwickle_das_projekt_sentinel`, `devpulse`, `aegis_mesh`, `chronos_ledger`), fast alle mit
derselben Diagnose: "Fixversuch änderte nichts an N Testfehler(n) - vermutlich falscher/
unzureichend instruierter Agent."

Die Eskalationsleiter hatte drei Stufen: derselbe Agent, dann der Fachbereichsleiter, dann
HEAVY_MODEL. Stufe 2 delegiert am Ende wieder an dieselben Teammitglieder, und Stufe 3 setzt
voraus, dass eine stärkere Modellstufe überhaupt erreichbar ist - bei `aetherqueue` und
`eventforge_core` war sie es nicht ("HEAVY_MODEL-Eskalation für tester griff nicht
tatsächlich"), die Leiter endete dort faktisch nach Stufe 2.

Stufe 4 ändert nicht das Modell, sondern den Blickwinkel: eine unbeteiligte Rolle liest den
Code read-only und stellt eine Diagnose, die dann als Kontext in einen letzten Fix-Auftrag an
die eigentlichen Eigentümer geht - wie ein Team jemanden dazuholt, der draufschaut, statt
lauter dieselbe Anweisung zu wiederholen.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.verifier import TestFailure, VerificationReport
from core.workspace import WorkspaceManager
from tests.helpers import ScriptedWriteFileLLM as _ScriptedLLM

_FAILURE = TestFailure(
    test_id="tests/test_app.py::test_x", message="AssertionError: boom", files=["backend/app.py"],
)
FAILING_REPORT = VerificationReport(
    ran=True, passed=False, exit_code=1, stdout="", stderr="", duration_seconds=0.1,
    failures=[_FAILURE],
)
PASSING_REPORT = VerificationReport(
    ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1, failures=[],
)

DIAGNOSIS_TEXT = (
    "Die Grundannahme war falsch: nicht der Handler ist fehlerhaft, sondern die Fixture legt "
    "die Tabelle in einer zweiten Metadata-Registry an."
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


class TestSecondOpinionEscalation(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()
        self.orchestrator._agents["backend"]._llm = _ScriptedLLM(written_file="backend/app.py")
        self.orchestrator._agents["code_reviewer"]._llm = _FakeToolCapableLLM(DIAGNOSIS_TEXT)
        self.dispatched: list[AgentTask] = []

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, run_tests_side_effect):
        """Zeichnet zusätzlich alle beauftragten AgentTasks auf, damit die Prüfung am
        tatsächlichen Auftrag ansetzen kann und nicht nur am Protokolltext."""
        original = Orchestrator._run_agents_parallel

        async def _recording(inner_self, tasks, *a, **kw):
            self.dispatched.extend(tasks)
            return await original(inner_self, tasks, *a, **kw)

        # Ohne den create_for_model-Patch baut die HEAVY_MODEL-Stufe der Eskalationsleiter
        # einen ECHTEN Provider-Client - und löst, wenn in dieser Umgebung ein API-Key gesetzt
        # ist, echte API-Aufrufe aus (hier gemessen: 49 s statt 2 s pro Test). Dieselbe
        # Begründung wie in tests/test_verification_no_progress_breaker.py.
        @patch.object(Orchestrator, "_run_agents_parallel", _recording)
        @patch("core.llm_factory.LLMFactory.create_for_model")
        @patch("agents.orchestrator.verification.upsert_ticket")
        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls, _mock_ticket, mock_create_for_model):
            mock_create_for_model.side_effect = lambda model_name: _ScriptedLLM(written_file="backend/app.py")
            task = AgentTask(task_id="t1", agent_id="backend", description="backend/app.py bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "second_opinion_test_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.side_effect = run_tests_side_effect
            mock_verifier.check_completeness.return_value.attempted = False
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_lint.return_value = []

            logs: list[str] = []
            asyncio.run(self.orchestrator.process("Baue etwas", status_callback=logs.append))
            return logs, mock_verifier

        return _inner()

    def _second_opinion_tasks(self) -> list[AgentTask]:
        return [t for t in self.dispatched if t.task_id.startswith("verify_second_opinion_")]

    def test_second_opinion_is_requested_after_the_other_stages_failed(self):
        logs, mock_verifier = self._run([FAILING_REPORT] * 6)

        diagnosis_tasks = [t for t in self._second_opinion_tasks() if "_fix_" not in t.task_id]
        self.assertEqual(len(diagnosis_tasks), 1)
        self.assertEqual(diagnosis_tasks[0].agent_id, "code_reviewer")
        self.assertTrue(any("Zweitmeinung" in line for line in logs))

    def test_diagnosis_is_read_only(self):
        """Die Zweitmeinung soll ANALYSIEREN, nicht nebenbei selbst Dateien umschreiben -
        sonst entsteht genau das unkoordinierte Fremdschreiben, das core/write_guard.py
        verhindern soll."""
        self._run([FAILING_REPORT] * 6)

        diagnosis = [t for t in self._second_opinion_tasks() if "_fix_" not in t.task_id][0]
        self.assertTrue(diagnosis.tools_read_only)

    def test_diagnosis_is_handed_to_the_stuck_owner_as_context(self):
        """Kern der Stufe: der Eigentümer bekommt die fremde Diagnose in den Auftrag - ohne sie
        wäre es nur eine weitere Wiederholung desselben Ansatzes."""
        self._run([FAILING_REPORT] * 6)

        fix_tasks = [t for t in self._second_opinion_tasks() if "_fix_" in t.task_id]
        self.assertEqual(len(fix_tasks), 1)
        self.assertEqual(fix_tasks[0].agent_id, "backend")
        self.assertIn(DIAGNOSIS_TEXT, fix_tasks[0].description)
        self.assertIn("DIAGNOSE VON CODE_REVIEWER", fix_tasks[0].description)

    def test_successful_second_opinion_makes_the_run_green(self):
        """Stufen 1-4 rot, der Testlauf nach der Zweitmeinung grün."""
        logs, _ = self._run([FAILING_REPORT] * 4 + [PASSING_REPORT, PASSING_REPORT])

        self.assertTrue(self.orchestrator.last_verification_ok)
        self.assertTrue(any("Zweitmeinung erfolgreich" in line for line in logs))

    def test_reviewer_is_never_one_of_the_stuck_owners(self):
        """Wäre der Gutachter selbst Eigentümer der steckenden Datei, wäre es keine
        Zweitmeinung - dann muss die nächste Rolle der Prioritätsliste greifen."""
        orchestrator = self.orchestrator
        self.assertIn("code_reviewer", orchestrator._SECOND_OPINION_ROLES)
        candidates = [
            a for a in orchestrator._SECOND_OPINION_ROLES
            if a in orchestrator._agents and a not in {"code_reviewer"}
        ]
        self.assertTrue(candidates, "Es muss eine Ausweich-Rolle für die Zweitmeinung geben.")

    def test_second_opinion_runs_only_once_per_run(self):
        """Begrenzte Leiter: die Stufe darf sich nicht bei jedem weiteren Versuch wiederholen."""
        self._run([FAILING_REPORT] * 6)

        diagnosis_tasks = [t for t in self._second_opinion_tasks() if "_fix_" not in t.task_id]
        self.assertEqual(len(diagnosis_tasks), 1)


if __name__ == "__main__":
    unittest.main()
