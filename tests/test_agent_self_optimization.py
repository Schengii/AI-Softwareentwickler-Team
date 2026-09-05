"""
tests/test_agent_self_optimization.py – Testet die Lern-Extraktion der Selbstoptimierung

Vorher wurden Lern-Regeln ausschließlich per fragilem Textmuster ("Betroffener Agent:"
gefolgt von Aufzählungspunkten) aus dem freien Trainer-Bericht extrahiert – hielt sich
das Modell nicht exakt an dieses Format, ging der Lerneffekt für den ganzen Lauf verloren.
Jetzt primär über einen maschinenlesbaren JSON-Block (robust gegen Formulierungs-
Abweichungen), mit dem alten Textmuster nur noch als Fallback. Jede agent_id wird gegen
die echten Agenten/Leads validiert, damit keine erfundene Rolle in der Wissensbasis landet.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agents.orchestrator import Orchestrator
from core.message_bus import AgentResult


class TestSelfOptimizationLearningExtraction(unittest.TestCase):
    def setUp(self):
        self.orchestrator = Orchestrator()
        self.temp_dir = tempfile.mkdtemp()
        self.kb_file = Path(self.temp_dir) / "agent_learnings.json"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _fresh_knowledge_base(self):
        from memory.agent_knowledge_base import AgentKnowledgeBase
        return AgentKnowledgeBase(file_path=self.kb_file)

    def test_structured_json_block_is_parsed_and_stored(self):
        report = '''## Report
Diverser Text...

```json
{"learnings": [{"agent_id": "backend", "rule": "Verwende immer async def fuer I/O-Endpunkte."}]}
```
'''
        kb = self._fresh_knowledge_base()
        with patch("memory.agent_knowledge_base.agent_knowledge_base", kb):
            self.orchestrator._extract_and_store_learnings(report)

        self.assertIn("Verwende immer async def fuer I/O-Endpunkte.", kb.get_learnings("backend"))

    def test_unknown_agent_id_in_json_is_rejected(self):
        report = '''```json
{"learnings": [{"agent_id": "voellig_erfundene_rolle", "rule": "Diese Regel darf niemals gespeichert werden."}]}
```
'''
        kb = self._fresh_knowledge_base()
        with patch("memory.agent_knowledge_base.agent_knowledge_base", kb):
            self.orchestrator._extract_and_store_learnings(report)

        self.assertEqual(kb.get_learnings("voellig_erfundene_rolle"), [])

    def test_malformed_json_falls_back_to_legacy_text_pattern(self):
        report = '''### 1. Schwachstellen
- **Betroffener Agent:** `database`
- **Vorgeschlagene Ergänzung:** "Lege bei jedem ForeignKey-Feld einen Index an."

```json
{dies ist kein gueltiges JSON}
```
'''
        kb = self._fresh_knowledge_base()
        with patch("memory.agent_knowledge_base.agent_knowledge_base", kb):
            self.orchestrator._extract_and_store_learnings(report)

        learnings = kb.get_learnings("database")
        self.assertTrue(any("ForeignKey" in learning for learning in learnings))

    def test_empty_learnings_array_stores_nothing(self):
        report = '```json\n{"learnings": []}\n```'
        kb = self._fresh_knowledge_base()
        with patch("memory.agent_knowledge_base.agent_knowledge_base", kb):
            self.orchestrator._extract_and_store_learnings(report)

        for agent_id in self.orchestrator._agents:
            self.assertEqual(kb.get_learnings(agent_id), [])

    def test_finds_real_learnings_block_past_an_earlier_unrelated_json_example(self):
        """
        Regressionstest für einen echten Fund aus einem echten Lauf: Der Trainer-Bericht
        illustriert seine Prompt-Diffs oft mit einem eigenen ```json-Beispiel-Snippet VOR dem
        eigentlichen Lern-Block am Ende. Ein "nimm den ersten ```json-Block"-Parser matcht dann
        das Beispiel (kein "learnings"-Schlüssel) und verwirft die echten Regeln lautlos.
        """
        report = '''### 2. Konkrete Prompt-Verbesserungen

Beispiel für einen Tool-Aufruf mit Begründung:
```json
{
  "name": "list_files",
  "arguments": {"path": "."},
  "thought_signature": "Ich pruefe den Bestand, bevor ich schreibe."
}
```

### 5. Maschinenlesbare Lern-Regeln
```json
{"learnings": [{"agent_id": "backend", "rule": "Schreibe nach maximal 2 Lese-Schritten eine erste Datei."}]}
```
'''
        kb = self._fresh_knowledge_base()
        with patch("memory.agent_knowledge_base.agent_knowledge_base", kb):
            self.orchestrator._extract_and_store_learnings(report)

        self.assertIn("Schreibe nach maximal 2 Lese-Schritten eine erste Datei.", kb.get_learnings("backend"))

    def test_verification_failure_triggers_self_optimization_despite_successful_agents(self):
        """
        Team-Optimierung (Retrospektive 2026-09-05, Punkt 4): AgentResult.success beschreibt nur
        den technischen Tool-Aufruf, nicht ob die echte Verifikation (Tests/Governance) am Ende
        durchging - vorher blieb die Selbstoptimierung deshalb stumm, wenn alle Agenten
        anstandslos, aber fachlich falschen Code lieferten (real beobachtet: workspace/
        zeiterfassung_app, drei Läufe mit identischem Testfehler, KEIN einziger AgentResult mit
        success=False). `verification_ok=False` muss die Selbstoptimierung jetzt AUCH ohne
        jeden Agenten-Fehler und ohne hohen Tokenverbrauch auslösen.
        """
        results = [
            AgentResult(task_id="t1", agent_id="backend", agent_name="Backend", success=True,
                        content="Fertig.", total_tokens=100),
        ]
        mock_execute = AsyncMock(return_value=AgentResult(
            task_id="trainer_auto_opt", agent_id="agent_trainer", agent_name="Agent Trainer",
            success=True, content='```json\n{"learnings": []}\n```',
        ))
        with patch.object(self.orchestrator._agents["agent_trainer"], "execute", mock_execute):
            trainer_result = asyncio.run(self.orchestrator._run_agent_trainer_self_optimization(
                user_request="Baue etwas", results=results, retro_content="",
                verification_ok=False, verification_summary="### Testfehler\n- DTZ001 in tests/test_invoices.py",
            ))

        mock_execute.assert_called_once()
        self.assertIsNotNone(trainer_result)
        # Die echte Verifikations-Zusammenfassung muss dem Trainer als Kontext mitgegeben
        # werden - sonst kann er die Grundursache nicht diagnostizieren, sondern rät nur aus
        # den (hier fehlerfreien) Agenten-Metadaten.
        sent_task = mock_execute.call_args.args[0]
        self.assertIn("DTZ001", sent_task.context)

    def test_successful_run_without_high_usage_skips_self_optimization(self):
        """Gegenprobe: verification_ok=True (Standardwert) und keine Fehler/hoher Tokenverbrauch
        - die Selbstoptimierung darf weiterhin NICHT für jeden grünen Lauf laufen (Kosten)."""
        results = [
            AgentResult(task_id="t1", agent_id="backend", agent_name="Backend", success=True,
                        content="Fertig.", total_tokens=100),
        ]
        mock_execute = AsyncMock()
        with patch.object(self.orchestrator._agents["agent_trainer"], "execute", mock_execute):
            trainer_result = asyncio.run(self.orchestrator._run_agent_trainer_self_optimization(
                user_request="Baue etwas", results=results, retro_content="",
            ))

        mock_execute.assert_not_called()
        self.assertIsNone(trainer_result)

    def test_department_lead_is_a_valid_learning_target(self):
        report = '''```json
{"learnings": [{"agent_id": "dev_lead", "rule": "Fasse Delegationsanweisungen kuerzer, um Tool-Iterationen zu sparen."}]}
```
'''
        kb = self._fresh_knowledge_base()
        with patch("memory.agent_knowledge_base.agent_knowledge_base", kb):
            self.orchestrator._extract_and_store_learnings(report)

        self.assertTrue(kb.get_learnings("dev_lead"))


if __name__ == "__main__":
    unittest.main()
