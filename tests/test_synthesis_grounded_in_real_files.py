"""
tests/test_synthesis_grounded_in_real_files.py – Testet, dass process() echten statt vom
LLM erfundenen Code anzeigt

Realer Fund aus einem echten End-to-End-Testlauf: die finale LLM-Synthese
(ResultAggregator.synthesize()) zeigte Code, der NICHT mit der tatsächlich geschriebenen
Datei übereinstimmte. agents/orchestrator.py.process() hängt jetzt einen deterministischen,
direkt von der Platte gelesenen "Tatsächlich geschriebene Dateien"-Abschnitt an (siehe
tests/test_real_files_section.py für die Methode selbst) – dieser Test beweist, dass er
wirklich im finalen Antworttext ankommt, auch wenn die LLM-Synthese etwas ANDERES behauptet.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse, ToolCall
from core.message_bus import AgentTask
from core.workspace import WorkspaceManager


class _WritesRealCodeThenFinishes:
    """Schreibt echten Code per write_file, antwortet danach final - simuliert exakt das
    reale Muster (Agent schreibt via Tool, sein Abschlusstext ist nur eine Kurzbeschreibung)."""

    REAL_CODE = "def add(a, b):\n    return a + b\n"

    def __init__(self):
        self.model_name = "fake-model"
        self._step = 0

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        self._step += 1
        if self._step == 1:
            return LLMResponse(
                text="", model_name=self.model_name, prompt_tokens=10, completion_tokens=5, total_tokens=15,
                tool_calls=[ToolCall(id="c1", name="write_file", arguments={
                    "path": "calc.py", "content": self.REAL_CODE,
                })],
            )
        return LLMResponse(text="Fertig implementiert.", model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[])

    async def generate_with_usage(self, prompt, system_prompt=None):
        return LLMResponse(text="Fertig.", model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15)


class TestFinalOutputContainsRealFileContent(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _WritesRealCodeThenFinishes()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def test_real_file_content_appears_even_when_synthesis_claims_something_different(self):
        # Die "LLM-Synthese" behauptet bewusst einen ANDEREN Code als den echten - genau das
        # reale Fehlerbild (Divergenz zwischen Erzählung und tatsächlicher Datei).
        fabricated_summary = "```python\ndef add(x, y):\n    return x + y + 1  # ERFUNDEN, nicht die echte Datei\n```"

        @patch("agents.orchestrator.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _run(mock_synthesize, mock_decompose, mock_verifier_cls):
            task = AgentTask(task_id="t1", agent_id="backend", description="Addiere zwei Zahlen")
            mock_decompose.return_value = ("Kurze Aufgabe", "grounding_test_proj", [task])
            mock_synthesize.return_value = (fabricated_summary, 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            from core.verifier import VerificationReport
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=False, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.0,
                reason_skipped="simuliert",
            )
            return asyncio.run(self.orchestrator.process("Baue etwas"))

        result = _run()

        # Der echte Code muss im Ergebnis auftauchen ...
        self.assertIn(_WritesRealCodeThenFinishes.REAL_CODE.strip(), result)
        self.assertIn("calc.py", result)
        # ... die erfundene Synthese-Behauptung darf zwar auch drinstehen (sie ist Teil der
        # LLM-Erzählung), aber der ECHTE Code muss zusätzlich als Ground Truth vorhanden sein.
        self.assertIn("Tatsächlich geschriebene Dateien", result)


if __name__ == "__main__":
    unittest.main()
