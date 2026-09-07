"""
core/production_monitor.py – Produktions-Monitoring für per `/deploy-cloud --real` deployte
Projekte (On-Call/SRE-Verhalten nach dem Go-Live)

Realer Fund: core/cloud_deployment.py kann ein Projekt echt live deployen (Fly.io/Vercel), aber
danach schaute NIEMAND mehr hin - `resilience_guard` (Agenten-Rolle) entwirft resilienten Code
(Circuit Breaker, Retries), überwacht aber keine bereits LAUFENDE Instanz. Das ist genau der
Unterschied zwischen "Code, der robust GESCHRIEBEN ist" und "ein Team, das nach dem Launch
noch hinschaut" - ein echtes Team hat für Zweiteres On-Call/Monitoring, nicht nur Code-Review.

Ein einzelner Poll-Durchlauf (aufgerufen über `python main.py --check-deployments`, z.B. per
Cron/Taskplaner/GitHub-Actions-Schedule, analog zu core/issue_watcher.py):
1. Findet jedes workspace/*-Projekt mit einem gespeicherten Deployment (core/deployment_status.py,
   nur ECHTE Deploys - core/cloud_deployment.py.deploy(dry_run=True) legt bewusst nichts ab,
   siehe interface/cli.py._deploy_cloud_with_confirmation()).
2. Führt einen ECHTEN HTTP-Request gegen die deployte URL aus (keine reine Ping-Prüfung -
   derselbe Request, den ein echter Nutzer auslösen würde).
3. Bei einem Ausfall: eröffnet (oder aktualisiert) ein Backlog-Ticket mit hoher Priorität UND
   benachrichtigt extern (core/notifier.py) - ein Ausfall bleibt so nicht unbemerkt, bis ein
   Mensch zufällig selbst nachschaut.
4. Bei Wiederherstellung: schließt ein zuvor durch diesen Monitor eröffnetes Ticket automatisch
   - ein echtes On-Call-Team löst einen Incident auch, sobald der Service wieder erreichbar
   ist, nicht erst nach manueller Nachprüfung.

Bewusst NICHT von core/backlog_worker.py aufgegriffen (source="monitor" ist absichtlich NICHT
in dessen _AUTONOMOUS_SOURCES enthalten): ein Ausfall kann eine echte Infrastruktur-/DNS-/
Billing-Ursache haben, die kein Code-Fix löst - das autonom als "Programmierauftrag"
misszuverstehen und blind einen PR dagegen zu öffnen wäre riskanter als ein sichtbares,
priorisiertes Ticket, das ein Mensch zuerst einordnet.
"""

import asyncio
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from config import DEPLOYMENT_HEALTH_CHECK_TIMEOUT_SECONDS, WORKSPACE_DIR
from core.backlog_store import list_tickets, upsert_ticket
from core.deployment_status import list_all_deployments, record_health_check
from core.notifier import notify_external

StatusCallback = Callable[[str], None]

# Ein Ticket pro überwachtem Projekt, deterministisch aus dem Slug abgeleitet (statt einer
# zufälligen UUID) - genau EIN offenes Ticket pro Projekt, egal wie oft ein Ausfall erneut
# auftritt, statt bei jedem Poll-Zyklus ein neues Duplikat anzulegen.
_TICKET_ID_PREFIX = "monitor-"

# Terminal-Ticket-Status, die auf einen NOCH OFFENEN, vom Monitor selbst eröffneten Incident
# hindeuten - "done"/"cancelled" gelten als bereits geschlossen (z.B. von einem Menschen).
_OPEN_INCIDENT_STATUSES = ("todo", "in_progress", "blocked")


@dataclass
class DeploymentHealthResult:
    """Ergebnis EINER Erreichbarkeitsprüfung."""
    project_slug: str
    url: str
    healthy: bool
    detail: str = ""


@dataclass
class DeploymentHealthReport:
    """Ergebnis eines gesamten Poll-Zyklus (ein Aufruf von `python main.py --check-deployments`)."""
    checked: list[DeploymentHealthResult] = field(default_factory=list)


