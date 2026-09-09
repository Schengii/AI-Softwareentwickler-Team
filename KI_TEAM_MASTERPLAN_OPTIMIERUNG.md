# 🏗️ KI-Team – Masterplan zur Weiterentwicklung zum vollwertigen Softwareentwickler-Team

**Stand:** 09.09.2026
**Analysebasis:** 200 Läufe (`memory/run_history.json`), 5.368 LLM-Calls (`memory/cost_history.json`), 50 Benchmark-Läufe (`evals/eval_history.json`), 36 Team-Lessons, 1.504 Framework-Tests, Live-Tests gegen die echten Provider-APIs
**Scope:** Ausschließlich das Framework – **nicht** die generierten Projekte in `workspace/`

---

## 🧭 Executive Summary

Das Framework selbst ist in bemerkenswert gutem Zustand: **1.504 Tests laufen grün, `ruff check` ist sauber**, die Architektur (33 Rollen, 6 Fachbereichsleiter, Verifikations-Schleife, Backlog, ADRs, Obsidian-Gedächtnis) ist vollständiger als bei den meisten kommerziellen Agenten-Frameworks.

**Trotzdem liegt die Verifikationsrate echter Projekte bei ~20–31 %.** Die Analyse zeigt: Das liegt **nicht primär an schwachen Prompts oder fehlenden Features**, sondern an drei operativen Defekten, die zusammen dafür sorgen, dass das Team faktisch etwas völlig anderes tut, als die Konfiguration behauptet:

> [!CAUTION]
> **Die drei Kernbefunde in einem Satz:**
> 1. **Das ganze Modell-Tiering ist zur Laufzeit wirkungslos** – 82 % aller Calls laufen auf dem schwächsten Modell, obwohl HEAVY-Rollen auf Sonnet/Opus konfiguriert sind.
> 2. **Die Telemetrie protokolliert Modelle, die nie gelaufen sind** – dadurch optimiert sich das Team anhand falscher Daten selbst.
> 3. **Der Benchmark kann strukturell nicht durchfallen** – 50 von 50 Eval-Läufen "bestanden", mit 0 Tokens.

Solange diese drei Punkte offen sind, ist **jede weitere Prompt- oder Feature-Optimierung Messrauschen**: Man verbessert einen Agenten, der ohnehin auf einem Notfall-Fallback-Modell läuft, und misst das Ergebnis mit einem Benchmark, der immer grün zeigt.

---

## 📊 Teil 1 – Die harten Zahlen

### 1.1 Was wirklich rechnet (5.368 Calls, `memory/cost_history.json`)

| Modell | Calls | Anteil | Tokens | Prompt : Completion |
|:--|--:|--:|--:|:--|
| **`gemini-3.1-flash-lite`** | **4.380** | **81,6 %** | **21,9 M** | **25 : 1** |
| `groq:openai/gpt-oss-120b` | 385 | 7,2 % | 1,5 M | 6,8 : 1 |
| `gemini-3.6-flash` | 297 | 5,5 % | 1,3 M | 10 : 1 |
| `openrouter/auto` | 210 | 3,9 % | 1,7 M | 6,2 : 1 |
| `gemini-3.8-flash` | 96 | 1,8 % | 0,44 M | 47 : 1 |
| **`claude-sonnet-5` / `claude-opus-5`** | **0** | **0 %** | **0** | – |

> [!IMPORTANT]
> **Claude taucht in der Kostenhistorie kein einziges Mal auf.** Es gibt keinen einzigen echten Claude-Call – obwohl 13 Rollen (`architect`, `backend`, `database`, `security`, `code_reviewer`, `refactoring`, `compliance`, `ml`, `prompt_engineer`, `agent_trainer`, `planning_lead`, `dev_lead`, `governance_lead`) **und der Orchestrator** darauf konfiguriert sind.

### 1.2 Erfolgsquote nach protokolliertem Modell (alle 200 Läufe)

