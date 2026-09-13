# Claude Code Skill: KI-Softwareentwickler-Team (ai-dev-team)

Dieses Verzeichnis enthält den fertigen Skill, mit dem Claude Code in **jedem beliebigen Projekt** dein 30-köpfiges Spezialistenteam aufrufen und Aufgaben autonom delegieren kann.

---

## 📁 Installation in Claude Code

Claude Code unterstützt benutzerdefinierte Skills und globale Befehle. Du kannst diesen Skill auf zwei Wegen einbinden:

### Option A: Als Skill für Claude Code (Empfohlen)
Kopiere den Ordner `skills/ai-dev-team` in dein lokales Claude-Konfigurationsverzeichnis:
* **Windows-Pfad:** `%APPDATA%\Claude\skills\ai-dev-team` oder `~/.claude/skills/ai-dev-team`
* Enthält die Datei `SKILL.md`.

### Option B: Direkt in `CLAUDE.md` in jedem Projekt verankern
Füge einfach den folgenden Abschnitt in die `CLAUDE.md` deiner anderen Projekte ein:

```markdown
## 🤖 KI-Softwareentwickler-Team (30 Spezialisten)
Wenn du ein großes Feature implementieren, das Projekt refaktorieren, eine vollständige Testsuite schreiben oder das Projekt auf Sicherheit prüfen möchtest, kannst du das lokale KI-Softwareentwickler-Team aufrufen:

```bash
python "C:/Users/sche-/Desktop/Programmieren Projekte/AI-Softwareentwickler-Team/main.py" --goal "<ZIEL_BESCHREIBUNG>" --project "."
```
```

---

## 🚀 Was dieser Skill für Claude ermöglicht:
1. **Autonome Projekt-Weiterentwicklung:** Claude übergibt das Ziel an das KI-Team.
2. **30 Spezialisten:** Das Team zerlegt die Aufgabe in Phasen (Architektur, UI/UX, Backend, Frontend, ML, Security, QA, etc.).
3. **Echte Verifikation:** Das Team installiert automatisch Dependencies, führt Pytest/Linter aus und korrigiert Fehler selbstständig.
4. **Ergebnisübernahme:** Sobald das Team fertig ist, übernimmt Claude den sauberen, getesteten Code.
