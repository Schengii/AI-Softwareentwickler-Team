"""
tests/test_department_lead_activation.py – Testet die ECHTE Teamleiter-Aktivierung

Vor diesem Umbau delegierten/konsolidierten die 5 Fachbereichs-Teamleiter nie
wirklich – der Orchestrator rief nur die Fachagenten direkt auf und gab dazu
vorgetäuschte notify()-Texte aus ("Teamleiter X hat Y abgenommen"), ohne dass
der Lead je einen LLM-Aufruf gemacht hätte. Dieser Test stellt sicher, dass
_run_department_delegation/_run_department_consolidation den Lead wirklich
per LLM-Call ausführen und deren echte Ergebnisse im Gesamtergebnis landen.
"""

import asyncio
import unittest

from agents.orchestrator import Orchestrator
from core.message_bus import AgentTask


class _RecordingFakeLLM:
    """Zeichnet auf, wie oft/mit welchem Prompt sie aufgerufen wurde, und liefert festen Text."""

    def __init__(self, label: str):
        self.label = label
        self.model_name = "fake-model"
        self.calls: list[str] = []

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        from core.llm_factory import LLMResponse
        self.calls.append(messages[-1].text if messages else "")
        return LLMResponse(
            text=f"[{self.label}] verarbeitet.", model_name=self.model_name,
            prompt_tokens=10, completion_tokens=10, total_tokens=20, tool_calls=[],
        )

    async def generate_with_usage(self, prompt, system_prompt=None):
        from core.llm_factory import LLMResponse
        self.calls.append(prompt)
        return LLMResponse(text=f"[{self.label}] verarbeitet.", model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=10, total_tokens=20)


class TestDepartmentLeadActivation(unittest.TestCase):
    def setUp(self):
        self.orchestrator = Orchestrator()
        for agent_id, agent in self.orchestrator._agents.items():
            agent._llm = _RecordingFakeLLM(agent_id)
        self.lead_llms: dict[str, _RecordingFakeLLM] = {}
        for dept_id, lead in self.orchestrator._dept_leads.items():
            fake = _RecordingFakeLLM(dept_id)
            lead._llm = fake
            self.lead_llms[dept_id] = fake

    def test_planning_lead_is_really_called_for_delegation_and_consolidation(self):
        task_map = {
            "product_owner": AgentTask(task_id="t1", agent_id="product_owner", description="Scope definieren", project_dir="."),
        }
        lead = self.orchestrator._dept_leads["planning_lead"]

        delegation = asyncio.run(self.orchestrator._run_department_delegation(
            lead, "Baue eine Todo-App", list(task_map.values()), "."
        ))
        self.assertTrue(delegation.success)
        self.assertEqual(delegation.content, "[planning_lead] verarbeitet.")
        self.assertEqual(len(self.lead_llms["planning_lead"].calls), 1)

        from core.message_bus import AgentResult
        member_results = [AgentResult(
            task_id="t1", agent_id="product_owner", agent_name="Product Owner",
            success=True, content="MVP-Scope definiert.",
        )]
        consolidation = asyncio.run(self.orchestrator._run_department_consolidation(lead, member_results, "."))
        self.assertTrue(consolidation.success)
        self.assertEqual(consolidation.content, "[planning_lead] verarbeitet.")

        # Der Lead wurde für BEIDE Schritte wirklich mit einem eigenen LLM-Aufruf aktiviert –
        # nicht nur mit einer vorgetäuschten Statusmeldung.
        self.assertEqual(len(self.lead_llms["planning_lead"].calls), 2)

    def test_full_hierarchy_includes_real_lead_results_not_fake_notify_only(self):
        agent_tasks = [
            AgentTask(task_id="t1", agent_id="product_owner", description="Scope"),
            AgentTask(task_id="t2", agent_id="backend", description="API"),
        ]
        results, file_owners, budget_aborted, _cancelled = asyncio.run(self.orchestrator._run_department_hierarchy(
            user_request="Baue eine Todo-App",
            task_summary="Todo-App mit Backend",
            agent_tasks=agent_tasks,
            project_dir=".",
            notify=lambda msg: None,
        ))
        self.assertFalse(budget_aborted)  # kein MAX_RUN_TOKENS in diesem Test konfiguriert

        result_agent_ids = [r.agent_id for r in results]
        # planning_lead und dev_lead müssen als ECHTE Teilnehmer mit eigenem Ergebnis auftauchen
        # (Delegation + Konsolidierung), nicht nur product_owner/backend selbst.
        self.assertIn("planning_lead", result_agent_ids)
        self.assertIn("dev_lead", result_agent_ids)
        self.assertEqual(result_agent_ids.count("planning_lead"), 2)  # Delegation + Konsolidierung
        self.assertEqual(result_agent_ids.count("dev_lead"), 2)

        # Jeder Lead-Aufruf ist ein eigener, gezählter LLM-Call – kein Fake-Text.
        self.assertEqual(len(self.lead_llms["planning_lead"].calls), 2)
        self.assertEqual(len(self.lead_llms["dev_lead"].calls), 2)


if __name__ == "__main__":
    unittest.main()
