"""
memory/agent_knowledge_base.py – Persistente Wissensbasis & Prompt-Optimierung für Agenten

Speichert:
- Best Practices & gelernte Regeln pro Agent
- Automatisch angeeignete Guardrails aus vorangegangenen Projekt-Läufen
- Permanente Selbstoptimierung: Schärft System-Prompts bei jeder Iteration
"""

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from config import BASE_DIR

KNOWLEDGE_FILE = Path(BASE_DIR) / "memory" / "agent_learnings.json"

# P2-1 (ROADMAP_TEMP.md): Wirksamkeitsmessung statt der reinen Spezifitäts-Heuristik. Eine Regel
# gilt erst ab dieser Anzahl an Prompt-Injektionen als statistisch aussagekräftig genug, um ihre
# gemessene Wirksamkeit (violations_after / injections) für die Verdrängung heranzuziehen - bei
# weniger Injektionen entscheidet weiterhin die Spezifitäts-Heuristik (_specificity_score/
# _evict_least_valuable), weil ein einzelner Zufallstreffer sonst eine junge, potenziell sehr
# wertvolle Regel sofort disqualifizieren würde.
MIN_INJECTIONS_FOR_EFFECTIVENESS = 5

# Ab dieser Injektionszahl mit mindestens einer erneuten Verletzung danach gilt eine Regel als
# wirkungslos genug, um automatisch gemeldet zu werden (siehe AgentKnowledgeBase._report_ineffective_rule) -
# derselbe Schwellenwert, den der agent_trainer-Prompt bereits für "Prompt-Regel wirkt nicht,
# deterministischer Check nötig" beschreibt (agents/agent_trainer_agent.py, Abschnitt "WICHTIGE
# Grenze von Punkt 1").
INEFFECTIVE_INJECTION_THRESHOLD = 20

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


def _effectiveness_rate(entry: dict) -> float | None:
    """
    Anteil der Prompt-Injektionen einer Regel, nach denen ihr `trigger_signature` TROTZDEM
    erneut auftrat (`violations_after / injections`) - None, wenn noch zu wenige Injektionen
    vorliegen (siehe MIN_INJECTIONS_FOR_EFFECTIVENESS), um daraus verlässlich etwas abzuleiten.
    Niedriger ist besser: 0.0 heißt, die Regel wurde injiziert und der Fehler blieb seitdem aus.
    """
    injections = entry.get("injections", 0)
    if injections < MIN_INJECTIONS_FOR_EFFECTIVENESS:
        return None
    return entry.get("violations_after", 0) / injections


def _evict_least_valuable_entry(entries: list[dict]) -> None:
    """
    Wie _evict_least_valuable() oben, aber für die neuen Metadaten-Einträge (P2-1): Liegen für
    mindestens eine Regel genug Injektionen vor, um ihre gemessene Wirksamkeit zu kennen, fliegt
    unter DIESEN die Regel mit der schlechtesten (höchsten) Verletzungsrate - eine nachweislich
    wirkungslose Regel wird so gezielter entfernt als über die reine Text-Heuristik. Liegen noch
    keine ausreichend gemessenen Regeln vor, fällt die Funktion auf die bestehende
    Spezifitäts-Heuristik zurück (_specificity_score über den Regeltext).
    """
    if len(entries) <= 1:
        return
    measured = [i for i, e in enumerate(entries) if _effectiveness_rate(e) is not None]
    if measured:
        # max() ist stabil: Bei gleicher (schlechtester) Rate gewinnt der zuerst gefundene,
        # also der älteste Eintrag - dieselbe Tiebreak-Konvention wie beim Text-Fallback unten.
        index = max(measured, key=lambda i: _effectiveness_rate(entries[i]))
    else:
        index = min(range(len(entries)), key=lambda i: _specificity_score(entries[i].get("rule", "")))
    entries.pop(index)


def _new_learning_entry(
    rule: str, *, trigger_signature: str | None, source_project: str | None
) -> dict:
    """Erzeugt einen neuen Learning-Eintrag im P2-1-Schema mit leerem Wirksamkeits-Zähler."""
    return {
        "rule": rule,
        "created_at": datetime.now(UTC).isoformat(),
        "source_project": source_project,
        "trigger_signature": trigger_signature,
        "injections": 0,
        "violations_before": 0,
        "violations_after": 0,
    }


