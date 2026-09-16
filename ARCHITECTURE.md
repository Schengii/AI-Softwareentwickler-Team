# 🏗️ System-Architektur: KI-Softwareentwickler-Team

Das **KI-Softwareentwickler-Team** ist ein autonomes, hierarchisch strukturiertes Multi-Agenten-System für die vollständige, token-optimierte Softwareentwicklung. Es bildet ein professionelles Entwicklerteam aus 33 spezialisierten KI-Experten und 6 Fachbereichs-Teamleitern ab.

---

## 1. Fachbereichs- & Teamleiter-Hierarchie

Das Gesamtsystem gliedert sich in **6 Fachbereiche**, die jeweils von einem eigenen **Department Lead** geführt werden. Der Orchestrator delegiert Phasen an die Teamleiter, welche wiederum konkrete Arbeitsaufträge an ihre Fachteams verteilen:

```
                                  ┌────────────────────────┐
                                  │      Orchestrator      │
                                  └───────────┬────────────┘
                                              │
         ┌───────────────┬────────────────┬───┴──────────┬────────────────┬───────────────┐
         │               │                │              │                │               │
         ▼               ▼                ▼              ▼                ▼               ▼
  🔵 Phase 1      🎨 Phase 2       🟢 Phase 3     📚 Phase 4       🟡 Phase 5      🔴 Phase 6
   Planung         Design & UI/UX   Entwicklung    Content & Doku   Qualität & Ops  Review & Gov.
  (Planning Lead) (Design Lead)    (Dev Lead)     (Content Lead)   (QA Lead)       (Governance Lead)
         │               │                │              │                │               │
  ┌──────┴──────┐ ┌──────┴──────┐  ┌──────┴──────┐┌──────┴──────┐  ┌──────┴──────┐ ┌──────┴──────┐
  │team_lead    │ │ui_ux        │  │frontend     ││accessibility│  │tester       │ │code_reviewer│
  │product_owner│ │image_gen.   │  │backend      ││i18n         │  │security     │ │refactoring  │
  │business_an. │ │copywriter   │  │database     ││documentation│  │devops       │ │compliance   │
  │architect    │ └─────────────┘  │api_integ.   ││readme       │  │resilience_g.│ │proj_cleaner │
  │finops       │                  │data_engineer│└─────────────┘  │github       │ │agent_trainer│
  │web_research │                  │mobile       │                 └─────────────┘ │retrospective│
  └─────────────┘                  │ml           │                                 └─────────────┘
                                   │prompt_eng.  │
                                   │performance  │
                                   └─────────────┘
```

---

### 1.1 Eine neue Fachrolle hinzufügen

Jede der 33 Rollen ist an **vier unabhängig gepflegten Stellen** registriert - keine ist von
den anderen automatisch ableitbar. `tests/test_agent_registry_consistency.py` prüft nach jeder
Änderung, ob alle vier noch zusammenpassen; seine Fehlermeldungen sind absichtlich als
Checkliste formuliert.

**Empfohlen: `scripts/new_agent.py`** automatisiert alle vier Schritte in einem Aufruf:

```
python scripts/new_agent.py <neue_rolle> \
    --name "Anzeigename" \
    --description "Kurzbeschreibung für den Planer-Prompt" \
    --phase 3 --department dev --tier standard
```

Legt `agents/<neue_rolle>_agent.py` als Gerüst an (System-Prompt mit TODO-Markierungen - eine
fachlich gute Rollenbeschreibung lässt sich nicht generisch erzeugen), ergänzt Import +
`self._agents`-Eintrag in `agents/orchestrator/__init__.py`, den `AVAILABLE_AGENTS`-Eintrag in
`core/task_manager.py` sowie `AGENT_MODELS`- und `DEPARTMENT_*_AGENTS`-Eintrag in `config.py`,
und lässt danach `ruff check --fix` laufen. Bricht mit klarer Fehlermeldung ab, falls die
Rolle an einer der vier Stellen bereits existiert. `--department` akzeptiert `planning`,
`design`, `dev`, `content`, `qa`, `governance` (NICHT `creative` - das ist in `config.py` eine
abgeleitete Vereinigung aus `design`+`content`, kein eigenständiges Ziel). Danach den
generierten System-Prompt ausformulieren und `pytest tests/test_agent_registry_consistency.py`
laufen lassen.

