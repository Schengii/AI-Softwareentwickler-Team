"""
core/acceptance_check.py – Abnahme gegen die ursprüngliche Anforderung (P4-2, ROADMAP_TEMP.md)

Die Definition of Done (core/definition_of_done.py) prüft technische Eigenschaften (Tests
laufen, App startet, keine Secrets) - nicht, ob geliefert wurde, was bestellt war. Realer Fund
`cachegrid_proxy`: bestellt waren u.a. "Write-Behind-Strategie", "Key-Tagging und selektive
Invalidierung", "vollständige pytest-Suite für Race Conditions und Cache-Eviction". Geliefert
wurden 3 Testfunktionen, die die Testtiefen-Prüfung trotzdem mit "1/1 API-Routen (100%)"
bestanden, weil das Projekt nur eine Route deklarierte - die Kennzahl war grün, die
Anforderung nicht erfüllt.

Zwei Schritte, beide über den `product_owner`-Agenten (existiert bereits, wurde laut P2-3 vorher
so gut wie nie eingesetzt):

1. `extract_requirements()` – VOR der Entwicklung, ohne Tool-Zugriff: liest ausschließlich den
   Auftragstext und destilliert ihn in eine nummerierte Liste konkreter, prüfbarer Anforderungen.
   Persistiert als `.ai_team_acceptance.json`.
2. `verify_acceptance()` – NACH der Entwicklung/Verifikation, mit LESE-Tool-Zugriff
   (`tools_read_only=True`, derselbe Modus wie core/roadmap_advisor.py): prüft jede Anforderung
   gegen den tatsächlich geschriebenen Code und markiert sie als erfüllt oder fehlend.

Beide Schritte sind bewusst tolerant gegenüber Freitext-Antworten (wie core/roadmap_advisor.py
und core/review_gate.py): lässt sich die Antwort nicht im erwarteten Format parsen, blockiert
das NICHT den Lauf - eine falsch-positive Blockade durch eine Formatabweichung wäre schlimmer als
ein übersprungener Check.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from core.message_bus import AgentTask

logger = logging.getLogger(__name__)

ACCEPTANCE_FILENAME = ".ai_team_acceptance.json"

_EXTRACT_TASK_PROMPT = (
    "Dies ist KEIN Auftrag, etwas zu implementieren. Lies AUSSCHLIESSLICH den folgenden "
    "Auftragstext und destilliere ihn in eine Liste konkreter, einzeln prüfbarer Anforderungen "
    "(Features, Funktionen, explizit genannte technische Vorgaben) - keine allgemeinen "
    "Qualitätsziele wie 'sauberer Code' oder 'gute Performance', nur Dinge, die man an der "
    "fertigen Lieferung konkret nachprüfen kann. Antworte AUSSCHLIESSLICH als nummerierte Liste "
    "in GENAU diesem Format, keine Einleitung, kein Fazit, maximal 10 Einträge:\n\n"
    "1. <eine Anforderung, ein Satz>\n2. <nächste Anforderung>\n(usw.)\n\n"
    "AUFTRAGSTEXT:\n{user_request}"
)

_VERIFY_TASK_PROMPT = (
    "Dies ist ein Abnahme-Check, KEIN Auftrag, etwas zu implementieren oder zu ändern. Prüfe "
    "JEDE der folgenden nummerierten Anforderungen GEGEN DEN TATSÄCHLICHEN CODE dieses Projekts "
    "(list_files/read_file/search_code - keine Annahmen, keine Vermutungen). Antworte "
    "AUSSCHLIESSLICH als nummerierte Liste in GENAU diesem Format, dieselbe Nummerierung und "
    "Reihenfolge wie unten, keine Einleitung, kein Fazit:\n\n"
    "1. [ERFÜLLT] <ein Satz, welche Datei/Stelle das belegt>\n"
    "2. [FEHLT] <ein Satz, was konkret fehlt>\n(usw., GENAU {count} Zeilen)\n\n"
    "ANFORDERUNGEN:\n{requirements}"
)

_REQUIREMENT_LINE_RE = re.compile(r"^\s*\d+\.\s*(.+?)\s*$")
_VERIFY_LINE_RE = re.compile(r"^\s*(\d+)\.\s*\[(ERF[UÜ]LLT|FEHLT)\]\s*(.*)$", re.IGNORECASE)


@dataclass
class AcceptanceCheckResult:
    """Ergebnis von verify_acceptance(). `parsed=False` heißt: die Antwort ließ sich nicht im
    erwarteten Format auswerten - blockiert NICHT (siehe Moduldocstring), `requirements_met`
    ist dann None statt False."""
    requirements: list[str] = field(default_factory=list)
    met: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    parsed: bool = False
    raw_content: str = ""
    error: str = ""

    @property
    def requirements_met(self) -> bool | None:
        if not self.parsed:
            return None
        return not self.missing


def parse_requirements(content: str, limit: int = 10) -> list[str]:
    """Parst das von extract_requirements() geforderte nummerierte Format."""
    items: list[str] = []
    for line in content.splitlines():
        match = _REQUIREMENT_LINE_RE.match(line)
        if match:
            text = match.group(1).strip()
            if text:
                items.append(text)
    return items[:limit]


def parse_verification(content: str, requirements: list[str]) -> AcceptanceCheckResult:
    """Parst das von verify_acceptance() geforderte nummerierte [ERFÜLLT]/[FEHLT]-Format.
    Ordnet strikt über die Zeilennummer zu (1-basiert), nicht über Textähnlichkeit - robuster
    gegen ein LLM, das die Anforderung beim Zurückgeben leicht umformuliert. Liefert
    `parsed=False`, wenn nicht für JEDE Anforderung eine eindeutig zuordenbare Zeile gefunden
    wurde (lieber gar kein Urteil als ein aus lückenhaften Daten geratenes)."""
    by_index: dict[int, tuple[bool, str]] = {}
    for line in content.splitlines():
        match = _VERIFY_LINE_RE.match(line)
        if not match:
            continue
        idx = int(match.group(1))
        met = match.group(2).upper().startswith("ERF")
        by_index[idx] = (met, match.group(3).strip())

    if len(by_index) != len(requirements) or not requirements:
        return AcceptanceCheckResult(requirements=requirements, raw_content=content, parsed=False)

    met: list[str] = []
    missing: list[str] = []
    for i, requirement in enumerate(requirements, start=1):
        if i not in by_index:
            return AcceptanceCheckResult(requirements=requirements, raw_content=content, parsed=False)
        is_met, _detail = by_index[i]
        (met if is_met else missing).append(requirement)

    return AcceptanceCheckResult(requirements=requirements, met=met, missing=missing, parsed=True, raw_content=content)


def write_requirements(project_dir: str | Path, requirements: list[str]) -> None:
    path = Path(project_dir) / ACCEPTANCE_FILENAME
    try:
        path.write_text(json.dumps({"requirements": requirements}, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        logger.warning("Anforderungsliste konnte nicht geschrieben werden (%s): %r", path, e)


def read_requirements(project_dir: str | Path) -> list[str]:
    path = Path(project_dir) / ACCEPTANCE_FILENAME
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data.get("requirements", [])
        return [str(i) for i in items] if isinstance(items, list) else []
    except (OSError, json.JSONDecodeError):
        return []


async def extract_requirements(orchestrator, user_request: str, project_dir: str | Path) -> list[str]:
    """Phase 1: destilliert den Auftragstext in eine Anforderungsliste (kein Tool-Zugriff nötig,
    der Code existiert an dieser Stelle des Laufs noch gar nicht) und persistiert sie. Best-
    effort: ein Fehler liefert eine leere Liste, ohne den Lauf zu gefährden."""
    task = AgentTask(
        task_id="acceptance_extract",
        agent_id="product_owner",
        description=_EXTRACT_TASK_PROMPT.format(user_request=user_request[:4000]),
        allow_tools=False,
    )
    try:
        result = await orchestrator._run_single_agent(task)
    except Exception as e:
        logger.warning("Anforderungs-Extraktion fehlgeschlagen: %r", e)
        return []
    if not result.success or not result.content:
        return []
    requirements = parse_requirements(result.content)
    if requirements:
        write_requirements(project_dir, requirements)
    return requirements


async def verify_acceptance(orchestrator, project_dir: str | Path, requirements: list[str]) -> AcceptanceCheckResult:
    """Phase 2: prüft jede Anforderung read-only gegen den tatsächlichen Code (list_files/
    read_file/search_code, kein Schreibzugriff - derselbe Modus wie core/roadmap_advisor.py)."""
    if not requirements:
        return AcceptanceCheckResult()
    numbered = "\n".join(f"{i}. {r}" for i, r in enumerate(requirements, start=1))
    task = AgentTask(
        task_id="acceptance_verify",
        agent_id="product_owner",
        description=_VERIFY_TASK_PROMPT.format(requirements=numbered, count=len(requirements)),
        project_dir=str(project_dir), allow_tools=True, tools_read_only=True,
    )
    try:
        result = await orchestrator._run_single_agent(task)
    except Exception as e:
        logger.warning("Abnahme-Prüfung fehlgeschlagen: %r", e)
        return AcceptanceCheckResult(requirements=requirements, error=str(e))
    if not result.success or not result.content:
        return AcceptanceCheckResult(requirements=requirements, error=result.error or "Keine Antwort vom product_owner-Agenten.")
    return parse_verification(result.content, requirements)
