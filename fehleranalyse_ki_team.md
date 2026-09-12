# 🔬 KI-Team Fehler- und Schwachstellenanalyse: CertPulse (Lauf 3)

**Datum/Uhrzeit:** 12.09.2026, 12:42–12:49 UTC (10:42–10:49 UTC)  
**Projekt:** CertPulse (`workspace/certpulse`)  
**Ziel:** Vollständige Implementierung des SSL/TLS-Monitoring-Services mit FastAPI, Dashboard und Testsuite  
**Ergebnis:** 🛑 **Abbruch (`budget_aborted: true`)** – 0 Quellcode-Dateien geschrieben, Tests übersprungen

---

## 📌 1. Executive Summary & Das Kern-Paradoxon

Im jüngsten Lauf wurden **319.244 Tokens** verbraucht, **36 Werkzeug-Aufrufe** getätigt und **11 Agenten-Schritte** ausgeführt. Alle Entwickler-Agenten meldeten formal `success: true`.

> [!CAUTION]
> **Das Kern-Paradoxon:** Trotz eines fast vollständig aufgebrauchten Token-Budgets (`323.977 / 350.000` Tokens = 93 %) wurde **keine einzige Anwendungs- oder Testdatei (`app/`, `tests/`) auf die Festplatte geschrieben**. Lediglich zwei statische CSS-Dateien (`dashboard.css`, `style.css`) wurden nachträglich per Regex-Text-Fallback aus einem Markdown-Antworttext gerettet.

Das gesamte Team verfing sich in einem **systematischen Teufelskreis aus Lese-Iterationen, einer Kontroll-Sperre in der letzten Iteration und einem Logikfehler im "Hard Delivery Gate"**, der den Fehlschlag vor dem Orchestrator verschleierte.

---

## 🔍 2. Detaillierte Befunde & Technische Ursachenanalyse

### Befund 1: Die "Premature Final Answer"-Falle im Tool-Loop (Kritischer Architekturfehler)

