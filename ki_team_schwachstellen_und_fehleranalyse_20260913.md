# 🔬 Umfassende System-, Fehler- und Schwachstellenanalyse des KI-Teams

**Erstellungsdatum:** 13. September 2026  
**Analysierte Läufe & Projekte:** `incident_pulse` (Lauf vom 13.09.2026), `vortex_circuit`, `hooksentinel`, `certpulse`, `vaultguard`, `sentinelgrid`, `pulseflow_gateway`  
**Analysierte Kernkomponenten:** Orchestrator (`agents/orchestrator/`), Verification-Engine (`core/verifier/`), Failure-Triage (`core/failure_triage.py`), Agent-System-Prompts & Direktiven (`agents/`), Completeness-Checks (`core/verifier/completeness.py`), Token-Budgeting (`.env`, `config.py`)

---

## 🎯 Executive Summary: Aktueller Zustand des KI-Teams

Das autonome KI-Entwicklerteam (33 Spezialisten, 6 Fachbereiche) zeigt in Konzeption, Architektur und Fachcode herausragende Fähigkeiten:
- **Exzellente Domänen-Entwürfe:** Async FastAPI-Routen, SQLAlchemy 2.0 Async-Engines, Pydantic V2-Validierung, Single-Page-Applications (Vanilla JS/CSS), sauber dokumentierte ADRs (`docs/adr/`) und Schnittstellenverträge (`interface_contract.json`).
- **Hohe Resilienz-Kompetenz:** Ausgefeilte Circuit-Breaker-Implementierungen mit Exponential Backoff, Jitter und Fallback-Caches.

Dennoch scheitern anspruchsvolle Fullstack-Läufe (wie der jüngste Durchlauf von `incident_pulse`) am Ende formal mit **`verification_ok: false`** und **`budget_aborted: true`**.

> [!CAUTION]
> **Die Kernursache:** Das Team scheitert **nicht** an fehlender Programmierkompetenz der Modelle, sondern an **strukturellen Reibungsverlusten im Framework**:
> 1. Ein **Event-Loop-Initialisierungs-Bug** im Code des `resilience_guard`-Agenten bringt `pytest` schon bei der Modul-Collection zum Absturz.
> 2. Die **automatische Fehler-Triage** (`core/failure_triage.py`) erkennt `RuntimeError` beim Modul-Import nicht und routet den Fix blind an unbeteiligte Rollen (`qa_lead`, `frontend`), wodurch wertvolle Fix-Versuche verpuffen.
> 3. **Token-Budget-Grenze (`MAX_RUN_TOKENS = 1.000.000`)** wird bei Multi-Turn-Fixschleifen knapp überschritten (1.017.927 Tokens in `incident_pulse`), wodurch die Definition of Done hart blockiert wird.
> 4. **Asymmetrische Direktiven:** Während für `architect`, `backend` und `tester` strikte Verbote gegen Import-Drift und ungesicherte Settings existieren, fehlen für `resilience_guard` und `database` Richtlinien gegen Modul-Level-Initialisierung asynchroner Objekte.

---

## 1. Detaillierte Analyse der aufgedeckten Fehler & Schwachstellen

### 🔴 Schwachstelle 1: Der "Top-Level Event-Loop"-Bug des `resilience_guard` (Python 3.10+ / 3.14)
* **Realer Fundort:** `workspace/incident_pulse/app/core/circuit_breaker.py:L118` & `L300`
* **Symptom:**
  ```text
  ERROR collecting tests/test_circuit_breaker.py
  tests/test_circuit_breaker.py:3: in <module>
      from app.core.circuit_breaker import CircuitBreaker, CircuitState, ...
  app/core/circuit_breaker.py:300: in <module>
      default_webhook_cb = CircuitBreaker(name="global_webhook_breaker", ...)
  app/core/circuit_breaker.py:118: in __init__
      self._last_state_change = asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else 0.0
  E   RuntimeError: There is no current event loop in thread 'MainThread'.
  ```
* **Ursache:**
  1. In modernen Python-Versionen (Python 3.10+, 3.12, 3.14) erzeugt `asyncio.get_event_loop()` im Main-Thread standardmäßig keinen neuen Event-Loop mehr, wenn keiner läuft. Der Aufruf wirft sofort `RuntimeError`.
  2. Der Agent instanziiert auf **Modulebene** (Zeile 300) ein globales Objekt `default_webhook_cb = CircuitBreaker(...)`.
  3. Sobald `pytest` die Testdateien einsammelt (`import app.core.circuit_breaker`), bricht die Testsuite sofort ab (Exit-Code 2). Kein einziger Test kann ausgeführt werden!