**Manuell** (z.B. um die einzelnen Schritte zu verstehen, oder für Detail-Anpassungen nach dem
Scaffold-Aufruf) für eine neue Rolle `<neue_rolle>`:

1. **`agents/<neue_rolle>_agent.py`**: neue Agentenklasse (System-Prompt, ggf. Tool-Zugriff) -
   orientiere dich an einer bestehenden Rolle ähnlicher Komplexität (z.B. `copywriter_agent.py`
   für eine kleine, klar umrissene Aufgabe; `backend_agent.py` für echte Architektur-Trade-offs).
2. **`agents/orchestrator/__init__.py`**: Import ergänzen und `"<neue_rolle>": NeueRolleAgent()`
   in `self._agents` eintragen (in der Phase, zu der sie fachlich gehört).
3. **`core/task_manager.py`**: Eintrag in `AVAILABLE_AGENTS` (Name, Phase, Beschreibung) -
   die Beschreibung UND die dem Planer-Modell gesendete ID-Liste werden automatisch daraus
   abgeleitet (`_DECOMPOSE_EXCLUDED_AGENT_IDS`, falls die Rolle bewusst NICHT direkt vom
   Planer wählbar sein soll, z.B. weil sie nur intern ausgelöst wird).
4. **`config.py`**: Eintrag in `AGENT_MODELS` (Modellstufe LITE/STANDARD/HEAVY nach
   tatsächlichem Aufgabenbedarf, siehe Kommentar dort) UND in GENAU einer
   `DEPARTMENT_*_AGENTS`-Menge.

Schritt 4 fehlt am schnellsten, weil er keinen sofort sichtbaren Fehler erzeugt -
`config.get_model_for_agent()` fällt bei einer fehlenden `AGENT_MODELS`-Zuordnung lautlos auf
`DEFAULT_AGENT_MODEL` zurück, statt die für die Rolle bewusst gewählte Komplexitätsstufe zu
nutzen. `pytest tests/test_agent_registry_consistency.py` nach jeder neuen Rolle laufen lassen.

---

## 2. Der Orchestrierungs- & Ausführungszyklus

Der Lebenszyklus einer Entwicklungsaufgabe durchläuft folgende feste Phasen:

1. **Task-Dekomposition & Skalierung (`core/task_manager.py`)**:
   - Zerlegung der Gesamtaufgabe in konkrete Teilaufgaben.
   - **Komplexitäts-Skalierung**: Reine Micro-Tasks (z. B. einfache Bugfixes, Einzelfunktionen) laufen direkt und schlank ohne Teamleiter-Overhead.
2. **Git-Worktree-Isolation (`core/git_isolation.py`)**:
   - Jeder Lauf operiert in einem isolierten Git-Worktree, um Datei-Kollisionen bei parallelen Läufen zu verhindern.
3. **Phasenweise Ausführung (`agents/orchestrator/`)** – Reihenfolge wie in einem echten Team mit CI:
   - **Planung & Architektur**: Anforderungsanalyse, ADRs, `interface_contract.json`.
   - **Projektgerüst (`core/project_scaffold.py`)**: deterministisch vor der Entwicklung – Paketordner mit `__init__.py` laut Vertrag, `pytest.ini`, `requirements.txt`/`requirements-dev.txt` je Stack, `.env.example`. Überschreibt nie, erzeugt keine Implementierungs-Stubs, läuft nie im Framework-Repo.
   - **Entwicklung + Test-First**: Entwickler und `tester` arbeiten parallel (Tests gegen Akzeptanzkriterien und Vertrag, `ENABLE_TEST_FIRST`). Jeder Entwickler durchläuft vor der Abgabe die **Übergabe-Prüfung** (`core/handoff_check.py`: Syntax, lokale Importe, fehlende `__init__.py`).
   - **Team-Board** (`core/team_board.py`, `agents/orchestrator/team_communication.py`): Übergabe-Notizen, Datei-Owner, Fragen per `ask_teammate`, Stand des Schnittstellen-Vertrags; jeder Agent sieht beim Start die aktuelle Sicht. `__init__.py`-Re-Exporte aus noch fehlenden Modulen lehnt die Toolbox ab.
   - **Live-Überwachung im Werkzeug-Loop**: `core/agent_watchdog.py` (Lesen ohne Schreiben, wiederholtes Neuschreiben, Fehlerwiederholung, Kontext-Explosion, Aufgaben-Tokendeckel), `core/context_compaction.py` (alte große Werkzeug-Ergebnisse verdichten) und ein erzwungener Werkzeug-Aufruf für Code-Rollen ohne gespeicherte Datei (`llm_factory.require_tool_call`).
   - **Integrations-Checkpoint** (`agents/orchestrator/integration.py`): direkt nach der Entwicklung Pre-Flight + deterministische Autofixes + genau eine gezielte Fix-Runde – bevor Content/QA auf kaputtem Code aufbauen. Meldet zusätzlich unerfüllte `requires` vom Team-Board.
   - **Design & Content, Qualität & Security**: optionale Fachbereiche werden übersprungen, wenn ihr Budget-Anteil (`PHASE_TOKEN_SHARES`) die Kernphasen gefährden würde. Teamleiter koordinieren nur Fachbereiche mit mindestens `DEPARTMENT_LEAD_MIN_MEMBERS` Mitgliedern.
   - **Echte Verifikation** (siehe 4.) – läuft auch nach einem Budget-Abbruch der Generierung (0 LLM-Tokens, ohne Fix-Agenten).
   - **Review & Governance NACH der Verifikation** (`ENABLE_REVIEW_AFTER_VERIFICATION`): Reviewer sehen den echten Teststatus; Review-Fixes werden durch einen **Regressionstest** bestätigt.
