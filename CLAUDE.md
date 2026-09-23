# CLAUDE.md – Projekt-Leitfaden & Kontext für Claude Code

Willkommen im Repository **KI-Softwareentwickler-Team**.
Dieses Dokument definiert Entwicklungsrichtlinien, Kernbefehle und Verhaltensregeln für maximale Token-Effizienz und saubere Code-Qualität.

---

## 🎯 Projekt-Überblick
Ein autonomes Multi-Agenten-System (33 Fachrollen, 6 Fachbereichs-Leiter) für die vollständige Softwareentwicklung mit integrierter Test-, Verifikations- und Refactoring-Schleife.
- **Laufzeitumgebung:** Python 3.14 (Windows)
- **Hauptframeworks:** FastAPI, Rich, Pydantic, Playwright, pytest, ruff

---

## 🧭 Orientierung zu Beginn einer Session (Neuester Stand)

Bevor du mit neuen Aufgaben, Optimierungen oder Analysen startest, orientiere dich immer anhand dieser Quellen:
1. **Aktueller Code-Stand:** `git log -n 5 --oneline` (zeigt die letzten Commits und den aktuellen Branch).
2. **Neueste Optimierungen & Historie:** Die obersten Zeilen von `CHANGELOG.md` lesen (nur die ersten ~60 Zeilen via Head/View, nicht die ganze Datei einlesen!).
3. **Letzte Fehleranalysen & Traces (Direkt ansteuern, nicht suchen):**
   - **Systemweite Deep-Dive-Analysen:** Die neuesten Berichte in `logs/FEHLERANALYSE_*.md` (z. B. `logs/FEHLERANALYSE_SMART_KNOWLEDGE_HUB_20260922_TEMP.md` und `FEHLERANALYSE_PULSE_QUEUE_20260922_TEMP.md`).
   - **Projektlokale Fehler & Postmortems:** `workspace/<projekt>/.ai_team_runs/*_postmortem.md` (Ursachenanalyse des Laufs) und `workspace/<projekt>/.ai_team_dod.json` (welche Kriterien blockieren).
   - **Rohe Fehlerausgaben & Tracebacks:** `logs/verification/*_<projekt>.log` (echte Pytest-, Linter- und Compiler-Meldungen).
   - **Vollständiger Agenten-Trace:** `logs/runs/*_<projekt>.jsonl` (jeder Agentenaufruf, Token-Verbrauch, Watchdogs, Fehler).
