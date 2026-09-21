"""
core/backlog_worker.py – Selbstgesteuertes Abarbeiten des eigenen Backlogs (autonome Arbeit
ohne externen Trigger)

Realer Fund: core/issue_watcher.py reagiert eigenständig auf GitHub-Issues, ABER nur auf neu
gelabelte – ein "todo"-Ticket aus `/backlog-add` (interface/cli.py) oder core/pr_review_watcher.py
wurde laut eigenem Docstring bisher NIE automatisch angegangen ("Führt selbst nichts aus – ein
'todo'-Ticket wird erst zu echter Arbeit, wenn du die Aufgabe regulär in den Chat schreibst").
Ein echtes, produktives Team wartet nicht auf ein manuelles Label, um mit dem nächsten
priorisierten Backlog-Punkt zu beginnen – genau diese Lücke schließt dieser Poll-Zyklus
(aufgerufen über `python main.py --work-backlog`, z.B. per Cron/Taskplaner/GitHub-Actions-
Schedule, analog zu core/issue_watcher.py).

Scope bewusst auf `source in ("cli", "dashboard")` begrenzt:
- "issue"-Tickets werden bereits vollständig von core/issue_watcher.py verwaltet – ein
  zweiter, konkurrierender Aufgreif-Mechanismus für dieselbe Quelle würde Doppelarbeit/
  widersprüchliche Zustände riskieren.
- "pr_review"-Tickets (core/pr_review_watcher.py) beziehen sich auf einen BEREITS
  bestehenden Feature-Branch – ihre `project_slug` ist der Branch-Name, kein Workspace-
  Projekt-Slug. Sie sinnvoll abzuarbeiten bräuchte einen echten Checkout dieses Branches
  VOR dem Orchestrator-Lauf, was dieser Worker (noch) nicht beherrscht – lieber ehrlich
  ausklammern als sie falsch (auf einem frischen Branch statt dem PR-Branch) zu bearbeiten.

Respektiert core/backlog_store.py.is_ticket_ready(): ein Ticket mit noch offenen
Abhängigkeiten wird übersprungen, nicht blind aufgegriffen – ein echtes Team beginnt Schritt 2
einer Kette auch nicht, bevor Schritt 1 fertig ist. Sicherheitsmodell identisch zu
core/issue_watcher.py (siehe dort für die ausführliche Begründung): kein Mensch zur
Bestätigung verfügbar, deshalb harter Secret-Block, immer Feature-Branch+PR statt Direct-Push,
und ein Fehlschlag der Verifikation ODER eine offene Rückfrage (core/agent_toolbox.py.
ask_human_for_clarification) öffnen trotzdem einen (dann als Draft markierten) PR statt
bereits geleistete Arbeit stillschweigend zu verwerfen.

Team-Optimierung (Retrospektive 2026-09-03, erweitert 2026-09-04): "blocked"-Tickets, die
agents/orchestrator/(verification.py|__init__.py) für einen ungelösten KRITISCHEN Governance-/
Verifikations-Befund eröffnen (unresolved-governance-critical-<slug>, unresolved-permission-
blocked-<slug>, recurring-failure-<slug>, recurring-lint-<slug>), landeten bisher in einer
Sackgasse - source="orchestrator" und status="blocked" fielen durch JEDES Filter unten, kein
Poll-Zyklus griff sie je wieder auf, selbst wenn ein späterer, unabhängiger Versuch das Problem
durchaus hätte lösen können. _governance_retry_pool() macht genau diese Tickets (bis zu
MAX_GOVERNANCE_TICKET_RETRIES-mal) wieder zu aufgreifbarer Arbeit - siehe dort für die Details
und die Abgrenzung zu einer echten Endlosschleife.
"""

import asyncio
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from agents.github_agent import GitHubAgent
from agents.orchestrator import Orchestrator
from config import (
    BACKLOG_WORKER_MAX_PER_CYCLE,
    BACKLOG_WORKER_WIP_LIMIT,
    BASE_DIR,
    GIT_PROTECTED_BRANCHES,
    MAX_GOVERNANCE_TICKET_RETRIES,
    RED_PROJECT_REPAIR_PER_POLL,
    WORKSPACE_DIR,
)
from core.backlog_store import Ticket, count_by_status, is_ticket_ready, list_tickets, upsert_ticket
from core.git_isolation import copy_worktree_changes_to_target, remove_worktree
from core.merge_watcher import check_merged_tickets
from core.notifier import notify_external
from core.provider_exhaustion import all_failed_on_provider_exhaustion, is_provider_exhaustion_error
from core.workspace import WorkspaceManager

StatusCallback = Callable[[str], None]

_AUTONOMOUS_SOURCES = ("cli", "dashboard")

