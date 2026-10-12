# Umsetzungsplan: KI-Softwareentwickler-Team

## 1. Ist-Zustand (max. 10 Zeilen)
- Autonomes Multi-Agenten-System (33 Fachrollen, 6 Fachbereichsleiter) unter Python 3.14 mit FastAPI, Playwright, pytest und ruff.
- `ruff check` läuft fehlerfrei durch (0 Fehler); `python -m py_compile` kompiliert alle Kerndateien ohne Syntaxfehler.
- Pytest-Suite umfasst über 279 Testdateien; fokussierte Tests (Secrets, CI-Feedback, Git-Runtime) passieren zu 100 %.
- Secrets-Gate und Pre-Commit-Hooks (`scripts/git-hooks/check_secrets.py`) sind aktiv und prüfen staged Diff & `.env`-Dateien zuverlässig.
- Verifier besitzt reale Tools (Playwright für DOM/Canvas, axe-core für a11y, Bandit für SAST, pip-audit für CVEs, Locust für Last).
- Hauptschwachstelle aus realen Läufen: Provider-Rate-Limits (Gemini 429, Groq 429) & Token-Exhaustion bei repetitivem Debugging.
- Hard Delivery Gate scheitert bei reinen Textantworten von Code-Agenten (z. B. ML/Security), wenn Tool-Aufrufe (`write_file`) unterbleiben.
- Workspace-Generierung leidet unter Schnittstellendiskrepanzen zwischen Backend-Implementierung und generierten Tests (z. B. Smart Knowledge Hub).
- Backlog-Store akkumuliert blockierte Tickets aus fehlgeschlagenen Läufen ohne automatisierte Re-Triagierung.
- CI (.github/workflows/ci.yml) deckt Lint, Tests und Workspace-Syntax ab, benötigt aber strikte Überwachung bei Dependency-Pins.

---

## 2. Maßnahmen in sinnvoller Reihenfolge

### Phase 1: CI, Sicherheit & Developer Experience (Basis-Infrastruktur)
- [x] M01 | Pytest-Versions-Pinning in requirements.txt synchronisieren | P1 | S | requirements.txt | requirements.txt:41 | Fertig wenn: `pytest>=8.0.0,<10.0.0` gesetzt ist und `pytest --version` (9.1.1) ohne Versionskonflikt-Warnung akzeptiert wird
- [x] M02 | Python 3.14 Kompatibilitäts-Deprecation-Warning isolieren | P2 | S | pytest.ini | pytest.ini:10 | Fertig wenn: filterwarnings in `pytest.ini` die `_UnionGenericAlias` DeprecationWarning aus `google.genai.types` gezielt unterdrückt
- [x] M03 | Pre-Commit Hook Installationsskript Windows-Pfadkompatibilität verifizieren | P2 | S | scripts/install-git-hooks.ps1 | scripts/install-git-hooks.ps1:15 | Fertig wenn: `install-git-hooks.ps1` idempotente Ausführung ohne ExecutionPolicy-Fehler abschließt
- [x] M04 | CI Workflow Matrix-Erweiterung für neuere Python-Versionen prüfen | P2 | M | .github/workflows/ci.yml | .github/workflows/ci.yml:49 | Fertig wenn: CI-Matrix mindestens Python 3.12 und 3.13 abbildet und der Test-Job grün durchläuft
- [x] M05 | Dependabot Konfiguration für automatische Update-Überwachung abgleichen | P3 | S | .github/dependabot.yml | .github/dependabot.yml:1 | Fertig wenn: Alle Manifest-Pfade (requirements.txt, dev, workspace) valide definiert sind

### Phase 2: Kern-Stabilität & Fehlerbehandlung (Provider & Delivery Gates)
- [x] M06 | Hard Delivery Gate Prompt-Eskalation bei reinem Textoutput schärfen | P1 | M | agents/base_agent.py | agents/base_agent.py:204 | Fertig wenn: Ein Agent nach 1. Stufe ohne Tool-Call zwingend einen strukturierten Tool-Call-Zwang erhält und Tests in `test_quality_gates.py` grün sind
- [x] M07 | Provider-Failover-Strategie bei 429 Quota Exceeded robuster abfangen | P1 | M | core/provider_exhaustion.py, core/llm_factory.py | core/provider_exhaustion.py:69 | Fertig wenn: Bei Gemini-Key-Erschöpfung ohne Endlosschleife sofort auf konfiguriertes Ausweichmodell umgeschaltet wird
- [x] M08 | Groq Rate-Limit & TPM/TPD Backoff-Schutz optimieren | P2 | M | core/llm_factory.py, tests/test_groq_tpm_fallback.py | tests/test_groq_tpm_fallback.py:1 | Fertig wenn: Groq TPM-Limit-Überschreitung eine progressive Wartezeit auslöst oder sofort Flash als Fallback wählt
- [x] M09 | Token-Compaction bei langen Verifikationsschleifen sicherstellen | P2 | M | core/context_compaction.py | core/context_compaction.py:1 | Fertig wenn: Überlange bash/tool-Outputs zuverlässig unter 500 Zeichen verdichtet werden und `test_context_compaction.py` besteht
- [x] M10 | Root-Cause-Analyst Ticket-Generierung deduplizieren | P2 | S | core/root_cause_analyst.py | core/root_cause_analyst.py:53 | Fertig wenn: Für denselben Projektfehler innerhalb von 24h maximal 1 RCA-Ticket im Backlog angelegt wird

