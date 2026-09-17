"""
tests/test_verification_no_progress_breaker.py – Testet den Zirkuit-Breaker in
agents/orchestrator/verification.py._run_verification_loop(): wenn ein Fixversuch die
Testfehler NICHT verändert hat (identische test_id+Fehlermeldung wie vor dem Versuch), bricht
die Schleife sofort ab statt einen zweiten, meist ebenso wirkungslosen Versuch zu verbrauchen.

Realer Fund (taskpulse-Projekt, 2026-09-03): 33 Agenten-Durchläufe / 714k Tokens / 23 Minuten,
weil jede der mehreren Fix-Schleifen (Test-, Governance-, Vollständigkeits-Schleife) ihre volle
Versuchszahl auch dann ausschöpfte, wenn der erste Versuch erkennbar nichts verändert hatte.
"""

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

_FAILURE = TestFailure(test_id="tests/test_app.py::test_x", message="AssertionError: boom", files=["backend/app.py"])

FAILING_REPORT = VerificationReport(
    ran=True, passed=False, exit_code=1, stdout="", stderr="", duration_seconds=0.1,
    failures=[_FAILURE],
)
DIFFERENT_FAILING_REPORT = VerificationReport(
    ran=True, passed=False, exit_code=1, stdout="", stderr="", duration_seconds=0.1,
    failures=[TestFailure(test_id="tests/test_app.py::test_y", message="AssertionError: other", files=["backend/app.py"])],
)
YET_ANOTHER_FAILING_REPORT = VerificationReport(
    ran=True, passed=False, exit_code=1, stdout="", stderr="", duration_seconds=0.1,
    failures=[TestFailure(test_id="tests/test_app.py::test_z", message="AssertionError: yet another", files=["backend/app.py"])],
)
PASSING_REPORT = VerificationReport(
    ran=True, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.1, failures=[],
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




class TestVerificationNoProgressBreaker(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()
        self.orchestrator._agents["backend"]._llm = _ScriptedLLM(written_file="backend/app.py")

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, run_tests_side_effect):
        # Team-Optimierung (2026-09-05, Punkt 3): der letzte Eskalationsschritt vor dem
        # endgültigen Aufgeben ersetzt _llm auf den stecken gebliebenen Agenten per
        # LLMFactory.create_for_model(HEAVY_MODEL) - ohne diesen Patch würde der Test einen
        # ECHTEN Provider-Client konstruieren (und, falls in dieser Umgebung ein API-Key gesetzt
        # ist, sogar einen echten API-Aufruf auslösen) statt weiter mit einer kontrollierten
        # Test-Double zu arbeiten.
        @patch("core.llm_factory.LLMFactory.create_for_model")
        @patch("agents.orchestrator.verification.upsert_ticket")
        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls, mock_upsert_ticket, mock_create_for_model):
            mock_create_for_model.side_effect = lambda model_name: _ScriptedLLM(written_file="backend/app.py")
            task = AgentTask(task_id="t1", agent_id="backend", description="backend/app.py bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "no_progress_test_proj", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.side_effect = run_tests_side_effect
            mock_verifier.check_docker_build.return_value.attempted = False
            mock_verifier.check_load_test.return_value.attempted = False
            mock_verifier.check_dependency_vulnerabilities.return_value = []
            mock_verifier.check_lint.return_value = []

            status_logs: list[str] = []
            result = asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return result, status_logs, mock_verifier, mock_upsert_ticket

        return _inner()

    def test_identical_failures_after_fix_stop_loop_early(self):
        # MAX_VERIFICATION_ITERATIONS ist standardmäßig 2 - ohne Zirkuit-Breaker würde die
        # Schleife TROTZDEM beide regulären Versuche ausschöpfen. Seit dem Eskalations-
        # Strategiewechsel (Team-Retrospektive: "letzter Stand wurde übernommen" statt eine
        # andere Strategie zu versuchen) folgt auf "kein Fortschritt" GENAU EIN zusätzlicher,
        # sofort geprüfter Eskalationsversuch an den Fachbereichsleiter, UND (Team-Optimierung
        # 2026-09-05, Punkt 3) danach GENAU EIN weiterer, ebenfalls sofort geprüfter Versuch mit
        # auf HEAVY_MODEL hochgestuften, stecken gebliebenen Agenten, bevor endgültig aufgegeben
        # wird - macht 4 echte run_tests-Aufrufe insgesamt (2 reguläre + 1 Eskalations-Recheck +
        # 1 Modell-Eskalations-Recheck). Ein fünfter Eintrag im side_effect (der nie erreicht
        # werden darf) macht das weiterhin messbar.
        result, logs, mock_verifier, mock_upsert_ticket = self._run(
            [FAILING_REPORT, FAILING_REPORT, FAILING_REPORT, FAILING_REPORT, FAILING_REPORT],
        )

        self.assertEqual(mock_verifier.run_tests.call_count, 4)
        self.assertFalse(self.orchestrator.last_verification_ok)
        self.assertTrue(any("Strategiewechsel" in line for line in logs))
        self.assertTrue(any("Kein Fortschritt" in line for line in logs))
        mock_upsert_ticket.assert_called()

    def test_model_escalation_recovers_after_failed_lead_escalation(self):
        # Team-Optimierung (2026-09-05, Punkt 3): schlägt sowohl der reguläre Fixversuch als
        # auch die Eskalation an den Fachbereichsleiter fehl (identischer Fehler), bekommt der
        # stecken gebliebene Agent (hier: backend) für GENAU einen letzten Versuch HEAVY_MODEL,
        # BEVOR aufgegeben und ein Ticket eröffnet wird. Schlägt DIESER Versuch an - hier
        # simuliert per PASSING_REPORT als 4. run_tests-Ergebnis - gilt der Lauf als verifiziert,
        # OHNE dass ein "recurring-failure"-Ticket eröffnet wird.
        result, logs, mock_verifier, mock_upsert_ticket = self._run(
            [FAILING_REPORT, FAILING_REPORT, FAILING_REPORT, PASSING_REPORT],
        )

        self.assertEqual(mock_verifier.run_tests.call_count, 4)
        self.assertTrue(self.orchestrator.last_verification_ok)
        self.assertEqual(self.orchestrator._agents["backend"]._llm.model_name, "fake-model")
        self.assertTrue(any("stärkerem Modell" in line for line in logs))
        self.assertTrue(any("Modell-Eskalation erfolgreich" in line for line in logs))
        mock_upsert_ticket.assert_not_called()

    def test_model_escalation_warns_when_heavy_model_not_actually_reached(self):
        # Realer Fund (chronoflow-Lauf 20260917_092911): `_escalate_agent_models()` setzt
        # `agent._llm` zwar zuverlässig auf HEAVY_MODEL, der tatsächliche API-Aufruf kann aber
        # (Kontingent-Erschöpfung) intern auf ein schwächeres Modell zurückfallen - `model_used`
        # zeigte am Ende `gemini-3.8-flash` statt des angeforderten `gemini-pro-latest`. Das
        # Test-Double hier meldet als `model_used` bewusst "fake-model" (keine HEAVY-Stufe) -
        # exakt dieselbe Situation, die die neue Prüfung erkennen und melden soll, UNABHÄNGIG
        # davon, ob der Fixversuch am Ende erfolgreich war.
        result, logs, mock_verifier, mock_upsert_ticket = self._run(
            [FAILING_REPORT, FAILING_REPORT, FAILING_REPORT, PASSING_REPORT],
        )

        self.assertTrue(self.orchestrator.last_verification_ok)
        self.assertTrue(any("nicht tatsächlich erreicht" in line for line in logs))

    def test_recurring_failure_ticket_notes_heavy_model_not_reached(self):
        """Scheitert die Verifikation trotz HEAVY_MODEL-Eskalation endgültig, muss das
        `recurring-failure`-Ticket den Hinweis enthalten, dass die Eskalation die Modellstufe
        nicht tatsächlich erreicht hat - sonst liest sich das Ticket wie ein Agenten-/
        Prompt-Befund, obwohl es (hier: per Test-Double simuliert) ein Infrastruktur-/
        Kontingent-Befund ist."""
        result, logs, mock_verifier, mock_upsert_ticket = self._run(
            [FAILING_REPORT, FAILING_REPORT, FAILING_REPORT, FAILING_REPORT, FAILING_REPORT],
        )

        recurring_calls = [
            c for c in mock_upsert_ticket.call_args_list
            if str(c.kwargs.get("ticket_id", "")).startswith("recurring-failure-")
        ]
        self.assertTrue(recurring_calls)
        self.assertTrue(
            any("HEAVY_MODEL-Eskalation für" in str(c.kwargs.get("detail", "")) for c in recurring_calls)
        )

    def test_different_failures_after_fix_do_not_trigger_breaker(self):
        # MAX_VERIFICATION_ITERATIONS ist standardmäßig 3 (config.py) - drei jeweils
        # UNTERSCHIEDLICHE Fehlschläge, damit keiner der drei regulär erlaubten Versuche vom
        # Zirkuit-Breaker abgebrochen wird.
        result, logs, mock_verifier, mock_upsert_ticket = self._run(
            [FAILING_REPORT, DIFFERENT_FAILING_REPORT, YET_ANOTHER_FAILING_REPORT],
        )

        # Unterschiedliche Fehlermeldungen nach jedem Fixversuch = echter Fortschritt - alle drei
        # regulär erlaubten Versuche laufen, KEIN früher Abbruch durch den Zirkuit-Breaker.
        self.assertEqual(mock_verifier.run_tests.call_count, 3)
        self.assertFalse(any("Kein Fortschritt" in line for line in logs))
        self.assertTrue(any("Maximale Verifikations-Iterationen erreicht" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
