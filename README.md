# 🤖 KI-Softwareentwickler-Team (v4.3)

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Hierarchy](https://img.shields.io/badge/Fachbereichs--Hierarchie-5_Teamleiter-blue?style=for-the-badge)
![Specialists](https://img.shields.io/badge/KI--Spezialisten-33_Agenten-success?style=for-the-badge)
![Resilience-Guard](https://img.shields.io/badge/Resilience--Guard-Fault--Tolerance_&_CircuitBreaker-orange?style=for-the-badge)
![RAG](https://img.shields.io/badge/Codebase_RAG-In--Memory_BM25-orange?style=for-the-badge)
![MCP](https://img.shields.io/badge/MCP_Server-IDE_Ready-6941C6?style=for-the-badge)
![Web-UI](https://img.shields.io/badge/Web--Dashboard-Dark_Mode-2ea043?style=for-the-badge)
![Persistent-Learning](https://img.shields.io/badge/Persistente_Selbstoptimierung-Aktiv-success?style=for-the-badge)
![Sandbox-Validation](https://img.shields.io/badge/Sandbox_Auto--Validierung-Aktiv-blueviolet?style=for-the-badge)

**Ein autonomes, hierarchisch strukturiertes KI-Team für vollständige, token-optimierte Softwareentwicklung.**  
33 hochspezialisierte KI-Experten – aufgeteilt in **5 Fachbereiche mit jeweils eigenem Teamleiter**, **Resilience-Guard (Circuit Breakers, Backoff, Graceful Degradation & Chaos Tests)**, **persistentem Langzeit-Gedächtnis & automatischer Selbstoptimierung**, **Prompt-Engineering**, **WCAG 2.2 Barrierefreiheit (a11y)**, **integriertem RAG-Vektorindex**, **Model Context Protocol (MCP)**, **Web-Dashboard**, **Sandbox-Code-Validierung**, **Tavily Live-Web-Recherche**, **DeepSeek Reasoning**, **Groq Turbo Inferenz** und Workspace-Dateisystem.

</div>

---

## 📖 Inhaltsverzeichnis

- [Hierarchische Team- & Fachbereichsstruktur (Grafik)](#teamstruktur)
- [Kommunikations- & Delegations-Workflow](#kommunikations-workflow)
- [🛡️ Neuer Spezialist: Resilience-Guard (QA & Fault-Tolerance)](#resilience-guard)
- [🌐 Modernes Web-Dashboard & Visualisierung](#web-dashboard)
- [🔌 MCP-Server: Einbindung in Cursor, Windsurf & Antigravity](#mcp-server)
- [🔍 Lokales Codebase-RAG & Semantische Suche](#codebase-rag)
- [🧪 Sandbox-Code-Validierung & Automatische Test-Execution](#sandbox-validierung)
- [🧠 Persistente KI-Selbstoptimierung & Langzeitgedächtnis](#persistente-selbstoptimierung)
- [🎯 Die 33 Spezialisten & Fachbereiche](#die-33-spezialisten)
- [🚀 Alle CLI-Befehle im Überblick](#cli-befehle)
- [🧪 Automatisierte Tests](#tests)

---

## 🏢 Hierarchische Team- & Fachbereichsstruktur

```
                                  Du (Nutzer)
                                       │
                                       │ 1. Aufgabe & Anforderungen
                                       ▼
                   ┌───────────────────────────────────────┐
                   │       🤖 HAUPTAGENT (Orchestrator)    │
                   │   Koordiniert Gesamtablauf & Synthese │
                   └───────────────────┬───────────────────┘
                                       │
                       2. Teilt auf in 5 Fachbereiche
                                       │
       ┌───────────────────────────────┼───────────────────────────────┬───────────────────────────────┬───────────────────────────────┐
       ▼                               ▼                               ▼                               ▼                               ▼
 ┌───────────┐                   ┌───────────┐                   ┌───────────┐                   ┌───────────┐                   ┌───────────┐
 │ 👔 Team-  │                   │ ⚡ Team-  │                   │ 🎨 Team-  │                   │ 🛡️ Team-  │                   │ 🔍 Team-  │
 │  leiter   │                   │  leiter   │                   │  leiter   │                   │  leiter   │                   │  leiter   │
 │  Planung  │                   │ Dev-Team  │                   │  Design   │                   │ QA/DevOps │                   │Governance │
 └─────┬─────┘                   └─────┬─────┘                   └─────┬─────┘                   └─────┬─────┘                   └─────┬─────┘
       │                               │                               │                               │                               │
       │ 3. Delegiert an Fachteam      │ 3. Delegiert an Fachteam      │ 3. Delegiert an Fachteam      │ 3. Delegiert an Fachteam      │ 3. Delegiert an Fachteam
       ▼                               ▼                               ▼                               ▼                               ▼
 ┌───────────┐                   ┌───────────┐                   ┌───────────┐                   ┌───────────┐                   ┌───────────┐
 │  FACHTEAM │                   │  FACHTEAM │                   │  FACHTEAM │                   │  FACHTEAM │                   │  FACHTEAM │
 │ • Product │                   │ • Backend │                   │ • Image/  │                   │ • DevOps  │                   │ • Code-   │
 │   Owner   │                   │ • Frontend│                   │   SVG     │                   │ • Tester  │                   │   Reviewer│
 │ • Business│                   │ • Database│                   │ • Copy-   │                   │ • Security│                   │ • Refact- │
 │   Analyst │                   │ • API/Int.│                   │   writer  │                   │ • Resil-  │                   │   oring   │
 │ • Web-Res.│                   │ • DataEng.│                   │ • UI/UX   │                   │   ience   │                   │ • Compli- │
 │ • Architekt                   │ • Mobile  │                   │ • a11y    │                   │   Guard   │                   │    ance   │
 │ • FinOps  │                   │ • ML / AI │                   │ • i18n    │                   │ • GitHub  │                   │ • Cleaner │
 └─────┬─────┘                   │ • Prompt- │                   │ • Docs    │                   └─────┬─────┘                   │ • Trainer │
       │                         │   Engineer│                   │ • Readme  │                         │                         └─────┬─────┘
       │ 4. Meldet Ergebnis      │ • Perform.│                   └─────┬─────┘                         │ 4. Meldet Ergebnis            │
       ▼                         └─────┬─────┘                         │                               ▼                               │ 4. Meldet Ergebnis
 ┌───────────┐                         │                               │ 4. Meldet Ergebnis      ┌───────────┐                         ▼
 │ 👔 Team-  │                         │ 4. Meldet Ergebnis            ▼                         │ 🛡️ Team-  │                   ┌───────────┐
 │  leiter   │                         ▼                         ┌───────────┐                   │  leiter   │                   │ 🔍 Team-  │
 │  Planung  │                   ┌───────────┐                   │ 🎨 Team-  │                   │ QA/DevOps │                   │  leiter   │
 └─────┬─────┘                   │ ⚡ Team-  │                   │  leiter   │                   └─────┬─────┘                   │Governance │
       │                         │  leiter   │                   │  Design   │                         │                         └─────┬─────┘
       │                         └─────┬─────┘                   └─────┬─────┘                         │                               │
       └───────────────────────────────┴───────────────┬───────────────┴───────────────────────────────┴───────────────────────────────┘
                                                       │
                                                       │ 5. Alle Teamleiter liefern geprüfte Teilberichte
                                                       ▼
                                       ┌───────────────────────────────┐
                                       │   🤖 HAUPTAGENT (Synthese)    │
                                       │ • Führt alle Teile zusammen   │
                                       │ • Schreibt Projekt-Dateien    │
                                       │ • Führt finale Sandbox-Tests  │
                                       └───────────────┬───────────────┘
                                                       │
                                                       │ 6. Fertiges Gesamtergebnis & Projektdateien
                                                       ▼
                                                  Du (Nutzer)
```

---

## 🛡️ Neuer Spezialist: Resilience-Guard (QA & Fault-Tolerance)

Der [ResilienceGuardAgent (agents/resilience_guard_agent.py)](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/agents/resilience_guard_agent.py) sichert Software gegen Ausfälle ab:
- **Circuit Breaker:** Unterbricht Anfragen an ausgefallene Fremddienste, bevor der eigene Server überlastet.
- **Smart Retries:** Exponentielles Backoff mit Jitter gegen Thundering-Herd-Probleme.
- **Graceful Degradation:** Fällt nahtlos auf Caches oder Fallbacks zurück.
- **Chaos Tests:** Schreibt gezielte Unit-Tests zur Simulation von Netzwerk-Timeouts und Verbindungsabbrüchen.

---

## 🎯 Die 33 Spezialisten & Fachbereiche

| Fachbereich | Teamleiter | Spezialisten im Team |
|---|---|---|
| 🔵 **Planung, Analyse & Architektur** | `planning_lead` | `product_owner`, `business_analyst`, `web_research`, `architect`, `finops`, `team_lead` |
| 🟢 **Software-Entwicklung** | `dev_lead` | `backend`, `frontend`, `database`, `api_integration`, `data_engineer`, `mobile`, `ml`, `prompt_engineer`, `performance` |
| 🎨 **Design, Media & Content** | `creative_lead` | `image_generator`, `copywriter`, `ui_ux`, `accessibility`, `i18n`, `documentation`, `readme` |
| 🟡 **Qualität, DevOps & Security** | `qa_lead` | `devops`, `tester`, `security`, `resilience_guard`, `github` |
| 🔴 **Excellence & Governance** | `governance_lead` | `code_reviewer`, `refactoring`, `compliance`, `project_cleaner`, `agent_trainer`, `retrospective` |

---

## 🚀 Alle CLI-Befehle im Überblick

```bash
python main.py
```

| Befehl | Beschreibung |
|---|---|
| `/projekte` | Listet alle bestehenden Projekte im Workspace auf |
| `/load <pfad/name>` | Lädt ein bestehendes Projekt (Workspace oder externer Pfad) zur Weiterentwicklung |
| `/rag <begriff>` | Führt eine semantische Code-Recherche im geladenen Projekt durch |
| `/team` | Zeigt alle 5 Fachbereiche, Teamleiter und 33 Spezialisten an |
| `/workspace [projekt]` | Listet alle generierten Dateien im Projektordner auf |
| `/export [projekt]` | Packt das Projektverzeichnis in ein ZIP-Archiv |
| `/run-tests [projekt]` | Führt automatische Unit-Tests im Projekt aus |
| `/push` | Führt manuell einen Git-Commit & Push aus |
| `/verlauf` | Zeigt den bisherigen Gesprächsverlauf |
| `/neu` | Startet eine neue Konversation (löscht Verlauf) |
| `/hilfe` | Zeigt die Befehlsübersicht an |
| `/beenden` | Beendet das Programm |

---

## 🧪 Tests ausführen

```bash
python -m unittest discover -s tests -p "test_*.py"
```
