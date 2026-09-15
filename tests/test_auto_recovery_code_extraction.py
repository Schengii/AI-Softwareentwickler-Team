"""
tests/test_auto_recovery_code_extraction.py – Testet den Auto-Recovery-Parser
(agents/base_agent.py._attempt_auto_recovery_save), der das `/goal`-Auftrag-Problem aus dem
nexus_resilience_gateway-Lauf behebt: ein Code-schreibender Agent lieferte fertigen Code als
Markdown-Codeblock im Antworttext, rief aber write_file/edit_file NIE auf (tool_calls_count: 0).
Bisher schlug das Hard Delivery Gate an und der komplette Tokenverbrauch verpuffte, obwohl der
Code inhaltlich bereits fertig formuliert war.

Der Parser greift, sobald der Agent trotz des regulären Korrektur-Hinweises (siehe
_run_agentic_loop) keine einzige Datei über ein echtes Werkzeug gespeichert hat: er extrahiert
Codeblöcke mit erkennbarem Dateipfad-Anker (core/workspace.py.extract_file_blocks) - und, NUR
für den frontend-Agenten, zusätzlich ein pfadloses vollständiges HTML-Dokument - und speichert
sie über denselben validierten write_file-Pfad wie ein echter Tool-Aufruf.
"""

import asyncio
import logging
import shutil
import tempfile
import unittest
from pathlib import Path

from agents.backend_agent import BackendAgent
from agents.frontend_agent import FrontendAgent
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask


class _FixedTextLLM:
    """Gibt bei JEDEM generate_with_tools-Aufruf dieselbe reine Textantwort ohne Tool-Calls
    zurück - simuliert einen Agenten, der Code nur im Chat-Text ausgibt statt write_file
    aufzurufen (tool_calls_count bleibt 0)."""

    def __init__(self, text: str):
        self._text = text
        self.model_name = "fake-model"

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        return LLMResponse(text=self._text, model_name=self.model_name,
                            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[])