* **Warum der Fix-Loop scheiterte:**
  Im Fix-Versuch ersetzte der Agent `asyncio.get_event_loop().time()` durch dieselbe fehlerhafte Bedingung (`... if asyncio.get_event_loop().is_running() ...`), weil `is_running()` bereits am ersten `get_event_loop()` scheiterte, statt `asyncio.get_running_loop()` in einem `try/except RuntimeError`-Block oder `time.monotonic()` zu verwenden.

---

### 🔴 Schwachstelle 2: Fehlende Erkennung von Import-Time `RuntimeError` in `core/failure_triage.py`
* **Realer Fundort:** `core/failure_triage.py` vs. `agents/orchestrator/verification.py`
* **Mechanismus:**
  - `core/failure_triage.py` besitzt mächtige Parser für `ImportError`, `ModuleNotFoundError`, `SyntaxError`, `SettingsValidationError` und `MissingGreenlet`.
  - Bricht der Import einer Datei beim Test-Sammeln jedoch mit einem **`RuntimeError`**, **`AttributeError`** oder **`TypeError`** ab, liefert `triage_structural_failure()` den Rückgabewert `None`.
* **Fatale Auswirkung:**
  - Die Verification-Engine fällt auf das generische Traceback-Routing zurück.
  - Da der Traceback sowohl `tests/test_circuit_breaker.py` (Owner: `tester`) als auch `app/core/circuit_breaker.py` (Owner: `resilience_guard`) enthält, schlägt die Eskalationsleiter fehl: Nach einem unvollständigen Fix des `resilience_guard` wurde der `qa_lead` und anschließend der `frontend`-Agent beauftragt (`incident_pulse` Logzeilen 21–24), obwohl das Problem rein im Python-Backend-Code lag.

---

### 🔴 Schwachstelle 3: Token-Ceiling & Multi-Turn-Akkumulation in der Fix-Schleife
* **Realer Fundort:** `.env:L80` (`MAX_RUN_TOKENS=1000000`) & `agents/orchestrator/budget.py`
* **Mechanismus:**
  - In `incident_pulse` verbrauchte die reguläre Feature-Entwicklung (Architektur, Backend, Frontend, DB, Security, Resilience, Doku) ca. **450.000 Tokens**.
  - Der anschließende Fix-Loop für die Verifikation benötigte für Re-Prompts, Kontext-Übertragungen und AST-Checks weitere **560.000 Tokens**.
  - Gesamtsumme: **1.017.927 Tokens**.
  - Der Orchestrator aktivierte den Notstopp (`budget_aborted: true`). Obwohl die Anwendung zu 98% fertig war, wurde der Lauf als fehlschlagend markiert.
* **Token-Treiber im Detail:**
  Jeder Fix-Agent erhält im Prompt den vollen Traceback, den bisherigen Code, ADR-Auszüge und System-Direktiven. Bei 7 Tool-Aufrufen im Fix-Loop steigt der Prompt-Token-Verbrauch quadratisch an.

---

### 🔴 Schwachstelle 4: Fehlender Smoke-Test vor der Verifikations-Testsuite
* **Realer Fundort:** `agents/orchestrator/verification.py:L1067-L1150` (`_run_smoke_test_gate`)
* **Problem:**
  - Das Smoke-Test-Gate prüft zwar, ob der **Haupteinstiegspunkt** (`app/main.py`) startet.
  - Es prüft jedoch **nicht**, ob die untergeordneten Kern-Module (wie `app.core.circuit_breaker`, `app.db.models`, `app.services`) importierbar sind.
  - Wenn `app/main.py` den fehlerhaften Circuit-Breaker erst spät oder via Lazy-Import lädt, besteht `app/main.py` das Smoke-Gate, aber `pytest` scheitert sofort bei der Collection der Modultests.

---

