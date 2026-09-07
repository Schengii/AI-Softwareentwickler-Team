# 🔍 KI-Team Analyse & Verbesserungsempfehlungen
> Basierend auf CHANGELOG.md, team_lessons.jsonl, ZWISCHENSTAND & Codestruktur (Stand: 07.09.2026)

> [!NOTE]
> **Umsetzungsstatus (07.09.2026, im Rahmen dieser Analyse direkt umgesetzt):**
> - ✅ Punkt 1 (Governance-Anti-Pattern-Checkliste) → `agents/backend_agent.py`
> - ✅ Punkt 2 (Tester-Prompt Top-Fehlermuster) → `agents/tester_agent.py`
> - ✅ Punkt 3 (Semantischer README↔Implementierung-Abgleich) → `core/verifier/completeness.py._readme_endpoints_not_implemented()`
> - ✅ Punkt 4 (Echte Testaufgaben für unterausgelastete Agenten) → 3 neue `evals/tasks.py`-Referenzaufgaben
> - ✅ Punkt 5 (Fake-Model aus Optimierungsberechnung ausfiltern) → `memory/run_history.py._is_real_run()`
> - ✅ Punkt 6 (Acceptance-Criteria-Prüfung) – Basisversion (Synthese-Prompt-Ergänzung) war bereits vorhanden (`core/result_aggregator.py`); ein vollständiger, mechanischer Checklisten-Abgleich in `completeness.py` ist NICHT Teil dieser Runde (höheres Risiko für Fehlalarme, siehe Session-Notizen)
> - ✅ Punkt 7 (MockObject-Leck) – bei Prüfung bereits behoben vorgefunden, keine Regression
> - ✅ Punkt 8 (Post-Deploy-Health-Check) → `core/production_monitor.wait_for_health()`, verdrahtet in CLI & Dashboard
> - ✅ Punkt 9 (Interoperabilitäts-Check zwischen Projekten) → `core/contract_verifier.verify_cross_project_contract()` + `/check-interop`
> - ✅ Punkt 10 (Nutzer-Feedback-Loop) → `/feedback`-Befehl, schreibt in `memory/team_lessons.jsonl`
>
> Vollständige Testsuite (1404 Tests) läuft grün, `ruff check` sauber.

---

## 🧭 Kurzfazit

Das Team ist **technisch bereits weit fortgeschritten** – Circuit-Breaker, RAG, Sandbox-Validation, Auto-Lint-Fix, Completeness-Check, Goal-Loop mit Stagnationserkennung uvm. sind implementiert. Die **echten Schwachstellen liegen jetzt auf drei Ebenen**:

1. Wiederkehrende Governance-Fehler im generierten Code werden nicht dauerhaft geheilt
2. Mehrere Agentenrollen arbeiten faktisch nie (Unterauslastung)
3. Orchestrator-/Tester-Qualität ist messbar unter dem Team-Durchschnitt

---

## 🔴 Kritische Baustellen (sofort angehen)

### 1. Tester-Agent: Erfolgsquote 57 % – dauerhaft unter Team-Schnitt
**Was passiert:** Das System meldet seit mindestens 15+ Zyklen unverändert  
> *"tester: Erfolgsquote 57.1% über 7 Aufrufe, deutlich unter dem Team-Durchschnitt (85.7%)"*

**Ursachen (aus Changelog analysiert):**
- `pytest` fehlte in der Umgebung → stille „Ran 0 tests"-Fehler
- Tests mocken externe Netzwerkaufrufe nicht → schlagen in isolierter Sandbox fehl
- Test-Code benutzt Elision (`# ... Imports`) statt echte Implementierung

**Was noch fehlt:**
- Die Selbstoptimierungsvorschläge bleiben **rein informativ** – sie lösen keinen Prompt-Update aus
- Kein automatischer A/B-Test zwischen zwei Prompt-Varianten des Testers

> [!IMPORTANT]
> Empfehlung: Den Tester-Agent-Prompt **konkret um die 3 häufigsten Fehlerkategorien** aus `team_lessons.jsonl` erweitern. Derzeit sind das: fehlende `__init__.py` in `tests/`, ungemockte External-Calls, Import-Zirkel.

