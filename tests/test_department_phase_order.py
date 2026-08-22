"""
tests/test_department_phase_order.py – Testet die 6-Phasen-Hierarchie mit Design-vor-Dev

Prüft:
1. PHASE_ORDER definiert exakt 6 Fachbereiche in der Reihenfolge:
   planning_lead -> design_lead -> dev_lead -> content_lead -> qa_lead -> governance_lead
2. Vorab-Design (ui_ux, image_generator, copywriter) läuft VOR der Software-Entwicklung (dev_lead).
3. Entwickler (frontend, backend) erhalten die erzeugten Design-Vorgaben im Kontext und sehen
   vorab geschriebene Dateien/Assets im Projektverzeichnis.
4. Content & Dokumentation (accessibility, i18n, documentation, readme) laufen NACH der Entwicklung
   und können den tatsächlich erzeugten Code analysieren.
"""

import asyncio
import shutil
import tempfile
import unittest

from agents.department_lead_agent import DEPARTMENT_DEFINITIONS
from agents.orchestrator import PHASE_ORDER, Orchestrator
from core.llm_factory import LLMResponse, ToolCall
from core.message_bus import AgentTask


class _RecordingLLM:
    def __init__(self, agent_id: str, write_file: str | None = None, write_content: str = ""):
        self.agent_id = agent_id
        self.model_name = "fake-model"
        self.write_file = write_file
        self.write_content = write_content
        self.step = 0
        self.received_contexts: list[str] = []

    async def generate_with_usage(self, prompt: str, system_prompt: str = "") -> LLMResponse:
        self.step += 1
        self.received_contexts.append(prompt)
        return LLMResponse(
            text=f"Fertig von {self.agent_id}.",
            model_name=self.model_name,
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            tool_calls=[],
        )

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        self.step += 1
        prompt_text = messages[0].text if messages else ""
        self.received_contexts.append(prompt_text)

        if self.step == 1 and self.write_file:
            return LLMResponse(
                text="Schreibe Datei...",
                model_name=self.model_name,
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                tool_calls=[ToolCall(id="c1", name="write_file", arguments={
                    "path": self.write_file,
                    "content": self.write_content,
                })],
            )
        return LLMResponse(
            text=f"Fertig von {self.agent_id}.",
            model_name=self.model_name,
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            tool_calls=[],
        )


class TestDepartmentPhaseOrder(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        from core.workspace import WorkspaceManager
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def test_phase_order_structure(self):
        """Prüft die exakte Struktur und Reihenfolge von PHASE_ORDER."""
        expected_lead_ids = [
            "planning_lead",
            "design_lead",
            "dev_lead",
            "content_lead",
            "qa_lead",
            "governance_lead",
        ]
        actual_lead_ids = [p[0] for p in PHASE_ORDER]
        self.assertEqual(actual_lead_ids, expected_lead_ids)

        for lead_id in expected_lead_ids:
            self.assertIn(lead_id, DEPARTMENT_DEFINITIONS)
            self.assertIn(lead_id, self.orchestrator._dept_leads)

    def test_design_lead_members_and_content_lead_members_are_disjoint_and_complete(self):
        """Prüft, dass Vorab-Design und Post-Dev-Content sauber getrennt sind."""
        design_members = set(DEPARTMENT_DEFINITIONS["design_lead"]["members"])
        content_members = set(DEPARTMENT_DEFINITIONS["content_lead"]["members"])
        dev_members = set(DEPARTMENT_DEFINITIONS["dev_lead"]["members"])

        self.assertEqual(design_members, {"ui_ux", "image_generator", "copywriter"})
        self.assertEqual(content_members, {"accessibility", "i18n", "documentation", "readme"})
        self.assertTrue(design_members.isdisjoint(content_members))
        self.assertTrue(design_members.isdisjoint(dev_members))
        self.assertTrue(content_members.isdisjoint(dev_members))

    def test_execution_order_design_runs_before_dev_and_content_runs_after_dev(self):
        """
        Prüft den realen Ablauf:
        1. ui_ux (Phase 2: design_lead) generiert style.css
        2. frontend (Phase 3: dev_lead) sieht style.css im Workspace
        3. documentation (Phase 4: content_lead) sieht den erzeugten Code
        """
        ui_ux_llm = _RecordingLLM("ui_ux", write_file="style.css", write_content=":root { --primary: #0070f3; }\n")
        frontend_llm = _RecordingLLM("frontend", write_file="index.html", write_content="<link rel='stylesheet' href='style.css'>\n")
        doc_llm = _RecordingLLM("documentation", write_file="README.md", write_content="# Projekt Doku\n")

        self.orchestrator._agents["ui_ux"]._llm = ui_ux_llm
        self.orchestrator._agents["frontend"]._llm = frontend_llm
        self.orchestrator._agents["documentation"]._llm = doc_llm

        for lead in self.orchestrator._dept_leads.values():
            lead._llm = _RecordingLLM(lead.department_id)

        execution_log: list[str] = []

        async def track_agent(task):
            execution_log.append(task.agent_id)
            return await self.orchestrator._original_run_single_agent(task)

        self.orchestrator._original_run_single_agent = self.orchestrator._run_single_agent
        self.orchestrator._run_single_agent = track_agent

        agent_tasks = [
            AgentTask(task_id="t1", agent_id="ui_ux", description="Design System entwerfen"),
            AgentTask(task_id="t2", agent_id="frontend", description="HTML implementieren"),
            AgentTask(task_id="t3", agent_id="documentation", description="Doku erstellen"),
        ]

        results, file_owners, budget_aborted, cancelled = asyncio.run(
            self.orchestrator._run_department_hierarchy(
                user_request="Erstelle eine Landingpage",
                task_summary="Landingpage",
                agent_tasks=agent_tasks,
                project_dir=self.temp_workspace,
                notify=lambda msg: None,
            )
        )

        self.assertFalse(budget_aborted)
        self.assertFalse(cancelled)

        # Überprüfe die Reihenfolge im Ausführungsprotokoll:
        # ui_ux MUSS vor frontend gelaufen sein, und frontend MUSS vor documentation gelaufen sein.
        self.assertIn("ui_ux", execution_log)
        self.assertIn("frontend", execution_log)
        self.assertIn("documentation", execution_log)

        ui_ux_idx = execution_log.index("ui_ux")
        frontend_idx = execution_log.index("frontend")
        doc_idx = execution_log.index("documentation")

        self.assertLess(ui_ux_idx, frontend_idx, "ui_ux muss VOR frontend ausgeführt werden")
        self.assertLess(frontend_idx, doc_idx, "frontend muss VOR documentation ausgeführt werden")

        # Prüfe, dass Frontend die Design-Informationen im Kontext erhalten hat
        self.assertTrue(any("Kontext aus vorherigen Fachbereichen" in ctx or "Design" in ctx for ctx in frontend_llm.received_contexts))


if __name__ == "__main__":
    unittest.main()
