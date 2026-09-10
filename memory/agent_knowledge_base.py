"""
memory/agent_knowledge_base.py – Persistente Wissensbasis & Prompt-Optimierung für Agenten

Speichert:
- Best Practices & gelernte Regeln pro Agent
- Automatisch angeeignete Guardrails aus vorangegangenen Projekt-Läufen
- Permanente Selbstoptimierung: Schärft System-Prompts bei jeder Iteration
"""

import json
import re
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

# Team-Optimierung (ki_team_analyse_und_optimierungen.md, Punkt 5): der bisherige Dedup-Check in
# add_learning() verglich nur auf EXAKTE String-Gleichheit ("clean_rule not in self._learnings[...]").
# Realer Fund: memory/agent_learnings.json enthielt beim backend-Agenten drei semantisch identische
# Regeln zum selben Thema ("Jeder neue Import muss sofort in requirements.txt nachgetragen werden.",
# "Jeder neue Import muss zwingend gegen die requirements.txt geprüft ... werden.", "Jeder neue Import
# muss vor dem Commit in die requirements.txt eingetragen werden. ...") - unterschiedlicher Wortlaut,
# gleiche Aussage. Jede belegte unnötig ein Zehntel des MAX_RULES_PER_AGENT-Slots und einen Teil des
# MAX_TOTAL_LEARNING_CHARS_PER_AGENT-Budgets, das dadurch für tatsächlich NEUE Erkenntnisse fehlte.
# Jaccard-Ähnlichkeit der (kleingeschriebenen, satzzeichenbereinigten) Wortmengen ist bewusst simpel
# gewählt statt eines Embedding-Vergleichs: kein zusätzlicher API-Aufruf/keine Latenz beim Speichern
# eines Learnings, funktioniert rein lokal, und die Learnings sind kurze, thematisch enge Sätze, bei
# denen Wortüberlappung ein guter Proxy für semantische Nähe ist.
_SIMILARITY_DEDUP_THRESHOLD = 0.6
_WORD_RE = re.compile(r"[a-zA-ZäöüÄÖÜß0-9_]+")


def _word_set(text: str) -> set[str]:
    """Kleingeschriebene Wortmenge eines Regeltexts, Satzzeichen ignoriert - Grundlage der
    Jaccard-Ähnlichkeit in _is_semantic_duplicate() unten."""
    return {w.lower() for w in _WORD_RE.findall(text)}


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Jaccard-Index zweier Wortmengen: |Schnittmenge| / |Vereinigungsmenge|, 0.0 bei zwei leeren
    Mengen (kein Wort in beiden Sätzen zu vergleichen - gilt bewusst NICHT als Duplikat)."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# Team-Optimierung (KI-Team-Masterplan, Stufe 3): Die Verdrängung bei vollem Budget arbeitete
