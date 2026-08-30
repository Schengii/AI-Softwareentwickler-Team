"""
tests/test_telemetry_resilience.py – Testet, dass ein Fehler in der reinen Tokenzahlen-/
Historien-Buchhaltung am Ende von Orchestrator.process() niemals einen sonst erfolgreichen
Lauf zum Scheitern bringt.

Realer Fund aus einem echten Lauf: record_run()/record_run_usage()/record_run_history()
werden am ALLERLETZTEN Schritt von process() aufgerufen, NACHDEM das fertige, konsolidierte
Ergebnis bereits in die Konversationshistorie geschrieben wurde. Ihre eigenen Kommentare/
Docstrings behaupten "rein additiv, darf einen sonst erfolgreichen Lauf niemals zum Scheitern
bringen" - das galt aber bisher nur für abgefangene I/O-Fehler. Ein `KeyError('cache_read_
tokens')` (beobachtet - vermutlich eine SDK-interne Eigenheit bei aktivem Prompt-Caching,
core/llm_factory.py/core/token_guard.py/memory/cost_history.py greifen bereits überall
defensiv über .get()/getattr(..., default) zu, siehe git-Historie) schlug UNBEHANDELT bis
zum CLI-Top-Level-Handler durch - der Nutzer verlor dadurch das bereits fertige Ergebnis
komplett, obwohl die eigentliche Team-Arbeit längst erfolgreich abgeschlossen war.
"""

import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.verifier import VerificationReport
from core.workspace import WorkspaceManager


class _FakeToolCapableLLM:
    def __init__(self, text: str, model_name: str = "gemini-2.5-flash"):
        self._text = text
        self.model_name = model_name

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        return LLMResponse(
            text=self._text, model_name=self.model_name,
            prompt_tokens=150, completion_tokens=80, total_tokens=230, tool_calls=[],
        )

    async def generate_with_usage(self, prompt, system_prompt=None):
        return LLMResponse(
            text=self._text, model_name=self.model_name,
            prompt_tokens=150, completion_tokens=80, total_tokens=230,
        )


class TestTelemetryResilience(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        fake_text = "### Zusammenfassung\nErledigt."
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM(fake_text)

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    @patch("agents.orchestrator.ProjectVerifier")
    @patch("core.task_manager.TaskManager.decompose")
    @patch("core.result_aggregator.ResultAggregator.synthesize")
    @patch("agents.orchestrator.record_run_usage")
    async def _run_with_broken_cost_history(self, mock_record_usage, mock_synthesize, mock_decompose, mock_verifier_cls):
        # Simuliert exakt den beobachteten Absturz: ein KeyError aus der Tokenzahlen-
        # Buchhaltung, NACHDEM alle Fachbereiche bereits fertig gearbeitet haben.
        mock_record_usage.side_effect = KeyError("cache_read_tokens")

        mock_decompose.return_value = (
            "Baue eine kleine App", "kleine_app",
            [AgentTask(task_id="t1", agent_id="product_owner", description="Scope")],
        )
        mock_synthesize.return_value = ("### Zusammenfassung: App fertig!", 50)

        mock_verifier = mock_verifier_cls.return_value
        mock_verifier.ensure_environment.return_value = ""
        mock_verifier.run_tests.return_value = VerificationReport(
            ran=False, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.0,
            reason_skipped="Keine Testdateien gefunden (simuliert).",
        )

        status_logs: list[str] = []
        # Der eigentliche Test: process() darf HIER NICHT raisen, obwohl record_run_usage()
        # intern einen KeyError wirft - vorher propagierte das bis zum Aufrufer durch.
        result = await self.orchestrator.process(
            "Baue mir eine kleine App",
            status_callback=lambda msg: status_logs.append(msg),
        )
        return result, status_logs

    def test_process_returns_final_result_despite_cost_history_crash(self):
        import asyncio
        result, status_logs = asyncio.run(self._run_with_broken_cost_history())

        # Das fertige Ergebnis muss trotzdem beim Aufrufer ankommen statt verloren zu gehen.
        self.assertIn("App fertig", result)
        self.assertIn("Projekt-Kennzahlen", result)

        # Der Fehler wird als Warnung sichtbar gemacht, nicht stillschweigend verschluckt.
        warning_lines = [line for line in status_logs if "Kosten-Historie" in line and "cache_read_tokens" in line]
        self.assertTrue(warning_lines, f"Erwartete Warnung zur fehlgeschlagenen Kosten-Historie fehlt in: {status_logs}")

    @patch("agents.orchestrator.ProjectVerifier")
    @patch("core.task_manager.TaskManager.decompose")
    @patch("core.result_aggregator.ResultAggregator.synthesize")
    @patch("agents.orchestrator.record_run")
    @patch("agents.orchestrator.record_run_history")
    async def _run_with_all_three_broken(
        self, mock_record_run_history, mock_record_run, mock_synthesize, mock_decompose, mock_verifier_cls,
    ):
        # Alle DREI Telemetrie-Aufrufe schlagen gleichzeitig fehl - jeder einzeln in einem
        # eigenen try/except, damit ein Fehler im einen die anderen beiden nicht verhindert.
        mock_record_run.side_effect = RuntimeError("Projekt-Historie kaputt")
        mock_record_run_history.side_effect = RuntimeError("Lauf-Historie kaputt")

        mock_decompose.return_value = (
            "Baue eine kleine App", "kleine_app_2",
            [AgentTask(task_id="t1", agent_id="product_owner", description="Scope")],
        )
        mock_synthesize.return_value = ("### Zusammenfassung: App auch fertig!", 50)

        mock_verifier = mock_verifier_cls.return_value
        mock_verifier.ensure_environment.return_value = ""
        mock_verifier.run_tests.return_value = VerificationReport(
            ran=False, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.0,
            reason_skipped="Keine Testdateien gefunden (simuliert).",
        )

        with patch("agents.orchestrator.record_run_usage", side_effect=ValueError("Kosten-Historie kaputt")):
            result = await self.orchestrator.process("Baue mir noch eine kleine App")
        return result

    def test_process_survives_all_three_telemetry_calls_failing_at_once(self):
        import asyncio
        result = asyncio.run(self._run_with_all_three_broken())
        self.assertIn("App auch fertig", result)


if __name__ == "__main__":
    unittest.main()