---

### 2. Governance-Kritische Befunde wiederholen sich projekt-übergreifend
**Aus `team_lessons.jsonl`** – über 10 von 31 Einträgen sind `unresolved_governance_critical` – und **dieselben Kategorien** tauchen immer wieder auf:

| Wiederkehrendes Muster | Projekte betroffen |
|---|---|
| Fehlende Router/Module importiert aber nicht erstellt | zeiterfassung, taskpulse, feature_pilot |
| Async/Sync Engine-Mismatch (SQLAlchemy) | logpulse, mockforge |
| CORS/TrustedHost-Konfiguration fehlt/falsch | taskboard, fleet_telemetry |
| Middleware-Klassen-Import-Fehler (Name ≠ Klasse) | zeiterfassung, event_relay |

**Was noch fehlt:**  
- Ein **"Governance-Pattern-Bibliothekar"**: Häufige kritische Befunde werden noch nicht als **Coding-Regeln in den Backend-/Frontend-Agent-Prompt** rückgekoppelt
- Es gibt `team_lessons.jsonl`, aber der Backend-Agent bekommt diese Muster nicht automatisch als Negativbeispiel-Liste bei jedem Start

> [!WARNING]
> Empfehlung: Injiziere die **Top-5 wiederkehrenden Governance-Muster** aus `team_lessons.jsonl` in den Backend-Agent-Systemprompt als "Anti-Pattern Checkliste". Dieser eine Schritt würde vermutlich 40 % der governance-kritischen Wiederholungsfehler eliminieren.

---

## 🟡 Mittelfristige Optimierungen (nächste 1-2 Wochen)

### 3. Stub-Completeness-Check: „Tests grün ≠ Feature fertig"
Das Problem wurde erkannt und ein `completeness.py`-Check gebaut. **Noch offen:**
- Der Check sucht nach deutschen/englischen Platzhaltern im Code – aber er erkennt **keine logisch unvollständigen Implementierungen** (z. B. eine Funktion, die `return {}` macht, aber laut README ein verschlüsseltes Objekt zurückgeben soll)
- **Fehlt:** Semantischer Check: README → API-Endpunkte → Implementierung abgleichen (ob Endpunkte aus dem README auch wirklich vorhanden sind)

### 4. Unterauslastete Agenten – 10 von 33 faktisch nie eingesetzt
Aus `team_lessons.jsonl` (06.09.): Nie eingesetzt in 100 Läufen:
`accessibility`, `copywriter`, `data_engineer`, `finops`, `i18n`, `image_generator`, `ml`, `mobile`, `performance`, `prompt_engineer`, `web_research`

**Bereits getan:** Planer-Beschreibungen konkretisiert, neue Eval-Aufgaben (FAQ-RAG-Chatbot).  
**Noch offen:**
- Gibt es **echte Testaufgaben** für `mobile`, `i18n`, `data_engineer`, `image_generator`?
- Gibt es einen **Mechanismus**, der den Planer sanft "ermutigt", diese Rollen mindestens 1x pro N Läufen zu wählen?
- Der `/apply-tuning`-Befehl existiert – aber gibt es eine **automatische Warnung**, wenn eine Rolle nach weiteren 20 Läufen immer noch nie gewählt wird?

### 5. Fake-Model in Testzyklen – kein echter Lerneffekt
In der `ZWISCHENSTAND`-Datei: Fast alle Zyklen 1–15 laufen mit `fake-model` und produzieren `0 Tool-Calls`, `0 Dateien geschrieben`. Das sind **Dummy-Testläufe**, die für das echte Optimierungs-Gedächtnis nichts beitragen.

> [!NOTE]
> Empfehlung: Trenne in der `run_history.json` klar zwischen **echten Läufen** (mit echtem Modell und >0 Tool-Calls) und Unit-Test-Runs. Optimierungsvorschläge sollten nur aus echten Läufen berechnet werden.

---

## 🟢 Wachstumspotenzial (längerfristig)