class TestAutoRecoveryCodeExtraction(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_explicit_path_header_block_is_auto_saved(self):
        """`# Dateipfad: ...`-Header vor einem Fence wird erkannt, automatisch gespeichert und
        der Turn gilt als Erfolg statt als Hard-Delivery-Gate-Fehlschlag."""
        fake_text = (
            "Hier ist der fertige Code:\n\n"
            "# Dateipfad: app/main.py\n"
            "```python\n"
            "from fastapi import FastAPI\n\napp = FastAPI()\n\n\n@app.get('/health')\n"
            "def health():\n    return {'status': 'ok'}\n"
            "```"
        )
        agent = BackendAgent()
        agent._llm = _FixedTextLLM(fake_text)
        task = AgentTask(task_id="t1", agent_id="backend", description="Baue den Health-Endpoint",
                          project_dir=self.temp_dir, max_tool_iterations=3)

        with self.assertLogs("agents.base_agent", level="INFO") as log_ctx:
            result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success, result.error)
        self.assertIsNone(result.error)
        self.assertEqual(result.files_written, ["app/main.py"])
        saved_path = Path(self.temp_dir) / "app" / "main.py"
        self.assertTrue(saved_path.is_file())
        self.assertIn("FastAPI()", saved_path.read_text(encoding="utf-8"))
        self.assertTrue(
            any("[Auto-Recovery]" in msg and "app/main.py" in msg for msg in log_ctx.output),
            f"Erwartete [Auto-Recovery]-Protokollzeile fehlt in: {log_ctx.output}",
        )

    def test_unlabeled_html_document_is_saved_for_frontend_agent(self):
        """Der frontend-Agent liefert ein vollständiges HTML-Dokument OHNE jeden Dateipfad-Hinweis
        - core/workspace.py.extract_file_blocks() findet dafür nichts (kein Pfad-Anker), die
        frontend-spezifische Fallback-Heuristik in base_agent.py erkennt es trotzdem und
        speichert es als public/index.html."""
        fake_text = (
            "```html\n"
            "<!DOCTYPE html>\n<html>\n<head><title>Dashboard</title></head>\n"
            "<body><h1>Nexus Resilience Gateway</h1></body>\n</html>\n"
            "```"
        )
        agent = FrontendAgent()
        agent._llm = _FixedTextLLM(fake_text)
        task = AgentTask(task_id="t2", agent_id="frontend", description="Baue das Dashboard-UI",
                          project_dir=self.temp_dir, max_tool_iterations=3)

        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.files_written, ["public/index.html"])
        saved_path = Path(self.temp_dir) / "public" / "index.html"
        self.assertTrue(saved_path.is_file())
        self.assertIn("Nexus Resilience Gateway", saved_path.read_text(encoding="utf-8"))

    def test_unlabeled_html_document_uses_existing_static_dir_for_frontend_agent(self):
        """Existiert bereits ein `static/`-Verzeichnis im Projekt, wird dieses als Zielordner
        verwendet statt blind IMMER `public/` zu wählen."""
        (Path(self.temp_dir) / "static").mkdir()
        fake_text = "```html\n<!DOCTYPE html>\n<html><body>UI</body></html>\n```"
        agent = FrontendAgent()
        agent._llm = _FixedTextLLM(fake_text)
        task = AgentTask(task_id="t3", agent_id="frontend", description="Baue das UI",
                          project_dir=self.temp_dir, max_tool_iterations=3)

        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.files_written, ["static/index.html"])

    def test_no_extractable_block_still_fails_the_hard_delivery_gate(self):
        """Reiner Fließtext ohne jeden rettbaren Codeblock bleibt weiterhin ein echter
        Hard-Delivery-Gate-Fehlschlag - der Auto-Recovery-Parser erfindet keinen Code."""
        fake_text = "Ich habe die Anforderungen analysiert, aber noch keinen Code geschrieben."
        agent = BackendAgent()
        agent._llm = _FixedTextLLM(fake_text)
        task = AgentTask(task_id="t4", agent_id="backend", description="Baue den Endpoint",
                          project_dir=self.temp_dir, max_tool_iterations=3)

        result = asyncio.run(agent.execute(task))

        self.assertFalse(result.success)
        self.assertEqual(result.files_written, [])
        self.assertIn("Hard Delivery Gate", result.error or "")

    def test_write_file_dispatch_failure_is_logged_and_does_not_crash(self):
        """Ein per Auto-Recovery erkannter Block, den write_file selbst ablehnt (hier: kaputtes
        Python), darf den Lauf nicht abstürzen lassen - nur eine Warnung protokollieren, statt
        kaputten Code unbemerkt auf die Platte zu schreiben."""
        fake_text = (
            "# Dateipfad: app/broken.py\n"
            "```python\n"
            "def broken(:\n    this is not valid python\n"
            "```"
        )
        agent = BackendAgent()
        agent._llm = _FixedTextLLM(fake_text)
        task = AgentTask(task_id="t5", agent_id="backend", description="Baue etwas",
                          project_dir=self.temp_dir, max_tool_iterations=3)

        with self.assertLogs("agents.base_agent", level="WARNING") as log_ctx:
            result = asyncio.run(agent.execute(task))

        # Kein Absturz und KEINE kaputte Datei auf der Platte - aber auch kein harter
        # Fehlschlag: derselbe Codeblock bleibt für den orchestrator-weiten Text-Fallback
        # (AUTO_SAVE_WORKSPACE) theoretisch sichtbar, der ihn aus denselben Gründen ebenfalls
        # ablehnen würde (core/workspace.py.parse_and_save_files() prüft dieselbe Syntax).
        self.assertEqual(result.files_written, [])
        self.assertFalse((Path(self.temp_dir) / "app" / "broken.py").exists())
        self.assertTrue(
            any("[Auto-Recovery]" in msg and "app/broken.py" in msg for msg in log_ctx.output),
            f"Erwartete Ablehnungs-Protokollzeile fehlt in: {log_ctx.output}",
        )


if __name__ == "__main__":
    logging.getLogger("agents.base_agent").setLevel(logging.DEBUG)
    unittest.main()
