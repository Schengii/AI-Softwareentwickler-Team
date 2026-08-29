"""
tests/test_small_department_sequential.py – Testet Sequenzialität bei kleinen Fachbereichen

Realer Fund: Für eine triviale Aufgabe entstanden zwei parallele Implementierungen
derselben Sache (app.py/test_app.py UND separat main.py/test_main.py für denselben
Health-Check-Endpoint), weil zwei Agenten desselben "parallelen" Fachbereichs fast
zeitgleich starteten und sich nie gegenseitig sahen. agents/orchestrator.py führt
Fachbereiche mit nur 1-2 Mitgliedern jetzt IMMER sequenziell aus (unabhängig von der
für den Fachbereich generell hinterlegten Präferenz), damit ein später startender Agent
die Dateien des ersten tatsächlich sieht.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse, ToolCall
from core.message_bus import AgentTask
from core.verifier import VerificationReport


class _WritesThenFinishesLLM:
    """Schreibt im ersten Tool-Aufruf eine Datei, antwortet danach final."""

    def __init__(self, filename: str):
        self.model_name = "fake-model"
        self._filename = filename
        self._step = 0

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        self._step += 1
        if self._step == 1:
            return LLMResponse(
                text="", model_name=self.model_name, prompt_tokens=10, completion_tokens=5, total_tokens=15,
                tool_calls=[ToolCall(id="c1", name="write_file", arguments={
                    "path": self._filename, "content": "print('hi')\n",
                })],
            )
        return LLMResponse(text="Fertig.", model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[])


class _CapturingLLM:
    """Merkt sich den ersten Prompt-Text und antwortet sofort final (keine Tools)."""

    def __init__(self):
        self.model_name = "fake-model"
        self.first_prompt_text: str | None = None

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        if self.first_prompt_text is None:
            self.first_prompt_text = messages[0].text
        return LLMResponse(text="Fertig.", model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[])


class TestSmallDepartmentRunsSequentially(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        from core.workspace import WorkspaceManager
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in self.orchestrator._agents.values():
            agent._llm = _CapturingLLM()
        for lead in self.orchestrator._dept_leads.values():
            lead._llm = _CapturingLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def test_second_agent_sees_file_written_by_first_in_a_two_member_department(self):
        # dev_lead-Fachbereich mit genau 2 Mitgliedern. DEPARTMENT_DEFINITIONS listet "frontend"
        # VOR "backend" (siehe agents/department_lead_agent.py) - member_tasks übernimmt diese
        # Reihenfolge, frontend läuft also zuerst. backend soll dessen Datei in seiner
        # Dateibaum-Vorschau sehen, wenn wirklich sequenziell (nicht parallel) gelaufen wird.
        writer_llm = _WritesThenFinishesLLM("app.py")
        observer_llm = _CapturingLLM()
        self.orchestrator._agents["frontend"]._llm = writer_llm
        self.orchestrator._agents["backend"]._llm = observer_llm

        @patch("agents.orchestrator.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _run(mock_synthesize, mock_decompose, mock_verifier_cls):
            mock_decompose.return_value = (
                "Kurze Aufgabe", "seq_test_proj",
                [
                    AgentTask(task_id="t1", agent_id="frontend", description="app.py schreiben"),
                    AgentTask(task_id="t2", agent_id="backend", description="Anbindung ergänzen"),
                ],
            )
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=False, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.0,
                reason_skipped="simuliert",
            )
            asyncio.run(self.orchestrator.process("Baue etwas"))

        _run()

        assert observer_llm.first_prompt_text is not None
        self.assertIn("BEREITS VORHANDENE DATEIEN", observer_llm.first_prompt_text)
        self.assertIn("app.py", observer_llm.first_prompt_text)

    def test_department_with_three_or_more_members_still_runs_in_parallel(self):
        """Gegenprobe: der Sequenzialitäts-Fix darf NICHT den Parallelitäts-Nutzen für
        größere Fachbereiche kosten - ab 3 Mitgliedern bleibt es bei echtem asyncio.gather."""
        for agent_id in ("frontend", "backend", "database"):
            self.orchestrator._agents[agent_id]._llm = _CapturingLLM()
        for lead in self.orchestrator._dept_leads.values():
            lead._llm = _CapturingLLM()

        with patch("agents.orchestrator.Orchestrator._run_agents_parallel", wraps=self.orchestrator._run_agents_parallel) as spy:
            @patch("agents.orchestrator.ProjectVerifier")
            @patch("core.task_manager.TaskManager.decompose")
            @patch("core.result_aggregator.ResultAggregator.synthesize")
            def _run(mock_synthesize, mock_decompose, mock_verifier_cls):
                mock_decompose.return_value = (
                    "Kurze Aufgabe", "parallel_test_proj",
                    [
                        AgentTask(task_id="t1", agent_id="frontend", description="UI bauen"),
                        AgentTask(task_id="t2", agent_id="backend", description="API bauen"),
                        AgentTask(task_id="t3", agent_id="database", description="Schema bauen"),
                    ],
                )
                mock_synthesize.return_value = ("### Fertig", 5)
                mock_verifier = mock_verifier_cls.return_value
                mock_verifier.ensure_environment.return_value = ""
                mock_verifier.run_tests.return_value = VerificationReport(
                    ran=False, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.0,
                    reason_skipped="simuliert",
                )
                asyncio.run(self.orchestrator.process("Baue etwas"))

            _run()
            spy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
