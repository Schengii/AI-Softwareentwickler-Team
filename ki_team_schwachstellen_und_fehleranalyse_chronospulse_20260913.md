# KI-Team Schwachstellen- und Fehleranalyse (Lauf: ChronosPulse)
**Datum:** 13. September 2026  
**Projekt:** ChronosPulse (Intelligente Observability- & Event-Streaming-Plattform)  
**Run-Log:** `logs/runs/20260913_102318_chronospulse.jsonl`  
**Status-Log:** `workspace/chronospulse/.ai_team_status_full.log`  

---

## 1. Management Summary & Kernergebnis

Beim Durchlauf von **ChronosPulse** band der Orchestrator erfolgreich nahezu das gesamte 30-köpfige Spezialistenteam über alle 6 Fachbereichs-Phasen ein. 
Es wurden **16 modulare Projektdateien** geschrieben (FastAPI SSE- & REST-Pipelines, Timeseries-Speicher, Webhooks, lokales EMA/Z-Score ML-Modell, Dockerfile, Locustfile, Testsuiten).

Trotz dieser starken Entwicklungsleistung schloss das Projekt mit **`verification_ok: false`** und **`budget_aborted: true`** ab. 
Die Kernursache dafür ist ein **gravierender Architektur-Bug in der Orchestrator-Steuerung**:
- Die Code-Generierungsphase stoppte bei Erreichen der Generation-Reserve (`MAX_RUN_TOKENS * (1 - VERIFICATION_TOKEN_RESERVE_RATIO) = 850.000 Tokens`). **Der Zweck dieser 15%-Reserve (150.000 Tokens) ist es laut Docstring ausdrücklich, Budget für die Verifikation freizuhalten!**
- **Der Bug:** `_run_department_hierarchy()` setzte dabei das Flag `budget_aborted = True`. Der Orchestrator in `agents/orchestrator/__init__.py:966` prüfte danach `elif budget_aborted or manually_cancelled:` und **übersprang die Verifikation komplett**!
- Dadurch wurde die reservierte Verifikation paradoxerweise durch genau die Reserve blockiert, die eigens für sie geschaffen wurde!

Zusätzlich traten 3 weitere konkrete Schwachstellen und Fehler im Team und Framework auf, die den Lauf beeinträchtigten:
1. **Fehlendes Code-Contract-Matching in `SecurityAgent` (`Hard Delivery Gate` Fehler)**
2. **Pytest Fixture-Crash (`conftest.py` vs. `app/ml/anomaly_detector.py`)**
3. **Unvollständige Implementierung von `app/utils/resilience.py` (Stub/Auszug)**

---

## 2. Detaillierte Fehleranalyse & Schwachstellen

### Schwachstelle 1: Der "Verification Reserve Paradox"-Bug im Orchestrator
* **Symptom:**
  ```text
  Status: budget_aborted
  Verifikations-Protokoll:
  - 🚫 Übersprungen: Lauf-Budget (MAX_RUN_TOKENS=1,000,000) wurde bereits während der Fachbereichs-Phasen oder der Governance-Fix-Schleife erreicht.
  ```
  Im Run-Log: `total_tokens: 852.222` (von 1.000.000!). Es waren noch knapp **150.000 Tokens übrig**!
* **Ursache im Framework ([agents/orchestrator/department.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/agents/orchestrator/department.py) & [agents/orchestrator/__init__.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/agents/orchestrator/__init__.py)):**
  - In `config.py` ist `VERIFICATION_TOKEN_RESERVE_RATIO = 0.15` definiert.
  - In `department.py:286` wird `self._generation_budget_exceeded()` geprüft (Schwellwert 850.000 Tokens). Sobald 850k Tokens erreicht sind, bricht die Fachbereichs-Phase ab und setzt `budget_aborted = True`.
  - Der Docstring in `budget.py:78` sagt wörtlich:
    > *"prüft gegen ein um VERIFICATION_TOKEN_RESERVE_RATIO reduziertes Kontingent, damit die anschließende Verifikations-/Fix-Phase garantiert noch Budget übrig hat..."*
  - **Der Fatale Fehler in `agents/orchestrator/__init__.py:966`:**
    ```python
    elif budget_aborted or manually_cancelled:
        # Hier wird die Verifikation KOMPLETT ÜBERSPRUNGEN, weil budget_aborted == True ist!
    ```
  - `department.py` muss unterscheiden zwischen `generation_budget_reached` (Generierung beendet, um Budget für Verifikation zu schonen) und echtem `run_budget_exceeded` (Gesamtlauf hat kein Token mehr). Durch die Gleichsetzung wird die Verifikation niemals ausgeführt, wenn die Generierungsreserve greift!

---

### Schwachstelle 2: Fehlende Datei-Generierung durch `SecurityAgent` (Hard Delivery Gate)
* **Symptom:**
  ```json
  "agent_id": "security", "success": false,
  "failure_class": "agent_error",
  "error": "Hard Delivery Gate: Agent hat trotz Korrektur-Hinweis keine einzige Datei über write_file/edit_file gespeichert - der Tokenverbrauch ist verpufft."
  ```
  Dauer: **147.9 Sekunden**, verbrauchte **56.171 Tokens komplett umsonst**.
