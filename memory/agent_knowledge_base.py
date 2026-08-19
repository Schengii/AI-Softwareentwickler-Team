"""
memory/agent_knowledge_base.py – Persistente Wissensbasis & Prompt-Optimierung für Agenten

Speichert:
- Best Practices & gelernte Regeln pro Agent
- Automatisch angeeignete Guardrails aus vorangegangenen Projekt-Läufen
- Permanente Selbstoptimierung: Schärft System-Prompts bei jeder Iteration
"""

import json
from pathlib import Path
from typing import Optional
from config import BASE_DIR


KNOWLEDGE_FILE = Path(BASE_DIR) / "memory" / "agent_learnings.json"


class AgentKnowledgeBase:
    """
    Verwaltet das persistente Langzeitgedächtnis und gelernte Regeln für alle Agenten.
    """

    def __init__(self, file_path: Optional[Path] = None):
        self.file_path = file_path or KNOWLEDGE_FILE
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._learnings: dict[str, list[str]] = self._load()

    def _load(self) -> dict[str, list[str]]:
        if self.file_path.exists():
            try:
                return json.loads(self.file_path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save(self) -> None:
        try:
            self.file_path.write_text(
                json.dumps(self._learnings, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def add_learning(self, agent_id: str, rule_or_tip: str) -> None:
        """Fügt ein neues Learning/Guardrail für einen Agenten hinzu."""
        clean_rule = rule_or_tip.strip()
        if not clean_rule:
            return

        if agent_id not in self._learnings:
            self._learnings[agent_id] = []

        if clean_rule not in self._learnings[agent_id]:
            self._learnings[agent_id].append(clean_rule)
            # Begrenze auf maximal 5 der wichtigsten gelernten Regeln pro Agent
            if len(self._learnings[agent_id]) > 5:
                self._learnings[agent_id] = self._learnings[agent_id][-5:]
            self._save()

    def get_learnings(self, agent_id: str) -> list[str]:
        """Gibt alle gelernten Regeln für einen Agenten zurück."""
        return self._learnings.get(agent_id, [])

    def get_augmented_prompt(self, agent_id: str, base_system_prompt: str) -> str:
        """Reichert den System-Prompt eines Agenten mit seinen gelernten Regeln an."""
        learnings = self.get_learnings(agent_id)
        if not learnings:
            return base_system_prompt

        learnings_text = "\n".join([f"- {rule}" for rule in learnings])
        augmented = f"""{base_system_prompt}

## 🧠 GELERNTE BEST PRACTICES & ERKENNTNISSE AUS FRÜHEREN PROJEKTEN:
{learnings_text}
Achte strikt auf die Einhaltung dieser zuvor gelernten Regeln!"""
        return augmented


# Globale Instanz
agent_knowledge_base = AgentKnowledgeBase()
