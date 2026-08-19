# 🤖 KI-Softwareentwickler-Team (v4.0)

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Hierarchy](https://img.shields.io/badge/Fachbereichs--Hierarchie-5_Teamleiter-blue?style=for-the-badge)
![Persistent-Learning](https://img.shields.io/badge/Persistente_Selbstoptimierung-Aktiv-success?style=for-the-badge)
![Sandbox-Validation](https://img.shields.io/badge/Sandbox_Auto--Validierung-Aktiv-blueviolet?style=for-the-badge)
![Multi-Project](https://img.shields.io/badge/Multi--Projekt--Support-Aktiv-success?style=for-the-badge)
![Token-Efficiency](https://img.shields.io/badge/Token--Sparmodus-Ultra_Effizient-blue?style=for-the-badge)
![DeepSeek](https://img.shields.io/badge/DeepSeek_V3-0066FF?style=for-the-badge&logo=deepseek&logoColor=white)
![Groq](https://img.shields.io/badge/Groq_Turbo-F55036?style=for-the-badge&logo=groq&logoColor=white)

**Ein autonomes, hierarchisch strukturiertes KI-Team für vollständige, token-optimierte Softwareentwicklung.**  
30 spezialisierte KI-Experten – aufgeteilt in **5 Fachbereiche mit jeweils eigenem Teamleiter**, **persistantem Langzeit-Gedächtnis & automatischer Selbstoptimierung**, **Sandbox-Code-Validierung**, **Multi-Projekt-Support**, **bidirektionalem Token-Lifecycle**, **Tavily Live-Web-Recherche**, **DeepSeek Reasoning**, **Groq Turbo Inferenz**, Projekt-Hygiene und Workspace-Dateisystem.

</div>

---

## 📖 Inhaltsverzeichnis

- [Hierarchische Team- & Fachbereichsstruktur (Grafik)](#teamstruktur)
- [Kommunikations- & Delegations-Workflow](#kommunikations-workflow)
- [Persistente KI-Selbstoptimierung & Langzeitgedächtnis](#persistente-selbstoptimierung)
- [Sandbox-Code-Validierung & Test-Execution](#sandbox-validierung)
- [Multi-Projekt & Externe Projekte weiterentwickeln](#multi-projekt-support)
- [Multi-LLM & Tool Matrix](#multi-llm--tool-matrix)
- [CLI-Befehle & Projektverwaltung](#cli-befehle)
- [Automatisierte Tests](#tests)

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
 │   Analyst │                   │ • API/Int.│                   │   writer  │                   │ • GitHub  │                   │   oring   │
 │ • Web-Res.│                   │ • DataEng.│                   │ • UI/UX   │                   └─────┬─────┘                   │ • Compli- │
 │ • Architekt                   │ • Mobile  │                   │ • i18n    │                         │                             ance    │
 │ • FinOps  │                   │ • ML / AI │                   │ • Docs    │                         │ 4. Meldet Ergebnis          │ • Cleaner │
 └─────┬─────┘                   │ • Perform.│                   │ • Readme  │                         ▼                             │ • Trainer │
       │                         └─────┬─────┘                   └─────┬─────┘                   ┌───────────┐                   └─────┬─────┘
       │ 4. Meldet Ergebnis            │                               │                         │ 🛡️ Team-  │                         │
       ▼                               │ 4. Meldet Ergebnis            │ 4. Meldet Ergebnis      │  leiter   │                         │ 4. Meldet Ergebnis
 ┌───────────┐                         ▼                               ▼                         └─────┬─────┘                         ▼
 │ 👔 Team-  │                   ┌───────────┐                   ┌───────────┐                         │                         ┌───────────┐
 │  leiter   │                   │ ⚡ Team-  │                   │ 🎨 Team-  │                         │                         │ 🔍 Team-  │
 │  Planung  │                   │  leiter   │                   │  leiter   │                         │                         │  leiter   │
 └─────┬─────┘                   └─────┬─────┘                   └─────┬─────┘                         │                         └─────┬─────┘
       │                               │                               │                               │                               │
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

## 🔄 Kommunikations- & Delegations-Workflow

1. **Aufgabenübergabe:** Du stellst die Anforderung wie gewohnt an den **Hauptagenten**.
2. **Fachbereichs-Routing:** Der Hauptagent teilt die Anforderung in 5 Fachbereiche auf und übergibt die Teilziele an die zuständigen **Fachbereichs-Teamleiter**.
3. **Fachteam-Delegation:** Jeder Teamleiter verteilt die Aufgaben an seine eigenen spezialisierten Unteragenten und koordiniert deren Ablauf.
4. **Bereichs-Qualitätsabnahme:** Sobald die Unteragenten eines Fachbereichs fertig sind, liefern sie ihre Ergebnisse an ihren Teamleiter. Der Teamleiter prüft die Ergebnisse und konsolidiert den Fachbereichs-Abschlussbericht.
5. **Rückmeldung & Synthese:** Alle Teamleiter übermitteln ihre Berichte an den Hauptagenten. Der Hauptagent wartet, bis alle Fachbereiche vollständig vorliegen, führt die Syntax- und Sandbox-Validierung durch, speichert alle Dateien in `workspace/<projekt>/` und präsentiert dir das geprüfte Gesamtergebnis.

---

## 🧠 Persistente KI-Selbstoptimierung & Langzeitgedächtnis

Das Entwicklerteam vergisst keine Fehler mehr. Über die [AgentKnowledgeBase (memory/agent_knowledge_base.py)](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/memory/agent_knowledge_base.py) speichert das Team gewonnene Erkenntnisse und Best Practices dauerhaft ab:
- **Ausbilder-Analyse (`agent_trainer`):** Ermittelt den Root Cause von Fehlern oder Ineffizienzen.
- **Persistentes Speichern:** Schreibt die gelernten Regeln in `memory/agent_learnings.json`.
- **Automatisches Anwenden:** Beim nächsten Projektlauf wird der System-Prompt des jeweiligen Agenten automatisch erweitert.

---

## 🧪 Sandbox-Code-Validierung & Schutz

Direkt nach der Kern-Entwicklung durchlaufen alle generierten Python-, JSON- und YAML-Codeblöcke automatisch die [CodeSandbox (core/code_sandbox.py)](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/core/code_sandbox.py):
- **Statische Syntax-Prüfung:** AST-Parser erkennt Syntaxfehler, fehlende Imports oder Tab/Indent-Fehler sofort.
- **Nahtlose Übergabe:** Eventuelle Mängel werden direkt dem Governance Lead und Code-Reviewer zur Bereinigung übergeben.

---

## 📂 Multi-Projekt-Support: Externe Projekte weiterentwickeln

Du kannst dein KI-Entwicklerteam ab sofort für **jedes beliebige bestehende oder externe Projekt** auf deinem PC einsetzen:

```bash
# Vorhandene Projekte anzeigen
/projekte

# Projekt aus dem Workspace oder externen Pfad laden
/load jobsuche-app
/load C:\Users\sche-\Desktop\MeinAnderesProjekt
```

---

## 🎯 Multi-LLM & Tool Matrix

| Provider / API | Zweck & Modell | Zugeordnete Agenten / Leads |
|---|---|---|
| 🏛️ **Heavy Tier** | `gemini-3.6-flash` / `claude-3-5-sonnet` | **Hauptagent**, **5 Fachbereichsleiter**, **Teamleiter (`team_lead`)**, **Ausbilder (`agent_trainer`)** |
| 🧠 **DeepSeek Tier** | `deepseek:deepseek-chat` | **Architekt (`architect`)**, **Backend (`backend`)**, **Datenbank (`database`)**, **Security (`security`)**, **Code-Reviewer (`code_reviewer`)**, **KI/ML (`ml`)** |
| ⚡ **Groq Turbo Tier** | `groq:openai/gpt-oss-120b` | **QA-Tester (`tester`)**, **Refactoring (`refactoring`)**, **Performance-Ingenieur (`performance`)** |
| 🚀 **Standard Tier** | `gemini-3.6-flash` | Frontend, Data Engineer, API Integration, DevOps, Product Owner, Copywriter, Compliance, Retrospektive |
| 🌐 **Tavily Search** | Echte Live-Recherche im Web | **Web-Recherche & Info Specialist (`web_research`)** |
| 🤗 **Hugging Face** | Image Prompts, Logos & Visuals | **Bild- & Grafik-Designer (`image_generator`)** |
| 💡 **Lite Tier** | `gemini-3.1-flash-lite` | Projekt-Hygiene (`project_cleaner`), UI/UX, Dokumentation, Übersetzungen, README, GitHub |

---

## 🚀 Alle CLI-Befehle im Überblick

```bash
python main.py
```

| Befehl | Beschreibung |
|---|---|
| `/projekte` | Listet alle bestehenden Projekte im Workspace auf |
| `/load <pfad/name>` | Lädt ein bestehendes Projekt (Workspace oder externer Pfad) zur Weiterentwicklung |
| `/team` | Zeigt alle 5 Fachbereiche, deren Teamleiter und Spezialisten an |
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
