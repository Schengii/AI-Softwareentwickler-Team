"""
core/roadmap_advisor.py – Eigenständiges Weiterdenken für bestehende Workspace-Projekte
("was wäre der nächste sinnvolle Schritt?")

Nutzerwunsch (KI-Team-Zustandsbericht 2026-09-08, Punkt "Product-Owner-Weiterdenken"): der
product_owner-Agent bearbeitet bisher AUSSCHLIESSLICH die konkret gestellte Aufgabe - es gibt
keine Rolle, die für ein bereits bestehendes Projekt eigenständig den nächsten sinnvollen
Schritt vorschlägt (z.B. "Login existiert, aber kein Passwort-Reset-Flow" oder "API hat keine
Rate-Limits trotz öffentlichem Zugriff"). Ein echtes Produktteam denkt über die gestellte
Aufgabe hinaus - dieses Modul schließt genau diese Lücke.

Bewusst NUR ein Vorschlags-Mechanismus, KEINE automatische Umsetzung: propose_next_steps()
liest das Projekt read-only (project_dir + tools_read_only=True, derselbe Modus wie die
verpflichtenden Re-Review-Tasks in agents/orchestrator/verification.py) und legt die
Vorschläge als Backlog-Tickets mit source="product_owner_proposal" an - dieser Source-String
ist bewusst NICHT in core/backlog_worker.py._AUTONOMOUS_SOURCES enthalten (dieselbe Linie wie
core/optimization_advisor.py.record_unused_agent_tickets(): OB ein vorgeschlagenes Feature
wirklich sinnvoll ist, ist eine menschliche Produktentscheidung, kein mechanischer Fix, den
--work-backlog selbstständig umsetzen sollte). Ein Mensch, der einen Vorschlag greenlighted,
stellt ihn regulär als Aufgabe (oder ändert den Ticket-Source per Dashboard/CLI).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.backlog_store import upsert_ticket
from core.message_bus import AgentTask
from core.workspace import WorkspaceManager

PROPOSAL_TICKET_SOURCE = "product_owner_proposal"

_TASK_PROMPT = (
    "Dies ist KEIN Auftrag, etwas zu implementieren - analysiere ausschließlich den "
    "BESTEHENDEN Code dieses Projekts (list_files/read_file) und schlage 3 bis 5 konkrete, "
    "sinnvolle NÄCHSTE Schritte vor, die ein echter Product Owner für dieses Projekt "
    "vorschlagen würde (fehlende, aber naheliegende Features, Lücken im aktuellen Funktions-"
    "umfang, technische Schulden mit spürbarem Nutzerwert). Antworte AUSSCHLIESSLICH als "
    "nummerierte Liste in GENAU diesem Format, keine Einleitung, kein Fazit:\n\n"
    "1. **Kurzer Titel** - Ein bis zwei Sätze Begründung, warum das der naheliegende nächste "
    "Schritt ist.\n"
    "2. **Kurzer Titel** - Begründung.\n"
    "(usw., 3-5 Einträge)"
)

_PROPOSAL_RE = re.compile(r"^\s*\d+\.\s*\*\*(.+?)\*\*\s*[-–—:]\s*(.+)$")


@dataclass
class RoadmapProposal:
    """Ein einzelner, vom product_owner-Agenten vorgeschlagener nächster Schritt."""
    title: str
    rationale: str


@dataclass
class RoadmapProposalReport:
    """Ergebnis eines propose_next_steps()-Durchlaufs für EIN Projekt."""
    project_slug: str
    proposals: list[RoadmapProposal] = field(default_factory=list)
    ticket_ids: list[str] = field(default_factory=list)
    raw_content: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def _parse_proposals(content: str) -> list[RoadmapProposal]:
    """Parst das vom Agenten geforderte nummerierte Format - best effort: eine Zeile, die nicht
    passt, wird übersprungen statt den ganzen Durchlauf scheitern zu lassen (dieselbe Toleranz
    wie core/review_gate.py gegenüber frei formuliertem LLM-Text)."""
    proposals: list[RoadmapProposal] = []
    for line in content.splitlines():
        match = _PROPOSAL_RE.match(line)
        if match:
            title, rationale = match.group(1).strip(), match.group(2).strip()
            if title and rationale:
                proposals.append(RoadmapProposal(title=title, rationale=rationale))
    return proposals


def _ticket_id_for(project_slug: str, index: int, title: str) -> str:
    """Stabil über wiederholte Läufe hinweg (Index in der zurückgegebenen Liste, NICHT ein Hash
    des Titels) - ein leicht anders formulierter, aber inhaltlich selber Vorschlag beim nächsten
    Lauf soll dasselbe Ticket auffrischen (upsert_ticket()-Semantik), nicht ein neues Duplikat
    anlegen. Ein Hash des Titels würde das verhindern, sobald das LLM denselben Vorschlag beim
    nächsten Mal nur minimal anders formuliert."""
    return f"roadmap-proposal-{project_slug}-{index + 1}"


async def propose_next_steps(orchestrator, project_slug: str) -> RoadmapProposalReport:
    """
    Lässt den product_owner-Agenten read-only Vorschläge für den nächsten sinnvollen Schritt
    eines BEREITS BESTEHENDEN Workspace-Projekts machen und legt sie als Backlog-Tickets an
    (source=PROPOSAL_TICKET_SOURCE, status="todo", priority=3 - niedrige Priorität, da ein
    Vorschlag, keine bereits entschiedene Arbeit).

    `orchestrator`: eine bereits initialisierte Orchestrator-Instanz (agents/orchestrator/
    __init__.py) - wiederverwendet statt selbst eine neue anzulegen, damit derselbe Aufruf aus
    interface/cli.py (wo der Nutzer bereits eine laufende Sitzung mit eigenem Orchestrator hat)
    UND aus core/backlog_worker.py-artigem Batch-Code funktioniert, ohne zwei verschiedene
    Codepfade zu brauchen.
    """
    project_dir = WorkspaceManager().get_project_dir(project_slug)
    if not project_dir.exists():
        return RoadmapProposalReport(project_slug=project_slug, error=f"Projekt '{project_slug}' existiert nicht in workspace/.")

    task = AgentTask(
        task_id=f"roadmap_proposal_{project_slug}",
        agent_id="product_owner",
        description=_TASK_PROMPT,
        context="", project_dir=str(project_dir), allow_tools=True, tools_read_only=True,
    )
    try:
        result = await orchestrator._run_single_agent(task)
    except Exception as e:
        return RoadmapProposalReport(project_slug=project_slug, error=str(e))

    if not result.success or not result.content:
        return RoadmapProposalReport(project_slug=project_slug, error=result.error or "Keine Antwort vom product_owner-Agenten.")

    proposals = _parse_proposals(result.content)
    if not proposals:
        return RoadmapProposalReport(
            project_slug=project_slug, raw_content=result.content,
            error="Antwort enthielt keine im erwarteten Format erkennbaren Vorschläge.",
        )

    ticket_ids: list[str] = []
    for i, proposal in enumerate(proposals):
        ticket_id = _ticket_id_for(project_slug, i, proposal.title)
        try:
            upsert_ticket(
                ticket_id=ticket_id, title=f"Vorschlag: {proposal.title}",
                source=PROPOSAL_TICKET_SOURCE, status="todo", project_slug=project_slug,
                priority=3, detail=proposal.rationale,
            )
            ticket_ids.append(ticket_id)
        except Exception:
            # Ein fehlgeschlagenes Einzel-Ticket darf die übrigen Vorschläge nicht verwerfen -
            # dasselbe Best-effort-Prinzip wie core/optimization_advisor.py.record_unused_
            # agent_tickets().
            continue

    return RoadmapProposalReport(
        project_slug=project_slug, proposals=proposals, ticket_ids=ticket_ids, raw_content=result.content,
    )
