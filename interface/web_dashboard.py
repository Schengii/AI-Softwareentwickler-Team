"""
interface/web_dashboard.py – Echtes, funktionsfähiges Web-Dashboard für das KI-Team

Vorher war dieses Modul reine UI-Attrappe: nirgends im Projekt aufgerufen (main.py/cli.py
verwiesen nie darauf), und der "Projekt-Entwicklung starten"-Button löste serverseitig gar
nichts aus – nur eine statische Textanzeige im Browser, kein einziger echter Request.
`/api/status` lieferte fest verdrahtete Werte ("32 Spezialisten", inzwischen 33).

Jetzt:
- Startbar über `python main.py --dashboard` oder `python -m interface.web_dashboard`.
- "Start"-Button sendet die Aufgabe wirklich per POST an /api/run, die dann echt über
  Orchestrator.process() läuft (in einem seriellen Hintergrund-Worker – siehe unten).
- Live-Fortschritt via Polling von /api/status/<job_id>, inkl. echter Status-Callback-Zeilen
  (dieselben, die auch die CLI anzeigt) und dem finalen Ergebnis.
- /api/status liefert echte Werte aus der laufenden Orchestrator-Instanz statt Konstanten.

Mehrere Jobs können jetzt tatsächlich GLEICHZEITIG laufen (config.DASHBOARD_MAX_CONCURRENT_JOBS,
Standard 2) – bewusst NICHT über mehrere OS-Threads (das würde echte Thread-Sicherheits-Arbeit
an allen geteilten globalen Zuständen erfordern: token_guard, agent_knowledge_base,
memory/cost_history.json, ...), sondern über EINEN persistenten asyncio-Event-Loop in einem
einzigen Hintergrund-Thread, in dem mehrere process()-Coroutinen nebeneinander laufen (siehe
_dispatch_loop/_execute_job) – Python/asyncio garantiert dabei, dass jede synchrone Operation
(z.B. ein Dict-Update) ungestört zu Ende läuft, bevor die nächste Coroutine an die Reihe kommt.
Jeder Job bekommt dabei eine FRISCHE, isolierte Orchestrator-Instanz (eigene
ConversationHistory) statt einer geteilten – das war der eigentliche Grund für die frühere
Serialisierung (eine geteilte ConversationHistory hätte sich bei gleichzeitigen Jobs vermischt).
`self.orchestrator` bleibt als EINE feste Instanz nur für /api/status-Metadaten (Agentenliste)
erhalten, wird aber nie für echte Jobs verwendet.

Sicherheit (siehe config.DASHBOARD_HOST/DASHBOARD_AUTH_TOKEN): Vorher band der Server per
`ThreadingHTTPServer(("", port), ...)` auf ALLE Netzwerk-Interfaces, ohne jede Authentifizierung
– jeder im selben Netzwerk konnte über POST /api/run einen vollen Agentenlauf mit echtem
Datei-/Kommandozugriff (run_command/pip/npm) auslösen. Jetzt: Standard-Bind ist 127.0.0.1
(nur lokal erreichbar), und run_dashboard() verweigert den Start auf einer nicht-lokalen
Adresse, solange kein DASHBOARD_AUTH_TOKEN gesetzt ist. Ist ein Token gesetzt, verlangt
JEDER Request einen gültigen "Authorization: Bearer <token>"-Header (oder "?token=").
"""

import asyncio
import contextlib
import hmac
import json
import os
import queue
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from agents.orchestrator import Orchestrator
from config import DASHBOARD_AUTH_TOKEN, DASHBOARD_HOST, DASHBOARD_MAX_CONCURRENT_JOBS
from core.backlog_store import list_tickets, upsert_ticket
from core.notifier import notify_external
from memory.run_history import get_agent_success_rates, get_recent_runs

MAX_LOG_LINES_KEPT = 500
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


@dataclass
class Job:
    job_id: str
    prompt: str
    status: str = "queued"  # queued -> running -> done | error | cancelled
    log: list[str] = field(default_factory=list)
    result: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.monotonic)
    cancel_requested: bool = False
    listeners: list[Any] = field(default_factory=list)


