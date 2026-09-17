"""
tests/test_task_complexity_scaling.py – Testet die Team-Komplexitäts-Skalierung

Realer Fund aus einem echten End-to-End-Testlauf: eine triviale Ein-Endpunkt-Aufgabe
(1 Datei Code + 1 Testdatei) verbrauchte 66.000 Tokens, weil jeder der 3 beteiligten
Fachbereiche (dev/qa/governance) trotz jeweils nur EINES einzigen Mitglieds die volle
Teamleiter-Delegation+Konsolidierung durchlief - der Lauf diagnostizierte sich in seiner
eigenen Retrospektive selbst als "Token-Inflation"/"Over-Engineering". Siehe
ENABLE_TASK_COMPLEXITY_SCALING in config.py für die vollständige Begründung.
"""

import asyncio
import unittest
from unittest.mock import patch

import config
from agents.orchestrator import Orchestrator
from core.message_bus import AgentTask
from core.model_capability import complex_run, current_run_is_complex
from core.task_manager import is_complex_task, is_micro_task


class TestIsMicroTask(unittest.TestCase):
    def test_single_backend_task_alone_is_micro(self):
        tasks = [AgentTask(task_id="t1", agent_id="backend", description="x")]
        self.assertTrue(is_micro_task(tasks))

    def test_backend_tester_code_reviewer_is_still_micro(self):
        """Genau der real beobachtete Plan aus dem Trial, der die Token-Inflation auslöste."""
        tasks = [
            AgentTask(task_id="t1", agent_id="backend", description="x"),
            AgentTask(task_id="t2", agent_id="tester", description="x"),
            AgentTask(task_id="t3", agent_id="code_reviewer", description="x"),
        ]
        self.assertTrue(is_micro_task(tasks))

    def test_architect_present_is_not_micro(self):
        tasks = [
            AgentTask(task_id="t1", agent_id="architect", description="x"),
            AgentTask(task_id="t2", agent_id="backend", description="x"),
        ]
        self.assertFalse(is_micro_task(tasks))

    def test_security_present_is_not_micro(self):
        tasks = [
            AgentTask(task_id="t1", agent_id="backend", description="x"),
            AgentTask(task_id="t2", agent_id="security", description="x"),
        ]
        self.assertFalse(is_micro_task(tasks))

    def test_too_many_agents_is_not_micro_even_without_signal_agents(self):
        tasks = [
            AgentTask(task_id=str(i), agent_id=aid, description="x")
            for i, aid in enumerate(["backend", "database", "tester", "code_reviewer", "readme"])
        ]
        self.assertFalse(is_micro_task(tasks))

    def test_empty_plan_is_micro(self):
        self.assertTrue(is_micro_task([]))


class TestIsComplexTask(unittest.TestCase):
    """Symmetrisches Gegenstück zu TestIsMicroTask: das ANDERE Ende der Skala."""

    def test_single_signal_agent_alone_is_not_complex(self):
        """Ein einziges Komplexitäts-Signal reicht für 'nicht trivial' (is_micro_task), aber
        noch nicht für 'anspruchsvoll genug, um eine Modell-Abstufung zu verhindern'."""
        tasks = [
            AgentTask(task_id="t1", agent_id="security", description="x"),
            AgentTask(task_id="t2", agent_id="backend", description="x"),
        ]
        self.assertFalse(is_complex_task(tasks))

    def test_two_signal_agents_are_complex(self):
        tasks = [
            AgentTask(task_id="t1", agent_id="architect", description="x"),
            AgentTask(task_id="t2", agent_id="security", description="x"),
            AgentTask(task_id="t3", agent_id="backend", description="x"),
        ]
        self.assertTrue(is_complex_task(tasks))

    def test_wide_plan_without_signal_agents_is_complex(self):
        tasks = [
            AgentTask(task_id=str(i), agent_id=aid, description="x")
            for i, aid in enumerate([
                "backend", "database", "tester", "code_reviewer", "readme",
                "frontend", "api_integration", "devops",
            ])
        ]
        self.assertTrue(is_complex_task(tasks))

    def test_small_plan_is_not_complex(self):
        tasks = [AgentTask(task_id="t1", agent_id="backend", description="x")]
        self.assertFalse(is_complex_task(tasks))

    def test_empty_plan_is_not_complex(self):
        self.assertFalse(is_complex_task([]))