4. **Dynamische Verifikations-Schleife (`core/verifier/`)**:
   - **Multi-Sprachen-Unterstützung**: Echte isolierte Testumgebungen für Python (`pytest`/`unittest`), Node/TS (`npm test`), Rust (`cargo test`) und Go (`go test`).
   - **Testabdeckungs-Messung**: Automatische Prüfung der Codeabdeckung (`pytest-cov`) gegen konfigurierte Schwellen (`MIN_TEST_COVERAGE`).
   - **Testtiefe (`core/test_depth.py`)**: Anteil der Backend-Routen, die in Tests aufgerufen werden (`MIN_ROUTE_TEST_RATIO`). Eine grüne, aber flache Suite bekommt eine gezielte tester-Runde; bleibt sie flach, blockiert das DoD-Kriterium `test_depth`.
   - **Statisches & AST-Linting**: `ruff` für Python, `eslint`/`tsc` für TypeScript/JavaScript, `cargo clippy` für Rust, `go vet` für Go.
   - **Headless Browser & Frontend-UI-Validierung (`core/browser_verifier.py`)**: Startet Web-Frontends, fängt JavaScript-Konsolenfehler (`console.error`) ab und prüft Asset-404s (Playwright / statisches DOM).
   - **Schwachstellen-Scan**: Echter `pip-audit`, `npm audit`, `cargo audit` und `govulncheck` gegen öffentliche CVE-Datenbanken.
   - **SAST & Lizenz-Audit**: Echter statischer Sicherheits-Scan (`bandit`) und Lizenz-/Copyleft-Scan (`pip-licenses`) für generierten Python-Code – ersetzt die bisherige LLM-Freitext-Einschätzung von `security`/`compliance` durch geparste Funde mit Datei/Zeile bzw. echte Paket-Metadaten.
   - **Lastentest (Smoke-Level)**: Startet die generierte App auf einem freien Port und führt einen kurzen k6-/Locust-Lasttest (`tests/load/`) ECHT dagegen aus – ersetzt den bisherigen Zustand, in dem der `performance`-Agent vollständige Lastentest-Skripte schrieb, die nie ausgeführt wurden.
   - **Accessibility-Scan (axe-core)**: Echter WCAG-2.x-Scan gegen eine per Playwright gerenderte Seite – ersetzt die bisherige LLM-Freitext-Checkliste des `accessibility`-Agenten durch geparste Verstöße mit Regel/Schweregrad/Element.
   - **Runtime Smoke-Check**: Teststart der Applikation im Subprozess (z. B. Uvicorn/FastAPI HTTP-Polling oder CLI-Help-Check), um sicherzustellen, dass die Anwendung tatsächlich hochfährt.
   - **Gezielte Fix-Schleife**: Traceback-Parsing ermittelt die verursachenden Dateien und weist nur dem zuständigen Agenten einen gezielten Korrekturauftrag zu. Browser-Fehler mit Backend-Ursache (CORS, 5xx, WebSocket-Handshake, 404 auf `/api`) gehen an `backend`.
   - **Strukturiertes Ergebnis (`core/verification_outcome.py`)**: jede Prüfung meldet `passed`/`failed`/`skipped`; Definition of Done und Status lesen diese Werte statt Markdown-Text. Die informativen Prüfungen (Audit, SAST, Lizenz, Lint) sind eigenständige Pipeline-Schritte (`agents/orchestrator/verification_checks.py`).
   - **Ehrliche Definition of Done (`core/definition_of_done.py`)**: `is_done` ist nie `True`, wenn die Verifikation rot ist; Build, Installation, App-Start, Secrets (`core/secret_scanner.scan_directory`) und – bei beauftragtem Frontend – der UI-Check sind echte Kriterien.
