# 🤖 KI-Softwareentwickler-Team (v2.3)

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Gemini](https://img.shields.io/badge/Google_Gemini-4285F4?style=for-the-badge&logo=google&logoColor=white)
![Claude](https://img.shields.io/badge/Anthropic_Claude-D4A017?style=for-the-badge&logoColor=white)
![Agents](https://img.shields.io/badge/Agenten-30-success?style=for-the-badge)
![Anti-Bloat](https://img.shields.io/badge/Anti--Bloat-Aktiv-green?style=for-the-badge)
![Token Guard](https://img.shields.io/badge/Token_Guard-Aktiv-blue?style=for-the-badge)
![License](https://img.shields.io/badge/Lizenz-MIT-blue?style=for-the-badge)

**Ein autonomes, multi-agenten KI-Team für vollständige, token-optimierte Softwareentwicklung.**  
30 spezialisierte KI-Experten – mit Projekt-Hygiene & Anti-Bloat Wächter, Multi-LLM Support (Claude 3.5 Sonnet & Gemini Pro/Flash), Teamleiter, Ausbilder/Prompt-Optimizer, Web-Recherche, Bild- & Text-Generierung, automatischem Git-Push und Workspace-Dateisystem.

</div>

---

## 📖 Inhaltsverzeichnis

- [Überblick & Highlights](#überblick)
- [Modell-Tiering & Token-Guard](#modell-tiering)
- [Agentenstruktur (30 Spezialisten)](#agentenstruktur)
- [Projekt-Hygiene & Anti-Bloat Schutz](#projekt-hygiene--anti-bloat)
- [5-Phasen-Workflow & Hintergrundausführung](#5-phasen-workflow)
- [Workspace & Code-Execution Engine](#workspace-dateisystem)
- [Installation & Setup](#installation)
- [CLI-Befehle & GitHub Push](#cli-befehle)
- [Automatisierte Tests](#tests)

---

## 🌟 Überblick & Highlights

Das **KI-Softwareentwickler-Team** koordiniert 30 spezialisierte Rollen. Alle Unteragenten arbeiten **vollständig im Hintergrund**, sodass der Nutzer nur die validierte Gesamtlösung erhält.

### Kern-Highlights (v2.3)

| Feature | Beschreibung |
|---|---|
| 🧽 **Projekt-Hygiene & Struktur-Wächter** | Bereinigt alten/toten Code, Logs, Cache und verwaiste Dateien; hält Ordner schlank und sauber. |
| 👔 **Teamleiter (Engineering Manager)** | Koordiniert Ziele, Definition of Done und löst Trade-Offs (Performance vs. Kosten). |
| 🎨 **Bild- & Grafik-Designer** | Erstellt speicherbare SVGs, Logos und High-End Prompts für Imagen 3 / Midjourney. |
| ✍️ **Copywriter & Content Specialist** | Schreibt Landingpage-Texte, UI-Microcopy (Buttons, Errors), SEO-Texte und FAQs. |
| 🌐 **Web-Recherche & Info Specialist** | Recherchiert aktuelle Dokumentationen, Bibliotheken und Best Practices im Web. |
| 🎓 **Ausbilder & Agent-Optimizer** | Analysiert Fehler der Agenten, schärft System-Prompts und bildet neue Agenten aus. |
| 🔀 **Interaktiver GitHub-Agent** | Fragt nach Projektabschluss höflich nach Erlaubnis und committet/pusht auf GitHub. |
| 🛡️ **Token-Guard & Multi-Provider** | Nutzt Claude 3.5 Sonnet & Gemini Pro/Flash mit Quota-Failover und Warnsystem. |

---

## 🧽 Projekt-Hygiene & Anti-Bloat

Der neue **Projekt-Hygiene & Struktur-Wächter (`project_cleaner`)** stellt sicher:
1. **Kein Dead Code & keine verwaisten Module:** Unbenutzter Code oder Prototyp-Reste werden identifiziert und gelöscht.
2. **Saubere Verzeichnishierarchie:** Dateien werden logisch nach Clean Architecture strukturiert (`src/core/`, `src/api/`, etc.).
3. **Automatische Cache- & Temp-Bereinigung:** Entfernt temporäre Build-Dateien, `__pycache__` und Test-Logs.
4. **Schlanke `.gitignore`:** Schützt das Git-Repository dauerhaft vor unnötigem Müll.

---

## 🎯 Modell-Tiering & Token-Optimierung

| Tier | Standardmodell | Einsatzzweck & Agenten |
|---|---|---|
| **Heavy Tier** | `gemini-2.5-pro` / `claude-3-5-sonnet` | Teamleiter (`team_lead`), Architekt (`architect`), Code-Reviewer (`code_reviewer`), Ausbilder (`agent_trainer`). |
| **Standard Tier** | `gemini-2.5-flash` / `claude-3-5-haiku` | Frontend, Backend, Database, Data Engineer, API Integration, DevOps, Tester, Security, Product Owner, Bildgenerator, Copywriter, Web-Recherche, Compliance, Retrospektive. |
| **Lite Tier** | `gemini-2.5-flash-lite` | Projekt-Hygiene (`project_cleaner`), UI/UX Konzepte, Dokumentation (`documentation`), Übersetzungen (`i18n`), README, GitHub Messages. |

---

## 🏗️ Agentenstruktur (30 Spezialisten)

```
Du (Nutzer)
    │  Aufgabe / Vision
    ▼
┌─────────────────────────────────────────────────────────────┐
│                🤖 HAUPTAGENT (Orchestrator)                  │
│  Plant → Delegiert im Hintergrund → Prüft → Fasst zusammen  │
└─────────────────────────────────────────────────────────────┘
         │
    ┌────▼────┐
    │ Phase 1 │  👔 Teamleiter  &  🎯 Product Owner  &  📋 Business Analyst  &  🌐 Web-Recherche
    └────┬────┘  (Vision, DoD, Scope, Marktrecherche, User Stories, Akzeptanzkriterien)
         │
    ┌────▼────┐
    │ Phase 2 │  🏛️ Software-Architekt  &  💰 Cost & FinOps
    └────┬────┘  (Systemblueprint, API-Contracts, Cloud-Kosten & TCO)
         │
    ┌────▼─────────────────────────────────────────────────────────┐
    │ Phase 3 │  ALLE PARALLEL IM HINTERGRUND                       │
    │         │  💻 Frontend   ⚙️ Backend   🗄️ Database   🔌 API/Integ.│
    │         │  🌊 Data Eng.  📱 Mobile    🤖 KI/ML     ⚡ Performance│
    │         │  🎨 Bild/SVG   ✍️ Copywriter 📐 UI/UX    🌍 i18n       │
    │         │  🚀 DevOps     🧪 QA/Tester 📚 Docs      🔒 Security   │
    └────┬─────────────────────────────────────────────────────────┘
         │
    ┌────▼────┐
    │ Phase 4 │  🔍 Code-Reviewer  &  🧹 Refactoring  &  ⚖️ Compliance
    │         │  🧽 Projekt-Hygiene & Anti-Bloat  &  🎓 Ausbilder
    └────┬────┘  (Qualitätsprüfung, Tech-Debt, Verzeichnis-Bereinigung, Prompt-Tuning)
         │
         ├───► [Kritische Mängel?] ──► 🛠️ Automatischer Fix-Loop
         │
    ┌────▼────┐
    │ Phase 5 │  💾 Workspace-Dateispeicherung (`workspace/<projekt>/`)
    │Synthese │  📊 Retrospektive, Lessons Learned & Token-Statistik
    └────┬────┘
         │
         ▼
    🔀 GitHub-Agent: Automatische Erlaubnis-Abfrage vor Commit & Push
```

---

## 🚀 Schnellstart & CLI-Befehle

```bash
# Installation
git clone https://github.com/Schengii/AI-Softwareentwickler-Team.git
cd AI-Softwareentwickler-Team
pip install -r requirements.txt

# Starten
python main.py
```

### CLI-Befehle:
- `/team`: Zeigt alle 30 Agenten mit deren zugeordnetem KI-Modell an.
- `/workspace [projekt]`: Listet alle im Workspace generierten Projektdateien auf.
- `/export [projekt]`: Packt das Projektverzeichnis als ZIP-Archiv.
- `/push`: Führt einen manuellen Git-Commit & Push aus.
- `/run-tests [projekt]`: Führt Unittests im Projektverzeichnis aus.
- `/verlauf`: Zeigt die Gesprächshistorie an.
- `/neu`: Setzt die Konversation zurück.
- `/hilfe`: Zeigt die Befehlsübersicht an.

---

## 🧪 Tests ausführen

```bash
python -m unittest discover -s tests -p "test_*.py"
```
