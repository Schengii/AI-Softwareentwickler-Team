"""
tests/test_file_write_collisions.py – Testet die Datei-Kollisionserkennung zwischen parallel
laufenden Fachteam-Mitgliedern (agents/orchestrator.py)

Realer struktureller Fund: bei 3+ Mitgliedern eines Fachbereichs laufen die Agenten echt
gleichzeitig per asyncio.gather (core/agent_toolbox.py._tool_write_file() überschreibt dabei
blind, kein Lock/Merge) - sehen sich dabei aber NIE gegenseitig (derselbe strukturelle Grund,
der bereits bei ≤2 Mitgliedern zur erzwungenen Sequenzialität führte, siehe
tests/test_small_department_sequential.py). Zwei Agenten, die dieselbe Datei schreiben,
verlieren die zuerst geschriebene Version bisher STILLSCHWEIGEND (nur _update_file_owners()
gewinnt intern, ohne jede Meldung). Diese Tests decken die Erkennung + Sichtbarmachung ab.
"""

import asyncio
import unittest
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.message_bus import AgentResult, AgentTask


def _result(agent_id: str, files_written: list[str]) -> AgentResult:
    return AgentResult(
        task_id=f"t-{agent_id}", agent_id=agent_id, agent_name=agent_id,
        success=True, content="ok", files_written=files_written,
    )


class TestDetectFileWriteCollisions(unittest.TestCase):
    def test_no_overlap_returns_empty(self):
        results = [_result("backend", ["app.py"]), _result("frontend", ["index.html"])]
        self.assertEqual(Orchestrator._detect_file_write_collisions(results), {})

    def test_two_agents_writing_same_file_is_a_collision(self):
        results = [_result("backend", ["requirements.txt"]), _result("database", ["requirements.txt"])]
        collisions = Orchestrator._detect_file_write_collisions(results)
        self.assertEqual(collisions, {"requirements.txt": ["backend", "database"]})

    def test_three_agents_writing_same_file_lists_all(self):
        results = [
            _result("backend", ["README.md"]),
            _result("database", ["README.md"]),
            _result("frontend", ["README.md"]),
        ]
        collisions = Orchestrator._detect_file_write_collisions(results)
        self.assertEqual(collisions["README.md"], ["backend", "database", "frontend"])

    def test_same_agent_writing_twice_is_not_a_collision(self):
        # z.B. write_file gefolgt von edit_file auf dieselbe Datei durch DENSELBEN Agenten -
        # keine Kollision, nur eine echte Bearbeitungshistorie.
        results = [_result("backend", ["app.py", "app.py"])]
        self.assertEqual(Orchestrator._detect_file_write_collisions(results), {})

    def test_empty_results_returns_empty(self):
        self.assertEqual(Orchestrator._detect_file_write_collisions([]), {})

    def test_no_files_written_returns_empty(self):
        results = [_result("backend", []), _result("database", [])]
        self.assertEqual(Orchestrator._detect_file_write_collisions(results), {})


class TestBuildFileCollisionSection(unittest.TestCase):
    def test_empty_collisions_returns_empty_string(self):
        self.assertEqual(Orchestrator._build_file_collision_section([]), "")

    def test_renders_path_phase_and_agents(self):
        section = Orchestrator._build_file_collision_section([
            {"phase": "Fachbereich 2/5: Software-Entwicklung", "path": "requirements.txt", "agents": ["backend", "database"]},
        ])
        self.assertIn("requirements.txt", section)
        self.assertIn("Fachbereich 2/5", section)
        self.assertIn("backend", section)
        self.assertIn("database", section)
        self.assertIn("Datei-Kollisionen", section)


class _RecordingFakeLLM:
    def __init__(self, label: str):
        self.label = label
        self.model_name = "fake-model"

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        from core.llm_factory import LLMResponse
        return LLMResponse(
            text=f"[{self.label}] verarbeitet.", model_name=self.model_name,
            prompt_tokens=10, completion_tokens=10, total_tokens=20, tool_calls=[],
        )

    async def generate_with_usage(self, prompt, system_prompt=None):
        from core.llm_factory import LLMResponse
        return LLMResponse(text=f"[{self.label}] verarbeitet.", model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=10, total_tokens=20)