| Protokolliertes Modell | Erfolge | Fehler | Erfolgsquote |
|:--|--:|--:|--:|
| `gemini-3.1-flash-lite` | 1.107 | 16 | **98,6 %** |
| `groq:openai/gpt-oss-120b` | 79 | 10 | 88,8 % |
| `openrouter/auto` | 44 | 0 | 100 % |
| `gemini-3.6-flash` | 44 | 38 | 53,7 % |
| **`gemini-3.8-flash`** (STANDARD-Stufe) | **6** | **64** | **8,6 %** 🔴 |
| **`claude-sonnet-5`** (HEAVY-Stufe) | **0** | **160** | **0,0 %** 🔴 |

**Lesart:** Die beiden Stufen, die für alle anspruchsvollen Aufgaben zuständig sind, schlagen praktisch immer fehl. Die gesamte reale Arbeit erledigt `flash-lite` – das Modell, das laut `config.py` ausdrücklich nur für *"kleine, klar umrissene Aufgaben"* wie `readme`, `github` und `project_cleaner` gedacht ist.

### 1.3 Agenten-Erfolgsquoten (letzte 30 Läufe)

| Agent | Calls | Erfolgsquote | Einordnung |
|:--|--:|--:|:--|
| `tester` | 78 | **65,4 %** | 🔴 Meistgerufen + schwächster Kern-Agent |
| `architect` | 19 | **68,4 %** | 🔴 Fundament-Rolle |
| `backend` | 53 | **73,6 %** | 🔴 Kern-Rolle |
| `qa_lead` | 57 | 75,4 % | 🟡 |
| `governance_lead` | 50 | 76,0 % | 🟡 |
| `security` | 42 | 76,2 % | 🟡 |
| `dev_lead` | 51 | 78,4 % | 🟡 |
| `code_reviewer` | 57 | 78,9 % | 🟡 |
| `frontend` | 43 | 81,4 % | 🟡 |

> Auffällig: Die schlechtesten Quoten haben **exakt die Rollen, die auf HEAVY (Claude) konfiguriert sind** – also die, deren Primärmodell zu 100 % ausfällt. Die Rollen auf LITE (`project_cleaner` 90 %, `api_integration` 86 %, `github` 86 %) schneiden am besten ab. **Das ist kein Prompt-Problem, das ist ein Infrastruktur-Problem.**

### 1.4 Token-Verbrennung ohne Ergebnis (letzte 16 echte Läufe)

| Datum | Projekt | Tokens | Verifiziert |
|:--|:--|--:|:--|
| 08.09. | `opspilot` | 1.038.910 | ❌ |
| 09.09. | `agent_governance` | 999.313 | ❌ |
| 07.09. | `taskboard` | 915.532 | ✅ |
| 09.09. | `devops_agent_dashboard` | 705.810 | ❌ |
| 09.09. | `devops_agent_dashboard` | 640.332 | ❌ |
| 08.09. | `opspilot` | 564.201 | ❌ |
| … | … | … | … |
| 09.09. | `event_ticket_api` | 8.193 | ❌ (19 von 21 Agenten gescheitert) |

**Die letzten 16 echten Läufe sind ausnahmslos gescheitert.** Zusammen ~7,5 Mio. Tokens ohne ein einziges verifiziertes Ergebnis.

---

## 🔴 Teil 2 – Die kritischen Defekte (mit Code-Beleg)

### 🔴 D1 – Das Modell-Tiering existiert zur Laufzeit nicht

**Beleg (Live-Test gegen die echten APIs, heute ausgeführt):**

```
HEAVY_MODEL    = claude-sonnet-5   → tatsächlich geantwortet: groq:openai/gpt-oss-120b
STANDARD_MODEL = gemini-3.8-flash  → tatsächlich geantwortet: groq:openai/gpt-oss-120b
LITE_MODEL     = gemini-3.1-flash-lite → tatsächlich geantwortet: groq:openai/gpt-oss-120b
```

