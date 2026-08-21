"""
tests/test_cli_plan_preview.py – Testet die CLI-seitige Plan-Vorschau & Weiterleitung

interface/cli.py._render_and_confirm_plan() zeigt den von TaskManager.decompose() erstellten
Plan gruppiert nach Fachbereich und lässt ihn bestätigen; _process_task() reicht diese Methode
als plan_confirmation_callback an Orchestrator.process() durch (siehe
tests/test_plan_confirmation_gate.py für die Gate-Logik selbst, die hier NICHT erneut
getestet wird).
"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import core.backlog_store as backlog_store
from core.message_bus import AgentTask
from interface.cli import CLIInterface


class TestRenderAndConfirmPlan(unittest.TestCase):
    def setUp(self):
        self.cli = CLIInterface()
        self._print_patcher = patch("interface.cli.console.print")
        self._print_patcher.start()
        self.addCleanup(self._print_patcher.stop)
        # _process_task() schreibt jetzt auch ins Backlog (core/backlog_store.py) - gegen ein
        # temporäres Verzeichnis statt der echten memory/backlog.json.
        self._backlog_dir = tempfile.mkdtemp()
        self._backlog_patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(self._backlog_dir) / "backlog.json")
        self._backlog_patcher.start()
        self.addCleanup(self._backlog_patcher.stop)

    def _tasks(self) -> list[AgentTask]:
        return [
            AgentTask(task_id="t1", agent_id="backend", description="FastAPI-Endpunkt implementieren"),
            AgentTask(task_id="t2", agent_id="frontend", description="React-Formular bauen"),
            AgentTask(task_id="t3", agent_id="tester", description="Unit-Tests schreiben"),
        ]

    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_approval_is_returned(self, mock_confirm):
        result = self.cli._render_and_confirm_plan("Kurze Aufgabe", "mein_projekt", self._tasks())
        self.assertTrue(result)

    @patch("interface.cli.Confirm.ask", return_value=False)
    def test_decline_is_returned(self, mock_confirm):
        result = self.cli._render_and_confirm_plan("Kurze Aufgabe", "mein_projekt", self._tasks())
        self.assertFalse(result)

    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_prompt_mentions_correct_task_and_department_counts(self, mock_confirm):
        self.cli._render_and_confirm_plan("Kurze Aufgabe", "mein_projekt", self._tasks())

        prompt_text = mock_confirm.call_args[0][0]
        self.assertIn("3 Spezialist(en)", prompt_text)
        # backend/frontend -> dev_lead, tester -> qa_lead: 2 Fachbereiche
        self.assertIn("2 Fachbereich(en)", prompt_text)

    @patch("interface.cli.Confirm.ask", return_value=True)
    def test_panel_shows_department_titles_and_agent_names(self, mock_confirm):
        with patch("interface.cli.Panel") as mock_panel:
            self.cli._render_and_confirm_plan("Kurze Aufgabe", "mein_projekt", self._tasks())

        panel_content = mock_panel.call_args[0][0]
        self.assertIn("Backend-Entwickler", panel_content)
        self.assertIn("Frontend-Entwickler", panel_content)
        self.assertIn("FastAPI-Endpunkt implementieren", panel_content)
        self.assertIn("mein_projekt", panel_content)


class TestProcessTaskForwardsPlanCallback(unittest.TestCase):
    def setUp(self):
        # _process_task() schreibt jetzt auch ins Backlog (core/backlog_store.py) - gegen ein
        # temporäres Verzeichnis statt der echten memory/backlog.json.
        self._backlog_dir = tempfile.mkdtemp()
        self._backlog_patcher = patch.object(backlog_store, "BACKLOG_FILE", Path(self._backlog_dir) / "backlog.json")
        self._backlog_patcher.start()
        self.addCleanup(self._backlog_patcher.stop)

    def _run_process_task(self):
        cli = CLIInterface()
        cli._orchestrator.process = AsyncMock(return_value="### ok")
        with patch("interface.cli.console.print"), patch("interface.cli.Live"), \
                patch("interface.cli.Confirm.ask", return_value=False):
            asyncio.run(cli._process_task("Baue etwas"))
        return cli._orchestrator.process

    @patch("interface.cli.ENABLE_PLAN_CONFIRMATION", True)
    def test_passes_a_real_callback_when_enabled(self):
        mock_process = self._run_process_task()
        callback = mock_process.call_args.kwargs.get("plan_confirmation_callback")
        self.assertIsNotNone(callback)
        self.assertTrue(callable(callback))

    @patch("interface.cli.ENABLE_PLAN_CONFIRMATION", False)
    def test_passes_none_when_disabled(self):
        mock_process = self._run_process_task()
        self.assertIsNone(mock_process.call_args.kwargs.get("plan_confirmation_callback"))


if __name__ == "__main__":
    unittest.main()
