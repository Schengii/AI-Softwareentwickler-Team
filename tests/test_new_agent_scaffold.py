"""
tests/test_new_agent_scaffold.py – Testet scripts/new_agent.py (Scaffolding-Werkzeug für eine
neue Fachrolle).

Die drei `insert_*`-Funktionen arbeiten rein auf Strings (kein Dateizugriff) und werden hier
gegen kleine, aber strukturell exakte Ausschnitte der echten Zieldateien getestet - dieselben
Anker (Marker-Strings/Regex), auf die scripts/new_agent.py in den echten Dateien trifft. Der
End-to-End-Test kopiert die ECHTEN vier Zieldateien in ein Temp-Verzeichnis und lässt main()
komplett gegen diese Kopien laufen (nie gegen das echte Repository) - validiert damit, dass
die Anker auch im tatsächlichen, aktuellen Dateiinhalt greifen, nicht nur in einem
nachgebauten Mini-Beispiel.
"""

import ast
import shutil
import tempfile
import unittest
from pathlib import Path

import scripts.new_agent as new_agent_module
from scripts.new_agent import (
    _pascal_case,
    insert_config_entries,
    insert_orchestrator_registration,
    insert_task_manager_entry,
    render_agent_file,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestPascalCase(unittest.TestCase):
    def test_single_word(self):
        self.assertEqual(_pascal_case("backend"), "Backend")

    def test_multiple_words(self):
        self.assertEqual(_pascal_case("load_tester"), "LoadTester")


class TestInsertOrchestratorRegistration(unittest.TestCase):
    SNIPPET = (
        "from agents.accessibility_agent import AccessibilityAgent\n"
        "from agents.backend_agent import BackendAgent\n"
        "\n"
        "class Orchestrator:\n"
        "    def __init__(self):\n"
        "        self._agents: dict[str, BaseAgent] = {\n"
        '            "backend":           BackendAgent(),\n'
        "        }\n"
    )

    def test_adds_import_and_dict_entry(self):
        result = insert_orchestrator_registration(self.SNIPPET, "load_tester", "LoadTesterAgent")
        self.assertIn("from agents.load_tester_agent import LoadTesterAgent\n", result)
        self.assertIn('"load_tester":', result)
        self.assertIn("LoadTesterAgent(),", result)
        # Bestehender Eintrag bleibt unangetastet.
        self.assertIn('"backend":           BackendAgent(),', result)

    def test_raises_on_duplicate_import(self):
        with self.assertRaises(ValueError):
            insert_orchestrator_registration(self.SNIPPET, "backend", "BackendAgent")


class TestInsertTaskManagerEntry(unittest.TestCase):
    SNIPPET = (
        "AVAILABLE_AGENTS = {\n"
        '    "backend": {\n'
        '        "name": "Backend-Entwickler",\n'
        '        "phase": 3,\n'
        '        "description": "Baut die Server-Logik.",\n'
        "    },\n"
        "}\n"
    )

    def test_adds_entry_before_closing_brace(self):
        result = insert_task_manager_entry(self.SNIPPET, "load_tester", "Load-Test-Spezialist", 5, "Fuehrt Lasttests durch.")
        self.assertIn('"load_tester": {', result)
        self.assertIn('"name": "Load-Test-Spezialist",', result)
        self.assertIn('"phase": 5,', result)
        self.assertIn('"description": "Fuehrt Lasttests durch.",', result)
        # Bestehender Eintrag bleibt unangetastet, Dict schliesst weiterhin sauber.
        self.assertIn('"backend": {', result)
        self.assertTrue(result.rstrip().endswith("}"))

    def test_raises_on_duplicate_agent_id(self):
        with self.assertRaises(ValueError):
            insert_task_manager_entry(self.SNIPPET, "backend", "x", 1, "y")


class TestInsertConfigEntries(unittest.TestCase):
    SNIPPET = (
        'AGENT_MODELS: dict[str, str] = {\n'
        '    "backend":           os.getenv("BACKEND_MODEL",         HEAVY_MODEL),\n'
        "}\n"
        "\n"
        'DEPARTMENT_DEV_AGENTS = {"dev_lead", "backend", "frontend"}\n'
        'DEPARTMENT_QA_AGENTS = {"qa_lead", "tester"}\n'
    )

    def test_adds_model_entry_and_department_membership(self):
        result = insert_config_entries(self.SNIPPET, "load_tester", "standard", "qa")
        self.assertIn('"load_tester":', result)
        self.assertIn("STANDARD_MODEL", result.split("AGENT_MODELS", 1)[1].split("\n}", 1)[0])
        self.assertIn('"load_tester"', result.split("DEPARTMENT_QA_AGENTS", 1)[1].splitlines()[0])
        # Anderer Fachbereich bleibt unangetastet.
        self.assertNotIn("load_tester", result.split("DEPARTMENT_DEV_AGENTS", 1)[1].splitlines()[0])

    def test_raises_on_duplicate_model_entry(self):
        with self.assertRaises(ValueError):
            insert_config_entries(self.SNIPPET, "backend", "heavy", "dev")

    def test_raises_when_already_in_target_department(self):
        # "backend" ist bereits in DEPARTMENT_DEV_AGENTS gelistet (siehe SNIPPET), aber noch
        # nicht in AGENT_MODELS -> die AGENT_MODELS-Prüfung greift hier noch nicht, wohl aber
        # die Fachbereichs-Mitgliedschaftsprüfung.
        snippet = self.SNIPPET.replace(
            'AGENT_MODELS: dict[str, str] = {\n',
            'AGENT_MODELS: dict[str, str] = {\n    "other_agent": x,\n',
        )
        with self.assertRaises(ValueError):
            insert_config_entries(snippet, "backend", "standard", "dev")


class TestRenderAgentFile(unittest.TestCase):
    def test_generated_file_is_valid_python(self):
        content = render_agent_file("load_tester", "LoadTesterAgent", "Load-Test-Spezialist", "Fuehrt Lasttests durch.", 5)
        ast.parse(content)  # wirft SyntaxError, falls das Gerüst kaputt ist
        self.assertIn("class LoadTesterAgent(BaseAgent):", content)
        self.assertIn('agent_id="load_tester"', content)


class TestEndToEndScaffold(unittest.TestCase):
    """Kopiert die ECHTEN vier Zieldateien in ein Temp-Verzeichnis und lässt main() komplett
    dagegen laufen - verifiziert, dass die Anker auch im tatsächlichen, aktuellen Dateiinhalt
    greifen (nicht nur in einem nachgebauten Mini-Beispiel), OHNE das echte Repository je
    anzufassen."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.agents_dir = self.temp_dir / "agents" / "orchestrator"
        self.agents_dir.mkdir(parents=True)
        (self.temp_dir / "agents" / "base_agent.py").write_text(
            (REPO_ROOT / "agents" / "base_agent.py").read_text(encoding="utf-8"), encoding="utf-8",
        )
        shutil.copy(REPO_ROOT / "agents" / "orchestrator" / "__init__.py", self.agents_dir / "__init__.py")
        (self.temp_dir / "core").mkdir()
        shutil.copy(REPO_ROOT / "core" / "task_manager.py", self.temp_dir / "core" / "task_manager.py")
        shutil.copy(REPO_ROOT / "config.py", self.temp_dir / "config.py")

        self._orig = (
            new_agent_module.REPO_ROOT, new_agent_module.ORCHESTRATOR_INIT,
            new_agent_module.TASK_MANAGER, new_agent_module.CONFIG_PY,
        )
        new_agent_module.REPO_ROOT = self.temp_dir
        new_agent_module.ORCHESTRATOR_INIT = self.agents_dir / "__init__.py"
        new_agent_module.TASK_MANAGER = self.temp_dir / "core" / "task_manager.py"
        new_agent_module.CONFIG_PY = self.temp_dir / "config.py"

    def tearDown(self):
        (
            new_agent_module.REPO_ROOT, new_agent_module.ORCHESTRATOR_INIT,
            new_agent_module.TASK_MANAGER, new_agent_module.CONFIG_PY,
        ) = self._orig
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_scaffolds_a_new_agent_consistently_against_real_files(self):
        exit_code = new_agent_module.main([
            "load_tester",
            "--name", "Load-Test-Spezialist",
            "--description", "Fuehrt automatisierte Lasttests gegen neue Endpunkte durch.",
            "--phase", "5",
            "--department", "qa",
            "--tier", "standard",
        ])
        self.assertEqual(exit_code, 0)

        agent_file = self.temp_dir / "agents" / "load_tester_agent.py"
        self.assertTrue(agent_file.exists())
        ast.parse(agent_file.read_text(encoding="utf-8"))

        orchestrator_text = new_agent_module.ORCHESTRATOR_INIT.read_text(encoding="utf-8")
        ast.parse(orchestrator_text)
        self.assertIn("from agents.load_tester_agent import LoadTesterAgent", orchestrator_text)
        self.assertIn('"load_tester"', orchestrator_text)

        task_manager_text = new_agent_module.TASK_MANAGER.read_text(encoding="utf-8")
        ast.parse(task_manager_text)
        self.assertIn('"load_tester": {', task_manager_text)

        config_text = new_agent_module.CONFIG_PY.read_text(encoding="utf-8")
        ast.parse(config_text)
        self.assertIn('"load_tester":', config_text)
        self.assertIn('"load_tester"', config_text.split("DEPARTMENT_QA_AGENTS", 1)[1].splitlines()[0])

    def test_rejects_already_existing_agent_id(self):
        exit_code = new_agent_module.main([
            "backend", "--name", "x", "--description", "y",
            "--phase", "3", "--department", "dev", "--tier", "standard",
        ])
        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
