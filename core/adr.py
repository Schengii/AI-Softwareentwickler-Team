"""
core/adr.py – Architecture Decision Records (ADRs): das WARUM, nicht nur das WAS

core/project_constitution.py hält bereits das WAS fest (Sprache, Framework, Code-Stil,
Deployment-Ziel) – aber nicht das WARUM ("REST statt GraphQL, weil…"). Ohne das können
spätere Läufe unbemerkt gegen frühere, bewusst getroffene Entscheidungen arbeiten. ADRs
(Nygard-Format: Titel, Status, Kontext, Entscheidung, Konsequenzen) schließen diese Lücke:
pro Entscheidung eine kurze, nummerierte Markdown-Datei unter docs/adr/ im Projektverzeichnis
– bewusst NICHT gitignored (anders als core/backlog_store.py's memory/backlog.json), da ADRs
Teil der Projekt-Dokumentation sind und mit dem Code selbst versioniert werden sollen, genau
wie eine .ai-team.toml-Konstitution.

Geschrieben über das neue Werkzeug record_architecture_decision() (core/agent_toolbox.py,
primär vom architect-Agenten genutzt) und vor jeder Aufgabe der HEAVY-Tier-Agenten mit echten
Architektur-Trade-offs in den Kontext injiziert (agents/orchestrator.py,
format_adr_summary_for_context()) – dieselbe "einmal festgelegt, künftig immer mitgegeben"
Philosophie wie die bestehende Projekt-Konstitution.
"""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from core.git_isolation import slugify

ADR_DIR_NAME = "docs/adr"

# Ab welcher Titel-Ähnlichkeit (0..1, SequenceMatcher.ratio()) eine neue ADR als
# Nahezu-Duplikat einer bestehenden gilt. Realer Fund (api_health_monitor): zwei ADRs mit
# fast identischem Titel/Inhalt ("SQLite für Check-Historie Persistenz") wurden in
# unterschiedlichen Läufen desselben Projekts angelegt, weil der Agent nicht auf bereits
# dokumentierte Entscheidungen desselben Themas geprüft hat, bevor er eine neue Datei anlegte
# (im Unterschied zur projektübergreifenden Nahezu-Duplikat-Erkennung in
# agents/orchestrator.py._find_near_duplicate_slug, die neue Projekte statt neue ADRs prüft).
DUPLICATE_TITLE_SIMILARITY_THRESHOLD = 0.7

# Wie viele ADRs maximal in den Agenten-Kontext injiziert werden (format_adr_summary_for_context)
# - der agentische Tool-Loop sendet den kompletten bisherigen Kontext bei JEDER weiteren
# Iteration erneut mit, ein unbegrenztes Wachstum würde den Tokenverbrauch mit der
# Projektlaufzeit linear steigen lassen. Die NEUESTEN Entscheidungen sind am relevantesten
# für "widerspreche ich hier gerade etwas Bestehendem" - ältere fallen zuerst raus.
MAX_ADRS_IN_CONTEXT = 12
MAX_SUMMARY_LINE_CHARS = 160

_FILENAME_PATTERN = re.compile(r"^(\d{4})-(.+)\.md$")


@dataclass
class AdrRecord:
    number: int
    title: str
    status: str
    path: Path


def _adr_dir(project_dir: str | Path) -> Path:
    return Path(project_dir) / ADR_DIR_NAME


def _parse_title_and_status(path: Path) -> tuple[str, str]:
    """Liest Titel (erste '# '-Überschrift) und Status (erste 'Status:'-Zeile) direkt aus der
    Markdown-Datei - kein Crash bei unerwartetem Format/fehlender Datei, liefert dann leere
    bzw. 'unbekannt'-Werte statt einer Exception."""
    title, status = "", "unbekannt"
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if stripped.startswith("# ") and not title:
                title = stripped[2:].strip()
            elif stripped.lower().startswith("status:") and status == "unbekannt":
                status = stripped.split(":", 1)[1].strip()
            if title and status != "unbekannt":
                break
    except OSError:
        pass
    return title, status


def list_adrs(project_dir: str | Path) -> list[AdrRecord]:
    """
    Listet alle bestehenden ADRs eines Projekts, aufsteigend nach Nummer sortiert. Liest die
    Nummer aus dem Dateinamen (NNNN-slug.md) – robust gegen unerwartet formatierten Inhalt,
    da nur der Dateiname strukturell verlässlich ist. Leere Liste, wenn docs/adr/ (noch)
    nicht existiert – kein Fehler, die meisten Projekte haben (noch) keine ADRs.
    """
    adr_dir = _adr_dir(project_dir)
    if not adr_dir.exists():
        return []
    records = []
    for path in sorted(adr_dir.glob("*.md")):
        match = _FILENAME_PATTERN.match(path.name)
        if not match:
            continue
        title, status = _parse_title_and_status(path)
        records.append(AdrRecord(
            number=int(match.group(1)), title=title or match.group(2).replace("-", " "),
            status=status, path=path,
        ))
    return sorted(records, key=lambda r: r.number)


def next_adr_number(project_dir: str | Path) -> int:
    existing = list_adrs(project_dir)
    return (existing[-1].number + 1) if existing else 1


