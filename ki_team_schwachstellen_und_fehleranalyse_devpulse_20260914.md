# KI-Team Schwachstellen-, Fehler- und Problem-Analyse (Lauf: DevPulse & Gesamtsystem)
**Datum:** 14. September 2026  
**Projekt:** DevPulse (Entwickler-Aktivitäts- & Fokus-Dashboard)  
**Workspace:** `workspace/devpulse`  
**Run-Log:** `logs/runs/20260914_082830_devpulse.jsonl`  
**Verifikations-Log:** `logs/verification/20260914_082830_devpulse.log`  
**Status-Log:** `workspace/devpulse/.ai_team_status_full.log`  

---

## 1. Management Summary & Kernergebnis

Im Projektlauf **DevPulse** erstellte das KI-Team ein vollständiges Grundgerüst: Es wurden 14 Dateien geschrieben, die Abhängigkeiten via `pip install` erfolgreich in der isolierten Umgebung eingerichtet, statische Audits (pip-audit, bandit, ruff, Lizenzprüfung) fehlerfrei bestanden und das Dashboard im Headless-Browser (Playwright) erfolgreich aufgerufen.

Dennoch schloss das Projekt mit **`verification_ok: false`** und **`is_done: false` (Blocker: `tests_pass`)** ab, nachdem **997.919 Tokens** und **31 Agenten-Aufrufe** über **15 Minuten Laufzeit** verbraucht wurden.

Die Analyse deckt **4 wesentliche Schwachstellen und Fehler im Multi-Agenten-System und Framework** auf:

1. **Routing-Fehlzuordnung bei Repository- & CRUD-Methodenfehlschlägen (Database vs. Tester):**  
   Der Test schlug fehl mit `AttributeError: 'SessionRepository' object has no attribute 'get_by_id'`. Das System wies die Korrektur dem `tester`-Agenten zu, statt dem `database`-Agenten (dem tatsächlichen Autor von `session_repo.py`). Der Tester löschte/änderte die Assertion nicht und konnte das Repository nicht anpassen, wodurch der Fix-Loop in eine Endlosschleife lief.
2. **`Hard Delivery Gate` Kollaps beim Tester-Agenten:**  
   In Versuch 1 verbrauchte der `tester`-Agent **107.510 Tokens in 27 Sekunden**, führte 8 Tool-Calls aus, speicherte aber keine Datei per `write_file`/`edit_file`. Dies löste das Hard Delivery Gate aus (`failure_class: agent_error`), wodurch über 10% des gesamten Run-Budgets wirkungslos verpufften.
3. **Ghost-Frontend-Problem (Frontend-Vollständigkeits-Täuschung):**  
   Das generierte Frontend in `static/index.html` besteht nur aus einem UI-Skelett mit Timer-Anzeige und CSS. Es gibt **keine JavaScript-Logik (`static/js/app.js`)**, keine REST-API-Anbindung (`fetch`) und keine Router-Einbindung in FastAPI (`app/main.py` enthält nur ein TODO: `# TODO: Include routers here once they are created`). Dennoch meldeten sowohl der `Completeness-Check` als auch der `Playwright-Browser-Check` ein grünes Ergebnis ("fehlerfrei"), weil keine JS-Fehler geworfen werden, wenn überhaupt kein Skript existiert.
4. **Fehlendes Contract-Driven Test-Design bei ORM-Modellen:**  
   Der QA-Tester konstruierte zu Beginn Tests mit Attributen (`Project(color=...)`, `Session(title=...)`), die in den SQLAlchemy-Modellen des `database`-Agenten gar nicht existierten.

---

## 2. Detaillierte Fehleranalyse

### Schwachstelle 1: Falsches Fehler-Routing bei fehlenden Methoden (`_class_definition_owner`)

* **Symptom:**  
  Im Verifikationslog:
  ```text
  tests\test_devpulse.py:169: in test_session_repository_crud
      fetched_session = await session_repo.get_by_id(created_session.id)
  E   AttributeError: 'SessionRepository' object has no attribute 'get_by_id'
  ```
  Obwohl `ProjectRepository` in `app/repositories/project_repo.py` die Methode `get_by_id()` besitzt, hat der `database`-Agent sie in `SessionRepository` (`app/repositories/session_repo.py`) schlicht vergessen zu implementieren (dort gab es nur `__init__` und `create`).
