"""
tests/test_scope_clarification_autofix.py – Testet
agents/orchestrator/verification.py._run_scope_clarification_autofix()

Realer Fund (incidentpilot-Projekt, .ai_team_status.json): der tester-Agent stellte eine echte
fachliche Scope-Rückfrage ("Soll ich die Grundstruktur ... von Grund auf neu erstellen, da ich
kein 'app/'-Verzeichnis sehe?") statt sie autonom zu beantworten. Anders als eine Schreibrechte-
Rückfrage (siehe tests/test_permission_blocked_clarification_fix.py) passt hier KEIN Muster von
find_permission_blocked_questions() - die Frage blieb unbeantwortet stehen und der Lauf endete,
ohne dass die eigentliche Kernfunktion je gebaut wurde, obwohl Architektur/ADRs/OpenAPI-Spec
bereits vollständig vorlagen. Genau das behebt _run_scope_clarification_autofix(): kein Mensch
ist anwesend, um die Rückfrage zu beantworten, also entscheidet der fragende Agent autonom mit
der naheliegendsten Annahme.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agents.orchestrator.budget as orch_budget_module
from agents.orchestrator import Orchestrator
from core import team_memory
from core.message_bus import AgentResult
from core.token_guard import TokenGuard
from core.workspace import WorkspaceManager

SCOPE_QUESTION = (
    "Soll ich die Grundstruktur der Anwendung (Backend mit FastAPI, Frontend mit Vite) "
    "inklusive der Test-Infrastruktur von Grund auf neu erstellen? Das Projektverzeichnis ist "
    "aktuell leer von Applikationscode (kein 'app/' Verzeichnis)."
)

PERMISSION_BLOCKED_QUESTION = (
    "Wie erhalte ich Schreibrechte, um die identifizierten kritischen Sicherheitslücken zu "
    "beheben? Ich habe keine Schreibrechte."
)

GENUINE_BUSINESS_QUESTION = (
    "Welche Zahlungsanbieter sollen unterstützt werden?"
)


class _FakeToolCapableLLM:
    def __init__(self, text: str = "Fertig."):
        self._text = text
        self.model_name = "fake-model"

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        from core.llm_factory import LLMResponse
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[])

    async def generate_with_usage(self, prompt, system_prompt=None):
        from core.llm_factory import LLMResponse
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15)


class TestScopeClarificationAutofix(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()
        self._team_memory_patch = patch.object(team_memory, "TEAM_MEMORY_FILE", Path(self.temp_workspace) / "team_lessons.jsonl")
        self._team_memory_patch.start()

    def tearDown(self):
        self._team_memory_patch.stop()
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def test_scope_question_dispatched_back_to_raising_agent(self):
        tester_result = AgentResult(
            task_id="t1", agent_id="tester", agent_name="QA-Tester", success=True,
            content="Testlauf geprüft.",
            needs_human_input=True, clarification_questions=[SCOPE_QUESTION],
        )

        results, summary, budget_aborted, cancelled = asyncio.run(
            self.orchestrator._run_scope_clarification_autofix(
                project_dir=self.temp_workspace,
                all_results=[tester_result],
                file_owners={},
                notify=lambda msg: None,
            )
        )

        self.assertFalse(budget_aborted)
        self.assertFalse(cancelled)
        self.assertIn("Auto-Entscheid-Protokoll", summary)
        self.assertIn("tester", summary)
        # Die autonom beantwortete Rückfrage darf nicht mehr als unbeantwortet offen stehen.
        self.assertEqual(tester_result.clarification_questions, [])
        self.assertTrue(any(r.agent_id == "tester" for r in results))

    def test_permission_blocked_question_left_to_the_other_fix_loop(self):
        # _run_scope_clarification_autofix() darf reine Schreibrechte-Fragen NICHT selbst
        # aufgreifen - dafür existiert bereits _run_permission_blocked_clarification_fix()
        # (läuft in agents/orchestrator/__init__.py VOR dieser Funktion).
        security_result = AgentResult(
            task_id="t2", agent_id="security", agent_name="Security", success=True,
            content="Sicherheitsreview durchgeführt.",
            needs_human_input=True, clarification_questions=[PERMISSION_BLOCKED_QUESTION],
        )

        results, summary, budget_aborted, cancelled = asyncio.run(
            self.orchestrator._run_scope_clarification_autofix(
                project_dir=self.temp_workspace,
                all_results=[security_result],
                file_owners={},
                notify=lambda msg: None,
            )
        )

        self.assertEqual(summary, "")
        self.assertEqual(security_result.clarification_questions, [PERMISSION_BLOCKED_QUESTION])

    def test_genuine_business_question_is_left_untouched(self):
        # Muss unangetastet bleiben - eine echte fachliche Unklarheit gehört zur bewussten
        # Mid-Task-Eskalation an einen Menschen (siehe tests/test_clarification_escalation.py),
        # nicht in diese enge Allowlist für reine Struktur-/Scope-Fragen.
        pm_result = AgentResult(
            task_id="t3", agent_id="product_owner", agent_name="Product Owner", success=True,
            content="Anforderungen geprüft.",
            needs_human_input=True, clarification_questions=[GENUINE_BUSINESS_QUESTION],
        )

        results, summary, budget_aborted, cancelled = asyncio.run(
            self.orchestrator._run_scope_clarification_autofix(
                project_dir=self.temp_workspace,
                all_results=[pm_result],
                file_owners={},
                notify=lambda msg: None,
            )
        )

        self.assertEqual(summary, "")
        self.assertEqual(pm_result.clarification_questions, [GENUINE_BUSINESS_QUESTION])

    def test_no_open_questions_is_a_noop(self):
        tester_result = AgentResult(
            task_id="t1", agent_id="tester", agent_name="QA-Tester", success=True,
            content="Alles erledigt.",
        )

        results, summary, budget_aborted, cancelled = asyncio.run(
            self.orchestrator._run_scope_clarification_autofix(
                project_dir=self.temp_workspace,
                all_results=[tester_result],
                file_owners={},
                notify=lambda msg: None,
            )
        )

        self.assertEqual(summary, "")
        self.assertEqual(results, [tester_result])

    def test_budget_exceeded_skips_dispatch(self):
        fresh_guard = TokenGuard()
        fresh_guard.record_usage("fake-model", 5, 0)
        tester_result = AgentResult(
            task_id="t1", agent_id="tester", agent_name="QA-Tester", success=True,
            content="Testlauf geprüft.",
            needs_human_input=True, clarification_questions=[SCOPE_QUESTION],
        )

        with patch.object(orch_budget_module, "token_guard", fresh_guard), \
             patch.object(orch_budget_module, "MAX_RUN_TOKENS", 1):
            results, summary, budget_aborted, cancelled = asyncio.run(
                self.orchestrator._run_scope_clarification_autofix(
                    project_dir=self.temp_workspace,
                    all_results=[tester_result],
                    file_owners={},
                    notify=lambda msg: None,
                    run_start_tokens=0,
                )
            )

        self.assertTrue(budget_aborted)
        self.assertFalse(cancelled)
        self.assertEqual(summary, "")
        self.assertEqual(tester_result.clarification_questions, [SCOPE_QUESTION])


if __name__ == "__main__":
    unittest.main()
