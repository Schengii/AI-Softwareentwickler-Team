# KI-Team Schwachstellen- und Fehleranalyse (Lauf: AetherMesh)
**Datum:** 13. September 2026  
**Projekt:** AetherMesh (Dezentrales Mesh-Netzwerk mit Zero-Knowledge Routing, Byzantine Fault Tolerance & WebRTC Peer Discovery)  
**Run-Log:** `logs/runs/20260913_093139_aethermesh.jsonl`  
**Verification-Log:** `logs/verification/20260913_093139_aethermesh.log`  

---

## 1. Management Summary & Kernergebnis

Beim Durchlauf des anspruchsvollen Projekts **AetherMesh** zeigte das KI-Team eine **architektonisch und code-technisch hervorragende Leistung**:
- Sämtliche 11 Rollen (Architect, Backend, Database, Frontend, Performance, ML, Accessibility, Readme, Tester, Resilience Guard, Security) erzeugten modular aufgebauten, sauberen und syntaktisch einwandfreien Python- & TypeScript-Code.
- Es wurden 9 anspruchsvolle asynchrone Unit- und Integrationstests geschrieben (`test_crypto.py`, `test_routing.py`, `test_topology.py`).
- **Manueller Nachtest im Projekt-Virtualenv:** **Alle 9 Tests laufen ohne Fehler durch (9 passed in 0.45s)!**

**Trotzdem schlug der Lauf im Orchestrator fehl (`verification_ok: false`, `budget_aborted: true`, `blocking: ["tests_pass"]`).**

Der Grund für das Scheitern war **kein inhaltlicher Code-Fehler des Agenten-Teams**, sondern ein **Zusammenspiel aus zwei systemischen Schwachstellen des Frameworks**:
1. **Pytest-Asyncio Framework-Lücke:** Der initiale Testlauf scheiterte, weil `pytest` asynchrone Testfunktionen (`async def test_...`) standardmäßig nicht unterstützt und `pytest-asyncio` bzw. `asyncio_mode = auto` in der Verifizierungs-Engine fehlte.
2. **Budget-Abbruch kurz vor Bestätigung (Confirmation Run Lockout):** Der Tester-Fix-Agent behob das Problem korrekt (erstellte `pytest.ini` und passte `requirements.txt` an), doch durch den hohen Token-Verbrauch des Fix-Prompts wurde das Token-Budget überschritten (1.140.935 Tokens vs. 1.000.000 Basis / 1.100.000 Confirmation Buffer), woraufhin der Verifizierer abbrach, **ohne die Bestätigungstests überhaupt auszuführen**.

---

## 2. Detaillierte Fehleranalyse & Schwachstellen

### Schwachstelle 1: Die `pytest-asyncio` / Async-Test Framework-Lücke
* **Symptom:** Im initialen Verifizierungsschritt (`pytest (erstlauf)`) schlugen alle 9 Tests fehl:
  ```text
  async def functions are not natively supported and have been skipped.
  You need to install a suitable plugin for your async framework, for example:
    - anyio
    - pytest-asyncio
    - pytest-tornasync
    - pytest-trio
    - pytest-twisted
  PytestUnknownMarkWarning: Unknown pytest.mark.asyncio - is this a typo?
  ```
* **Ursache im Framework ([core/verifier/environment.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/core/verifier/environment.py)):**
  - Die Methode `_ensure_pytest_available()` prüft ausschließlich, ob das Paket `pytest` im venv installiert ist. Wenn ja, wird nichts weiter unternommen.
  - Moderne Python-Projekte (FastAPI, WebRTC, AsyncIO-Mesh) nutzen fast durchgehend `async def test_...`.
  - Pytest verlangt für Coroutinen zwingend das Plugin `pytest-asyncio` sowie die Konfiguration `asyncio_mode = auto` (oder Aufruf mit `-o asyncio_mode=auto`).
  - Da das Framework dies nicht proaktiv bereitstellt oder als Default-Argument an `pytest` übergibt, scheitert der Erstlauf bei jedem asynchronen Projekt reflexartig, obwohl der Code fehlerfrei ist.

---

### Schwachstelle 2: Fehlender Re-Sync des Environments nach Fix-Iterationen
* **Symptom:** Wenn ein Agent im Fix-Loop (`verify_fix_tester_1`) feststellt, dass ein Paket fehlt und es in `requirements.txt` oder `package.json` einträgt, wird die virtuelle Umgebung vor dem Re-Test **nicht aktualisiert**.
* **Ursache im Orchestrator ([agents/orchestrator/verification.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/agents/orchestrator/verification.py)):**
  - `verifier.ensure_environment()` wird nur einmal ganz zu Beginn der Verifizierungsphase aufgerufen.
  - Wenn `tester` oder `backend` während der Fehlerbehebung `requirements.txt` modifiziert, führt `verification.py` danach direkt `_run_tests_logged()` aus.
  - Wäre `pytest-asyncio` nicht zufällig schon im venv durch frühere Builds vorhanden gewesen, hätte der Re-Test selbst mit `pytest.ini` versagt, weil `pip install` nach dem Edit nie getriggert worden wäre.

