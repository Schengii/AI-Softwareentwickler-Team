"""
tests/test_agent_self_optimization.py – Testet die Lern-Extraktion der Selbstoptimierung

Vorher wurden Lern-Regeln ausschließlich per fragilem Textmuster ("Betroffener Agent:"
gefolgt von Aufzählungspunkten) aus dem freien Trainer-Bericht extrahiert – hielt sich
das Modell nicht exakt an dieses Format, ging der Lerneffekt für den ganzen Lauf verloren.
Jetzt primär über einen maschinenlesbaren JSON-Block (robust gegen Formulierungs-
Abweichungen), mit dem alten Textmuster nur noch als Fallback. Jede agent_id wird gegen
die echten Agenten/Leads validiert, damit keine erfundene Rolle in der Wissensbasis landet.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.orchestrator import Orchestrator


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
