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

import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.message_bus import AgentTask
from core.verifier import VerificationReport
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
        self.orchestrator = Orchestrator()
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM("Kurze Erledigung.")

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

    def test_last_task_summary_is_real_summary_not_raw_input(self):
        import asyncio
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


if __name__ == "__main__":
    unittest.main()