# rein nach FIFO (`rules.pop(0)`). Realer Fund: 7 der 19 Agenten mit Learnings standen exakt am
# Limit MAX_RULES_PER_AGENT (architect, dev_lead, governance_lead, code_reviewer, qa_lead,
# frontend, security - je 10/10). Bei ihnen verdrängte JEDE neue Regel die jeweils älteste,
# unabhängig von deren Wert. Eine bewährte, sehr konkrete Regel ("Nutze StaticPool bei
# In-Memory-SQLite") konnte so von einer beliebig generischen ("Achte auf saubere Fehler-
# behandlung") verdrängt werden - das Gedächtnis verlor also mit der Zeit gerade seine
# nützlichsten Einträge.
#
# Eine echte Wirksamkeitsmessung (zählen, ob der zugehörige Fehler seit Einführung der Regel
# ausblieb) würde ein anderes Speicherformat erfordern - memory/agent_learnings.json ist eine
# schlichte dict[str, list[str]]-Struktur ohne Metadaten. Als lokal berechenbarer, migrationsfreier
# Ersatz dient die SPEZIFITÄT: Regeln, die konkrete, überprüfbare Anker enthalten (Codebezeichner,
# Dateinamen, Fehlerklassen, Zahlen), sind erfahrungsgemäß handlungsleitender als allgemeine
# Ermahnungen. Verdrängt wird deshalb die generischste Regel - bei Gleichstand weiterhin die
# älteste (stabiles, nachvollziehbares Verhalten).
_CODE_MARKER_RE = re.compile(
    r"`[^`]+`"                 # in Backticks gesetzter Code/Bezeichner
    r"|\b\w+\.(?:py|json|txt|toml|ini|yaml|yml|tsx?|jsx?)\b"  # konkrete Dateinamen
    r"|\b\w+_\w+\b"            # snake_case-Bezeichner
    r"|\b[a-z]+[A-Z]\w*\b"     # camelCase-Bezeichner
    r"|\b[A-Z][a-z]+[A-Z]\w*\b"  # CamelCase-Klassennamen
    r"|\b\w+\(\)"              # Funktionsaufrufe
    r"|\b\w*(?:Error|Exception|Warning)\b"  # Fehlerklassen
    r"|\b\d+\b"                # konkrete Zahlen/Schwellenwerte
)


def _specificity_score(rule: str) -> int:
    """
    Grobes Maß dafür, wie konkret und damit handlungsleitend eine Regel ist: die Anzahl
    überprüfbarer Anker (Codebezeichner, Dateinamen, Fehlerklassen, Zahlen) im Text.

    Bewusst eine reine Zählung ohne Normierung auf die Länge: Eine lange Regel mit vielen
    konkreten Ankern IST wertvoller als eine kurze ohne. Das Zeichenbudget begrenzt die Länge
    ohnehin bereits an anderer Stelle (MAX_TOTAL_LEARNING_CHARS_PER_AGENT).
    """
    return len(_CODE_MARKER_RE.findall(rule or ""))


def _evict_least_valuable(rules: list[str]) -> None:
    """
    Entfernt genau eine Regel: die mit der geringsten Spezifität, bei Gleichstand die älteste
    (kleinster Index). Arbeitet in-place, damit die Liste im Aufrufer dieselbe bleibt.
    """
    if len(rules) <= 1:
        return
    # min() ist stabil: Bei gleichem Score gewinnt der zuerst gefundene, also der älteste Eintrag.
    index = min(range(len(rules)), key=lambda i: _specificity_score(rules[i]))
    rules.pop(index)


# Qualitäts-Gate (Analyse 2026-09-10, Fund am auditlog_sentinel-Lauf): memory/agent_learnings.json
# enthielt Regeln wie "Bei 429-Fehlern: Umschalten auf High-Level-Compliance-Check ohne
# detaillierte Code-Analyse.", "nutze gpt-3.5-turbo als Fallback." oder "Signalisiere bei
# API-429-Fehlern sofort <fallback_request> zur Modell-Rotation." - reine Infrastruktur-
# Workarounds, keine Code-Lektionen. Ein einzelner Agent sieht in seinem Prompt nie den rohen
# HTTP-Statuscode eines gescheiterten LLM-Aufrufs (das behandelt core/llm_factory.py/
# core/token_guard.py/core/provider_exhaustion.py bereits zentral, VOR dem Agenten) - eine
# solche "gelernte" Regel ist bestenfalls wirkungslos, schlimmstenfalls schädlich (z.B. security
# angewiesen, "ohne detaillierte Code-Analyse" zu prüfen). Setzt zwei UNABHÄNGIGE Marker voraus
# (Fehler-/Kontingent-Indikator UND eine Reaktions-Formulierung auf den eigenen LLM-Aufruf), damit
# eine legitime fachliche Regel über HTTP-429-Verhalten der zu bauenden APPLIKATION selbst (z.B.
# "Backend soll bei Ratenlimit-Überschreitung 429 zurückgeben") nicht fälschlich verworfen wird.
_INFRA_ERROR_MARKER_RE = re.compile(
    r"\b(429|503|413)\b|rate.?limit|kontingent|provider-(ausfall|fehler)|api-fehler",
    re.IGNORECASE,
)
_INFRA_REACTION_MARKER_RE = re.compile(
    r"fallback|modell-?rotation|backoff|governance\s*lead|eskalation|checkpoint|credit|"
    r"token-limit|reasoning-chain|umschalt",
    re.IGNORECASE,
)
# Fremdmodelle, die in DIESEM Framework nirgends konfiguriert sind (siehe config.py.AGENT_MODELS/
# MODEL_FALLBACKS) - eine Regel, die ein Agent zur Nutzung anweist, kann nie wirken und verrät,
# dass sie aus generischem Trainingswissen stammt statt aus einer echten Beobachtung an DIESEM Team.
_FOREIGN_MODEL_RE = re.compile(r"\bgpt-3\.5-turbo\b|\bgpt-4o?\b", re.IGNORECASE)


