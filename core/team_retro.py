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
from datetime import UTC, datetime, timedelta

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


# ─────────────────────────────────────────────────────────────────────────────
# Weekly Digest: Sprint-Review-artiger Wochenüberblick (KI-Team-Zustandsbericht 2026-09-08)
# ─────────────────────────────────────────────────────────────────────────────
# Nutzerwunsch: der obige Team-Retro-Report zeigt nur liegengebliebene Tickets - kein
# Fortschritts-Blick wie bei einem echten Sprint-Review (was wurde fertig, wie viel hat das
# gekostet, wird das Team schneller/langsamer, wie steht die Verifikations-Erfolgsquote gerade).
# Kombiniert bereits bestehende, über Läufe hinweg gesammelte Datenquellen (memory/run_history.py,
# memory/cost_history.py, core/backlog_store.py) zu EINEM Überblick statt drei separaten Befehlen
# (`/tokens`, `/backlog`, keinen für die Verifikations-Quote) - bewusst rein deterministisch,
# keine LLM-Interpretation nötig, dieselbe Linie wie core/optimization_advisor.py.

DIGEST_WINDOW_DAYS = 7


@dataclass
class WeeklyDigest:
    """Sprint-Review-artiger Überblick über die letzten `window_days` Tage."""
    window_days: int = DIGEST_WINDOW_DAYS
    tickets_completed: int = 0
    tickets_opened: int = 0
    tokens_spent: int = 0
    verification_runs: int = 0
    verification_passed: int = 0
    verification_rate: float = 0.0
    stale_retro: TeamRetroReport = field(default_factory=TeamRetroReport)

    @property
    def velocity_delta(self) -> int:
        """Positiv = mehr abgeschlossen als neu eröffnet (Backlog schrumpft), negativ =
        Backlog wächst schneller, als das Team abarbeitet."""
        return self.tickets_completed - self.tickets_opened

    def format_for_humans(self) -> str:
        trend_icon = "📈" if self.velocity_delta > 0 else ("📉" if self.velocity_delta < 0 else "➡️")
        lines = [
            f"🗓️ Weekly Digest (letzte {self.window_days} Tage)",
            "",
            f"✅ Abgeschlossen: {self.tickets_completed} Ticket(s)",
            f"📥 Neu eröffnet: {self.tickets_opened} Ticket(s)",
            f"{trend_icon} Velocity: {self.velocity_delta:+d} (Backlog {'schrumpft' if self.velocity_delta > 0 else 'wächst' if self.velocity_delta < 0 else 'stabil'})",
            f"🪙 Tokenverbrauch: {self.tokens_spent:,}".replace(",", "."),
        ]
        if self.verification_runs:
            lines.append(
                f"🧪 Verifikations-Erfolgsquote: {self.verification_passed}/{self.verification_runs} "
                f"({self.verification_rate}%)"
            )
        else:
            lines.append("🧪 Verifikations-Erfolgsquote: keine Läufe in diesem Zeitraum aufgezeichnet.")
        lines.append("")
        lines.append(self.stale_retro.format_for_humans())
        return "\n".join(lines)


def build_weekly_digest(window_days: int = DIGEST_WINDOW_DAYS) -> WeeklyDigest:
    """Baut den Weekly Digest aus bereits bestehenden Datenquellen zusammen - jede einzelne
    Quelle best-effort (ein Fehler in einer Quelle darf den Rest des Digests nicht verwerfen)."""
    from memory.cost_history import _load as _load_cost_history
    from memory.run_history import get_recent_runs

    all_tickets = list_tickets()
    completed = sum(1 for t in all_tickets if t.status == "done" and _age_days(t) <= window_days)
    opened = sum(1 for t in all_tickets if _created_age_days(t) <= window_days)

    tokens_spent = 0
    try:
        daily = _load_cost_history().get("daily", {})
        cutoff = datetime.now(UTC) - timedelta(days=window_days)
        for day_str, models in daily.items():
            try:
                day = datetime.strptime(day_str, "%Y-%m-%d").replace(tzinfo=UTC)
            except ValueError:
                continue
            if day < cutoff:
                continue
            tokens_spent += sum(stats.get("total_tokens", 0) for stats in models.values())
    except Exception:
        tokens_spent = 0

    verification_runs = verification_passed = 0
    try:
        cutoff = datetime.now(UTC) - timedelta(days=window_days)
        for run in get_recent_runs(limit=200):
            try:
                ts = datetime.fromisoformat(run.get("timestamp", ""))
            except ValueError:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if ts < cutoff:
                continue
            verification_runs += 1
            if run.get("verification_ok"):
                verification_passed += 1
    except Exception:
        verification_runs = verification_passed = 0

    return WeeklyDigest(
        window_days=window_days,
        tickets_completed=completed,
        tickets_opened=opened,
        tokens_spent=tokens_spent,
        verification_runs=verification_runs,
        verification_passed=verification_passed,
        verification_rate=round(100 * verification_passed / verification_runs, 1) if verification_runs else 0.0,
        stale_retro=build_team_retro_report(),
    )


def _created_age_days(ticket: Ticket) -> float:
    try:
        created = datetime.fromisoformat(ticket.created_at)
    except (ValueError, TypeError):
        return 0.0
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return (datetime.now(UTC) - created).total_seconds() / 86400
