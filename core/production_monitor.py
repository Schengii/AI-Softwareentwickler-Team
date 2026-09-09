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
    # Team-Optimierung (KI-Team-Zustandsbericht 2026-09-08): gesetzt, wenn der Server zwar
    # erreichbar ist (healthy=True, Statuscode < 500), der Response-Body aber einen eindeutigen
    # Fehler-Marker enthält (siehe _scan_response_body_for_errors()) - "erreichbar, aber echte
    # Nutzer sehen einen Fehler" ist ein ANDERER, milderer Zustand als "Server tot", verdient
    # aber trotzdem ein sichtbares Signal statt stillschweigend als "ok" durchzugehen.
    error_signal: str = ""


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


# Team-Optimierung (KI-Team-Zustandsbericht 2026-09-08, "echtes Fehler-Feedback aus
# Produktion"): _check_url() prüfte bisher AUSSCHLIESSLICH den HTTP-Statuscode - ein häufiges,
# reales Muster ist aber, dass ein Framework eine Ausnahme intern abfängt und trotzdem mit
# Statuscode 200 eine "freundliche" Fehlerseite ausliefert (klassisches Beispiel: ein Flask-/
# Django-Debug-Traceback, der als normale HTML-Seite mit 200 zurückkommt) - so ein Ausfall wäre
# für _check_url() bisher unsichtbar gewesen ("Server ist tot" ist nicht dasselbe wie "Server
# antwortet, aber echte Nutzer sehen einen Fehler"). Bewusst eine kleine, konservative Liste
# eindeutiger Marker statt eines aggressiven Musters wie "error" (viel zu viele Fehlalarme,
# z.B. eine Login-Seite mit dem Text "Fehlerhafte Anmeldedaten" ist kein App-Ausfall).
_ERROR_BODY_MARKERS: tuple[str, ...] = (
    "Internal Server Error",
    "Traceback (most recent call last)",
    "500 Internal Server Error",
    "Application Error",  # Heroku-typische Crash-Seite
    "An unhandled exception occurred",
    "UNCAUGHT EXCEPTION",
)

# Nur die ersten N Zeichen des Response-Bodys scannen - ein Fehler-Marker steht bei den oben
# gelisteten Frameworks immer nahe am Seitenanfang (Titel/Überschrift), ein unbegrenzter Read
# würde bei einer großen, gesunden Seite unnötig viele Daten herunterladen.
_ERROR_BODY_SCAN_CHARS = 20_000


def _scan_response_body_for_errors(url: str, timeout: float) -> str:
    """
    Lädt (best effort) die ersten _ERROR_BODY_SCAN_CHARS des Response-Bodys erneut herunter und
    prüft auf _ERROR_BODY_MARKERS - NUR aufgerufen, wenn _check_url() bereits `healthy=True`
    gemeldet hat (ein Statuscode >=500 ist bereits eindeutig ein Ausfall, dafür braucht es
    keinen zusätzlichen Body-Scan). Gibt den gefundenen Marker zurück, oder "" bei keinem Fund
    ODER JEDEM Problem beim erneuten Abruf (z.B. Timeout) - dieser Zusatz-Check darf das
    Gesamtergebnis eines ansonsten erreichbaren Deployments nie zum Absturz bringen.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ai-team-production-monitor"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - feste, selbst gespeicherte HTTPS-Deploy-URL, kein Nutzereingabe-Pfad
            body = resp.read(_ERROR_BODY_SCAN_CHARS).decode("utf-8", errors="replace")
    except Exception:
        return ""
    for marker in _ERROR_BODY_MARKERS:
        if marker in body:
            return marker
    return ""


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

        # Bewusst NUR geprüft/getoggelt, wenn healthy=True: bei einem vollständigen Ausfall
        # (healthy=False) ist der oben bereits eröffnete "nicht erreichbar"-Vorfall das
        # relevante, schwerwiegendere Signal - ein bestehendes Degraded-Ticket dann fälschlich
        # als "Fehler-Marker nicht mehr gefunden" zu schließen (weil schlicht nie gescannt
        # wurde) würde einen VERSCHLECHTERTEN Zustand als Verbesserung ausgeben.
        error_signal = ""
        degraded_ticket_id = f"{ticket_id}-degraded"
        if healthy:
            error_signal = await asyncio.to_thread(
                _scan_response_body_for_errors, url, DEPLOYMENT_HEALTH_CHECK_TIMEOUT_SECONDS,
            )
            if error_signal:
                upsert_ticket(
                    ticket_id=degraded_ticket_id,
                    title=f"⚠️ Deployment erreichbar, aber Fehlerseite erkannt: {project_slug}",
                    source="monitor", status="todo", priority=2, project_slug=project_slug,
                    detail=(
                        f"{url} antwortet mit {detail}, der Response-Body enthält aber den "
                        f"Fehler-Marker \"{error_signal}\" - echte Nutzer sehen vermutlich einen "
                        "Fehler, auch wenn der Server selbst erreichbar ist."
                    ),
                )
            else:
                existing_degraded = next(
                    (t for t in list_tickets() if t.id == degraded_ticket_id and t.status in _OPEN_INCIDENT_STATUSES), None,
                )
                if existing_degraded:
                    upsert_ticket(
                        ticket_id=degraded_ticket_id, title=existing_degraded.title, source="monitor",
                        status="done", detail="Fehler-Marker im Response-Body nicht mehr gefunden.",
                        project_slug=project_slug,
                    )

        report.checked.append(DeploymentHealthResult(project_slug, url, healthy, detail, error_signal))

    return report