4. **Bereits diagnostizierte, aber noch nicht behobene Befunde:** `memory/team_lessons.jsonl` (Einträge mit `"category": "root_cause_analysis"`) enthält Root-Cause-Analysen aus echten Läufen, die noch keinem Fix zugeordnet wurden – oft die ergiebigste Quelle für echte, bereits belegte Framework-Bugs statt Spekulation. Der verbindliche Status-Speicher ist aber das Backlog (`core/backlog_store.py`, `source="root_cause_analysis"`), nicht die JSONL-Datei: `python -c "from core.backlog_store import list_tickets; [print(t.id, t.status) for t in list_tickets() if t.source=='root_cause_analysis']"` zeigt, was davon noch offen ist.
5. **Projektgedächtnis & Obsidian-Notizen:** Bei architektonischen Entscheidungen oder Detailfragen die synchronisierten Notizen in `C:\Users\sche-\Desktop\Obsidian\02 Areas\Lernprojekte\AI-Softwareentwickler-Team\` konsultieren (besonders `00_PROJEKT_GEDAECHTNIS.md` und `01_TEAM_LEARNINGS.md`).

**Wichtig beim Committen eines Fixes für ein Root-Cause-/Audit-Ticket:** Nenne die Ticket-ID in der Commit-Nachricht als eigene Zeile `Closes: <ticket-id>` (auch `Fixes:`/`Resolves:` funktionieren, mehrere IDs kommagetrennt). `core/backlog_hygiene.py.run_backlog_hygiene()` (`python main.py --backlog-hygiene`) markiert danach automatisch das referenzierte Ticket als `done` – ohne diese Zeile bleibt ein längst behobenes Ticket unbegrenzt als offen im Backlog stehen, obwohl der Fix bereits committet ist (realer Fund, 2026-09-17: mehrere `root-cause-*`-Tickets standen trotz längst gemergter Fixes noch auf `todo`/`blocked`, weil frühere Fix-Commits keine `Closes:`-Zeile enthielten).

**🧹 Automatische Git-Worktree-Bereinigung nach Merges:**
Sobald Änderungen von einem Feature- oder Framework-Branch (`ai-team/*`, `feat/*`) nach `main` gemergt und gepusht wurden, MÜSSEN eventuell noch existierende Git-Worktrees (in `../.ai-team-worktrees/`) sofort bereinigt werden, damit die Source-Control-Seitenleiste sauber bleibt:
1. `git worktree list` prüfen.
2. Nicht mehr benötigte Worktrees entfernen: `git worktree remove --force "<pfad>"`.
3. Verwaiste Metadaten aufräumen: `git worktree prune`.

**💰 Strikte Token- & Kostenoptimierung (Gemini API Pay-As-You-Go – UNVERRÜCKBARE VORGABE):**
Das kostenlose Gemini-Kontingent ist erschöpft; alle API-Calls sind kostenpflichtig. Um unnötige Kosten zu verhindern, gelten diese unverrückbaren Regeln, die **unter keinen Umständen eigenmächtig rückgängig gemacht werden dürfen**:
1. **Kein automatischer Einsatz von Gemini Pro (`gemini-pro-latest`):**
   - In realen Läufen verursachte `gemini-pro-latest` trotz nur 28 % der Tokens über 90 % der API-Rechnung (Faktor 15x–25x teurer als Flash bei langen Prompts).
   - Alle Rollen (inkl. Backend, Datenbank, Architect, Security, Orchestrator) laufen standardmäßig auf `gemini-3.8-flash` oder `gemini-3.6-flash`.
   - `GEMINI_HEAVY_MODEL`, `HEAVY_MODEL` oder Agentenmodelle in `config.py` und `.env` dürfen **NIEMALS** eigenmächtig wieder auf `gemini-pro-latest` umgestellt werden!
2. **Gestraffte Werkzeug-Iterationen (`AGENT_MAX_TOOL_ITERATIONS`):**
   - Jede zusätzliche Iteration sendet die gesamte kumulierte Historie erneut mit (Multi-Turn Multiplikator für Input-Tokens).
   - Für Code- und Test-Rollen gilt ein striktes Limit von maximal **8 Iterationen** (`backend: 8`, `frontend: 8`, `tester: 8`, `database: 6`).
   - Diese Limits nicht eigenmächtig wieder auf 12–14 anheben.
3. **Kontext-Verdichtung aktiv halten:**
   - `CONTEXT_COMPACTION_KEEP_ROUNDS=1` und `CONTEXT_COMPACTION_MIN_CHARS=500` bleiben aktiv, damit gelesene Dateien und Bash-Outputs früher zu Snippets verdichtet werden.

---

## ⚡ Wichtige Entwicklungs- & Testbefehle

| Aufgabe | Befehl |
| :--- | :--- |
| **Alle Tests ausführen** | `pytest` |
| **Einzelne Testdatei** | `pytest tests/test_obsidian_sync.py -v` |
| **Linter prüfen & autofixen** | `ruff check` bzw. `ruff check --fix` |
| **Interaktive CLI starten** | `python main.py` |
| **Web-Dashboard starten** | `python main.py --dashboard` |
| **Gedächtnis-Sync nach Obsidian** | `python main.py --sync-obsidian` |
| **Obsidian-Echtzeit-Watcher** | `python scripts/watch_obsidian_sync.py` |
| **Test-Rauschen aus Lern-Historie entfernen** | `python main.py --clean-telemetry [--dry-run]` |
| **Workspace-Hygiene (Alte Build-Artefakte prunen)** | `python main.py --workspace-hygiene [--days 7] [--dry-run]` |
| **Backlog-Hygiene** | `python main.py --backlog-hygiene` |
| **Rote Projekte zur Nachbesserung einplanen** | `python main.py --queue-red-projects` |
| **Nur-Kommentar-Änderung beweisen** | `python scripts/check_comment_only_change.py <dateien>` |

---

## 🏗️ Verzeichnis-Struktur

```
AI-Softwareentwickler-Team/
├── agents/        # 33 Agentenrollen & 6 Fachbereichsleiter (orchestrator/, department_lead_agent.py)
├── core/          # Kernsystem (task_manager, verifier, obsidian_sync, code_sandbox, rate_limiter)
├── interface/     # Schnittstellen (cli.py, web_dashboard.py)
├── memory/        # Persistentes Backlog (backlog.json), Token-Kosten & Run-Historie
├── scripts/       # Hilfsskripte (sync_to_obsidian.py, watch_obsidian_sync.py)
├── skills/        # AI-Dev-Team Skill & Rollen-Katalog (ai-dev-team/SKILL.md)
├── tests/         # pytest-Suite für Framework & Verifier
├── workspace/     # Generierte Zielprojekte (vom Framework-Code getrennt halten!)
├── config.py      # Zentrale Konfiguration & Umgebungsvariablen
└── main.py        # CLI-Einstiegspunkt
```

---

## 🪙 Token-Optimierung & Best Practices für Claude Code

1. **Kein Einlesen von Riesendateien:**
   - `CHANGELOG.md` (255 KB / 3.500 Zeilen) und `README.md` (78 KB) nie komplett einlesen – gezielt mit `grep`/`Grep` auf Überschriften oder Stichworte suchen. Für historischen Kontext zusätzlich `git log` oder das Obsidian-Gedächtnis nutzen.
2. **`workspace/` schonen:**
   - Suche bei allgemeinen Code-Fragen nicht in `workspace/`, da dort über 20 generierte Projekte liegen.
3. **Präzise Edits:**
   - Bearbeite gezielt nur die betroffenen Zeilenblöcke (keine unnötigen Komplettüberschreibungen großer Dateien).
4. **Verifikation nach Änderungen:**
   - Führe nach Codeänderungen immer `ruff check` und den relevanten `pytest`-Test aus.

---

## 🧠 Externes Gedächtnis (Obsidian Vault)

Alle wichtigen Projektkonfigurationen, Architekturpläne und Verlaufsdaten werden automatisch mit deinem Obsidian-Vault synchronisiert:
- **Basis-Verzeichnis:** `C:\Users\sche-\Desktop\Obsidian\02 Areas\Lernprojekte\AI-Softwareentwickler-Team\`

### 📂 Struktur im Vault & Wann Claude was liest:

| Obsidian-Pfad | Inhalt / Zweck | Wann aufrufen? |
| :--- | :--- | :--- |
| `00_PROJEKT_GEDAECHTNIS.md` | **Zentraler Index & Hub** mit Wiki-Links zu allen synchronisierten Notizen | Zu Beginn für Gesamtübersicht & Einstiegspunkt |
| `01_TEAM_LEARNINGS.md` | **Aggregierter Erfahrungsspeicher** (Root-Cause-Analysen, typische Dependency-Fallen, Governance-Befunde) | Vor komplexen Bugfixes, Architekturänderungen oder Verifikationsschleifen |
| `skills/ai-dev-team/SKILL.md` | **Rollen- & Agenten-Katalog** mit Toolsets, Modellen, Fachbereichen | Wenn Rollenbeschreibungen, Prompts oder Workflow-Regeln modifiziert werden |
| `ARCHITECTURE.md` | **Systemarchitektur** des Frameworks (6 Fachbereiche, 33 Rollen, Tiers) | Bei Architekturentscheidungen und Pipeline-Erweiterungen |
| `CHANGELOG.md` | **Historie aller Bugfixes & Features** | Zum Nachschlagen, wann ein Feature implementiert oder geändert wurde |
| `.env.example.md` | **Konfigurations-Dokumentation** (Alle Umgebungsvariablen erklärt, KEINE echten Secrets) | Bei Fragen zu Config-Optionen, LLM-Keys oder Modell-Routing |
| `03 Resources/Permanent Notes/ADR - *.md` | **Architektur-Entscheidungen (ADRs)** der autonomen Zielprojekte | Bei Detailfragen zu früheren Design-Entscheidungen einzelner generierter Apps |

*Tipp für Claude:* Falls du in einer Session gezielt nach früheren Fehlern oder Dependency-Fallen suchst, lese direkt `01_TEAM_LEARNINGS.md` im Vault oder `memory/team_lessons.jsonl`.

---

## 📐 Code- & Stil-Konventionen

- **Python:** Saubere Typ-Annotationen (`from __future__ import annotations` oder Python 3.10+ Typen).
- **Windows UTF-8:** Bei Dateioperationen immer explizit `encoding="utf-8"` angeben.
- **Sprache:** Deutsche Docstrings und Statusmeldungen für Nutzer, englische Code-Bezeichner (Variablen/Klassennamen).
- **Resilienz:** Bei Dateisystem- und Netzwerkoperationen immer sauberes Fehler-Handling mit aussagekräftigen Log-/Fehlermeldungen.
