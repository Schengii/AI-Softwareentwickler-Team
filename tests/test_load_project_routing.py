"""
tests/test_load_project_routing.py – Testet, dass /load die Folge-Nachrichten wirklich routet

Realer Fund: interface/cli.py speicherte den per `/load <name>` gewählten Pfad zwar in
`_loaded_project_dir`, reichte ihn aber nie an Orchestrator.process() durch – nur `/rag`
nutzte ihn. Jede normale Chat-Nachricht nach einem `/load` liess den TaskManager trotzdem
einen NEUEN project_slug raten und legte einen NEUEN workspace/-Ordner an, obwohl der
Hilfetext genau das Gegenteil verspricht ("So entwickelst du ein bestehendes Projekt
weiter: 1. Lade das Projekt... 2. Gib dem Team deine Anweisung."). Das erklärt reale
Duplikate wie calculator_service/simple_calculator.

Diese Tests stellen sicher, dass:
1. Orchestrator.process(forced_project_dir=...) genau dieses Verzeichnis nutzt und NICHT
   project_slug/get_project_dir() zur Pfadwahl heranzieht.
2. Ohne forced_project_dir (Standardfall, kein /load aktiv) bleibt das bisherige Verhalten
   (frisch geratener project_slug) unverändert.
3. interface/cli.py._process_task() reicht self._loaded_project_dir tatsächlich durch.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import core.backlog_store as backlog_store
from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.verifier import VerificationReport
from core.workspace import WorkspaceManager
from interface.cli import CLIInterface


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


class TestForcedProjectDirRouting(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.external_dir = tempfile.mkdtemp()  # simuliert ein per /load geladenes Projekt
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)
        shutil.rmtree(self.external_dir, ignore_errors=True)

    def _run(self, forced_project_dir: str | None):
        @patch("agents.orchestrator.verification.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            task = AgentTask(task_id="t1", agent_id="backend", description="Etwas bauen")
            mock_decompose.return_value = ("Kurze Aufgabe", "irrelevant_guessed_slug", [task])
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=False, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.0,
                reason_skipped="simuliert",
            )
            asyncio.run(self.orchestrator.process("Baue etwas", forced_project_dir=forced_project_dir))
            return task

        return _inner()

    def test_forced_project_dir_is_used_verbatim_ignoring_guessed_slug(self):
        task = self._run(self.external_dir)
        self.assertEqual(task.project_dir, self.external_dir)
        # Der geratene Slug darf KEINEN neuen Ordner im Workspace anlegen.
        self.assertNotIn("irrelevant_guessed_slug", self.orchestrator._workspace.list_projects())

    def test_without_forced_dir_falls_back_to_guessed_slug_in_workspace(self):
        task = self._run(None)
        expected = str(Path(self.temp_workspace) / "irrelevant_guessed_slug")
        self.assertEqual(str(Path(task.project_dir)), expected)


class TestCliPassesLoadedProjectDir(unittest.TestCase):
    def test_process_task_forwards_loaded_project_dir_to_orchestrator(self):
        cli = CLIInterface()
        cli._loaded_project_dir = r"C:\some\loaded\project"
        cli._orchestrator.process = AsyncMock(return_value="### ok")

        # _process_task loest am Ende auch das Git-Push-Gate aus (siehe tests/test_cli_push_gate.py)
        # - hier bewusst mit Confirm.ask=False stillgelegt, das ist nicht Testgegenstand dieses Falls.
        # _process_task() schreibt außerdem jetzt ins Backlog (core/backlog_store.py) - gegen ein
        # temporäres Verzeichnis statt der echten memory/backlog.json.
        backlog_dir = tempfile.mkdtemp()
        with patch("interface.cli.console.print"), patch("interface.cli.Live"), \
                patch("interface.cli.Confirm.ask", return_value=False), \
                patch.object(backlog_store, "BACKLOG_FILE", Path(backlog_dir) / "backlog.json"):
            asyncio.run(cli._process_task("Mach etwas an diesem Projekt"))

        cli._orchestrator.process.assert_called_once()
        self.assertEqual(
            cli._orchestrator.process.call_args.kwargs.get("forced_project_dir"),
            r"C:\some\loaded\project",
        )


if __name__ == "__main__":
    unittest.main()
