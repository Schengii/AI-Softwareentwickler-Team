# 🧬 Tiefenanalyse & Optimierungs-Roadmap für das KI-Softwareentwickler-Team

**Stand:** 10.09.2026  
**Ziel:** Weiterentwicklung des Frameworks zum autonomen, fehlerresistenten Softwareentwickler-Team  
**Scope:** Ausschließlich das **Framework** (`core/`, `agents/`, `interface/`, `memory/`, `evals/`) – **nicht** die Zielprojekte in `workspace/`.

---

## 🔍 Teil 1: Analyse der realen Fehlerbilder & Ursachen

Die Auswertung der neuesten Telemetrie- und Verifikations-Logs (insbesondere der 4 heutigen Läufe von `logipulse` sowie der 200 historischen Läufe) zeigt, dass Stufe 0 (Ehrliche Messung mit `core/run_logger.py`, `core/definition_of_done.py`) exzellent gegriffen hat: **Erstmals ist das tatsächliche Geschehen glasklar und ungeschminkt dokumentiert.**

Genau diese Dokumentation deckt nun die nächsten systemischen Flaschenhälse auf:

### 1. Kaskadierender Fallback-Kollaps („Silent Downgrade Cascade“)
- **Beobachtung:** Im Lauf `20260910_084833_logipulse.jsonl` forderten Rollen wie `architect`, `backend`, `security`, `code_reviewer` und `refactoring` richtigerweise `openai/gpt-oss-120b` (Groq) bzw. `gemini-3.8-flash` an.
- **Tatsächliches Verhalten:** **100 % aller erfolgreichen Calls wurden auf `gemini-3.1-flash-lite` herabgestuft!**
- **Ursache:** In `core/llm_factory.py` bricht bei einem temporären Schluckauf oder Provider-Limit (Groq/Gemini-3.8) der Client in die Fallback-Kette ein. Dort hangelt er sich bis zu `gemini-3.1-flash-lite` durch. 
- **Folge:** Komplexe Architekturen, Pydantic-Schemas und Backend-Pipelines werden von der kleinsten Modellstufe generiert. Als auch diese schließlich ihr Free-Tier-Tageslimit (`429 RESOURCE_EXHAUSTED: limit 500`) erreichte, starb das gesamte Team.

### 2. Der PyJWT vs. JWT Kollisions-Bug (Python-Ökosystem-Falle)
- **Fehlerbild:** Im Verifikations-Log (`logs/verification/20260910_084833_logipulse.log`) scheiterten alle Auth- und Endpoint-Tests sofort mit:
  ```text
  AttributeError: module 'jwt' has no attribute 'encode'
  ```
- **Ursache:** In `requirements.txt` standen:
  ```text
  pyjwt>=2.8.0
  jwt
  ```
  Das PyPI-Paket `jwt` ist ein völlig anderes (veraltetes/leeres) Paket als `PyJWT`. Wird `pip install jwt` nach oder mit `pyjwt` installiert, überschreibt es den Modul-Namespace `jwt`, und `jwt.encode()` verschwindet!
- **Systemischer Framework-Mangel:** 
  1. `core/verifier/completeness.py` mappt zwar `"jwt": "pyjwt"`, aber `core/manifest_guard.py` oder die Sandbox verhindern nicht, dass Agenten `jwt` als eigenständiges Paket in `requirements.txt` listen.
  2. **Fehlerhafter Fix-Loop:** Der Verifier diagnostizierte den `AttributeError: module 'jwt' has no attribute 'encode'` generisch und routete ihn blind an den `tester`. Der `tester` versuchte den Test zu ändern, anstatt die defekte Abhängigkeit in `requirements.txt` bzw. `src/main.py` anzupassen.

### 3. Falsche Agenten-Zuweisung im Verifikations-Fix-Loop
- **Beobachtung:** Bei Testfehlschlägen wie:
  - `AttributeError: module 'jwt' has no attribute 'encode'` (Ursache: Backend-Dependency / Router)
  - `assert 404 == 202` auf Route `/api/v1/events` (Ursache: Fehlender API-Prefix oder fehlender Router in `src/main.py`)
- **Verhalten:** Die Verifikation adressierte wiederholt den `tester` (`seq 11`, `seq 15` in `logipulse.jsonl`) mit `tests/test_events.py`.
- **Systemfehler:** Wenn Tests 404 zurückgeben, weil der Backend-Entwickler den Router in FastAPI nicht mit `app.include_router()` eingebunden hat, ist **nicht der Test kaputt, sondern das Backend**. Da der `tester` als Owner der Testdatei ermittelt wurde (Traceback endet in `test_events.py:33`), versucht der Tester vergeblich, Tests anzupassen, anstatt den `backend`-Agenten anzuweisen, den Router in `main.py` zu registrieren.