### 6. Kein strukturierter "Done-Kriterien"-Vertrag zwischen Auftraggeber und Agenten
**Problem:** Aufgaben wie "Baue etwas" oder "Verbessere das Projekt" sind für das Team zu vage. Es fehlt ein strukturierter **Acceptance-Criteria-Check**:
- Was gilt als "fertig"?
- Wurden alle genannten Endpunkte implementiert?
- Schlägt der Smoke-Test mit echten Daten an?

**Empfehlung:** Ein neuer Schritt nach der Planung: Der `product_owner`-Agent extrahiert aus dem Nutzer-Prompt automatisch **messbare Acceptance Criteria** als Checkliste, die am Ende von `completeness.py` geprüft wird.

### 7. MockObject-Leak im Verifikationsprotokoll
Aus `ZWISCHENSTAND` Zyklen 6, 12–16: Protokollzeilen wie:
```
MagicMock name='ProjectVerifier().check_browser_ui().tested_url' id='206...'
```
Das bedeutet: **Mock-Objekte laufen in echten Verifikations-Reports durch**, obwohl sie eigentlich nur in Tests verwendet werden sollen. Das ist ein Test-Isolation-Bug, der dazu führt, dass scheinbar erfolgreiche Checks (`fehlerfrei`, `keine WCAG-Verstöße`) auf Mock-Basis bestehen, nicht auf echter Basis.

> [!CAUTION]
> Das ist ein kritischer Zuverlässigkeitsfehler: Das Team glaubt, es hat Accessibility- und Browser-Checks bestanden – aber in Wirklichkeit wurde nie wirklich gecheckt.

### 8. Kein Deployment-Validierungsschritt
Das Team kann Cloud-Deployments anlegen (Fly.io, Vercel, Render), aber es gibt **keinen automatischen Post-Deploy-Health-Check**:
- Ist der Service erreichbar?
- Antworten die Endpunkte HTTP 200?
- Funktioniert das Frontend nach dem Deploy wirklich?

### 9. Fehlende Interoperabilitäts-Tests zwischen generierten Projekten
Bisher arbeitet jedes Workspace-Projekt isoliert. Im realen Entwicklungsalltag müssen Microservices **miteinander kommunizieren**. Ein Test, ob zwei generierte Projekte korrekt zusammenarbeiten (z. B. event_relay → Kafka → taskpulse), fehlt völlig.

### 10. Kein strukturiertes Feedback-System vom Nutzer zurück ans Team
Aktuell läuft alles **in eine Richtung**: Das Team produziert, du begutachtest. Es gibt keinen formalisierten Weg, Feedback wie "Diese Lösung war gut, merke dir das Muster" oder "Diese Entscheidung war falsch, lerne daraus" direkt in die `team_lessons.jsonl` zu schreiben.

---

## 📊 Priorisierte Maßnahmen-Tabelle

| Priorität | Maßnahme | Aufwand | Wirkung |
|---|---|---|---|
| 🔴 1 | Governance-Anti-Pattern als Backend-Prompt-Regeln | Klein | Sehr hoch |
| 🔴 2 | Tester-Prompt mit Top-3-Fehlermuster erweitern | Klein | Hoch |
| 🟡 3 | MockObject-Leak in Verifikationsprotokoll beheben | Mittel | Hoch |
| 🟡 4 | Fake-Model aus Optimierungsberechnung ausfiltern | Klein | Mittel |
| 🟡 5 | Semantischer README→Implementierungs-Abgleich | Mittel | Mittel |
| 🟡 6 | Acceptance-Criteria-Extraktion (product_owner) | Mittel | Hoch |
| 🟢 7 | Unterauslastete Agenten: echte Testaufgaben | Mittel | Mittel |
| 🟢 8 | Post-Deploy-Health-Check | Groß | Mittel |
| 🟢 9 | Nutzer-Feedback-Loop in team_lessons.jsonl | Klein | Hoch (langfristig) |
| 🟢 10 | Multi-Projekt-Interoperabilitätstests | Groß | Mittel |
