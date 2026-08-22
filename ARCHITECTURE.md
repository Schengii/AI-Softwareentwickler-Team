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

## 2. Der Orchestrierungs- & Ausführungszyklus

Der Lebenszyklus einer Entwicklungsaufgabe durchläuft folgende feste Phasen:

1. **Task-Dekomposition & Skalierung (`core/task_manager.py`)**:
   - Zerlegung der Gesamtaufgabe in konkrete Teilaufgaben.
   - **Komplexitäts-Skalierung**: Reine Micro-Tasks (z. B. einfache Bugfixes, Einzelfunktionen) laufen direkt und schlank ohne Teamleiter-Overhead.
2. **Git-Worktree-Isolation (`core/git_isolation.py`)**:
   - Jeder Lauf operiert in einem isolierten Git-Worktree, um Datei-Kollisionen bei parallelen Läufen zu verhindern.
3. **Phasenweise Ausführung (`agents/orchestrator.py`)**:
   - **Phase 1 (Planung & Architektur)**: Anforderungsanalyse, Architecture Decision Records (ADRs), Spezifikation.
   - **Phase 2 (Entwicklung)**: Parallele Erstellung von Backend-, Frontend-, Datenbank- und Schnittstellencode.
   - **Phase 3 (Design & Content)**: UI/UX-Styles, Barrierefreiheit (WCAG 2.2), Mehrsprachigkeit, Dokumentation.
   - **Phase 4 (Qualität & Sicherheit)**: Testsuite, Security-Audits, DevOps/Docker-Konfiguration.
   - **Phase 5 (Review & Governance)**: Code-Review, Refactoring, Compliance-Check.
4. **Dynamische Verifikations-Schleife (`core/verifier.py`)**:
   - **Multi-Sprachen-Unterstützung**: Echte isolierte Testumgebungen für Python (`pytest`/`unittest`), Node/TS (`npm test`), Rust (`cargo test`) und Go (`go test`).
   - **Testabdeckungs-Messung**: Automatische Prüfung der Codeabdeckung (`pytest-cov`) gegen konfigurierte Schwellen (`MIN_TEST_COVERAGE`).
   - **Statisches & AST-Linting**: `ruff` für Python, `eslint`/`tsc` für TypeScript/JavaScript, `cargo clippy` für Rust, `go vet` für Go.
   - **Headless Browser & Frontend-UI-Validierung (`core/browser_verifier.py`)**: Startet Web-Frontends, fängt JavaScript-Konsolenfehler (`console.error`) ab und prüft Asset-404s (Playwright / statisches DOM).
   - **Schwachstellen-Scan**: Echter `pip-audit`, `npm audit`, `cargo audit` und `govulncheck` gegen öffentliche CVE-Datenbanken.
   - **Runtime Smoke-Check**: Teststart der Applikation im Subprozess (z. B. Uvicorn/FastAPI HTTP-Polling oder CLI-Help-Check), um sicherzustellen, dass die Anwendung tatsächlich hochfährt.
   - **Gezielte Fix-Schleife**: Traceback-Parsing ermittelt die verursachenden Dateien und weist nur dem zuständigen Agenten einen gezielten Korrekturauftrag zu.
5. **Ergebnis-Synthese & Akzeptanzkriterien-Check (`core/result_aggregator.py`)**:
   - Zusammenfassung aller Fachberichte und mechanischer Abgleich mit den Given/When/Then-Akzeptanzkriterien.

---

## 3. Resilience, Fault-Tolerance & Token-Schutz

- **Resilience-Guard (`agents/resilience_guard_agent.py`, `core/rate_limiter.py`)**:
  - Implementiert Circuit Breakers, Exponential Backoff mit Jitter und Graceful Degradation bei Provider-Ausfällen.
- **Multi-Tier LLM Fallback (`core/llm_factory.py`)**:
  - Primär- und Fallback-Modelle über Gemini, Anthropic Claude, DeepSeek und Groq.
- **Token Guard & Quota-Management (`core/token_guard.py`, `core/quota_estimator.py`)**:
  - Hartes Budget-Limit (`MAX_RUN_TOKENS`) mit kontrolliertem, sicherem Abbruch vor Budget-Überschreitung.

---

## 4. Code-Knowledge-Graph, Observability & Cloud-Deployments

- **AST-Codebase-Graph & Symbol-Index (`core/code_graph.py`)**:
  - Parst Quelltext in einen typisierten AST-Index (`find_symbol_definition`, `find_symbol_references`, `analyze_code_impact`) für fehlerfreie Refactorings in großen Projekten.
- **Run-Historie (`memory/run_history.py`)**:
  - Protokolliert Erfolgsquoten je Agent, Tokenverbrauch, Laufzeit und Verifikationsergebnisse.
- **Zentraler Backlog-Store (`core/backlog_store.py`)**:
  - Einheitliches Kanban-Board für Aufgaben aus CLI, Web-Dashboard, GitHub-Issues und Dependency-Watchern.
- **GitHub PR-Review Feedback-Loop (`core/pr_review_watcher.py`)**:
  - Liest Inline-Kommentare aus GitHub-Pull-Requests und erstellt gezielte Korrektur-Tickets (`python main.py --check-pr-reviews`).
- **Cloud-Preview-Deployments (`core/cloud_deployment.py`)**:
  - Automatische Generierung von Manifesten (`fly.toml`, `vercel.json`, `render.yaml`) und Bereitstellung weltweiter Preview-URLs.
- **Benchmark- & Evaluations-Harness (`evals/`)**:
  - Kanonische Referenzaufgaben (`evals/tasks.py`) für reproduzierbare Qualitäts- und Regressionstests über `python main.py --eval`.
- **Periodischer Dependency-Watch (`core/dependency_watch.py`)**:
  - Automatische Überwachung aller Workspace-Projekte auf neue CVEs über `python main.py --check-dependencies`.

---

## 5. Schnittstellen & Integrationen

| Schnittstelle | Modul / Datei | Zweck |
| :--- | :--- | :--- |
| **Interaktive CLI** | `interface/cli.py` | Rich-formatierte Terminal-Oberfläche mit Live-Status und Plan-Gate. |
| **Web-Dashboard** | `interface/web_dashboard.py` | Dark-Mode Web-UI mit Live-Log, Kanban-Backlog, Observability und Docker-Deploy. |
| **MCP-Server** | `interface/mcp_server.py` | Standardisiertes Model Context Protocol für IDE-Integrationen (VS Code, Cursor, Antigravity). |
| **GitHub-Issue-Watcher** | `core/issue_watcher.py` | Automatische Bearbeitung von GitHub-Issues mit Label-Trigger (`--check-issues`). |
| **PR-Review-Watcher** | `core/pr_review_watcher.py` | Automatische Einarbeitung von menschlichem PR-Feedback (`--check-pr-reviews`). |
| **Dependency-Scanner** | `core/dependency_watch.py`, `core/dependency_updater.py` | Regelmäßige Sicherheitsprüfung aller Workspace-Projekte (`--check-dependencies`) – hebt verwundbare Python-Pakete mit bekannter `fix_versions`-Angabe automatisch an und öffnet dafür einen Pull Request. |
| **Benchmark-Suite** | `evals/runner.py` | Ausführung standardisierter Benchmarks (`python main.py --eval`). |