# ID-Präfixe, unter denen agents/orchestrator/(verification.py|__init__.py) ungelöste Befunde als
# "blocked"-Ticket eröffnet (siehe dort: upsert_ticket(ticket_id=f"unresolved-...-{slug}", ...)
# bzw. f"recurring-...-{slug}"). NUR diese vier - ein generisches "jedes blocked-Ticket erneut
# versuchen" würde auch ein Ticket wieder aufgreifen, das ein MENSCH bewusst als "blocked"
# markiert hat (z.B. wartet auf eine externe Entscheidung), was hier ausdrücklich nicht gewollt
# ist.
#
# Team-Optimierung (Retrospektive, 2026-09-04): "recurring-failure-" (echte Testfehler, die nach
# 2 Fixversuchen bestehen blieben, agents/orchestrator/verification.py) und "recurring-lint-"
# (hartnäckige Lint-Funde über mehrere Läufe, agents/orchestrator/__init__.py) fehlten hier
# ursprünglich - genau die Sackgasse, die dieses Modul laut Docstring oben bereits einmal für die
# "unresolved-..."-Tickets behoben hatte, nur nicht auf diese beiden Nachbar-Kategorien
# ausgeweitet. Ergebnis: 5 von 17 echten Tickets im Backlog steckten dauerhaft fest, weil
# `--work-backlog` sie nie wieder aufgriff. Beide Kategorien schließen sich inzwischen (wie die
# "unresolved-..."-Tickets) automatisch selbst, sobald der zugrunde liegende Befund in einem
# späteren Lauf behoben ist (siehe agents/orchestrator/verification.py: had_prior_test_ticket
# bzw. agents/orchestrator/__init__.py: lint_ticket_id-Auto-Close) - ein Retry-Versuch kann also
# tatsächlich zu einem geschlossenen Ticket führen, nicht nur zu erneutem "blocked".
_GOVERNANCE_RETRY_PREFIXES = (
    "unresolved-governance-critical-", "unresolved-permission-blocked-",
    "recurring-failure-", "recurring-lint-",
    # Team-Optimierung (Token-/Erfolgsquoten-Analyse 2026-09-17, echter Fund: `test-regression-
    # pipeline_pilot`, `test-regression-entwickle_das_projekt_sentinel` standen seit dem
    # 16./17.09. unverändert auf "blocked"): "test-regression-" (agents/orchestrator/
    # verification.py legt dieses Ticket an, wenn selbst der neue Auto-Revert-Versuch - siehe
    # core.test_depth.restore_test_files() - einen gelöschten statt behobenen Test nicht retten
    # konnte) fehlte hier aus genau demselben Grund wie "recurring-failure-"/"recurring-lint-"
    # oben ursprünglich: eine eigene, thematisch verwandte Ticket-Kategorie, die der generische
    # Filter unten nicht als retry-fähig erkannte - das Ticket blieb dadurch für immer "blocked"
    # liegen, ohne dass `--work-backlog` je einen weiteren Versuch unternahm.
    "test-regression-",
    # Team-Optimierung (KI-Team-Optimierungs-Session, echter Fund): core/workspace_audit.py
    # eröffnet "audit-<slug>"-Tickets (fehlgeschlagene Re-Verifikation) UND
    # "audit-<slug>-adr-duplicate"-Tickets (Nahezu-Duplikat-ADRs) mit `source="workspace_audit"`
    # - beide Filter unten (Prefix UND source) ließen sie bisher durchfallen, obwohl sie
    # inhaltlich genau dasselbe Muster sind wie die vier Governance-Kategorien oben (rein
    # maschinell erkannt, kein Mensch hat sie bewusst "blocked" gesetzt). Real beobachtet: 7
    # per --audit-workspace eröffnete Tickets blieben deshalb für immer liegen, `--work-backlog`
    # griff sie nie auf. "team-verification-trend" (ebenfalls source="workspace_audit", aber
    # OHNE project_slug und ohne "audit-"-Prefix) bleibt bewusst NICHT retry-fähig - es
    # beschreibt einen teamweiten Trend über viele Projekte hinweg, kein einzelnes, für einen
    # Orchestrator-Lauf sinnvoll formulierbares Fix-Ziel.
    "audit-",
)



# Team-Optimierung (KI-Team-Weiterentwicklung): die Erschöpfungserkennung selbst lebt jetzt in
# core/provider_exhaustion.py (siehe dessen Moduldocstring) - agents/orchestrator/dispatch.py
# braucht dieselbe Logik für den interaktiven Lauf, nicht nur für diesen autonomen Worker-Pfad.
# Lokale Alias-Namen bleiben erhalten, damit bestehende Aufrufer/Tests unten unverändert bleiben.
_is_provider_exhaustion_error = is_provider_exhaustion_error
_all_agents_failed_on_provider_exhaustion = all_failed_on_provider_exhaustion


def _governance_retry_pool(all_tickets: list[Ticket]) -> list[Ticket]:
    """
    Liefert die "blocked"-Governance-/Verifikations-Tickets, die noch nicht
    MAX_GOVERNANCE_TICKET_RETRIES automatische Wiederholungsversuche hinter sich haben - genau
    die Tickets, die ohne diese Funktion für immer unangetastet im Backlog liegen blieben (siehe
    Modul-Docstring). Ein Ticket, das die Grenze bereits erreicht hat, bleibt bewusst "blocked"
    liegen (sichtbar für eine menschliche Prüfung), statt endlos denselben erfolglosen Ansatz zu
    wiederholen.
    """
    return [
        t for t in all_tickets
        if t.status == "blocked"
        and t.source in ("orchestrator", "workspace_audit")
        and t.id.startswith(_GOVERNANCE_RETRY_PREFIXES)
        and t.retries < MAX_GOVERNANCE_TICKET_RETRIES
        and is_ticket_ready(t, all_tickets)[0]
    ]

# Dieselbe Terminal-Status-Zuordnung wie core/issue_watcher.py._OUTCOME_TO_TICKET_STATUS -
# siehe dort für die Begründung je Ausgang.
_OUTCOME_TO_TICKET_STATUS = {
    "pr_opened": "review",
    "pr_opened_ci_failed": "blocked",
    "pr_opened_needs_clarification": "blocked",
}

# Ausgänge OHNE neuen, verwertbaren Erkenntnisgewinn gegenüber dem, was das Ticket vor diesem
# Versuch schon wusste - siehe Kommentar bei ihrer Verwendung in run_backlog_poll_cycle() für
# den vollen Kontext (echter Fund: dauerhaft "blocked" hängende Tickets ohne jeden Ticket-Text).
# "blocked_secret" ist bewusst NICHT enthalten - ein Secret-Fund IST eine neue, wichtige
# Information für die nächste Bearbeitung, kein kontextloser Fehlschlag.
_NON_INFORMATIVE_RETRY_OUTCOMES = ("no_changes", "error")