5. **Ergebnis-Synthese & Akzeptanzkriterien-Check (`core/result_aggregator.py`)**:
   - Zusammenfassung aller Fachberichte und mechanischer Abgleich mit den Given/When/Then-Akzeptanzkriterien.

---

## 3. Resilience, Fault-Tolerance & Token-Schutz

- **Resilience-Guard (`agents/resilience_guard_agent.py`, `core/rate_limiter.py`)**:
  - Implementiert Circuit Breakers, Exponential Backoff mit Jitter und Graceful Degradation bei Provider-Ausfällen.
- **Multi-Tier LLM Fallback (`core/llm_factory.py`)**:
  - Primär- und Fallback-Modelle über Gemini, Anthropic Claude, DeepSeek und Groq.
- **Token Guard, Prompt Caching & Quota-Management (`core/token_guard.py`, `core/quota_estimator.py`, `core/llm_factory.py`)**:
  - Hartes Budget-Limit (`MAX_RUN_TOKENS`) mit kontrolliertem, sicherem Abbruch vor Budget-Überschreitung.
  - Effizienz-Kennzahlen pro Lauf (`agents/orchestrator/efficiency.py`): Cache-Quote, eingesparter Kontext, Watchdog-Eingriffe und Modell-Abwertungen im Abschlussbericht und in `run_closed`.
- **Saubere Lern-Datenbasis & Selbstheilung**: `core/telemetry_hygiene.py` (keine Test-Einträge in Lauf-/Benchmark-Historie), `core/backlog_hygiene.py` (hängende/doppelte Tickets, `Closes: <id>` in Commits, Tickets zu gelöschten Projekten, dauerhaft liegengebliebene Tickets), `core/red_project_repair.py` (rote Projekte als Nachbesserungs-Ticket für den Backlog-Worker).
  - Automatisches **Prompt-Caching** (Anthropic `cache_control: ephemeral`) und **Gemini Context Caching** für signifikante Kosten- und Latenzreduktion bei Multi-Turn-Tool-Loops.

---

## 4. Code-Knowledge-Graph, Observability & Cloud-Deployments

- **AST-Codebase-Graph & Symbol-Index (`core/code_graph.py`)**:
  - Parst Quelltext in einen typisierten AST-Index (`find_symbol_definition`, `find_symbol_references`, `analyze_code_impact`) für fehlerfreie Refactorings in großen Projekten.
- **Run-Historie (`memory/run_history.py`)**:
  - Protokolliert Erfolgsquoten je Agent, Tokenverbrauch, Laufzeit und Verifikationsergebnisse.
- **Projektlokaler Lauf-Trace (`core/run_trace.py`)**:
  - `<projekt>/.ai_team_runs/<zeitstempel>_trace.jsonl` (Phasen, Agenten, Tokens, Werkzeugaufrufe, Dateien) und `<zeitstempel>_verification.md` (vollständiges Verifikationsprotokoll). Versioniert, auf 20 Läufe begrenzt; Grundlage der Root-Cause-Analyse.
- **Zentrales Regelwerk (`core/known_pitfalls.py`)**:
  - Einzige Quelle für Importname→Paket, transitive Pakete, Dev-Pakete, toxische Pakete, versteckte Laufzeit-Abhängigkeiten und den Stolperfallen-Katalog (auch als Prompt-Abschnitt für Agenten).
