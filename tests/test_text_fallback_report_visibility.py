"""
tests/test_text_fallback_report_visibility.py – Testet, dass per Text-Fallback gespeicherte
Dateien (core/workspace.py.parse_and_save_files, ausgelöst wenn ein Agent Code nur im
Antworttext statt über write_file/edit_file liefert) im Abschlussbericht NAMENTLICH sichtbar
sind, nicht nur als anonyme Zahl.

Realer Fund aus einem echten Lauf: eine so gespeicherte main.py bestand nur aus einem
Patch-/Integrations-Kommentar + drei Zeilen ohne die dafür nötigen Imports (syntaktisch
gültiges, aber semantisch unvollständiges Python - core/workspace.py.parse_and_save_files()
prüft nur echte Syntaxfehler, nicht das). Ohne den Dateinamen im Bericht war bei einem
späteren Lint-/Testfehler nicht erkennbar, welche der vielen Dateien überhaupt über diesen
fehleranfälligeren Pfad statt eines echten write_file-Tool-Aufrufs entstanden ist.
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
from core.workspace import WorkspaceManager


class _FakeToolCapableLLM:
    def __init__(self, text: str):
        self._text = text
        self.model_name = "fake-model"

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[])

    async def generate_with_usage(self, prompt, system_prompt=None):
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15)


class TestTextFallbackReportVisibility(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        # Codeblock mit Datei-Pfad im Antworttext statt eines echten write_file-Tool-Aufrufs -
        # genau der Pfad, den core/workspace.py.parse_and_save_files() abfängt.
        fake_text = "```python:app/routes.py\nfrom fastapi import APIRouter\nrouter = APIRouter()\n```"
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM(fake_text)

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    @patch("agents.orchestrator.ProjectVerifier")
    @patch("core.task_manager.TaskManager.decompose")
    @patch("core.result_aggregator.ResultAggregator.synthesize")
    def _run(self, mock_synthesize, mock_decompose, mock_verifier_cls):
        mock_decompose.return_value = (
            "Baue eine kleine API", "kleine_api",
            [AgentTask(task_id="t1", agent_id="backend", description="Router bauen")],
        )
        mock_synthesize.return_value = ("### Fertig", 5)
        mock_verifier = mock_verifier_cls.return_value
        mock_verifier.ensure_environment.return_value = ""
        mock_verifier.run_tests.return_value = VerificationReport(
            ran=False, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.0,
            reason_skipped="simuliert",
        )
        status_logs: list[str] = []
        result = asyncio.run(self.orchestrator.process("Baue eine kleine API", status_callback=status_logs.append))
        return result, status_logs

    def test_final_report_names_the_text_fallback_file(self):
        result, _ = self._run()
        self.assertIn("Text-Fallback gespeicherte Dateien", result)
        self.assertIn("app/routes.py", result)

    def test_live_status_log_names_the_text_fallback_file(self):
        _, status_logs = self._run()
        self.assertTrue(
            any("Text-Fallback" in line and "app/routes.py" in line for line in status_logs),
            f"Erwartete Datei-Nennung im Live-Log fehlt in: {status_logs}",
        )


if __name__ == "__main__":
    unittest.main()