class DashboardServer:
    """
    Hält die Job-Liste und einen persistenten Hintergrund-Event-Loop, in dem bis zu
    config.DASHBOARD_MAX_CONCURRENT_JOBS Jobs gleichzeitig laufen können. `self.orchestrator`
    ist eine feste Instanz NUR für /api/status-Metadaten (Agentenliste) – echte Jobs bekommen
    in _execute_job() jeweils eine frische, isolierte Instanz.
    """

    def __init__(self, max_concurrent_jobs: int = DASHBOARD_MAX_CONCURRENT_JOBS):
        self.orchestrator = Orchestrator()
        self.jobs: dict[str, Job] = {}
        # Deploy-Status pro Projektname (core/deployment.py) - EIN aktueller Stand pro
        # Projekt reicht (kein History-Log wie bei Jobs), da /deploy manuell pro Projekt
        # ausgelöst wird, nicht als Warteschlange vieler Anfragen.
        self.deployments: dict[str, dict] = {}
        self._max_concurrent_jobs = max_concurrent_jobs
        self._loop = asyncio.new_event_loop()
        self._async_queue: asyncio.Queue[str] | None = None  # im Loop-Thread erzeugt, siehe _run_event_loop
        self._dispatch_task: asyncio.Task | None = None  # im Loop-Thread erzeugt, siehe _run_event_loop
        loop_ready = threading.Event()
        self._thread = threading.Thread(target=self._run_event_loop, args=(loop_ready,), daemon=True)
        self._thread.start()
        loop_ready.wait(timeout=5)

    def _run_event_loop(self, loop_ready: threading.Event) -> None:
        asyncio.set_event_loop(self._loop)
        self._async_queue = asyncio.Queue()
        loop_ready.set()
        self._dispatch_task = self._loop.create_task(self._dispatch_loop())
        self._loop.run_forever()

    async def _dispatch_loop(self) -> None:
        """Zieht Job-IDs von der Queue und startet für jede eine eigene Task, gedeckelt durch
        ein Semaphore auf max_concurrent_jobs gleichzeitig LAUFENDE (nicht wartende) Jobs."""
        semaphore = asyncio.Semaphore(self._max_concurrent_jobs)

        async def _run_with_semaphore(job_id: str) -> None:
            async with semaphore:
                await self._execute_job(job_id)

        while True:
            job_id = await self._async_queue.get()
            self._loop.create_task(_run_with_semaphore(job_id))

    def enqueue(self, prompt: str) -> str:
        job_id = uuid.uuid4().hex[:12]
        self.jobs[job_id] = Job(job_id=job_id, prompt=prompt)
        # Sofort im Backlog sichtbar (core/backlog_store.py) - dieselbe Ticket-Quelle, die
        # auch core/issue_watcher.py und interface/cli.py befüllen, damit das Kanban-Board
        # ALLE Trigger-Quellen zeigt, nicht nur Dashboard-Jobs.
        upsert_ticket(ticket_id=f"dashboard-{job_id}", title=prompt[:80], source="dashboard", status="todo")
        # call_soon_threadsafe: enqueue() wird vom HTTP-Handler-Thread aufgerufen, die Queue
        # gehört aber dem Event-Loop-Thread - asyncio.Queue.put_nowait() ist NICHT threadsafe.
        self._loop.call_soon_threadsafe(self._async_queue.put_nowait, job_id)
        return job_id

    def cancel(self, job_id: str) -> bool:
        """Markiert einen Job zum Abbruch - eine laufende Ausführung sieht das beim nächsten
        Prüfpunkt (vor jeder Fachbereichs-Phase/jedem Fixversuch). Ein noch wartender Job wird
        direkt als abgebrochen markiert, ohne je zu starten. Gibt False zurück, wenn die
        job_id unbekannt oder der Job bereits abgeschlossen ist."""
        job = self.jobs.get(job_id)
        if not job or job.status in ("done", "error", "cancelled"):
            return False
        job.cancel_requested = True
        if job.status == "queued":
            job.status = "cancelled"
        return True

    def shutdown(self, timeout: float = 5.0) -> None:
        """
        Stoppt den Hintergrund-Event-Loop-Thread wieder sauber. Der Produktivbetrieb
        (`run_dashboard()`) läuft absichtlich bis zum Prozessende und ruft dies nie auf – aber
        Tests, die pro Testklasse eine eigene `DashboardServer()`-Instanz erzeugen (siehe
        tests/test_web_dashboard.py, tests/test_observability_endpoint.py), MÜSSEN ihn
        aufrufen: `self._loop.run_forever()` liefe sonst als daemon-Thread unbegrenzt über das
        Testende hinaus weiter. Realer Fund: mit zwei solchen Testdateien in derselben
        `unittest discover`-Suite blieben zwei dauerhaft laufende Event-Loops gleichzeitig im
        Prozess zurück – die volle Suite hing sich dabei reproduzierbar minutenlang auf,
        obwohl jede Datei einzeln ausgeführt in unter 2s durchlief.

        Cancelt zusätzlich den dauerhaft laufenden `_dispatch_loop()`-Task VOR dem Stoppen
        des Loops (Bugfix aus Code-Review): vorher wurde nur `loop.stop()` aufgerufen, der
        `while True`-Dispatch-Task blieb dabei als "pending" hängen und wurde erst beim
        Garbage-Collect zerstört - sichtbar als `Task was destroyed but it is pending!`/
        `RuntimeError: Event loop is closed`-Rauschen am Ende jedes Testlaufs mit mehreren
        DashboardServer-Instanzen. Rein kosmetisch (keine Tests schlugen dadurch fehl), aber
        ein sauberer Shutdown sollte keine offenen Tasks lautlos zurücklassen.
        """
        async def _cancel_dispatch_and_stop() -> None:
            if self._dispatch_task is not None:
                self._dispatch_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._dispatch_task
            self._loop.stop()

        if self._loop.is_running():
            asyncio.run_coroutine_threadsafe(_cancel_dispatch_and_stop(), self._loop)
        else:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=timeout)

    async def _execute_job(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if not job or job.status == "cancelled":
            if job:
                upsert_ticket(ticket_id=f"dashboard-{job_id}", title=job.prompt[:80], source="dashboard", status="cancelled")
                for q in list(job.listeners):
                    try:
                        q.put_nowait({"type": "status", "status": "cancelled", "result": "", "error": ""})
                    except Exception:
                        pass
            return  # bereits vor dem Start abgebrochen (siehe cancel())
        job.status = "running"
        upsert_ticket(ticket_id=f"dashboard-{job_id}", title=job.prompt[:80], source="dashboard", status="in_progress")
        for q in list(job.listeners):
            try:
                q.put_nowait({"type": "status", "status": "running", "result": "", "error": ""})
            except Exception:
                pass

        job_orchestrator = Orchestrator()

        def on_status(msg: str, _job=job):
            clean = re.sub(r"\[/?[a-zA-Z0-9 _]+\]", "", msg)  # rich-Markup entfernen
            _job.log.append(clean)
            if len(_job.log) > MAX_LOG_LINES_KEPT:
                del _job.log[: len(_job.log) - MAX_LOG_LINES_KEPT]
            for q in list(_job.listeners):
                try:
                    q.put_nowait({"type": "log", "line": clean})
                except Exception:
                    pass

        try:
            result = await job_orchestrator.process(
                job.prompt, status_callback=on_status,
                cancel_requested=lambda _job=job: _job.cancel_requested,
            )
            job.result = result
            job.status = "cancelled" if job.cancel_requested and "Manuell abgebrochen" in result else "done"
        except Exception as e:
            job.error = str(e)
            job.status = "error"

        for q in list(job.listeners):
            try:
                q.put_nowait({"type": "status", "status": job.status, "result": job.result, "error": job.error})
            except Exception:
                pass

        ticket_status = "blocked" if job.status == "error" else job.status
        upsert_ticket(ticket_id=f"dashboard-{job_id}", title=job.prompt[:80], source="dashboard", status=ticket_status)
        if ticket_status == "blocked":
            await asyncio.to_thread(
                notify_external, "Dashboard-Job fehlgeschlagen",
                f"'{job.prompt[:80]}': {job.error or 'unbekannter Fehler'}",
            )

    def deploy(self, project_name: str) -> None:
        """Startet ein echtes lokales Docker-Deployment für ein Workspace-Projekt
        (core/deployment.py) - läuft im Hintergrund-Event-Loop, Status via
        GET /api/deploy-status/<projekt> pollbar (dasselbe Prinzip wie Jobs)."""
        self.deployments[project_name] = {"status": "running"}
        self._loop.call_soon_threadsafe(self._loop.create_task, self._execute_deploy(project_name))

    async def _execute_deploy(self, project_name: str) -> None:
        from core.deployment import deploy_project
        project_dir = self.orchestrator._workspace.get_project_dir(project_name)
        try:
            # asyncio.to_thread: deploy_project() ist blockierend (echte Subprozesse) - direkt
            # im Event-Loop aufgerufen würde es ALLE anderen Jobs/Deploys in diesem Prozess
            # für die Dauer des Docker-Builds blockieren.
            result = await asyncio.to_thread(deploy_project, project_dir)
        except Exception as e:
            self.deployments[project_name] = {"status": "error", "output": str(e)}
            return
        self.deployments[project_name] = {
            "status": "done" if result.attempted else "skipped",
            "success": result.success, "method": result.method,
            "urls": result.urls, "output": result.output, "reason_skipped": result.reason_skipped,
        }

    def stop_deploy(self, project_name: str) -> None:
        """Fährt ein per deploy() gestartetes Deployment wieder herunter."""
        self.deployments[project_name] = {"status": "stopping"}
        self._loop.call_soon_threadsafe(self._loop.create_task, self._execute_stop_deploy(project_name))

    async def _execute_stop_deploy(self, project_name: str) -> None:
        from core.deployment import stop_deployment
        project_dir = self.orchestrator._workspace.get_project_dir(project_name)
        try:
            result = await asyncio.to_thread(stop_deployment, project_dir)
        except Exception as e:
            self.deployments[project_name] = {"status": "error", "output": str(e)}
            return
        self.deployments[project_name] = {
            "status": "stopped" if result.success else "error",
            "success": result.success, "method": result.method, "output": result.output,
        }


HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>KI-Softwareentwickler-Team Dashboard</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-dark: #0d1117; --card-bg: #161b22; --card-border: #30363d;
      --accent: #58a6ff; --accent-green: #2ea043; --text-main: #c9d1d9;
      --text-muted: #8b949e; --text-white: #f0f6fc;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background-color: var(--bg-dark); color: var(--text-main); font-family: 'Inter', sans-serif; padding: 24px; line-height: 1.5; }
    .header { display: flex; justify-content: space-between; align-items: center; padding-bottom: 20px; border-bottom: 1px solid var(--card-border); margin-bottom: 28px; }
    .header h1 { font-size: 24px; color: var(--text-white); display: flex; align-items: center; gap: 10px; }
    .badge { background: rgba(88, 166, 255, 0.15); color: var(--accent); padding: 4px 12px; border-radius: 20px; font-size: 13px; font-weight: 600; border: 1px solid rgba(88, 166, 255, 0.3); }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; margin-bottom: 28px; }
    .card { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px; padding: 20px; }
    .card h3 { color: var(--text-white); font-size: 16px; margin-bottom: 8px; }
    .member-tag { display: inline-block; background: #21262d; color: #e6edf3; padding: 3px 8px; border-radius: 6px; font-size: 11px; font-family: 'JetBrains Mono', monospace; margin: 2px; border: 1px solid #30363d; }
    .prompt-box { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px; padding: 20px; margin-bottom: 28px; }
    textarea { width: 100%; height: 90px; background: #0d1117; border: 1px solid var(--card-border); border-radius: 8px; color: #f0f6fc; padding: 12px; font-family: inherit; resize: vertical; margin-top: 10px; }
    button { background: var(--accent-green); color: white; border: none; padding: 10px 20px; border-radius: 8px; font-weight: 600; cursor: pointer; margin-top: 12px; }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    #cancelBtn { background: #da3633; margin-left: 10px; display: none; }
    #logPanel { display: none; background: #010409; border: 1px solid var(--card-border); border-radius: 12px; padding: 16px; margin-bottom: 28px; }
    #logOutput { font-family: 'JetBrains Mono', monospace; font-size: 12.5px; white-space: pre-wrap; max-height: 340px; overflow-y: auto; color: var(--text-main); }
    #resultOutput { font-family: 'JetBrains Mono', monospace; font-size: 12.5px; white-space: pre-wrap; margin-top: 12px; color: var(--text-white); }
    .kanban { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin-bottom: 28px; }
    .kanban-col { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px; padding: 14px; min-height: 60px; }
    .kanban-col h4 { color: var(--text-white); font-size: 13px; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.5px; }
    .ticket { background: #0d1117; border: 1px solid var(--card-border); border-radius: 8px; padding: 10px; margin-bottom: 8px; font-size: 12.5px; }
    .ticket .ticket-title { color: var(--text-white); margin-bottom: 4px; }
    .ticket .ticket-meta { color: var(--text-muted); font-size: 11px; font-family: 'JetBrains Mono', monospace; }
    .modal { display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); overflow: auto; }
    .modal-content { background: var(--card-bg); margin: 5% auto; padding: 20px; border: 1px solid var(--card-border); border-radius: 12px; width: 80%; max-width: 900px; }
    .modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; border-bottom: 1px solid var(--card-border); padding-bottom: 10px; }
    .modal-close { color: var(--text-muted); font-size: 24px; font-weight: bold; cursor: pointer; }
    .file-tree { max-height: 250px; overflow-y: auto; background: #010409; border: 1px solid var(--card-border); border-radius: 8px; padding: 10px; font-family: 'JetBrains Mono', monospace; font-size: 12px; }
    .file-item { padding: 4px 8px; cursor: pointer; border-radius: 4px; color: var(--text-main); display: flex; justify-content: space-between; }
    .file-item:hover { background: #21262d; color: var(--accent); }
    .code-preview { background: #010409; border: 1px solid var(--card-border); border-radius: 8px; padding: 12px; font-family: 'JetBrains Mono', monospace; font-size: 12px; max-height: 400px; overflow: auto; white-space: pre-wrap; color: #f0f6fc; margin-top: 10px; }
  </style>
</head>
<body>
  <div class="header">
    <h1>🤖 KI-Softwareentwickler-Team</h1>
    <div id="teamMeta"><span class="badge" id="agentCountBadge">lade…</span></div>
  </div>

  <div class="prompt-box">
    <h3>⚡ Neue Projekt-Aufgabe an das KI-Team</h3>
    <textarea id="promptInput" placeholder="z. B. Entwickle ein FastAPI Backend mit Authentifizierung und PostgreSQL..."></textarea>
    <button id="startBtn" onclick="startTask()">Projekt-Entwicklung starten</button>
    <button id="cancelBtn" onclick="cancelTask()">⏹️ Lauf abbrechen</button>
    <span id="taskStatus" style="margin-left: 15px; font-size: 13px; color: var(--accent);"></span>
  </div>

  <div id="logPanel">
    <h3 style="color: var(--text-white); margin-bottom: 10px;">📡 Live-Fortschritt (SSE Streaming)</h3>
    <div id="logOutput"></div>
    <div id="resultOutput"></div>
  </div>

  <div class="prompt-box">
    <h3>📂 Workspace-Dateien & Diff-Inspektor</h3>
    <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 10px;">
      <select id="inspectProjectSelect" style="background: #0d1117; color: #f0f6fc; border: 1px solid var(--card-border); border-radius: 8px; padding: 8px;"><option>Lade Projekte…</option></select>
      <button onclick="inspectProjectFiles()" style="background: #238636;">Dateien durchsuchen</button>
      <button onclick="inspectProjectDiff()" style="background: #1f6feb;">Git-Diff anzeigen</button>
    </div>
    <div id="fileInspectorContainer" style="margin-top: 12px; display: none;">
      <div class="file-tree" id="fileTreeList"></div>
      <div class="code-preview" id="fileCodePreview" style="display: none;"></div>
    </div>
  </div>

  <div class="prompt-box">
    <h3>🚀 Deployment (lokal per Docker)</h3>
    <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 10px;">
      <select id="deployProjectSelect" style="background: #0d1117; color: #f0f6fc; border: 1px solid var(--card-border); border-radius: 8px; padding: 8px;"><option>Lade Projekte…</option></select>
      <button id="deployBtn" onclick="deployProject()">Deploy</button>
      <button id="deployStopBtn" onclick="stopDeployProject()" style="background: #da3633;">Stoppen</button>
    </div>
    <div id="deployStatus" style="margin-top: 10px; font-size: 13px; color: var(--text-muted); font-family: 'JetBrains Mono', monospace; white-space: pre-wrap;"></div>
  </div>

  <h2 style="color: var(--text-white); font-size: 18px; margin-bottom: 16px;">🎫 Backlog / Kanban-Board</h2>
  <p style="color: var(--text-muted); font-size: 12.5px; margin-bottom: 14px; margin-top: -12px;">Alle Tickets über CLI, Dashboard und autonome GitHub-Issue-Läufe hinweg (core/backlog_store.py) – persistent, überlebt einen Neustart.</p>
  <div class="kanban" id="kanbanBoard"><p style="color: var(--text-muted);">Lade Backlog…</p></div>

  <h2 style="color: var(--text-white); font-size: 18px; margin-bottom: 16px;">📈 Observability & Trends</h2>
  <p style="color: var(--text-muted); font-size: 12.5px; margin-bottom: 14px; margin-top: -12px;">Erfolgsquote je Agent und jüngste Läufe über ALLE Trigger-Quellen hinweg (memory/run_history.py) – persistent, überlebt einen Neustart.</p>
  <div class="grid" style="margin-bottom: 24px;">
    <div class="card">
      <h3>Erfolgsquote je Agent (letzte 50 Läufe)</h3>
      <div id="successRatesList"><p style="color: var(--text-muted);">Lade Trends…</p></div>
    </div>
    <div class="card">
      <h3>Jüngste Läufe</h3>
      <div id="recentRunsList"><p style="color: var(--text-muted);">Lade Läufe…</p></div>
    </div>
  </div>

  <h2 style="color: var(--text-white); font-size: 18px; margin-bottom: 16px;">🏢 Fachbereichs- & Teamleiter-Hierarchie</h2>
  <div class="grid" id="departmentGrid"><p style="color: var(--text-muted);">Lade Teamstruktur…</p></div>

  <script>
    let pollTimer = null;
    let currentJobId = null;
    window.eventSource = null;

    async function loadStatus() {
      const res = await fetch('/api/status');
      const data = await res.json();
      document.getElementById('agentCountBadge').innerText =
        `${data.agents_count} Spezialisten · ${data.departments_count} Fachbereiche`;
      const grid = document.getElementById('departmentGrid');
      grid.innerHTML = '';
      for (const dept of data.departments) {
        const card = document.createElement('div');
        card.className = 'card';
        card.innerHTML = `<h3>${dept.title}</h3><p><strong>Teamleiter:</strong> <code>${dept.lead_id}</code></p>
          <div>${dept.members.map(m => `<span class="member-tag">${m}</span>`).join('')}</div>`;
        grid.appendChild(card);
      }
    }

    async function startTask() {
      const val = document.getElementById('promptInput').value.trim();
      if (!val) { alert('Bitte gib eine Aufgabe ein.'); return; }
      document.getElementById('startBtn').disabled = true;
      document.getElementById('taskStatus').innerText = '⏳ Wird gestartet…';
      document.getElementById('logPanel').style.display = 'block';
      document.getElementById('logOutput').innerText = '';
      document.getElementById('resultOutput').innerText = '';

      const res = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: val }),
      });
      const data = await res.json();
      if (!res.ok) {
        document.getElementById('taskStatus').innerText = '❌ ' + (data.error || 'Fehler beim Start.');
        document.getElementById('startBtn').disabled = false;
        return;
      }
      currentJobId = data.job_id;
      document.getElementById('cancelBtn').style.display = 'inline-block';
      pollJob(data.job_id);
    }

    async function cancelTask() {
      if (!currentJobId) return;
      document.getElementById('cancelBtn').disabled = true;
      document.getElementById('taskStatus').innerText = '⏹️ Abbruch angefordert…';
      await fetch(`/api/cancel/${currentJobId}`, { method: 'POST' });
    }

    function startFallbackPolling(jobId, finish) {
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(async () => {
        const res = await fetch(`/api/status/${jobId}`);
        if (!res.ok) return;
        const data = await res.json();
        document.getElementById('logOutput').innerText = data.log.join('\\n');
        document.getElementById('logOutput').scrollTop = document.getElementById('logOutput').scrollHeight;
        if (data.status === 'queued') {
          document.getElementById('taskStatus').innerText = '⏳ In Warteschlange…';
        } else if (data.status === 'running') {
          document.getElementById('taskStatus').innerText = '🔄 Team arbeitet… (Polling)';
        } else if (['done', 'cancelled', 'error'].includes(data.status)) {
          finish(data.status, data.result, data.error);
        }
      }, 2000);
    }

    function pollJob(jobId) {
      if (pollTimer) clearInterval(pollTimer);
      if (window.eventSource) {
        window.eventSource.close();
        window.eventSource = null;
      }

      const finish = (status, result, error) => {
        document.getElementById('startBtn').disabled = false;
        document.getElementById('cancelBtn').style.display = 'none';
        document.getElementById('cancelBtn').disabled = false;
        if (status === 'done') {
          document.getElementById('taskStatus').innerText = '✅ Fertig!';
          document.getElementById('resultOutput').innerText = result || '';
        } else if (status === 'cancelled') {
          document.getElementById('taskStatus').innerText = '⏹️ Abgebrochen.';
          document.getElementById('resultOutput').innerText = result || '';
        } else if (status === 'error') {
          document.getElementById('taskStatus').innerText = '❌ Fehler: ' + (error || '');
        }
        currentJobId = null;
        if (window.eventSource) {
          window.eventSource.close();
          window.eventSource = null;
        }
        if (pollTimer) clearInterval(pollTimer);
        loadBacklog();
        loadObservability();
        loadProjects();
      };

      try {
        const es = new EventSource(`/api/stream/${jobId}`);
        window.eventSource = es;
        es.addEventListener('init', (e) => {
          const d = JSON.parse(e.data);
          if (d.log && d.log.length) {
            document.getElementById('logOutput').innerText = d.log.join('\\n');
            document.getElementById('logOutput').scrollTop = document.getElementById('logOutput').scrollHeight;
          }
          if (d.status === 'running') {
            document.getElementById('taskStatus').innerText = '🔄 Team arbeitet… (Live Stream)';
          } else if (['done', 'cancelled', 'error'].includes(d.status)) {
            finish(d.status, d.result, d.error);
          }
        });
        es.addEventListener('log', (e) => {
          const d = JSON.parse(e.data);
          const logEl = document.getElementById('logOutput');
          logEl.innerText += (logEl.innerText ? '\\n' : '') + d.line;
          logEl.scrollTop = logEl.scrollHeight;
          document.getElementById('taskStatus').innerText = '🔄 Team arbeitet… (Live Stream)';
        });
        es.addEventListener('status', (e) => {
          const d = JSON.parse(e.data);
          if (['done', 'cancelled', 'error'].includes(d.status)) {
            finish(d.status, d.result, d.error);
          }
        });
        es.onerror = () => {
          if (es.readyState === EventSource.CLOSED) {
            startFallbackPolling(jobId, finish);
          }
        };
      } catch (err) {
        startFallbackPolling(jobId, finish);
      }
    }

    async function inspectProjectFiles() {
      const proj = document.getElementById('inspectProjectSelect').value;
      if (!proj) return;
      const res = await fetch(`/api/project-files?project=${encodeURIComponent(proj)}`);
      const data = await res.json();
      const container = document.getElementById('fileInspectorContainer');
      const tree = document.getElementById('fileTreeList');
      const preview = document.getElementById('fileCodePreview');
      container.style.display = 'block';
      preview.style.display = 'none';
      if (!data.files || !data.files.length) {
        tree.innerHTML = '<p style="color: var(--text-muted);">Keine Dateien im Projekt gefunden.</p>';
        return;
      }
      tree.innerHTML = data.files.map(f => `
        <div class="file-item" onclick="loadContent('${escapeHtml(proj)}', '${escapeHtml(f.path)}')">
          <span>📄 ${escapeHtml(f.path)}</span>
          <span style="color: var(--text-muted);">${f.size} B</span>
        </div>`).join('');
    }

    async function loadContent(proj, path) {
      const res = await fetch(`/api/project-file-content?project=${encodeURIComponent(proj)}&path=${encodeURIComponent(path)}`);
      const data = await res.json();
      const preview = document.getElementById('fileCodePreview');
      preview.style.display = 'block';
      preview.innerText = `// ${path}\n\n` + (data.content || '(Leere Datei)');
    }

    async function inspectProjectDiff() {
      const proj = document.getElementById('inspectProjectSelect').value;
      if (!proj) return;
      const res = await fetch(`/api/project-diff?project=${encodeURIComponent(proj)}`);
      const data = await res.json();
      const container = document.getElementById('fileInspectorContainer');
      const tree = document.getElementById('fileTreeList');
      const preview = document.getElementById('fileCodePreview');
      container.style.display = 'block';
      tree.innerHTML = `<h4>Git Diff / Status (${escapeHtml(proj)})</h4>`;
      preview.style.display = 'block';
      preview.innerText = data.diff || 'Keine Änderungen.';
    }

    const KANBAN_COLUMNS = [
      ['todo', '📋 Todo'], ['in_progress', '🔄 In Bearbeitung'], ['review', '👀 Review'],
      ['blocked', '🚧 Blockiert'], ['cancelled', '⏹️ Abgebrochen'], ['done', '✅ Fertig'],
    ];

    function escapeHtml(s) {
      const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
      return (s || '').replace(/[&<>"']/g, c => map[c]);
    }

    async function loadBacklog() {
      const res = await fetch('/api/backlog');
      if (!res.ok) return;
      const data = await res.json();
      const board = document.getElementById('kanbanBoard');
      board.innerHTML = '';
      for (const [status, label] of KANBAN_COLUMNS) {
        const tickets = data.tickets.filter(t => t.status === status);
        const col = document.createElement('div');
        col.className = 'kanban-col';
        const cards = tickets.slice(0, 8).map(t => `
          <div class="ticket">
            <div class="ticket-title">${escapeHtml(t.title)}</div>
            <div class="ticket-meta">${escapeHtml(t.source)} · ${escapeHtml((t.detail || t.id).slice(0, 40))}</div>
          </div>`).join('');
        col.innerHTML = `<h4>${label} (${tickets.length})</h4>${cards}`;
        board.appendChild(col);
      }
    }

    async function loadObservability() {
      const res = await fetch('/api/observability');
      if (!res.ok) return;
      const data = await res.json();

      const ratesEl = document.getElementById('successRatesList');
      if (!data.agent_success_rates.length) {
        ratesEl.innerHTML = '<p style="color: var(--text-muted);">Noch keine Läufe aufgezeichnet.</p>';
      } else {
        ratesEl.innerHTML = data.agent_success_rates.map(r => {
          const color = r.success_rate >= 80 ? '#2ea043' : (r.success_rate >= 50 ? '#d29922' : '#da3633');
          return `
            <div style="margin-bottom: 10px;">
              <div style="display: flex; justify-content: space-between; font-size: 12.5px; color: var(--text-muted); margin-bottom: 3px;">
                <span><code>${escapeHtml(r.agent_id)}</code> (${r.calls} Aufruf${r.calls === 1 ? '' : 'e'})</span>
                <span>${r.success_rate}%</span>
              </div>
              <div style="background: #0d1117; border-radius: 4px; height: 8px; overflow: hidden;">
                <div style="width: ${r.success_rate}%; background: ${color}; height: 100%;"></div>
              </div>
            </div>`;
        }).join('');
      }

      const runsEl = document.getElementById('recentRunsList');
      if (!data.recent_runs.length) {
        runsEl.innerHTML = '<p style="color: var(--text-muted);">Noch keine Läufe aufgezeichnet.</p>';
      } else {
        runsEl.innerHTML = data.recent_runs.slice(0, 8).map(r => `
          <div class="ticket">
            <div class="ticket-title">${r.verification_ok ? '✅' : '⚠️'} ${escapeHtml(r.task_summary)}</div>
            <div class="ticket-meta">${escapeHtml(r.project_slug)} · ${r.total_tokens.toLocaleString()} Tokens · ${r.duration_seconds}s · ${escapeHtml(r.timestamp.slice(0, 16).replace('T', ' '))}</div>
          </div>`).join('');
      }
    }

    async function loadProjects() {
      const res = await fetch('/api/projects');
      const data = await res.json();
      const sel = document.getElementById('deployProjectSelect');
      const inspectSel = document.getElementById('inspectProjectSelect');
      const opts = data.projects.length
        ? data.projects.map(p => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`).join('')
        : '<option value="">Keine Projekte im Workspace</option>';
      if (sel) sel.innerHTML = opts;
      if (inspectSel) inspectSel.innerHTML = opts;
    }

    let deployPollTimer = null;

    async function deployProject() {
      const project = document.getElementById('deployProjectSelect').value;
      if (!project) return;
      document.getElementById('deployStatus').innerText = '🚀 Deploye… (kann mehrere Minuten dauern)';
      const res = await fetch('/api/deploy', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project }),
      });
      if (!res.ok) {
        const data = await res.json();
        document.getElementById('deployStatus').innerText = '❌ ' + (data.error || 'Fehler beim Start.');
        return;
      }
      pollDeployStatus(project);
    }

    async function stopDeployProject() {
      const project = document.getElementById('deployProjectSelect').value;
      if (!project) return;
      document.getElementById('deployStatus').innerText = '⏹️ Stoppe…';
      await fetch('/api/deploy-stop', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project }),
      });
      pollDeployStatus(project);
    }

    function pollDeployStatus(project) {
      if (deployPollTimer) clearInterval(deployPollTimer);
      deployPollTimer = setInterval(async () => {
        const res = await fetch(`/api/deploy-status/${encodeURIComponent(project)}`);
        const data = await res.json();
        if (data.status === 'done') {
          clearInterval(deployPollTimer);
          const urlsText = (data.urls && data.urls.length) ? data.urls.join(', ') : '(kein Port ermittelt)';
          document.getElementById('deployStatus').innerText = data.success
            ? `✅ Deployment erfolgreich (${data.method}): ${urlsText}`
            : `❌ Deployment fehlgeschlagen:\n${data.output || ''}`;
        } else if (data.status === 'stopped') {
          clearInterval(deployPollTimer);
          document.getElementById('deployStatus').innerText = '⏹️ Deployment gestoppt.';
        } else if (data.status === 'skipped') {
          clearInterval(deployPollTimer);
          document.getElementById('deployStatus').innerText = 'ℹ️ ' + (data.reason_skipped || 'Nicht möglich.');
        } else if (data.status === 'error') {
          clearInterval(deployPollTimer);
          document.getElementById('deployStatus').innerText = '❌ ' + (data.output || 'Fehler.');
        }
      }, 3000);
    }

    loadStatus();
    loadBacklog();
    loadProjects();
    loadObservability();
    setInterval(loadBacklog, 5000);
    setInterval(loadObservability, 15000);
  </script>
</body>
</html>
"""


def _build_status_payload(server: DashboardServer) -> dict:
    from agents.department_lead_agent import DEPARTMENT_DEFINITIONS

    departments = []
    for dept_id, info in DEPARTMENT_DEFINITIONS.items():
        departments.append({
            "lead_id": dept_id,
            "title": info["title"],
            "members": [m for m in info["members"] if m in server.orchestrator._agents],
        })
    return {
        "status": "online",
        "agents_count": len(server.orchestrator._agents),
        "departments_count": len(server.orchestrator._dept_leads),
        "departments": departments,
    }


def make_handler(server: DashboardServer):
    class DashboardHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def _send_json(self, payload: dict, status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _check_auth(self) -> bool:
            if not DASHBOARD_AUTH_TOKEN:
                return True

            provided = ""
            auth_header = self.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                provided = auth_header[len("Bearer "):]
            else:
                query = parse_qs(urlparse(self.path).query)
                provided = (query.get("token") or [""])[0]

            if provided and hmac.compare_digest(provided, DASHBOARD_AUTH_TOKEN):
                return True

            self._send_json({"error": "Unauthorized – gültiger Token via 'Authorization: Bearer <token>' oder '?token=' erforderlich."}, status=401)
            return False

        def do_GET(self):
            if not self._check_auth():
                return
            parsed_url = urlparse(self.path)
            path_only = parsed_url.path

            if path_only in ("/", "/index.html"):
                body = HTML_DASHBOARD.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path_only == "/api/status":
                self._send_json(_build_status_payload(server))
            elif path_only.startswith("/api/status/"):
                job_id = path_only.rsplit("/", 1)[-1]
                job = server.jobs.get(job_id)
                if not job:
                    self._send_json({"error": "Unbekannte job_id"}, status=404)
                    return
                self._send_json({
                    "job_id": job.job_id, "status": job.status,
                    "log": job.log, "result": job.result, "error": job.error,
                })
            elif path_only.startswith("/api/stream/"):
                job_id = path_only.rsplit("/", 1)[-1]
                job = server.jobs.get(job_id)
                if not job:
                    self._send_json({"error": "Unbekannte job_id"}, status=404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()

                q = queue.Queue()
                job.listeners.append(q)
                init_data = json.dumps({"status": job.status, "log": job.log, "result": job.result, "error": job.error}, ensure_ascii=False)
                self.wfile.write(f"event: init\ndata: {init_data}\n\n".encode())
                self.wfile.flush()

                try:
                    while True:
                        try:
                            msg = q.get(timeout=1.0)
                            evt_type = msg.get("type", "message")
                            data_str = json.dumps(msg, ensure_ascii=False)
                            self.wfile.write(f"event: {evt_type}\ndata: {data_str}\n\n".encode())
                            self.wfile.flush()
                            if msg.get("type") == "status" and msg.get("status") in ("done", "error", "cancelled"):
                                break
                        except queue.Empty:
                            if job.status in ("done", "error", "cancelled"):
                                break
                            self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                except (ConnectionResetError, BrokenPipeError, OSError):
                    pass
                finally:
                    if q in job.listeners:
                        job.listeners.remove(q)
            elif path_only == "/api/backlog":
                self._send_json({"tickets": [vars(t) for t in list_tickets()]})
            elif path_only == "/api/projects":
                self._send_json({"projects": server.orchestrator._workspace.list_projects()})
            elif path_only == "/api/project-files":
                query = parse_qs(parsed_url.query)
                project_name = (query.get("project") or [""])[0]
                if not project_name:
                    self._send_json({"error": "Kein Projekt angegeben"}, status=400)
                    return
                project_dir = server.orchestrator._workspace.get_project_dir(project_name)
                if not project_dir.exists():
                    self._send_json({"error": "Projektverzeichnis nicht gefunden"}, status=404)
                    return
                files_list = []
                ignored = {".git", ".venv", "venv", ".ai_team_venv", "__pycache__", "node_modules"}
                for root, dirs, files in os.walk(project_dir):
                    dirs[:] = [d for d in dirs if d not in ignored and not d.startswith(".")]
                    for f in files:
                        p = Path(root) / f
                        rel = str(p.relative_to(project_dir)).replace("\\", "/")
                        files_list.append({"path": rel, "size": p.stat().st_size})
                self._send_json({"project": project_name, "files": sorted(files_list, key=lambda x: x["path"])})
            elif path_only == "/api/project-file-content":
                query = parse_qs(parsed_url.query)
                project_name = (query.get("project") or [""])[0]
                rel_path = (query.get("path") or [""])[0]
                if not project_name or not rel_path:
                    self._send_json({"error": "Projekt oder Pfad fehlt"}, status=400)
                    return
                project_dir = server.orchestrator._workspace.get_project_dir(project_name)
                clean_rel = rel_path.replace("\\", "/").lstrip("/")
                target = (project_dir / clean_rel).resolve()
                if target != project_dir and project_dir not in target.parents:
                    self._send_json({"error": "Ungültiger Pfad"}, status=403)
                    return
                if not target.exists() or not target.is_file():
                    self._send_json({"error": "Datei nicht gefunden"}, status=404)
                    return
                try:
                    content = target.read_text(encoding="utf-8", errors="replace")
                    self._send_json({"project": project_name, "path": clean_rel, "content": content, "size": len(content)})
                except Exception as e:
                    self._send_json({"error": str(e)}, status=500)
            elif path_only == "/api/project-diff":
                query = parse_qs(parsed_url.query)
                project_name = (query.get("project") or [""])[0]
                if not project_name:
                    self._send_json({"error": "Kein Projekt angegeben"}, status=400)
                    return
                project_dir = server.orchestrator._workspace.get_project_dir(project_name)
                if not project_dir.exists():
                    self._send_json({"error": "Projekt nicht gefunden"}, status=404)
                    return
                diff_text = ""
                try:
                    res = subprocess.run(["git", "diff", "HEAD~1"], cwd=str(project_dir), capture_output=True, text=True, timeout=5)
                    diff_text = res.stdout or ""
                    if not diff_text:
                        res_stat = subprocess.run(["git", "status", "--short"], cwd=str(project_dir), capture_output=True, text=True, timeout=5)
                        diff_text = res_stat.stdout or "Keine uncommitted Diffs vorhanden."
                except Exception:
                    diff_text = "Git-Diff nicht verfügbar."
                self._send_json({"project": project_name, "diff": diff_text})
            elif path_only == "/api/observability":
                self._send_json({
                    "recent_runs": get_recent_runs(limit=20),
                    "agent_success_rates": get_agent_success_rates(limit_runs=50),
                })
            elif path_only.startswith("/api/deploy-status/"):
                project_name = unquote(path_only.rsplit("/", 1)[-1])
                self._send_json({"project": project_name, **server.deployments.get(project_name, {"status": "none"})})
            else:
                self._send_json({"error": "Not found"}, status=404)

        def do_POST(self):
            if not self._check_auth():
                return
            if urlparse(self.path).path == "/api/run":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(length) or b"{}")
                    prompt = (payload.get("prompt") or "").strip()
                except Exception:
                    self._send_json({"error": "Ungültiger Request-Body"}, status=400)
                    return
                if not prompt:
                    self._send_json({"error": "Kein 'prompt' angegeben."}, status=400)
                    return
                job_id = server.enqueue(prompt)
                self._send_json({"job_id": job_id, "status": "queued"}, status=202)
            elif urlparse(self.path).path.startswith("/api/cancel/"):
                job_id = urlparse(self.path).path.rsplit("/", 1)[-1]
                if server.cancel(job_id):
                    self._send_json({"job_id": job_id, "cancel_requested": True})
                else:
                    self._send_json({"error": "Unbekannte job_id oder Job bereits abgeschlossen."}, status=404)
            elif urlparse(self.path).path in ("/api/deploy", "/api/deploy-stop"):
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(length) or b"{}")
                    project_name = (payload.get("project") or "").strip()
                except Exception:
                    self._send_json({"error": "Ungültiger Request-Body"}, status=400)
                    return
                if not project_name or project_name not in server.orchestrator._workspace.list_projects():
                    self._send_json({"error": "Unbekanntes Projekt."}, status=404)
                    return
                if urlparse(self.path).path == "/api/deploy":
                    server.deploy(project_name)
                else:
                    server.stop_deploy(project_name)
                self._send_json({"project": project_name, "status": "running"}, status=202)
            else:
                self._send_json({"error": "Not found"}, status=404)

    return DashboardHandler


def run_dashboard(port: int = 8080, host: str | None = None) -> None:
    resolved_host = host or DASHBOARD_HOST

    if resolved_host not in LOOPBACK_HOSTS and not DASHBOARD_AUTH_TOKEN:
        raise SystemExit(
            f"🚫 Sicherheitssperre: Das Dashboard soll auf '{resolved_host}' laufen (nicht nur lokal "
            "erreichbar), aber DASHBOARD_AUTH_TOKEN ist nicht gesetzt. Ohne Token könnte jeder im "
            "Netzwerk über POST /api/run einen vollen Agentenlauf mit echtem Datei-/Kommandozugriff "
            "auslösen.\n   Setze DASHBOARD_AUTH_TOKEN in der .env-Datei, bevor du das Dashboard im "
            "Netzwerk erreichbar machst."
        )

    server = DashboardServer()
    handler_cls = make_handler(server)
    with ThreadingHTTPServer((resolved_host, port), handler_cls) as httpd:
        bind_note = "🔒 nur lokal erreichbar" if resolved_host in LOOPBACK_HOSTS else "🌐 im Netzwerk erreichbar (Token-Auth aktiv)"
        print(f"🚀 Web-Dashboard läuft unter: http://{resolved_host}:{port} ({len(server.orchestrator._agents)} Agenten geladen) [{bind_note}]")
        httpd.serve_forever()


if __name__ == "__main__":
    run_dashboard()
