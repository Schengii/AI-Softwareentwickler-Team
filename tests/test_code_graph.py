"""
tests/test_code_graph.py – Testet den AST-basierten Codebase-Graph (core/code_graph.py)
und die Werkzeug-Integration in core/agent_toolbox.py
"""

import asyncio
import tempfile
import unittest
from pathlib import Path

from core.agent_toolbox import AgentToolbox
from core.code_graph import CodebaseGraph


class TestCodebaseGraph(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = Path(self.temp_dir)

    def _create_sample_files(self):
        # 1. Models & Helper
        (self.project_dir / "models.py").write_text(
            "class User:\n"
            "    '''User entity model.'''\n"
            "    def __init__(self, name: str):\n"
            "        self.name = name\n\n"
            "    def get_display_name(self) -> str:\n"
            "        return f'User: {self.name}'\n",
            encoding="utf-8",
        )

        # 2. Service calling User
        (self.project_dir / "service.py").write_text(
            "from models import User\n\n"
            "def create_user_service(name: str) -> User:\n"
            "    user = User(name)\n"
            "    return user\n",
            encoding="utf-8",
        )

        # 3. Main calling service
        (self.project_dir / "main.py").write_text(
            "from service import create_user_service\n\n"
            "def main():\n"
            "    u = create_user_service('Alice')\n"
            "    print(u.get_display_name())\n",
            encoding="utf-8",
        )

        # 4. JS Frontend
        (self.project_dir / "app.js").write_text(
            "import { fetchUser } from './api';\n\n"
            "class UserCard extends HTMLElement {\n"
            "    connectedCallback() {}\n"
            "}\n\n"
            "function renderApp() {\n"
            "    console.log('rendering');\n"
            "}\n",
            encoding="utf-8",
        )

    def test_find_definition_python(self):
        self._create_sample_files()
        graph = CodebaseGraph(self.project_dir)

        user_defs = graph.find_definition("User")
        self.assertEqual(len(user_defs), 1)
        self.assertEqual(user_defs[0].kind, "class")
        self.assertEqual(user_defs[0].file_path, "models.py")
        self.assertEqual(user_defs[0].docstring, "User entity model.")

        func_defs = graph.find_definition("create_user_service")
        self.assertEqual(len(func_defs), 1)
        self.assertEqual(func_defs[0].kind, "function")
        self.assertEqual(func_defs[0].file_path, "service.py")

    def test_find_definition_javascript(self):
        self._create_sample_files()
        graph = CodebaseGraph(self.project_dir)

        js_classes = graph.find_definition("UserCard")
        self.assertEqual(len(js_classes), 1)
        self.assertEqual(js_classes[0].kind, "class")
        self.assertEqual(js_classes[0].file_path, "app.js")

        js_funcs = graph.find_definition("renderApp")
        self.assertEqual(len(js_funcs), 1)
        self.assertEqual(js_funcs[0].kind, "function")

    def test_find_references_and_impact_analysis(self):
        self._create_sample_files()
        graph = CodebaseGraph(self.project_dir)

        impact = graph.analyze_impact("User")
        self.assertEqual(impact.symbol_name, "User")
        self.assertEqual(impact.defining_file, "models.py")
        self.assertIn("service.py", impact.imported_in)
        self.assertIn("service.py", impact.referencing_files)

    def test_get_summary_output(self):
        self._create_sample_files()
        graph = CodebaseGraph(self.project_dir)
        summary = graph.get_summary()

        self.assertIn("Codebase-Graph: 4 Datei(en) indexiert", summary)
        self.assertIn("Symbole", summary)

    def test_get_structural_overview_contains_signatures_not_bodies(self):
        # Team-Optimierung (Token-Effizienz): get_structural_overview() ist die Grundlage für
        # den kompakten Kontext, den LEAN_CONTEXT_AGENT_IDS-Rollen (readme/compliance/
        # prompt_engineer, siehe agents/orchestrator/department.py) statt des vollen
        # running_context bekommen - muss Klassen-/Funktionssignaturen enthalten, aber NIE den
        # Funktionskörper (hier: "f'User: {self.name}'" darf nicht auftauchen).
        self._create_sample_files()
        graph = CodebaseGraph(self.project_dir)
        overview = graph.get_structural_overview()

        self.assertIn("class User", overview)
        self.assertIn("def create_user_service(name)", overview)
        self.assertNotIn("f'User: {self.name}'", overview)

    def test_get_structural_overview_on_empty_project(self):
        graph = CodebaseGraph(self.project_dir)
        overview = graph.get_structural_overview()
        self.assertIn("keine indexierbaren Quelldateien", overview)

    def test_agent_toolbox_tools_integration(self):
        self._create_sample_files()
        toolbox = AgentToolbox(self.project_dir, agent_id="backend")

        # find_symbol_definition tool
        res_def = asyncio.run(toolbox.dispatch("find_symbol_definition", {"symbol_name": "User"}))
        self.assertTrue(res_def["found"])
        self.assertEqual(res_def["definitions"][0]["file_path"], "models.py")

        # find_symbol_references tool
        res_ref = asyncio.run(toolbox.dispatch("find_symbol_references", {"symbol_name": "User"}))
        self.assertGreaterEqual(res_ref["references_count"], 1)

        # analyze_code_impact tool
        res_impact = asyncio.run(toolbox.dispatch("analyze_code_impact", {"symbol_name": "User"}))
        self.assertEqual(res_impact["defining_file"], "models.py")
        self.assertIn("service.py", res_impact["imported_in"])


if __name__ == "__main__":
    unittest.main()
