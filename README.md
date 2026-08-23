  # 🤖 KI-Softwareentwickler-Team (v4.3)

<div align="center">

[![CI](https://github.com/Schengii/AI-Softwareentwickler-Team/actions/workflows/ci.yml/badge.svg)](https://github.com/Schengii/AI-Softwareentwickler-Team/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Hierarchy](https://img.shields.io/badge/Fachbereichs--Hierarchie-6_Teamleiter-blue?style=for-the-badge)
![Specialists](https://img.shields.io/badge/KI--Spezialisten-33_Agenten-success?style=for-the-badge)
![Resilience-Guard](https://img.shields.io/badge/Resilience--Guard-Fault--Tolerance_&_CircuitBreaker-orange?style=for-the-badge)
![RAG](https://img.shields.io/badge/Codebase_RAG-Gemini_Embeddings_%2B_BM25--Fallback-orange?style=for-the-badge)
![MCP](https://img.shields.io/badge/MCP_Server-IDE_Ready-6941C6?style=for-the-badge)
![Web-UI](https://img.shields.io/badge/Web--Dashboard-Dark_Mode-2ea043?style=for-the-badge)
![Persistent-Learning](https://img.shields.io/badge/Persistente_Selbstoptimierung-Aktiv-success?style=for-the-badge)
![Sandbox-Validation](https://img.shields.io/badge/Sandbox_Auto--Validierung-Aktiv-blueviolet?style=for-the-badge)

**Ein autonomes, hierarchisch strukturiertes KI-Team für vollständige, token-optimierte Softwareentwicklung.**  
33 hochspezialisierte KI-Experten – aufgeteilt in **6 Fachbereiche mit jeweils eigenem Teamleiter**, **Resilience-Guard (Circuit Breakers, Backoff, Graceful Degradation & Chaos Tests)**, **persistentem Langzeit-Gedächtnis & automatischer Selbstoptimierung**, **Prompt-Engineering**, **WCAG 2.2 Barrierefreiheit (a11y)**, **integriertem RAG-Vektorindex**, **Model Context Protocol (MCP)**, **Web-Dashboard**, **Sandbox-Code-Validierung**, **Tavily Live-Web-Recherche**, **DeepSeek Reasoning**, **Groq Turbo Inferenz** und Workspace-Dateisystem.

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
- [🔀 PR-Workflow & Kollaborativer Review-Loop](#pr-workflow)
- [🎫 Autonome, getriggerte Arbeit: GitHub-Issues als Backlog](#issue-watcher)
- [📋 Backlog/Kanban-Board über CLI, Dashboard & Issue-Watcher hinweg](#backlog-kanban)
- [🌐 Modernes Web-Dashboard & Visualisierung](#web-dashboard)
- [🔌 MCP-Server: Einbindung in Cursor, Windsurf & Antigravity](#mcp-server)
- [🕸️ AST-Codebase-Graph & Semantische Impact-Analyse](#code-graph)
- [🎭 Headless-Browser & Frontend-UI-Validierung](#browser-ui)
- [☁️ Cloud-Preview-Deployments (Fly.io, Vercel, Render)](#cloud-deploy)
- [🔍 Lokales Codebase-RAG & Semantische Suche](#codebase-rag)
- [🧪 Sandbox-Code-Validierung & Multi-Sprachen-Testing](#sandbox-validierung)
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
2. **Phasen-Durchlauf:** Die 6 Fachbereiche laufen in fester Reihenfolge (`PHASE_ORDER`):
   Planung → Vorab-Design → Software-Entwicklung → Content & Doku → QA/Security → Governance.
   Planung und Governance laufen sequenziell, die anderen parallel (`asyncio.gather`).
   Vorab-Design (UI/UX, Assets, Wireframes) liefert Spezifikationen direkt an die Entwickler,
   während Content & Dokumentation nachgelagert auf dem echten Code aufbauen.
3. **Echte Delegation:** Vor jeder Phase bekommt der zuständige Teamleiter einen echten
   LLM-Aufruf mit der Aufgabenliste seines Fachteams und liefert priorisierte
   Arbeitsanweisungen zurück, die den Mitgliedern als Zusatzkontext mitgegeben werden. **Ausnahme
   (Team-Komplexitäts-Skalierung):** Hat ein Fachbereich nur EIN Mitglied UND ist die
   Gesamtaufgabe klein (`core/task_manager.py.is_micro_task()`, rein deterministisch aus dem
   bereits erstellten Plan – kein zusätzlicher LLM-Aufruf), entfällt die Delegation, da hier
   kein echter Abstimmungsbedarf besteht. Fachbereiche mit mehreren Mitgliedern behalten die
   Teamleiter-Koordination immer. Abschaltbar über `ENABLE_TASK_COMPLEXITY_SCALING=false`.
4. **Ausführung mit echtem Werkzeugzugriff:** Jedes Fachteam-Mitglied arbeitet über den
   agentischen Werkzeug-Loop (siehe oben) direkt im Projektverzeichnis und liefert ein
   `AgentResult` (Erfolg/Fehler, Inhalt, Tokens, geschriebene Dateien) zurück.
5. **Echte Konsolidierung:** Nach jeder Phase prüft derselbe Teamleiter per weiterem
   LLM-Aufruf die Ergebnisse seines Teams und erstellt den offiziellen Fachbereichsbericht
   (bei einem einzelnen Mitglied und kleiner Gesamtaufgabe entfällt auch dieser Schritt, siehe
   Punkt 3). Eine `file_owners`-Map merkt sich dabei, welcher Agent welche Datei geschrieben
   hat – die Grundlage für die gezielte Fehlerbehebung in der Verifikationsphase (siehe unten).
6. **Governance-Fix-Loop:** `code_reviewer`/`security`/`compliance` kategorisieren Befunde in
   ihren Reports selbst nach Schweregrad ("Kritisch") – `agents/orchestrator.py._run_governance_fix_loop()`
   (`core/review_gate.py`) erkennt diese Befunde per Text-Heuristik und spielt sie GEZIELT an
   den laut `file_owners` zuständigen Agenten zur Korrektur zurück, BEVOR die echte
   Testverifikation läuft – ein "Kritisch" im Review ist bei einem echten Team ein Blocker,
   kein FYI im Abschlussbericht. Abschaltbar über `ENABLE_GOVERNANCE_FIX_LOOP=false`, Anzahl
   der Fix-/Recheck-Runden über `MAX_REVIEW_ITERATIONS` (Standard `1`).
7. **Synthese:** Der Hauptagent fasst alle Fachbereichsberichte über `ResultAggregator`
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
- **CI-Feedback-Loop:** Nach der PR-Erstellung wartet `core/issue_watcher.py` zusätzlich auf
  die echte CI-Pipeline (`agents/github_agent.py.wait_for_ci_status()`). Wird sie tatsächlich
  rot, zieht das Backlog-Ticket auf `blocked` (statt bei `review` stehen zu bleiben) und der
  Issue-Kommentar warnt explizit – das `ai-team-done`-Label bleibt trotzdem gesetzt, da ein PR
  ja tatsächlich eröffnet wurde. Derselbe Mechanismus (inkl. Ticket-Status) gilt auch für den
  interaktiven `/push`-Dialog in der CLI (`interface/cli.py._ask_for_git_push()`).
- **Externe Benachrichtigung:** `NOTIFY_WEBHOOK_URL` (Standard leer = deaktiviert) schickt bei
  jedem Ausgang, der menschliche Aufmerksamkeit braucht (blockiertes Issue, rote CI,
  erreichtes Lauf-Budget, fehlgeschlagener Dashboard-Job), einen echten Slack-Block-Kit-POST
  über `core/notifier.py` – fett hervorgehobenes Event-Label, farbiger Rand je nach grob
  erkanntem Schweregrad ("fehlgeschlagen"/"blockiert"/… → Rot) und Zeitstempel-Footer statt
  eines flachen, unformatierten Text-Strings. Ein `"text"`-Fallback-Feld bleibt zusätzlich
  gesetzt (Slacks eigene Konvention für Push-Vorschauen/Clients ohne Block-Kit-Rendering) –
  wichtig gerade hier, da beim Poll-Zyklus (und bei Dashboard-Hintergrund-Jobs) anders als in
  der CLI niemand aktiv zusieht.

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
- **Automatisches Release-Tagging (`core/release_manager.py`):** Wird ein Ticket dabei echt
  auf `done` gezogen (der PR also wirklich gemerged wurde) UND hat es ein `project_slug`,
  öffnet derselbe Zyklus direkt ein neues GitHub-Release (`<projekt>-vX.Y.Z`, fortlaufende
  Patch-Version je Projekt) mit automatischen Release-Notes (Ticket-Titel + PR-Link) – nicht
  nur das Framework selbst hatte bisher eine Versionshistorie, generierte Projekte in
  `workspace/` jetzt auch. Best effort: ein fehlgeschlagenes Tagging (z. B. `gh` fehlt) lässt
  das Ticket trotzdem korrekt auf `done` stehen. Zusätzlich pflegt `update_project_changelog()`
  bei jedem erfolgreichen Release eine echte `CHANGELOG.md` **im generierten Projekt selbst**
  (`workspace/<projekt>/CHANGELOG.md`, neueste Einträge zuerst) – über die GitHub-Contents-API
  direkt gegen den Default-Branch geschrieben (wie `gh release create` selbst operiert das ohne
  Eingriff in den lokalen Checkout). Bisher hatte nur das Framework-Repo ein gepflegtes
  CHANGELOG.md; das GitHub-Release allein macht die Versionshistorie nicht auch im Projekt
  selbst lesbar. Ebenfalls Best effort, ohne Rückwirkung auf den Release-Erfolg.
- **Priorität, Schätzung & WIP-Limit:** Jedes Ticket trägt jetzt `priority` (1=hoch/2=mittel/
  3=niedrig, bleibt über den gesamten Lebenszyklus erhalten, auch wenn ein Update sie nicht
  erneut mitgibt) und optional `estimate` (freier Text). `/backlog-add [priorität] <titel>`
  legt manuell ein noch nicht begonnenes, priorisiertes `todo`-Ticket an – bisher entstand
  jedes Ticket erst, wenn eine Aufgabe bereits lief, es gab keine Möglichkeit, mehrere geplante
  Aufgaben vorab zu priorisieren. `/backlog` sortiert jede Spalte danach und warnt (rein
  informativ, kein Hard-Block), wenn `BACKLOG_WIP_LIMIT_IN_PROGRESS` (Standard `0` = aus)
  überschritten ist.

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
- **`GET /api/observability`** + Panel "📈 Observability & Trends": Erfolgsquote je Agent
  (letzte 50 Läufe) als Balkenanzeige + Liste der jüngsten Läufe (Tokens, Dauer, Ergebnis) –
  aus `memory/run_history.py`, über ALLE Trigger-Quellen hinweg (CLI/Dashboard/Issue-Watcher),
  nicht nur Dashboard-Jobs. Ergänzt die bereits bestehende kumulierte Kosten-Historie
  (`/tokens`) um echte Trends statt nur Gesamtsummen.

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

<a id="code-graph"></a>
## 🕸️ AST-Codebase-Graph & Semantische Impact-Analyse

Große Codebases (50+ Dateien) erfordern mehr als reine Vektorsuche: Der [CodebaseGraph](core/code_graph.py) parst den gesamten Quelltext (`.py`, `.js`, `.ts`, `.tsx`) in einen echten Abstract-Syntax-Tree (AST) und stellt Agenten präzise strukturelle Werkzeuge zur Verfügung:

- **`find_symbol_definition`:** Findet die exakte Definition (Klasse, Methode, Funktion) dateiübergreifend mit Signatur und Docstring.
- **`find_symbol_references`:** Listet alle Aufrufe, Ableitungen und Imports eines Symbols über das gesamte Projekt hinweg.
- **`analyze_code_impact`:** Berechnet vor einem Refactoring die Auswirkung einer Änderung (welche Dateien, Module und Aufrufer brechen bei einer Signaturänderung?).

---

<a id="browser-ui"></a>
## 🎭 Headless-Browser & Frontend-UI-Validierung

Frontends (HTML/CSS/JS, React, Vue, FastAPI/Flask-Templates) werden durch [BrowserVerifier](core/browser_verifier.py) echten Funktionstests unterzogen:

- **Dynamischer Headless-Browser-Check (Playwright):** Startet die Anwendung auf einem freien Port, fängt JavaScript-Konsolenfehler (`console.error`, Uncaught Exceptions) ab und prüft das Rendering.
- **Asset- & 404-Integritätsprüfung:** Verifiziert, ob alle in HTML verlinkten CSS-, JS- und Bilddateien existieren.
- **Graceful Fallback:** Ist kein Browser-Binary installiert, analysiert das System den DOM-Baum statisch und schlägt bei fehlenden Assets oder fehlerhaften Tags an.

---

<a id="cloud-deploy"></a>
## ☁️ Cloud-Preview-Deployments (Fly.io, Vercel, Render, Railway)

Über das lokale Docker-Deployment hinaus generiert [CloudDeploymentManager](core/cloud_deployment.py) produktionsreife Cloud-Manifeste:

- **Fly.io:** Erstellt `fly.toml` und `Dockerfile` mit Region Frankfurt (`fra`) und Auto-Stop/Start.
- **Vercel:** Erstellt `vercel.json` für Serverless Python-, Next.js- oder Static-Deployments.
- **Render / Railway:** Erstellt Blueprints (`render.yaml`, `railway.json`).
- **CLI & Dashboard:** Kann per Dry-Run oder echten Deploy-Befehl (`flyctl deploy`, `vercel deploy`) direkt eine globale HTTPS-Preview-URL bereitstellen.

---

<a id="sandbox-validierung"></a>
## 🧪 Sandbox-Code-Validierung & Multi-Sprachen-Testing

Zwei unabhängige Prüfebenen, die sich ergänzen:

1. **Statische Validierung** (`core/code_sandbox.py`): Prüft Python-Code per `ast.parse()`
   auf Syntaxfehler, JSON per `json.loads()`, YAML auf grobe Formatierungsfehler – schnell, ohne Ausführung.
2. **Echte dynamische Multi-Sprachen-Verifikation** (`core/verifier.py`, `ProjectVerifier`):
   - **Python:** Isolierte venv, echte Testausführung (`pytest` / `unittest`), Testabdeckungsschwelle (`pytest-cov`), Linting (`ruff`), Security-Audit (`pip-audit`), Runtime-Smoke-Test.
   - **Node / TypeScript:** Echte Installation (`npm ci`/`npm install`), Testläufe (`npm test`), Linting (`eslint`, `tsc`), Security-Audit (`npm audit`).
   - **Rust:** `Cargo.toml`-Erkennung, Build-Check (`cargo check`), echte Tests (`cargo test`), Linting (`cargo clippy`), Security-Audit (`cargo audit`).
   - **Go:** `go.mod`-Erkennung, Modul-Download (`go mod download`), echte Tests (`go test -v ./...`), Linting (`go vet`), Security-Audit (`govulncheck`).
   - **SAST (Static Application Security Testing):** `bandit` scannt generierten Python-Code statisch auf bekannte Schwachstellenmuster (hartcodierte Secrets, unsichere Deserialisierung, SQL-Injection-Vektoren, unsichere Zufallszahlen, `eval`/`exec`, …) – ersetzt die bisher rein LLM-basierte Freitext-Einschätzung des `security`-Agenten (keine Datei/Zeile) durch einen echten, geparsten Fund mit exaktem Fundort. Node/Rust/Go folgen ggf. in einer späteren Runde.
   - **Lizenz-/SBOM-Audit:** `pip-licenses` liest die Lizenzen der tatsächlich installierten Python-Abhängigkeiten aus und markiert bekannte Copyleft-Lizenzen (GPL/AGPL/LGPL/MPL/CDDL/EUPL/SSPL) – ersetzt die bisher geratene Lizenz-Tabelle des `compliance`-Agenten durch echte Paket-Metadaten statt einer LLM-Vermutung.
   - **Lastentest (Smoke-Level):** Vom `performance`-Agenten geschriebene k6-/Locust-Skripte (`tests/load/`) werden jetzt tatsächlich AUSGEFÜHRT statt nur unausgeführt im Projekt zu liegen – die App wird auf einem freien Port gestartet, ein kurzer Lasttest (wenige Sekunden, wenige virtuelle Nutzer) läuft dagegen. Kein vollständiger Lasttest/Benchmark, nur eine Prüfung, ob die App unter minimaler gleichzeitiger Last fehlerfrei antwortet. Opt-out über `ENABLE_LOAD_TEST_CHECK=false`.
   - **Accessibility-Scan (WCAG 2.x):** `axe-core-python` scannt generierte Web-Frontends echt per axe-core gegen eine per Playwright gerenderte Seite – ersetzt die bisher rein LLM-basierte Freitext-Checkliste des `accessibility`-Agenten durch geparste Verstöße mit Regel/Schweregrad/betroffenem Element.
   Schlägt ein Test fehl, wird der reale Traceback geparst und der betroffene Agent anhand der `file_owners`-Map gezielt zur Korrektur beauftragt (bis zu `MAX_VERIFICATION_ITERATIONS` Runden). SAST- und Lizenz-Funde sind (wie Lint) rein informativ im Abschlussbericht sichtbar – ein Fund braucht menschliche Einschätzung (False Positives, Lizenz-Nutzungskontext) statt eines automatischen Blockers. Ein fehlgeschlagener Lastentest zählt dagegen wie der Runtime-Smoke-Test als echte Anforderungsverletzung.

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

**Zusätzlich: Pro-Projekt-Kostenbudget über ALLE Läufe hinweg.** `MAX_RUN_TOKENS` begrenzt nur
EINEN einzelnen Lauf – ein Projekt mit vielen aufeinanderfolgenden Läufen (z. B. für einen
externen Auftraggeber mit festem Kostenrahmen) hatte bisher kein Limit über die gesamte
Projekt-Lebenszeit. `/constitution` (Feld `max_project_tokens`, `0`/leer = unbegrenzt) setzt
ein zusätzliches, unabhängiges Budget, das den bereits über `memory/run_history.py`
aufgezeichneten Tokenverbrauch FRÜHERER Läufe an diesem Projekt mit einbezieht – ist es
bereits VOR Laufbeginn erschöpft, bricht der Lauf ab, ohne auch nur einen Agenten zu starten.
Beide Budgets sind unabhängig konfigurierbar; die Abbruch-Meldung nennt immer korrekt, welches
der beiden gerade bindend war.

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
- **Projekt-Design-System** (`core/design_system.py`): Das Pendant zur Konstitution, nur für
  visuelle statt technische Präferenzen. Seit der Design-vor-Dev-Aufspaltung (`design_lead`
  läuft VOR `dev_lead`) fehlte ausgerechnet dem Design selbst eine Persistenz über mehrere
  Läufe hinweg – `ui_ux`/`image_generator`/`copywriter` hätten Farbpalette, Typografie,
  Spacing-Skala, Komponenten-Namenskonvention und Tonalität bei jedem Lauf am selben Projekt
  neu erfinden können, ohne dass die Nutzeranfrage das je erwähnt. `/design-system [projekt]`
  legt diese Werte einmal fest; sie werden danach wie die Konstitution bei JEDEM künftigen
  Lauf an diesem Projekt in den Kontext aller Teilaufgaben injiziert. Datei `.ai-team-design.toml`
  im Projektverzeichnis, bewusst nicht gitignored – echte Projekt-Konfiguration.
- **Architecture Decision Records** (`core/adr.py`): Die Konstitution hält das WAS fest
  (Tech-Stack), aber nicht das WARUM ("REST statt GraphQL, weil…"). Der `architect`-Agent
  (und grundsätzlich jeder Agent im Werkzeug-Loop) dokumentiert echte Trade-off-Entscheidungen
  über das Werkzeug `record_architecture_decision` als nummerierte, mit dem Code versionierte
  Markdown-Datei unter `docs/adr/NNNN-titel.md` im Projekt (Nygard-Format: Titel, Status,
  Kontext, Entscheidung, Konsequenzen) – bewusst NICHT gitignored, anders als
  `memory/backlog.json`. Bereits getroffene Entscheidungen werden bei JEDEM künftigen Lauf
  automatisch in den Kontext aller Teilaufgaben injiziert, damit spätere Läufe nicht
  unbemerkt gegen frühere, bewusste Entscheidungen arbeiten. Über `/adr [projekt]` einsehbar.
- **Datenbasierte Selbstoptimierungs-Vorschläge** (`core/optimization_advisor.py`): `agent_trainer`
  passt bisher einzelne Agenten-Prompts nach EINEM Lauf per LLM-Interpretation an – es fehlte
  eine rein deterministische Auswertung über VIELE Läufe hinweg (`memory/run_history.py`), ob
  die aktuell konfigurierte Modellzuweisung eines Agenten (z. B. nach einem manuellen
  `.env`-Wechsel) tatsächlich die empirisch beste ist, und ob ein Agent auffällig oft
  gegenüber dem Team-Durchschnitt scheitert. Kein zusätzlicher LLM-Aufruf nötig (Erfolgsquoten/
  Tokenverbrauch sind bereits harte Zahlen) – erscheint automatisch am Ende jedes Laufs, wenn
  ein statistisch aussagekräftiger Befund vorliegt (Mindest-Stichprobengröße + deutlicher
  Unterschied, kein Rauschen bei knappen Abweichungen), sonst kein zusätzlicher Abschnitt.
  Bewusst **nur ein Vorschlag, keine automatische Änderung an `config.py`** – eine
  Modellzuweisung hat neben der reinen Erfolgsquote weitere Faktoren (Kosten, Rate-Limits,
  bewusste Provider-Präferenzen), die das Modul nicht kennt. Jederzeit auch ohne neuen Lauf
  über `/optimize` abrufbar.

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
| 🎨 **Vorab-Design, UI/UX & Media** | `design_lead` | `ui_ux`, `image_generator`, `copywriter` |
| 🟢 **Software-Entwicklung** | `dev_lead` | `backend`, `frontend`, `database`, `api_integration`, `data_engineer`, `mobile`, `ml`, `prompt_engineer`, `performance` |
| 📚 **Content, Doku & Barrierefreiheit** | `content_lead` | `accessibility`, `i18n`, `documentation`, `readme` |
| 🟡 **Qualität, DevOps & Security** | `qa_lead` | `devops`, `tester`, `security`, `resilience_guard`, `github` |
| 🔴 **Excellence & Governance** | `governance_lead` | `code_reviewer`, `refactoring`, `compliance`, `project_cleaner`, `agent_trainer`, `retrospective` |

---

<a id="cli-befehle"></a>
## 🚀 Alle CLI-Befehle im Überblick

```bash
python main.py                              # Interaktive CLI (Standard)
python main.py --dashboard [--port N]       # Web-Dashboard unter http://localhost:8080
python main.py --check-issues               # EIN Poll-Zyklus über offene GitHub-Issues
python main.py --check-pr-reviews           # EIN Poll-Zyklus über offene PR-Review-Kommentare
python main.py --check-dependencies         # Workspace-weiter Schwachstellen-Scan + Auto-Update-PR
python main.py --eval [--tasks t1,t2]       # Reproduzierbare Benchmark-Suite ausführen
python main.py --list-evals                 # Alle Benchmark-Aufgaben auflisten
```

Details zum Web-Dashboard: [🌐 Modernes Web-Dashboard & Visualisierung](#web-dashboard).
Details zu `--check-issues`: [🎫 Autonome, getriggerte Arbeit](#issue-watcher).

**`--check-dependencies` öffnet jetzt automatisch einen Update-PR statt nur zu warnen:**
Findet der Scan eine bekannte Schwachstelle mit einer von `pip-audit` gelieferten
`fix_versions`-Angabe (nur Python/`requirements.txt`; Node/Rust/Go bleiben bei der reinen
Meldung, siehe `core/dependency_updater.py`), hebt `core/dependency_updater.py` das
betroffene Paket automatisch an und öffnet dafür – über denselben PR-Mechanismus wie der
Issue-Watcher, ohne menschliche Bestätigung (unbeaufsichtigter Poll-Zyklus) – einen echten
Pull Request. Das Backlog-Ticket landet dann auf `review` statt `blocked`. Abschaltbar über
`ENABLE_DEPENDENCY_AUTO_UPDATE=false`.

**`/protect-branch [branch]` sichert den Hauptbranch zusätzlich auf GitHub-Seite selbst ab:**
Der PR-Workflow oben verhindert nur, dass dieses Tool direkt auf `main` pusht – ein Mensch
(oder ein anderes Tool) könnte weiterhin `git push origin main` direkt ausführen. Der Befehl
aktiviert per `gh api` echte Branch-Protection (Pflicht-Freigaben vor dem Merge, kein
Force-Push/Löschen, gilt auch für Repo-Admins) – mit Vorschau & Bestätigung, da eine Änderung
an den Repo-Einstellungen selbst Admin-Rechte voraussetzt und ein bewusster, einmaliger
Schritt ist statt eines automatischen Laufs.

**Datei-Kollisionen zwischen parallel arbeitenden Fachteam-Mitgliedern werden jetzt gemeldet:**
Läuft ein Fachbereich mit 3+ Mitgliedern parallel (`asyncio.gather`), sehen sich die Agenten
nie gegenseitig (jeder bekommt nur den Dateibaum zu seinem eigenen Startzeitpunkt) –
schreiben zwei von ihnen dieselbe Datei (z.B. `requirements.txt`), überschrieb das bisher
unbemerkt die zuerst geschriebene Version. `agents/orchestrator.py._detect_file_write_collisions()`
erkennt das jetzt nach jedem parallelen Ausführungs-Batch und macht es per Live-Warnung sowie
einem eigenen `### ⚠️ Datei-Kollisionen`-Abschnitt im Abschlussbericht sichtbar, statt es
stillschweigend zu verwerfen – automatisch entscheidbar, welche Version richtig ist, ist es
nicht, ein Mensch prüft die betroffene(n) Datei(en) gezielt nach.

| Befehl | Beschreibung |
|---|---|
| `/projekte` | Listet alle bestehenden Projekte im Workspace auf |
| `/load <pfad/name>` | Lädt ein bestehendes Projekt (Workspace oder externer Pfad) zur Weiterentwicklung |
| `/tokens` | Zeigt den aktuellen Tokenverbrauch dieser Sitzung UND den kumulierten Verbrauch über alle bisherigen Läufe an |
| `/rag <begriff>` | Führt eine semantische Code-Recherche im geladenen Projekt durch |
| `/team` | Zeigt alle 6 Fachbereiche, Teamleiter und 33 Spezialisten an |
| `/workspace [projekt]` | Listet alle generierten Dateien im Projektordner auf |
| `/export [projekt]` | Packt das Projektverzeichnis in ein ZIP-Archiv |
| `/run-tests [projekt]` | Führt automatische Unit-Tests im Projekt aus |
| `/delete-project <name>` | Löscht ein Projekt unwiderruflich aus dem Workspace (mit Bestätigung) |
| `/audit-projekt [projekt]` | Lässt den Projekt-Hygiene-Agenten das Framework (oder ein Projekt) wirklich durchsehen; Löschungen nur nach Bestätigung |
| `/learnings` | Zeigt alle von den Agenten gelernten Regeln (persistentes Gedächtnis) mit Nummer je Agent an |
| `/delete-learning <agent> <nr>` | Entfernt eine einzelne, falsche/überholte gelernte Regel (mit Bestätigung) |
| `/constitution [projekt]` | Zeigt/bearbeitet feste Tech-Stack-Präferenzen (Sprache, Framework, Code-Stil, …) für ein Projekt – gilt für jeden künftigen Lauf daran |
| `/adr [projekt]` | Zeigt die dokumentierten Architecture Decision Records (Begründungen echter Architektur-Entscheidungen) eines Projekts |
| `/backlog` | Zeigt das Kanban-Board (Todo/In Bearbeitung/Review/Blockiert/Fertig) über CLI, Dashboard UND autonome Issue-Läufe hinweg, inkl. Priorität und WIP-Limit-Warnung |
| `/backlog-add [priorität] <titel>` | Legt manuell ein priorisiertes, noch nicht begonnenes Ticket im Status "todo" an (Priorität: 1/hoch, 2/mittel, 3/niedrig) |
| `/deploy [projekt]` | Deployt ein Projekt lokal per Docker (Compose bevorzugt, sonst Dockerfile) – mit Vorschau & Bestätigung |
| `/deploy-stop [projekt]` | Fährt ein per `/deploy` gestartetes Deployment wieder herunter |
| `/push` | Führt manuell einen Git-Commit & Push aus (mit Secret-Scan, Verifikations-Warnung & PR-Workflow) |
| `/protect-branch [branch]` | Aktiviert echte GitHub-Branch-Protection (Pflicht-Reviews vor Merge, kein Force-Push/Löschen) für den Hauptbranch – mit Vorschau & Bestätigung |
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

**Empfehlung: vor größeren Releases einmal `--eval` mit echten Keys laufen lassen.** Die
gemockte Suite prüft nur die Logik-Zweige, die ein Mock auch tatsächlich durchläuft – ein
realer Fund beim Code-Review zeigte genau die Lücke: ein `NameError` in
`core/browser_verifier.py` (fehlendes `import sys`) und ein stiller, nicht gemeldeter
Runtime-Smoke-Test-Fehlschlag in `agents/orchestrator.py` blieben unbemerkt, weil kein Mock
je den echten, dynamischen Codepfad ausgeführt hat. Ein einmaliger, gezielter Lauf mit
echten Provider-Keys fängt genau solche Lücken auf, die reine Mocks strukturell nicht
sehen können:

```bash
python main.py --eval          # alle Benchmark-Aufgaben, echte LLM-Aufrufe (kostenpflichtig)
python main.py --list-evals    # Übersicht aller Aufgaben, falls nur eine Teilmenge nötig ist
```

Bewusst weiterhin kein automatisierter Cloud-Workflow dafür: das würde wiederkehrende, echte
API-Kosten verursachen und eigene Secrets-Freigaben im Repo voraussetzen – dieser Schritt
bleibt deshalb manuell und gezielt, nicht Teil von CI oder des Scheduler-Workflows.

## 🧹 Lint (ruff)

```bash
pip install -r requirements-dev.txt
ruff check .
```

Konfiguration in `ruff.toml` (bewusst auf den Framework-Code beschränkt, `workspace/`
mit den vom Team selbst generierten Beispielprojekten ist ausgeschlossen). Läuft als
eigener, paralleler `lint`-Job in `.github/workflows/ci.yml` bei jedem Push/PR.

**Lokales Pre-Commit-Lint-Gate (empfohlen, einmalig einrichten):** Ein realer Fund zeigte,
dass ein rot-lintender Stand (u.a. ein echter `NameError`, siehe oben) unbemerkt bis auf
`main` gelangen konnte, weil `ruff` nirgends VOR dem Commit lief – erst der CI-Lint-Job in
der Cloud fing es auf, nachdem der Stand bereits gepusht war. `scripts/git-hooks/pre-commit`
holt genau diese Prüfung lokal nach vorne (bricht `git commit` ab, wenn `ruff check .`
Funde meldet; umgehbar mit `git commit --no-verify`):

```bash
# Windows:
powershell -ExecutionPolicy Bypass -File scripts/install-git-hooks.ps1
# macOS/Linux:
sh scripts/install-git-hooks.sh
```

## 📄 Lizenz

MIT – siehe [LICENSE](LICENSE).
