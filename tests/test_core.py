"""
tests/test_core.py – Tests für TaskManager, Workspace, Sandbox, TokenGuard & ToolRegistry
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from core.code_sandbox import CodeSandbox
from core.workspace import WorkspaceManager
from core.tool_registry import ToolRegistry
from core.task_manager import TaskManager, AVAILABLE_AGENTS
from core.token_guard import TokenGuard


class TestCoreModules(unittest.TestCase):
    """Testet die Kernkomponenten des Systems."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = WorkspaceManager(base_workspace_dir=self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_available_agents_structure(self):
        """Prüft, dass alle 30 Agenten im TaskManager mit Namen und Phase konfiguriert sind."""
        self.assertEqual(len(AVAILABLE_AGENTS), 30)
        for aid, info in AVAILABLE_AGENTS.items():
            self.assertIn("name", info)
            self.assertIn("phase", info)
            self.assertIn("description", info)
            self.assertIn(info["phase"], [1, 2, 3, 4])

    def test_token_guard_recording_and_warnings(self):
        """Prüft, dass TokenGuard Verbräuche misst und Warnungen auslöst."""
        guard = TokenGuard(high_usage_threshold_per_call=1000)
        warnings = guard.record_usage("gemini-2.5-flash", 800, 400, "BackendAgent")
        self.assertEqual(len(warnings), 1)
        self.assertIn("Hoher Tokenverbrauch", warnings[0])

        guard.mark_model_exhausted("claude-3-5-sonnet")
        self.assertTrue(guard.is_model_exhausted("claude-3-5-sonnet"))

    def test_workspace_file_parsing_fence(self):
        """Testet das Extrahieren von Code-Blöcken mit Datei-Pfaden."""
        sample_response = """
Hier ist die Implementierung:

```python:src/main.py
def hello():
    return "world"
```

Und die Konfiguration:
```yaml:config/settings.yml
app_name: test
port: 8080
```
"""
        saved = self.workspace.parse_and_save_files("test_proj", sample_response, "TesterAgent")
        self.assertEqual(len(saved), 2)

        files = self.workspace.list_project_files("test_proj")
        paths = [f["path"] for f in files]
        self.assertIn("src/main.py", paths)
        self.assertIn("config/settings.yml", paths)

        main_content = (Path(self.temp_dir) / "test_proj" / "src" / "main.py").read_text(encoding="utf-8")
        self.assertIn('return "world"', main_content)

    def test_workspace_zip_export(self):
        """Testet die Erstellung eines ZIP-Archivs für ein Projekt."""
        self.workspace.parse_and_save_files("zip_proj", "```python:app.py\nprint(1)\n```")
        zip_path = self.workspace.create_project_zip("zip_proj")
        self.assertTrue(os.path.exists(zip_path))
        self.assertTrue(zip_path.endswith(".zip"))

    def test_sandbox_validation(self):
        """Testet statische Validierung für Python und JSON."""
        res_py_valid = CodeSandbox.validate_code("def foo():\n    return 42", "py")
        self.assertTrue(res_py_valid.is_valid)

        res_py_invalid = CodeSandbox.validate_code("def foo( broken syntax", "py")
        self.assertFalse(res_py_invalid.is_valid)

        res_json_valid = CodeSandbox.validate_code('{"key": "value"}', "json")
        self.assertTrue(res_json_valid.is_valid)

        res_json_invalid = CodeSandbox.validate_code('{"key": invalid}', "json")
        self.assertFalse(res_json_invalid.is_valid)

    def test_tool_registry(self):
        """Testet die ToolRegistry und die integrierten Tools."""
        registry = ToolRegistry(workspace_manager=self.workspace)
        tools = registry.list_tools()
        tool_names = [t["name"] for t in tools]
        self.assertIn("validate_syntax", tool_names)
        self.assertIn("list_workspace_files", tool_names)


if __name__ == "__main__":
    unittest.main()