# Team-Optimierung (echter Fund: memory/backlog.json-Ticket `audit-service_bookmark_monitor`,
# seit über 15 Stunden unverändert "in_progress" hängend): _process_single_ticket() markiert ein
# Ticket "in_progress", BEVOR die eigentliche Arbeit beginnt - stürzt der Prozess danach ab
# (Rechner-Neustart, Absturz, harter Abbruch), bleibt es für IMMER in diesem Zustand: weder
# `ready_todo` (nur "todo") noch `_governance_retry_pool()` (nur "blocked") picken "in_progress"
# je wieder auf. Grosszügig bemessen (deutlich länger als ein realistischer Lauf - laut echten
# Läufen typischerweise Minuten, siehe CHANGELOG.md), damit ein tatsächlich noch laufendes
# Ticket nicht fälschlich als verwaist behandelt wird.
STALE_IN_PROGRESS_HOURS = 3.0


def _recover_stale_in_progress_tickets(all_tickets: list[Ticket]) -> list[str]:
    """
    Setzt Tickets, die seit STALE_IN_PROGRESS_HOURS unverändert "in_progress" sind, auf ihren
    vermutlichen Status VOR dem Aufgreifen zurück - siehe Moduldocstring-Ergänzung oben für den
    vollen Kontext. Governance-/Audit-Retry-Tickets (_GOVERNANCE_RETRY_PREFIXES) waren vorher
    "blocked" (respektiert damit weiterhin `retries`/MAX_GOVERNANCE_TICKET_RETRIES über
    _governance_retry_pool() - kein Umgehen des Wiederholungslimits durch einen Absturz), alle
    anderen (cli/dashboard) waren "todo". Gibt die IDs der wiederhergestellten Tickets zurück.
    """
    now = datetime.now(UTC)
    recovered: list[str] = []
    for t in all_tickets:
        if t.status != "in_progress":
            continue
        try:
            updated = datetime.fromisoformat(t.updated_at)
        except ValueError:
            continue
        if (now - updated).total_seconds() < STALE_IN_PROGRESS_HOURS * 3600:
            continue
        recovered_status = "blocked" if t.id.startswith(_GOVERNANCE_RETRY_PREFIXES) else "todo"
        upsert_ticket(
            ticket_id=t.id, title=t.title, source=t.source, status=recovered_status,
            detail=t.detail, project_slug=t.project_slug,
        )
        recovered.append(t.id)
    return recovered


@dataclass
class BacklogRunResult:
    """Ergebnis der Bearbeitung EINES Tickets in einem Poll-Zyklus."""
    ticket_id: str
    title: str
    outcome: str  # "pr_opened" | "pr_opened_ci_failed" | "pr_opened_needs_clarification" | "no_changes" | "blocked_secret" | "error"
    detail: str = ""


@dataclass
class BacklogPollReport:
    """Ergebnis eines gesamten Poll-Zyklus (ein Aufruf von `python main.py --work-backlog`)."""
    results: list[BacklogRunResult] = field(default_factory=list)
    # Sichtbar statt stumm nichts zu tun, wenn dieser Zyklus bewusst NICHTS aufgegriffen hat
    # (WIP-Limit erreicht, `gh` nicht bereit, oder kein bereites "todo"-Ticket) - dieselbe
    # "niemals stumm überspringen"-Linie wie reason_skipped an anderer Stelle im Projekt.
    skipped_reason: str = ""
    merged_ticket_ids: list[str] = field(default_factory=list)
    # Team-Optimierung (KI-Team-Weiterentwicklung): siehe run_backlog_poll_cycle() für die volle
    # Herleitung - Governance-Retry-Tickets, die GENAU in diesem Zyklus ihren letzten erlaubten
    # automatischen Versuch verbraucht haben (retries erreicht MAX_GOVERNANCE_TICKET_RETRIES) UND
    # weiterhin nicht "pr_opened" erreichten, landen hier zusätzlich zu `results` - für eine
    # Erfolgsmeldung/einen CLI-Hinweis, der diese besonders hervorheben kann, statt sie in der
    # generischen Ergebnisliste untergehen zu lassen.
    retries_exhausted_ticket_ids: list[str] = field(default_factory=list)