def _normalize_entry(item: object) -> dict:
    """
    Abwärtskompatibler Loader (P2-1): memory/agent_learnings.json enthielt bisher pro Agent eine
    schlichte `list[str]`. Ein Alteintrag (reiner String) wird beim Laden transparent in das neue
    Metadaten-Schema gehoben (Regeltext + leere Zähler) - die vorhandenen Regeln gehen dadurch
    nicht verloren, sammeln ab jetzt aber Wirksamkeitsdaten. Ein bereits migrierter Eintrag (dict)
    wird um fehlende Schlüssel ergänzt, falls eine ältere Programmversion ihn unvollständig
    geschrieben hat.
    """
    if isinstance(item, str):
        return _new_learning_entry(item, trigger_signature=None, source_project=None)
    if isinstance(item, dict) and isinstance(item.get("rule"), str):
        entry = _new_learning_entry(item.get("rule", ""), trigger_signature=item.get("trigger_signature"), source_project=item.get("source_project"))
        entry.update(item)
        return entry
    return _new_learning_entry(str(item), trigger_signature=None, source_project=None)


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


# Themen, zu denen Umformulierungen dieselbe Aussage treffen, ohne genug Wörter zu teilen.
# Analyse 2026-09-15: der frontend-Agent hatte 6 von 10 Regeln zu "Code per write_file statt im Chat"
# und scheiterte trotzdem weiter - eine siebte Regel hilft nicht, sie verdrängt nur nützliche Regeln.
# Eine Wiederholung wird deshalb als Team-Lektion "learning_saturated" gemeldet (Framework-Fix nötig).
_RULE_TOPICS: dict[str, tuple[re.Pattern[str], ...]] = {
    "code_via_tools": (
        re.compile(r"write_file|edit_file|physisch", re.IGNORECASE),
        re.compile(r"chat|\btext\b|markdown|textantwort|ausgeben|ausgabe", re.IGNORECASE),
    ),
    "pyjwt_package": (
        re.compile(r"\bjwt\b", re.IGNORECASE),
        re.compile(r"pyjwt", re.IGNORECASE),
    ),
    "pytest_asyncio": (
        re.compile(r"pytest-asyncio|pytest_asyncio", re.IGNORECASE),
        re.compile(r"async", re.IGNORECASE),
    ),
}


