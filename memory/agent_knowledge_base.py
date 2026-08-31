"""
memory/agent_knowledge_base.py – Persistente Wissensbasis & Prompt-Optimierung für Agenten

Speichert:
- Best Practices & gelernte Regeln pro Agent
- Automatisch angeeignete Guardrails aus vorangegangenen Projekt-Läufen
- Permanente Selbstoptimierung: Schärft System-Prompts bei jeder Iteration
"""

import json
from pathlib import Path

from config import BASE_DIR

KNOWLEDGE_FILE = Path(BASE_DIR) / "memory" / "agent_learnings.json"

# Jede gespeicherte Regel wird bei JEDEM künftigen Aufruf des betroffenen Agenten in dessen
# System-Prompt eingefügt (siehe get_augmented_prompt) - für immer, bis sie verdrängt wird.
# Eine einzelne, unbegrenzt lange "Regel" (der Trainer-Agent liefert Freitext, kein garantiert
# kurzes Format) würde diesen Tokenverbrauch bei jedem künftigen Lauf unbemerkt wiederholen -
# deshalb hart gedeckelt statt nur auf die Anzahl der Regeln.
MAX_RULE_LENGTH = 300

# Realer Fund: ein reiner Zähler-Cap (früher: fix 5 Regeln pro Agent, älteste zuerst verdrängt)
# wirft eine wertvolle, spezifische Lektion (z.B. "StaticPool bei In-Memory-SQLite") genauso
# schnell raus wie eine generische Stil-Regel, sobald der 6. Eintrag hinzukommt - unabhängig
# davon, wie kurz/lang die einzelnen Regeln sind. Ein kombiniertes Budget aus Anzahl UND
# Gesamtzeichenlänge lässt mehr KURZE, spezifische Lektionen gleichzeitig bestehen, ohne den
# Tokenverbrauch im System-Prompt unbegrenzt wachsen zu lassen - dieselbe Deckelungs-Idee wie
# MAX_RULE_LENGTH, nur über alle Regeln eines Agenten hinweg statt pro einzelner Regel.
MAX_RULES_PER_AGENT = 10
MAX_TOTAL_LEARNING_CHARS_PER_AGENT = 1500


class AgentKnowledgeBase:
    """
    Verwaltet das persistente Langzeitgedächtnis und gelernte Regeln für alle Agenten.
    """

    def __init__(self, file_path: Path | None = None):
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
        if len(clean_rule) > MAX_RULE_LENGTH:
            # An der letzten Wortgrenze kürzen statt hart mitten im Wort abzuschneiden
            # (gleiches Prinzip wie interface/cli.py._truncate_at_word).
            cut = clean_rule[:MAX_RULE_LENGTH]
            last_space = cut.rfind(" ")
            clean_rule = (cut[:last_space] if last_space > 0 else cut).rstrip() + "…"

        if agent_id not in self._learnings:
            self._learnings[agent_id] = []

        if clean_rule not in self._learnings[agent_id]:
            self._learnings[agent_id].append(clean_rule)
            # Verdränge älteste Regeln zuerst, bis BEIDE Budgets eingehalten sind (Anzahl UND
            # Gesamtzeichenlänge, siehe MAX_RULES_PER_AGENT/MAX_TOTAL_LEARNING_CHARS_PER_AGENT) -
            # kurze, spezifische Lektionen kommen so seltener zu früh raus als beim alten reinen
            # Zähler-Cap.
            rules = self._learnings[agent_id]
            while len(rules) > MAX_RULES_PER_AGENT or sum(len(r) for r in rules) > MAX_TOTAL_LEARNING_CHARS_PER_AGENT:
                if len(rules) <= 1:
                    break
                rules.pop(0)
            self._save()

    def get_learnings(self, agent_id: str) -> list[str]:
        """Gibt alle gelernten Regeln für einen Agenten zurück."""
        return self._learnings.get(agent_id, [])

    def get_all_learnings(self) -> dict[str, list[str]]:
        """Gibt eine Kopie ALLER gespeicherten Learnings zurück (agent_id -> Regeln) – für
        Anzeige-/Audit-Zwecke, z. B. den /learnings-CLI-Befehl. Kopie statt Referenz, damit
        der Aufrufer die interne Struktur nicht versehentlich mutieren kann."""
        return {agent_id: list(rules) for agent_id, rules in self._learnings.items()}

    def remove_learning(self, agent_id: str, rule_index: int) -> str | None:
        """
        Entfernt eine einzelne gelernte Regel anhand ihres 1-basierten Index (wie im
        /learnings-CLI-Befehl angezeigt). Gibt den entfernten Regeltext zurück, oder None bei
        unbekanntem agent_id/ungültigem Index (kein Fehler).

        Realer Bedarf: der agent_trainer analysiert Läufe automatisch per LLM-Aufruf - eine
        einzelne falsche oder inzwischen überholte Regel würde sonst erst nach 5 neueren
        Regeln automatisch verdrängt (siehe add_learning) und bis dahin bei JEDEM Aufruf
        dieses Agenten den System-Prompt verzerren. Der Mensch muss das gezielt korrigieren
        können, statt darauf zu warten.
        """
        rules = self._learnings.get(agent_id)
        if not rules or not (1 <= rule_index <= len(rules)):
            return None
        removed = rules.pop(rule_index - 1)
        if not rules:
            del self._learnings[agent_id]
        self._save()
        return removed

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