* **Ursache im Agenten-Design ([agents/base_agent.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/agents/base_agent.py) & [agents/security_agent.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/agents/security_agent.py)):**
  - In `base_agent.py:61` ist `"security"` in `CODE_WRITING_AGENT_IDS` eingetragen. Das System verlangt zwingend, dass er Dateien per `write_file` schreibt.
  - Doch im System-Prompt von `SecurityAgent` ([agents/security_agent.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/agents/security_agent.py)) heißt es:
    ```text
    Ausgabe-Format:
    - Strukturierter Security-Report mit Findings
    - Schweregrad-Bewertung
    - Konkrete Code-Fixes mit Vorher/Nachher-Vergleich
    ```
  - Der Prompt weist den Agenten nirgends an, eine konkrete Datei (z. B. `SECURITY_AUDIT.md`, `app/core/security.py` oder `security_report.json`) per `write_file` anzulegen! Er erzeugt daher den Report als reinen Text. Das Hard Delivery Gate fängt dies ab, schickt einen Korrekturhinweis, der Agent versteht nicht, wohin er schreiben soll, und scheitert nach 56k Tokens hart.
  - **Lösung:** Entweder `security` aus `CODE_WRITING_AGENT_IDS` entfernen (wenn er nur auditiert) ODER seinen System-Prompt explizit anweisen, `docs/SECURITY_AUDIT.md` (oder `app/core/security.py`) per `write_file` zu schreiben.

---

### Schwachstelle 3: Schnittstellen-Bruch in Tests (`conftest.py` vs. `app/ml/anomaly_detector.py`)
* **Symptom:** Beim manuellen Ausführen von `pytest workspace/chronospulse/tests/test_api.py`:
  ```text
  ERROR workspace/chronospulse/tests/test_api.py::test_smoke_health_check
  conftest.py:20: AttributeError: 'AnomalyDetector' object has no attribute 'baselines'
  ```
* **Ursache:**
  - `tester` hat in `conftest.py` in der Fixture `client()` die Zeile `anomaly_detector.baselines.clear()` eingebaut.
  - `ml` hat in `app/ml/anomaly_detector.py` das Attribut jedoch `self.state: Dict[str, Tuple[float, float]] = {}` genannt.
  - Dieser klassische Typ- bzw. Schnittstellen-Drift zwischen zwei Agenten wird normalerweise durch den statischen Pre-Flight-/Pre-Import-Check bzw. die Verifikationsschleife sofort aufgedeckt und automatisch behoben. Da die Verifikation wegen Schwachstelle 1 übersprungen wurde, blieb dieser Fehler unkorrigiert.

---

### Schwachstelle 4: Stub/Fragment-Lieferung durch `resilience_guard`
* **Symptom:** Beim Ausführen von `test_resilience.py`:
  ```text
  ImportError: cannot import name 'CircuitBreaker' from 'app.utils.resilience'
  ```
  Ein Blick in `app/utils/resilience.py` zeigt:
  ```python
  # Auszug aus app/utils/resilience.py
  # - CircuitBreaker: Statusverwaltung (CLOSED, OPEN, HALF_OPEN), Failure Thresholds, Cooldown
  # - ExponentialBackoff: Full-Jitter mit secrets.SystemRandom() gegen Thundering Herd
  ```
  Die Datei besteht nur aus 5 Zeilen Kommentar!
* **Ursache:**
  - `resilience_guard` hat in seiner Werkzeug-Iteration nur einen Entwurf/Auszug als Kommentar gespeichert oder die Datei unvollständig hinterlassen, statt die vollständige Klassen-Implementierung von `CircuitBreaker`, `CircuitState` und `ExponentialBackoff` abzulegen.
  - Der Vollständigkeits-Check (`core/verifier/completeness.py`) hätte dies als Stub entlarvt, wenn die Verifikation gestartet worden wäre.

---

## 3. Gegenüberstellung & Kernproblem

| Komponente | Erwartung | Realität im Lauf | Ursache |
|---|---|---|---|
| **Verifikation** | Startet mit 150k Rest-Tokens | 🚫 Komplett übersprungen | Fälschlicher Abbruch in `__init__.py:966` bei `generation_budget_exceeded` |
| **Security Agent** | Liefert Security-Audit | ❌ 56k Tokens verbrannt | Widerspruch: `CODE_WRITING_AGENT_IDS` vs. Text-Report im Prompt |
| **Resilience & ML** | Echte Implementierung | ⚠️ Fragment / Attribut-Drift | Nicht durch Fix-Loop repariert, da Verifikation blockiert war |

---

## 4. Empfohlene Maßnahmen für das Framework

1. **Entkopplung von Generierungs-Stop und Verifikations-Abbruch ([agents/orchestrator/__init__.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/agents/orchestrator/__init__.py) & [agents/orchestrator/department.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/agents/orchestrator/department.py)):**
   - `_run_department_hierarchy()` darf nicht pauschal `budget_aborted = True` zurückgeben, wenn nur die Generation-Reserve (`_generation_budget_exceeded`) erreicht wurde, sondern z. B. `generation_budget_reached = True`.
   - In `__init__.py` darf `generation_budget_reached` **nicht** dazu führen, dass die Verifikation übersprungen wird. Die Verifikation MUSS mit dem verbleibenden Rest-Budget (den 15% bzw. 150.000 Tokens) regulär ausgeführt werden!
2. **Klarer Kontrakt für `SecurityAgent` ([agents/security_agent.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/agents/security_agent.py)):**
   - Im System-Prompt von `SecurityAgent` klar vorgeben: "Speichere deinen vollständigen Audit-Bericht IMMER per `write_file` in `docs/SECURITY_AUDIT.md` (und eventuelle Security-Middleware in `app/core/security.py`)."
3. **Schutz vor Pseudo-Dateien ("Auszug aus..."):**
   - Im Stub-Detector von `completeness.py` bzw. `base_agent.py` Dateien abfangen, die mit `# Auszug aus...` oder weniger als 10 Zeilen reinem Kommentar beginnen.