async def run_backlog_poll_cycle(
    max_tickets: int | None = None, status_callback: StatusCallback | None = None,
) -> BacklogPollReport:
    """
    Ein einzelner Poll-Durchlauf: greift bis zu `max_tickets` (Standard:
    config.BACKLOG_WORKER_MAX_PER_CYCLE) abhängigkeitsfreie "todo"-Tickets aus `_AUTONOMOUS_
    SOURCES` auf, höchste Priorität zuerst. Wird von außen wiederholt aufgerufen (Cron/
    Taskplaner) – KEINE eigene Schleife/Sleep hier, ein Aufruf = ein Zyklus (dasselbe Prinzip
    wie core/issue_watcher.py.run_issue_poll_cycle()).
    """
    report = BacklogPollReport()
    github_agent = GitHubAgent()
    if not github_agent.gh_ready():
        report.skipped_reason = "`gh`-CLI ist auf diesem System nicht bereit (fehlt/kein Login) - übersprungen."
        return report

    # Merge-Erkennung fürs Backlog (core/merge_watcher.py) opportunistisch mitnehmen, exakt
    # wie core/issue_watcher.py es tut - kein zusätzlicher Cron-Eintrag nötig.
    report.merged_ticket_ids = check_merged_tickets(github_agent)

    # Verwaiste "in_progress"-Tickets zuerst zurücksetzen (siehe _recover_stale_in_progress_
    # tickets()-Docstring) - VOR dem WIP-Limit-Check unten, sonst würde ein längst abgestürzter
    # Prozess über count_by_status("in_progress") auf unbestimmte Zeit echte neue Arbeit
    # blockieren, obwohl niemand mehr daran arbeitet.
    recovered_stale_tickets = _recover_stale_in_progress_tickets(list_tickets())
    if recovered_stale_tickets and status_callback:
        status_callback(
            f"🔁 {len(recovered_stale_tickets)} verwaiste(s) 'in_progress'-Ticket(s) "
            f"(länger als {STALE_IN_PROGRESS_HOURS:.0f}h unverändert - vermutlich abgestürzter "
            f"Lauf) wieder aufgreifbar gemacht: {', '.join(recovered_stale_tickets)}."
        )

    # Dubletten schließen und per Commit referenzierte Tickets erledigen (core/backlog_hygiene.py),
    # damit der Worker keine bereits behobenen oder doppelten Tickets erneut bearbeitet.
    try:
        from core.backlog_hygiene import (
            cancel_duplicates,
            cancel_orphaned_project_tickets,
            cancel_stale_open_tickets,
            close_tickets_referenced_in_commits,
            read_commit_messages,
        )
        hygiene_closed = close_tickets_referenced_in_commits(list_tickets(), read_commit_messages())
        hygiene_cancelled = cancel_duplicates(list_tickets())
        # Backlog-Analyse 2026-09-16: 25 offene Tickets zeigten auf gelöschte Projekte und 45 lagen
        # nie aufgegriffen herum - beides direkt hier abräumen, sonst wächst die Warteschlange mit
        # jedem Poll-Zyklus weiter, ohne dass je jemand `--backlog-hygiene` von Hand aufruft.
        hygiene_orphans = cancel_orphaned_project_tickets(list_tickets())
        # `skip_ids`: die oben gerade wieder aufgegriffenen Tickets nicht im selben Zyklus schließen.
        hygiene_stale = cancel_stale_open_tickets(list_tickets(), skip_ids=recovered_stale_tickets)
        if (hygiene_closed or hygiene_cancelled or hygiene_orphans or hygiene_stale) and status_callback:
            status_callback(
                f"🧹 Backlog-Hygiene: {len(hygiene_closed)} per Commit erledigt, "
                f"{len(hygiene_cancelled)} Dublette(n), {len(hygiene_orphans)} ohne Projekt, "
                f"{len(hygiene_stale)} liegengeblieben geschlossen."
            )
    except Exception as e:  # Hygiene darf den Worker nie blockieren
        logging.getLogger(__name__).warning("Backlog-Hygiene fehlgeschlagen: %r", e)

    # Rote Projekte zur Nachbesserung einplanen (core/red_project_repair.py) - höchstens eins pro
    # Poll, damit ein Worker-Durchlauf nicht das gesamte Token-Budget auf alte Projekte verteilt.
    if RED_PROJECT_REPAIR_PER_POLL > 0:
        try:
            from core.red_project_repair import queue_red_projects
            repair = queue_red_projects(max_new=RED_PROJECT_REPAIR_PER_POLL)
            if repair.queued and status_callback:
                status_callback(f"🔁 Rotes Projekt zur Nachbesserung eingeplant: {', '.join(repair.queued)}")
        except Exception as e:  # noqa: BLE001 - Einplanung darf den Worker nie blockieren
            logging.getLogger(__name__).warning("Rote Projekte konnten nicht eingeplant werden: %r", e)

    if BACKLOG_WORKER_WIP_LIMIT > 0 and count_by_status("in_progress") >= BACKLOG_WORKER_WIP_LIMIT:
        report.skipped_reason = (
            f"WIP-Limit erreicht ({BACKLOG_WORKER_WIP_LIMIT} Ticket(s) gleichzeitig 'in_progress') "
            "- laufende Arbeit wird zuerst abgeschlossen, bevor Neues eigenständig begonnen wird."
        )
        return report

    all_tickets = list_tickets()
    # P1-3 (ROADMAP_TEMP.md, realer Fund 2026-09-20): status=="blocked" mit
    # blocked_reason=="stale" (core/backlog_hygiene.py.recover_stale_in_progress()) ist KEINE
    # inhaltliche Blockade - das Ticket wurde schlicht nie in einem Poll-Zyklus aufgegriffen und
    # unterscheidet sich in nichts von einem frischen "todo". Ohne diese Zeile blieben solche
    # Tickets für immer liegen: das generische "blocked"-Sicherheitsnetz unten
    # (_GOVERNANCE_RETRY_PREFIXES) greift bewusst NUR für bekannte Governance-Präfixe, damit ein
    # Mensch bewusst blockiertes Ticket nicht versehentlich erneut aufgegriffen wird - ein
    # "cli"-Ticket erreicht diesen Präfix nie.
    ready_todo = [
        t for t in all_tickets
        if (t.status == "todo" or (t.status == "blocked" and t.blocked_reason == "stale"))
        and t.source in _AUTONOMOUS_SOURCES and is_ticket_ready(t, all_tickets)[0]
    ]
    # Governance-/Verifikations-Tickets NACH den regulären "todo"-Tickets (niedrigere
    # effektive Priorität als jede echte Priorität 1-3, siehe Sortierung unten) - ein
    # bewusst vom Nutzer/Dashboard eingereichtes Ticket soll nicht hinter einem
    # automatischen Wiederholungsversuch zurückstehen müssen.
    retry_pool = _governance_retry_pool(all_tickets)
    combined = ready_todo + retry_pool
    if not combined:
        report.skipped_reason = "Kein abhängigkeitsfreies 'todo'-Ticket aus cli/dashboard und kein wiederholbares Governance-Ticket im Backlog gefunden."
        return report
    combined.sort(key=lambda t: (t.priority, t.id in {rt.id for rt in retry_pool}))  # 1=hoch zuerst, Retries zuletzt bei gleicher Priorität

    limit = max_tickets if max_tickets is not None else BACKLOG_WORKER_MAX_PER_CYCLE
    for ticket in combined[:limit]:
        is_retry = ticket in retry_pool
        if is_retry:
            if status_callback:
                status_callback(
                    f"🎫 Governance-Ticket `{ticket.id}` wird erneut aufgegriffen "
                    f"(Versuch {ticket.retries + 1}/{MAX_GOVERNANCE_TICKET_RETRIES})..."
                )
            # Zähler VOR dem eigentlichen Versuch erhöhen (nicht erst danach) - ein Absturz
            # mitten im Versuch (siehe try/except in _process_single_ticket) darf nicht dazu
            # führen, dass derselbe Befund unbegrenzt oft ohne Fortschritt erneut versucht wird.
            upsert_ticket(
                ticket_id=ticket.id, title=ticket.title, source=ticket.source,
                status=ticket.status, detail=ticket.detail, project_slug=ticket.project_slug,
                retries=ticket.retries + 1,
            )
        elif status_callback:
            status_callback(f"🎫 Backlog-Ticket `{ticket.id}` '{ticket.title}' wird eigenständig aufgegriffen...")
        result = await _process_single_ticket(github_agent, ticket, status_callback)
        # Team-Optimierung (echter Fund: memory/backlog.json-Tickets `recurring-lint-
        # sentinelproxy`/`recurring-failure-sentinelproxy`, beide dauerhaft "blocked" mit
        # identischem, kontextlosem Detail nach retries=2): ein "no_changes"/"error"-Ausgang
        # überschrieb `detail` bisher IMMER mit der knappen, generischen Ausgangs-Zeile ("Ticket
        # bearbeitet, dabei aber keine Datei geändert...") - für Governance-/Recurring-*-Retry-
        # Tickets ist `ticket.detail` aber der EINZIGE Träger des ursprünglich erkannten Befunds,
        # den _process_single_ticket() oben extra in den Fix-Auftrag mischt (siehe dortiger
        # Kommentar zu `task_text`). Nach GENAU EINEM Fehlschlag ohne neue Erkenntnis war dieser
        # Kontext für JEDEN weiteren automatischen Retry unwiderbringlich weg - jeder folgende
        # Versuch hatte dadurch WENIGER Information als der erste, garantiert kein besseres
        # Ergebnis, bis MAX_GOVERNANCE_TICKET_RETRIES erreicht war und das Ticket für immer
        # "blocked" liegen blieb. Ein Ausgang OHNE neue, verwertbare Information behält den
        # ursprünglichen Befundtext jetzt bei; ein Ausgang mit echtem neuem Erkenntnisgewinn (PR
        # eröffnet, CI-Fehler, Rückfrage, gefundene Secrets) überschreibt ihn wie bisher.
        preserved_detail = (
            ticket.detail
            if (
                ticket.id.startswith(_GOVERNANCE_RETRY_PREFIXES)
                and ticket.detail
                and result.outcome in _NON_INFORMATIVE_RETRY_OUTCOMES
            )
            else result.detail
        )
        # Terminal-Status im Backlog nachziehen (der "in_progress"-Stand wurde bereits beim
        # Aufgreifen geschrieben, siehe _process_single_ticket()) - EIN Mapping-Ort statt an
        # jedem der mehreren Rückgabepunkte dort. Ein Governance-Retry, der erneut nicht
        # "pr_opened" erreicht, bleibt "blocked" (Default von .get() unten) - der bereits oben
        # erhöhte retries-Zähler bleibt dabei erhalten (kein retries=... hier, siehe
        # core/backlog_store.py.upsert_ticket()-Sentinel-Verhalten).
        upsert_ticket(
            ticket_id=ticket.id, title=ticket.title, source=ticket.source,
            status=_OUTCOME_TO_TICKET_STATUS.get(result.outcome, "blocked"), detail=preserved_detail,
        )
        if result.outcome != "pr_opened":
            # Team-Optimierung (KI-Team-Weiterentwicklung, echter Fund: memory/backlog.json-
            # Tickets `recurring-failure-sentinelproxy`/`recurring-lint-sentinelproxy`, beide
            # dauerhaft "blocked" mit retries==MAX_GOVERNANCE_TICKET_RETRIES): der GENAU
            # gleiche, generische Hinweis "Backlog-Ticket benötigt Aufmerksamkeit" feuerte bei
            # JEDEM erfolglosen Versuch - beim finalen, letztlich erfolglosen Versuch (danach
            # greift `_governance_retry_pool()` dieses Ticket NIE wieder auf, siehe deren
            # Docstring) sah die Meldung identisch aus wie bei einem Versuch, dem noch ein
            # weiterer automatischer Retry folgt. Ohne dieses Wissen wirkte ein dauerhaft
            # "blocked" liegendes Ticket wie "wird schon noch automatisch behoben" - bis
            # jemand zufällig `retries`/MAX_GOVERNANCE_TICKET_RETRIES nachschlägt.
            retries_exhausted = (
                is_retry and (ticket.retries + 1) >= MAX_GOVERNANCE_TICKET_RETRIES
            )
            if retries_exhausted:
                report.retries_exhausted_ticket_ids.append(ticket.id)
                await asyncio.to_thread(
                    notify_external,
                    "🛑 Automatische Wiederholungsversuche ausgeschöpft - menschliche Prüfung erforderlich",
                    f"`{result.ticket_id}` '{result.title}': nach {MAX_GOVERNANCE_TICKET_RETRIES} "
                    f"automatischen Versuchen weiterhin nicht gelöst ({result.outcome}) - "
                    "`--work-backlog` greift dieses Ticket nicht mehr eigenständig erneut auf.\n\n"
                    f"{result.detail[:200]}",
                )
            else:
                await asyncio.to_thread(
                    notify_external, "Backlog-Ticket benötigt Aufmerksamkeit",
                    f"`{result.ticket_id}` '{result.title}' ({result.outcome}): {result.detail[:200]}",
                )
        report.results.append(result)
    return report