---

### Schwachstelle 3: Zu enger Confirmation-Buffer & Token-Exhaustion bei Fix-Tasks
* **Symptom:**
  ```json
  "total_tokens": 1140935,
  "verification_ok": false,
  "budget_aborted": true,
  "blocking": ["tests_pass"]
  ```
* **Ursache im Verifizierungs-Budget ([agents/orchestrator/verification.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/agents/orchestrator/verification.py)):**
  - Die Methode `_run_budget_within_confirmation_buffer()` erlaubt lediglich einen 10%-Puffer (`MAX_RUN_TOKENS * 1.10 = 1.100.000 Tokens`).
  - Vor dem Fix-Task lag das Projekt bei ca. 1.051.000 Tokens.
  - Der Aufruf von `verify_fix_tester_1` verbrauchte 89.240 Tokens (durch Injection des gesamten Test-Outputs und aller Projektdateien).
  - Damit landete das Projekt bei 1.140.935 Tokens – genau 40.935 Tokens über dem 1.100.000-Puffer.
  - **Fataler Ablauf:** Der Tester-Agent hat den Fix erfolgreich geschrieben (`pytest.ini` angelegt), doch direkt vor dem Re-Test griff die Prüfung `_run_budget_exceeded()`. Die Bestätigungsphase wurde abgebrochen, und das Projekt als "fehlgeschlagen" deklariert, obwohl der Fix bereits im Dateisystem aktiv war!

---

### Schwachstelle 4: Fehlende Standard-Testkonfiguration (`pytest.ini` / `pyproject.toml`) durch das Agenten-Team
* **Symptom:** Weder der `architect` noch der `tester` generierten zu Beginn eine Konfigurationsdatei für das Test-Framework.
* **Ursache bei den Agenten-Prompts:**
  - Der `architect` spezifiziert Projektstrukturen, vergisst aber häufig tooling-spezifische Konfigurationsdateien wie `pytest.ini`, `.coveragerc` oder `setup.cfg`.
  - Der `tester` schreibt sauberen Testcode mit `@pytest.mark.asyncio`, verlässt sich aber blind darauf, dass die Test-Engine magisch weiß, wie mit asynchronen Tests umzugehen ist.
  - Eine explizite Anweisung in den Prompts für `architect` und `tester`, bei asynchronen Projekten stets `pytest.ini` mit `[pytest]\nasyncio_mode = auto\npythonpath = .` anzulegen, fehlte bisher.

---

## 3. Gegenüberstellung: Vorher vs. Nachher (Beweis)

| Schritt | Status im Run | Status manuell im Projekt-Venv |
|---|---|---|
| Code-Generierung (11 Agenten) | Erfolgreich | 100% syntaktisch valide |
| Testlauf 1 (ohne `asyncio_mode`) | ❌ Failed (9/9 Errors) | ❌ Failed (`async def not supported`) |
| Tester-Fix (`pytest.ini` geschrieben) | ✅ Erfolgreich | ✅ `pytest.ini` existiert |
| Testlauf 2 (Re-Test / Bestätigung) | ⚠️ Übersprungen (Budget-Abbruch) | **✅ 9 PASSED in 0.45s** |

---

## 4. Empfohlene Maßnahmen & Verbesserungen

1. **Automatisches Async-Setup im Verifier ([core/verifier/environment.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/core/verifier/environment.py)):**
   - In `_ensure_pytest_available()` immer sicherstellen, dass `pytest-asyncio` installiert ist.
2. **Automatischer Fallback-Flag im Testrunner ([core/verifier/testrunner.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/core/verifier/testrunner.py)):**
   - Pytest immer mit `-o asyncio_mode=auto` aufrufen (oder wenn `pytest-asyncio` installiert ist bzw. `async def test_` im Code gefunden wird).
3. **Environment-Re-Sync nach Fix-Edits ([agents/orchestrator/verification.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/agents/orchestrator/verification.py)):**
   - Wenn ein Fix-Agent Dependency-Dateien (`requirements.txt`, `package.json`, `pyproject.toml`) verändert, muss vor dem nächsten Testlauf zwingend `verifier.ensure_environment()` erneut ausgeführt werden.
4. **Intelligenterer Confirmation-Puffer:**
   - Wenn ein Fix-Agent erfolgreich Code oder Config geändert hat, sollte der **Confirmation Run** (das reine Ausführen von `pytest`, was 0 LLM-Tokens kostet!) **immer** durchgeführt werden, anstatt vorher wegen Token-Limits hart abzubrechen. Das reine Ausführen von pytest verbraucht keine API-Tokens!
5. **Prompt-Schärfung für `architect` & `tester`:**
   - Verpflichtende Generierung einer `pytest.ini` mit `asyncio_mode = auto` und `pythonpath = .`, sobald asynchrone Bibliotheken oder Funktionen verwendet werden.