def _check_url(url: str, timeout: float) -> tuple[bool, str]:
    """
    Echter HTTP-GET gegen die deployte URL - kein reiner Ping, sondern derselbe Request, den
    ein echter Nutzer auslösen würde. Jeder Statuscode < 500 gilt als "erreichbar" (auch
    404/eine Weiterleitung ist die App, die antwortet - kein Server-/Infrastruktur-Ausfall);
    >=500 oder eine Netzwerk-Exception (Timeout, DNS-Fehler, Verbindung abgelehnt) gelten als
    echter Ausfall.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ai-team-production-monitor"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - feste, selbst gespeicherte HTTPS-Deploy-URL, kein Nutzereingabe-Pfad
            return resp.status < 500, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        return e.code < 500, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)[:200]


async def wait_for_health(
    url: str, attempts: int = 5, delay_seconds: float = 3.0,
    timeout: float = DEPLOYMENT_HEALTH_CHECK_TIMEOUT_SECONDS,
) -> DeploymentHealthResult:
    """
    Sofortiger Post-Deploy-Health-Check: unmittelbar NACH einem erfolgreichen `deploy_project()`/
    `CloudDeploymentManager.deploy()`-Aufruf, statt erst beim nächsten periodischen
    `python main.py --check-deployments`-Zyklus. Realer Fund (KI-Team-Analyse 07.09.2026): ein
    "✅ Deployment erfolgreich" bedeutete bisher nur, dass der Deploy-BEFEHL selbst (docker/
    flyctl/vercel) mit Exit-Code 0 zurückkam - ob der Service danach tatsächlich unter der
    Ziel-URL antwortet (Endpunkte erreichbar, kein Crash-Loop beim Boot), blieb bis zum nächsten
    manuell/per Cron ausgelösten Monitor-Zyklus ungeprüft.

    Nutzt dieselbe `_check_url()`-Logik (jeder Statuscode < 500 gilt als erreichbar) wie der
    periodische Monitor-Zyklus oben, aber mit mehreren Versuchen statt nur einem: ein frisch
    gestarteter Container/eine frisch ausgerollte Cloud-Instanz braucht oft ein paar Sekunden,
    bis der Anwendungsprozess wirklich auf dem Port lauscht - ein einzelner sofortiger Check
    direkt nach `docker run`/`flyctl deploy` würde sonst systematisch fälschlich "nicht
    erreichbar" melden, obwohl der Service kurz danach normal hochkommt.
    """
    detail = "kein Versuch unternommen"
    for attempt in range(1, attempts + 1):
        healthy, detail = await asyncio.to_thread(_check_url, url, timeout)
        if healthy:
            return DeploymentHealthResult(project_slug="", url=url, healthy=True, detail=detail)
        if attempt < attempts:
            await asyncio.sleep(delay_seconds)
    return DeploymentHealthResult(project_slug="", url=url, healthy=False, detail=detail)


async def run_deployment_health_check_cycle(status_callback: StatusCallback | None = None) -> DeploymentHealthReport:
    """
    Ein einzelner Poll-Durchlauf über ALLE per `/deploy-cloud --real` deployten Projekte. Wird
    von außen wiederholt aufgerufen (Cron/Taskplaner) – KEINE eigene Schleife/Sleep hier,
    dasselbe Prinzip wie core/issue_watcher.py.run_issue_poll_cycle().
    """
    report = DeploymentHealthReport()
    deployments = list_all_deployments(WORKSPACE_DIR)

    for project_slug, data in deployments:
        url = data.get("url", "")
        if not url:
            continue
        if status_callback:
            status_callback(f"🩺 Prüfe Deployment von `{project_slug}` ({url})...")

        healthy, detail = await asyncio.to_thread(_check_url, url, DEPLOYMENT_HEALTH_CHECK_TIMEOUT_SECONDS)
        record_health_check(Path(WORKSPACE_DIR) / project_slug, healthy=healthy, detail=detail)

        ticket_id = f"{_TICKET_ID_PREFIX}{project_slug}"
        if not healthy:
            upsert_ticket(
                ticket_id=ticket_id, title=f"🚨 Deployment nicht erreichbar: {project_slug}",
                source="monitor", status="todo", detail=f"{url} – {detail}",
                project_slug=project_slug, priority=1,
            )
            await asyncio.to_thread(
                notify_external, "Deployment nicht erreichbar",
                f"{project_slug} ({url}): {detail}",
            )
        else:
            existing = next(
                (t for t in list_tickets() if t.id == ticket_id and t.status in _OPEN_INCIDENT_STATUSES), None,
            )
            if existing:
                upsert_ticket(
                    ticket_id=ticket_id, title=existing.title, source="monitor", status="done",
                    detail=f"Wieder erreichbar: {detail}", project_slug=project_slug,
                )

        report.checked.append(DeploymentHealthResult(project_slug, url, healthy, detail))

    return report
