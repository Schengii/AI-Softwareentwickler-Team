# 🤖 KI-Softwareentwickler-Team (v4.3)

<div align="center">

[![CI](https://github.com/Schengii/AI-Softwareentwickler-Team/actions/workflows/ci.yml/badge.svg)](https://github.com/Schengii/AI-Softwareentwickler-Team/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Hierarchy](https://img.shields.io/badge/Fachbereichs--Hierarchie-5_Teamleiter-blue?style=for-the-badge)
![Specialists](https://img.shields.io/badge/KI--Spezialisten-33_Agenten-success?style=for-the-badge)
![Resilience-Guard](https://img.shields.io/badge/Resilience--Guard-Fault--Tolerance_&_CircuitBreaker-orange?style=for-the-badge)
![RAG](https://img.shields.io/badge/Codebase_RAG-Gemini_Embeddings_%2B_BM25--Fallback-orange?style=for-the-badge)
![MCP](https://img.shields.io/badge/MCP_Server-IDE_Ready-6941C6?style=for-the-badge)
![Web-UI](https://img.shields.io/badge/Web--Dashboard-Dark_Mode-2ea043?style=for-the-badge)
![Persistent-Learning](https://img.shields.io/badge/Persistente_Selbstoptimierung-Aktiv-success?style=for-the-badge)
![Sandbox-Validation](https://img.shields.io/badge/Sandbox_Auto--Validierung-Aktiv-blueviolet?style=for-the-badge)

**Ein autonomes, hierarchisch strukturiertes KI-Team für vollständige, token-optimierte Softwareentwicklung.**  
33 hochspezialisierte KI-Experten – aufgeteilt in **5 Fachbereiche mit jeweils eigenem Teamleiter**, **Resilience-Guard (Circuit Breakers, Backoff, Graceful Degradation & Chaos Tests)**, **persistentem Langzeit-Gedächtnis & automatischer Selbstoptimierung**, **Prompt-Engineering**, **WCAG 2.2 Barrierefreiheit (a11y)**, **integriertem RAG-Vektorindex**, **Model Context Protocol (MCP)**, **Web-Dashboard**, **Sandbox-Code-Validierung**, **Tavily Live-Web-Recherche**, **DeepSeek Reasoning**, **Groq Turbo Inferenz** und Workspace-Dateisystem.

</div>

---

## 🛠️ Echter agentischer Werkzeug-Loop, echte Verifikation & aktive Teamleiter

Seit dem letzten Umbau ist das Team kein reiner Ein-Schuss-Textgenerator mehr, sondern nutzt echtes,
providerübergreifendes Function-Calling:

- **Echte Werkzeuge statt nur Text:** Jeder Agent mit Projektzugriff bekommt `read_file`, `write_file`,
  `edit_file` (präziser Patch statt Volltext-Neuerstellung), `list_files`, `search_code`, `run_command`
  und `run_tests` – und ruft sie über natives Function-Calling von Gemini/DeepSeek/Groq/Claude/OpenRouter
  wirklich auf, bevor er eine Aufgabe als erledigt meldet (`agents/base_agent.py`, `core/agent_toolbox.py`).
- **Echte Verifikation statt Keyword-Raten:** Nach der QA-Phase installiert der Hauptagent Abhängigkeiten
  in einer isolierten venv und führt die tatsächliche Testsuite aus (`core/verifier.py`). Schlägt ein Test
  fehl, wird der reale Traceback geparst und der Korrekturauftrag GEZIELT an genau den Agenten geschickt,
  der die betroffene Datei geschrieben hat – nicht mehr blind an alle Dev-Agenten.
- **Aktive Fachbereichs-Teamleiter:** Jeder der 5 Teamleiter delegiert und konsolidiert jetzt über einen
  echten LLM-Aufruf (nicht mehr nur simulierte Statusmeldungen) und erscheint mit eigenem, geprüftem
  Ergebnis in der finalen Kennzahlen-Tabelle.

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

<a id="teamstruktur"></a>
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

<a id="kommunikations-workflow"></a>
## 🔄 Kommunikations- & Delegations-Workflow

Was die Grafik oben zeigt, läuft technisch über zwei einfache Datenstrukturen
(`core/message_bus.py`) und einen festen 5-Phasen-Ablauf (`agents/orchestrator.py`):

1. **Zerlegung:** `TaskManager.decompose()` lässt den Hauptagenten die Nutzeranfrage in eine
   Liste von `AgentTask`-Objekten (Agent-ID + präzise Teilaufgabe) aufteilen – nur die
   Spezialisten, die für die Aufgabe wirklich gebraucht werden.
2. **Phasen-Durchlauf:** Die 5 Fachbereiche laufen in fester Reihenfolge (`PHASE_ORDER`):
   Planung → Entwicklung → Design/Content → QA/Security → Governance. Planung und
   Governance laufen sequenziell, die anderen drei parallel (`asyncio.gather`).
3. **Echte Delegation:** Vor jeder Phase bekommt der zuständige Teamleiter einen echten
   LLM-Aufruf mit der Aufgabenliste seines Fachteams und liefert priorisierte
   Arbeitsanweisungen zurück, die den Mitgliedern als Zusatzkontext mitgegeben werden.
4. **Ausführung mit echtem Werkzeugzugriff:** Jedes Fachteam-Mitglied arbeitet über den
   agentischen Werkzeug-Loop (siehe oben) direkt im Projektverzeichnis und liefert ein
   `AgentResult` (Erfolg/Fehler, Inhalt, Tokens, geschriebene Dateien) zurück.
5. **Echte Konsolidierung:** Nach jeder Phase prüft derselbe Teamleiter per weiterem
   LLM-Aufruf die Ergebnisse seines Teams und erstellt den offiziellen Fachbereichsbericht.
   Eine `file_owners`-Map merkt sich dabei, welcher Agent welche Datei geschrieben hat –
   die Grundlage für die gezielte Fehlerbehebung in der Verifikationsphase (siehe unten).
6. **Synthese:** Der Hauptagent fasst alle Fachbereichsberichte über `ResultAggregator`
   zu einem einheitlichen Gesamtergebnis zusammen und liefert es an den Nutzer zurück.

---

<a id="resilience-guard"></a>
## 🛡️ Neuer Spezialist: Resilience-Guard (QA & Fault-Tolerance)

Der [ResilienceGuardAgent](agents/resilience_guard_agent.py) sichert Software gegen Ausfälle ab:
- **Circuit Breaker:** Unterbricht Anfragen an ausgefallene Fremddienste, bevor der eigene Server überlastet.
- **Smart Retries:** Exponentielles Backoff mit Jitter gegen Thundering-Herd-Probleme.
- **Graceful Degradation:** Fällt nahtlos auf Caches oder Fallbacks zurück.
- **Chaos Tests:** Schreibt gezielte Unit-Tests zur Simulation von Netzwerk-Timeouts und Verbindungsabbrüchen.

---

<a id="web-dashboard"></a>
## 🌐 Modernes Web-Dashboard & Visualisierung

```bash
python main.py --dashboard [--port N]   # Standard: Port 8080
```

Ein echter, funktionsfähiger HTTP-Server (`interface/web_dashboard.py`, stdlib
`ThreadingHTTPServer`, keine zusätzliche Web-Framework-Abhängigkeit):

- **Startseite:** Dark-Mode-UI mit Eingabefeld für neue Aufgaben und Live-Übersicht aller
  5 Fachbereiche mit ihren echten Mitgliederlisten (aus `DEPARTMENT_DEFINITIONS`, nicht
  hart codiert).
- **`POST /api/run`:** Nimmt eine Aufgabe entgegen und reiht sie in eine Job-Queue ein.
  Jobs laufen **seriell** in einem einzigen Hintergrund-Worker – bewusst kein paralleler
  Mehrfach-Betrieb, weil sich mehrere gleichzeitige Läufe sonst denselben
  Gesprächsverlauf (`ConversationHistory`) teilen und gegenseitig verfälschen würden.
- **`GET /api/status/<job_id>`:** Wird vom Frontend alle 2 Sekunden abgefragt und liefert
  denselben Live-Fortschritt (Status-Zeilen je Fachbereich/Agent), den auch die CLI zeigt,
  plus das fertige Ergebnis, sobald der Lauf abgeschlossen ist.
- **`GET /api/status`:** Echte Team-Metadaten (Agentenanzahl, Fachbereiche, Mitglieder) aus
  der laufenden `Orchestrator`-Instanz statt fest verdrahteter Werte.

---

<a id="mcp-server"></a>
## 🔌 MCP-Server: Einbindung in Cursor, Windsurf & Antigravity

`interface/mcp_server.py` ist ein Model-Context-Protocol-Server über stdio (JSON-RPC 2.0),
mit dem jede MCP-fähige IDE das gesamte Team als Werkzeug ansprechen kann.

**Start:** `python -m interface.mcp_server`

**Einbindung** (Beispiel für die MCP-Client-Konfiguration, z. B. Cursor `mcp.json` oder
Claude Desktop `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "ki-softwareentwickler-team": {
      "command": "python",
      "args": ["-m", "interface.mcp_server"],
      "cwd": "/pfad/zu/AI-Softwareentwickler-Team"
    }
  }
}
```

**Bereitgestellte Werkzeuge:**

| Tool | Beschreibung |
|---|---|
| `ai_team_develop` | Führt das komplette Team für eine beliebige Aufgabe aus (`prompt`) und liefert das fertige, geprüfte Ergebnis. |
| `ai_team_list_projects` | Listet alle vorhandenen Projekte im `workspace/`-Verzeichnis auf. |
| `ai_team_rag_search` | Durchsucht ein konkretes Projekt (`project` + `query`) semantisch – dieselbe Gemini-Embedding-Suche wie `/rag` in der CLI. |

---

<a id="sandbox-validierung"></a>
## 🧪 Sandbox-Code-Validierung & Automatische Test-Execution

Zwei unabhängige Prüfebenen, die sich ergänzen:

1. **Statische Validierung** (`core/code_sandbox.py`): Prüft Python-Code per `ast.parse()`
   auf Syntaxfehler, JSON per `json.loads()`, YAML auf grobe Formatierungsfehler (z. B. Tabs
   statt Leerzeichen) – schnell, ohne Ausführung, ohne Abhängigkeiten.
2. **Echte dynamische Verifikation** (`core/verifier.py`, `ProjectVerifier`): Legt bei
   vorhandener `requirements.txt` eine isolierte venv im Projekt an, installiert die
   Abhängigkeiten wirklich per `pip`, und führt die tatsächliche Testsuite aus (`pytest`,
   falls installiert, sonst `unittest discover`). Schlägt ein Test fehl, wird der reale
   Traceback geparst (beide Formate: klassischer Python-Traceback und pytest-Kurzformat)
   und der betroffene Agent anhand der `file_owners`-Map gezielt zur Korrektur beauftragt –
   bis zu `MAX_VERIFICATION_ITERATIONS` Runden (Standard: 2).

Beide Ebenen laufen automatisch als Teil jedes Orchestrator-Laufs, ohne dass der Nutzer sie
manuell anstoßen muss. Manuell erreichbar über `/run-tests [projekt]` in der CLI.

---

<a id="persistente-selbstoptimierung"></a>
## 🧠 Persistente KI-Selbstoptimierung & Langzeitgedächtnis

- **Gesprächsverlauf** (`memory/conversation_history.py`): Jede Nutzer-/Assistenten-Nachricht
  wird als JSON unter `memory/history_<session>.json` persistiert und bei künftigen Anfragen
  als Kontext (gekürzt auf die letzten Nachrichten) mitgegeben – Konversationen überleben
  also einen Neustart des Programms.
- **Agenten-Wissensbasis** (`memory/agent_knowledge_base.py`): Nach jedem Lauf analysiert der
  `agent_trainer`-Agent per LLM-Aufruf Fehler und Ineffizienzen und schlägt konkrete
  Prompt-Schärfungen vor. Diese werden geparst und pro Agent als Liste kurzer Regeln in
  `memory/agent_learnings.json` gespeichert (max. 5 pro Agent – älteste fällt raus) und bei
  jedem künftigen Aufruf automatisch an dessen System-Prompt angehängt
  (`get_augmented_prompt()`).
- **Ehrliche Einschränkung:** Die Extraktion der Lern-Regeln aus dem Trainer-Bericht basiert
  auf einem einfachen Textmuster (`"Betroffener Agent:"` gefolgt von Aufzählungspunkten).
  Hält sich das Modell nicht exakt an dieses Format, geht der Lerneffekt für diesen Lauf
  verloren – ein bekanntes, bewusst in Kauf genommenes Risiko einer leichtgewichtigen,
  abhängigkeitsfreien Lösung statt eines strukturierten Function-Calling-Extrahierens.

---

<a id="codebase-rag"></a>
## 🔍 Lokales Codebase-RAG & Semantische Suche

Agenten (über das `search_code`-Werkzeug), `/load` bestehender Projekte, der `/rag`-CLI-Befehl
und der MCP-Server (`ai_team_rag_search`) durchsuchen den Code semantisch über echte
Gemini-Embeddings (`core/embedding_index.py`, Modell `gemini-embedding-001`, 768 Dimensionen)
– findet auch Treffer ohne Wortüberschneidung, z. B. liefert *"Wie wird ein Nutzer
eingeloggt?"* die passende `auth.py`, obwohl dort nirgends "einloggen" steht.

- **Persistenter Cache pro Projekt** (`workspace/<projekt>/.ai_team_rag/index.json`): Nur
  neue oder per SHA-256-Hash erkannte geänderte Dateien werden neu eingebettet – nicht das
  gesamte Projekt bei jedem Aufruf.
- **Automatischer Fallback:** Ohne `GEMINI_API_KEY` oder bei einem fehlgeschlagenen
  Embedding-Aufruf springt das System auf die eingebaute BM25-Keyword-Suche
  (`core/vector_store.py`) zurück – die Suche funktioniert also immer, nur mit
  unterschiedlicher Qualität.

---

<a id="die-33-spezialisten"></a>
## 🎯 Die 33 Spezialisten & Fachbereiche

| Fachbereich | Teamleiter | Spezialisten im Team |
|---|---|---|
| 🔵 **Planung, Analyse & Architektur** | `planning_lead` | `product_owner`, `business_analyst`, `web_research`, `architect`, `finops`, `team_lead` |
| 🟢 **Software-Entwicklung** | `dev_lead` | `backend`, `frontend`, `database`, `api_integration`, `data_engineer`, `mobile`, `ml`, `prompt_engineer`, `performance` |
| 🎨 **Design, Media & Content** | `creative_lead` | `image_generator`, `copywriter`, `ui_ux`, `accessibility`, `i18n`, `documentation`, `readme` |
| 🟡 **Qualität, DevOps & Security** | `qa_lead` | `devops`, `tester`, `security`, `resilience_guard`, `github` |
| 🔴 **Excellence & Governance** | `governance_lead` | `code_reviewer`, `refactoring`, `compliance`, `project_cleaner`, `agent_trainer`, `retrospective` |

---

<a id="cli-befehle"></a>
## 🚀 Alle CLI-Befehle im Überblick

```bash
python main.py                          # Interaktive CLI (Standard)
python main.py --dashboard [--port N]   # Web-Dashboard unter http://localhost:8080
```

Details zum Web-Dashboard: [🌐 Modernes Web-Dashboard & Visualisierung](#web-dashboard).

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

<a id="tests"></a>
## 🧪 Tests ausführen

```bash
python -m unittest discover -s tests -p "test_*.py"
```

Die komplette Testsuite ist vollständig gemockt und läuft **ohne jeden API-Key/echten
LLM-Aufruf** durch (verifiziert). `.github/workflows/ci.yml` führt sie bei jedem Push/PR
gegen `main` automatisch aus (Python 3.11 & 3.12) – kostenlos, ohne Secrets nötig, plus
ein Syntax-Check aller Quelldateien. Echte End-to-End-Läufe mit echten LLM-Aufrufen
bleiben bewusst ein manueller, gezielter Schritt und sind nicht Teil der CI.

## 🧹 Lint (ruff)

```bash
pip install -r requirements-dev.txt
ruff check .
```

Konfiguration in `ruff.toml` (bewusst auf den Framework-Code beschränkt, `workspace/`
mit den vom Team selbst generierten Beispielprojekten ist ausgeschlossen). Läuft als
eigener, paralleler `lint`-Job in `.github/workflows/ci.yml` bei jedem Push/PR.
