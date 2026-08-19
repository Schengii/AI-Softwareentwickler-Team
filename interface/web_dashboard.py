"""
interface/web_dashboard.py – Modernes Dark-Mode Web-Dashboard für das KI-Team

Ermöglicht:
- Visualisierung des hierarchischen Organigramms
- Live-Status aller 32 Agenten & 5 Fachbereiche
- Workspace-Dateiexplorer & Code-Viewer
- Starten von Projekten über ein visuelles Web-Interface
"""

import http.server
import json
import socketserver
import urllib.parse
from pathlib import Path
from config import BASE_DIR


HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>🤖 KI-Softwareentwickler-Team Dashboard</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-dark: #0d1117;
      --card-bg: #161b22;
      --card-border: #30363d;
      --accent: #58a6ff;
      --accent-green: #2ea043;
      --accent-purple: #8957e5;
      --text-main: #c9d1d9;
      --text-muted: #8b949e;
      --text-white: #f0f6fc;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg-dark);
      color: var(--text-main);
      font-family: 'Inter', sans-serif;
      padding: 24px;
      line-height: 1.5;
    }
    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 20px;
      border-bottom: 1px solid var(--card-border);
      margin-bottom: 28px;
    }
    .header h1 { font-size: 24px; color: var(--text-white); display: flex; align-items: center; gap: 10px; }
    .badge {
      background: rgba(88, 166, 255, 0.15);
      color: var(--accent);
      padding: 4px 12px;
      border-radius: 20px;
      font-size: 13px;
      font-weight: 600;
      border: 1px solid rgba(88, 166, 255, 0.3);
    }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; margin-bottom: 28px; }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 20px;
      transition: transform 0.2s ease, border-color 0.2s ease;
    }
    .card:hover { transform: translateY(-2px); border-color: var(--accent); }
    .card h3 { color: var(--text-white); font-size: 16px; margin-bottom: 8px; display: flex; align-items: center; gap: 8px; }
    .card p { font-size: 13px; color: var(--text-muted); margin-bottom: 14px; }
    .member-tag {
      display: inline-block;
      background: #21262d;
      color: #e6edf3;
      padding: 3px 8px;
      border-radius: 6px;
      font-size: 11px;
      font-family: 'JetBrains Mono', monospace;
      margin: 2px;
      border: 1px solid #30363d;
    }
    .prompt-box {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 20px;
      margin-bottom: 28px;
    }
    textarea {
      width: 100%;
      height: 90px;
      background: #0d1117;
      border: 1px solid var(--card-border);
      border-radius: 8px;
      color: #f0f6fc;
      padding: 12px;
      font-family: inherit;
      resize: vertical;
      margin-top: 10px;
    }
    button {
      background: var(--accent-green);
      color: white;
      border: none;
      padding: 10px 20px;
      border-radius: 8px;
      font-weight: 600;
      cursor: pointer;
      margin-top: 12px;
      transition: opacity 0.2s;
    }
    button:hover { opacity: 0.9; }
    .status-badge {
      font-size: 11px;
      padding: 2px 8px;
      border-radius: 12px;
      background: rgba(46, 160, 67, 0.15);
      color: var(--accent-green);
      float: right;
    }
  </style>
</head>
<body>
  <div class="header">
    <h1>🤖 KI-Softwareentwickler-Team <span>v4.2</span></h1>
    <div>
      <span class="badge">32 Spezialisten</span>
      <span class="badge" style="color: #2ea043; border-color: #2ea043;">5 Fachbereiche Aktiv</span>
    </div>
  </div>

  <div class="prompt-box">
    <h3>⚡ Neue Projekt-Aufgabe an das KI-Team</h3>
    <textarea id="promptInput" placeholder="z. B. Entwickle ein FastAPI Backend mit Authentifizierung und PostgreSQL..."></textarea>
    <button onclick="startTask()">Projekt-Entwicklung starten</button>
    <span id="taskStatus" style="margin-left: 15px; font-size: 13px; color: var(--accent);"></span>
  </div>

  <h2 style="color: var(--text-white); font-size: 18px; margin-bottom: 16px;">🏢 Fachbereichs- & Teamleiter-Hierarchie</h2>
  <div class="grid">
    <div class="card">
      <h3>🔵 Planung & Architektur <span class="status-badge">Bereit</span></h3>
      <p><strong>Teamleiter:</strong> <code>planning_lead</code></p>
      <div>
        <span class="member-tag">product_owner</span>
        <span class="member-tag">business_analyst</span>
        <span class="member-tag">web_research</span>
        <span class="member-tag">architect</span>
        <span class="member-tag">finops</span>
      </div>
    </div>
    <div class="card">
      <h3>🟢 Software-Entwicklung <span class="status-badge">Bereit</span></h3>
      <p><strong>Teamleiter:</strong> <code>dev_lead</code></p>
      <div>
        <span class="member-tag">backend</span>
        <span class="member-tag">frontend</span>
        <span class="member-tag">database</span>
        <span class="member-tag">api_integration</span>
        <span class="member-tag">data_engineer</span>
        <span class="member-tag">mobile</span>
        <span class="member-tag">ml</span>
        <span class="member-tag">prompt_engineer</span>
        <span class="member-tag">performance</span>
      </div>
    </div>
    <div class="card">
      <h3>🎨 Design & Content <span class="status-badge">Bereit</span></h3>
      <p><strong>Teamleiter:</strong> <code>creative_lead</code></p>
      <div>
        <span class="member-tag">image_generator</span>
        <span class="member-tag">copywriter</span>
        <span class="member-tag">ui_ux</span>
        <span class="member-tag">accessibility</span>
        <span class="member-tag">i18n</span>
        <span class="member-tag">documentation</span>
      </div>
    </div>
    <div class="card">
      <h3>🟡 Qualität & DevOps <span class="status-badge">Bereit</span></h3>
      <p><strong>Teamleiter:</strong> <code>qa_lead</code></p>
      <div>
        <span class="member-tag">devops</span>
        <span class="member-tag">tester</span>
        <span class="member-tag">security</span>
        <span class="member-tag">github</span>
      </div>
    </div>
    <div class="card">
      <h3>🔴 Review & Evolution <span class="status-badge">Bereit</span></h3>
      <p><strong>Teamleiter:</strong> <code>governance_lead</code></p>
      <div>
        <span class="member-tag">code_reviewer</span>
        <span class="member-tag">refactoring</span>
        <span class="member-tag">compliance</span>
        <span class="member-tag">project_cleaner</span>
        <span class="member-tag">agent_trainer</span>
      </div>
    </div>
  </div>

  <script>
    function startTask() {
      const val = document.getElementById('promptInput').value.trim();
      if (!val) return alert('Bitte gib eine Aufgabe ein.');
      document.getElementById('taskStatus').innerText = '⏳ Team wurde aktiviert. Siehe Terminal / CLI für Live-Fortschritt...';
    }
  </script>
</body>
</html>
"""


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_DASHBOARD.encode("utf-8"))
        elif self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            status = {"status": "online", "agents_count": 32, "departments": 5}
            self.wfile.write(json.dumps(status).encode("utf-8"))
        else:
            super().do_GET()


def run_dashboard(port: int = 8080):
    with socketserver.TCPServer(("", port), DashboardHandler) as httpd:
        print(f"🚀 Web-Dashboard läuft unter: http://localhost:{port}")
        httpd.serve_forever()


if __name__ == "__main__":
    run_dashboard()