### 🔴 Schwachstelle 5: Fehlende Resilienz-Direktive in `agents/team_directives.py`
* **Realer Fundort:** `agents/team_directives.py` & `agents/resilience_guard_agent.py`
* **Lücke im Regelwerk:**
  In `agents/team_directives.py` gibt es:
  - `ARCHITECT_CONTRACT_DIRECTIVE`
  - `BACKEND_CONTRACT_DIRECTIVE`
  - `TESTER_CONTRACT_DIRECTIVE`
  - `FRONTEND_CONTRACT_DIRECTIVE`
  - `_SETTINGS_RULE` (Dev-Defaults für Pydantic-Settings)
  
  Es fehlt jedoch eine **`RESILIENCE_AND_ASYNC_DIRECTIVE`**:
  > *"Erzeuge NIEMALS asynchrone Instanzen (Locks, Queues, CircuitBreaker mit `get_event_loop()`, DB-Engines) auf Modulebene. Nutze immer `time.monotonic()` statt `loop.time()` für Timeouts/Cooldowns und instanziiere Status-Objekte innerhalb von FastAPI Lifespan-Handlern oder Dependencies."*

---

## 2. Zusammenfassende Matrix der Schwachstellen

| Nr. | Komponente | Art des Problems | Konkrete Auswirkung | Schweregrad |
|---|---|---|---|---|
| **1** | `resilience_guard` | Bug in `circuit_breaker.py` | `RuntimeError: There is no current event loop` blockiert `pytest` komplett | **Kritisch** (Blocker) |
| **2** | `core/failure_triage.py` | Lücke in Triage-Regex | `RuntimeError` beim Test-Sammeln wird nicht klassifiziert; Fehl-Routing an Frontend/QA | **Hoch** |
| **3** | `agents/team_directives.py` | Fehlende Direktive | Agenten instanziieren Async-Objekte global auf Modulebene | **Hoch** |
| **4** | `agents/orchestrator/verification.py` | Fehlender Modul-Import-Precheck | Fehlerhafte Modul-Einstiegspunkte werden erst im teuren Testlauf entdeckt | **Mittel** |
| **5** | `.env` / Budget-Logik | Strenge Budget-Deckelung | Große Fullstack-Projekte brechen bei 1M Tokens mitten in der Reparatur ab | **Mittel** |

---

## 3. Konkrete Handlungsempfehlungen & Quick-Fixes für das Framework

### 🛠️ Maßnahme 1: `agents/team_directives.py` um Async/Resilienz-Regel erweitern
In `agents/team_directives.py` und `agents/resilience_guard_agent.py` folgende Direktive ergänzen:
```python
_ASYNC_MODULE_LEVEL_RULE = """
## ⚡ Asynchroner Code & Event-Loop-Sicherheit
- Rufe NIEMALS `asyncio.get_event_loop()` auf Modulebene oder im `__init__` synchroner Klassen auf! In Python 3.10+ existiert beim Import kein Event-Loop.
- Verwende für Zeitmessungen, Cooldowns und Timeouts IMMER `time.monotonic()` statt `loop.time()`.
- Globale Singletons (wie Circuit Breaker oder HTTP-Clients) dürfen erst innerhalb von FastAPI-Lifespan-Handlern oder asynchronen Factory-Funktionen initialisiert werden.
"""
```

### 🛠️ Maßnahme 2: `core/failure_triage.py` um Import-Collection-Runtime-Errors erweitern
In `core/failure_triage.py` den Triage-Katalog um Modul-Level-RuntimeErrors erweitern:
```python
_MODULE_LEVEL_RUNTIME_ERROR_RE = re.compile(
    r"(?:RuntimeError: There is no current event loop|RuntimeError: Event loop is closed)",
    re.IGNORECASE,
)
```
Tritt dieser Fehler in `tests/` oder `app/` auf, wird sofort der verantwortliche Autor des Moduls (z. B. `resilience_guard` oder `backend`) mit dem konkreten Hinweis adressiert, `time.monotonic()` zu nutzen.

### 🛠️ Maßnahme 3: Vorab-Modul-Import-Check vor `pytest`
Vor dem Starten von `pytest` in `core/verifier/testrunner.py` einen einfachen Import aller `.py`-Dateien im Projektverzeichnis ausführen:
```python
python -c "import importlib; [importlib.import_module(...) for ...]"
```
Dadurch werden Modul-Level-Crashes innerhalb von Millisekunden erkannt, ohne dass die gesamte Pytest-Collection aufwendig anlaufen muss.

### 🛠️ Maßnahme 4: Dynamisches Puffer-Budget für finale Verifikation
Wenn ein Lauf bei 950.000 Tokens steht und sich bereits in der finalen Verifikation befindet (`_run_verification_loop`), sollte dem Fix-Loop ein einmaliges Resilienz-Kontingent von +150.000 Tokens gewährt werden, statt einen 12-minütigen Qualitätslauf 5% vor dem Ziel hart abzubrechen.