* **Ursache im Framework (`agents/orchestrator/failure_diagnosis.py`):**  
  In `_route_failure_owners()` prüft die Erkennung:
  ```python
  elif (
      (im := _INSTANCE_ATTRIBUTE_ERROR_RE.search(message))
      and im.group(1) != "dict"
      and (class_owner := _class_definition_owner(im.group(1), file_owners, available_agents, project_dir))
  ):
      owners.add(class_owner)
  ```
  `_INSTANCE_ATTRIBUTE_ERROR_RE` sucht:
  ```python
  re.compile(r"AttributeError:\s*'(\w+)' object has no attribute '(\w+)'")
  ```
  Auf Windows-Systemen oder wenn im Traceback `tests/test_devpulse.py` in `files` steht, enthält `owners` zunächst `{tester}`. Wird `class_owner` (`database`) hinzugefügt, enthält `owners` `{tester, database}`.  
  Im Eskalationspfad und im Dispatcher wurde jedoch primär der `tester` adressiert (`verify_fix_tester_1` und `verify_model_escalation_tester_2`). Der Tester weigerte sich zu Recht, seinen Test ungültig zu machen, konnte aber das fremde Repository nicht reparieren.
* **Lösung:**  
  Wenn ein `AttributeError: '{Klasse}' object has no attribute '{methode}'` auftritt und `{Klasse}` eine Domänen- oder Repository-Klasse des Produktivcodes ist, muss der `tester` aus `owners` entfernt werden (`owners.discard("tester")`), damit der **Autor der Klasse** (`database` bzw. `backend`) die fehlende Methode nachliefert.

---

### Schwachstelle 2: `Hard Delivery Gate` Crash des Testers (107.510 Tokens Verlust)

* **Symptom:**  
  Run-Log Zeile 20:
  ```json
  {
    "agent_id": "tester",
    "success": false,
    "prompt_tokens": 106509,
    "completion_tokens": 1001,
    "total_tokens": 107510,
    "failure_class": "agent_error",
    "error": "Hard Delivery Gate: Agent hat trotz Korrektur-Hinweis keine einzige Datei über write_file/edit_file gespeichert - der Tokenverbrauch ist verpufft."
  }
  ```
* **Ursache:**  
  Der `tester`-Agent (`agents/tester_agent.py`) ist in `CODE_WRITING_AGENT_IDS` eingetragen. Wenn er in den Verifikations-Fix geschickt wird, liest er zwar die Test- und Repository-Dateien (`tool_calls_count: 8`), entscheidet sich aber analytisch dagegen, die Test-Datei zu ändern (da der Test semantisch korrekt war und die fehlende Methode rügte). Er formuliert seine Analyse als Antworttext, speichert aber keinen Dateiinhalt. Das Delivery Gate fordert ihn auf zu schreiben, er schreibt erneut nichts und scheitert hart.
* **Lösung:**  
  Im Fix-Task-Prompt für Verifikationsfehler muss dem Agenten ein klarer Handlungsleitfaden gegeben werden:  
  *Wenn der Fehler nicht im eigenen Zuständigkeitsbereich liegt, darf der Agent nicht in eine passive Text-Antwort verfallen, sondern das Framework muss erkennen, wenn ein Agent keine Datei-Mutation vornimmt, und den Task sofort an den Modul-Owner umleiten.*

---

### Schwachstelle 3: Ghost-Frontend – Playwright & Completeness verifizieren leere Fassade

* **Symptom:**  
  Im Status-Log steht:
  ```text
  - 🧩 Vollständigkeits-Check: keine Stub-/Platzhalter-Funde
  - 🌐 Frontend/UI-Check: http://127.0.0.1:56332/static/index.html [playwright] fehlerfrei (JS wurde echt ausgeführt).
  ```
  In Wirklichkeit:
  1. `workspace/devpulse/static/index.html` hat **kein einziges `<script>`-Tag**.
  2. Es gibt keine JavaScript-Datei im gesamten `workspace/devpulse/static/`-Verzeichnis.
  3. Die Kernanforderungen (Timer starten/stoppen, Tasks speichern, Statistiken visualisieren) sind im Frontend reine HTML-Attrappen ohne jede Logik.
  4. In `app/main.py` wurden die API-Router nicht gemountet:
     ```python
     # TODO: Include routers here once they are created in app/api/
     # app.include_router(api_router, prefix=settings.API_V1_STR)
     ```