### Phase 3: Architektur & Verifier (Qualitäts-Gates)
- [x] M11 | Statische Import- und Attribut-Prüfung im Preflight-Check erweitern | P1 | L | core/pre_flight_check.py | core/pre_flight_check.py:756 | Fertig wenn: Diskrepanzen zwischen lokalen Klassen-Exporten und Test-Importen vor dem Testlauf als Fehler gemeldet werden
- [x] M12 | Interface-Mismatch-Erkennung zwischen Service und Test-Fixtures implementieren | P1 | M | core/contract_verifier.py | core/contract_verifier.py:1 | Fertig wenn: Nicht existierende Methodenaufrufe in Pytest-Fixtures (wie initialize_vault) vor Testausführung moniert werden
- [x] M13 | Verifier Runtime-Sandbox-Timeout-Behandlung vereinheitlichen | P2 | M | core/verifier/environment.py | core/verifier/environment.py:55 | Fertig wenn: Venv-Installation bei Timeout sauber abbricht und informativen Report statt unvollständigem Environment liefert
- [x] M14 | Canvas- & Blank-Screen-Erkennung im Browser-Verifier härten | P2 | S | core/browser_verifier.py | core/browser_verifier.py:39 | Fertig wenn: Web-Frontends ohne Zeichenaufrufe im `<canvas>` zuverlässig als blank_canvases erkannt werden
- [x] M15 | Accessibility-Prüfung axe-core Fallback absichern | P3 | S | core/browser_verifier.py | core/browser_verifier.py:50 | Fertig wenn: Fehlen von axe-core-python oder Playwright sauber protokolliert wird, ohne den Verifier crashen zu lassen

### Phase 4: Backlog, Telemetrie & Performance
- [x] M16 | Backlog-Archivierung für blockierte Alttickets aktivieren | P2 | S | core/backlog_store.py | core/backlog_store.py:38 | Fertig wenn: `archive_completed_tickets()` verwaiste blocked/cancelled Tickets älter als 14 Tage ins Archiv verschiebt
- [ ] M17 | Backlog-Worker Governance-Retry-Pool Obergrenze durchsetzen | P2 | M | core/backlog_worker.py | core/backlog_worker.py:39 | Fertig wenn: Tickets mit `MAX_GOVERNANCE_TICKET_RETRIES` final als unrecoverable geschlossen werden
- [ ] M18 | Git-Worktree-Bereinigung nach abgebrochenen Läufen automatisieren | P2 | S | core/git_isolation.py | core/git_isolation.py:36 | Fertig wenn: Verwaiste `ai-team/*` Worktrees nach Laufabbruch via `prune_stale_worktrees()` aufgeräumt werden
- [ ] M19 | Obsidian-Sync Watcher Performance & Exception-Handling prüfen | P3 | S | scripts/watch_obsidian_sync.py | scripts/watch_obsidian_sync.py:59 | Fertig wenn: Watcher bei Dateizugriffsfehlern (Windows File Locks) nicht abstürzt und mit Backoff weitermacht
- [ ] M20 | Telemetrie-Bereinigung CLI-Option Validierung | P3 | S | core/telemetry_hygiene.py | core/telemetry_hygiene.py:1 | Fertig wenn: `python main.py --clean-telemetry --dry-run` verwaiste Rauschdaten korrekt auflistet

### Phase 5: Dokumentation & Richtlinien-Synchronisation
- [ ] M21 | CLAUDE.md und README.md bezüglich Pytest-Version und Modell-Restriktionen abgleichen | P2 | S | CLAUDE.md, README.md | CLAUDE.md:36 | Fertig wenn: Keine Widersprüche bzgl. Flash-Nutzung und Test-Befehlen in Dokumenten existieren
- [ ] M22 | Architecture ADR-Verzeichnisstruktur dokumentieren und verlinken | P3 | S | ARCHITECTURE.md, core/adr.py | ARCHITECTURE.md:1 | Fertig wenn: Architektur-Entscheidungen aus dem Memory-Ordner mit Obsidian-Index verlinkt sind