class TestDepartmentHierarchySurfacesCollisions(unittest.TestCase):
    """
    Integrationsnaher Test: _run_agents_parallel() selbst ist gemockt (die echte agentische
    Ausführung/Tool-Nutzung ist bereits an anderer Stelle abgedeckt), Gegenstand hier ist NUR,
    ob _run_department_hierarchy() eine erkannte Kollision tatsächlich per notify() meldet UND
    in collision_sink einträgt - mit genügend Mitgliedern (>2), damit der Fachbereich
    tatsächlich im "parallel"-Modus läuft (siehe effective_run_mode-Fallback auf sequenziell
    bei ≤2 Mitgliedern).
    """

    def setUp(self):
        self.orchestrator = Orchestrator()
        for agent_id, agent in self.orchestrator._agents.items():
            agent._llm = _RecordingFakeLLM(agent_id)
        for lead in self.orchestrator._dept_leads.values():
            lead._llm = _RecordingFakeLLM("lead")

    def test_collision_between_parallel_members_is_notified_and_collected(self):
        agent_tasks = [
            AgentTask(task_id="t1", agent_id="backend", description="API bauen"),
            AgentTask(task_id="t2", agent_id="database", description="Schema bauen"),
            AgentTask(task_id="t3", agent_id="frontend", description="UI bauen"),
        ]
        fake_results = [
            _result("backend", ["requirements.txt", "app.py"]),
            _result("database", ["requirements.txt", "models.py"]),
            _result("frontend", ["index.html"]),
        ]
        notifications: list[str] = []
        collision_sink: list[dict] = []

        with patch.object(Orchestrator, "_run_agents_parallel", return_value=fake_results):
            asyncio.run(self.orchestrator._run_department_hierarchy(
                user_request="Baue eine kleine App",
                task_summary="App implementiert",
                agent_tasks=agent_tasks,
                project_dir=".",
                notify=notifications.append,
                collision_sink=collision_sink,
            ))

        self.assertEqual(len(collision_sink), 1)
        self.assertEqual(collision_sink[0]["path"], "requirements.txt")
        self.assertEqual(collision_sink[0]["agents"], ["backend", "database"])
        self.assertTrue(any("Datei-Kollision" in n for n in notifications))

    def test_no_collision_leaves_sink_empty(self):
        agent_tasks = [
            AgentTask(task_id="t1", agent_id="backend", description="API bauen"),
            AgentTask(task_id="t2", agent_id="database", description="Schema bauen"),
            AgentTask(task_id="t3", agent_id="frontend", description="UI bauen"),
        ]
        fake_results = [
            _result("backend", ["app.py"]),
            _result("database", ["models.py"]),
            _result("frontend", ["index.html"]),
        ]
        notifications: list[str] = []
        collision_sink: list[dict] = []

        with patch.object(Orchestrator, "_run_agents_parallel", return_value=fake_results):
            asyncio.run(self.orchestrator._run_department_hierarchy(
                user_request="Baue eine kleine App",
                task_summary="App implementiert",
                agent_tasks=agent_tasks,
                project_dir=".",
                notify=notifications.append,
                collision_sink=collision_sink,
            ))

        self.assertEqual(collision_sink, [])
        self.assertFalse(any("Datei-Kollision" in n for n in notifications))

    def test_collision_sink_none_does_not_crash(self):
        """Bestehende Aufrufer/Tests, die collision_sink nicht übergeben, bleiben unverändert lauffähig."""
        agent_tasks = [
            AgentTask(task_id="t1", agent_id="backend", description="API bauen"),
            AgentTask(task_id="t2", agent_id="database", description="Schema bauen"),
            AgentTask(task_id="t3", agent_id="frontend", description="UI bauen"),
        ]
        fake_results = [
            _result("backend", ["requirements.txt"]),
            _result("database", ["requirements.txt"]),
            _result("frontend", ["index.html"]),
        ]
        with patch.object(Orchestrator, "_run_agents_parallel", return_value=fake_results):
            results, _fo, _ba, _c = asyncio.run(self.orchestrator._run_department_hierarchy(
                user_request="Baue eine kleine App",
                task_summary="App implementiert",
                agent_tasks=agent_tasks,
                project_dir=".",
                notify=lambda msg: None,
            ))
        self.assertTrue(len(results) > 0)


if __name__ == "__main__":
    unittest.main()