* **Ursache:**  
  - **BrowserVerifier (`core/browser_verifier.py`):** Prüft, ob beim Laden von `index.html` Konsolenfehler oder 404-Fehler auftreten. Da kein Skript eingebunden ist, gibt es weder JS-Laufzeitfehler noch 404-Requests. Playwright wertet den Check als `passed = True`.
  - **Completeness-Check (`core/verifier/completeness.py`):** `_missing_frontend_entrypoints()` greift nur, wenn eine `package.json` existiert. Bei reinen Vanilla-HTML/CSS/JS-Projekten (wie von FastAPI serviert) prüft der Completeness-Check nicht, ob interaktive UI-Elemente (`<button>`, `<form>`) auch tatsächlich ein begleitendes Skript besitzen.
* **Lösung:**  
  1. Erweiterung von `_missing_frontend_entrypoints()`: Wenn ein Frontend HTML-Dateien mit Formularen, Buttons oder dynamischen Dashboards enthält, muss mindestens eine echte `.js`-Datei existieren und eingebunden sein.
  2. Erweiterung des `BrowserVerifier`: Eine Seite ohne jegliche Skripte und ohne Daten-Interaktion sollte eine Warnung oder Nicht-Bestehen auslösen, wenn in den Projektanforderungen ein interaktives Tool/Dashboard verlangt wurde.

---

### Schwachstelle 4: Schnittstellen-Drift (Interface Mismatch) bei Test-Generierung

* **Symptom:**  
  Beim Erstlauf scheiterten 4 Tests sofort:
  ```text
  TypeError: 'color' is an invalid keyword argument for Project
  TypeError: 'title' is an invalid keyword argument for Session
  TypeError: ProjectRepository.create() got an unexpected keyword argument 'color'
  ```
* **Ursache:**  
  Der `tester`-Agent hat seine Tests parallel oder isoliert von der konkreten Implementierung des `database`-Agenten geschrieben. `interface_contract.json` enthielt zu diesem Zeitpunkt nur abstrakte Signaturen, aber keine exakten Spaltendefinitionen der SQLAlchemy-Modelle.
* **Lösung:**  
  Der Tester muss im Prompt strikt angewiesen werden, vor dem Schreiben von Integrationstests die tatsächlichen Klassen in `app/models/` und `app/repositories/` via `read_file` zu inspizieren.

---

## 3. Konkrete Handlungsempfehlungen für das Framework

| Bereich | Schwachstelle | Empfohlene Maßnahme |
|---|---|---|
| **Fehler-Routing** | `AttributeError` auf Methoden (`get_by_id`) wird dem Tester statt dem Repo-Autor zugeordnet | In `failure_diagnosis.py`: Wenn die Zielklasse in `file_owners` existiert, `tester` aus `owners` entfernen und den Autor der Klasse verpflichtend beauftragen. |
| **Delivery Gate** | `tester` stürzt im Fix-Loop mit 107k verpufften Tokens ab | Timeout & Token-Cap für Fix-Durchläufe auf max. 30.000 Tokens drosseln; bei 0 geschriebenen Dateien sofort zur Neudiagnose abbrechen. |
| **Frontend-Validierung** | Vanilla-HTML ohne JS wird als "fehlerfrei" validiert | In `core/verifier/completeness.py` prüfen, ob HTML-Dateien mit Formularen/Buttons existieren, denen eine JavaScript-Logikdatei fehlt. |
| **FastAPI Mounting** | `app/main.py` belässt Router als TODO-Kommentar | `check_completeness()` muss prüfen, ob definierte Router in `app/api/` oder Controller in `app/main.py` tatsächlich per `app.include_router(...)` eingebunden sind. |
