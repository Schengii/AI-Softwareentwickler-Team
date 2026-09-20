"""
tests/test_completeness_measured_despite_budget.py – Deterministische Messung vor dem Budget-Gate

Realer Fund (Roadmap P5-3, 2026-09-20): das Budget-Gate der Vollständigkeits-Schleife in
`agents/orchestrator/verification.py` stand VOR dem Aufruf von `verifier.check_completeness()`.
Bei erschöpftem Budget wurde deshalb gar nicht erst gemessen - `completeness_report` blieb
`None`, die Aufzeichnung am Ende der Schleife fiel aus, und der Check galt als "nicht gemessen"
statt als bestanden oder gerissen.

`check_completeness()` ist ein rein deterministischer AST-/Dateisystem-Check
(`core/verifier/completeness.py`) und kostet KEINE Tokens. Das Gate sparte dort also nichts und
warf ein Qualitätssignal weg - genau in den Läufen, in denen es am meisten zählt. Real
beobachtet bei `sentinedge` (20260919_001502) und `eventforge_core` (20260919_003629):
"🚫 Lauf-Budget (`MAX_RUN_TOKENS=1,000,000`) erreicht - Vollständigkeits-Check nach Versuch 0
abgebrochen".

Messung über die letzten neun echten Läufe: der Verifikations-Anteil am Gesamtverbrauch liegt
im Median bei 16 %, bei Läufen MIT Budget-Abbruch aber zwischen 19,5 % und 35 % - die
konfigurierte `VERIFICATION_TOKEN_RESERVE_RATIO` von 15 % reicht also gerade in den
Reparaturläufen nicht, für die sie existiert. Budgetpflichtig ist deshalb nur noch der
FIX-Versuch (ein echter Agenten-Aufruf), nicht die Messung.
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
from core.verifier import VerificationReport
from core.verifier.models import CompletenessIssue, CompletenessReport
from core.workspace import WorkspaceManager

PASSING_TESTS = VerificationReport(
    ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1, failures=[],
)
_ISSUE = CompletenessIssue(
    file_path="app/db/base.py", line_number=1,
    message="Mehrere eigenständige SQLAlchemy-`Base`-Definitionen gefunden.",
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


class TestCompletenessMeasuredDespiteBudget(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, completeness_side_effect, *, budget_exhausted: bool):
        """Das Budget laeuft - wie in den echten Laeufen - erst WAEHREND der Verifikation leer,
        nicht schon davor: `sentinedge` und `eventforge_core` verbrauchten es in den
        Testsuite-Fixrunden und erreichten die Vollstaendigkeits-Schleife mit leerem Konto
        ("Vollstaendigkeits-Check nach Versuch 0 abgebrochen"). Waere es schon vor der
        Testsuite erschoepft, griffe ein voellig anderes, aeusseres Gate."""
        tests_done = {"value": False}

        @patch("agents.orchestrator.verification.upsert_ticket")
        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls, _mock_ticket):
            task = AgentTask(task_id="t1", agent_id="backend", description="app/main.py bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "budget_completeness_test_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""

            def _run_tests(*_a, **_kw):
                tests_done["value"] = True
                return PASSING_TESTS

            mock_verifier.run_tests.side_effect = _run_tests
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_lint.return_value = []
            mock_verifier.check_completeness.side_effect = completeness_side_effect

            status_logs: list[str] = []
            with patch.object(
                Orchestrator, "_run_budget_exceeded",
                side_effect=lambda *_a, **_kw: budget_exhausted and tests_done["value"],
            ):
                asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return status_logs, mock_verifier

        return _inner()

    def test_finding_is_measured_and_recorded_even_with_no_budget_left(self):
        """Der zentrale Fund: erschöpftes Budget darf die kostenlose MESSUNG nicht verhindern."""
        logs, mock_verifier = self._run(
            [FAILING_COMPLETENESS] * 4, budget_exhausted=True,
        )

        outcome = self.orchestrator.last_verification_outcome
        # Gemessen UND als Fehlschlag aufgezeichnet - nicht "nicht gemessen".
        self.assertIs(outcome.status("completeness"), False)
        self.assertIn("completeness", outcome.failed_checks)
        self.assertGreaterEqual(mock_verifier.check_completeness.call_count, 1)

    def test_protocol_says_measured_but_unfixed_not_check_aborted(self):
        """Der Text muss den Unterschied benennen: der Befund ist bekannt, nur der Fix fiel aus."""
        logs, _ = self._run([FAILING_COMPLETENESS] * 4, budget_exhausted=True)

        summary = self.orchestrator.last_verification_summary
        self.assertIn("Vollständigkeits-Fund(e) gemessen", summary)
        self.assertIn("kein Fixversuch mehr möglich", summary)
        # Die frühere, irrefuehrende Formulierung darf nicht mehr vorkommen.
        self.assertNotIn("Vollständigkeits-Check nach Versuch 0 abgebrochen", summary)

    def test_no_fix_agent_is_dispatched_when_the_budget_is_gone(self):
        """Gegenprobe zur Lockerung: budgetpflichtig bleibt der AGENTEN-Aufruf. Gemessen wird,
        aber es folgt keine Fix-Runde - im Protokoll darf also keine Korrektur-Beauftragung
        und kein Eskalations-Schritt auftauchen."""
        logs, _ = self._run([FAILING_COMPLETENESS] * 4, budget_exhausted=True)

        summary = self.orchestrator.last_verification_summary
        self.assertNotIn("Vollständigkeits-Fund(e) → gezielt zur Korrektur an", summary)
        self.assertFalse(any("stärkerem Modell" in line for line in logs))

    def test_passing_check_with_no_budget_is_recorded_as_passed(self):
        """Ein sauberes Projekt darf am leeren Budget nicht sein gruenes Ergebnis verlieren."""
        self._run([PASSING_COMPLETENESS] * 4, budget_exhausted=True)
        self.assertIs(self.orchestrator.last_verification_outcome.status("completeness"), True)

    def test_with_budget_available_the_fix_loop_still_runs(self):
        """Gegenprobe: bei vorhandenem Budget bleibt das bisherige Verhalten unveraendert -
        auf den Befund folgt ein echter Fixversuch und eine erneute Messung."""
        _logs, mock_verifier = self._run(
            [FAILING_COMPLETENESS, PASSING_COMPLETENESS, PASSING_COMPLETENESS], budget_exhausted=False,
        )
        self.assertGreaterEqual(mock_verifier.check_completeness.call_count, 2)
        self.assertIs(self.orchestrator.last_verification_outcome.status("completeness"), True)


if __name__ == "__main__":
    unittest.main()