### 4. Völlige Blockade der Selbstheilung durch Token-Quota-Erschöpfung
- **Beobachtung:** Sobald ein Fix-Versuch nötig wurde, war das Kontingent von `gemini-3.1-flash-lite` erschöpft. Der `frontend`-Agent stürzte mit Exit-Code 429 ab (`seq 18`), und der Lauf endete mit `is_done: false`.
- **Ursache:** Fehlendes Routing auf alternative, tatsächlich vorhandene Provider (DeepSeek / OpenRouter / Groq), wenn Gemini global auf 429 steht.

---

## 🛠️ Teil 2: Konkrete Optimierungsmaßnahmen für das KI-Team

### P0: Resilientes Multi-Provider-Loadbalancing & Quota-Isolation
1. **Intelligentes Provider-Failover statt Einbahnstraße:**
   - Wenn Gemini ein 429 meldet, darf der Fallback nicht auf eine schwächere Gemini-Version gehen (da das Projekt-Quota bei Google oft projektweit gilt), sondern muss **sofort den Provider wechseln** (z. B. auf DeepSeek, OpenRouter oder Groq).
   - Bereits vorhandene API-Keys in `.env` müssen vorrangig genutzt werden, anstatt Free-Tier-Kontingente in Minuten zu verbrennen.
2. **Provider-Pinning mit Budget-Schutz:**
   - Verhindern, dass ein Agent stillschweigend von einem 120B-Modell auf ein 8B/Lite-Modell herabgestuft wird, ohne dass die Task-Komplexität angepasst wird. Lieber 10 Sekunden Backoff-Pause als ein unbrauchbarer Code-Entwurf.

### P1: Package-Collision & Dependency Sanitation Guard
1. **Verbot toxischer PyPI-Paketduplikate:**
   - `core/manifest_guard.py` muss bekannte Namespace-Kollisionen deterministisch bereinigen:
     - `jwt` vs. `PyJWT` (Wenn `pyjwt` genutzt wird, MUSS `jwt` verboten/entfernt werden).
     - `crypto` vs. `pycryptodome` / `cryptography`.
     - `PIL` vs. `pillow`.
2. **Auto-Sanitize vor Sandbox-Installation:**
   - Bevor `pip install -r requirements.txt` ausgeführt wird, filtert das Framework toxische / kollidierende Pakete automatisch heraus.

### P2: Smarter Fix-Loop mit Ursachen- statt Symptom-Routing
1. **404 Route-NotFound Routing:**
   - Tritt in Tests ein `assert 404 == ...` auf, ist zu 90 % der Router nicht in `main.py` / `app.py` registriert. Der Fix-Auftrag MUSS an `backend` gehen, nicht an `tester`!
2. **AttributeError / ImportError auf Drittanbieter-Modulen:**
   - Tritt ein `AttributeError: module 'X' has no attribute 'Y'` auf, muss der Diagnostiker prüfen: Ist `X` in `requirements.txt`? Handelt es sich um eine bekannte Paketkollision? Zuweisung an `backend`/`refactoring`, nicht an `tester`.
3. **Echte Arbeitsteilung beim Fixen:**
   - Wenn ein Test fehlschlägt, dürfen sowohl der betroffene Service-Entwickler (`backend`) als auch der `tester` im Tandem informiert werden: Einer stellt sicher, dass der Endpoint existiert, der andere validiert die Payload-Erwartung.

### P3: Architektur-Vertrag („API Contract First“)
1. **Deterministisches Routing-Schema:**
   - Der `architect` muss ein striktes JSON-Manifest der Endpunkte hinterlegen (z. B. `endpoints: [{"path": "/api/v1/events", "router_file": "src/events/router.py", "app_file": "src/main.py"}]`).
   - Der Verifier prüft statisch per AST VOR den Tests, ob jede Route in der zentralen FastAPI-App importiert und per `app.include_router` gemountet ist.

---

## 📋 Teil 3: Umsetzungs-Matrix für Framework-Code

| Bereich | Betroffene Datei(en) | Konkrete Änderung |
| :--- | :--- | :--- |
| **Quota & Failover** | `core/llm_factory.py` | Bei 429 Quota-Fehler sofort Provider wechseln (Cross-Provider-Failover), nicht innerhalb desselben Gemini-Projekts auf Lite herabstufen. |
| **Dependency-Schutz** | `core/manifest_guard.py`<br>`core/verifier/completeness.py` | Regel für `jwt` vs. `pyjwt` hinzufügen. Wenn `pyjwt` da ist, Zeile `jwt` in `requirements.txt` verbieten/löschen. |
| **Fix-Diagnostik** | `agents/orchestrator/verification.py` | `_diagnose_runtime_failure()` erweitern: `assert 404` auf API-Aufrufe routet zwingend an `backend` mit dem Hinweis `Router-Registrierung in main.py prüfen`. |
| **Sandbox-Sicherheit** | `core/verifier/environment.py` | Bereinigung toxischer Einträge vor `pip install`. |
| **DoD-Messung** | `core/definition_of_done.py` | Beibehalten und als Qualitäts-Gate im CI-Report etablieren. |