In [`agents/base_agent.py`](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/agents/base_agent.py#L272-L288) existiert folgender Schutzmechanismus:
```python
for iteration in range(1, max_iterations + 1):
    if iteration == max_iterations and max_iterations > 1:
        turns.append(AgentMessage(
            role="user",
            text=(
                "Dies ist deine LETZTE Gelegenheit zu antworten. Rufe KEIN weiteres "
                "Werkzeug mehr auf – liefere jetzt deine finale Textantwort basierend "
                "auf allem, was du bisher gesehen hast."
            ),
        ))
```

**Was real passierte:**
1. Der Entwickler-Agent (`backend`, `frontend`, `database`, `tester`) startet mit `max_iterations = 5`.
2. Das Prompting fordert ihn auf: *"Prüfe VOR jedem write_file, ob die gewünschte Funktionalität hier bereits existiert."*
3. Im Projekt lagen bereits 3 ADRs, `interface_contract.json` und `pytest.ini`.
4. Der Agent rief brav in Iteration 1 `read_file(adr/0001)`, in Iteration 2 `read_file(adr/0002)`, in Iteration 3 `read_file(adr/0003)` und in Iteration 4 `read_file(interface_contract.json)` auf.
5. In Iteration 5 (`iteration == max_iterations`) injizierte der Loop die strikte Anweisung: **"Rufe KEIN weiteres Werkzeug mehr auf – liefere jetzt deine finale Textantwort"**.
6. Der Agent gehorchte: Er rief kein `write_file` mehr auf, sondern schrieb seine Code-Implementierung als Fließtext/Markdown in seine finale Antwort.
7. **Ergebnis:** Der Agent hatte 4 Werkzeuge aufgerufen, war fleißig, durfte aber seinen Code niemals auf Platte speichern!

---

### Befund 2: Der Logikfehler im "Hard Delivery Gate" (Verschleierter Fehler)

Eigentlich soll das in [`agents/base_agent.py`](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/agents/base_agent.py#L330-L430) definierte **Hard Delivery Gate** genau verhindern, dass ein Entwickler ohne geschriebene Datei als erfolgreich gewertet wird. 

Hier liegt jedoch ein fataler Logikfehler im Zusammenspiel zweier Bedingungen:

```python
# Stufe 1: Verwarnung und Korrektur-Retry
elif (
    not response.tool_calls
    and iteration < max_iterations        # <-- FEHLERQUELLE A: In Iteration 5 ist das FALSE!
    and not no_file_written_retry_used
    and self.agent_id in CODE_WRITING_AGENT_IDS
    and not toolbox.files_written
    ...
):
    no_file_written_retry_used = True
    ...

# Stufe 2: Endgültige Bewertung als Fehlschlag
if (
    self.agent_id in CODE_WRITING_AGENT_IDS
    and not toolbox.files_written
    and not task.tools_read_only
    and not toolbox.clarification_requests
    and no_file_written_retry_used       # <-- FEHLERQUELLE B: Verlangt, dass Stufe 1 lief!
    and not text_has_extractable_file_blocks(response.text)
):
    hard_delivery_gate_failed = True
```

**Warum das Gate komplett umgangen wurde:**
* In den Iterationen 1 bis 4 gab es Tool-Calls (`not response.tool_calls` war `False`).
* In Iteration 5 gab es keinen Tool-Call mehr, aber `iteration < max_iterations` (`5 < 5`) war `False`.
* Dadurch wurde `no_file_written_retry_used = True` **niemals gesetzt**.
* In Stufe 2 verlangt die Bedingung jedoch zwingend `and no_file_written_retry_used`. Da dieser Flag `False` war, wurde `hard_delivery_gate_failed` **nicht auf `True` gesetzt**!
* Der Agent meldete `AgentResult(success=True, files_written=[])`. Der Orchestrator ging davon aus, dass alles bestens sei.

---

### Befund 3: Die Token-Explosion im zustandslosen Multi-Turn-Loop

Weil LLM-APIs (Gemini/Claude) zustandslos sind, wird bei jeder Iteration die **gesamte bisherige Gesprächshistorie inklusive aller Werkzeug-Rückgabewerte** erneut mitgesendet:

$$\text{Tokens pro Agent} = \sum_{i=1}^{n} (\text{Basiskontext} + \sum_{j=1}^{i-1} \text{Tool-Result}_j)$$

* Jeder Agent startete bereits mit einem üppigen Basiskontext (~10.000 Tokens: System-Prompt, Aufgabenstellung, Projekthistorie, Team-Lessons, ADRs).
* Jedes gelesene Dokument fügte ~1.500 bis 2.500 Tokens hinzu.
* Runde 1: ~10.000 Prompt-Tokens
* Runde 2: ~12.500 Prompt-Tokens
* Runde 3: ~15.000 Prompt-Tokens
* Runde 4: ~17.500 Prompt-Tokens
* **Pro Entwickler fielen so 42.000 bis 48.000 Tokens an.**
* Bei 7 Entwickler- und Support-Rollen ergab das: **$7 \times \approx 44.000 \approx 308.000$ Tokens**, ohne dass eine einzige Zeile Code existierte!

---

### Befund 4: Die Verifikations-Reserve-Falle (`generation_ceiling`)

In [`agents/orchestrator/budget.py`](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/agents/orchestrator/budget.py#L69-L71) wird berechnet:
$$\text{generation\_ceiling} = \text{MAX\_RUN\_TOKENS} \times (1.0 - \text{VERIFICATION\_TOKEN\_RESERVE\_RATIO})$$
$$350.000 \times (1.0 - 0.15) = 297.500\text{ Tokens}$$

* Sobald der QA-Tester fertig war, lag der Gesamtverbrauch bei **311.357 Tokens**.
* Damit war `generation_ceiling` (297.500) überschritten.
* Der Orchestrator brach den Lauf sofort mit `budget_aborted: true` ab.
* **Folge:** Phasen wie `design_lead` und `governance_lead` wurden übersprungen, und die Verifikation (`pytest`, Dependency-Install) wurde gar nicht erst gestartet.

---

## 📊 3. Ressourcen- und Rollen-Übersicht des Laufs

| KI-Agent | Rolle / Fachbereich | Modell | Dauer | Tokens | Tool-Calls | Dateien geschrieben | Realer Status |
|---|---|---|---|---|---|---|---|
| `dev_lead` | Teamleiter Dev | `gemini-3.6-flash` | 24.2s | 16.122 | 3 | 0 | Hat delegiert |
| `frontend` | Frontend-Entwickler | `gemini-3.6-flash` | 53.2s | 42.172 | 4 | 0 (2 per Text) | Nur gelesen, Code im Text |
| `backend` | Backend-Entwickler | `gemini-3.6-flash` | 68.8s | 48.022 | 4 | 0 | Nur gelesen, Code im Text |
| `database` | Datenbank-Entwickler | `gemini-3.6-flash` | 58.8s | 42.009 | 4 | 0 | Nur gelesen, Code im Text |
| `performance`| Performance-Ingenieur| `gemini-3.6-flash` | 61.6s | 39.960 | 4 | 0 | Nur analysiert |
| `dev_lead` | Teamleiter Dev | `gemini-3.6-flash` | 123.9s | 24.656 | 4 | 0 | Konsolidiert (leer!) |
| `content_lead`| Content Lead | `gemini-3.1-flash-lite` | 57.7s | 12.456 | 3 | 0 | Doku-Vorgaben |
| `accessibility`| A11y Specialist | `gemini-3.1-flash-lite` | 5.1s | 20.761 | 2 | 0 | HTML-Muster im Text |
| `qa_lead` | QA Lead | `gemini-3.1-flash-lite` | 53.9s | 12.880 | 3 | 0 | Testplan aufgestellt |
| `tester` | QA-Tester | `gemini-3.1-flash-lite` | 9.0s | 41.781 | 3 | 0 | Stopp: *"Kein Code in app/"* |
| `orchestrator`| Synthese | `claude-opus-5` | - | 7.887 | - | 0 | Budget-Abbruch |
| **Gesamt** | | | **420s** | **319.244** | **36** | **0** | **Abgebrochen** |

---

## 🛠️ 4. Schwachstellen & Lücken im Detail

### 1. Fehlende Priorisierung von Schreib-Aktionen im Prompt
Weder der System-Prompt noch der Task-Prompt sagen dem Entwickler:
> *"Deine Hauptaufgabe ist das SCHREIBEN von Code mit `write_file`. Verschwende maximal 1 Iteration zum Lesen. Spätestens in Iteration 2 MUSST du deine Zieldatei anlegen."*
Stattdessen lasen alle Entwickler dieselben ADR-Dateien wieder und wieder durch.

### 2. Redundante Leseoperationen trotz bereits vorhandenem Prompt-Kontext
Die Inhalte der ADRs und der Projektstatus wurden bereits über `format_adr_summary_for_context()` und `format_context_for_agents()` in den Initial-Prompt injiziert. Die Agenten riefen trotzdem per `read_file` exakt dieselben ADR-Dateien nochmals auf.

### 3. Degradierung des Modells bei QA-Tester
Der `tester` stufte sich von `gemini-3.6-flash` auf `gemini-3.1-flash-lite` ab. `gemini-3.1-flash-lite` neigt bei komplexeren Tests eher dazu, frühzeitig abzubrechen oder nur Textkommentare abzugeben, statt eigenständig Testdateien anzulegen.

---

## 🎯 5. Konkreter Maßnahmenplan (Roadmap)

### Stufe 1: Sofort-Fixes im Framework (Bugs)
1. **Hard Delivery Gate reparieren ([base_agent.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/agents/base_agent.py)):**
   Wenn `self.agent_id in CODE_WRITING_AGENT_IDS` und `toolbox.files_written` nach Beendigung des Loops leer ist, **muss** der Schritt als `hard_delivery_gate_failed = True` gewertet werden – völlig unabhängig davon, ob zuvor `no_file_written_retry_used` gesetzt wurde oder ob das Limit erreicht war.
2. **"Write First"-Regel im Agentic Loop ([base_agent.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/agents/base_agent.py)):**
   Vor Iteration `max_iterations` (z. B. in Iteration `max_iterations - 1`) muss der Agent gewarnt werden: *"Achtung: Du hast noch keine Datei geschrieben. Rufe in dieser Iteration zwingend `write_file` auf!"*
3. **Kontext-Redundanz unterbinden:**
   Dateien, deren Inhalt bereits im Kontext-Prompt steht (wie ADRs oder `interface_contract.json`), sollten im Prompt explizit mit dem Hinweis versehen werden: *"Der Inhalt von ADRs und Schnittstellen liegt dir oben bereits vollständig vor. Rufe dafür KEIN `read_file` auf."*

### Stufe 2: Budget- und Iterations-Tuning
1. **`MAX_RUN_TOKENS` auf 450.000 anheben** für vollwertige Fullstack-Projekte (350k reicht bei 11 Rollen knapp nicht, wenn 15% für die Verifikation reserviert sind).
2. **Entwickler-Iterations-Budget:**
   Code-schreibende Agenten bekommen 4 gezielte Iterationen:
   * Runde 1: Optional 1 gezielter Read.
   * Runde 2: Zwingend `write_file` (Hauptmodul).
   * Runde 3: Zwingend `write_file` (Begleitdateien/Submodule).
   * Runde 4: Abschlussbericht.

---

## 💡 6. Fazit
Das Scheitern des CertPulse-Laufs lag **nicht an fehlendem LLM-Wissen oder unzureichenden Prompts**, sondern an einer **technischen Blockade-Kette im Framework**: Die Agenten wurden durch die "Letzte Gelegenheit"-Meldung am Schreiben gehindert, das Sicherheits-Gate übersah den Fehler wegen einer fehlerhaften Bedingung, und die Token-Reserve brach den Lauf vorzeitig ab. Mit den oben skizzierten Korrekturen wird das Team in die Lage versetzt, CertPulse in einem einzigen, sauberen Durchlauf fehlerfrei auf die Platte zu schreiben.
