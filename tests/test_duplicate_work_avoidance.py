"""
tests/test_duplicate_work_avoidance.py – Testet die proaktive Dateibaum-Injektion im Tool-Loop

Realer Fund aus einem echten Lauf: Für eine triviale Aufgabe ("Health-Check-Endpoint")
entstanden ZWEI parallele, redundante Implementierungen (app.py/test_app.py UND separat
main.py/test_main.py), weil ein Agent nicht von sich aus list_files aufgerufen hat, bevor
er zu schreiben begann. agents/base_agent.py._run_agentic_loop() stellt den aktuellen
Dateibaum seitdem OHNE Zutun des Modells dem ersten Prompt voran.

Diese Tests stellen sicher, dass:
1. Bereits vorhandene Dateien im ersten Prompt an das Modell auftauchen.
2. Diese harness-seitige Abfrage NICHT in tool_calls_count/call_log auftaucht (sonst
   verfälscht sie die "Werkzeug-Aufrufe"-Kennzahl im Abschlussbericht).
3. Ein leeres Projektverzeichnis den Prompt nicht mit einem leeren Abschnitt aufbläht.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path

from agents.backend_agent import BackendAgent
from core.llm_factory import LLMResponse
from core.message_bus import AgentTask


class _CapturingFakeLLM:
    """Merkt sich den ersten an sie gesendeten Prompt-Text und antwortet sofort final."""

    def __init__(self):
        self.model_name = "fake-model"
        self.first_prompt_text: str | None = None

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        if self.first_prompt_text is None:
            self.first_prompt_text = messages[0].text
        return LLMResponse(
            text="Fertig.", model_name=self.model_name,
            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=[],
        )


class TestExistingFilesInjectedIntoPrompt(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_existing_file_is_mentioned_in_first_prompt(self):
        (Path(self.temp_dir) / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()", encoding="utf-8")

        agent = BackendAgent()
        fake_llm = _CapturingFakeLLM()
        agent._llm = fake_llm

        # tools_read_only=True: dieser Test prüft ausschließlich die Prompt-Injektion des
        # Dateibaums, keine tatsächliche Datei-Lieferung - der Fake-LLM oben antwortet immer
        # sofort mit reinem Text ohne write_file-Aufruf. Ohne das würde das Hard Delivery Gate
        # (agents/base_agent.py, seit der pulseflow_gateway-Härtung unabhängig von einem
        # Code-Fence im Text) das als Ghost-Code werten.
        task = AgentTask(task_id="t1", agent_id="backend", description="Schreibe Tests für den Health-Check",
                          project_dir=self.temp_dir, tools_read_only=True)
        result = asyncio.run(agent.execute(task))

        self.assertTrue(result.success)
        assert fake_llm.first_prompt_text is not None
        self.assertIn("main.py", fake_llm.first_prompt_text)
        self.assertIn("BEREITS VORHANDENE DATEIEN", fake_llm.first_prompt_text)
        # Die harness-seitige Abfrage darf NICHT als Werkzeug-Aufruf des Agenten gezählt werden.
        self.assertEqual(result.tool_calls_count, 0)

    def test_empty_project_dir_does_not_add_empty_section(self):
        agent = BackendAgent()
        fake_llm = _CapturingFakeLLM()
        agent._llm = fake_llm

        task = AgentTask(task_id="t2", agent_id="backend", description="Neues Projekt starten", project_dir=self.temp_dir)
        asyncio.run(agent.execute(task))

        assert fake_llm.first_prompt_text is not None
        self.assertNotIn("BEREITS VORHANDENE DATEIEN", fake_llm.first_prompt_text)


if __name__ == "__main__":
    unittest.main()
