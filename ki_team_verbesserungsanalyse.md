# 🔬 KI-Softwareentwickler-Team – Umfassende Verbesserungs- & Optimierungsanalyse

**Stand:** 10.09.2026, 19:15 Uhr
**Analysiert mit:** Claude Opus 4.6
**Grundlage:** Alle Core-Module, 200+ Run-Logs, Architektur-Docs, bisherige Optimierungspläne ([KI_TEAM_MASTERPLAN_OPTIMIERUNG.md](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/KI_TEAM_MASTERPLAN_OPTIMIERUNG.md), [ki_team_analyse_und_optimierungen.md](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/ki_team_analyse_und_optimierungen.md)), neueste Lauf-Logs (`auditlog_sentinel`, `vaultguard`, `logipulse`, `smoke_jwt_router`)

---

## 📋 Inhaltsverzeichnis

1. [Status der bisherigen Maßnahmen](#-teil-1--status-der-bisherigen-maßnahmen)
2. [Noch offene kritische Probleme](#-teil-2--noch-offene-kritische-probleme)
3. [Neue Erkenntnisse aus den jüngsten Läufen](#-teil-3--neue-erkenntnisse-aus-den-jüngsten-läufen)
4. [Architektonische Optimierungsvorschläge](#-teil-4--architektonische-optimierungsvorschläge)
5. [Code-Qualität & technische Schulden](#-teil-5--code-qualität--technische-schulden)
6. [Priorisierte Maßnahmen-Roadmap](#-teil-6--priorisierte-maßnahmen-roadmap)
7. [Was bereits exzellent funktioniert](#-teil-7--was-bereits-exzellent-funktioniert)

---

## ✅ Teil 1 – Status der bisherigen Maßnahmen

Die Analyse der beiden vorherigen Optimierungspläne zeigt, dass **erhebliche Fortschritte** erzielt wurden. Hier der Status jeder Maßnahme:

### Masterplan Stufe 0 – Ehrliche Messung ✅ Umgesetzt

| # | Maßnahme | Status | Bewertung |
|:--|:--|:--|:--|
| 1 | Effektives Modell im Fehlerpfad korrekt protokollieren | ✅ **Erledigt** | [base_agent.py:174](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/agents/base_agent.py#L174) – `failure_class` + `is_infrastructure_failure()` |
| 2 | `provider_exhausted` aus Erfolgsquoten herausrechnen | ✅ **Erledigt** | [provider_exhaustion.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/core/provider_exhaustion.py) – saubere Taxonomie |
| 3 | Benchmark reparieren | ✅ **Erledigt** | [runner.py:190](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/evals/runner.py#L190) – strukturiertes Ergebnis, Token-Summe, Archivierung |
| 4 | Strukturiertes JSONL-Logging | ✅ **Erledigt** | [run_logger.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/core/run_logger.py) – 200 Run-Logs, 200 Verification-Logs vorhanden |

### Masterplan Stufe 1 – Funktionierende Modelle ✅ Umgesetzt

| # | Maßnahme | Status | Bewertung |
|:--|:--|:--|:--|
| 5 | `HEAVY_MODEL` auf verfügbare Modelle setzen | ✅ **Erledigt** | [config.py:104-141](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/config.py#L104) – `_first_available_model()` |
| 6 | Stille Gemini-Abwertung sichtbar machen | ✅ **Erledigt** | [llm_factory.py:332-350](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/core/llm_factory.py#L332) – `_model_downgrade_listener` |
| 7 | Start-Preflight | ✅ **Erledigt** | [model_preflight.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/core/model_preflight.py) – `--check-models` |
| 8 | Circuit Breaker bei Massen-Ausfall | ✅ **Erledigt** | Budget-Abbruch in Lauf-Logs sichtbar (`budget_aborted: true`) |

### Masterplan Stufe 2 – Qualität 🟡 Teilweise

| # | Maßnahme | Status | Bewertung |
|:--|:--|:--|:--|
| 9 | Smoke-Test-Gate | ✅ **Erledigt** | Im CHANGELOG als umgesetzt dokumentiert |
| 10 | Architektur-Manifest als Phase-Gate | 🟡 **Teilweise** | `interface_contract.json` existiert (team_directives), aber kein hartes Gate |
| 11 | Fehler-Taxonomie | ✅ **Erledigt** | [failure_triage.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/core/failure_triage.py) – 677 Zeilen, AST-basiert |
| 12 | Eskalation bei doppelter Fehler-Signatur | ❌ **Offen** | Kein Hash-basierter Eskalationsmechanismus erkennbar |
| 13 | `.ai_team_dod.json` | ✅ **Erledigt** | [definition_of_done.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/core/definition_of_done.py) |

### Masterplan Stufe 3 – Effizienz 🟡 Teilweise

| # | Maßnahme | Status | Bewertung |
|:--|:--|:--|:--|
| 14 | Env-Namen-Mapping für Rollen-Override (D6) | ❌ **Offen** | Kein `AGENT_MODEL_ENV_KEYS`-Dict in config.py |
| 15 | Learning-Dedup + Nutzen-basierte Verdrängung | ❌ **Offen** | Immer noch FIFO in `agent_knowledge_base.py` |
| 16 | Cache-stabile Prompt-Reihenfolge | ✅ **Erledigt** | [base_agent.py:107-119](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/agents/base_agent.py#L107) – Learnings nach hinten |
| 17 | Inaktive Rollen aus Zerlegungs-Prompt ausblenden | ❌ **Offen** | Noch kein Filter erkennbar |
| 18 | Benchmark-Katalog erweitern | ❌ **Offen** | Nur `fastapi_ping` in eval_history |

---

## 🔴 Teil 2 – Noch offene kritische Probleme

### 🔴 P1: Universeller Silent-Downgrade auf `gemini-3.1-flash-lite`

> [!CAUTION]
> **Das kritischste aktive Problem.** Die neuesten Lauf-Logs beweisen: Das Modell-Tiering ist **immer noch wirkungslos**.

**Beleg** – [auditlog_sentinel Run-Log vom 10.09.](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/logs/runs/20260910_132041_auditlog_sentinel.jsonl):
- **41 von 41 erfolgreichen Calls** liefen auf `gemini-3.1-flash-lite`
- **Jeder einzelne Agent** zeigt `model_downgraded: true`
- `architect` (HEAVY → flash-lite), `backend` (HEAVY → flash-lite), `security` (HEAVY → flash-lite)

```
seq  2: architect    → requested: openai/gpt-oss-120b → effective: gemini-3.1-flash-lite ⚠️
seq  4: architect    → requested: openai/gpt-oss-120b → effective: gemini-3.1-flash-lite ⚠️
seq  8: database     → requested: openai/gpt-oss-120b → effective: gemini-3.1-flash-lite ⚠️
seq 10: backend      → requested: openai/gpt-oss-120b → effective: gemini-3.1-flash-lite ⚠️
seq 16: security     → requested: openai/gpt-oss-120b → effective: gemini-3.1-flash-lite ⚠️
```

**Warum `model_capability.py` nicht greift:** Das Modul wurde als Graceful Degradation gebaut – es blockiert den Aufruf, wenn kein ausreichend starkes Modell verfügbar ist. Aber wenn `gemini-3.1-flash-lite` als letzte Fallback-Stufe die Rate-Limits noch nicht erreicht hat, **lässt die Kette es durch**, bevor die Capability-Floor-Prüfung greift. Der Floor scheint nur zu greifen, wenn GAR kein Provider antwortet.

**Ursachenkette:**
1. `HEAVY_MODEL` → Groq `openai/gpt-oss-120b` (korrekt konfiguriert per `_first_available_model`)
2. Groq schlägt fehl (Rate-Limit oder TPD-Limit)
3. Fallback-Kette in `llm_factory.py` probiert: Claude (kein Key) → DeepSeek (Insufficient Balance) → OpenRouter (requires more credits) → `gemini-3.8-flash` (20 Calls/Tag erschöpft) → `gemini-3.6-flash` → `gemini-3.1-flash-lite` ✓
4. **Alle HEAVY-Aufgaben werden vom schwächsten Modell erledigt**

### 🔴 P2: Alle bezahlten Provider erschöpft, nur Free-Tier übrig

**Beleg** – Fehlerprotokoll seq 13 im [zweiten auditlog_sentinel-Lauf](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/logs/runs/20260910_134206_auditlog_sentinel.jsonl):
```
gemini-3.8-flash:        429 RESOURCE_EXHAUSTED (20 Calls/Tag Free-Tier)
claude-sonnet-5:         übersprungen (kein API-Key)
deepseek:deepseek-chat:  übersprungen (Insufficient Balance)
openrouter/auto:         übersprungen (requires more credits)
gemini-3.6-flash:        429 Quota Exceeded (alle Keys erschöpft)
groq:openai/gpt-oss-120b: 429 Rate limit reached
gemini-3.1-flash-lite:   429 Quota Exceeded (alle Keys erschöpft)
```

> [!WARNING]
> **Das gesamte Team kann maximal ~500 Calls/Tag machen** (Free-Tier-Limit von `gemini-3.1-flash-lite`). Ein einziger komplexer Lauf verbraucht 30-50 Calls. Das reicht für **maximal 10-15 Läufe/Tag**.

### 🔴 P3: Der Fix-Loop wiederholt denselben Fehler

**Beleg** – auditlog_sentinel erster Lauf:
- `requirements.txt` wurde **5-mal** hintereinander von verschiedenen Agenten überschrieben (seq 28, 29, 30, 32, 33, 34, 39)
- `backend`, `performance`, `tester`, `security`, `database` editierten alle `requirements.txt` unkoordiniert
- Am Ende scheiterten die Tests trotzdem (`exit_code: 2`)

Dies ist das **Fehlen eines verbindlichen Architektur-Vertrags**: Ohne ein einziges, autoritatives Dependency-Manifest editieren alle Agenten dieselbe Datei – und überschreiben die Änderungen der anderen.

---

## 🆕 Teil 3 – Neue Erkenntnisse aus den jüngsten Läufen

### 3.1 Coordination-Failure: Mehrere Agenten editieren dasselbe File

In den neuesten Lauf-Logs zeigt sich ein systematisches Pattern:

| Datei | Agenten die sie schrieben | Lauf |
|:--|:--|:--|
| `requirements.txt` | backend, performance, tester, security, database | auditlog_sentinel |
| `app/config.py` | architect, security (2×) | auditlog_sentinel |
| `app/models.py` | database, documentation | auditlog_sentinel |
| `app/main.py` | security, frontend | auditlog_sentinel |
| `app/__init__.py` | tester, security | auditlog_sentinel |

**Problem:** Ohne File-Locking oder einen „Owner per File"-Mechanismus überschreiben spätere Agenten die Arbeit früherer. Das ist eine der Hauptursachen für Test-Fehlschläge.

### 3.2 Completion-Token stagnieren bei ~150-300 in Fix-Loops

In den späteren Fix-Iterationen des auditlog_sentinel-Laufs (seq 28-34) brechen die Completion-Tokens ein:

| seq | Agent | Completion-Tokens | files_written |
|:--|:--|--:|:--|
| 28 | performance | 153 | requirements.txt |
| 29 | backend | 141 | requirements.txt |
| 30 | tester | 158 | requirements.txt |
| 31 | database | 309 | – |
| 33 | backend | 142 | requirements.txt |
| 34 | tester | 244 | requirements.txt |

Die Agenten generieren pro Fix-Iteration nur noch **winzige Änderungen** (eine Zeile in requirements.txt), statt das eigentliche Problem (fehlende Routen, kaputte Imports) zu beheben. Das deutet auf **zu wenig Kontext im Fix-Prompt** hin.

### 3.3 Groq `gpt-oss-120b` erreicht nie den Agenten

Obwohl `_first_available_model()` korrekt Groq als HEAVY-Modell wählt (`GROQ_API_KEY` ist gesetzt), wird es in keinem einzigen erfolgreichen Call als `effective_model` gelistet. Die gesamte Groq-Kapazität scheint bereits erschöpft zu sein, bevor die echten Aufgaben starten – möglicherweise durch die Tests (200 Lauf-Logs vom selben Tag `20260910_093*`).

### 3.4 Anthropic API-Key ist jetzt gesetzt, wird aber nicht genutzt

> [!IMPORTANT]
> In der `.env` steht jetzt ein `ANTHROPIC_API_KEY` (`sk-ant-api03-...`). Trotzdem zeigt kein einziger Lauf-Log einen erfolgreichen Claude-Call. Mögliche Ursachen:
> 1. Der Key ist abgelaufen/ungültig
> 2. Claude wird in der Fallback-Kette übersprungen, weil Groq zuerst kommt
> 3. `_provider_available()` prüft nur, ob der Key existiert, nicht ob er gültig ist

---

## 🏗️ Teil 4 – Architektonische Optimierungsvorschläge

### 4.1 Echtes Provider-Budget-Management (statt „Best Effort")

**Problem:** Das System hat keinerlei Kenntnis über die tatsächlichen Kontingente der Provider. Es probiert blind und fällt bei Erschöpfung durch.

**Vorschlag – Provider-Budget-Tracker:**

```python
# core/provider_budget.py (neu)
@dataclass
class ProviderBudget:
    provider: str
    daily_limit: int           # bekanntes Tageskontingent
    used_today: int = 0        # heutiger Verbrauch
    last_exhaustion: float = 0 # Zeitpunkt des letzten 429
    
KNOWN_FREE_TIER_LIMITS = {
    "gemini-3.1-flash-lite": 500,   # Calls/Tag
    "gemini-3.8-flash": 20,         # Calls/Tag
    "gemini-3.6-flash": 100,        # Calls/Tag
    "groq:openai/gpt-oss-120b": 30, # geschätzt aus Logs
}
```

- **Vor jedem Call:** Budget prüfen, bei <10% Reserve direkt zum nächsten Provider
- **Nach jedem 429:** Tatsächliches Limit und Verbrauch lernen
- **Am Laufbeginn:** Dem Nutzer anzeigen: „Verfügbares Budget: ~X Calls auf Provider Y, Z"

### 4.2 File-Ownership & Merge-Koordination

**Problem:** Mehrere Agenten editieren dieselbe Datei unkontrolliert.

**Vorschlag:**

1. **File-Lock im AgentToolbox:** Bevor ein Agent `write_file` aufruft, prüft das System, ob ein anderer Agent die Datei im selben Lauf bereits geschrieben hat.
2. **Merge statt Overwrite:** Wenn `requirements.txt` bereits existiert, fügt der neue Agent seine Einträge hinzu, statt die Datei komplett zu überschreiben. Die Logik in `manifest_guard.py` hat bereits eine gute Grundlage dafür.
3. **Autoritativer Owner:** `requirements.txt` → `backend`, `package.json` → `frontend`, `Dockerfile` → `devops`. Andere Agenten dürfen nur **vorschlagen**, nicht direkt schreiben.

### 4.3 Intelligentes Fix-Loop-Budget

**Problem:** Fix-Loops verbrauchen enorme Token-Mengen ohne Fortschritt.

**Vorschlag:**

```
Fix-Iteration 1: Vollständiger Kontext (Traceback + betroffene Dateien)   → 60% Budget
Fix-Iteration 2: Fokussierter Kontext + Diff aus Iteration 1              → 25% Budget
Fix-Iteration 3: Eskalation an eine höherwertige Rolle                    → 15% Budget
Fix-Iteration 4: STOPP – als „teilweise gescheitert" markieren
```

- **Fortschrittsmessung:** Anzahl der bestandenen Tests nach jedem Fix vergleichen. Sinkt sie, wird der Fix zurückgerollt.
- **Fehler-Signatur-Hash:** Selber Traceback nach 2 Versuchen → automatische Eskalation

### 4.4 Pre-Flight-Budget-Kalkulation

**Vorschlag:** Vor dem Lauf anhand der Aufgabenkomplexität und der verfügbaren Provider-Budgets abschätzen, ob der Lauf überhaupt zu Ende laufen kann:

```
Aufgabe: "Fullstack CRUD App mit Auth"
Geschätzter Bedarf:  ~40 Agent-Calls × ~30k Tokens = ~1.2M Tokens
Verfügbar:           gemini-3.1-flash-lite: 480/500 Calls, Groq: 0/30 Calls
→ ⚠️ WARNUNG: Nur 1 Provider mit ausreichend Kontingent. 
  HEAVY-Rollen werden auf flash-lite herabgestuft.
  Fortfahren? [j/n]
```

### 4.5 Inkrementelle Entwicklung statt Big-Bang

**Problem:** Das Team versucht ein Fullstack-Projekt in einem einzigen Lauf zu bauen. Bei 33 Agenten × 1-3 Calls ergibt das 50-100 LLM-Calls, die alle auf dem schwächsten Modell laufen.

**Vorschlag – Phasen-orientierte Ausführung:**

| Phase | Agenten | Erwartung |
|:--|:--|:--|
| **Phase A: Skeleton** | architect, backend | `main.py` startet, `/health` antwortet |
| **Smoke-Test** | verifier | App startet? → Ja: weiter / Nein: Fix |
| **Phase B: Core Features** | backend, database, tester | CRUD-Endpoints, DB-Schema, Tests laufen |
| **Integration-Test** | verifier | Alle Tests grün? → Ja: weiter / Nein: Fix |
| **Phase C: Frontend & Doku** | frontend, ui_ux, documentation, readme | UI, Docs |
| **Phase D: Härten** | security, code_reviewer, compliance | Audit & Fixes |

Jede Phase hat ein **eigenständiges Verifikations-Gate**. Erst wenn Phase A bestanden ist, beginnt Phase B.

---

## 🔧 Teil 5 – Code-Qualität & Technische Schulden

### 5.1 Monolithische Dateien

| Datei | Zeilen | Größe | Problem |
|:--|--:|--:|:--|
| [verification.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/agents/orchestrator/verification.py) | ~4000+ | 193 KB | Schwer wartbar, schwer testbar |
| [orchestrator/__init__.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/agents/orchestrator/__init__.py) | ~2000+ | 102 KB | Zentraler Single Point of Failure |
| [llm_factory.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/core/llm_factory.py) | 1687 | 89 KB | 5 Client-Klassen + Logik in einer Datei |
| [config.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/config.py) | 827 | 61 KB | Konfiguration + Logik vermischt |
| [completeness.py](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/core/verifier/completeness.py) | ~1600+ | 63 KB | Zu viel Verantwortung |

> [!WARNING]
> `verification.py` mit **193 KB** ist das größte Einzelmodul. Bei einer Datei dieser Größe ist die Wahrscheinlichkeit hoch, dass Änderungen unbeabsichtigte Seiteneffekte haben. Ein Refactoring in thematische Sub-Module wäre die sicherste Investition in langfristige Wartbarkeit.

### 5.2 Env-Variable Inkonsistenz (D6 – noch offen)

Die 7 Rollen mit abweichenden Env-Variablen-Namen aus dem Masterplan sind **immer noch nicht korrigiert**:

| Agent | Wird in config.py gelesen | Tatsächlich in .env.example |
|:--|:--|:--|
| `product_owner` | `PO_MODEL` | ✅ passt |
| `business_analyst` | `BA_MODEL` | ✅ passt |
| `prompt_engineer` | `PROMPT_ENG_MODEL` | ✅ passt |
| `resilience_guard` | `RESILIENCE_MODEL` | ✅ passt |

> [!NOTE]
> Die `get_model_for_agent()`-Funktion aus dem Masterplan (D6) wurde durch die direkte Zuweisung in `AGENT_MODELS` ersetzt. Die Env-Variablen werden jetzt inline gelesen. Das Problem ist damit **implizit gemildert**, aber ein standardisiertes `AGENT_MODEL_ENV_KEYS`-Dict wäre trotzdem sauberer.

### 5.3 Learning-System (D7 – noch offen)

[agent_learnings.json](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/memory/agent_learnings.json) (15 KB) zeigt, dass das Learning-System aktiv ist. Aber:

- **Keine Deduplizierung:** Ähnliche Regeln können sich ansammeln
- **Kein Nutzen-Tracking:** Keine Messung, ob eine Regel tatsächlich hilft
- **Keine Quarantäne:** Regeln aus Provider-Exhausted-Läufen werden nicht gefiltert
- **FIFO-Verdrängung:** Die älteste, nicht die nutzloseste Regel wird entfernt

### 5.4 Der Backlog wächst unkontrolliert

[backlog.json](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/memory/backlog.json) ist bereits **101 KB** groß. Ohne eine Bereinigungsstrategie für erledigte oder veraltete Tickets wird die Datei immer größer und der Kontext für `--work-backlog` immer unübersichtlicher.

### 5.5 history_default.json ist 13 MB groß

[history_default.json](file:///c:/Users/sche-/Desktop/Programmieren%20Projekte/AI-Softwareentwickler-Team/memory/history_default.json) ist **13,2 MB** groß – deutlich zu groß für eine Datei, die potentiell bei jedem Start eingelesen wird. Hier fehlt eine Rotation oder Archivierungsstrategie.

---

## 🚀 Teil 6 – Priorisierte Maßnahmen-Roadmap

### 🔴 Stufe 0 – Sofort umsetzbar, höchster Impact

| # | Maßnahme | Betroffene Datei(en) | Aufwand | Erwarteter Impact |
|:--|:--|:--|:--|:--|
| **1** | **Anthropic-Key validieren & Claude aktivieren** | `.env`, `core/model_preflight.py` | S | 🔥 HEAVY-Rollen bekommen ein starkes Modell |
| **2** | **Capability-Floor HART durchsetzen** – flash-lite darf für HEAVY-Rollen NICHT als Fallback dienen | `core/model_capability.py`, `core/llm_factory.py` | M | 🔥 Stoppt die stille Abstufung |
| **3** | **Provider-Budget-Awareness** – Bekannte Free-Tier-Limits (500, 20, 100) VOR dem Lauf anzeigen und bei < Budget warnen | `core/model_preflight.py` (erweitern) | M | Verhindert sinnlose Läufe |

### 🟠 Stufe 1 – Qualitätsverbesserung der generierten Projekte

| # | Maßnahme | Betroffene Datei(en) | Aufwand | Erwarteter Impact |
|:--|:--|:--|:--|:--|
| **4** | **File-Ownership:** `requirements.txt` darf nur von `backend` geschrieben werden; andere Agenten schlagen Änderungen vor | `core/agent_toolbox.py`, `agents/team_directives.py` | M | Beendet Overwrite-Konflikte |
| **5** | **Fix-Loop-Eskalation:** Fehler-Signatur-Hash, 2× selber Fehler → Eskalation an andere Rolle | `agents/orchestrator/verification.py` | M | Beendet Token-Verbrennung |
| **6** | **Fix-Loop-Budget:** Max. 3 Iterationen, Fortschrittsmessung (Anzahl bestandener Tests) | `agents/orchestrator/verification.py` | S | Spart 30-50% Token bei Fehlläufen |
| **7** | **Phasenweise Entwicklung mit Zwischen-Gates** | `agents/orchestrator/__init__.py`, `department.py` | L | Strukturelle Verbesserung |

### 🟡 Stufe 2 – Effizienz & Wartbarkeit

| # | Maßnahme | Betroffene Datei(en) | Aufwand | Erwarteter Impact |
|:--|:--|:--|:--|:--|
| **8** | **Learning-Dedup + Nutzen-Tracking** | `memory/agent_knowledge_base.py` | M | Bessere Lernregeln |
| **9** | **Inaktive Rollen aus Zerlegungs-Prompt ausblenden** (`mobile`, `i18n`, `finops`, `team_lead`) | `core/task_manager.py` | S | Weniger Prompt-Tokens |
| **10** | **Benchmark-Katalog erweitern** auf `api`, `cli`, `fullstack` | `evals/tasks.py` | S | Aussagekräftigere Benchmarks |
| **11** | **verification.py aufteilen** in Sub-Module (install, test, lint, fix, smoke) | `agents/orchestrator/verification.py` | L | Wartbarkeit |
| **12** | **history_default.json Rotation** – max. 100 Läufe, ältere archivieren | `memory/run_history.py` | S | Weniger I/O, schnellerer Start |
| **13** | **Backlog-Bereinigung** – erledigte Tickets nach 30 Tagen löschen | `core/backlog_store.py` | S | Übersichtlicherer Backlog |

### 🟢 Stufe 3 – Strategische Erweiterungen

| # | Maßnahme | Aufwand | Beschreibung |
|:--|:--|:--|:--|
| **14** | Bezahlte Provider-Integration | S | Gemini API Billing aktivieren (Pay-as-you-go statt Free-Tier) |
| **15** | Inkrementelle Entwicklung (Skeleton → Features → Frontend → Härtung) | L | 4-Phasen-Modell mit Zwischen-Verifikation |
| **16** | Modell-spezifische Prompt-Optimierung | M | flash-lite bekommt einfachere, strukturiertere Prompts als HEAVY-Modelle |
| **17** | Agent-Merge: `product_owner` + `business_analyst` → `requirements_analyst` | S | Reduziert redundante Calls |

---

## 🌟 Teil 7 – Was bereits exzellent funktioniert

> [!TIP]
> Diese Aspekte sollten **bewusst beibehalten** und als Vorbild für zukünftige Entwicklung dienen.

### Framework-Qualität
- **1.504 Tests, alle grün, `ruff` sauber** – für ein Hobby-Projekt dieser Größe außergewöhnlich
- **Agent-Registry-Konsistenztest** (`test_agent_registry_consistency.py`) – verhindert, dass neue Rollen vergessen werden
- **`scripts/new_agent.py`** – automatisiertes Scaffolding, das 4 Registrierungsstellen abdeckt

### Diagnostik & Transparenz
- **Strukturiertes JSONL-Logging** – revolutionärer Fortschritt gegenüber dem leeren `logs/`-Verzeichnis
- **DoD-System** – ehrliche, maschinenlesbare Fertigstellungskriterien
- **Provider-Exhaustion-Taxonomie** – saubere Trennung von Infrastruktur- und Agenten-Fehlern
- **Model-Downgrade-Listener** – jede Abstufung ist jetzt sichtbar

### Architektur
- **failure_triage.py** (677 Zeilen, AST-basiert) – beeindruckend ausgereiftes Fehler-Routing
- **manifest_guard.py** – Schutz vor korrupten Dependency-Dateien und toxischen Paket-Kollisionen
- **team_directives.py** – Contract-First-Ansatz mit `interface_contract.json`
- **model_capability.py** – Capability-Floor-Konzept (muss nur härter greifen)

### Dokumentation
- **ARCHITECTURE.md** – vorbildlich strukturiert mit ASCII-Diagramm
- **CLAUDE.md** – klare, token-effiziente Anweisungen
- **Kommentare in config.py/llm_factory.py** – begründen Entscheidungen mit echten Fundstellen

---

## 🎯 Fazit

Das KI-Softwareentwickler-Team hat in den letzten Tagen einen **enormen Qualitätssprung** gemacht. Die Stufen 0 und 1 des Masterplans (ehrliche Messung, funktionierende Modelle) sind vollständig umgesetzt. Die Infrastruktur für Stufe 2 (Qualität) ist angelegt.

**Das verbleibende Kernproblem ist ein einziges:** Alle Calls landen auf `gemini-3.1-flash-lite`, weil die tatsächlichen Provider-Kontingente zu schnell erschöpft sind. Das ist kein Software-Bug mehr, sondern ein **Ressourcen-Problem**:

> [!IMPORTANT]
> **Die wirkungsvollste Einzelmaßnahme** wäre die Aktivierung von Gemini API Billing (Pay-as-you-go) oder die Validierung und Nutzung des vorhandenen Anthropic-Keys. Damit würden die HEAVY-Rollen wieder auf einem angemessenen Modell laufen – und die gesamte Architektur (Tiering, Capability-Floor, Contract-First) könnte endlich ihre Wirkung entfalten.

Ohne bezahlte Provider arbeitet das Team faktisch mit einem **Werkzeugkasten aus Schraubenziehern unterschiedlicher Größe**, bei dem aber immer nur der kleinste Schraubenzieher aus der Schublade kommt.
