"""
tests/test_commit_message_summary.py – Testet die Commit-Message-Zusammenfassung für /push

Realer Fund aus einem echten Lauf: Die Commit-Message nutzte bisher die ROHE, oft
konversationelle Nutzereingabe (z.B. "Okay ich möchte, dass ihr das Projekt weiter
verbessert ...") statt der vom TaskManager erzeugten Kurzfassung, hart bei 50 Zeichen
mitten im Wort abgeschnitten. Ergebnis: Commit-Messages wie
"feat: implement Okay ich möchte das ihr das Projekt weiter Verbess via AI Developer Team".

Diese Tests stellen sicher, dass:
1. Orchestrator.process() die echte, kurze task_summary in last_task_summary ablegt
   (nicht die rohe user_request).
2. interface/cli.py._truncate_at_word() niemals mitten in einem Wort abschneidet.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import core.backlog_store as backlog_store
from agents.orchestrator import Orchestrator
from core.message_bus import AgentTask
from core.verifier import VerificationReport
from core.workspace import WorkspaceManager
from interface.cli import CLIInterface


class _FakeToolCapableLLM:
    def __init__(self, text: str, model_name: str = "gemini-2.5-flash"):
        self._text = text
        self.model_name = model_name

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        from core.llm_factory import LLMResponse
        return LLMResponse(
            text=self._text, model_name=self.model_name,
            prompt_tokens=50, completion_tokens=20, total_tokens=70, tool_calls=[],
        )

    async def generate_with_usage(self, prompt, system_prompt=None):
        from core.llm_factory import LLMResponse
        return LLMResponse(
            text=self._text, model_name=self.model_name,
            prompt_tokens=50, completion_tokens=20, total_tokens=70,
        )


class TestCommitMessageUsesRealSummary(unittest.TestCase):
    def setUp(self):
        # Bugfix (Code-Review-Fund): ohne isolierte WorkspaceManager-Instanz schrieb dieser Test
        # bei jedem Lauf über core/project_status.py.record_run() eine echte
        # .ai_team_status.json in den TATSÄCHLICHEN Framework-Workspace
        # (workspace/fastapi_health_check/ - der project_slug aus dem gemockten decompose()
        # unten) statt in eine temporäre Testumgebung, und legte diesen Projektordner dabei
        # sogar neu an. Gleiches Isolationsmuster wie test_coverage_integration.py/
        # test_runtime_smoke_integration.py.
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM("Kurze Erledigung.")

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    @patch("agents.orchestrator.ProjectVerifier")
    @patch("core.task_manager.TaskManager.decompose")
    @patch("core.result_aggregator.ResultAggregator.synthesize")
    async def _run(self, mock_synthesize, mock_decompose, mock_verifier_cls):
        mock_decompose.return_value = (
            "Health-Check-Endpoint für FastAPI implementiert",
            "fastapi_health_check",
            [AgentTask(task_id="t1", agent_id="backend", description="Health-Check bauen")],
        )
        mock_synthesize.return_value = ("### Fertig", 10)
        mock_verifier = mock_verifier_cls.return_value
        mock_verifier.ensure_environment.return_value = ""
        mock_verifier.run_tests.return_value = VerificationReport(
            ran=False, passed=True, exit_code=0, stdout="", stderr="", duration_seconds=0.0,
            reason_skipped="simuliert",
        )

        raw_user_message = "Okay ich möchte das ihr das Projekt weiter Verbessert und einen Health-Check baut"
        await self.orchestrator.process(raw_user_message)

        # last_task_summary muss die kurze, vom TaskManager erzeugte Zusammenfassung sein –
        # NICHT die rohe, konversationelle Nutzereingabe.
        self.assertEqual(self.orchestrator.last_task_summary, "Health-Check-Endpoint für FastAPI implementiert")
        self.assertNotIn("Okay ich möchte", self.orchestrator.last_task_summary)
        self.assertEqual(self.orchestrator.last_project_slug, "fastapi_health_check")

    def test_last_task_summary_is_real_summary_not_raw_input(self):
        asyncio.run(self._run())


class TestTruncateAtWord(unittest.TestCase):
    def test_never_cuts_mid_word(self):
        text = "Health-Check-Endpoint für FastAPI mit ausführlicher Dokumentation implementiert"
        truncated = CLIInterface._truncate_at_word(text, 50)
        self.assertLessEqual(len(truncated), 50)
        # Das letzte Zeichen muss das Ende eines der Original-Wörter sein, kein Bruchstück.
        self.assertIn(truncated.split()[-1], text.split())

    def test_short_text_is_returned_unchanged(self):
        self.assertEqual(CLIInterface._truncate_at_word("Kurzer Text", 50), "Kurzer Text")

    def test_flattens_newlines_and_extra_whitespace(self):
        self.assertEqual(
            CLIInterface._truncate_at_word("Zeile 1\n\nZeile   2", 50), "Zeile 1 Zeile 2"
        )


class TestRawRequestEchoFallback(unittest.TestCase):
    """
    Realer Fund (2. Vorkommen trotz vorherigem Fix): task_summary war erneut faktisch eine
    Kopie der rohen Nutzeranfrage ("Ich möchte das ihr ein neues Projekt erstellt. Es" als
    Commit-Betreff) – diesmal, weil das Modell den (bereits verschärften) Zusammenfassungs-
    Auftrag im DECOMPOSE_SYSTEM_PROMPT selbst nicht befolgt hat. Deterministische Absicherung
    ohne weiteren LLM-Aufruf: erkennbare Anrede-/Bitte-Formeln lösen einen Fallback auf den
    (immer kurzen) Projektordnernamen statt eines weiteren rohen [:50]-Schnitts aus.
    """

    def test_detects_common_raw_request_openers(self):
        for text in (
            "Ich möchte das ihr ein neues Projekt erstellt. Es soll...",
            "ich will einen Taschenrechner",
            "Könnt ihr bitte eine README schreiben",
            "Bitte baut mir eine API",
            "Okay, macht weiter",
        ):
            self.assertTrue(CLIInterface._looks_like_raw_user_request(text), text)

    def test_does_not_flag_real_summaries(self):
        for text in (
            "Health-Check-Endpoint für FastAPI implementiert",
            "Taschenrechner-GUI mit Core/GUI-Trennung erstellt",
            "README aktualisiert",
        ):
            self.assertFalse(CLIInterface._looks_like_raw_user_request(text), text)

    def test_commit_message_falls_back_to_project_slug_when_summary_looks_raw(self):
        cli = CLIInterface()
        fake_github = MagicMock()
        fake_github.get_status.return_value = "?? new_file.py"
        fake_github.get_diff.return_value = "new_file.py | 1 +"
        fake_github.commit.return_value = (True, "commit ok")
        fake_github.push.return_value = (True, "push ok")
        fake_github.get_current_branch.return_value = "main"
        fake_github.wait_for_ci_status = AsyncMock(return_value=("no_run", "kein CI im Test"))
        fake_github.scan_for_secrets.return_value = []
        # PR-Workflow ist hier nicht Testgegenstand (siehe tests/test_pr_workflow.py) - hält
        # den bisherigen Direct-Push-Pfad aktiv.
        fake_github.gh_ready.return_value = False
        cli._orchestrator._agents["github"] = fake_github
        cli._orchestrator.last_project_slug = "modular_calculator_gui"

        # _ask_for_git_push() schreibt jetzt auch ins Backlog (core/backlog_store.py) - gegen
        # ein temporäres Verzeichnis statt der echten memory/backlog.json.
        backlog_dir = tempfile.mkdtemp()
        with patch.object(backlog_store, "BACKLOG_FILE", Path(backlog_dir) / "backlog.json"):
            with patch("interface.cli.console.print"), patch("interface.cli.Confirm.ask", return_value=False):
                asyncio.run(cli._ask_for_git_push("Ich möchte das ihr ein neues Projekt erstellt. Es"))

            # Confirm.ask=False -> commit() wird nicht aufgerufen, aber die Vorschau-Message wurde
            # bereits gebaut und an console.print übergeben; wir prüfen sie über den nächsten echten
            # Aufruf mit Confirm.ask=True, um den tatsächlich verwendeten commit_msg zu erhalten.
            fake_github.reset_mock()
            with patch("interface.cli.console.print"), patch("interface.cli.Confirm.ask", return_value=True):
                asyncio.run(cli._ask_for_git_push("Ich möchte das ihr ein neues Projekt erstellt. Es"))

        fake_github.commit.assert_called_once()
        commit_msg = fake_github.commit.call_args[0][0]
        self.assertIn("modular_calculator_gui", commit_msg)
        self.assertNotIn("Ich möchte", commit_msg)


if __name__ == "__main__":
    unittest.main()
