# 🤖 KI-Softwareentwickler-Team

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Gemini](https://img.shields.io/badge/Google_Gemini-4285F4?style=for-the-badge&logo=google&logoColor=white)
![Claude](https://img.shields.io/badge/Anthropic_Claude-D4A017?style=for-the-badge&logoColor=white)
![Agents](https://img.shields.io/badge/Agenten-17-success?style=for-the-badge)
![asyncio](https://img.shields.io/badge/asyncio-Parallel-green?style=for-the-badge)
![License](https://img.shields.io/badge/Lizenz-MIT-blue?style=for-the-badge)

**Ein autonomes, multi-agenten KI-Team für vollständige Softwareentwicklung.**  
17 spezialisierte KI-Experten – koordiniert, phasenbasiert, vollständig professionell.

</div>

---

## 📖 Inhaltsverzeichnis

- [Überblick](#überblick)
- [Agentenstruktur (17 Spezialisten)](#agentenstruktur)
- [4-Phasen-Workflow](#4-phasen-workflow)
- [Projektstruktur](#projektstruktur)
- [Installation](#installation)
- [Konfiguration](#konfiguration)
- [Verwendung](#verwendung)
- [CLI-Befehle](#cli-befehle)
- [Agenten im Detail](#agenten-im-detail)
- [Erweiterung](#erweiterung)
- [Technologie-Stack](#technologie-stack)
- [Changelog](#changelog)

---

## 🌟 Überblick

Das **KI-Softwareentwickler-Team** ist ein Python-Framework, das ein vollständiges, professionelles Softwareentwicklungsteam aus 17 KI-Agenten simuliert. Der Nutzer kommuniziert ausschließlich mit dem **Hauptagenten (Orchestrator)**, der die Aufgabe analysiert, phasenbasiert an spezialisierte Teams verteilt und vollständige Lösungen liefert.

### Kernfunktionen

| Funktion | Beschreibung |
|----------|-------------|
| 🏛️ **4-Phasen-Workflow** | BA → Architekt → Parallele Agenten → Code-Reviewer |
| 🧠 **Intelligente Task-Zerlegung** | Gemini analysiert und wählt automatisch die richtigen Agenten |
| ⚡ **Parallele Ausführung** | Implementierungs-Agenten arbeiten gleichzeitig via `asyncio.gather()` |
| 🔄 **Automatischer Fallback** | Bei API-Überlastung: Retry + Wechsel zum Backup-Modell |
| 💬 **Gesprächsgedächtnis** | Session-übergreifende Konversationshistorie (JSON-Persistenz) |
| 📊 **Live-Status** | Echtzeit-Fortschrittsanzeige im CLI (Rich-Bibliothek) |
| 🔀 **Kontext-Weitergabe** | Architektur-Blueprint fließt automatisch an alle Implementierer |

---

## 🏗️ Agentenstruktur

### Vollständige Team-Übersicht (17 Spezialisten)

```
Du (Nutzer)
    │  Aufgabe / Feedback
    ▼
┌─────────────────────────────────────────────────────────────┐
│                🤖 HAUPTAGENT (Orchestrator)                  │
│   Analysiert → Plant → Koordiniert → Synthetisiert          │
└─────────────────────────────────────────────────────────────┘
         │
         │  4-Phasen-Ausführung
         │
    ┌────▼────┐
    │ Phase 1 │  📋 Business Analyst
    └────┬────┘  (klärt Anforderungen, User Stories, Scope)
         │ Anforderungs-Dokument
    ┌────▼────┐
    │ Phase 2 │  🏛️ Software-Architekt
    └────┬────┘  (System-Blueprint, API-Contracts, Tech-Entscheidungen)
         │ Architektur-Blueprint (an alle Phase-3-Agenten)
    ┌────▼─────────────────────────────────────────────────────────┐
    │ Phase 3 │  ALLE PARALLEL                                      │
    │         │  🎨 UI/UX  💻 Frontend  ⚙️ Backend  🗄️ Datenbank   │
    │         │  📱 Mobile  🤖 KI/ML  ⚡ Perf.  🌍 i18n            │
    │         │  🚀 DevOps  🧪 Tester  📚 Docs  🔒 Security        │
    └────┬─────────────────────────────────────────────────────────┘
         │ Alle Code-Ergebnisse
    ┌────▼────┐
    │ Phase 4 │  🔍 Code-Reviewer
    └────┬────┘  (prüft Qualität, Konsistenz, Best Practices)
         │ Finales Review
    ┌────▼────┐
    │ Synthese│  Orchestrator fasst alles zusammen
    └─────────┘
         │
         ▼
   Vollständige Lösung
```

### Agenten-Tabelle

| Phase | ID | Name | Symbol | Spezialisierung |
|-------|-----|------|--------|----------------|
| **1** | `business_analyst` | Business Analyst | 📋 | User Stories, Scope, Anforderungen |
| **2** | `architect` | Software-Architekt | 🏛️ | Systemarchitektur, API-Contracts, ADRs |
| **3** | `ui_ux` | UI/UX Designer | 🎨 | Wireframes, Design-Systeme, User Flows |
| **3** | `frontend` | Frontend-Entwickler | 💻 | HTML/CSS/JS, React, Vue.js |
| **3** | `backend` | Backend-Entwickler | ⚙️ | REST APIs, FastAPI, Python |
| **3** | `database` | Datenbank-Entwickler | 🗄️ | SQL/NoSQL, Schemas, Migrations |
| **3** | `mobile` | Mobile-Entwickler | 📱 | React Native, Flutter, iOS, Android |
| **3** | `ml` | KI/ML-Entwickler | 🤖 | LLM-APIs, ML-Modelle, RAG, Data Science |
| **3** | `performance` | Performance-Ingenieur | ⚡ | Load Tests, Profiling, Optimierung |
| **3** | `i18n` | Internationalisierungs-Spezialist | 🌍 | Mehrsprachigkeit, RTL, Zeitzonen |
| **3** | `devops` | DevOps-Ingenieur | 🚀 | Docker, CI/CD, GitHub Actions |
| **3** | `tester` | QA-Tester | 🧪 | pytest, Unit-Tests, Testpläne |
| **3** | `documentation` | Dokumentant | 📚 | README, API-Docs, Changelogs |
| **3** | `security` | Sicherheits-Analyst | 🔒 | OWASP, Code-Reviews, Sicherheit |
| **4** | `code_reviewer` | Code-Reviewer | 🔍 | Code-Qualität, Konsistenz, Best Practices |
| **U** | `readme` | README-Agent | 📝 | Automatische README-Pflege |
| **U** | `github` | GitHub-Agent | 🔀 | Git-Operationen, Commit-Messages |

---

## 🔄 4-Phasen-Workflow

### Phase 1 – Business Analyst (optional, sequentiell)
> *Aktiv wenn: Anforderungen komplex/mehrdeutig sind*

- Analysiert die Nutzeranforderung vollständig
- Erstellt User Stories mit Given/When/Then Akzeptanzkriterien
- Definiert den Scope (In-Scope vs. Out-of-Scope)
- Priorisiert Features (MoSCoW)
- Sein Output fließt als Kontext an den Architekten

### Phase 2 – Software-Architekt (optional, sequentiell)
> *Aktiv wenn: mehrere Komponenten zusammenarbeiten*

- Entwirft die Gesamtarchitektur (C4-Modell, Mermaid-Diagramme)
- Definiert API-Contracts zwischen allen Komponenten
- Trifft begründete Technologieentscheidungen (ADRs)
- Sein Blueprint wird als Pflicht-Kontext an ALLE Phase-3-Agenten übergeben

### Phase 3 – Implementierung (immer, vollständig parallel)
> *Alle relevanten Agenten arbeiten gleichzeitig*

```
⏱ T=0s:  Alle Phase-3-Agenten starten gleichzeitig
          (mit Architektur-Blueprint als Kontext)
⏱ T≈30s: Erste Agenten fertig
⏱ T≈60s: Alle fertig → weiter zu Phase 4
```

### Phase 4 – Code-Reviewer (optional, sequentiell)
> *Aktiv bei jeder Code-produzierenden Aufgabe*

- Bekommt den gesamten Code aller Phase-3-Agenten
- Prüft Konsistenz zwischen Frontend/Backend/DB
- Identifiziert Bugs, Anti-Patterns, fehlende Error-Handling
- Erstellt priorisierten Fix-Plan

---

## 📁 Projektstruktur

```
AI-Softwareentwickler-Team/
│
├── 📄 main.py                            # Einstiegspunkt
├── 📄 config.py                          # Konfiguration & API-Keys
├── 📄 requirements.txt                   # Python-Abhängigkeiten
├── 📄 .env                               # Secrets (nicht in Git!)
├── 📄 .gitignore
├── 📄 README.md
│
├── 📂 agents/                            # Alle 17 KI-Agenten
│   ├── orchestrator.py                   # ⭐ Hauptagent (4-Phasen-Workflow)
│   ├── base_agent.py                     # Abstrakte Basisklasse
│   │
│   │── Phasen-Agenten (sequentiell) ─────
│   ├── business_analyst_agent.py         # 📋 Phase 1: Business Analyst
│   ├── architect_agent.py                # 🏛️  Phase 2: Software-Architekt
│   ├── code_reviewer_agent.py            # 🔍 Phase 4: Code-Reviewer
│   │
│   │── Implementierungs-Agenten (parallel)
│   ├── ui_ux_agent.py                    # 🎨 UI/UX Designer
│   ├── frontend_agent.py                 # 💻 Frontend-Entwickler
│   ├── backend_agent.py                  # ⚙️  Backend-Entwickler
│   ├── database_agent.py                 # 🗄️  Datenbank-Entwickler
│   ├── mobile_agent.py                   # 📱 Mobile-Entwickler (NEU)
│   ├── ml_agent.py                       # 🤖 KI/ML-Entwickler (NEU)
│   ├── performance_agent.py              # ⚡ Performance-Ingenieur (NEU)
│   ├── i18n_agent.py                     # 🌍 i18n-Spezialist (NEU)
│   │
│   │── Infrastruktur & Qualität ──────────
│   ├── devops_agent.py                   # 🚀 DevOps-Ingenieur
│   ├── tester_agent.py                   # 🧪 QA-Tester
│   ├── documentation_agent.py            # 📚 Dokumentant
│   ├── security_agent.py                 # 🔒 Sicherheits-Analyst
│   │
│   │── Utility-Agenten ───────────────────
│   ├── readme_agent.py                   # 📝 README-Agent
│   └── github_agent.py                   # 🔀 GitHub-Agent
│
├── 📂 core/                              # Kernsystem
│   ├── llm_factory.py                    # Gemini/Claude + Retry/Fallback
│   ├── task_manager.py                   # Task-Zerlegung (17 Agenten)
│   ├── result_aggregator.py              # Ergebnis-Synthese
│   └── message_bus.py                    # Datenklassen & Nachrichtentypen
│
├── 📂 memory/                            # Persistenz
│   └── conversation_history.py           # Gesprächsverlauf (RAM + JSON)
│
└── 📂 interface/                         # Benutzeroberflächen
    └── cli.py                            # Rich-basiertes CLI
```

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
```env
# .env Datei bearbeiten:
GEMINI_API_KEY=dein-gemini-api-key-hier
ANTHROPIC_API_KEY=dein-claude-key-hier  # optional
```

**API-Keys besorgen:**
| Dienst | URL | Kostenlos? |
|--------|-----|-----------|
| Google Gemini | https://aistudio.google.com | ✅ Ja (mit Limits) |
| Anthropic Claude | https://console.anthropic.com | ❌ Bezahlt |

### Schritt 4: Starten
```bash
python main.py
```

---

## ⚙️ Konfiguration

```env
# ── API Keys ──────────────────────────────────────
GEMINI_API_KEY=AQ.xxx...              # Pflicht
ANTHROPIC_API_KEY=sk-ant-...          # Optional (für Claude)

# ── Modelle ───────────────────────────────────────
ORCHESTRATOR_MODEL=gemini-3.6-flash   # Hauptagent
DEFAULT_AGENT_MODEL=gemini-3.6-flash  # Standard für alle Agenten

# Agenten-spezifische Modelle (optional)
BACKEND_MODEL=gemini-3.6-flash
TESTER_MODEL=gemini-3.6-flash

# ── Verhalten ─────────────────────────────────────
AGENT_LANGUAGE=de                     # de=Deutsch, en=Englisch
MAX_OUTPUT_TOKENS=8192
TEMPERATURE=0.7
```

---

## 💻 Verwendung

```bash
python main.py
```

### Beispiel-Aufgaben

```
# Einfache REST API (aktiviert: Architekt, Backend, Tester, DevOps, Docs, Reviewer)
Erstelle eine REST API für ein Blog-System mit FastAPI

# Vollständige Web-App (alle relevanten Agenten)
Baue eine Todo-App mit React, FastAPI, PostgreSQL und User-Authentifizierung

# Mobile App (aktiviert: BA, Architekt, Mobile, Backend, DB, Tester, Reviewer)
Entwickle eine React Native App für Fitness-Tracking mit Offline-Support

# KI-Feature (aktiviert: BA, Architekt, ML, Backend, Tester, Security, Reviewer)
Erstelle einen KI-Chatbot mit RAG über meine Produktdokumentation

# Performance-Analyse (aktiviert: Performance, Backend)
Analysiere und optimiere die Performance meiner FastAPI-Endpunkte

# Internationale App (aktiviert: i18n, Frontend, Backend)
Mache meine React-App für Deutsch, Englisch und Arabisch (RTL) bereit

# Security-Audit (aktiviert: Security, Code-Reviewer)
Überprüfe mein Login-System auf Sicherheitslücken
```

---

## 🖥️ CLI-Befehle

| Befehl | Beschreibung |
|--------|-------------|
| `/team` | Zeigt alle 17 Agenten mit Phasen-Zuordnung |
| `/verlauf` | Zeigt den bisherigen Gesprächsverlauf |
| `/neu` | Startet eine neue Konversation |
| `/hilfe` | Zeigt alle Befehle |
| `/beenden` | Beendet das Programm |

---

## 🤖 Agenten im Detail

### 📋 Business Analyst (`business_analyst`) – Phase 1
Klärt Anforderungen bevor irgendjemand mit der Implementierung beginnt.
- User Stories mit Given/When/Then Akzeptanzkriterien
- Scope-Definition (In/Out of Scope)
- MoSCoW-Priorisierung
- Non-Functional Requirements
- Getroffene Annahmen transparent dokumentieren

### 🏛️ Software-Architekt (`architect`) – Phase 2
Entwirft den Blueprint, nach dem alle anderen arbeiten.
- C4-Modell und Mermaid-Systemdiagramme
- API-Contracts zwischen allen Komponenten
- Architecture Decision Records (ADRs)
- Technologie-Stack mit Begründung
- Skalierbarkeits- und Risiko-Analyse

### 🎨 UI/UX Designer (`ui_ux`) – Phase 3
- Wireframe-Beschreibungen mit konkreten Spezifikationen (HEX/HSL)
- User Flows und Interaktionsdesign
- Barrierefreiheit (WCAG)
- Design-System-Empfehlungen

### 💻 Frontend-Entwickler (`frontend`) – Phase 3
- HTML5, CSS3, JavaScript (ES2023+), TypeScript
- React.js, Vue.js 3, Next.js
- Responsive Design, Core Web Vitals
- State Management, API-Integration

### ⚙️ Backend-Entwickler (`backend`) – Phase 3
- FastAPI, Django, Flask (Python bevorzugt)
- REST API Design mit OpenAPI/Swagger
- JWT, OAuth2, Authentifizierung
- Clean Architecture, SOLID

### 🗄️ Datenbank-Entwickler (`database`) – Phase 3
- PostgreSQL, MySQL, MongoDB, Redis
- ER-Diagramme und Schema-Design
- Migrations (Alembic), Query-Optimierung
- Index-Strategien

### 📱 Mobile-Entwickler (`mobile`) – Phase 3 *(NEU)*
- React Native mit Expo (TypeScript)
- Flutter (Dart, Riverpod)
- Native iOS (Swift/SwiftUI), Android (Kotlin/Jetpack Compose)
- Push Notifications, Offline-First, Deep Linking
- App Store / Google Play Deployment

### 🤖 KI/ML-Entwickler (`ml`) – Phase 3 *(NEU)*
- LLM-Integration (Gemini, Claude, OpenAI API)
- RAG-Systeme mit Vektordatenbanken (Pinecone, Chroma)
- Machine Learning (scikit-learn, PyTorch, TensorFlow)
- Prompt Engineering, Fine-Tuning
- Hugging Face, LangChain, LlamaIndex

### ⚡ Performance-Ingenieur (`performance`) – Phase 3 *(NEU)*
- Load Tests mit k6 und Locust
- Backend-Profiling (py-spy, cProfile)
- N+1 Query Detection, Caching-Strategien
- Core Web Vitals, Bundle-Analyse
- Monitoring mit Prometheus/Grafana

### 🌍 Internationalisierungs-Spezialist (`i18n`) – Phase 3 *(NEU)*
- react-i18next, vue-i18n, next-intl
- ICU Message Format (Pluralisierung, Interpolation)
- RTL-Support (Arabisch, Hebräisch, Persisch)
- Datum/Zeit/Währungsformatierung (Intl API)
- Übersetzungs-Workflow und i18n-Architektur

### 🚀 DevOps-Ingenieur (`devops`) – Phase 3
- Docker & Docker Compose
- GitHub Actions CI/CD-Pipelines
- Nginx, Traefik (Reverse Proxy)
- Cloud-Deployment (AWS, GCP, Azure)

### 🧪 QA-Tester (`tester`) – Phase 3
- pytest (Python), Jest (JavaScript)
- Unit-Tests, Integrationstests, E2E-Tests (Playwright/Cypress)
- TDD, Coverage-Analyse
- Testpläne und Bug-Reports

### 📚 Dokumentant (`documentation`) – Phase 3
- README-Dateien (GitHub-Standard)
- API-Dokumentation (OpenAPI, Docstrings)
- Architektur-Diagramme (Mermaid)
- Changelog-Erstellung

### 🔒 Sicherheits-Analyst (`security`) – Phase 3
- OWASP Top 10 Analyse
- SQL/NoSQL-Injection, XSS, CSRF Prävention
- Dependency-Scanning, Secret Management
- Security-Reports mit Schweregrad-Bewertung

### 🔍 Code-Reviewer (`code_reviewer`) – Phase 4 *(NEU)*
Das letzte Qualitätstor – prüft den gesamten Team-Output:
- Code-Qualität, Lesbarkeit, Wartbarkeit
- Konsistenz zwischen allen Komponenten
- Anti-Patterns und fehlende Error-Handling
- Bewertung + priorisierter Fix-Plan

### 📝 README-Agent (`readme`) – Utility
- Hält README.md bei Projektänderungen aktuell

### 🔀 GitHub-Agent (`github`) – Utility
- Conventional Commit Messages
- Branch-Strategien, PR-Beschreibungen

---

## 🔧 Erweiterung

### Neuen Agenten hinzufügen

1. **`agents/mein_agent.py`** erstellen:
```python
from agents.base_agent import BaseAgent

class MeinAgent(BaseAgent):
    def __init__(self):
        super().__init__(agent_id="mein_agent", name="Mein Spezialist")

    @property
    def system_prompt(self) -> str:
        return """Du bist Experte für...
        Kernkompetenzen: ...
        Ausgabe-Format: ..."""
```

2. **`agents/orchestrator.py`** – Agent importieren und registrieren:
```python
from agents.mein_agent import MeinAgent
# In __init__:
self._agents["mein_agent"] = MeinAgent()
```

3. **`core/task_manager.py`** – `AVAILABLE_AGENTS` erweitern:
```python
"mein_agent": {
    "name": "Mein Spezialist",
    "phase": 3,
    "description": "Zuständig für... EINSETZEN wenn: ..."
}
```

### Verschiedene Modelle pro Agent

```env
# .env
BACKEND_MODEL=gemini-3.6-flash
TESTER_MODEL=claude-sonnet-4-5
ML_MODEL=gemini-2.5-pro
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

## 📝 Changelog

### v1.2.0 (2026-08-18) – 17-Agenten Release
- ➕ **`mobile_agent.py`** – React Native, Flutter, iOS, Android
- ➕ **`ml_agent.py`** – LLM-APIs, ML-Modelle, RAG, Data Science
- ➕ **`performance_agent.py`** – Load Tests (k6/Locust), Profiling, Optimierung
- ➕ **`i18n_agent.py`** – Mehrsprachigkeit, RTL, Zeitzonen, Währungen
- ➕ **`architect_agent.py`** – System-Blueprint, ADRs, API-Contracts
- ➕ **`code_reviewer_agent.py`** – Code-Qualität, Konsistenz-Check
- ➕ **`business_analyst_agent.py`** – User Stories, Scope, Anforderungen
- 🔄 **Orchestrator** – Komplett neu mit intelligentem 4-Phasen-Workflow
- 🔄 **TaskManager** – Alle 17 Agenten mit Phasen-Metadaten
- 📖 **README.md** – Vollständig aktualisiert

### v1.1.0 (2026-08-18)
- ➕ README-Agent und GitHub-Agent hinzugefügt
- 📖 Erste vollständige README.md

### v1.0.0 (2026-08-18)
- 🎉 Erstes Release mit 10 Agenten
- ✅ Parallele Ausführung mit asyncio
- ✅ Gemini JSON-Modus für Task-Zerlegung
- ✅ Automatischer Retry + Modell-Fallback
- ✅ Rich CLI mit Live-Status

---

## 🤝 Mitwirken

1. Fork des Repositories
2. Feature-Branch: `git checkout -b feature/NeuerAgent`
3. Commit: `git commit -m 'feat(agents): NeuerAgent hinzugefügt'`
4. Push: `git push origin feature/NeuerAgent`
5. Pull Request erstellen

---

## 📄 Lizenz

MIT License

---

<div align="center">

**17 KI-Spezialisten | 4-Phasen-Workflow | Powered by Google Gemini**

[⭐ Star auf GitHub](https://github.com/Schengii/AI-Softwareentwickler-Team) | [🐛 Bug melden](https://github.com/Schengii/AI-Softwareentwickler-Team/issues)

</div>
