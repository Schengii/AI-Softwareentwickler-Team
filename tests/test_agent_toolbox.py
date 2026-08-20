"""
tests/test_agent_toolbox.py – Testet die echten, projektgebundenen Agenten-Werkzeuge

Prüft read_file/write_file/edit_file/list_files/search_code/run_command inkl.
Sicherheits-Grenzen (Directory-Traversal-Schutz, run_command-Whitelist,
eindeutige edit_file-Treffer) – die operative Grundlage des agentischen Loops.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path

from core.agent_toolbox import AgentToolbox


def run(coro):
    return asyncio.run(coro)


class TestAgentToolbox(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.toolbox = AgentToolbox(project_dir=self.temp_dir, agent_id="backend")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_write_then_read_file(self):
        result = run(self.toolbox.dispatch("write_file", {"path": "app/main.py", "content": "print('hi')"}))
        self.assertEqual(result["status"], "ok")
        self.assertIn("app/main.py", self.toolbox.files_written)

        read_result = run(self.toolbox.dispatch("read_file", {"path": "app/main.py"}))
        self.assertEqual(read_result["content"], "print('hi')")

    def test_read_missing_file_returns_error_not_crash(self):
        result = run(self.toolbox.dispatch("read_file", {"path": "does_not_exist.py"}))
        self.assertIn("error", result)

    def test_list_files_ignores_venv_and_git(self):
        (Path(self.temp_dir) / "app").mkdir()
        (Path(self.temp_dir) / "app" / "main.py").write_text("x = 1")
        (Path(self.temp_dir) / ".venv").mkdir()
        (Path(self.temp_dir) / ".venv" / "lib.py").write_text("y = 2")

        result = run(self.toolbox.dispatch("list_files", {}))
        self.assertIn("app/main.py", result["files"])
        self.assertFalse(any(".venv" in f for f in result["files"]))

    def test_edit_file_requires_unique_match(self):
        run(self.toolbox.dispatch("write_file", {"path": "app.py", "content": "x = 1\nx = 1\n"}))

        ambiguous = run(self.toolbox.dispatch("edit_file", {"path": "app.py", "old_text": "x = 1", "new_text": "x = 2"}))
        self.assertIn("error", ambiguous)
        self.assertIn("mal", ambiguous["error"])

    def test_edit_file_applies_unique_patch(self):
        run(self.toolbox.dispatch("write_file", {"path": "app.py", "content": "def foo():\n    return 1\n"}))

        result = run(self.toolbox.dispatch("edit_file", {
            "path": "app.py", "old_text": "return 1", "new_text": "return 2",
        }))
        self.assertEqual(result["status"], "ok")

        content = (Path(self.temp_dir) / "app.py").read_text()
        self.assertIn("return 2", content)
        self.assertIn("app.py", self.toolbox.files_written)

    def test_write_file_rejects_syntactically_invalid_python(self):
        """
        Realer Fund aus einem echten Lauf: ein Agent überschrieb main.py per write_file mit
        Inhalt, dessen Zeilenumbrüche/Anführungszeichen als literale '\\n'/'\\"' statt echter
        Escape-Sequenzen im String landeten - eine einzige, komplett kaputte Zeile. Die Datei
        landete unbemerkt auf der Platte; main.py UND interface/cli.py waren danach nicht mehr
        lauffähig. write_file muss das jetzt sofort ablehnen, bevor etwas geschrieben wird.
        """
        broken_content = '\\"\\"\\"\\nmain.py\\n\\"\\"\\"\\n\\nimport sys\\n'
        result = run(self.toolbox.dispatch("write_file", {"path": "main.py", "content": broken_content}))
        self.assertIn("error", result)
        self.assertIn("Syntax-Fehler", result["error"])
        self.assertFalse((Path(self.temp_dir) / "main.py").exists())
        self.assertNotIn("main.py", self.toolbox.files_written)

    def test_write_file_still_accepts_valid_python(self):
        result = run(self.toolbox.dispatch("write_file", {"path": "ok.py", "content": "def foo():\n    return 1\n"}))
        self.assertEqual(result["status"], "ok")
        self.assertTrue((Path(self.temp_dir) / "ok.py").exists())

    def test_write_file_syntax_check_ignores_non_python_files(self):
        # Absichtlich "ungültiges Python", aber kein .py - darf nicht betroffen sein.
        result = run(self.toolbox.dispatch("write_file", {"path": "notes.txt", "content": "def foo(:\n"}))
        self.assertEqual(result["status"], "ok")

    def test_edit_file_rejects_edit_that_would_break_syntax(self):
        run(self.toolbox.dispatch("write_file", {"path": "app.py", "content": "def foo():\n    return 1\n"}))

        result = run(self.toolbox.dispatch("edit_file", {
            "path": "app.py", "old_text": "return 1", "new_text": "return 1(",  # syntaktisch kaputt
        }))
        self.assertIn("error", result)
        self.assertIn("Syntax-Fehler", result["error"])
        # Die Original-Datei muss unangetastet (weiterhin gültig) bleiben - NICHT mit dem
        # syntaktisch kaputten "return 1(" überschrieben worden sein.
        content = (Path(self.temp_dir) / "app.py").read_text()
        self.assertIn("return 1\n", content)
        self.assertNotIn("return 1(", content)

    def test_directory_traversal_is_rejected(self):
        result = run(self.toolbox.dispatch("write_file", {"path": "../../evil.py", "content": "pwned = True"}))
        self.assertIn("error", result)
        self.assertFalse((Path(self.temp_dir).parent.parent / "evil.py").exists())

    def test_run_command_whitelist_blocks_arbitrary_commands(self):
        result = run(self.toolbox.dispatch("run_command", {"command": "rm -rf /"}))
        self.assertIn("error", result)

    def test_run_command_allows_whitelisted_python_module(self):
        run(self.toolbox.dispatch("write_file", {"path": "hello.py", "content": "print('hello')"}))
        # 'python' wird intern auf sys.executable gemappt; ein einfaches unittest-discover
        # ohne Testdateien liefert exit_code 0 (keine Tests gefunden ist kein Fehler für unittest).
        result = run(self.toolbox.dispatch("run_command", {"command": "python -m unittest discover"}))
        self.assertIn("exit_code", result)

    def test_search_code_finds_relevant_chunk(self):
        run(self.toolbox.dispatch("write_file", {
            "path": "auth/service.py",
            "content": "def authenticate_user(username, password):\n    return verify_jwt(username, password)\n",
        }))
        result = run(self.toolbox.dispatch("search_code", {"query": "authenticate JWT", "top_k": 3}))
        self.assertTrue(any("auth/service.py" in r["file"] for r in result["results"]))

    def test_read_only_toolbox_blocks_write(self):
        read_only_box = AgentToolbox(project_dir=self.temp_dir, agent_id="planning_lead", read_only=True)
        result = run(read_only_box.dispatch("write_file", {"path": "x.py", "content": "x = 1"}))
        self.assertIn("error", result)

    def test_unknown_tool_returns_error_not_crash(self):
        result = run(self.toolbox.dispatch("delete_everything", {}))
        self.assertIn("error", result)

    def test_env_file_cannot_be_read(self):
        # project_dir kann seit /audit-projekt auch auf das Framework-Root zeigen (echtes
        # .env mit echten API-Keys), nicht nur auf generierte workspace/-Sandboxen.
        (Path(self.temp_dir) / ".env").write_text("GEMINI_API_KEY=echter-geheimer-wert")
        result = run(self.toolbox.dispatch("read_file", {"path": ".env"}))
        self.assertIn("error", result)
        self.assertNotIn("geheimer-wert", str(result))

    def test_env_file_hidden_from_list_files(self):
        (Path(self.temp_dir) / ".env").write_text("SECRET=1")
        (Path(self.temp_dir) / "app.py").write_text("x = 1")
        result = run(self.toolbox.dispatch("list_files", {}))
        self.assertNotIn(".env", result["files"])
        self.assertIn("app.py", result["files"])

    def test_env_file_cannot_be_overwritten(self):
        (Path(self.temp_dir) / ".env").write_text("GEMINI_API_KEY=echt")
        result = run(self.toolbox.dispatch("write_file", {"path": ".env", "content": "pwned=true"}))
        self.assertIn("error", result)
        self.assertEqual((Path(self.temp_dir) / ".env").read_text(), "GEMINI_API_KEY=echt")

    def test_credentials_json_and_pem_files_blocked(self):
        for name in ("credentials.json", "server.pem", "id_rsa"):
            (Path(self.temp_dir) / name).write_text("secret-content")
            result = run(self.toolbox.dispatch("read_file", {"path": name}))
            self.assertIn("error", result, msg=f"{name} sollte gesperrt sein")

    def test_env_example_remains_readable(self):
        (Path(self.temp_dir) / ".env.example").write_text("GEMINI_API_KEY=")
        result = run(self.toolbox.dispatch("read_file", {"path": ".env.example"}))
        self.assertNotIn("error", result)


if __name__ == "__main__":
    unittest.main()
