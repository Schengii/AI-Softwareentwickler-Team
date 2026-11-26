# 🤖 KI-Softwareentwickler-Team

[![CI](https://github.com/Schengii/AI-Softwareentwickler-Team/actions/workflows/ci.yml/badge.svg)](https://github.com/Schengii/AI-Softwareentwickler-Team/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)

Ein autonomes Multi-Agent-System, das aus einer Feature-Beschreibung ein geplantes, programmiertes und getestetes Projekt macht. Das Ergebnis wird durch echte Testläufe verifiziert (pytest/npm), nicht nur behauptet.

## Was es kann

- **33 Spezialisten in 6 Fachbereichen**, je Bereich ein Teamleiter (Planung, Design, Entwicklung u. a.)
- **Echte Verifikation:** Sandbox-Ausführung in isolierter venv, Tests, ruff, pip-audit
- **Resilience-Guard:** Circuit Breaker, Backoff, Graceful Degradation
- **Hartes Token-Budget** pro Lauf (`MAX_RUN_TOKENS`)
- **Web-Dashboard**, **MCP-Server** (Cursor, Windsurf), **lokales Codebase-RAG**
- **PR-Workflow** und reproduzierbare Benchmark-Suite (`--eval`)

## Schnellstart

```bash
pip install -r requirements.txt
playwright install chromium      # einmalig, für den echten Browser-Check
cp .env.example .env             # API-Keys eintragen
python main.py                   # interaktive CLI: App beschreiben, Team arbeitet
python main.py --dashboard       # Web-Dashboard auf http://localhost:8080
```

Das Ergebnis landet in `workspace/<projekt>/`, ein fertiges Beispiel ist [`workspace/fastapi-task-mgmt`](workspace/fastapi-task-mgmt).
`workspace/` ist bewusst versioniert: Es dient der CI und dem Scheduler als Prüfkorpus (echte `npm test`-/Audit-Läufe über alle generierten Projekte).

## Dokumentation

Alle Funktionen, Workflows und CLI-Befehle: [docs/FEATURES.md](docs/FEATURES.md) · Architektur: [ARCHITECTURE.md](ARCHITECTURE.md) · Historie: [CHANGELOG.md](CHANGELOG.md)

## Tests & Lint

```bash
pytest
ruff check .
```

## Lizenz

MIT, siehe [LICENSE](LICENSE).