### Optional (Ideen ohne akuten Fehlerbeleg)
- [ ] M23 | Unterstützung für Python 3.15 Vorab-Testing evaluieren | P3 | M | config.py | Optional | Fertig wenn: Machbarkeit neuer Syntax-Features dokumentiert ist
- [ ] M24 | Dashboard SSE-Verbindungs-Reconnect per Exponential Backoff im Frontend verbessern | P3 | S | interface/web_dashboard.py | Optional | Fertig wenn: UI bei Server-Neustart ohne Reload nahtlos wieder verbindet

---

## 3. Vorgehen je Phase

### Phase 1: CI, Sicherheit & Developer Experience
- **Reihenfolge:** M01 -> M02 -> M03 -> M04 -> M05
- **Test nach Phase:**
  - `python -m py_compile config.py main.py`
  - `ruff check .`
  - `pytest tests/test_ci_feedback_loop.py tests/test_pre_commit_secret_hook.py tests/test_git_runtime.py -v`
  - `python scripts/git-hooks/check_secrets.py`
- **Rollback:** `git checkout -- requirements.txt pytest.ini scripts/ .github/`

### Phase 2: Kern-Stabilität & Fehlerbehandlung
- **Reihenfolge:** M06 -> M07 -> M08 -> M09 -> M10
- **Test nach Phase:**
  - `pytest tests/test_quality_gates.py tests/test_provider_exhaustion.py tests/test_groq_tpm_fallback.py tests/test_context_compaction.py -v`
  - `ruff check agents/ core/`
- **Rollback:** `git checkout -- agents/base_agent.py core/provider_exhaustion.py core/llm_factory.py core/context_compaction.py core/root_cause_analyst.py`

### Phase 3: Architektur & Verifier
- **Reihenfolge:** M11 -> M12 -> M13 -> M14 -> M15
- **Test nach Phase:**
  - `pytest tests/test_pre_flight_check.py tests/test_contract_verifier.py tests/test_browser_verifier.py -v`
  - `ruff check core/verifier/ core/pre_flight_check.py`
- **Rollback:** `git checkout -- core/pre_flight_check.py core/contract_verifier.py core/verifier/`

### Phase 4: Backlog, Telemetrie & Performance
- **Reihenfolge:** M16 -> M17 -> M18 -> M19 -> M20
- **Test nach Phase:**
  - `pytest tests/test_backlog_store.py tests/test_backlog_worker.py tests/test_git_isolation.py tests/test_telemetry_hygiene.py -v`
  - `python -c "from core.backlog_store import list_tickets; print(len(list_tickets()))"`
- **Rollback:** `git checkout -- core/backlog_store.py core/backlog_worker.py core/git_isolation.py scripts/watch_obsidian_sync.py core/telemetry_hygiene.py`

### Phase 5: Dokumentation & Richtlinien-Synchronisation
- **Reihenfolge:** M21 -> M22
- **Test nach Phase:**
  - Markdown-Syntaxprüfung (`git diff`)
  - Konsistenzprüfung der Versions- und Modellangaben
- **Rollback:** `git checkout -- CLAUDE.md README.md ARCHITECTURE.md`

---

## 4. Risiken und offene Fragen

### Risiken
1. **Gemini API Pay-As-You-Go Kontingente:** Bei unvorsichtiger Modellwahl (`gemini-pro-latest`) explodieren die Kosten. Strikte Einhaltung der Flash-Vorgabe (`gemini-3.8-flash`) ist lebensnotwendig (Beleg: CLAUDE.md:36-48).
2. **Windows File Locking:** Hintergrundprozesse (z. B. Playwright, Python venvs) können temporäre Dateien sperren, was zu Abbrüchen bei Aufräumarbeiten führt.
3. **AST-Analyse vs. Dynamische Imports:** Erweiterte statische Namensauflösung im Preflight-Check (M11) darf keine False Positives bei dynamisch geladenen Modulen (z. B. Plugin-Systeme) erzeugen.
4. **Git-Worktree Deadlocks:** Abgebrochene Prozesse könnten gesperrte Branches in `.ai-team-worktrees` hinterlassen.

### Offene Fragen
1. Sollen Alttickets im Status `blocked` aus historischen Fehlschlägen (wie `smart_knowledge_hub`, `aegisflow`) automatisiert geschlossen oder im Rahmen von M16 ins Archiv verschoben werden?
2. Wird GitHub Actions CI zukünftig auf Python 3.13 oder 3.14 erweitert, sobald Third-Party-Wheels (insb. ältere Pydantic/Playwright-Releases) vollständig stabil verfügbar sind?