class TestComplexRunBlocksAutoTuneDowngrade(unittest.TestCase):
    """core/model_capability.complex_run() + config.get_model_for_agent(): eine vom
    Selbstoptimierer vorgeschlagene Abstufung darf während eines anspruchsvollen Laufs nicht
    stillschweigend greifen - siehe CHANGELOG "Token-Analyse 2026-09-17"."""

    def test_downgrade_suppressed_during_complex_run(self):
        fake_entry = {"model": "gemini-3.1-flash-lite", "manual": True}
        with patch("config._read_auto_tuned_entry", return_value=fake_entry), \
                patch("config.AGENT_MODELS", {"tester": "gemini-3.8-flash"}):
            with complex_run(True):
                self.assertEqual(config.get_model_for_agent("tester"), "gemini-3.8-flash")
            with complex_run(False):
                self.assertEqual(config.get_model_for_agent("tester"), "gemini-3.1-flash-lite")

    def test_upgrade_still_applies_during_complex_run(self):
        """Eine Aufwertung (z.B. durch einen bestandenen A/B-Test) ist kein Risiko und bleibt
        deshalb auch während eines anspruchsvollen Laufs erlaubt."""
        fake_entry = {"model": "gemini-pro-latest", "ab_promoted": True}
        with patch("config._read_auto_tuned_entry", return_value=fake_entry), \
                patch("config.AGENT_MODELS", {"tester": "gemini-3.8-flash"}), \
                complex_run(True):
            self.assertEqual(config.get_model_for_agent("tester"), "gemini-pro-latest")

    def test_flag_disabled_keeps_downgrade_even_during_complex_run(self):
        fake_entry = {"model": "gemini-3.1-flash-lite", "manual": True}
        with patch("config._read_auto_tuned_entry", return_value=fake_entry), \
                patch("config.AGENT_MODELS", {"tester": "gemini-3.8-flash"}), \
                patch("config.ENABLE_TASK_COMPLEXITY_SCALING", False), \
                complex_run(True):
            self.assertEqual(config.get_model_for_agent("tester"), "gemini-3.1-flash-lite")


class _RecordingFakeLLM:
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


