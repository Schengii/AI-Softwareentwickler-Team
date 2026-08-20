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

Bewusste Design-Entscheidung: Jobs laufen SERIELL in einem einzigen Worker-Thread (nicht
mehrere gleichzeitig), weil Orchestrator._history (ConversationHistory) sonst bei parallelen
Anfragen aus verschiedenen Threads inkonsistent würde. Für eine lokale Einzelnutzer-Anwendung
ist das die richtige, einfache und sichere Grundannahme – wie ein CLI-Terminal kann jeweils
ein Auftrag aktiv sein, weitere werden eingereiht.

Sicherheit (siehe config.DASHBOARD_HOST/DASHBOARD_AUTH_TOKEN): Vorher band der Server per
`ThreadingHTTPServer(("", port), ...)` auf ALLE Netzwerk-Interfaces, ohne jede Authentifizierung
– jeder im selben Netzwerk konnte über POST /api/run einen vollen Agentenlauf mit echtem
Datei-/Kommandozugriff (run_command/pip/npm) auslösen. Jetzt: Standard-Bind ist 127.0.0.1
(nur lokal erreichbar), und run_dashboard() verweigert den Start auf einer nicht-lokalen
Adresse, solange kein DASHBOARD_AUTH_TOKEN gesetzt ist. Ist ein Token gesetzt, verlangt
JEDER Request einen gültigen "Authorization: Bearer <token>"-Header (oder "?token=").
"""

import asyncio
import hmac
import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from agents.orchestrator import Orchestrator
from config import DASHBOARD_AUTH_TOKEN, DASHBOARD_HOST

MAX_LOG_LINES_KEPT = 500
# Adressen, die als "nur von diesem Rechner erreichbar" gelten – hier darf das Dashboard
# auch ohne Token starten, weil ein entfernter Angreifer den Server so nicht erreichen kann.
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
    # Von POST /api/cancel/<job_id> gesetzt - der Worker fragt das an DENSELBEN Prüfpunkten
    # ab wie das bestehende MAX_RUN_TOKENS-Budget (siehe Orchestrator.process(
    # cancel_requested=...)), kein hartes Kill mitten in einer laufenden Datei-/Subprozess-
    # Operation.
    cancel_requested: bool = False


class DashboardServer:
    """Hält die geteilte Orchestrator-Instanz, die Job-Queue und den seriellen Worker."""

    def __init__(self):
        self.orchestrator = Orchestrator()
        self.jobs: dict[str, Job] = {}
        self._queue: queue.Queue[str] = queue.Queue()
        self._worker = threading.Thread(target=self._run_worker, daemon=True)
        self._worker.start()

    def enqueue(self, prompt: str) -> str:
        job_id = uuid.uuid4().hex[:12]
        self.jobs[job_id] = Job(job_id=job_id, prompt=prompt)
        self._queue.put(job_id)
        return job_id

    def cancel(self, job_id: str) -> bool:
        """Markiert einen Job zum Abbruch - der Worker (falls dieser Job gerade läuft) sieht
        das beim nächsten Prüfpunkt (vor jeder Fachbereichs-Phase/jedem Fixversuch). Ein noch
        in der Warteschlange stehender Job wird direkt als abgebrochen markiert, ohne je zu
        starten. Gibt False zurück, wenn die job_id unbekannt oder der Job bereits fertig ist."""
        job = self.jobs.get(job_id)
        if not job or job.status in ("done", "error", "cancelled"):
            return False
        job.cancel_requested = True
        if job.status == "queued":
            job.status = "cancelled"
        return True

    def _run_worker(self) -> None:
        while True:
            job_id = self._queue.get()
            job = self.jobs.get(job_id)
            if not job or job.status == "cancelled":
                continue  # bereits vor dem Start abgebrochen (siehe cancel())
            job.status = "running"

            def on_status(msg: str, _job=job):
                import re
                clean = re.sub(r"\[/?[a-zA-Z0-9 _]+\]", "", msg)  # rich-Markup entfernen
                _job.log.append(clean)
                if len(_job.log) > MAX_LOG_LINES_KEPT:
                    del _job.log[: len(_job.log) - MAX_LOG_LINES_KEPT]

            try:
                result = asyncio.run(self.orchestrator.process(
                    job.prompt, status_callback=on_status,
                    cancel_requested=lambda _job=job: _job.cancel_requested,
                ))
                job.result = result
                # cancel_requested war gesetzt UND der Lauf hat sich tatsächlich vorzeitig
                # beendet (statt zufällig kurz danach ganz normal fertig zu werden) - der
                # Orchestrator-Status im Ergebnistext selbst ist die verlässliche Quelle.
                job.status = "cancelled" if job.cancel_requested and "Manuell abgebrochen" in result else "done"
            except Exception as e:
                job.error = str(e)
                job.status = "error"


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
    <h3 style="color: var(--text-white); margin-bottom: 10px;">📡 Live-Fortschritt</h3>
    <div id="logOutput"></div>
    <div id="resultOutput"></div>
  </div>

  <h2 style="color: var(--text-white); font-size: 18px; margin-bottom: 16px;">🏢 Fachbereichs- & Teamleiter-Hierarchie</h2>
  <div class="grid" id="departmentGrid"><p style="color: var(--text-muted);">Lade Teamstruktur…</p></div>

  <script>
    let pollTimer = null;
    let currentJobId = null;

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

    function pollJob(jobId) {
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(async () => {
        const res = await fetch(`/api/status/${jobId}`);
        const data = await res.json();
        document.getElementById('logOutput').innerText = data.log.join('\\n');
        document.getElementById('logOutput').scrollTop = document.getElementById('logOutput').scrollHeight;

        const finish = () => {
          document.getElementById('startBtn').disabled = false;
          document.getElementById('cancelBtn').style.display = 'none';
          document.getElementById('cancelBtn').disabled = false;
          currentJobId = null;
          clearInterval(pollTimer);
        };

        if (data.status === 'queued') {
          document.getElementById('taskStatus').innerText = '⏳ In Warteschlange…';
        } else if (data.status === 'running') {
          document.getElementById('taskStatus').innerText = '🔄 Team arbeitet…';
        } else if (data.status === 'done') {
          document.getElementById('taskStatus').innerText = '✅ Fertig!';
          document.getElementById('resultOutput').innerText = data.result;
          finish();
        } else if (data.status === 'cancelled') {
          document.getElementById('taskStatus').innerText = '⏹️ Abgebrochen.';
          document.getElementById('resultOutput').innerText = data.result;
          finish();
        } else if (data.status === 'error') {
          document.getElementById('taskStatus').innerText = '❌ Fehler: ' + data.error;
          finish();
        }
      }, 2000);
    }

    loadStatus();
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
        def log_message(self, format, *args):  # weniger Konsolen-Rauschen
            pass

        def _send_json(self, payload: dict, status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _check_auth(self) -> bool:
            """
            Ohne konfiguriertes DASHBOARD_AUTH_TOKEN bleibt das Verhalten unverändert (kein
            Auth-Zwang – sicher, solange der Server wie standardmäßig nur auf 127.0.0.1 bindet).
            Ist ein Token gesetzt, muss JEDER Request (auch GET /) ihn per Header oder
            Query-Parameter mitliefern, sonst 401 – konstant in der Vergleichszeit
            (hmac.compare_digest), um Timing-Angriffe auf den Token-Vergleich zu vermeiden.
            """
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
            # Routing bewusst ohne Query-String: seit _check_auth() auch "?token=<token>" als
            # Auth-Weg akzeptiert, würde ein exakter Vergleich von self.path (inkl. Query) hier
            # sonst z.B. "/api/status?token=..." nicht mehr auf "/api/status" matchen.
            path_only = urlparse(self.path).path
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
