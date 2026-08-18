# 🤖 KI-Softwareentwickler-Team

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Gemini](https://img.shields.io/badge/Google_Gemini-4285F4?style=for-the-badge&logo=google&logoColor=white)
![Claude](https://img.shields.io/badge/Anthropic_Claude-D4A017?style=for-the-badge&logoColor=white)
![asyncio](https://img.shields.io/badge/asyncio-Parallel-green?style=for-the-badge)
![License](https://img.shields.io/badge/Lizenz-MIT-blue?style=for-the-badge)

**Ein autonomes, multi-agenten KI-Team für Softwareentwicklung.**  
Du gibst dem Hauptagenten eine Aufgabe – dein Team aus 10 KI-Spezialisten erledigt sie parallel.

</div>

---

## 📖 Inhaltsverzeichnis

- [Überblick](#überblick)
- [Agentenstruktur](#agentenstruktur)
- [Projektstruktur](#projektstruktur)
- [Workflow](#workflow)
- [Installation](#installation)
- [Konfiguration](#konfiguration)
- [Verwendung](#verwendung)
- [CLI-Befehle](#cli-befehle)
- [Agenten im Detail](#agenten-im-detail)
- [Erweiterung](#erweiterung)
- [Technologie-Stack](#technologie-stack)

---

## 🌟 Überblick

Das **KI-Softwareentwickler-Team** ist ein Python-Framework, das ein vollständiges Softwareentwicklungsteam aus KI-Agenten simuliert. Der Nutzer kommuniziert ausschließlich mit dem **Hauptagenten (Orchestrator)**, der die Aufgabe analysiert, sie in Teilaufgaben zerlegt und diese **parallel** an spezialisierte Unteragenten verteilt.

### Kernfunktionen

| Funktion | Beschreibung |
|----------|-------------|
| 🧠 **Intelligente Task-Zerlegung** | Gemini analysiert die Aufgabe und wählt automatisch die richtigen Agenten |
| ⚡ **Parallele Ausführung** | Alle Agenten arbeiten gleichzeitig via `asyncio.gather()` |
| 🔄 **Automatischer Fallback** | Bei API-Überlastung: Retry + Wechsel zum Backup-Modell |
| 💬 **Gesprächsgedächtnis** | Session-übergreifende Konversationshistorie (JSON-Persistenz) |
| 📊 **Live-Status** | Echtzeit-Fortschrittsanzeige im CLI (Rich-Bibliothek) |
| 📖 **Auto-README** | Dedizierter Agent hält die Dokumentation aktuell |
| 🔀 **Git-Integration** | Dedizierter GitHub-Agent für Versionskontrolle |

---

## 🏗️ Agentenstruktur

```
Du (Nutzer)
    │
    ▼  Aufgabe / Feedback
┌───────────────────────────────────────────────────┐
│              🤖 HAUPTAGENT (Orchestrator)          │
│  ┌─────────────────────────────────────────────┐  │
│  │  1. Aufgabe empfangen                        │  │
│  │  2. Gemini: Aufgabe → JSON-Taskplan          │  │
│  │  3. Passende Agenten auswählen               │  │
│  │  4. Alle parallel starten (asyncio.gather)   │  │
│  │  5. Auf ALLE Ergebnisse warten               │  │
│  │  6. Ergebnisse zu Gesamtlösung zusammenfassen│  │
│  └─────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────┘
    │    │    │    │    │    │    │    │    │    │
    ▼    ▼    ▼    ▼    ▼    ▼    ▼    ▼    ▼    ▼
  🎨   💻   ⚙️   🗄️   🚀   🧪   📚   🔒   📝   🔀
UI/UX Front Back  DB  DevOps Test  Docs Sec  README GitHub
```

### Agenten-Übersicht

| ID | Name | Symbol | Spezialisierung |
|----|------|--------|----------------|
| `ui_ux` | UI/UX Designer | 🎨 | Wireframes, Design-Systeme, User Flows |
| `frontend` | Frontend-Entwickler | 💻 | HTML/CSS/JS, React, Vue.js |
| `backend` | Backend-Entwickler | ⚙️ | REST APIs, FastAPI, Python |
| `database` | Datenbank-Entwickler | 🗄️ | SQL/NoSQL, Schemas, Migrations |
| `devops` | DevOps-Ingenieur | 🚀 | Docker, CI/CD, GitHub Actions |
| `tester` | QA-Tester | 🧪 | pytest, Unit-Tests, Testpläne |
| `documentation` | Dokumentant | 📚 | README, API-Docs, Changelogs |
| `security` | Sicherheits-Analyst | 🔒 | OWASP, Code-Reviews, Sicherheit |
| `readme` | README-Agent | 📝 | Automatische Dokumentations-Updates |
| `github` | GitHub-Agent | 🔀 | Git-Operationen, Commit-Messages |

---

## 📁 Projektstruktur

```
AI-Softwareentwickler-Team/
│
├── 📄 main.py                        # Einstiegspunkt (python main.py)
├── 📄 config.py                      # Zentrale Konfiguration
├── 📄 requirements.txt               # Python-Abhängigkeiten
├── 📄 .env                           # API-Keys (nicht in Git!)
├── 📄 .gitignore
├── 📄 README.md                      # Diese Datei
│
├── 📂 agents/                        # Alle KI-Agenten
│   ├── orchestrator.py               # ⭐ Hauptagent (Herzstück)
│   ├── base_agent.py                 # Abstrakte Basisklasse
│   ├── ui_ux_agent.py                # 🎨 UI/UX Designer
│   ├── frontend_agent.py             # 💻 Frontend-Entwickler
│   ├── backend_agent.py              # ⚙️ Backend-Entwickler
│   ├── database_agent.py             # 🗄️ Datenbank-Entwickler
│   ├── devops_agent.py               # 🚀 DevOps-Ingenieur
│   ├── tester_agent.py               # 🧪 QA-Tester
│   ├── documentation_agent.py        # 📚 Dokumentant
│   ├── security_agent.py             # 🔒 Sicherheits-Analyst
│   ├── readme_agent.py               # 📝 README-Agent (neu)
│   └── github_agent.py               # 🔀 GitHub-Agent (neu)
│
├── 📂 core/                          # Kernsystem
│   ├── llm_factory.py                # Gemini/Claude Clients + Retry
│   ├── task_manager.py               # Aufgaben-Zerlegung (Gemini JSON)
│   ├── result_aggregator.py          # Ergebnis-Synthese
│   └── message_bus.py                # Datenklassen & Nachrichtentypen
│
├── 📂 memory/                        # Persistenz
│   └── conversation_history.py       # Gesprächsverlauf (RAM + JSON)
│
└── 📂 interface/                     # Benutzeroberflächen
    └── cli.py                        # Rich-basiertes CLI
```

---

## 🔄 Workflow

### 1. Aufgabe stellen
Du gibst dem Hauptagenten eine Aufgabe in natürlicher Sprache:
```
Du → "Erstelle eine Todo-App mit Benutzer-Authentifizierung und PostgreSQL"
```

### 2. Automatische Analyse (Gemini JSON-Modus)
Der Orchestrator analysiert die Aufgabe und erstellt einen Taskplan:
```json
{
  "task_summary": "Todo-App mit Auth und Datenbank",
  "required_agents": [
    { "agent_id": "ui_ux", "task": "Erstelle UI-Konzept mit Login-Flow..." },
    { "agent_id": "backend", "task": "Implementiere FastAPI mit JWT-Auth..." },
    { "agent_id": "database", "task": "Entwerfe PostgreSQL-Schema..." },
    { "agent_id": "tester", "task": "Schreibe pytest-Tests..." }
  ]
}
```

### 3. Parallele Ausführung
Alle Agenten arbeiten **gleichzeitig** (`asyncio.gather()`):
```
⏱ T=0s:  UI/UX, Backend, Datenbank, Tester starten alle gleichzeitig
⏱ T=25s: UI/UX fertig
⏱ T=30s: Datenbank fertig, Backend fertig
⏱ T=38s: Tester fertig → Alle fertig!
```

### 4. Synthese & Antwort
Der Orchestrator fasst alle Ergebnisse zu einer kohärenten Gesamtlösung zusammen.

### 5. Feedback-Schleife
Du gibst Feedback → Orchestrator verteilt Verbesserungen an betroffene Agenten.

---

## 🚀 Installation

### Voraussetzungen
- Python 3.11 oder höher
- Git
- Google AI Studio API-Key (Gemini)
- Optional: Anthropic API-Key (Claude)

### Schritt 1: Repository klonen
```bash
git clone https://github.com/Schengii/AI-Softwareentwickler-Team.git
cd AI-Softwareentwickler-Team
```

### Schritt 2: Abhängigkeiten installieren
```bash
pip install -r requirements.txt
```

### Schritt 3: API-Keys konfigurieren
```bash
# .env Datei bearbeiten
GEMINI_API_KEY=dein-gemini-api-key-hier
ANTHROPIC_API_KEY=dein-claude-key-hier  # optional
```

### Schritt 4: Starten
```bash
python main.py
```

---

## ⚙️ Konfiguration

Alle Einstellungen werden in der `.env` Datei vorgenommen:

```env
# ── API Keys ──────────────────────────────────────
GEMINI_API_KEY=AQ.xxx...              # Pflicht
ANTHROPIC_API_KEY=sk-ant-...          # Optional (für Claude)

# ── Modelle ───────────────────────────────────────
ORCHESTRATOR_MODEL=gemini-3.6-flash   # Hauptagent
DEFAULT_AGENT_MODEL=gemini-3.6-flash  # Standard für Unteragenten

# ── Verhalten ─────────────────────────────────────
AGENT_LANGUAGE=de                     # de = Deutsch, en = Englisch
MAX_OUTPUT_TOKENS=8192                # Maximale Antwortlänge
TEMPERATURE=0.7                       # Kreativität (0.0–1.0)
```

### API-Keys besorgen

| Dienst | URL | Kostenlos? |
|--------|-----|-----------|
| Google Gemini | https://aistudio.google.com | ✅ Ja (mit Limits) |
| Anthropic Claude | https://console.anthropic.com | ❌ Bezahlt |

---

## 💻 Verwendung

### System starten
```powershell
# Windows PowerShell
cd "c:\Pfad\zu\AI-Softwareentwickler-Team"
python main.py
```

### Beispiel-Aufgaben

```
# Einfache REST API
Erstelle eine Hello-World REST API mit FastAPI und Python

# Komplette Web-App
Baue eine Todo-App mit React Frontend, FastAPI Backend und PostgreSQL

# Code-Review
Überprüfe diesen Python-Code auf Sicherheitslücken: [code einfügen]

# Dokumentation
Erstelle eine vollständige API-Dokumentation für mein FastAPI-Projekt

# Testing
Schreibe umfangreiche pytest-Tests für meine UserAuthentication Klasse

# DevOps
Erstelle ein Docker-Setup mit docker-compose für meine Flask-App
```

---

## 🖥️ CLI-Befehle

| Befehl | Beschreibung |
|--------|-------------|
| `/team` | Zeigt alle verfügbaren Agenten mit Beschreibungen |
| `/verlauf` | Zeigt den bisherigen Gesprächsverlauf |
| `/neu` | Startet eine neue Konversation (löscht Verlauf) |
| `/hilfe` | Zeigt alle Befehle |
| `/beenden` | Beendet das Programm |

---

## 🤖 Agenten im Detail

### 🎨 UI/UX Designer (`ui_ux`)
- Wireframe-Beschreibungen mit konkreten Spezifikationen
- Farbschemata (HEX/HSL), Typografie, Abstände
- User Flows und Interaktionsdesign
- Barrierefreiheit (WCAG-Standards)
- Design-System-Empfehlungen

### 💻 Frontend-Entwickler (`frontend`)
- HTML5, CSS3, JavaScript (ES2023+), TypeScript
- React.js (Hooks, Context), Vue.js 3, Next.js
- Responsive Design, Mobile-First
- Performance-Optimierung
- Testing mit Jest / Vitest

### ⚙️ Backend-Entwickler (`backend`)
- FastAPI, Django, Flask (Python bevorzugt)
- REST API Design mit OpenAPI/Swagger
- JWT, OAuth2, Authentifizierung
- Microservices, Event-Driven Design
- Clean Architecture, SOLID-Prinzipien

### 🗄️ Datenbank-Entwickler (`database`)
- PostgreSQL, MySQL, SQLite (SQL)
- MongoDB, Redis (NoSQL)
- ER-Diagramme und Schema-Design
- Migrations (Alembic, Flyway)
- Query-Optimierung und Indexierung

### 🚀 DevOps-Ingenieur (`devops`)
- Docker & Docker Compose
- GitHub Actions CI/CD-Pipelines
- Nginx, Traefik (Reverse Proxy)
- Cloud-Deployment (AWS, GCP, Azure)
- Monitoring mit Prometheus/Grafana

### 🧪 QA-Tester (`tester`)
- pytest (Python), Jest (JavaScript)
- Unit-Tests, Integrationstests, E2E-Tests
- Test-Driven Development (TDD)
- Coverage-Analyse
- Testpläne und Fehlerberichte

### 📚 Dokumentant (`documentation`)
- README-Dateien (GitHub-Standard)
- API-Dokumentation (OpenAPI, Docstrings)
- Technische Tutorials
- Changelog-Erstellung
- Architektur-Diagramme (Mermaid)

### 🔒 Sicherheits-Analyst (`security`)
- OWASP Top 10 Analyse
- SQL/NoSQL-Injection Prävention
- Authentifizierungs-Best-Practices
- Dependency-Scanning
- Security-Reports mit Schweregrad-Bewertung

### 📝 README-Agent (`readme`)
- Automatische README-Aktualisierung
- Erkennt neue Agenten, Funktionen, Strukturänderungen
- Hält Dokumentation konsistent mit dem Code

### 🔀 GitHub-Agent (`github`)
- Generiert aussagekräftige Commit-Messages
- Erstellt Branch-Strategien
- Pull-Request-Beschreibungen
- Git-Workflow-Empfehlungen

---

## 🔧 Erweiterung

### Neuen Agenten hinzufügen

1. **Neue Agenten-Datei erstellen** (`agents/mein_agent.py`):
```python
from agents.base_agent import BaseAgent

class MeinAgent(BaseAgent):
    def __init__(self):
        super().__init__(agent_id="mein_agent", name="Mein Spezialist")

    @property
    def system_prompt(self) -> str:
        return """Du bist Experte für...
        Deine Kernkompetenzen: ...
        Wie du arbeitest: ..."""
```

2. **Im Orchestrator registrieren** (`agents/orchestrator.py`):
```python
from agents.mein_agent import MeinAgent

self._agents["mein_agent"] = MeinAgent()
```

3. **Im TaskManager beschreiben** (`core/task_manager.py`):
```python
AVAILABLE_AGENTS["mein_agent"] = {
    "name": "Mein Spezialist",
    "description": "Zuständig für..."
}
```

### Anderes Modell für einen Agenten verwenden

In `.env`:
```env
BACKEND_MODEL=gemini-2.5-pro
TESTER_MODEL=claude-sonnet-4-5
```

---

## 🛠️ Technologie-Stack

| Komponente | Technologie | Version |
|------------|-------------|---------|
| **Sprache** | Python | 3.11+ |
| **KI (primär)** | Google Gemini | gemini-3.6-flash |
| **KI (optional)** | Anthropic Claude | claude-sonnet-4-5 |
| **Gemini SDK** | google-genai | 2.7.0+ |
| **Claude SDK** | anthropic | 0.40.0+ |
| **Parallelität** | asyncio | Built-in |
| **CLI** | Rich | 13.7.0+ |
| **Konfiguration** | python-dotenv | 1.0.0+ |

---

## 📋 Voraussetzungen

```
Python >= 3.11
google-genai >= 2.0.0
anthropic >= 0.40.0      # Optional
python-dotenv >= 1.0.0
rich >= 13.7.0
aiofiles >= 23.2.0
```

---

## 📝 Changelog

### v1.1.0 (2026-08-18)
- ➕ README-Agent (`readme_agent.py`) hinzugefügt
- ➕ GitHub-Agent (`github_agent.py`) hinzugefügt
- 📖 Umfassende README.md erstellt
- 🔄 Orchestrator um neue Agenten erweitert

### v1.0.0 (2026-08-18)
- 🎉 Erstes Release
- ✅ 8 spezialisierte Unteragenten implementiert
- ✅ Parallele Ausführung mit asyncio
- ✅ Gemini JSON-Modus für Task-Zerlegung
- ✅ Automatischer Retry + Modell-Fallback
- ✅ Rich CLI mit Live-Status
- ✅ Gesprächsverlauf-Persistenz
- ✅ Windows UTF-8 Fix

---

## 🤝 Mitwirken

Contributions sind willkommen! Bitte:
1. Fork des Repositories erstellen
2. Feature-Branch erstellen (`git checkout -b feature/NeuerAgent`)
3. Änderungen committen (`git commit -m 'feat: NeuerAgent hinzugefügt'`)
4. Branch pushen (`git push origin feature/NeuerAgent`)
5. Pull Request erstellen

---

## 📄 Lizenz

MIT License – siehe [LICENSE](LICENSE) Datei.

---

<div align="center">

**Gebaut mit ❤️ und 🤖 | Powered by Google Gemini & Anthropic Claude**

[⭐ Star auf GitHub](https://github.com/Schengii/AI-Softwareentwickler-Team) | [🐛 Bug melden](https://github.com/Schengii/AI-Softwareentwickler-Team/issues)

</div>
