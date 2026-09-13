"""
tests/test_governance_resilience.py – Fehleranalyse 2026-09-13: unbehandelte TypeErrors im
Governance-Fix-Loop (agents/orchestrator/verification.py).

Zwei reale Absturzklassen werden hier gezielt simuliert:
1. `still_critical` (der finale Re-Review nach dem letzten Fix-Versuch) enthält nicht-string-
   fache Einträge - `finding_from_critical_block()` erwartet zwingend `block: str` und würde ohne
   die `isinstance`-Absicherung in `_run_governance_fix_loop_impl()` mit einem TypeError
   abstürzen.
2. Ein völlig unerwarteter Fehler tritt IRGENDWO in der Governance-Schleife auf (hier: eine
   gepatchte `_run_governance_fix_loop_impl()`, die absichtlich eine Exception wirft) - die
   robuste Außenhülle `_run_governance_fix_loop()` muss das abfangen und trotzdem IMMER das
   erwartete Tupel `(all_results, summary, budget_aborted, manually_cancelled)` liefern, statt die
   Exception bis zu `process()` durchzureichen.

Beide Fälle dürfen den Lauf NICHT zum Absturz bringen - genau das beweisen die Tests unten.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core import team_memory
from core.llm_factory import LLMResponse
from core.message_bus import AgentResult
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


class TestGovernanceLoopResilience(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)
        for agent in list(self.orchestrator._agents.values()) + list(self.orchestrator._dept_leads.values()):
            agent._llm = _FakeToolCapableLLM()
        # record_lesson() schreibt sonst in die ECHTE, repo-weite memory/team_lessons.jsonl -
        # hier auf eine Wegwerfdatei umgeleitet (dasselbe Muster wie test_governance_fix_loop.py).
        self._team_memory_patch = patch.object(
            team_memory, "TEAM_MEMORY_FILE", Path(self.temp_workspace) / "team_lessons.jsonl",
        )
        self._team_memory_patch.start()

    def tearDown(self):
        self._team_memory_patch.stop()
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def test_malformed_still_critical_entries_do_not_crash(self):
        """Der verpflichtende Re-Review nach dem letzten Fix-Versuch liefert `still_critical`
        mit nicht-string-fachen Einträgen (z.B. ein Exception-Objekt statt eines Freitext-Blocks) -
        `_run_governance_fix_loop()` darf dabei NIE mit einem TypeError abstürzen und muss trotzdem
        ein valides Tupel zurückgeben."""
        code_reviewer_result = AgentResult(
            task_id="t2", agent_id="code_reviewer", agent_name="Code-Reviewer", success=True,
            content="## Code-Review Report\n\n### 🔴 Kritische Probleme (müssen behoben werden)\nSQL-Injection.\n",
        )

        call_count = {"n": 0}

        def _fake_find_critical_findings(content: str):
            # Erster Aufruf (Fund-Ermittlung vor dem Fix-Dispatch): normaler String-Fund, damit
            # die Schleife überhaupt einen Fix dispatcht. JEDER weitere Aufruf (verpflichtender
            # Re-Review nach dem letzten Fix-Versuch, ggf. Eskalations-Rechecks) liefert
            # absichtlich fehlerhafte, nicht-string-fache Einträge - genau das reale Fehlerbild
            # aus der Analyse (`still_critical` darf so etwas laut Spezifikation nie enthalten,
            # ein zukünftiger Bug an anderer Stelle könnte es aber doch).
            call_count["n"] += 1
            if call_count["n"] == 1:
                return ["SQL-Injection in `backend/db.py`"]
            return [RuntimeError("kaputter, nicht-string-facher Fund"), 42, {"unexpected": "dict"}]

        async def _fake_run_agents_parallel(tasks, notify=None):
            return [
                AgentResult(task_id=t.task_id, agent_id=t.agent_id, agent_name=t.agent_id,
                            success=True, content="Fertig.", total_tokens=10)
                for t in tasks
            ]

        with patch("agents.orchestrator.verification.MAX_REVIEW_ITERATIONS", 1), \
             patch("agents.orchestrator.verification.find_critical_findings", side_effect=_fake_find_critical_findings), \
             patch.object(self.orchestrator, "_run_agents_parallel", side_effect=_fake_run_agents_parallel):
            try:
                results, summary, budget_aborted, cancelled = asyncio.run(
                    self.orchestrator._run_governance_fix_loop(
                        project_dir=self.temp_workspace,
                        all_results=[code_reviewer_result],
                        file_owners={"backend/db.py": "backend"},
                        notify=lambda msg: None,
                        run_start_tokens=0,
                    )
                )
            except TypeError as e:  # pragma: no cover - genau das darf NICHT passieren
                self.fail(f"_run_governance_fix_loop() ließ einen TypeError durchschlagen: {e}")

        self.assertIsInstance(results, list)
        self.assertIsInstance(summary, str)
        self.assertIsInstance(budget_aborted, bool)
        self.assertIsInstance(cancelled, bool)
        # Der Befund landet trotz kaputter Typen als Text im Backlog-Ticket/Lernprotokoll, statt
        # mit einem TypeError abzubrechen.
        self.assertIn("Backlog-Ticket eröffnet", summary)

    def test_unexpected_exception_in_loop_is_caught_by_outer_wrapper(self):
        """Ein völlig unerwarteter Fehler irgendwo in der (internen) Governance-Fix-Logik darf
        NIE bis zu process() durchschlagen - die robuste Außenhülle `_run_governance_fix_loop()`
        fängt ihn ab und liefert den unveränderten `all_results`-Stand plus ein leeres Protokoll
        zurück, statt den Lauf abstürzen zu lassen."""
        original_results = [
            AgentResult(task_id="t1", agent_id="backend", agent_name="Backend", success=True, content="ok"),
        ]

        async def _boom(*args, **kwargs):
            raise ValueError("Simulierter unerwarteter Fehler in der Governance-Schleife")

        with patch.object(self.orchestrator, "_run_governance_fix_loop_impl", side_effect=_boom):
            try:
                results, summary, budget_aborted, cancelled = asyncio.run(
                    self.orchestrator._run_governance_fix_loop(
                        project_dir=self.temp_workspace,
                        all_results=original_results,
                        file_owners={},
                        notify=lambda msg: None,
                        run_start_tokens=0,
                    )
                )
            except Exception as e:  # pragma: no cover - genau das darf NICHT passieren
                self.fail(f"_run_governance_fix_loop() ließ eine Exception durchschlagen: {e}")

        self.assertIs(results, original_results)
        self.assertEqual(summary, "")
        self.assertFalse(budget_aborted)
        self.assertFalse(cancelled)

    def test_permission_blocked_fix_wrapper_catches_unexpected_exception(self):
        """Dieselbe Absicherung wie oben, für die Schwester-Schleife
        `_run_permission_blocked_clarification_fix()` (Klärungs-Loop bei schreibgeschützt
        blockierten Rückfragen)."""
        original_results = [
            AgentResult(task_id="t1", agent_id="backend", agent_name="Backend", success=True, content="ok"),
        ]

        async def _boom(*args, **kwargs):
            raise KeyError("Simulierter unerwarteter Fehler im Klärungs-Loop")

        with patch.object(
            self.orchestrator, "_run_permission_blocked_clarification_fix_impl", side_effect=_boom,
        ):
            try:
                results, summary, budget_aborted, cancelled = asyncio.run(
                    self.orchestrator._run_permission_blocked_clarification_fix(
                        project_dir=self.temp_workspace,
                        all_results=original_results,
                        file_owners={},
                        notify=lambda msg: None,
                        run_start_tokens=0,
                    )
                )
            except Exception as e:  # pragma: no cover - genau das darf NICHT passieren
                self.fail(f"_run_permission_blocked_clarification_fix() ließ eine Exception durchschlagen: {e}")

        self.assertIs(results, original_results)
        self.assertEqual(summary, "")
        self.assertFalse(budget_aborted)
        self.assertFalse(cancelled)


if __name__ == "__main__":
    unittest.main()