def rule_topic(rule: str) -> str | None:
    """Thema einer Regel aus _RULE_TOPICS (alle Muster müssen passen) oder None."""
    for topic, patterns in _RULE_TOPICS.items():
        if all(p.search(rule) for p in patterns):
            return topic
    return None


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
        # P2-1: intern immer das Metadaten-Schema (list[dict]), unabhängig vom Format der Datei
        # auf der Platte (siehe _normalize_entry) - Konsumenten außerhalb dieser Klasse sehen
        # weiterhin reine Regeltexte (get_learnings/get_all_learnings), Details liefert
        # get_learning_details().
        self._learnings: dict[str, list[dict]] = self._load()

    def _load(self) -> dict[str, list[dict]]:
        if not self.file_path.exists():
            return {}
        try:
            raw = json.loads(self.file_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return {agent_id: [_normalize_entry(item) for item in items] for agent_id, items in raw.items()}

    def _save(self) -> None:
        try:
            self.file_path.write_text(
                json.dumps(self._learnings, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def add_learning(
        self,
        agent_id: str,
        rule_or_tip: str,
        *,
        trigger_signature: str | None = None,
        source_project: str | None = None,
    ) -> None:
        """
        Fügt ein neues Learning/Guardrail für einen Agenten hinzu.

        `trigger_signature` (P2-1, ROADMAP_TEMP.md) identifiziert den auslösenden Befund
        (z. B. eine Ruff-Regel-ID oder ein Fehlerbild wie `import_name_error:<modul>.<symbol>`).
        Tritt dieselbe Signatur erneut auf, während für sie bereits eine Regel existiert, wird
        KEINE Dublette angelegt - stattdessen zählt das als gemessene Verletzung NACH Einführung
        der Regel (`violations_after`), die Grundlage der Wirksamkeitsmessung (siehe
        _effectiveness_rate). Aufrufer ohne bekannte Signatur (z. B. LLM-Retrospektiven) lassen
        das Argument weg - für sie verhält sich die Methode wie zuvor.
        """
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
        entries = self._learnings[agent_id]
        existing_rules = [e["rule"] for e in entries]

        if trigger_signature:
            for entry in entries:
                if entry.get("trigger_signature") == trigger_signature:
                    entry["violations_after"] = entry.get("violations_after", 0) + 1
                    self._save()
                    return

        topic = rule_topic(clean_rule)
        if topic and any(rule_topic(existing) == topic for existing in existing_rules):
            self._report_saturated_topic(agent_id, topic, clean_rule)
            return

        if clean_rule not in existing_rules and not _is_semantic_duplicate(clean_rule, existing_rules):
            entries.append(_new_learning_entry(clean_rule, trigger_signature=trigger_signature, source_project=source_project))
            # Verdränge die jeweils am wenigsten wertvolle Regel, bis BEIDE Budgets eingehalten
            # sind (Anzahl UND Gesamtzeichenlänge, siehe MAX_RULES_PER_AGENT/
            # MAX_TOTAL_LEARNING_CHARS_PER_AGENT). _evict_least_valuable_entry nutzt die
            # gemessene Wirksamkeit, sobald genug Injektionen vorliegen, sonst die
            # Spezifitäts-Heuristik (siehe dortige Herleitung).
            while len(entries) > MAX_RULES_PER_AGENT or sum(len(e["rule"]) for e in entries) > MAX_TOTAL_LEARNING_CHARS_PER_AGENT:
                if len(entries) <= 1:
                    break
                _evict_least_valuable_entry(entries)
            self._save()

    @staticmethod
    def _report_saturated_topic(agent_id: str, topic: str, rule: str) -> None:
        """Eine erneute Regel zu einem bereits abgedeckten Thema zeigt: Prompt-Regeln wirken hier nicht."""
        try:
            from core.team_memory import record_lesson
            record_lesson(
                project_slug="_team",
                category="learning_saturated",
                detail=(
                    f"Agent '{agent_id}' bekam erneut eine Regel zum Thema '{topic}', obwohl bereits eine existiert - "
                    f"das Fehlverhalten wiederholt sich trotz Prompt-Regel. Framework-Fix statt weiterer Regel nötig. "
                    f"Neue Regel: {rule[:200]}"
                ),
            )
        except Exception as e:  # noqa: BLE001 - Meldung ist Zusatznutzen, das Speichern darf nie scheitern
            logging.getLogger(__name__).warning("learning_saturated konnte nicht gemeldet werden: %r", e)

    @staticmethod
    def _report_ineffective_rule(agent_id: str, entry: dict) -> None:
        """
        P2-1: Eine Regel mit > INEFFECTIVE_INJECTION_THRESHOLD Injektionen, deren Signatur
        trotzdem mindestens einmal erneut auftrat, wirkt als Prompt-Text nachweislich nicht -
        genau die Grenze, die der agent_trainer-Prompt bereits beschreibt (siehe
        INEFFECTIVE_INJECTION_THRESHOLD-Docstring). Meldet das einmalig pro Regel
        (`_ineffective_reported`-Flag im Eintrag), statt bei jedem künftigen Aufruf erneut.
        """
        try:
            from core.team_memory import record_lesson
            record_lesson(
                project_slug="_team",
                category="learning_ineffective",
                detail=(
                    f"Agent '{agent_id}': Regel wurde {entry.get('injections', 0)}x in den Prompt injiziert, "
                    f"die zugehörige Signatur '{entry.get('trigger_signature')}' trat danach trotzdem "
                    f"{entry.get('violations_after', 0)}x erneut auf - Prompt-Regel wirkungslos, "
                    f"deterministischer Check nötig statt einer weiteren Regel. Regel: {entry.get('rule', '')[:200]}"
                ),
            )
        except Exception as e:  # noqa: BLE001 - Meldung ist Zusatznutzen, das Speichern darf nie scheitern
            logging.getLogger(__name__).warning("learning_ineffective konnte nicht gemeldet werden: %r", e)

    def consolidate_topic_duplicates(self) -> dict[str, int]:
        """Behält je Agent und Thema nur die erste Regel. Liefert entfernte Regeln je Agent."""
        removed: dict[str, int] = {}
        for agent_id, entries in self._learnings.items():
            seen: set[str] = set()
            kept: list[dict] = []
            for entry in entries:
                topic = rule_topic(entry["rule"])
                if topic and topic in seen:
                    continue
                if topic:
                    seen.add(topic)
                kept.append(entry)
            if len(kept) != len(entries):
                removed[agent_id] = len(entries) - len(kept)
                self._learnings[agent_id] = kept
        if removed:
            self._save()
        return removed

    def get_learnings(self, agent_id: str) -> list[str]:
        """Gibt alle gelernten Regeln für einen Agenten zurück (nur der Regeltext, keine
        Metadaten - siehe get_learning_details() für Wirksamkeit/Alter)."""
        return [e["rule"] for e in self._learnings.get(agent_id, [])]

    def get_all_learnings(self) -> dict[str, list[str]]:
        """Gibt eine Kopie ALLER gespeicherten Learnings zurück (agent_id -> Regeltexte) – für
        Anzeige-/Audit-Zwecke, z. B. den /learnings-CLI-Befehl. Kopie statt Referenz, damit
        der Aufrufer die interne Struktur nicht versehentlich mutieren kann."""
        return {agent_id: self.get_learnings(agent_id) for agent_id in self._learnings}

    def get_learning_details(self, agent_id: str) -> list[dict]:
        """
        P2-1: Liefert je Regel eine Kopie ihrer vollständigen Metadaten (rule, created_at,
        source_project, trigger_signature, injections, violations_after) PLUS die berechnete
        `effectiveness` (siehe _effectiveness_rate - None, wenn noch zu wenige Injektionen
        vorliegen). Grundlage für die erweiterte /learnings-Anzeige (Wirksamkeit + Alter) und
        für Tests, ohne die interne Speicherstruktur offenzulegen.
        """
        return [
            {**entry, "effectiveness": _effectiveness_rate(entry)}
            for entry in self._learnings.get(agent_id, [])
        ]

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
        entries = self._learnings.get(agent_id)
        if not entries or not (1 <= rule_index <= len(entries)):
            return None
        removed = entries.pop(rule_index - 1)
        if not entries:
            del self._learnings[agent_id]
        self._save()
        return removed["rule"]

    def get_augmented_prompt(self, agent_id: str, base_system_prompt: str) -> str:
        """Reichert den System-Prompt eines Agenten mit seinen gelernten Regeln an. Zählt dabei
        je Regel eine Injektion (P2-1, Grundlage der Wirksamkeitsmessung) und meldet einmalig
        eine Regel, die trotz vieler Injektionen nachweislich nicht wirkt (siehe
        _report_ineffective_rule)."""
        entries = self._learnings.get(agent_id, [])
        if not entries:
            return base_system_prompt

        ineffective: list[dict] = []
        for entry in entries:
            entry["injections"] = entry.get("injections", 0) + 1
            if (
                entry["injections"] > INEFFECTIVE_INJECTION_THRESHOLD
                and entry.get("violations_after", 0) > 0
                and not entry.get("_ineffective_reported")
            ):
                entry["_ineffective_reported"] = True
                ineffective.append(entry)
        self._save()
        for entry in ineffective:
            self._report_ineffective_rule(agent_id, entry)

        learnings_text = "\n".join([f"- {e['rule']}" for e in entries])
        augmented = f"""{base_system_prompt}

## 🧠 GELERNTE BEST PRACTICES & ERKENNTNISSE AUS FRÜHEREN PROJEKTEN:
{learnings_text}
Achte strikt auf die Einhaltung dieser zuvor gelernten Regeln!"""
        return augmented


# Globale Instanz
agent_knowledge_base = AgentKnowledgeBase()