def _is_infrastructure_workaround(rule: str) -> bool:
    """True für eine Regel, die tatsächlich einen Provider-/Kontingent-Workaround statt einer
    Code-/Architektur-Lektion beschreibt - siehe Modul-Docstring oben."""
    if _FOREIGN_MODEL_RE.search(rule):
        return True
    return bool(_INFRA_ERROR_MARKER_RE.search(rule) and _INFRA_REACTION_MARKER_RE.search(rule))


def _is_semantic_duplicate(new_rule: str, existing_rules: list[str]) -> bool:
    """True, wenn `new_rule` einer bereits gespeicherten Regel semantisch stark ähnelt (Jaccard-
    Ähnlichkeit der Wortmengen >= _SIMILARITY_DEDUP_THRESHOLD) - verhindert Fast-Dubletten wie die
    drei "Import in requirements.txt nachtragen"-Varianten im Docstring oben, die exakter
    String-Vergleich nicht erkennt."""
    new_words = _word_set(new_rule)
    return any(_jaccard_similarity(new_words, _word_set(existing)) >= _SIMILARITY_DEDUP_THRESHOLD for existing in existing_rules)


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
        if _is_infrastructure_workaround(clean_rule):
            return
        if len(clean_rule) > MAX_RULE_LENGTH:
            # An der letzten Wortgrenze kürzen statt hart mitten im Wort abzuschneiden
            # (gleiches Prinzip wie interface/cli.py._truncate_at_word).
            cut = clean_rule[:MAX_RULE_LENGTH]
            last_space = cut.rfind(" ")
            clean_rule = (cut[:last_space] if last_space > 0 else cut).rstrip() + "…"

        if agent_id not in self._learnings:
            self._learnings[agent_id] = []

        if clean_rule not in self._learnings[agent_id] and not _is_semantic_duplicate(
            clean_rule, self._learnings[agent_id]
        ):
            self._learnings[agent_id].append(clean_rule)
            # Verdränge die jeweils GENERISCHSTE Regel (bei Gleichstand die älteste), bis BEIDE
            # Budgets eingehalten sind (Anzahl UND Gesamtzeichenlänge, siehe
            # MAX_RULES_PER_AGENT/MAX_TOTAL_LEARNING_CHARS_PER_AGENT). Zuvor wurde rein nach FIFO
            # verdrängt, wodurch bei den 7 Agenten am Limit jede neue - auch jede belanglose -
            # Regel die älteste und oft konkreteste Lektion herausdrängte (siehe
            # _specificity_score() oben für die vollständige Herleitung).
            rules = self._learnings[agent_id]
            while len(rules) > MAX_RULES_PER_AGENT or sum(len(r) for r in rules) > MAX_TOTAL_LEARNING_CHARS_PER_AGENT:
                if len(rules) <= 1:
                    break
                _evict_least_valuable(rules)
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