def find_near_duplicate_adr(project_dir: str | Path, title: str) -> AdrRecord | None:
    """Findet eine bereits im Projekt existierende ADR mit einem stark ähnlichen Titel (z.B.
    "SQLite für Check-Historie Persistenz" vs. "SQLite für Check-Historie-Persistenz") -
    gedacht, um zu verhindern, dass derselbe Trade-off zweimal separat dokumentiert wird, statt
    die bestehende ADR zu erweitern oder darauf zu verweisen. Vergleicht case-insensitive per
    difflib.SequenceMatcher; gibt None zurück, wenn keine ADR über
    DUPLICATE_TITLE_SIMILARITY_THRESHOLD liegt oder das Projekt noch keine ADRs hat."""
    needle = (title or "").strip().lower()
    if not needle:
        return None
    best_match, best_ratio = None, 0.0
    for record in list_adrs(project_dir):
        ratio = SequenceMatcher(None, needle, record.title.strip().lower()).ratio()
        if ratio > best_ratio:
            best_match, best_ratio = record, ratio
    return best_match if best_ratio >= DUPLICATE_TITLE_SIMILARITY_THRESHOLD else None


def write_adr(
    project_dir: str | Path, title: str, context: str, decision: str,
    consequences: str, status: str = "Angenommen",
) -> Path:
    """
    Legt eine neue, nummerierte ADR-Datei an (docs/adr/NNNN-slug.md, Nygard-Format). Die
    Nummer wird deterministisch in Python vergeben statt vom Modell geraten
    (core/agent_toolbox.py._tool_record_architecture_decision() ruft dies auf) – schließt
    Kollisionen/Lücken aus, die ein vom LLM selbst gewählter Dateiname verursachen könnte.
    Gibt den absoluten Pfad der geschriebenen Datei zurück.
    """
    adr_dir = _adr_dir(project_dir)
    adr_dir.mkdir(parents=True, exist_ok=True)
    number = next_adr_number(project_dir)
    path = adr_dir / f"{number:04d}-{slugify(title)}.md"

    content = (
        f"# {title}\n\n"
        f"Status: {status}\n\n"
        f"## Kontext\n\n{context.strip()}\n\n"
        f"## Entscheidung\n\n{decision.strip()}\n\n"
        f"## Konsequenzen\n\n{consequences.strip()}\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


def find_existing_near_duplicate_adr_pairs(project_dir: str | Path) -> list[tuple[AdrRecord, AdrRecord]]:
    """
    Rückwirkende Variante von find_near_duplicate_adr(): durchsucht ALLE bereits vorhandenen
    ADRs eines Projekts paarweise auf Titel-Ähnlichkeit, statt nur einen neuen Titel gegen
    bestehende zu prüfen. find_near_duplicate_adr() verhindert nur KÜNFTIGE Duplikate beim
    Schreiben (core/agent_toolbox.py) - ADRs, die schon vor Einführung dieser Prüfung entstanden
    sind (realer Fund: api_health_monitor/docs/adr/0001 und 0002, fast identischer Inhalt),
    bleiben davon unentdeckt. core/workspace_audit.py ruft dies bei jedem `--audit-workspace`-
    Zyklus auf, damit solche Altlasten wie unvollständige/nahezu-doppelte Projekte sichtbar
    werden. Gibt jedes Paar nur einmal zurück (niedrigere vor höherer Nummer).
    """
    records = list_adrs(project_dir)
    pairs: list[tuple[AdrRecord, AdrRecord]] = []
    for i, a in enumerate(records):
        for b in records[i + 1:]:
            ratio = SequenceMatcher(None, a.title.strip().lower(), b.title.strip().lower()).ratio()
            if ratio >= DUPLICATE_TITLE_SIMILARITY_THRESHOLD:
                pairs.append((a, b))
    return pairs


def format_adr_summary_for_context(project_dir: str | Path) -> str:
    """
    Kurzer, gedeckelter Digest bestehender Entscheidungen für den Agenten-Kontext
    (agents/orchestrator.py) – NUR Nummer/Titel/Status, kein voller Inhalt (der lässt sich
    bei Bedarf über read_file/list_files im Werkzeug-Loop selbst nachladen). Leerer String,
    wenn das Projekt noch keine ADRs hat – kein unnötiger Prompt-Text für die Mehrheit der
    Läufe (frische Projekte ohne bisherige Entscheidungen).
    """
    records = list_adrs(project_dir)
    if not records:
        return ""
    recent = records[-MAX_ADRS_IN_CONTEXT:]
    lines = [f"- ADR-{r.number:04d} [{r.status}] {r.title}"[:MAX_SUMMARY_LINE_CHARS] for r in recent]
    omitted_note = f"\n(… {len(records) - len(recent)} ältere ADR(s) ausgelassen)" if len(records) > len(recent) else ""
    return (
        "Bereits getroffene Architektur-Entscheidungen dieses Projekts (widersprich ihnen "
        "nicht unbemerkt – bei Bedarf per read_file('docs/adr/<datei>') vollständig nachlesen):\n"
        + "\n".join(lines) + omitted_note
    )
