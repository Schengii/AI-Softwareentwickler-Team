"""
tests/test_core.py – Tests für TaskManager, Workspace, Sandbox & TokenGuard
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from core.code_sandbox import CodeSandbox
from core.task_manager import (
    _DECOMPOSE_EXCLUDED_AGENT_IDS,
    AVAILABLE_AGENTS,
    DECOMPOSE_SYSTEM_PROMPT,
    TaskManager,
    _relevant_agent_ids,
)
from core.token_guard import TokenGuard
from core.workspace import WorkspaceManager


class TestCoreModules(unittest.TestCase):
    """Testet die Kernkomponenten des Systems."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = WorkspaceManager(base_workspace_dir=self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_available_agents_structure(self):
        """Prüft, dass alle 33 Agenten im TaskManager mit Namen und Phase konfiguriert sind."""
        self.assertEqual(len(AVAILABLE_AGENTS), 33)
        for data in AVAILABLE_AGENTS.values():
            self.assertIn("name", data)
            self.assertIn("phase", data)
            self.assertIn("description", data)
            self.assertIsInstance(data["phase"], int)
            self.assertTrue(1 <= data["phase"] <= 6)

    def test_decompose_system_prompt_agent_id_placeholder_gets_substituted(self):
        """Realer Fund (Team-Retrospektive 2026-09-06): die im System-Prompt gesendete Liste
        "Verfügbare Agenten-IDs" war früher ein von Hand gepflegter, zweiter String, komplett
        unabhängig von AVAILABLE_AGENTS - bereits real gedriftet (`agent_trainer` stand dort
        als wählbar, obwohl bewusst ohne Beschreibung ausgeschlossen). decompose() muss den
        Platzhalter durch GENAU die Agenten-IDs ersetzen, die auch die Beschreibungsliste
        speisen - dieselbe Ausschlussliste, eine einzige Quelle."""
        self.assertIn("__AVAILABLE_AGENT_IDS__", DECOMPOSE_SYSTEM_PROMPT)

        task_manager = TaskManager(model_name="gemini-3.6-flash")
        task_manager._llm = AsyncMock()
        task_manager._llm.generate_json.return_value = json.dumps({
            "needs_clarification": False,
            "clarifying_questions": [],
            "task_summary": "Test",
            "project_slug": "test",
            "required_agents": [],
        })

        asyncio.run(task_manager.decompose("Baue etwas"))

        sent_system_prompt = task_manager._llm.generate_json.call_args[0][1]
        self.assertNotIn("__AVAILABLE_AGENT_IDS__", sent_system_prompt)
        # Nischenrollen, die für diese Anfrage ausgeblendet sind, fehlen bewusst (_relevant_agent_ids).
        hidden_niche_ids = _relevant_agent_ids("Baue etwas")
        for agent_id in AVAILABLE_AGENTS:
            if agent_id in _DECOMPOSE_EXCLUDED_AGENT_IDS:
                self.assertNotIn(agent_id, sent_system_prompt)
            elif agent_id not in hidden_niche_ids:
                self.assertIn(agent_id, sent_system_prompt)

    def test_token_guard_recording_and_warnings(self):
        """Prüft, dass TokenGuard Verbräuche misst und Warnungen auslöst."""
        guard = TokenGuard(high_usage_threshold_per_call=1000)
        warnings = guard.record_usage("gemini-2.5-flash", 800, 400, "BackendAgent")
        self.assertEqual(len(warnings), 1)
        self.assertIn("Hoher Tokenverbrauch", warnings[0])

        guard.mark_model_exhausted("claude-3-5-sonnet")
        self.assertTrue(guard.is_model_exhausted("claude-3-5-sonnet"))

    def test_get_summary_returns_an_independent_snapshot_not_a_live_reference(self):
        """
        Realer Fund: get_summary()["models"] nutzte vars(v) - das liefert v.__dict__ direkt
        zurück, KEINE Kopie. Ein Aufrufer, der sich einen frühen Stand für eine spätere
        Differenzberechnung merkt (z.B. agents/orchestrator.py._model_usage_deltas() für
        memory/cost_history.py), sah durch spätere record_usage()-Aufrufe unbemerkt den
        AKTUELLEN Stand statt des gemerkten - jede Delta-Berechnung wäre fälschlich 0 gewesen.
        """
        guard = TokenGuard()
        guard.record_usage("gemini-3.6-flash", 100, 50)
        snapshot = guard.get_summary()["models"]

        guard.record_usage("gemini-3.6-flash", 900, 900)  # nach dem Snapshot

        self.assertEqual(snapshot["gemini-3.6-flash"]["total_tokens"], 150)  # unverändert
        self.assertEqual(guard.get_summary()["models"]["gemini-3.6-flash"]["total_tokens"], 1950)  # echter aktueller Stand

    def test_seconds_until_available_returns_zero_for_unknown_or_recovered_models(self):
        guard = TokenGuard()
        # Unbekanntes Modell -> sofort verfügbar.
        self.assertEqual(guard.seconds_until_available(["nie-erschoepft"]), 0.0)

        guard.mark_model_exhausted("a", cooldown_seconds=30.0)
        guard.mark_model_exhausted("b", cooldown_seconds=5.0)
        # "c" ist gar nicht erschöpft -> die Liste gilt als sofort verfügbar (0.0).
        self.assertEqual(guard.seconds_until_available(["a", "b", "c"]), 0.0)

    def test_seconds_until_available_returns_shortest_cooldown_when_all_exhausted(self):
        guard = TokenGuard()
        guard.mark_model_exhausted("a", cooldown_seconds=30.0)
        guard.mark_model_exhausted("b", cooldown_seconds=5.0)
        wait = guard.seconds_until_available(["a", "b"])
        # Kürzerer Cooldown (b, ~5s) muss gewinnen, nicht der längere (a, ~30s).
        self.assertGreater(wait, 0.0)
        self.assertLessEqual(wait, 5.0)

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

    def test_workspace_file_parsing_skips_syntactically_invalid_python(self):
        """
        Wie core/agent_toolbox.py._tool_write_file(): niemals syntaktisch kaputtes Python
        unbemerkt auf die Platte schreiben, auch nicht über den Regex-Text-Fallback.
        """
        sample_response = """
```python:broken.py
def hello(:
    return "world"
```

```python:ok.py
def works():
    return 1
```
"""
        saved = self.workspace.parse_and_save_files("broken_proj", sample_response, "TesterAgent")
        saved_paths = [f.relative_path for f in saved]
        self.assertNotIn("broken.py", saved_paths)
        self.assertIn("ok.py", saved_paths)
        self.assertFalse((Path(self.temp_dir) / "broken_proj" / "broken.py").exists())

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

    def test_sandbox_run_command_strips_sensitive_env_vars(self):
        """
        run_command() startet vom Modell gewählte pip-/npm-Kommandos (siehe
        core/agent_toolbox.py) – ein bösartiges Paket könnte per Install-Skript versuchen,
        Umgebungsvariablen auszulesen. Diese dürfen daher NIE echte Secrets sehen, PATH &
        Co. müssen aber weiter funktionieren (sonst schlägt jede echte pip/npm-Ausführung fehl).
        """
        os.environ["TEST_FAKE_GEMINI_API_KEY"] = "sk-should-never-leak"
        self.addCleanup(os.environ.pop, "TEST_FAKE_GEMINI_API_KEY", None)

        probe = (
            "import os; "
            "print('SECRET=' + os.environ.get('TEST_FAKE_GEMINI_API_KEY', 'MISSING')); "
            "print('PATH_OK=' + ('yes' if os.environ.get('PATH') else 'no'))"
        )
        result = CodeSandbox.run_command([sys.executable, "-c", probe], timeout_seconds=15)

        self.assertEqual(result.exit_code, 0, msg=result.stderr)
        self.assertIn("SECRET=MISSING", result.stdout)  # Secret wurde NICHT durchgereicht
        self.assertIn("PATH_OK=yes", result.stdout)     # PATH funktioniert weiterhin

    def test_sandbox_run_command_restrict_env_false_keeps_full_env(self):
        """restrict_env=False bleibt als bewusster Opt-out verfügbar (kein Verhaltensbruch)."""
        os.environ["TEST_FAKE_GEMINI_API_KEY"] = "sk-visible-when-opted-out"
        self.addCleanup(os.environ.pop, "TEST_FAKE_GEMINI_API_KEY", None)

        probe = "import os; print('SECRET=' + os.environ.get('TEST_FAKE_GEMINI_API_KEY', 'MISSING'))"
        result = CodeSandbox.run_command([sys.executable, "-c", probe], timeout_seconds=15, restrict_env=False)

        self.assertEqual(result.exit_code, 0, msg=result.stderr)
        self.assertIn("SECRET=sk-visible-when-opted-out", result.stdout)

    @unittest.skipUnless(shutil.which("npm"), "npm nicht installiert - Windows-.cmd-Regressionstest übersprungen")
    def test_sandbox_run_command_resolves_windows_cmd_style_executables(self):
        """
        Realer Fund: core/verifier.py's neue npm-Verifikation schlug unter Windows IMMER mit
        `WinError 2` fehl – `npm` (und npx/yarn/pnpm) sind dort .cmd-Batch-Wrapper, keine
        echten .exe, und subprocess.run(["npm", ...], shell=False) kann .cmd/.bat-Dateien
        nicht direkt starten. run_command() löst command[0] jetzt vorab über shutil.which()
        auf den vollständigen, tatsächlich ausführbaren Pfad auf.
        """
        result = CodeSandbox.run_command(["npm", "--version"], timeout_seconds=15)
        self.assertEqual(result.exit_code, 0, msg=f"stdout={result.stdout}\nstderr={result.stderr}")
        self.assertRegex(result.stdout.strip(), r"^\d+\.\d+\.\d+$")

if __name__ == "__main__":
    unittest.main()