async def _process_single_ticket(
    github_agent: GitHubAgent, ticket: Ticket, status_callback: StatusCallback | None,
) -> BacklogRunResult:
    # Sofort sichtbar im Backlog/Kanban-Board, nicht erst nach Abschluss - sonst würde ein noch
    # laufendes Ticket auf dem Board gar nicht auftauchen (dasselbe Prinzip wie
    # core/issue_watcher.py._process_single_issue()).
    # Team-Optimierung (echter Fund: memory/backlog.json-Ticket `audit-service_bookmark_
    # monitor`, seit über 15 Stunden verwaist bei status="in_progress" UND detail=""): anders
    # als project_slug/priority/estimate/epic/retries ist `detail` in core/backlog_store.py.
    # upsert_ticket() KEIN Sentinel-Parameter (fester Default `""`, kein "None = unverändert
    # lassen") - dieser Aufruf ohne explizites `detail=` löschte den bereits bekannten Befund
    # damit SOFORT beim Aufgreifen, lange bevor überhaupt ein Ergebnis vorliegt. Stürzt der
    # Prozess danach ab (z.B. Rechner-Neustart mitten im Lauf, echt beobachtet), bleibt das
    # Ticket für immer "in_progress" MIT LEEREM Detail zurück - unsichtbar für jeden künftigen
    # Poll-Zyklus (weder `ready_todo` noch `_governance_retry_pool()` picken "in_progress" auf)
    # UND ohne jeden Kontext für eine spätere manuelle Prüfung. `ticket.detail` explizit
    # mitgeben, damit der bereits bekannte Befund diesen Zwischenschritt unbeschadet übersteht.
    upsert_ticket(
        ticket_id=ticket.id, title=ticket.title, source=ticket.source,
        status="in_progress", detail=ticket.detail,
    )

    original_branch = github_agent.get_current_branch()
    base_branch = original_branch if original_branch in GIT_PROTECTED_BRANCHES else (GIT_PROTECTED_BRANCHES[0] if GIT_PROTECTED_BRANCHES else "main")

    # Best effort: existiert bereits ein Workspace-Projekt mit diesem Slug, arbeitet der Lauf
    # DARIN weiter statt (fälschlich) ein neues zu beginnen. Kein project_slug oder kein
    # existierendes Verzeichnis -> Orchestrator entscheidet wie gewohnt selbst (core/task_
    # manager.py leitet einen Slug aus der Aufgabe ab), exakt wie core/issue_watcher.py es
    # bereits für Issues tut.
    forced_project_dir: str | None = None
    if ticket.project_slug:
        candidate = WorkspaceManager().get_project_dir(ticket.project_slug)
        if candidate.exists():
            forced_project_dir = str(candidate)

    # Ein Governance-/Verifikations-Retry-Ticket trägt im Titel nur eine generische
    # Zusammenfassung ("Ungelöster kritischer Governance-Befund: <slug>") - der eigentliche,
    # für einen Fix-Agenten verwertbare Befundtext steckt in `detail` (siehe
    # agents/orchestrator/verification.py: upsert_ticket(..., detail=finding_text)). Ohne diese
    # Ergänzung bekäme der Orchestrator bei einem Retry nur den generischen Titel und müsste
    # den konkreten Fehler erneut selbst herausfinden, obwohl er bereits bekannt ist.
    task_text = (
        f"{ticket.title}\n\nKonkreter, bereits bekannter Befund (aus einem vorherigen Lauf):\n{ticket.detail}"
        if ticket.id.startswith(_GOVERNANCE_RETRY_PREFIXES) and ticket.detail
        else ticket.title
    )
    # Team-Optimierung (echter Fund, KI-Team-Zustandsbericht 2026-09-08: memory/backlog.json-
    # Tickets `recurring-lint-sentinelproxy`/`recurring-failure-sentinelproxy`,
    # `unresolved-verification-service_bookmark_monitor` - jeweils mit dem Detail "Ticket
    # bearbeitet, dabei aber keine Datei geändert - vermutlich war der Titel nicht eindeutig
    # genug" bzw. "Fixversuch änderte nichts an 1 Testfehler(n)"): ein Governance-Retry mit
    # retries>=1 hat bereits MINDESTENS EINEN automatischen Versuch mit exakt demselben
    # `task_text` hinter sich, der keine (oder eine unwirksame) Änderung erzeugte - denselben
    # vagen Titel/Befundtext unverändert ein zweites Mal zu schicken lieferte real beobachtet
    # NIE ein anderes Ergebnis. Statt darauf zu hoffen, wird der Agent hier explizit angewiesen,
    # die betroffene Datei ERST gezielt zu lokalisieren (Traceback/Testname/Symbolsuche über das
    # bereits verfügbare `find_symbol_definition`-Tool bzw. eine gezielte Textsuche), BEVOR er
    # etwas ändert - siehe `escalate_models` direkt darüber für die parallele Modell-Eskalation
    # bei derselben Bedingung.
    if ticket.id.startswith(_GOVERNANCE_RETRY_PREFIXES) and ticket.retries >= 1:
        task_text += (
            "\n\nHINWEIS: Ein vorheriger automatischer Versuch für dieses Ticket hat KEINE oder "
            "keine wirksame Dateiänderung erzeugt (vermutlich war der Titel/Befund nicht "
            "eindeutig genug, um die betroffene Datei zu identifizieren). Lokalisiere daher ZUERST "
            "gezielt die tatsächlich betroffene Datei (z.B. über das find_symbol_definition-Tool, "
            "eine Textsuche nach dem im Befund genannten Fehler/Testnamen, oder die Testdatei, die "
            "den Fehler auslöst) und ändere dann konkret genau diese Datei - eine erneute Wiederholung "
            "des vorherigen, erfolglosen Versuchs ohne neue Datei-Änderung ist keine akzeptable Lösung."
        )

    # Team-Optimierung (Retrospektive 2026-09-04): `ticket.retries` ist hier noch der Stand VOR
    # dem Zähler-Erhöhen in run_backlog_poll_cycle (derselbe `ticket`, die Erhöhung schreibt nur
    # in den Store, siehe dort) - retries>=1 heißt also "mindestens ein automatischer Backlog-
    # Retry ist bereits gescheitert, das hier ist schon der ZWEITE (oder ein späterer)". Genau
    # dann mit demselben Agenten/Modell wie zuvor weiterzumachen, hätte real beobachtet (siehe
    # Orchestrator.__init__-Docstring) selten zu einem anderen Ergebnis geführt.
    escalate_models = ticket.id.startswith(_GOVERNANCE_RETRY_PREFIXES) and ticket.retries >= 1
    if escalate_models and status_callback:
        status_callback(
            f"⬆️ Governance-Ticket `{ticket.id}` scheiterte bereits an einem vorherigen "
            "automatischen Retry - dieser Versuch nutzt ein stärkeres Modell (HEAVY_MODEL)."
        )

    try:
        orchestrator = Orchestrator(escalate_models=escalate_models)
        final_report = await orchestrator.process(
            task_text, status_callback=status_callback, forced_project_dir=forced_project_dir,
        )
    except Exception as e:
        return BacklogRunResult(ticket.id, ticket.title, "error", str(e))

    # Bugfix (Team-Optimierung, real beobachtet im mockforge-Governance-Retry): der
    # Orchestrator isoliert JEDEN Lauf gegen bereits vorhandenen Inhalt (siehe
    # agents/orchestrator/__init__.py._resolve_project_isolation) in einem separaten
    # Git-Worktree - ohne diese Übertragung sah github_agent.get_status() (läuft immer gegen
    # BASE_DIR, siehe agents/github_agent.py) nie etwas davon, selbst wenn das Team das
    # Ticket nachweislich korrekt bearbeitet hatte. Siehe core/git_isolation.py.
    # copy_worktree_changes_to_target()-Docstring für die volle Herleitung.
    worktree = getattr(orchestrator, "last_isolated_worktree", None)
    # Echter Fund (KI-Team-Optimierungs-Session): ein Lauf, bei dem JEDER Agenten-Aufruf
    # (inkl. aller konfigurierten Fallback-Modelle, siehe core/llm_factory.py.MODEL_FALLBACKS)
    # an einer API-Kontingent-Erschöpfung scheiterte, öffnete trotzdem einen PR - der enthielt
    # ausschließlich automatisch aktualisierte Statusdateien (.ai_team_status.json,
    # PROJECT_STATE.md, ui_screenshot.png; diese werden unabhängig vom Agenten-Erfolg vom
    # Orchestrator selbst geschrieben), keine einzige echte Code-Änderung. Bewusst NUR bei
    # 100% Fehlschlag durch Kontingent-Erschöpfung übersprungen (siehe
    # _all_agents_failed_on_provider_exhaustion()-Docstring) - ein normaler Verifikations-
    # Fehlschlag mit ECHTEN Code-Änderungen öffnet weiterhin wie gewohnt einen (dann als Draft
    # markierten) PR, siehe Moduldocstring oben ("...verwerfen bereits geleistete Arbeit
    # NICHT stillschweigend").
    provider_exhausted = _all_agents_failed_on_provider_exhaustion(
        getattr(orchestrator, "last_agent_results", None) or [],
    )
    if worktree is not None:
        if provider_exhausted:
            if status_callback:
                status_callback(
                    "⏭️ Alle Agenten-Aufrufe scheiterten an einer API-Kontingent-Erschöpfung - "
                    "keine echte Änderung entstanden, Worktree wird verworfen statt einen "
                    "leeren PR zu eröffnen."
                )
            remove_worktree(worktree, force=True)
        else:
            try:
                copied = copy_worktree_changes_to_target(worktree, BASE_DIR)
                if status_callback and copied:
                    status_callback(
                        f"🌳 {len(copied)} Datei(en) aus isoliertem Worktree `{worktree.branch}` "
                        "ins echte Arbeitsverzeichnis übernommen."
                    )
            finally:
                # Worktree danach immer aufräumen (force=True, da die soeben übertragenen
                # Änderungen dort absichtlich als "unkommittiert" zurückbleiben) - ein
                # vollautomatischer Aufrufer hat keinen Menschen, der ihn später manuell prüft.
                remove_worktree(worktree, force=True)

    diff_status = github_agent.get_status()
    if not diff_status:
        detail = (
            "Alle Agenten-Aufrufe scheiterten an einer API-Kontingent-Erschöpfung (429/"
            "RESOURCE_EXHAUSTED) - kein Fortschritt möglich, bitte später erneut versuchen."
            if provider_exhausted else
            "Ticket bearbeitet, dabei aber keine Datei geändert - vermutlich war der Titel nicht eindeutig genug."
        )
        return BacklogRunResult(ticket.id, ticket.title, "no_changes", detail)

    # Kein Mensch zur Bestätigung verfügbar – ein Secret-Fund blockiert deshalb HART, anders
    # als im interaktiven Pfad (interface/cli.py), wo bewusst übersteuert werden kann (siehe
    # dieselbe Begründung in core/issue_watcher.py).
    if github_agent.scan_for_secrets():
        return BacklogRunResult(
            ticket.id, ticket.title, "blocked_secret",
            "Mögliche Secrets in den Änderungen gefunden und den Push abgebrochen - bitte manuell prüfen.",
        )

    # Bugfix (Team-Optimierung, real beobachtet im mockforge-Governance-Retry): base_branch
    # wurde oben rein statisch bestimmt (original_branch, falls dieser bereits ein Hauptbranch
    # ist, sonst blind GIT_PROTECTED_BRANCHES[0]) - existiert das bearbeitete Projekt aber NUR
    # auf original_branch (noch nicht nach main gemerged, ein bei diesem Team etablierter,
    # bewusster Arbeitsmodus für langlebige Feature-Branches), scheiterte `git checkout -b
    # <feature> main` real mit "Your local changes ... would be overwritten by checkout" -
    # main kennt die soeben geänderten Projektdateien schlicht nicht. Siehe
    # agents/github_agent.py.path_exists_in_branch()-Docstring für die volle Herleitung.
    if base_branch != original_branch:
        slug = getattr(orchestrator, "last_project_slug", None) or ticket.project_slug
        if slug:
            project_rel_path = f"{os.path.relpath(WORKSPACE_DIR, BASE_DIR)}/{slug}"
            if not github_agent.path_exists_in_branch(base_branch, project_rel_path):
                base_branch = original_branch

    feature_branch = github_agent.build_feature_branch_name(ticket.title)
    success_b, out_b = github_agent.create_branch(feature_branch, base=base_branch)
    if not success_b:
        return BacklogRunResult(ticket.id, ticket.title, "error", out_b)

    commit_msg = f"feat: {ticket.title[:60]} (Backlog {ticket.id}) via AI Developer Team"
    success_c, out_c = github_agent.commit(commit_msg)
    if not success_c:
        return BacklogRunResult(ticket.id, ticket.title, "error", out_c)

    success_p, out_p = github_agent.push(branch=feature_branch)
    if not success_p:
        return BacklogRunResult(ticket.id, ticket.title, "error", out_p)

    verification_ok = getattr(orchestrator, "last_verification_ok", False)
    needs_human_input = getattr(orchestrator, "last_needs_human_input", False)
    clarification_questions = getattr(orchestrator, "last_clarification_questions", [])

    clarification_flag = (
        "❓ **Offene Rückfrage(n):**\n" + "\n".join(f"- {q}" for q in clarification_questions) + "\n\n"
        if needs_human_input else ""
    )
    verification_flag = (
        "" if verification_ok else
        "⚠️ **Verifikation nicht bestanden** – bitte vor dem Merge besonders genau prüfen.\n\n"
    )
    # final_report gedeckelt, damit ein sehr großer Fachbereichs-Bericht den PR-Body nicht
    # unbegrenzt aufbläht (dieselbe Vorsicht wie core/issue_watcher.py).
    pr_body = (
        f"{clarification_flag}{verification_flag}Automatisch aus dem Backlog aufgegriffen vom "
        f"KI-Softwareentwickler-Team.\n\nTicket: `{ticket.id}`\n\n---\n\n{final_report[:3000]}"
    )
    success_pr, pr_out = github_agent.create_pull_request(
        title=commit_msg, body=pr_body, base=base_branch, head=feature_branch,
        draft=needs_human_input or not verification_ok,
    )
    # Bewusst KEIN Zurückwechseln zum Hauptbranch mehr - dieselbe Begründung wie
    # core/issue_watcher.py: ein Checkout weg vom Feature-Branch würde jede nur dort committete
    # Datei aus dem Arbeitsverzeichnis entfernen, bis der PR gemerged ist.
    if not success_pr:
        return BacklogRunResult(ticket.id, ticket.title, "error", pr_out)

    pr_url = pr_out.splitlines()[-1] if pr_out else pr_out

    # Team-Optimierung (KI-Team-Zustandsbericht 2026-09-08, echte PR-Review-Kommentare): dieselbe
    # Ergänzung wie interface/cli.py._ask_for_git_push() - unbehobene kritische Governance-/
    # Permission-Blocked-Funde landen sonst NUR im unresolved-*-Backlog-Ticket, unsichtbar für
    # einen Reviewer, der nur den PR selbst öffnet. Best-effort: ein fehlgeschlagener Review-Post
    # darf den bereits erfolgreich erstellten PR nicht verwerfen (siehe github_agent.post_pr_
    # review()-Docstring), deshalb wird das Ergebnis hier bewusst nicht ausgewertet.
    unresolved_findings = getattr(orchestrator, "last_unresolved_review_findings", [])
    if unresolved_findings:
        github_agent.post_pr_review(pr_url, unresolved_findings)

    # Eine offene Rückfrage ist wichtiger als das CI-Ergebnis (das kann durchaus grün sein,
    # obwohl eine fachliche Frage offen ist) - deshalb vor der CI-Prüfung behandelt.
    if needs_human_input:
        return BacklogRunResult(ticket.id, ticket.title, "pr_opened_needs_clarification", pr_url)

    ci_status, ci_detail = await github_agent.wait_for_ci_status(feature_branch)
    if ci_status == "failed":
        return BacklogRunResult(ticket.id, ticket.title, "pr_opened_ci_failed", f"{pr_url} (CI fehlgeschlagen: {ci_detail})")
    return BacklogRunResult(ticket.id, ticket.title, "pr_opened", pr_url)
