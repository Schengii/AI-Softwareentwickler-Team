"""
core/team_retro.py – Periodische Team-Retro: sammelt genau die Backlog-Tickets, die KEIN
automatischer Poll-Zyklus je wieder aufgreift.

Nutzerwunsch (KI-Team-Zustandsbericht 2026-09-08): core/backlog_worker.py._process_single_
ticket() greift bewusst NUR Tickets aus _AUTONOMOUS_SOURCES bzw. mit einem der vier
_GOVERNANCE_RETRY_PREFIXES automatisch wieder auf - alles andere (z.B. "unused-agent-<id>"-
Tickets von core/optimization_advisor.py, oder "team-verification-trend" von core/workspace_
audit.py) ist mit Absicht ausgeschlossen, weil die richtige Reaktion eine menschliche Abwägung
braucht (Rollen-Konsolidierung, Team-weiter Trend), kein mechanischer Fix. Das eigentliche
Problem war nicht die Ausnahme selbst, sondern dass dafür KEIN Ersatz-Rhythmus existierte, der
diese Kategorie stattdessen regelmäßig vorlegt - echte Tickets blieben dadurch tagelang
unbeachtet im Backlog liegen, bis ein Mensch von Hand nachsah (das war real der Fall bei den 10
"unused-agent-*"-Tickets vom 06./07.09., noch offen am 08.09.).

Bewusst rein deterministisch (keine LLM-Interpretation, keine Netzwerkaufrufe) - dieselbe Linie
wie core/optimization_advisor.py: eine Liste von Fakten aus memory/backlog.json, kein Urteil.
Gedacht zum periodischen Aufruf (z.B. wöchentlich per `python main.py --team-retro`, per Cron/
`/loop`/`schedule`-Skill) - ob und wie oft, ist eine bewusste Entscheidung des Nutzers, kein
hartcodierter Automatismus hier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from core.backlog_store import Ticket, list_tickets

# Dieselbe Ausnahme-Liste wie core/backlog_worker.py._AUTONOMOUS_SOURCES/_GOVERNANCE_RETRY_
# PREFIXES - absichtlich hier dupliziert statt importiert: es sind zwei fachlich verschiedene
# Fragen ("wird dieses Ticket automatisch erneut versucht?" vs. "sollte ein Mensch es JETZT
# ansehen?"), die zufällig auf denselben zugrunde liegenden Daten operieren. Ein Import hätte
# außerdem core/backlog_worker.py (mit seinem GitHubAgent/Orchestrator-Importgewicht) in jeden
# Aufrufer dieses schlanken, reinen Auswertungsmoduls hineingezogen (z.B. core/goal_loop.py).
_AUTONOMOUS_SOURCES = ("cli", "dashboard")
_GOVERNANCE_RETRY_PREFIXES = (
    "unresolved-governance-critical-", "unresolved-permission-blocked-",
    "recurring-failure-", "recurring-lint-", "audit-",
)

# Ab wann ein Ticket ohne automatischen Retry-Pfad als "hängengeblieben" gilt - siehe
# TeamRetroReport.stale_tickets-Docstring. 5 Tage, nicht 1: ein Team-Retro ist eine
# wöchentliche/periodische Routine, kein Alarm für jedes frische Ticket.
STALE_TICKET_DAYS = 5


def _is_autonomously_retried(ticket: Ticket) -> bool:
    """True, wenn core/backlog_worker.py dieses Ticket ohnehin von selbst wieder aufgreift -
    exakte Kopie der Filterlogik aus run_backlog_poll_cycle()/_governance_retry_pool()."""
    if ticket.source in _AUTONOMOUS_SOURCES:
        return True
    return ticket.id.startswith(_GOVERNANCE_RETRY_PREFIXES)


def _age_days(ticket: Ticket) -> float:
    try:
        updated = datetime.fromisoformat(ticket.updated_at)
    except (ValueError, TypeError):
        return 0.0
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    return (datetime.now(UTC) - updated).total_seconds() / 86400


@dataclass
class TeamRetroReport:
    """Ergebnis eines Team-Retro-Durchlaufs - reine Bestandsaufnahme, keine Bewertung."""

    # Tickets ohne automatischen Retry-Pfad (siehe _is_autonomously_retried()), die seit
    # mindestens STALE_TICKET_DAYS Tagen unverändert in "todo"/"blocked"/"review" liegen - genau
    # die Kategorie, die ohne diese Routine unbemerkt tagelang liegen bleibt.
    stale_tickets: list[Ticket] = field(default_factory=list)
    total_open_tickets: int = 0
    total_stale_tickets: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.stale_tickets

    def format_for_humans(self) -> str:
        if self.is_empty:
            return (
                f"✅ Team-Retro: {self.total_open_tickets} offene(s) Ticket(s), keines davon "
                f"seit {STALE_TICKET_DAYS}+ Tagen ohne automatischen Retry-Pfad liegen geblieben."
            )
        lines = [
            f"🗓️ Team-Retro: {self.total_stale_tickets} von {self.total_open_tickets} offenen "
            f"Ticket(s) haben KEINEN automatischen Retry-Pfad und liegen seit "
            f"{STALE_TICKET_DAYS}+ Tagen unverändert - menschliche/manuelle Prüfung fällig:",
            "",
        ]
        for t in self.stale_tickets:
            age = _age_days(t)
            lines.append(f"- [{t.status}] `{t.id}` \"{t.title}\" ({age:.0f} Tage, source={t.source})")
            if t.detail:
                lines.append(f"    {t.detail[:200]}")
        return "\n".join(lines)


def build_team_retro_report() -> TeamRetroReport:
    """Sammelt alle offenen Tickets ohne automatischen Retry-Pfad, die seit STALE_TICKET_DAYS
    Tagen unverändert sind - siehe Moduldocstring für die volle Herleitung."""
    open_tickets = [t for t in list_tickets() if t.status in ("todo", "blocked", "review")]
    stale = [
        t for t in open_tickets
        if not _is_autonomously_retried(t) and _age_days(t) >= STALE_TICKET_DAYS
    ]
    # Älteste zuerst - die am längsten liegen gebliebenen Tickets sind am dringendsten.
    stale.sort(key=_age_days, reverse=True)
    return TeamRetroReport(
        stale_tickets=stale,
        total_open_tickets=len(open_tickets),
        total_stale_tickets=len(stale),
    )
