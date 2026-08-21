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

## 📜 Änderungsprotokoll

Jede bisherige Verbesserungsrunde entstand aus einem konkreten, real beobachteten Fund
(meist aus einem echten Lauf gegen ein echtes Projekt), nicht aus spekulativen Ideen –
die vollständige, chronologische Historie steht jetzt in [CHANGELOG.md](CHANGELOG.md),
damit dieses README als aktuelle Funktionsübersicht schlank bleibt.

---

## 📖 Inhaltsverzeichnis

- [Hierarchische Team- & Fachbereichsstruktur (Grafik)](#teamstruktur)
- [Kommunikations- & Delegations-Workflow](#kommunikations-workflow)
- [🛡️ Neuer Spezialist: Resilience-Guard (QA & Fault-Tolerance)](#resilience-guard)
- [🔀 PR-Workflow: Feature-Branch + Pull Request statt Direct-Push](#pr-workflow)
- [🎫 Autonome, getriggerte Arbeit: GitHub-Issues als Backlog](#issue-watcher)
- [📋 Backlog/Kanban-Board über CLI, Dashboard & Issue-Watcher hinweg](#backlog-kanban)
- [🌐 Modernes Web-Dashboard & Visualisierung](#web-dashboard)
- [🔌 MCP-Server: Einbindung in Cursor, Windsurf & Antigravity](#mcp-server)
- [🔍 Lokales Codebase-RAG & Semantische Suche](#codebase-rag)
- [🧪 Sandbox-Code-Validierung & Automatische Test-Execution](#sandbox-validierung)
- [🪙 Hartes Lauf-Budget (MAX_RUN_TOKENS)](#lauf-budget)
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

<a id="pr-workflow"></a>
## 🔀 PR-Workflow: Feature-Branch + Pull Request statt Direct-Push

`/push` (bzw. der automatische Push-Dialog nach jedem Lauf) committete bisher IMMER direkt
auf den gerade ausgecheckten Branch – bei einem frischen/geladenen Projekt i.d.R. `main`.
Ein echtes Team committet nicht direkt auf den Hauptbranch: eigener Feature-Branch pro
Aufgabe, Pull Request, Merge erst nach grüner CI und Freigabe.

- **Automatischer Feature-Branch:** Ist der aktuell ausgecheckte Branch einer der
  `GIT_PROTECTED_BRANCHES` (Standard: `main,master`) UND die `gh`-CLI installiert und
  eingeloggt (`gh_ready()`), legt `agents/github_agent.py` vor dem Commit automatisch einen
  eindeutigen Feature-Branch an (`feat/<slug-der-aufgabe>-<uuid>`), pusht ihn und öffnet
  per `gh pr create` einen Pull Request gegen den ursprünglichen Hauptbranch – der
  Vorschau-Dialog vor der Bestätigung zeigt das vorab an, kein blindes Ja/Nein.
- **Arbeitsverzeichnis bleibt auf dem Feature-Branch:** Nach Push + PR-Erstellung wechselt
  der Agent NICHT zurück zum Hauptbranch (realer Fund: ein `git checkout` hätte jede Datei,
  die nur auf dem Feature-Branch committet ist, aus dem Arbeitsverzeichnis entfernt – das
  gerade generierte Projekt wäre bis zum Merge lokal unsichtbar gewesen). Der NÄCHSTE Lauf
  erkennt einen so zurückgelassenen `feat/`-Branch automatisch als eigenen Leftover-Zustand
  und zweigt seinen neuen Feature-Branch trotzdem korrekt vom konfigurierten Hauptbranch ab,
  nicht vom Leftover-Branch.
- **Graceful Degradation:** Ist bereits ein manuell ausgecheckter Feature-/Worktree-Branch
  aktiv (kein Hauptbranch und kein eigener `feat/`-Leftover), oder ist `gh` nicht
  installiert/nicht eingeloggt, oder schlägt das Anlegen des Branches fehl, fällt der Ablauf
  automatisch auf den bisherigen Direct-Push zurück – der Nutzer wird informiert, aber nicht
  blockiert. `ENABLE_PR_WORKFLOW=false` schaltet den gesamten PR-Workflow ab und stellt das
  alte Verhalten wieder her.

---

<a id="issue-watcher"></a>
## 🎫 Autonome, getriggerte Arbeit: GitHub-Issues als Backlog

Bisher wurde das Team ausschließlich durch eine direkte Nutzeranfrage aktiv (CLI, Dashboard,
MCP). `python main.py --check-issues` ergänzt die Gegenrichtung: ein einzelner Poll-Zyklus,
gedacht für einen wiederkehrenden externen Aufruf (Cron, Windows-Taskplaner, GitHub-Actions-
Schedule, z.B. alle 10–15 Minuten) – kein eingebauter Dauer-Scheduler, das übernimmt
zuverlässiger die vorhandene Infrastruktur.

- **Opt-in-Backlog statt Autopilot auf dem ganzen Tracker:** Nur offene Issues mit dem Label
  `ISSUE_TRIGGER_LABEL` (Standard: `ai-team`) werden aufgegriffen – ein Mensch entscheidet
  weiterhin, welche Tickets das Team bekommt, genau wie bei einem triagierten Backlog in
  einem echten Team.
- **Label-Zustandsmaschine gegen Doppelbearbeitung:** `ai-team-in-progress` wird VOR dem Lauf
  gesetzt (schützt vor überlappenden Poll-Zyklen), `ai-team-done` bzw. `ai-team-blocked`
  danach – alle drei Namen über `ISSUE_*_LABEL` in `config.py` änderbar.
  `core/issue_watcher.py` legt die Labels bei Bedarf automatisch im Repo an.
- **Immer über den PR-Workflow, nie Direct-Push:** Jedes bearbeitete Issue bekommt einen
  frischen Feature-Branch + Pull Request (`Closes #<issue-nummer>` im Body, damit GitHub das
  Issue beim Merge automatisch schließt) – ohne den `gh_ready()`-Fallback auf Direct-Push des
  interaktiven Pfads, da dafür eine menschliche Bestätigung nötig wäre, die hier fehlt.
- **Schärferes Sicherheitsmodell als der interaktive Pfad:** Ein Secret-Fund blockiert HART
  (kein Push, kein PR, Issue-Kommentar mit Warnung) statt nur zu warnen – niemand ist da, der
  bewusst übersteuern könnte. Fehlgeschlagene Verifikation blockiert dagegen NICHT hart,
  sondern öffnet den PR trotzdem mit deutlicher `⚠️ Verifikation nicht bestanden`-Kennzeichnung
  in Titel/Body, damit ein Mensch das beim Review sieht statt die Arbeit stillschweigend zu
  verwerfen.
- **Ergebnis immer als Issue-Kommentar sichtbar:** PR-Link, Blockade-Grund oder Fehler landen
  als Kommentar auf dem Issue – die einzige Rückmeldung, die ohne CLI/Dashboard-Ansicht
  überhaupt ankommt.

**Einrichtung unter Windows** (`scripts/run_issue_watcher.ps1`): ruft `--check-issues` auf
und hängt die Ausgabe UTF-8-sicher an `logs/issue_watcher.log` an (nicht versioniert, siehe
`.gitignore`). Als wiederkehrender Taskplaner-Eintrag (alle 15 Min, läuft nur bei laufendem
PC – für unabhängigen Cloud-Betrieb siehe Hinweis unten):

```powershell
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument '-NoProfile -ExecutionPolicy Bypass -File "<projektpfad>\scripts\run_issue_watcher.ps1"'
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName "AI-Team-IssueWatcher" -Action $Action -Trigger $Trigger -Description "Poll-Zyklus fuer GitHub-Issues"
```

Wichtig: `--check-issues` braucht dieselben lokalen Voraussetzungen wie jeder andere Lauf –
gültige `.env` (API-Keys) und eine eingeloggte `gh`-CLI (`gh auth status`). Eine Cloud-basierte
Alternative (z.B. Claude Codes `/schedule`) hat KEINEN Zugriff auf lokale Secrets/das lokale
Framework und würde entweder eigene API-Keys in der Cloud-Umgebung brauchen oder die Arbeit
mit cloud-eigenen Tools statt dem eigenen Multi-Agent-Team erledigen – für dieses Feature
deshalb bewusst lokal gelöst.

---

<a id="backlog-kanban"></a>
## 📋 Backlog/Kanban-Board über CLI, Dashboard & Issue-Watcher hinweg

Bisher hatte jede Trigger-Quelle ihren eigenen, isolierten Fortschritts-Begriff: das
Web-Dashboard hielt Jobs nur im Speicher (weg nach jedem Neustart), der Issue-Watcher trackte
Fortschritt nur über GitHub-Labels (nur dort sichtbar), die CLI gar nicht. `core/backlog_store.py`
hält jetzt eine EINZIGE, persistente Ticket-Liste (`memory/backlog.json`), in die alle drei
Quellen schreiben:

- **Spalten:** `todo` → `in_progress` → `review` (PR eröffnet, wartet auf Merge) →
  `done`/`blocked`/`cancelled`.
- **CLI:** `/backlog` zeigt das Board als Tabelle. Jede Aufgabe legt beim Start ein Ticket an
  (sofort `in_progress`, noch bevor eine echte Kurzfassung vorliegt) und finalisiert es beim
  Abschluss über denselben Mechanismus wie der PR-Workflow (`_ask_for_git_push()`).
- **Dashboard:** Neuer Board-Bereich auf der Startseite (`GET /api/backlog`), aktualisiert
  sich alle 5 Sekunden – zeigt auch Tickets, die über die CLI oder autonome Issue-Läufe
  entstanden sind, nicht nur die Jobs dieses Dashboard-Prozesses.
- **Issue-Watcher:** Jedes aufgegriffene Issue ist sofort als `in_progress` sichtbar (nicht
  erst nach Abschluss) und landet je nach Ausgang auf `review` (PR eröffnet) oder `blocked`.
- **Merge-Erkennung (`core/merge_watcher.py`):** "review"-Tickets bleiben nicht für immer
  auf "review" hängen – `check_merged_tickets()` fragt für jedes den echten PR-Status per
  `gh pr view` ab und zieht den Backlog-Status nach: echt gemerged → `done`, ohne Merge
  geschlossen → `blocked`. Läuft automatisch im selben `--check-issues`-Poll-Zyklus mit
  (kein zusätzlicher Cron-Eintrag nötig) UND vor jeder `/backlog`-Anzeige in der CLI.

---

<a id="web-dashboard"></a>
## 🌐 Modernes Web-Dashboard & Visualisierung

```bash
python main.py --dashboard [--port N] [--host ADRESSE]   # Standard: Port 8080, nur localhost
```

Ein echter, funktionsfähiger HTTP-Server (`interface/web_dashboard.py`, stdlib
`ThreadingHTTPServer`, keine zusätzliche Web-Framework-Abhängigkeit):

- **Startseite:** Dark-Mode-UI mit Eingabefeld für neue Aufgaben und Live-Übersicht aller
  5 Fachbereiche mit ihren echten Mitgliederlisten (aus `DEPARTMENT_DEFINITIONS`, nicht
  hart codiert).
- **`POST /api/run`:** Nimmt eine Aufgabe entgegen und reiht sie ein. Bis zu
  `config.DASHBOARD_MAX_CONCURRENT_JOBS` (Standard: `2`) Jobs laufen dabei tatsächlich
  **gleichzeitig** – jeder mit einer frischen, isolierten `Orchestrator`-Instanz (eigener
  Gesprächsverlauf), damit sich parallele Läufe nicht gegenseitig verfälschen.
- **`POST /api/cancel/<job_id>`** + "⏹️ Lauf abbrechen"-Button im UI: bricht einen laufenden
  oder noch wartenden Job kooperativ ab (dieselben Prüfpunkte wie das bestehende
  `MAX_RUN_TOKENS`-Budget) – bereits erarbeitete Ergebnisse werden trotzdem ausgeliefert.
- **`GET /api/status/<job_id>`:** Wird vom Frontend alle 2 Sekunden abgefragt und liefert
  denselben Live-Fortschritt (Status-Zeilen je Fachbereich/Agent), den auch die CLI zeigt,
  plus das fertige Ergebnis, sobald der Lauf abgeschlossen ist.
- **`GET /api/status`:** Echte Team-Metadaten (Agentenanzahl, Fachbereiche, Mitglieder) aus
  einer festen `Orchestrator`-Instanz statt fest verdrahteter Werte.

**🔒 Sicherheit standardmäßig aktiv:** Der Server bindet per Default nur auf `127.0.0.1`
(`config.DASHBOARD_HOST`) – aus dem Netzwerk nicht erreichbar. Wer das Dashboard bewusst im
Netzwerk freigeben will (`--host 0.0.0.0` oder `DASHBOARD_HOST` in der `.env`), MUSS
zusätzlich `DASHBOARD_AUTH_TOKEN` setzen; ohne Token verweigert `run_dashboard()` den Start
mit einer klaren Fehlermeldung, statt unauthentifiziert im Netzwerk zu lauschen. Ist ein
Token gesetzt, verlangt jeder Request (auch `GET /`) entweder den Header
`Authorization: Bearer <token>` oder `?token=<token>` in der URL – sonst `401 Unauthorized`.

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

**🔒 Secrets bleiben vor Subprozessen verborgen:** `run_command`/`run_tests` (und damit jede
von einem Agenten ausgelöste `pip install`/`npm install`) starten den Kindprozess NICHT mit
der vollen Prozessumgebung dieses Frameworks – `core/code_sandbox.py` filtert vorher alles
heraus, dessen Variablenname nach einem Secret aussieht (`*_API_KEY`, `*_TOKEN`, …). Ein
bösartiges oder kompromittiertes Paket, das per Install-Skript Umgebungsvariablen ausliest,
bekommt so keine echten API-Keys zu sehen.

---

<a id="lauf-budget"></a>
## 🪙 Hartes Lauf-Budget (MAX_RUN_TOKENS)

`core/quota_estimator.py` zeigt den Tokenverbrauch live an – vorher aber nur als Anzeige,
ohne dass ein außer Kontrolle geratener Lauf (z. B. durch mehrere Verifikations-Fixversuche
mit kostenpflichtigen Heavy-Modellen wie Claude) je automatisch gestoppt wurde. `agents/orchestrator.py`
bricht Läufe jetzt tatsächlich ab, sobald das per `.env` konfigurierte `MAX_RUN_TOKENS`
(Standard: `0` = deaktiviert, bestehende Läufe bleiben unangetastet) erreicht wird:

- Die Prüfung erfolgt vor jeder der 5 Fachbereichs-Phasen sowie vor jedem Verifikations-Fixversuch
  (`_run_budget_exceeded()`), nicht mitten in einer laufenden Phase – bereits begonnene Arbeit
  wird also nicht abgewürgt.
- Bei Überschreitung werden verbleibende Fachbereiche, weitere Verifikations-Fixversuche sowie
  Retrospektive & Selbstoptimierung übersprungen – die bis dahin erarbeiteten Ergebnisse werden
  trotzdem synthetisiert und ausgeliefert, nicht verworfen (Graceful Degradation statt Abbruch
  ohne Ergebnis).
- Die `### 📈 Projekt-Kennzahlen`-Tabelle zeigt bei aktivem Budget zusätzlich `Lauf-Budget: X / Y
  Tokens` an, sodass der Verbrauch schon während des Laufs sichtbar ist (nicht erst danach).

---

<a id="persistente-selbstoptimierung"></a>
## 🧠 Persistente KI-Selbstoptimierung & Langzeitgedächtnis

- **Gesprächsverlauf** (`memory/conversation_history.py`): Jede Nutzer-/Assistenten-Nachricht
  wird als JSON unter `memory/history_<session>.json` persistiert und bei künftigen Anfragen
  als Kontext (gekürzt auf die letzten Nachrichten) mitgegeben – Konversationen überleben
  also einen Neustart des Programms.
- **Agenten-Wissensbasis** (`memory/agent_knowledge_base.py`): Nach jedem Lauf analysiert der
  `agent_trainer`-Agent per LLM-Aufruf Fehler und Ineffizienzen und schlägt konkrete
  Prompt-Schärfungen vor. `Orchestrator._extract_and_store_learnings()` liest primär einen
  maschinenlesbaren ```json```-Block (`{"learnings": [{"agent_id": ..., "rule": ...}]}`) aus
  dem Trainer-Bericht – dabei explizit NICHT nur den ersten gefundenen Block, sondern den
  ersten, der wirklich einen `"learnings"`-Schlüssel enthält (der Bericht selbst zeigt in
  seinen Prompt-Diff-Beispielen oft schon ein illustratives ```json```-Snippet davor). Liefert
  das Modell keinen gültigen JSON-Block, greift ein Text-Fallback
  (`"Betroffener Agent:"` gefolgt von Aufzählungspunkten). Jede `agent_id` wird gegen die
  echten Agenten-/Leiter-IDs validiert. Regeln werden pro Agent als Liste in
  `memory/agent_learnings.json` gespeichert (max. 5 pro Agent – älteste fällt raus, jede
  einzelne Regel zusätzlich auf `MAX_RULE_LENGTH=300` Zeichen gedeckelt, da sie bei JEDEM
  künftigen Aufruf des Agenten erneut in dessen System-Prompt landet) und bei jedem künftigen
  Aufruf automatisch angehängt (`get_augmented_prompt()`). Über `/learnings` einsehbar und
  über `/delete-learning <agent> <nr>` gezielt korrigierbar, falls der Trainer mal eine
  falsche oder überholte Regel gelernt hat.
- **Kumulierte Kosten-Historie** (`memory/cost_history.py`): `/tokens` zeigt neben dem
  aktuellen Sitzungsverbrauch auch den Tokenverbrauch über ALLE bisher aufgezeichneten Läufe
  hinweg, pro Modell aufgeschlüsselt – bewusst nur echte Tokenzahlen, kein geschätzter
  $-Betrag (echte Preise unterscheiden sich pro Provider und ändern sich laufend).
- **Projekt-Konstitution** (`core/project_constitution.py`): `/constitution [projekt]` legt
  feste Tech-Stack-Präferenzen (Sprache, Framework, Test-Framework, Code-Stil,
  Deployment-Ziel) fest, die bei JEDEM künftigen Lauf an diesem Projekt als verbindlicher
  Kontext an alle Agenten mitgegeben werden – einmal festgelegt statt bei jeder Anfrage neu
  spezifiziert.
- **Architecture Decision Records** (`core/adr.py`): Die Konstitution hält das WAS fest
  (Tech-Stack), aber nicht das WARUM ("REST statt GraphQL, weil…"). Der `architect`-Agent
  (und grundsätzlich jeder Agent im Werkzeug-Loop) dokumentiert echte Trade-off-Entscheidungen
  über das Werkzeug `record_architecture_decision` als nummerierte, mit dem Code versionierte
  Markdown-Datei unter `docs/adr/NNNN-titel.md` im Projekt (Nygard-Format: Titel, Status,
  Kontext, Entscheidung, Konsequenzen) – bewusst NICHT gitignored, anders als
  `memory/backlog.json`. Bereits getroffene Entscheidungen werden bei JEDEM künftigen Lauf
  automatisch in den Kontext aller Teilaufgaben injiziert, damit spätere Läufe nicht
  unbemerkt gegen frühere, bewusste Entscheidungen arbeiten. Über `/adr [projekt]` einsehbar.

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
python main.py --check-issues           # EIN Poll-Zyklus über offene GitHub-Issues, dann Ende
```

Details zum Web-Dashboard: [🌐 Modernes Web-Dashboard & Visualisierung](#web-dashboard).
Details zu `--check-issues`: [🎫 Autonome, getriggerte Arbeit](#issue-watcher).

| Befehl | Beschreibung |
|---|---|
| `/projekte` | Listet alle bestehenden Projekte im Workspace auf |
| `/load <pfad/name>` | Lädt ein bestehendes Projekt (Workspace oder externer Pfad) zur Weiterentwicklung |
| `/tokens` | Zeigt den aktuellen Tokenverbrauch dieser Sitzung UND den kumulierten Verbrauch über alle bisherigen Läufe an |
| `/rag <begriff>` | Führt eine semantische Code-Recherche im geladenen Projekt durch |
| `/team` | Zeigt alle 5 Fachbereiche, Teamleiter und 33 Spezialisten an |
| `/workspace [projekt]` | Listet alle generierten Dateien im Projektordner auf |
| `/export [projekt]` | Packt das Projektverzeichnis in ein ZIP-Archiv |
| `/run-tests [projekt]` | Führt automatische Unit-Tests im Projekt aus |
| `/delete-project <name>` | Löscht ein Projekt unwiderruflich aus dem Workspace (mit Bestätigung) |
| `/audit-projekt [projekt]` | Lässt den Projekt-Hygiene-Agenten das Framework (oder ein Projekt) wirklich durchsehen; Löschungen nur nach Bestätigung |
| `/learnings` | Zeigt alle von den Agenten gelernten Regeln (persistentes Gedächtnis) mit Nummer je Agent an |
| `/delete-learning <agent> <nr>` | Entfernt eine einzelne, falsche/überholte gelernte Regel (mit Bestätigung) |
| `/constitution [projekt]` | Zeigt/bearbeitet feste Tech-Stack-Präferenzen (Sprache, Framework, Code-Stil, …) für ein Projekt – gilt für jeden künftigen Lauf daran |
| `/adr [projekt]` | Zeigt die dokumentierten Architecture Decision Records (Begründungen echter Architektur-Entscheidungen) eines Projekts |
| `/backlog` | Zeigt das Kanban-Board (Todo/In Bearbeitung/Review/Blockiert/Fertig) über CLI, Dashboard UND autonome Issue-Läufe hinweg |
| `/deploy [projekt]` | Deployt ein Projekt lokal per Docker (Compose bevorzugt, sonst Dockerfile) – mit Vorschau & Bestätigung |
| `/deploy-stop [projekt]` | Fährt ein per `/deploy` gestartetes Deployment wieder herunter |
| `/push` | Führt manuell einen Git-Commit & Push aus (mit Secret-Scan, Verifikations-Warnung & PR-Workflow) |
| `/verlauf` | Zeigt den bisherigen Gesprächsverlauf |
| `/neu` | Startet eine neue Konversation (löscht Verlauf) |
| `/hilfe` | Zeigt die Befehlsübersicht an |
| `/beenden` | Beendet das Programm |

Während eines laufenden Teams: **Strg+C** bricht kooperativ ab (bereits begonnene Arbeit wird
zu Ende geführt, danach werden bisherige Ergebnisse ausgeliefert) – ein zweites Strg+C
erzwingt den sofortigen Abbruch.

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
