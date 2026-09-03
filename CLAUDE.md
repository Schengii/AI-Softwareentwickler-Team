# CLAUDE.md – Projekt-Leitfaden & Kontext für Claude Code

Willkommen im Repository **KI-Softwareentwickler-Team**.
Dieses Dokument definiert Entwicklungsrichtlinien, Kernbefehle und Verhaltensregeln für maximale Token-Effizienz und saubere Code-Qualität.

---

## 🎯 Projekt-Überblick
Ein autonomes Multi-Agenten-System (33 Fachrollen, 6 Fachbereichs-Leiter) für die vollständige Softwareentwicklung mit integrierter Test-, Verifikations- und Refactoring-Schleife.
- **Laufzeitumgebung:** Python 3.14 (Windows)
- **Hauptframeworks:** FastAPI, Rich, Pydantic, Playwright, pytest, ruff

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
   - Lies **niemals** `ZWISCHENSTAND_KI_TEAM_PROJEKT.md` komplett ein (1.8 MB / 46.000 Zeilen). Nutze stattdessen `CHANGELOG.md`, `git log` oder das Obsidian-Gedächtnis.
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
- **Konfig-Dateien:** `.env.md`, `README.md`, `ARCHITECTURE.md`, `CHANGELOG.md`
- Wenn du nach bisherigen Entscheidungen oder Setup-Details suchst, ist `00_PROJEKT_GEDAECHTNIS.md` im Vault die schnellste Quelle.

---

## 📐 Code- & Stil-Konventionen

- **Python:** Saubere Typ-Annotationen (`from __future__ import annotations` oder Python 3.10+ Typen).
- **Windows UTF-8:** Bei Dateioperationen immer explizit `encoding="utf-8"` angeben.
- **Sprache:** Deutsche Docstrings und Statusmeldungen für Nutzer, englische Code-Bezeichner (Variablen/Klassennamen).
- **Resilienz:** Bei Dateisystem- und Netzwerkoperationen immer sauberes Fehler-Handling mit aussagekräftigen Log-/Fehlermeldungen.
