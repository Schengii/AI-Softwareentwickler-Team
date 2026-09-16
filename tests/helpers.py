"""
tests/helpers.py – Gemeinsame Test-Doppel der Framework-Testsuite

Enthält LLM-Attrappen, die mehrere Testmodule identisch brauchen. Hintergrund: Die Klasse
`ScriptedWriteFileLLM` lag zuvor fünfmal wortgleich in den Testdateien
`test_governance_fix_loop.py`, `test_governance_no_progress_breaker.py`,
`test_preflight_check_fix_loop.py`, `test_preimport_check.py` und
`test_verification_no_progress_breaker.py`; deren Docstrings verwiesen bereits gegenseitig mit
"dieselbe Konvention wie in ..." aufeinander. Eine Änderung am erwarteten Werkzeug-Protokoll
(z.B. ein zusätzliches Argument an `generate_with_tools()`) musste deshalb an fünf Stellen
nachgezogen werden. Neue Attrappen gehören hierher, sobald sie ein zweites Modul braucht.
"""

from core.llm_factory import LLMResponse, ToolCall


class ScriptedWriteFileLLM:
    """
    Ruft beim ERSTEN `generate_with_tools()`-Aufruf `write_file` auf (falls `written_file`
    gesetzt ist) und liefert ab dem zweiten Aufruf `text` als finale Antwort – simuliert das
    realistische "erst Werkzeug, dann Zusammenfassung"-Muster statt denselben Tool-Call endlos
    zu wiederholen.

    Der Schreibvorgang macht zugleich `file_owners` für `written_file` bekannt. Das ist nötig,
    damit die Fix-Schleifen einen Befund (Governance-Fund, Vorab-Import-Check, Traceback)
    überhaupt einem zuständigen Agenten zuordnen können.
    """

    def __init__(self, text: str = "Fertig.", written_file: str | None = None):
        self._text = text
        self._written_file = written_file
        self._call_count = 0
        self.model_name = "fake-model"

    async def generate_with_tools(self, messages, system_prompt, tools, _allow_self_fallback=True):
        self._call_count += 1
        tool_calls = []
        if self._written_file and self._call_count == 1:
            tool_calls = [ToolCall(id="call_1", name="write_file",
                                   arguments={"path": self._written_file, "content": "# fix\n"})]
        text = "" if tool_calls else self._text
        return LLMResponse(
            text=text, model_name=self.model_name,
            prompt_tokens=10, completion_tokens=5, total_tokens=15, tool_calls=tool_calls,
        )

    async def generate_with_usage(self, prompt, system_prompt=None):
        return LLMResponse(
            text=self._text, model_name=self.model_name,
            prompt_tokens=10, completion_tokens=5, total_tokens=15,
        )
