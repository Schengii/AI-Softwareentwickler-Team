"""
tests/test_duplicate_project_warning.py – Testet die Frühwarnung vor doppelten Projekten

Realer Fund aus einem echten Lauf: "calculator_service" vs. "simple_calculator" und
"notes_tasks_api" vs. "personal_notes_tasks" waren jeweils zwei komplette, separat
bezahlte Läufe für praktisch dieselbe Anwendung, weil project_slug pro Lauf neu vom
Modell geraten wird und sich selbst bei inhaltlich identischer Aufgabe unterscheiden
kann. agents/orchestrator.py.process() gibt seitdem einen rein informativen Hinweis
aus (kein LLM-Aufruf, keine Heuristik), sobald ein NEUER Projektordner angelegt würde,
während bereits andere Projekte im Workspace existieren.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.project_status import record_run
from core.verifier import VerificationReport
from core.workspace import WorkspaceManager


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


class TestDuplicateProjectWarning(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self, new_slug: str):
        @patch("agents.orchestrator.ProjectVerifier")
        @patch("core.task_manager.TaskManager.decompose")
        @patch("core.result_aggregator.ResultAggregator.synthesize")
        def _inner(mock_synthesize, mock_decompose, mock_verifier_cls):
            mock_decompose.return_value = (
                "Kurze Aufgabe", new_slug,
                [AgentTask(task_id="t1", agent_id="backend", description="Etwas bauen")],
            )
            mock_synthesize.return_value = ("### Fertig", 5)
            mock_verifier = mock_verifier_cls.return_value
            mock_verifier.ensure_environment.return_value = ""
            mock_verifier.run_tests.return_value = VerificationReport(
                ran=False, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.0,
                reason_skipped="simuliert",
            )
            status_logs: list[str] = []
            asyncio.run(self.orchestrator.process("Baue etwas", status_callback=status_logs.append))
            return status_logs

        return _inner()

    def test_warns_when_new_project_created_alongside_existing_ones(self):
        (self.orchestrator._workspace.base_dir / "calculator_service").mkdir()
        logs = self._run("simple_calculator")
        self.assertTrue(any("Neues Projekt 'simple_calculator'" in line and "calculator_service" in line for line in logs))
        self.assertTrue(any("/load" in line for line in logs))

    def test_no_warning_on_first_ever_project(self):
        logs = self._run("brand_new_project")
        self.assertFalse(any("Neues Projekt" in line for line in logs))

    def test_no_warning_when_continuing_an_existing_project(self):
        (self.orchestrator._workspace.base_dir / "already_here").mkdir()
        logs = self._run("already_here")
        self.assertFalse(any("Neues Projekt" in line for line in logs))

    def test_second_run_in_same_session_names_the_previous_project_slug(self):
        """
        Realer Fund aus einem echten Lauf: eine beim Einfügen zerrissene Nutzereingabe kam als
        mehrere separate Prompts an, jeder ließ das Modell einen NEUEN project_slug für
        praktisch dieselbe Aufgabe erraten ("fastapi_task_websocket" dann "fastapi-task-mgmt")
        - INNERHALB derselben Sitzung/desselben Orchestrator-Objekts. Die generische
        "Bereits vorhanden: ..."-Liste allein macht das eigene Vorprojekt DIESER Sitzung nicht
        besonders kenntlich. Ein zweiter process()-Aufruf auf demselben Orchestrator muss jetzt
        explizit auf self.last_project_slug (vom ERSTEN Aufruf) hinweisen.
        """
        self._run("erstes_projekt")
        self.assertEqual(self.orchestrator.last_project_slug, "erstes_projekt")

        logs = self._run("zweites_projekt")
        self.assertTrue(
            any("erstes_projekt" in line and "DIESER Sitzung" in line for line in logs),
            f"Erwarteter Hinweis auf 'erstes_projekt' aus derselben Sitzung fehlt in: {logs}",
        )
        self.assertTrue(any("/load erstes_projekt" in line for line in logs))

    def test_warning_shows_failed_verification_status_of_existing_project(self):
        """
        Realer Fund (Retrospektive zu vier separaten Läufen an praktisch derselben Aufgabe -
        "fastapi-task-mgmt", "fastapi_task_websocket", "kanban_board", "kanban_task_manager"):
        die reine Namensliste allein macht nicht sichtbar, dass ein bereits vorhandenes Projekt
        beim letzten Lauf gar nicht verifiziert werden konnte - ein weiterer, komplett neuer
        Versuch wirkt dadurch günstiger, als er ist. Der Hinweis muss jetzt zusätzlich den
        zuletzt protokollierten Status (core/project_status.record_run()) jedes vorhandenen
        Projekts anzeigen.
        """
        existing_dir = self.orchestrator._workspace.base_dir / "kanban_board"
        existing_dir.mkdir()
        record_run(
            project_dir=str(existing_dir),
            task_summary="Kanban-Board implementiert",
            verification_ok=False,
            budget_aborted=False,
            files_written_count=12,
        )

        logs = self._run("kanban_task_manager")
        self.assertTrue(
            any("kanban_board ⚠️" in line for line in logs),
            f"Erwartetes Status-Symbol für den fehlgeschlagenen letzten Lauf von "
            f"'kanban_board' fehlt in: {logs}",
        )

    def test_no_same_session_hint_when_reusing_the_same_slug(self):
        """Wird im zweiten Lauf wieder derselbe Slug geraten (echte Fortsetzung), ist der
        Zusatzhinweis überflüssig - project_slug == last_project_slug, keine Verwirrung möglich."""
        self._run("mein_projekt")
        logs = self._run("mein_projekt")
        self.assertFalse(any("DIESER Sitzung" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