**Alle drei Stufen kollabieren auf dasselbe Modell.** Die sorgfältig gepflegte Zuordnung in [config.py:77-140](config.py#L77) hat zur Laufzeit **null Wirkung**.

**Ursachen (zwei, unabhängig voneinander):**

1. **`ANTHROPIC_API_KEY` ist leer** (`.env` verifiziert). `HEAVY_MODEL = CLAUDE_STANDARD_MODEL` ([config.py:71](config.py#L71)). Damit hat **keine einzige HEAVY-Rolle ein funktionierendes Primärmodell** – jede fällt über `ClaudeClient._free_heavy_fallback_client()` ([core/llm_factory.py:1060](core/llm_factory.py#L1060)) auf Groq/DeepSeek/OpenRouter oder am Ende auf die Gemini-Standardstufe.
2. **Stille Zweitabwertung im `GeminiClient`.** Selbst mit `_allow_self_fallback=False` liefert `gemini-3.8-flash` eine Antwort von `gemini-3.6-flash`, und `gemini-3.6-flash` eine von `gemini-3.1-flash-lite`. Es gibt also **eine zweite Abwertungsebene, die den Fallback-Schalter ignoriert** – dadurch merkt der Aufrufer nie, dass er ein schwächeres Modell bekommen hat.

**Maßnahme (P0):**
- **Realistische Primärmodelle konfigurieren.** Ohne Anthropic-Guthaben darf `HEAVY_MODEL` nicht auf Claude zeigen. Setze `HEAVY_MODEL` auf ein Modell mit echtem Kontingent (`gemini-pro-latest` oder `groq:openai/gpt-oss-120b`) und behalte Claude nur als *optionalen* Fallback, der aktiv wird, sobald ein Key hinterlegt ist.
- **Effektives Modell zurückmelden.** `GeminiClient` muss bei jeder stillen Abwertung das *tatsächlich* genutzte Modell in `LLMResponse.model_name` schreiben **und** den Downgrade sichtbar loggen.
- **Start-Preflight einführen:** Beim Start von `main.py` einmalig jeden konfigurierten Tier-Primärmodell mit einem 1-Token-Ping prüfen und dem Nutzer eine ehrliche Tabelle zeigen (`HEAVY → tatsächlich X`). Ein Team, das nicht weiß, mit welchen Modellen es arbeitet, kann sich nicht selbst optimieren.

---

### 🔴 D2 – Die Telemetrie protokolliert Modelle, die nie gelaufen sind

In [agents/base_agent.py:141](agents/base_agent.py#L141) wird im **Fehlerpfad** geschrieben:

```python
model_used=self._llm.model_name,   # ← das KONFIGURIERTE Modell, nicht das ausgeführte
```

Im Erfolgspfad steht korrekt `response.model_name` (das echte Modell). Konsequenz:

- **Erfolge** werden dem echten Modell zugeschrieben (`flash-lite`),
- **Fehler** dem konfigurierten Modell (`claude-sonnet-5`),

und genau deshalb zeigt die Statistik `claude-sonnet-5: 0 Erfolge / 160 Fehler` für ein Modell, das **nie einen einzigen Call gemacht hat**.

**Folgeschaden – und das ist der eigentliche Punkt:** Der `optimization_advisor` und die Retrospektive ziehen aus diesen Daten Schlüsse. In `memory/team_lessons.jsonl` steht bereits:

> `"Agent 'ml' (Modell 'claude-sonnet-5') wurde über die letzten 100 Läufe kein einziges Mal genutzt"`
> `"Agent 'tester' liegt mit 57.1% Erfolgsquote deutlich unter dem Durchschnitt"`
> `"Agent 'accessibility' liegt mit 60.0% Erfolgsquote deutlich unter dem Durchschnitt"`

Diese "Erkenntnisse" messen **API-Kontingent-Ausfälle, keine Qualitätsprobleme**. Das Team schreibt sich also Lernregeln und Modell-Umstufungen auf Basis von Rate-Limit-Fehlern. **Der Selbstoptimierungs-Kreislauf läuft derzeit auf vergiftete Daten.**

**Maßnahme (P0):**
- Im Fehlerpfad `model_used` nur setzen, wenn das Modell tatsächlich kontaktiert wurde; sonst `""` bzw. ein Marker `"nicht-erreicht"`.
- `AgentResult` um `failure_class` erweitern (`provider_exhausted` / `provider_unavailable` / `agent_error` / `timeout`).
- **Alle Auswertungen** (`optimization_advisor`, `team_retro`, `run_history.py`) müssen `provider_exhausted`-Fehler **aus den Erfolgsquoten herausrechnen**. Ein Agent, der wegen 429 nicht laufen konnte, hat nicht "versagt".

---

### 🔴 D3 – Der Benchmark kann strukturell nicht durchfallen

`evals/eval_history.json`: **50 Läufe, 50× dieselbe Micro-Task `fastapi_ping`, 50× bestanden, 50× `total_tokens: 0`.**

Drei echte Bugs in [evals/runner.py:119-181](evals/runner.py#L119):

1. **`total_tokens = 0` wird initialisiert und nie zugewiesen** (Zeile 134). Jeder Benchmark-Report weist 0 Tokens aus – die Kennzahl ist tot.
2. **`verification_ok` ist ein Substring-Match:**
   ```python
   verification_ok = "✅ Verifikation erfolgreich" in result_text or "🧪 Verifikations-Protokoll" in result_text
   ```
   Der zweite String steht in **jedem** Report – auch in gescheiterten. Beleg: `workspace/event_ticket_api/.ai_team_status.json` enthält bei `verification_ok: false` wörtlich `"### 🧪 Verifikations-Protokoll …"`. **`verification_ok` ist damit praktisch immer `True`.**
3. **Datei-Existenzprüfung gegen ein persistentes Verzeichnis.** `workspace.get_project_dir(...)` wird zwischen Läufen nicht geleert – Dateien aus einem früheren Lauf lassen einen späteren, gescheiterten Lauf bestehen.

**Maßnahme (P0):**
- `verification_ok` aus dem **strukturierten** Verifikationsergebnis übernehmen (das `Verifier`-Objekt liefert es bereits), nie aus Report-Text parsen.
- `total_tokens` aus dem Orchestrator-Ergebnis durchreichen.
- Jede Benchmark-Task in ein **frisches, temporäres Workspace-Verzeichnis** ausführen.
- Benchmark-Katalog erweitern: aktuell wird nur die `micro`-Task gefahren. Mindestens eine `api`-, eine `cli`- und eine `fullstack`-Task müssen bei jedem Regressionslauf mitlaufen – sonst misst der Benchmark genau die Klasse von Projekten nicht, die scheitert.

---

### 🟠 D4 – Kein Hard-Stop bei Massen-Ausfall

`core/provider_exhaustion.py` erkennt Kontingent-Erschöpfung korrekt, und `dispatch.py:76` markiert sie für den Rest des Laufs. **Aber der Lauf wird nicht abgebrochen.**

Beleg – Lauf `event_ticket_api` vom 09.09. 14:43:

```json
"verification_ok": false,
"budget_aborted": false,
"files_written_count": 0
```
bei **21 Agenten, davon 19 gescheitert, 8.193 Tokens.**

Das Team hat trotzdem: alle Phasen durchlaufen, die Verifikation gestartet, einen Fix-Auftrag an `tester` dispatcht (`.ai_team_decisions.jsonl`: `missing_tests_fix_dispatched`), `PROJECT_STATE.md` geschrieben und den Status auf *"⚠️ In Entwicklung / Verifikation ausstehend"* gesetzt – **obwohl kein einziger Agent Code produziert hat.** Das erzeugt irreführende Projektzustände und Backlog-Tickets für Probleme, die es nicht gibt.

**Maßnahme (P0/P1):**
- **Circuit Breaker:** Scheitern in einer Welle >60 % der Agenten an Provider-Erschöpfung, den Lauf **sofort sauber beenden** – mit klarer Meldung, ohne `PROJECT_STATE`-Schreibung, ohne Fix-Dispatch, ohne Ticket-Eröffnung.
- **Resume-Fähigkeit:** Den abgebrochenen Lauf als `paused_provider_exhausted` im Backlog ablegen, damit `--work-backlog` ihn nach Kontingent-Reset exakt dort fortsetzt.

---

### 🟠 D5 – Kein persistentes Logging

`logs/` ist **vollständig leer**, und in `core/`, `agents/`, `interface/`, `main.py` gibt es **kein einziges `logging.basicConfig` und keinen `FileHandler`**. Die gesamte Diagnose läuft über `rich`-Konsolenausgabe, die nach dem Schließen des Terminals weg ist.

Für ein *autonomes* Team, das im Hintergrund über `--work-backlog`, `issue_watcher`, `production_monitor` und `merge_watcher` läuft, ist das der größte blinde Fleck: **Wenn ein nächtlicher Lauf scheitert, gibt es nichts zu untersuchen.**

**Maßnahme (P1):**
- Strukturiertes JSONL-Log pro Lauf: `logs/runs/<timestamp>_<slug>.jsonl` – ein Eintrag je Agenten-Call mit `agent_id`, angefordertes Modell, **effektives Modell**, Tokens, Dauer, `failure_class`, Tool-Calls.
- Roh-Output jedes Verifikationslaufs (pip/pytest/npm stdout+stderr) unter `logs/verification/` ablegen. Aktuell landet nur eine gekürzte Zusammenfassung im Report – die eigentliche Fehlermeldung, die ein Mensch zum Debuggen braucht, geht verloren.
- Retention: 30 Tage bzw. 200 Läufe, automatische Rotation.

---

### 🟡 D6 – Rollen-Override greift bei 7 Agenten nicht

In [config.py:160](config.py#L160) prüft `get_model_for_agent()`:

```python
if agent_id in AGENT_MODELS and os.getenv(f"{agent_id.upper()}_MODEL"):
```

Bei 7 Rollen heißt die tatsächliche Umgebungsvariable aber anders:

| Agent | Echte Variable | Geprüft wird |
|:--|:--|:--|
| `product_owner` | `PO_MODEL` | `PRODUCT_OWNER_MODEL` |
| `business_analyst` | `BA_MODEL` | `BUSINESS_ANALYST_MODEL` |
| `prompt_engineer` | `PROMPT_ENG_MODEL` | `PROMPT_ENGINEER_MODEL` |
| `resilience_guard` | `RESILIENCE_MODEL` | `RESILIENCE_GUARD_MODEL` |
| `image_generator` | `IMAGE_GEN_MODEL` | `IMAGE_GENERATOR_MODEL` |
| `accessibility` | `A11Y_MODEL` | `ACCESSIBILITY_MODEL` |
| `documentation` | `DOCS_MODEL` | `DOCUMENTATION_MODEL` |

**Wirkung:** Für diese 7 Rollen wird ein explizit gesetzter Rollen-Override **still von einem Fachbereichs-Override überstimmt** – genau die Vorrang-Regel, die der Code herstellen soll, kehrt sich um.

**Maßnahme (P2):** Env-Namen je Rolle explizit in einem Dict `AGENT_MODEL_ENV_KEYS` hinterlegen und in Schritt 1 daraus lesen. Ein Test, der Dict-Keys gegen die `os.getenv`-Namen prüft, verhindert Rückfälle.

---

### 🟡 D7 – Learning-Speicher läuft über (FIFO statt Relevanz)

7 von 19 Agenten stehen exakt am Limit `MAX_RULES_PER_AGENT = 10`:

| Agent | Regeln | Zeichen |
|:--|--:|--:|
| `architect`, `dev_lead`, `governance_lead`, `code_reviewer`, `qa_lead`, `frontend`, `security` | **10 / 10** | ~1.000–1.150 |

Neue Erkenntnisse verdrängen ältere nach **FIFO, nicht nach Nutzen**. Eine bewährte, spezifische Regel kann durch eine generische ersetzt werden – und da die Fehlerdaten (D2) ohnehin verfälscht sind, entstehen die neuen Regeln teilweise aus Rate-Limit-Rauschen.

**Maßnahme (P2):**
- **Wirksamkeit messen:** Pro Regel mitzählen, wie viele Läufe seit Einführung den zugehörigen Fehler *nicht* mehr zeigten. Verdrängt wird die Regel mit dem geringsten Nutzen, nicht die älteste.
- **Deduplizieren:** Vor dem Einfügen Jaccard-Ähnlichkeit gegen bestehende Regeln prüfen (Schwelle ~0,6) und bei Treffer zusammenführen statt anhängen.
- **Quarantäne:** Regeln, die aus einem Lauf mit `provider_exhausted` stammen, gar nicht erst aufnehmen.

---

### 🟡 D8 – Kontext-Effizienz: 25 : 1 Prompt-zu-Completion

`gemini-3.1-flash-lite`: **21,08 Mio. Prompt-Tokens gegen 0,84 Mio. Completion-Tokens.** Cache-Reads: 2,6 Mio. = **12 % Trefferquote**.

Das heißt: Für jedes erzeugte Token werden 25 gelesen, und der Prompt-Cache greift bei knapp jedem achten. Bei `gemini-3.8-flash` ist das Verhältnis sogar **47 : 1**. Der überwiegende Teil der Kosten entsteht dadurch, dass Kontext immer wieder neu geschickt wird.

**Maßnahme (P2):**
- **Cache-stabile Prompt-Reihenfolge:** Statischer Teil (System-Prompt, Werkzeugkatalog, Projekt-Konstitution) muss byte-identisch am Anfang stehen; alles Variable (Task, Historie) ans Ende. Bereits kleine Änderungen im statischen Präfix – z. B. eingebettete Zeitstempel oder ein wachsender Learnings-Block – entwerten den Cache komplett.
- **Learnings-Block stabilisieren:** `get_augmented_prompt()` hängt Learnings an den System-Prompt an. Da sich dieser Block laufend ändert, invalidiert **jede neue Lernregel den Cache aller folgenden Calls dieses Agenten**. Learnings hinter den Cache-Breakpoint verschieben.
- **Kontext-Budget je Agent:** Der `tester` braucht nicht die vollständige Projekt-Konstitution, der `readme`-Agent keine DB-Schemata. Rollenspezifische Kontext-Filter senken die Prompt-Last spürbar.

---

## 🏢 Teil 3 – Was zum "echten Softwareentwickler-Team" noch fehlt

Diese Punkte sind keine Bugs, sondern Fähigkeiten, die ein reales Team hat und dieses noch nicht:

### 3.1 Ein verbindliches Architektur-Gate zwischen Planung und Umsetzung
Aktuell delegiert der `dev_lead` **parallel** an `backend`, `database`, `frontend` ([agents/orchestrator/department.py](agents/orchestrator/department.py)). Keiner sieht die Zwischenergebnisse der anderen; der `contract_verifier` prüft erst **nach** der Konsolidierung. Ein echtes Team hält ein Design-Review, *bevor* fünf Leute parallel loscodieren.

**Vorschlag:** Nach der Planungsphase ein deterministisches **Architektur-Manifest** erzwingen (JSON, kein Fließtext): DB-Paradigma (sync/async), Liste aller Routen mit Request-/Response-Schema, Modul-Exports, `requirements.txt`-Entwurf. Der `dev_lead` startet erst, wenn das Manifest vollständig ist – und **jeder Implementierungs-Agent bekommt das Manifest als bindenden Vertrag** statt einer Prosa-Zusammenfassung.

### 3.2 Smoke-Test-First statt Test-Suite-am-Ende
Der `tester` ist mit 78 Calls der meistgerufene und mit 65 % der schwächste Kern-Agent. Ein Großteil der Fix-Zyklen entsteht, weil die App **gar nicht startet** – das fällt aber erst auf, wenn schon eine komplette Test-Suite geschrieben wurde.

**Vorschlag:** Direkt nach der ersten Backend-Welle einen **verpflichtenden 10-Zeilen-Smoke-Test** (`GET /health` bzw. Import der App) ausführen. Schlägt der fehl, wird **keine weitere Zeile Feature-Code oder Test** geschrieben, sondern sofort der Start-Fehler behoben. Das ist die wirksamste Einzelmaßnahme gegen die teuren 500k-Token-Fehlläufe.

### 3.3 Echte Definition of Done
`PROJECT_STATE.md` sagt aktuell *"⚠️ In Entwicklung / Verifikation ausstehend"* – auch dann, wenn null Dateien geschrieben wurden. Es fehlt ein maschinenlesbarer, unbestechlicher Zustand.

**Vorschlag:** Ein `.ai_team_dod.json` je Projekt mit harten Kriterien: `app_starts`, `tests_exist`, `tests_pass`, `lint_clean`, `deps_installable`, `no_secrets`, `coverage >= X`. Ein Lauf ist **nur** dann erfolgreich, wenn alle erfüllt sind. Diese Datei ist gleichzeitig die Datenquelle für den Benchmark aus D3.

### 3.4 Fehler-Taxonomie statt generischer Fix-Aufträge
`verification.py` (2.450 Zeilen) erkennt `ModuleNotFoundError` und `ImportError` gezielt, für die übrigen häufigen Klassen gibt es kein Pattern-Matching – der Fix-Agent bekommt dann nur *"lies die Datei und behebe den Fehler"*.

**Vorschlag – Muster mit konkreter Handlungsanweisung ergänzen:**
| Fehlerklasse | Anweisung an den Fix-Agenten |
|:--|:--|
| `OperationalError: no such table: X` | Alle Modelle müssen dieselbe `Base` verwenden – Registry prüfen |
| `IntegrityError: NOT NULL constraint failed: t.c` | `nullable=True` setzen **oder** Testdaten ergänzen |
| `AttributeError: 'dict' object has no attribute` | Rückgabewert ist `dict` statt Modell-Instanz |
| `404` auf dokumentierter Route | Router-Prefix-Verdopplung prüfen |
| `create_engine` **und** `create_async_engine` im selben Projekt | Architektur-Konflikt – an `architect` eskalieren |

### 3.5 Eskalation statt Wiederholung
Derselbe Fehler kann heute mehrfach denselben (falschen) Fix auslösen. Ein reales Team zieht nach dem zweiten Fehlversuch jemand anderen hinzu.

**Vorschlag:** Fehler-Signatur (Exception-Typ + Datei + Zeile) hashen. Beim zweiten identischen Auftreten **an eine andere Rolle eskalieren** (`backend` → `architect`/`database`); beim dritten den Befund als Backlog-Ticket ablegen und den Lauf ehrlich als teilweise gescheitert beenden, statt weiter Tokens zu verbrennen.

### 3.6 Rollen-Konsolidierung
`mobile` (0 Calls), `i18n` (1), `finops` (1), `team_lead` (1), `prompt_engineer` (2), `web_research` (3) sind faktisch inaktiv, blähen aber den Zerlegungs-Prompt des Orchestrators bei **jedem** Lauf auf.

**Vorschlag:** Nicht löschen, aber aus dem Standard-Zerlegungs-Prompt herausnehmen und nur bei passendem Projekt-Typ (bzw. expliziter Nennung durch den Nutzer) einblenden. `product_owner` + `business_analyst` zu einer Rolle "Requirements Analyst" zusammenlegen.

---

## 🚀 Teil 4 – Priorisierter Umsetzungsplan

### Stufe 0 – Messbarkeit herstellen *(ohne das ist alles andere blind)*

| # | Maßnahme | Datei | Aufwand |
|:--|:--|:--|:--|
| 1 | Effektives Modell im Fehlerpfad korrekt protokollieren + `failure_class` | `agents/base_agent.py` | S |
| 2 | `provider_exhausted` aus allen Erfolgsquoten herausrechnen | `optimization_advisor.py`, `team_retro.py`, `run_history.py` | M |
| 3 | Benchmark reparieren (`verification_ok`, `total_tokens`, frisches Verzeichnis) | `evals/runner.py` | M |
| 4 | Strukturiertes JSONL-Logging je Lauf + Verifikations-Rohausgaben | neu: `core/run_logger.py` | M |

### Stufe 1 – Das Team wieder arbeitsfähig machen

| # | Maßnahme | Datei | Aufwand |
|:--|:--|:--|:--|
| 5 | `HEAVY_MODEL`/`STANDARD_MODEL` auf Modelle mit echtem Kontingent setzen | `config.py` | S |
| 6 | Stille Gemini-Abwertung sichtbar machen & korrektes `model_name` melden | `core/llm_factory.py` | S |
| 7 | Start-Preflight: reale Modell-Verfügbarkeit prüfen und anzeigen | `main.py` | S |
| 8 | Circuit Breaker bei >60 % Provider-Ausfall + Resume über Backlog | `agents/orchestrator/dispatch.py` | M |

### Stufe 2 – Qualität der Ergebnisse

| # | Maßnahme | Datei | Aufwand |
|:--|:--|:--|:--|
| 9 | Smoke-Test-Gate nach der ersten Backend-Welle | `agents/orchestrator/verification.py` | M |
| 10 | Verbindliches Architektur-Manifest als Phase-Gate | `agents/orchestrator/department.py` | L |
| 11 | Fehler-Taxonomie (5 neue Muster mit Handlungsanweisung) | `agents/orchestrator/verification.py` | M |
| 12 | Eskalation bei doppelter Fehler-Signatur | `agents/orchestrator/verification.py` | M |
| 13 | `.ai_team_dod.json` als Definition of Done | neu: `core/definition_of_done.py` | M |

### Stufe 3 – Effizienz & Pflege

| # | Maßnahme | Datei | Aufwand |
|:--|:--|:--|:--|
| 14 | Env-Namen-Mapping für Rollen-Override (D6) | `config.py` | S |
| 15 | Learning-Dedup + Nutzen-basierte Verdrängung | `memory/agent_knowledge_base.py` | M |
| 16 | Cache-stabile Prompt-Reihenfolge, Learnings hinter den Breakpoint | `agents/base_agent.py` | M |
| 17 | Inaktive Rollen aus dem Standard-Zerlegungs-Prompt ausblenden | `core/task_manager.py` | S |
| 18 | Benchmark-Katalog auf `api`/`cli`/`fullstack` erweitern | `evals/tasks.py` | S |

---

## ✅ Teil 5 – Was bereits sehr gut ist (bewusst erhalten)

Damit die Kritik nicht den Blick verstellt – diese Bausteine sind überdurchschnittlich solide gebaut:

- **Framework-Testabdeckung:** 1.504 Tests, alle grün, `ruff` sauber. Für ein Projekt dieser Größe ungewöhnlich diszipliniert.
- **Fallback-Ketten mit Verfügbarkeitsprüfung:** `_provider_available()` filtert Kandidaten ohne API-Key **vor** dem Versuch – konzeptionell genau richtig gelöst.
- **Dokumentationsdisziplin im Code:** Die Kommentare in `llm_factory.py` und `config.py` begründen Entscheidungen mit echten Fundstellen aus realen Läufen. Das ist vorbildlich und sollte beibehalten werden.
- **Governance-Infrastruktur:** ADRs, Decision-Log, Projekt-Konstitution, Secret-Scanner, Review-Gate, Push-Gate, Backlog – das deckt den Prozessteil eines echten Teams bereits weitgehend ab.
- **Bereits umgesetzte Vorgänger-Maßnahmen:** Pre-Flight-SQLAlchemy-Check, Retry-Eskalation und die geschärften Tester-/Datenbank-/Backend-Prompts (Commits `c0316c2`, `0cd8ad7`, `fb70cef`) adressieren die Prio-1-Punkte der vorherigen Analyse korrekt.

---

## 🎯 Fazit

Das Team hat **kein Fähigkeits-Problem, sondern ein Wahrnehmungs-Problem.**

Es arbeitet mit Modellen, von denen es nicht weiß, dass es sie benutzt; es misst seinen Erfolg mit einem Benchmark, der nicht durchfallen kann; und es lernt aus Fehlern, die in Wahrheit Rate-Limits waren. Alle drei Defekte verstärken sich gegenseitig – und erklären die Lücke zwischen einer exzellent getesteten Codebasis und einer Verifikationsrate von 20 %.

**Die Reihenfolge ist entscheidend:** Erst Stufe 0 (ehrliche Messung), dann Stufe 1 (funktionierende Modelle), dann Stufe 2 (Qualität). Wer bei Stufe 2 anfängt, optimiert ins Leere – weil er das Ergebnis nicht messen kann.

Realistische Erwartung nach Stufe 0 + 1: **Verifikationsrate 20 % → 50–60 %**, allein dadurch, dass die Kern-Rollen wieder auf einem angemessenen Modell laufen und Ausfälle nicht mehr als Qualitätsmängel fehlinterpretiert werden. Stufe 2 sollte auf **>75 %** tragen.
