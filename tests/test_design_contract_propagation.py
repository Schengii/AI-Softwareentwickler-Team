"""
tests/test_design_contract_propagation.py – Testet, dass der konsolidierte design_lead-Bericht
JEDEN nachfolgenden Fachbereich unverkürzt erreicht (agents/orchestrator.py._run_department_hierarchy,
ENABLE_DESIGN_CONTRACT_PROPAGATION).

Realer Fund: running_context ist auf die letzten 3000 Zeichen gedeckelt - bei einem GUI-Projekt
ohne /design-system verdrängten die umfangreicheren dev_lead-Ergebnisse den design_lead-Bericht
bereits aus dem Kontext, BEVOR die QA-Phase ihn erreichte. frontend baute eine Komponente laut
Design-Entscheidung, tester (2 Phasen später) bekam diese Entscheidung nie zu Gesicht und schrieb
einen Test gegen eine andere, selbst angenommene Struktur - verification_ok wurde False.

Dieser Test erzwingt genau dieses Szenario (eine sehr umfangreiche dev_lead-Ausgabe zwischen
design_lead und qa_lead) und prüft, dass der design_lead-Bericht trotzdem im Kontext von tester
ankommt - einmal MIT aktiver Propagation (muss ankommen) und einmal mit deaktiviertem Flag
(darf nicht als eigener Block ankommen), um zu belegen, dass genau dieser Mechanismus wirkt und
nicht nur zufällig noch im rollierenden running_context-Fenster Platz war.
"""

import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask
from core.workspace import WorkspaceManager

DESIGN_MARKER = "🎨 Design-Kontrakt: Framework=React, Komponente=App, Copy='Portfolio hochladen'"


class _ScriptedLLM:
    def __init__(self, agent_id: str, text: str):
        self.agent_id = agent_id
        self.model_name = "fake-model"
        self.text = text
        self.received_contexts: list[str] = []

    async def generate_with_usage(self, prompt: str, system_prompt: str = "") -> LLMResponse:
        self.received_contexts.append(prompt)
        return LLMResponse(text=self.text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15)

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        prompt_text = messages[0].text if messages else ""
        self.received_contexts.append(prompt_text)
        return LLMResponse(text=self.text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[])


class TestDesignContractPropagation(unittest.TestCase):
    def setUp(self):
        self.temp_workspace = tempfile.mkdtemp()
        self.orchestrator = Orchestrator()
        self.orchestrator._workspace = WorkspaceManager(self.temp_workspace)

        # design_lead konsolidiert auf den Marker-Text (das ist der "Design-Kontrakt").
        self.orchestrator._dept_leads["design_lead"]._llm = _ScriptedLLM("design_lead", DESIGN_MARKER)
        self.orchestrator._agents["ui_ux"]._llm = _ScriptedLLM("ui_ux", "Design-Vorschlag.")

        # dev_lead-Ausgabe ist bewusst SEHR umfangreich (>3000 Zeichen), um das rollierende
        # running_context-Fenster zu füllen und ältere Phasen daraus zu verdrängen.
        bulk_text = "Umfangreiche Implementierungsdetails. " * 200
        self.orchestrator._dept_leads["dev_lead"]._llm = _ScriptedLLM("dev_lead", bulk_text)
        self.orchestrator._agents["frontend"]._llm = _ScriptedLLM("frontend", bulk_text)

        self.tester_llm = _ScriptedLLM("tester", "Test geschrieben.")
        self.orchestrator._dept_leads["qa_lead"]._llm = _ScriptedLLM("qa_lead", "QA-Bericht.")
        self.orchestrator._agents["tester"]._llm = self.tester_llm

    def tearDown(self):
        shutil.rmtree(self.temp_workspace, ignore_errors=True)

    def _run(self):
        agent_tasks = [
            AgentTask(task_id="t1", agent_id="ui_ux", description="Design entwerfen"),
            AgentTask(task_id="t2", agent_id="frontend", description="Komponente bauen"),
            AgentTask(task_id="t3", agent_id="tester", description="Test schreiben"),
        ]
        return asyncio.run(
            self.orchestrator._run_department_hierarchy(
                user_request="Baue ein GUI",
                task_summary="GUI-Aufgabe",
                agent_tasks=agent_tasks,
                project_dir=self.temp_workspace,
                notify=lambda msg: None,
            )
        )

    def test_design_contract_reaches_tester_despite_bulky_dev_phase(self):
        with patch("agents.orchestrator.ENABLE_TASK_COMPLEXITY_SCALING", False), \
             patch("agents.orchestrator.ENABLE_DESIGN_CONTRACT_PROPAGATION", True):
            self._run()

        self.assertTrue(
            any("Verbindlicher Design-Kontrakt" in ctx and DESIGN_MARKER in ctx for ctx in self.tester_llm.received_contexts),
            "tester sollte den design_lead-Bericht als eigenen, unverkürzten Kontext-Block erhalten.",
        )

    def test_without_flag_design_contract_block_is_absent(self):
        with patch("agents.orchestrator.ENABLE_TASK_COMPLEXITY_SCALING", False), \
             patch("agents.orchestrator.ENABLE_DESIGN_CONTRACT_PROPAGATION", False):
            self._run()

        self.assertFalse(
            any("Verbindlicher Design-Kontrakt" in ctx for ctx in self.tester_llm.received_contexts),
            "Ohne das Flag darf der dedizierte Design-Kontrakt-Block nicht injiziert werden.",
        )


if __name__ == "__main__":
    unittest.main()
