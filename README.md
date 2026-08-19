# 🤖 KI-Softwareentwickler-Team (v2.0)

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Gemini](https://img.shields.io/badge/Google_Gemini-4285F4?style=for-the-badge&logo=google&logoColor=white)
![Claude](https://img.shields.io/badge/Anthropic_Claude-D4A017?style=for-the-badge&logoColor=white)
![Agents](https://img.shields.io/badge/Agenten-23-success?style=for-the-badge)
![asyncio](https://img.shields.io/badge/asyncio-Parallel-green?style=for-the-badge)
![License](https://img.shields.io/badge/Lizenz-MIT-blue?style=for-the-badge)

**Ein autonomes, multi-agenten KI-Team für vollständige, professionelle Softwareentwicklung.**  
23 spezialisierte KI-Experten – mit 5-Phasen-Workflow, iterativem Review- & Fix-Loop, Code-Sandbox und Workspace-Dateisystem.

</div>

---

## 📖 Inhaltsverzeichnis

- [Überblick](#überblick)
- [Agentenstruktur (23 Spezialisten)](#agentenstruktur)
- [5-Phasen-Workflow & Iterativer Fix-Loop](#5-phasen-workflow)
- [Workspace & Code-Execution Engine](#workspace-dateisystem)
- [Projektstruktur](#projektstruktur)
- [Installation & Setup](#installation)
- [Konfiguration](#konfiguration)
- [CLI-Befehle](#cli-befehle)
- [Automatisierte Tests](#tests)
- [Agenten im Detail](#agenten-im-detail)
- [Changelog](#changelog)

---

## 🌟 Überblick

Das **KI-Softwareentwickler-Team** ist ein professionelles Python-Framework, das ein komplettes 23-köpfiges Entwickler- und Engineering-Team simuliert. Der Nutzer interagiert mit dem **Hauptagenten (Orchestrator)**, der die Aufgabenstellung intelligent analysiert, die passenden Spezialisten über 5 Phasen koordiniert, Code-Qualität in einem iterativen Fix-Loop sichert und fertige Projektdateien direkt im Workspace abspeichert.

### Kernfunktionen

| Funktion | Beschreibung |
|---|---|
| 🏛️ **5-Phasen-Workflow** | Product/BA $\rightarrow$ Architekt/FinOps $\rightarrow$ Parallele Entwicklung $\rightarrow$ Review/Compliance $\rightarrow$ Workspace/Synthese |
| 🔄 **Iterativer Review- & Fix-Loop** | Automatische Nachbesserung durch Entwickler bei kritischen Mängeln im Review |
| 📁 **Automatischer Datei-Workspace** | Generierter Code wird strukturiert in `workspace/<projekt>/` abgelegt und kann als ZIP exportiert werden |
| 🧪 **Code-Sandbox & Validation** | Statische Syntax- und Typprüfung für Python, JSON & YAML sowie Subprocess-Testausführung |
| ⚡ **Vollparallele Ausführung** | Entwickler- und QA-Spezialisten arbeiten gleichzeitig via `asyncio.gather()` |
| 🛡️ **Legal & Compliance Audit** | Integrierter DSGVO/GDPR-Check, Lizenzprüfung (GPL vs. MIT) und Barrierefreiheit (WCAG 2.1) |
| 💰 **FinOps & Cloud-Kalkulation** | Vorab-Kostenschätzung für AWS, GCP, Hetzner, Serverless und AI-Tokens |

---

## 🏗️ Agentenstruktur

### Vollständige Team-Übersicht (23 Spezialisten)

```
Du (Nutzer)
    │  Aufgabe / Vision
    ▼
┌─────────────────────────────────────────────────────────────┐
│                🤖 HAUPTAGENT (Orchestrator)                  │
│   Task-Zerlegung → Phasensteuerung → Fix-Loop → Synthese    │
└─────────────────────────────────────────────────────────────┘
         │
         │  5-Phasen-Workflow & Iterative Schleifen
         │
    ┌────▼────┐
    │ Phase 1 │  🎯 Product Owner  &  📋 Business Analyst
    └────┬────┘  (Vision, MVP-Scope, User Stories, Akzeptanzkriterien)
         │ Anforderungs- & Produktkontext
    ┌────▼────┐
    │ Phase 2 │  🏛️ Software-Architekt  &  💰 Cost & FinOps
    └────┬────┘  (Systemdiagramme, API-Contracts, Cloud-Kosten & TCO)
         │ Vollständiger Blueprint (an alle Implementierer)
    ┌────▼─────────────────────────────────────────────────────────┐
    │ Phase 3 │  ALLE PARALLEL                                      │
    │         │  🎨 UI/UX      💻 Frontend   ⚙️ Backend   🗄️ Database │
    │         │  🔌 API/Integ. 🌊 Data Eng.  📱 Mobile    🤖 KI/ML    │
    │         │  ⚡ Performance 🌍 i18n       🚀 DevOps   🧪 QA/Tester│
    │         │  📚 Docs       🔒 Security                            │
    └────┬─────────────────────────────────────────────────────────┘
         │ Vollständige Komponenten & Codeblöcke
    ┌────▼────┐
    │ Phase 4 │  🔍 Code-Reviewer  &  🧹 Refactoring  &  ⚖️ Compliance
    └────┬────┘  (Qualitätsprüfung, Tech-Debt, DSGVO, Lizenzen, a11y)
         │
         ├───► [Kritische Mängel?] ──► 🛠️ Automatischer Fix-Loop (Phase 3)
         │
    ┌────▼────┐
    │ Phase 5 │  💾 Workspace-Export (`workspace/<projekt>/`)
    │Synthese │  📝 Finale Zusammenfassung & Dokumentation
    └─────────┘
```

### Agenten-Tabelle

| Phase | ID | Name | Symbol | Spezialisierung |
|---|---|---|---|---|
| **1** | `product_owner` | Product Owner | 🎯 | MVP-Scope, MoSCoW, Epic-Roadmap |
| **1** | `business_analyst` | Business Analyst | 📋 | User Stories, Akzeptanzkriterien, Scope |
| **2** | `architect` | Software-Architekt | 🏛️ | Systemarchitektur, API-Contracts, ADRs |
| **2** | `finops` | Cost & FinOps Engineer | 💰 | Cloud-Kosten (AWS/GCP/Hetzner), TCO, AI Tokens |
| **3** | `ui_ux` | UI/UX Designer | 🎨 | Wireframes, Design-Systeme, User Flows |
| **3** | `frontend` | Frontend-Entwickler | 💻 | React, Vue, Next.js, HTML/CSS |
| **3** | `backend` | Backend-Entwickler | ⚙️ | REST APIs, FastAPI, Node.js, Python |
| **3** | `database` | Datenbank-Entwickler | 🗄️ | PostgreSQL, MongoDB, Schema, ORM |
| **3** | `api_integration` | API & Integration Specialist | 🔌 | OpenAPI 3.1, GraphQL, Webhooks, Stripe, OAuth2 |
| **3** | `data_engineer` | Data Engineer | 🌊 | Kafka, RabbitMQ, Redis Cache, ETL Pipelines |
| **3** | `mobile` | Mobile-Entwickler | 📱 | Flutter, React Native, iOS, Android |
| **3** | `ml` | KI/ML-Entwickler | 🤖 | LLM-APIs, RAG-Systeme, Embeddings, ML |
| **3** | `performance` | Performance-Ingenieur | ⚡ | Load-Testing, Profiling, Query-Optimierung |
| **3** | `i18n` | Internationalisierungs-Spezialist | 🌍 | Mehrsprachigkeit (i18n), RTL, Lokalisierung |
| **3** | `devops` | DevOps-Ingenieur | 🚀 | Docker, Docker-Compose, CI/CD, K8s |
| **3** | `tester` | QA-Tester | 🧪 | pytest, Unittests, Integrationstests |
| **3** | `documentation` | Dokumentant | 📚 | API-Docs, Inline-Kommentare, Markdown |
| **3** | `security` | Sicherheits-Analyst | 🔒 | OWASP Top 10, Injection, Auth-Audits |
| **4** | `code_reviewer` | Code-Reviewer | 🔍 | Code-Qualität, Konsistenz, Scoring |
| **4** | `refactoring` | Refactoring Specialist | 🧹 | Tech-Debt, Code Smells, Type-Hints, Clean Code |
| **4** | `compliance` | Legal & Compliance Specialist | ⚖️ | DSGVO/GDPR, Open-Source-Lizenzen, WCAG 2.1 |
| **U** | `readme` | README-Agent | 📝 | Projekt-README-Pflege |
| **U** | `github` | GitHub-Agent | 🔀 | PR-Texte, Git-Strategien, Commit-Messages |

---

## 🔄 5-Phasen-Workflow & Iterativer Fix-Loop

1. **Phase 1 – Produkt & Anforderungen (PO & BA):** Erstellt die Produktvision, grenzt das MVP ab und liefert User Stories.
2. **Phase 2 – Architektur & FinOps:** Entwirft den technischen Blueprint und kalkuliert die monatlichen Cloud- & Token-Kosten.
3. **Phase 3 – Parallele Entwicklung:** Alle Frontend-, Backend-, Daten- und Infrastruktur-Experten implementieren gleichzeitig auf Basis des Blueprints.
4. **Phase 4 – Review, Refactoring & Compliance:**
   - **Code-Reviewer** prüft Qualität und Konsistenz.
   - **Refactoring Agent** beseitigt Tech-Debt und optimiert Typsicherheit.
   - **Compliance Agent** auditiert DSGVO, Barrierefreiheit und Lizenzen.
5. **Iterativer Fix-Loop:** Werden im Review gravierende Fehler oder Inkompatibilitäten entdeckt, beauftragt der Orchestrator die betroffenen Entwickler automatisch mit gezielten Nachbesserungen.
6. **Phase 5 – Workspace & Synthese:** Alle erstellten Dateien werden in `workspace/<projekt>/` geschrieben und dem Nutzer übersichtlich präsentiert.

---

## 📁 Workspace Dateisystem & CLI-Befehle

| Befehl | Beschreibung |
|---|---|
| `/team` | Zeigt alle 23 Agenten und Phasen an |
| `/workspace [projekt]` | Zeigt den Dateibaum des generierten Projekts an |
| `/export [projekt]` | Exportiert das gesamte Projektverzeichnis als ZIP-Archiv |
| `/run-tests [projekt]` | Führt Unittests im Projektverzeichnis aus |
| `/verlauf` | Zeigt den bisherigen Konversationsverlauf an |
| `/neu` | Startet eine neue Session (löscht Verlauf) |
| `/hilfe` | Zeigt die Befehlsübersicht an |
| `/beenden` | Beendet die Anwendung |

---

## 🚀 Installation & Schnellstart

```bash
# Repository klonen
git clone https://github.com/Schengii/AI-Softwareentwickler-Team.git
cd AI-Softwareentwickler-Team

# Abhängigkeiten installieren
pip install -r requirements.txt

# .env konfigurieren
cp .env.example .env  # Trage deinen GEMINI_API_KEY ein

# Anwendung starten
python main.py
```

---

## 🧪 Tests ausführen

```bash
# Vollständige Testsuite ausführen (Agents, Core, Workspace, Sandbox & Workflows)
python -m unittest discover -s tests -p "test_*.py"
```

---

## 📝 Changelog (v2.0)

- ✨ **Team-Erweiterung auf 23 Spezialisten**: Neu hinzugefügt: `Product Owner`, `Cost & FinOps`, `API & Integration Specialist`, `Data Engineer`, `Refactoring Specialist`, `Legal & Compliance Specialist`.
- 📁 **Automatisches Workspace-Dateisystem (`core/workspace.py`)**: Parst Codeblöcke aus Agenten-Antworten und legt echte, lauffähige Projektdateien ab.
- 🔄 **Iterativer Review- & Fix-Loop**: Automatisierte Nachbesserung von fehlerhaftem Code vor Abschluss der Synthese.
- 🧪 **Code-Sandbox (`core/code_sandbox.py`)**: Statische Python-, JSON- & YAML-Validierung sowie isolierter Testrunner.
- 🛠️ **Tool Registry & Vorbereitung für MCP (`core/tool_registry.py`)**: Standardisierte Werkzeug-Schnittstelle.
- 🖥️ **Erweiterte CLI**: Neue Befehle `/workspace`, `/export`, `/run-tests`.
- ✅ **Umfassende automatisierte Testsuite (`tests/`)**.