class TestOrchestratorSkipsLeadLayerForMicroTasks(unittest.TestCase):
    def setUp(self):
        self.orchestrator = Orchestrator()
        for agent_id, agent in self.orchestrator._agents.items():
            agent._llm = _RecordingFakeLLM(agent_id)
        self.lead_llms: dict[str, _RecordingFakeLLM] = {}
        for dept_id, lead in self.orchestrator._dept_leads.items():
            fake = _RecordingFakeLLM(dept_id)
            lead._llm = fake
            self.lead_llms[dept_id] = fake

    def test_single_member_departments_skip_delegation_and_consolidation_for_micro_task(self):
        """Der real beobachtete Fall: backend (dev_lead) und tester (qa_lead) sind jeweils
        EINZIGES Mitglied ihres Fachbereichs bei einer insgesamt kleinen Aufgabe - beide
        Teamleiter dürfen NICHT per LLM-Aufruf delegieren/konsolidieren."""
        agent_tasks = [
            AgentTask(task_id="t1", agent_id="backend", description="Endpunkt bauen"),
            AgentTask(task_id="t2", agent_id="tester", description="Test schreiben"),
        ]
        results, _file_owners, budget_aborted, _cancelled = asyncio.run(self.orchestrator._run_department_hierarchy(
            user_request="Baue einen Ping-Endpunkt",
            task_summary="Ping-Endpunkt implementiert",
            agent_tasks=agent_tasks,
            project_dir=".",
            notify=lambda msg: None,
        ))
        self.assertFalse(budget_aborted)

        result_agent_ids = [r.agent_id for r in results]
        self.assertNotIn("dev_lead", result_agent_ids)
        self.assertNotIn("qa_lead", result_agent_ids)
        self.assertIn("backend", result_agent_ids)
        self.assertIn("tester", result_agent_ids)
        self.assertEqual(len(self.lead_llms["dev_lead"].calls), 0)
        self.assertEqual(len(self.lead_llms["qa_lead"].calls), 0)

    def test_multi_member_department_keeps_lead_layer_even_for_micro_task(self):
        """Fachbereiche mit MEHREREN Mitgliedern behalten die Teamleiter-Koordination immer -
        dort besteht echter Abstimmungsbedarf (z.B. doppelte Parallel-Implementierungen
        vermeiden), unabhängig von der Gesamtkomplexität."""
        agent_tasks = [
            AgentTask(task_id="t1", agent_id="backend", description="API"),
            AgentTask(task_id="t2", agent_id="database", description="Schema"),
        ]
        results, _file_owners, _budget_aborted, _cancelled = asyncio.run(self.orchestrator._run_department_hierarchy(
            user_request="Baue eine kleine API mit DB",
            task_summary="API mit DB implementiert",
            agent_tasks=agent_tasks,
            project_dir=".",
            notify=lambda msg: None,
        ))
        result_agent_ids = [r.agent_id for r in results]
        self.assertEqual(result_agent_ids.count("dev_lead"), 2)  # Delegation + Konsolidierung
        # Konsolidierung ist seit 2026-09-15 standardmäßig deterministisch (kein LLM-Aufruf).
        self.assertEqual(len(self.lead_llms["dev_lead"].calls), 1)

    def test_hierarchy_marks_complex_run_for_nested_agent_calls(self):
        """_run_department_hierarchy() muss core.model_capability.complex_run() für die
        gesamte Dauer eines als anspruchsvoll erkannten Laufs aktivieren - inklusive der
        Sicht der einzelnen Agenten-Aufrufe, die verschachtelt darin laufen - und danach
        wieder zurücksetzen. Nutzt den bereits anderswo abgedeckten Single-Member-Pfad
        (backend/tester) als Trägeraufgabe, is_complex_task() wird direkt erzwungen."""
        seen_during_run: list[bool] = []
        backend_llm = self.orchestrator._agents["backend"]._llm
        original_generate = backend_llm.generate_with_usage

        async def _recording_generate(*args, **kwargs):
            seen_during_run.append(current_run_is_complex())
            return await original_generate(*args, **kwargs)

        backend_llm.generate_with_usage = _recording_generate

        agent_tasks = [
            AgentTask(task_id="t1", agent_id="backend", description="Endpunkt bauen"),
            AgentTask(task_id="t2", agent_id="tester", description="Test schreiben"),
        ]
        self.assertFalse(current_run_is_complex())
        with patch("agents.orchestrator.department.is_complex_task", return_value=True):
            asyncio.run(self.orchestrator._run_department_hierarchy(
                user_request="Baue ein anspruchsvolles System",
                task_summary="System implementiert",
                agent_tasks=agent_tasks,
                project_dir=".",
                notify=lambda msg: None,
            ))
        self.assertFalse(current_run_is_complex())
        self.assertTrue(seen_during_run)
        self.assertTrue(all(seen_during_run))

    def test_flag_disabled_keeps_old_behavior_for_single_member_department(self):
        """Regressionsschutz: ENABLE_TASK_COMPLEXITY_SCALING=False muss exakt das alte
        Verhalten (immer volle Delegation+Konsolidierung) wiederherstellen."""
        agent_tasks = [AgentTask(task_id="t1", agent_id="backend", description="Endpunkt bauen")]
        with patch("agents.orchestrator.department.ENABLE_TASK_COMPLEXITY_SCALING", False), \
                patch("agents.orchestrator.department.DEPARTMENT_LEAD_MIN_MEMBERS", 1):
            results, _fo, _ba, _c = asyncio.run(self.orchestrator._run_department_hierarchy(
                user_request="Baue einen Ping-Endpunkt",
                task_summary="Ping-Endpunkt implementiert",
                agent_tasks=agent_tasks,
                project_dir=".",
                notify=lambda msg: None,
            ))
        result_agent_ids = [r.agent_id for r in results]
        self.assertEqual(result_agent_ids.count("dev_lead"), 2)


if __name__ == "__main__":
    unittest.main()
