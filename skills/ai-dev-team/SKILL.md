---
name: ai-dev-team
description: Delegiert komplexe Softwareentwicklungs-, Refactoring-, Test- oder Auditierungsaufgaben an das lokale 30-Agenten KI-Softwareentwickler-Team.
---

# KI-Softwareentwickler-Team (30 Spezialisten)

Nutze diesen Skill, wenn:
- Ein neues Projekt, Modul oder Feature von Grund auf entwickelt werden soll.
- Ein bestehendes Projekt umfassend refaktoriert, mit Tests abgesichert oder umgebaut werden soll.
- Ein Security-, Performance- oder WCAG-Barrierefreiheits-Audit mit anschließender Behebung gefordert wird.
- Du Aufgaben parallel an Spezialisten (Architect, Backend, Frontend, Database, ML, DevOps, Tester, Security) delegieren möchtest.

---

## 🛠️ Ausführung & Befehle

Das KI-Team wird über den Headless Goal-Loop ausgeführt. Es führt selbstständig Planungsphasen, Code-Generierung, Dependency-Installation, Pytest-Verifikation und Fehlerschleifen aus.

### 1. Im aktuellen Projektverzeichnis arbeiten:
Führe folgenden Befehl aus (ersetze `<ZIEL>` durch die konkrete Anforderung):

```powershell
python "c:\Users\sche-\Desktop\Programmieren Projekte\AI-Softwareentwickler-Team\main.py" --goal "<DEIN_ZIEL>" --project "."
```

### 2. In einem externen/spezifischen Projektordner arbeiten:
```powershell
python "c:\Users\sche-\Desktop\Programmieren Projekte\AI-Softwareentwickler-Team\main.py" --goal "<DEIN_ZIEL>" --project "C:\Pfad\zum\Projekt"
```

### 3. Ein brandneues Projekt im Workspace des Teams anlegen:
```powershell
python "c:\Users\sche-\Desktop\Programmieren Projekte\AI-Softwareentwickler-Team\main.py" --goal "<DEIN_ZIEL>" --project "neues_projekt_slug"
```

---

## ⚙️ Wie das KI-Team arbeitet
1. **Planung & Architektur (Phase 1 & 2):** Team Lead, Product Owner, Business Analyst und Architect erstellen Systemblueprint, DoD und ADRs.
2. **Design & Content:** UI/UX, Design-Tokens, barrierefreie Paletten und Copywriting.
3. **Software-Entwicklung (Phase 3):** Backend, Frontend, Database, API-Integration, Data-Engineer, ML und Performance schreiben modularen Code.
4. **Qualität, Security & DevOps (Phase 4 & 5):** Tester schreibt Pytest-Suiten, DevOps erstellt Dockerfile, Security führt Audits durch, Resilience-Guard baut Circuit Breaker.
5. **Echte Verifikation:** Das Team installiert die Abhängigkeiten in einer isolierten Umgebung, führt echte Pytest-Läufe aus und behebt Fehlschläge in autonomen Fix-Schleifen.
