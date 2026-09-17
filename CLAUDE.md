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
3. **Letzte Fehleranalysen & Traces:** Prüfe die neuesten Berichte in `logs/FEHLERANALYSE_*.md` sowie die letzten Ausführungs-Traces in `logs/runs/` bzw. `logs/verification/`.
4. **Bereits diagnostizierte, aber noch nicht behobene Befunde:** `memory/team_lessons.jsonl` (Einträge mit `"category": "root_cause_analysis"`) enthält Root-Cause-Analysen aus echten Läufen, die noch keinem Fix zugeordnet wurden – oft die ergiebigste Quelle für echte, bereits belegte Framework-Bugs statt Spekulation.
5. **Projektgedächtnis:** Bei architektonischen Grundsatzentscheidungen `00_PROJEKT_GEDAECHTNIS.md` im Obsidian-Vault konsultieren.

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
- **Vault-Pfad:** `C:\Users\sche-\Desktop\Obsidian\02 Areas\Lernprojekte\AI-Softwareentwickler-Team\`
- **Index-Notiz:** `00_PROJEKT_GEDAECHTNIS.md`
- **Konfig-Dateien:** `.env.example.md` (Vorlage, KEINE echten Secrets), `README.md`, `ARCHITECTURE.md`, `CHANGELOG.md`
- Wenn du nach bisherigen Entscheidungen oder Setup-Details suchst, ist `00_PROJEKT_GEDAECHTNIS.md` im Vault die schnellste Quelle.

---

## 📐 Code- & Stil-Konventionen

- **Python:** Saubere Typ-Annotationen (`from __future__ import annotations` oder Python 3.10+ Typen).
- **Windows UTF-8:** Bei Dateioperationen immer explizit `encoding="utf-8"` angeben.
- **Sprache:** Deutsche Docstrings und Statusmeldungen für Nutzer, englische Code-Bezeichner (Variablen/Klassennamen).
- **Resilienz:** Bei Dateisystem- und Netzwerkoperationen immer sauberes Fehler-Handling mit aussagekräftigen Log-/Fehlermeldungen.
