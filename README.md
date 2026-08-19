# 🤖 KI-Softwareentwickler-Team (v3.1)

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Multi-Project](https://img.shields.io/badge/Multi--Projekt--Support-Aktiv-success?style=for-the-badge)
![Auto-Self-Optimization](https://img.shields.io/badge/Auto--Selbstoptimierung-Aktiv-success?style=for-the-badge)
![Token-Efficiency](https://img.shields.io/badge/Token--Sparmodus-Ultra_Effizient-blue?style=for-the-badge)
![HuggingFace](https://img.shields.io/badge/HuggingFace-Assets_&_Design-FFD21E?style=for-the-badge&logo=huggingface&logoColor=black)
![OpenRouter](https://img.shields.io/badge/OpenRouter-Universal_Gateway-6941C6?style=for-the-badge)
![Tavily](https://img.shields.io/badge/Tavily-Live_Search-blueviolet?style=for-the-badge)
![DeepSeek](https://img.shields.io/badge/DeepSeek_V3-0066FF?style=for-the-badge&logo=deepseek&logoColor=white)
![Groq](https://img.shields.io/badge/Groq_Turbo-F55036?style=for-the-badge&logo=groq&logoColor=white)

**Ein autonomes, multi-agenten KI-Team für vollständige, token-optimierte Softwareentwicklung.**  
30 spezialisierte KI-Experten – mit **Multi-Projekt & externer Codebase-Unterstützung**, **automatischer KI-Selbstoptimierung**, **Ultra-Token-Sparmodus**, **bidirektionalem Token-Lifecycle (Auto-Fallback & Recovery)**, **Hugging Face Asset-Design**, **Tavily Live-Web-Recherche**, **DeepSeek Reasoning**, **Groq Turbo Inferenz**, Projekt-Hygiene & Anti-Bloat und Workspace-Dateisystem.

</div>

---

## 📖 Inhaltsverzeichnis

- [Überblick & Highlights](#überblick)
- [Multi-Projekt & Externe Projekte weiterentwickeln](#multi-projekt-support)
- [Ultra-Token-Sparmodus & Auto-Recovery](#ultra-token-sparmodus)
- [Automatische KI-Selbstoptimierung](#automatische-selbstoptimierung)
- [Multi-LLM & Tool Matrix](#multi-llm--tool-matrix)
- [Agentenstruktur (30 Spezialisten)](#agentenstruktur)
- [CLI-Befehle & Projektverwaltung](#cli-befehle)
- [Automatisierte Tests](#tests)

---

## 📂 Multi-Projekt-Support: Externe & Zukünftige Projekte weiterentwickeln

Du kannst dein KI-Entwicklerteam ab sofort für **jedes beliebige bestehende oder externe Projekt** auf deinem PC einsetzen:

### 1. Bestehende Projekte anzeigen:
```bash
/projekte
```
Zeigt dir alle bisherigen Projekte im `workspace/` mit Dateianzahl und Pfaden an.

### 2. Projekt laden & weiterentwickeln:
```bash
/load jobsuche-app
# oder beliebiger externer Pfad:
/load C:\Users\sche-\Desktop\MeinAnderesProjekt
```
- **Automatischer Code-Scan:** Das Team liest alle relevanten Quellcodedateien (`.py`, `.js`, `.ts`, `.html`, `.sql`, etc.) ein und versteht den Aufbau.
- **Aufgaben stellen:** Du kannst sofort Instruktionen geben, z. B.:
  - *"Refaktoriere die Datenbank und füge Pytest-Unittests hinzu."*
  - *"Erstelle ein modernes Tailwind/CSS Frontend für diese API."*
  - *"Führe ein Security- und DSGVO-Audit durch und behebe alle Schwachstellen."*

---

## 💡 Ultra-Token-Sparmodus: Maximale Produktivität bei minimalem Verbrauch

1. **Bedarfsgerechtes Routing:** Der TaskManager wählt nur die absolut notwendigen Spezialisten aus.
2. **Kompakte Prompt-Guardrails:** Alle Prompts erzwingen dichte, redundanzfreie Code-Ausgaben ohne Fülltexte.
3. **Lite-Tier Routing:** Routineaufgaben (Docs, README, Git, Hygiene) laufen auf dem sparsamen `gemini-3.1-flash-lite`.
4. **Auto-Recovery Lifecycle:** Bei 429 Quota wechselt das System verzögerungsfrei und kehrt nach 60s automatisch zum Primärmodell zurück.

---

## 🎯 Multi-LLM & Tool Matrix

| Provider / API | Zweck & Modell | Zugeordnete Agenten |
|---|---|---|
| 🤗 **Hugging Face** | Image Prompts, Logos & Visuals | **Bild- & Grafik-Designer (`image_generator`)** |
| 🌐 **Tavily Search** | Echte Live-Recherche im Web | **Web-Recherche & Info Specialist (`web_research`)** |
| 🧠 **DeepSeek Tier** | `deepseek:deepseek-chat` | **Architekt (`architect`)**, **Backend (`backend`)**, **Datenbank (`database`)**, **Security (`security`)**, **Code-Reviewer (`code_reviewer`)**, **KI/ML (`ml`)** |
| ⚡ **Groq Turbo Tier** | `groq:openai/gpt-oss-120b` | **QA-Tester (`tester`)**, **Refactoring (`refactoring`)**, **Performance-Ingenieur (`performance`)** |
| 🚀 **Standard Tier** | `gemini-3.6-flash` | Frontend, Data Engineer, API Integration, DevOps, Product Owner, Copywriter, Compliance, Retrospektive |
| 🔀 **OpenRouter Gateway** | Universal Router & Fallback | **Universal Fallback für alle Agenten** |
| 🏛️ **Heavy Tier** | `gemini-3.6-flash` / `claude-3-5-sonnet` | Teamleiter (`team_lead`), Ausbilder & Prompt-Optimizer (`agent_trainer`) |
| 💡 **Lite Tier** | `gemini-3.1-flash-lite` | Projekt-Hygiene (`project_cleaner`), UI/UX, Dokumentation, Übersetzungen, README, GitHub |

---

## 🚀 Alle CLI-Befehle im Überblick

```bash
python main.py
```

| Befehl | Beschreibung |
|---|---|
| `/projekte` | Listet alle bestehenden Projekte im Workspace auf |
| `/load <pfad/name>` | Lädt ein bestehendes Projekt (Workspace oder externer Pfad) zur Weiterentwicklung |
| `/team` | Zeigt alle 30 Spezialisten und deren KI-Modelle an |
| `/workspace [projekt]` | Listet alle generierten Dateien im Projektordner auf |
| `/export [projekt]` | Packt das Projektverzeichnis in ein ZIP-Archiv |
| `/run-tests [projekt]` | Führt automatische Unit-Tests im Projekt aus |
| `/push` | Führt manuell einen Git-Commit & Push aus |
| `/verlauf` | Zeigt den bisherigen Gesprächsverlauf |
| `/neu` | Startet eine neue Konversation (löscht Verlauf) |
| `/hilfe` | Zeigt die Befehlsübersicht an |
| `/beenden` | Beendet das Programm |

---

## 🧪 Tests ausführen

```bash
python -m unittest discover -s tests -p "test_*.py"
```
