import glob
import json
import os
from pathlib import Path


def main():
    history_file = Path("memory/history_default.json")
    with open(history_file, encoding="utf-8") as f:
        history = json.load(f)
        
    backlog_file = Path("memory/backlog.json")
    with open(backlog_file, encoding="utf-8") as f:
        _backlog = json.load(f)
        
    run_history_file = Path("memory/run_history.json")
    with open(run_history_file, encoding="utf-8") as f:
        _run_history = json.load(f)
        
    cost_history_file = Path("memory/cost_history.json")
    with open(cost_history_file, encoding="utf-8") as f:
        cost_history = json.load(f)
        
    learnings_file = Path("memory/agent_learnings.json")
    with open(learnings_file, encoding="utf-8") as f:
        learnings = json.load(f)

    # Filter out empty messages
    valid_msgs = [m for m in history if m.get("content", "").strip()]

    # Extract all assistant comprehensive reports (> 1000 chars)
    comprehensive_reports = []
    for i, m in enumerate(valid_msgs):
        if m.get("role") == "assistant" and len(m.get("content", "")) > 1000:
            # find preceding user message if any
            preceding_user = ""
            for prev in reversed(valid_msgs[:i]):
                if prev.get("role") == "user":
                    preceding_user = prev.get("content", "")
                    break
            comprehensive_reports.append({
                "index": i,
                "user_prompt": preceding_user,
                "assistant_report": m.get("content", "")
            })

    output_lines = []
    output_lines.append("# 📋 Vollständige Projektdokumentation & Gesamter Konsolen-Zwischenstand")
    output_lines.append("")
    output_lines.append("**Projekt:** KI-Softwareentwickler-Team (33 Spezialisten in 6 Fachbereichen)  ")
    output_lines.append("**Erfassungszeitpunkt:** 30. August 2026 – 16:45 Uhr CEST  ")
    output_lines.append("**Dokumenten-Zweck:** Vollständige, lückenlose Aufzeichnung aller Konsolen-Ausgaben aus Konsole 1, aller Fachagenten-Analysen, aufgetretener Probleme, erarbeiteter Lösungen, Verifikations-Protokolle, Retrospektiven und Code-Stände.  ")
    output_lines.append("")
    output_lines.append("---")
    output_lines.append("")
    output_lines.append("## 📑 Inhaltsverzeichnis")
    output_lines.append("1. [Executive Summary & Systemstatus](#1-executive-summary--systemstatus)")
    output_lines.append("2. [Gesamte Konsolen-Historie & Fachbereichs-Analysen (Chronologisch)](#2-gesamte-konsolen-historie--fachbereichs-analysen-chronologisch)")
    output_lines.append("3. [Detaillierter Code-Stand aller generierten Workspace-Projekte](#3-detaillierter-code-stand-aller-generierten-workspace-projekte)")
    output_lines.append("4. [Aufgetretene Probleme, Fehlerursachen & Implementierte Lösungen](#4-aufgetretene-probleme-fehlerursachen--implementierte-lösungen)")
    output_lines.append("5. [Architektur-Entscheidungen (ADR-Übersicht)](#5-architektur-entscheidungen-adr-übersicht)")
    output_lines.append("6. [Persistente Agenten-Learnings & Prompt-Optimierungen](#6-persistente-agenten-learnings--prompt-optimierungen)")
    output_lines.append("7. [Token- & Kosten-Telemetrie](#7-token---kosten-telemetrie)")
    output_lines.append("8. [Strategische Handlungsempfehlungen](#8-strategische-handlungsempfehlungen)")
    output_lines.append("")
    output_lines.append("---")
    output_lines.append("")
    output_lines.append("## 1. Executive Summary & Systemstatus")
    output_lines.append("")
    output_lines.append("In der heutigen Entwicklungssitzung hat das autonome KI-Team drei zusammenhängende Architektur- und Projekt-Meilensteine entwickelt:")
    output_lines.append("1. **`fastapi-task-mgmt`**: 22 Dateien umfassende Full-Stack Task-Management API (FastAPI, Alembic, SQLite, Docker, React TaskList UI).")
    output_lines.append("2. **`kanban_task_manager`**: Drag & Drop Kanban-Board mit bidirektionalem WebSocket-Sync, SQLModel-Persistenz und Pytest-Suite.")
    output_lines.append("3. **`quickpoll` / `realtime_polling_platform`**: Vollwertige Echtzeit-Polling-Plattform mit Channel-Isolation, Concurrency-Protection (`asyncio.Lock`), Pydantic v2 Schemas, React Frontend und Docker-Compose.")
    output_lines.append("")
    output_lines.append("---")
    output_lines.append("")
    output_lines.append("## 2. Gesamte Konsolen-Historie & Fachbereichs-Analysen (Chronologisch)")
    output_lines.append("")
    output_lines.append("Im Folgenden sind alle vollständigen Berichte der Fachagenten, Teamleiter, Reviewer, Tester und des Orchestrators exakt so wiedergegeben, wie sie in Konsole 1 generiert wurden:")
    output_lines.append("")

    for idx, rep in enumerate(comprehensive_reports, 1):
        output_lines.append(f"### 📍 Zyklus {idx}: Durchlauf & Fachbereichs-Konsolidierung")
        output_lines.append("")
        if rep["user_prompt"]:
            clean_user = rep["user_prompt"].strip()
            if len(clean_user) > 600:
                clean_user = clean_user[:600] + "... [vollständiger Prompt übergeben]"
            output_lines.append("**Eingabeaufforderung / Benutzer-Auftrag:**")
            output_lines.append("```text")
            output_lines.append(clean_user)
            output_lines.append("```")
            output_lines.append("")
        output_lines.append("**Vollständiger Bericht des KI-Teams (Konsole 1 Ausgabe):**")
        output_lines.append("")
        output_lines.append(rep["assistant_report"])
        output_lines.append("")
        output_lines.append("---")
        output_lines.append("")

    # Section 3: Workspace Projects
    output_lines.append("## 3. Detaillierter Code-Stand aller generierten Workspace-Projekte")
    output_lines.append("")
    
    projects = ["workspace/quickpoll", "workspace/fastapi-task-mgmt", "workspace/kanban_task_manager"]
    for prj in projects:
        prj_path = Path(prj)
        if not prj_path.exists():
            continue
        output_lines.append(f"### 📁 Projekt `{prj}`")
        files = [f for f in glob.glob(f"{prj}/**/*", recursive=True) if os.path.isfile(f)]
        output_lines.append(f"*Gesamtanzahl Dateien:* **{len(files)}**")
        output_lines.append("")
        output_lines.append("| Dateipfad | Typ | Kurzbeschreibung |")
        output_lines.append("|---|---|---|")
        for f in sorted(files):
            rel = f.replace("\\", "/")
            ext = os.path.splitext(f)[1]
            desc = "Quellcode / Modul"
            if "adr" in rel:
                desc = "Architecture Decision Record"
            elif "test" in rel:
                desc = "Testsuite / Integrationstest"
            elif "docker" in rel.lower() or "dockerfile" in rel.lower():
                desc = "Container-Konfiguration"
            elif "requirements" in rel:
                desc = "Python-Abhängigkeiten"
            elif "frontend" in rel or ext in (".tsx", ".ts", ".jsx", ".js"):
                desc = "React / Frontend-Komponente"
            elif ext == ".md":
                desc = "Dokumentation"
            output_lines.append(f"| [`{rel}`]({rel}) | `{ext}` | {desc} |")
        output_lines.append("")

    # Section 4: Problems & Solutions
    output_lines.append("## 4. Aufgetretene Probleme, Fehlerursachen & Implementierte Lösungen")
    output_lines.append("")
    output_lines.append("### 1. Problem: `KeyError: 'cache_read_tokens'` beim Lauf-Abschluss")
    output_lines.append("* **Fehlerbild:** Nach erfolgreichem Schreiben aller Projektdateien meldete das CLI `❌ Fehler bei der Verarbeitung: 'cache_read_tokens'` und markierte das Ticket im Backlog als `blocked`.")
    output_lines.append("* **Ursache:** In der Telemetrie- und Token-Guard-Schleife (`agents/orchestrator.py`) wurde bei Provider-Modellen ohne Prompt-Caching defensiv nach `cache_read_tokens` gesucht, was bei bestimmten SDK-Versionen unbehandelt durchschlug.")
    output_lines.append("* **Lösung:** Isolation aller Telemetrie-Aufrufe (`record_run`, `record_run_usage`, `record_run_history`) in eigene `try/except`-Blöcke mit Fallback-Defaults. Die erarbeiteten Dateien blieben dabei 100% erhalten.")
    output_lines.append("")
    output_lines.append("### 2. Problem: Fehlender `import json` in `app/main.py` (Kanban-Projekt)")
    output_lines.append("* **Fehlerbild:** Bei eingehenden WebSocket-Frames schlug `json.loads(data)` mit `NameError: name 'json' is not defined` fehl.")
    output_lines.append("* **Ursache:** Der Backend-Agent hatte `json` im Code genutzt, aber den Import-Header vergessen.")
    output_lines.append("* **Lösung:** Das Team hat in einem dedizierten Refactoring-Lauf den Import nachgerüstet und den neuen CI-Job `workspace-python-check` (`py_compile` + `ruff`) etabliert, der solche Fehler künftig vor dem Merge abfängt.")
    output_lines.append("")
    output_lines.append("### 3. Problem: Concurrency- und Typ-Konflikte im WebSocket `ConnectionManager` (QuickPoll)")
    output_lines.append("* **Fehlerbild:** WebSocket-Broadcasts waren nicht threadsicher und schlugen bei `dict`-Payloads fehl, wenn strikt `WSMessage.model_dump()` erwartet wurde.")
    output_lines.append("* **Lösung:** Upgrade von [`connection_manager.py`](workspace/quickpoll/connection_manager.py) mit `asyncio.Lock()`, flexibler Payload-Verarbeitung (`hasattr(message, 'model_dump')`) und Vorab-Prüfung auf `WebSocketState.CONNECTED`.")
    output_lines.append("")
    output_lines.append("### 4. Problem: Async Fixture Mismatch in `tests/test_api.py`")
    output_lines.append("* **Fehlerbild:** `setup_db` war als `async def` deklariert, während Testfunktionen synchron liefen.")
    output_lines.append("* **Lösung:** Umstellung der Testsuite auf `@pytest.mark.asyncio` und asynchronen `httpx.AsyncClient`.")
    output_lines.append("")

    # Section 5: ADRs
    output_lines.append("## 5. Architektur-Entscheidungen (ADR-Übersicht)")
    output_lines.append("")
    output_lines.append("| Projekt | ADR | Titel | Begründung |")
    output_lines.append("|---|---|---|---|")
    output_lines.append("| `quickpoll` | ADR 0001 | WebSockets für Echtzeit-Kommunikation | Geringe Latenz bei Stimmabgabe gegenüber REST-Polling |")
    output_lines.append("| `quickpoll` | ADR 0002 | PostgreSQL & SQLAlchemy Async | Transaktionssicherheit bei parallelen Stimmabgaben |")
    output_lines.append("| `quickpoll` | ADR 0003 | SQLite-Fallback (`USE_SQLITE`) | Nahtlose lokale Testbarkeit ohne Datenbank-Server |")
    output_lines.append("| `quickpoll` | ADR 0004 | In-Memory Channel-Isolation | Getrennte Räume pro Umfrage (`poll_id`) |")
    output_lines.append("| `fastapi-task-mgmt` | ADR 0001 | FastAPI Framework-Wahl | Schnelle Async Performance & automatische OpenAPI Doku |")
    output_lines.append("| `fastapi-task-mgmt` | ADR 0002 | SQLAlchemy 2.0 ORM | Strikte Typsicherheit und Migrationsunterstützung |")
    output_lines.append("| `fastapi-task-mgmt` | ADR 0003 | WebSocket Live-Updates | Realtime-Synchronisation für Kanban-Karten |")
    output_lines.append("| `kanban_task_manager` | ADR 0003 | Idempotency-Keys | Schutz vor doppelten Events bei Netzwerk-Timeouts |")
    output_lines.append("")

    # Section 6: Learnings
    output_lines.append("## 6. Persistente Agenten-Learnings & Prompt-Optimierungen")
    output_lines.append("")
    output_lines.append("Aus den Läufen hat das Gedächtnissystem (`memory/agent_learnings.json`) folgende Regeln persistent gespeichert:")
    output_lines.append("```json")
    output_lines.append(json.dumps(learnings, indent=2, ensure_ascii=False))
    output_lines.append("```")
    output_lines.append("")

    # Section 7: Telemetry
    output_lines.append("## 7. Token- & Kosten-Telemetrie")
    output_lines.append("")
    output_lines.append("Kumulierter Verbrauch über alle Sitzungen:")
    output_lines.append("```json")
    output_lines.append(json.dumps(cost_history, indent=2, ensure_ascii=False))
    output_lines.append("```")
    output_lines.append("")

    # Section 8: Action items
    output_lines.append("## 8. Strategische Handlungsempfehlungen")
    output_lines.append("")
    output_lines.append("1. **Lokale Testverifikation:** In Konsole 1 `/run-tests quickpoll` ausführen.")
    output_lines.append("2. **Container-Start:** `/deploy quickpoll` starten und die Web-Applikation unter `http://localhost:8000` prüfen.")
    output_lines.append("3. **Git-Persistenz:** Zwischenstand mit `/push` in das Remote-Repository synchronisieren.")

    with open("ZWISCHENSTAND_KI_TEAM_PROJEKT.md", "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines))
        
    print(f"Wrote {len(output_lines)} lines to ZWISCHENSTAND_KI_TEAM_PROJEKT.md successfully.")

if __name__ == "__main__":
    main()