- **Team-Lektionen mit Lebenszyklus (`core/team_memory.py`)**:
  - Signatur je Lektion, Status `open → implemented → verified → archived`, Wiederholungszähler, automatische Verknüpfung mit dem Regelwerk (`/lessons`), Auswahl nach Relevanz je Agent statt nur nach Aktualität. Ein erneut auftretender Fehler öffnet eine erledigte Lektion wieder.
- **Modell-A/B-Tests (`core/model_ab_trials.py`)**:
  - Modell-Vorschläge laufen zuerst in `MODEL_AB_TRIAL_SHARE` der Läufe; Übernahme, Ablehnung oder Rücknahme nach `MODEL_AB_MIN_TRIAL_CALLS` echten Aufrufen. `.env`-Overrides haben immer Vorrang.
- **Zentraler Backlog-Store (`core/backlog_store.py`)**:
  - Einheitliches Kanban-Board für Aufgaben aus CLI, Web-Dashboard, GitHub-Issues und Dependency-Watchern.
- **GitHub PR-Review Feedback-Loop (`core/pr_review_watcher.py`)**:
  - Liest Inline-Kommentare aus GitHub-Pull-Requests und erstellt gezielte Korrektur-Tickets (`python main.py --check-pr-reviews`).
- **Cloud-Preview-Deployments (`core/cloud_deployment.py`)**:
  - Automatische Generierung von Manifesten (`fly.toml`, `vercel.json`, `render.yaml`) und Bereitstellung weltweiter Preview-URLs.
- **Benchmark- & Evaluations-Harness (`evals/`)**:
  - Kanonische Referenzaufgaben (`evals/tasks.py`) für reproduzierbare Qualitäts- und Regressionstests über `python main.py --eval`.
  - Regressions-Suite aus realen Fehlschlägen (`python main.py --eval --regression`) und **Eval-Gate** (`python main.py --eval-gate`, `evals/gate.py`): Exit-Code 1 bei sinkender Erfolgsquote, gescheiterter Baseline-Aufgabe oder >25 % mehr Tokens. Nächtlich per `.github/workflows/nightly-evals.yml`.
- **Periodischer Dependency-Watch (`core/dependency_watch.py`)**:
  - Automatische Überwachung aller Workspace-Projekte auf neue CVEs über `python main.py --check-dependencies`.

---

## 5. Schnittstellen & Integrationen

| Schnittstelle | Modul / Datei | Zweck |
| :--- | :--- | :--- |
| **Interaktive CLI** | `interface/cli.py` | Rich-formatierte Terminal-Oberfläche mit Live-Status und Plan-Gate. |
| **Web-Dashboard** | `interface/web_dashboard.py` | Dark-Mode Web-UI mit SSE-Live-Streaming, Datei-/Diff-Inspektor, Kanban-Backlog, Observability und Docker-Deploy. |
| **MCP-Server** | `interface/mcp_server.py` | Standardisiertes Model Context Protocol für IDE-Integrationen (VS Code, Cursor, Antigravity). |
| **GitHub-Issue-Watcher** | `core/issue_watcher.py` | Automatische Bearbeitung von GitHub-Issues mit Label-Trigger (`--check-issues`). |
| **PR-Review-Watcher** | `core/pr_review_watcher.py` | Automatische Einarbeitung von menschlichem PR-Feedback (`--check-pr-reviews`). |
| **Ausführungs-Sandbox** | `core/docker_sandbox.py` | Mit `SANDBOX_BACKEND=docker` laufen pip/npm-Installation, Testsuiten, Frontend-Build und `run_command` (pip/python/pytest/npm/npx/node) in einem Container, der nur das Projektverzeichnis sieht – kein Zugriff auf die `.env` des Frameworks. Ohne erreichbaren Daemon: Warnung + lokale Ausführung. Weiterhin lokal: Runtime-Smoke-/Lasttests und Browser-Checks (starten lokal erreichbare Server). |
| **Dependency-Scanner** | `core/dependency_watch.py`, `core/dependency_updater.py` | Regelmäßige Sicherheitsprüfung aller Workspace-Projekte (`--check-dependencies`) – hebt verwundbare Python-Pakete mit bekannter `fix_versions`-Angabe automatisch an und öffnet dafür einen Pull Request. |
| **Benchmark-Suite** | `evals/runner.py` | Ausführung standardisierter Benchmarks (`python main.py --eval`). |
