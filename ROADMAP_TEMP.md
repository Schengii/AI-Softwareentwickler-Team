# 🗺️ ROADMAP (temporär) – Verbesserungen & Optimierungen des KI-Softwareentwickler-Teams

**Erstellt:** 2026-09-20
**Analysebasis:** 152 Läufe in `memory/run_history.json`, die letzten 6 Live-Läufe
(`aegisflow`, `aetherqueue`, `nexus_mesh`, `sentinedge`, `eventforge_core`, `cachegrid_proxy`),
`logs/runs/*.jsonl`, `logs/verification/*.log`, alle `workspace/*/.ai_team_dod.json`,
`memory/team_lessons.jsonl` (102 Lektionen), `memory/backlog.json` (200 Tickets),
`memory/agent_learnings.json`, `memory/provider_cooldowns.json`, `memory/auto_tuned_models.json`,
`logs/FEHLERANALYSE_KI_TEAM_20260916.md`.

**Zustand des Frameworks zum Analysezeitpunkt:** `ruff check` sauber, `pytest` grün
(2380 passed, 1 skipped, 645 s). Die Probleme unten sind also **keine kaputten Tests**, sondern
Lücken zwischen dem, was getestet wird, und dem, was im echten Lauf passiert.

> Diese Datei ist ein Arbeitsdokument zum Abarbeiten. Jeder erledigte Punkt gehört mit
> `Closes: <ticket-id>` committet (siehe CLAUDE.md) und danach hier abgehakt.

---

## ✅ Sprint 1 – Ergebnis (2026-09-20)

Abgearbeitet: **P6-1, P0-1, P0-2, P0-3, P0-5, P0-6** (Teil 1). **P0-4** wurde gegen den echten
Code geprüft und als Fehlannahme der Analyse zurückgezogen – Begründung steht beim Punkt selbst.

### Was sich messbar geändert hat

| Messung | vorher | nachher |
| :--- | :--- | :--- |
| `unmet_requirements('workspace/aegisflow')` | 1 Falsch-Positiv (`backend`) → Veto | `[]` für `security` – Veto weg |
| `unmet_requirements('workspace/sentinedge')` | 2 Funde, beide falsch | `[]` |
| `unmet_requirements('workspace/eventforge_core')` | 2 Funde, 1 davon falsch | 1 Fund – **echt** (`HMAC_SECRET_KEY` steht nur in einem String-Literal) |
| `unmet_requirements('workspace/aegisflow')`, alle Rollen | 2 Funde | 1 Fund – **echt** (`POST /api/v1/dlq/replay` existiert nicht) |
| Rote Projekte unter „Sonstiger Fehler" | 8 von 12 | 4 von 12 |
| Erkannte gemeinsame Fehlermuster | „Sonstiger Fehler" (8), „Testsuite" (3) | „Sicherheits-Übergabe offen" (2), „Testsuite" (2), „Sonstiger Fehler" (4) |
| DoD-Detail bei einem Lauf mit `lint` + `pre_flight` | „fehlgeschlagene Prüfungen: lint, pre_flight" | „fehlgeschlagene Prüfungen: pre_flight" |

Die Kategorisierung ist zusätzlich nachweisbar **richtiger** geworden: `pipeline_pilot` gilt jetzt
als „Test-Schrumpfung" (deckt sich mit seinem Ticket `test-regression-pipeline_pilot`) und
`entwickle_eventforge_ein_webhook` als „Vollständigkeit" (deckt sich mit dem CHANGELOG-Eintrag
zum Completeness-Fund dieses Laufs).

Die verbleibenden 4 Projekte unter „Sonstiger Fehler" (`devpulse`, `eventstream_zero`,
`nexus_resilience_gateway`, `nexusforge`) stammen aus der Zeit vor `detail_file` – für sie
existiert kein vollständiges Protokoll mehr. Das ist nicht weiter reparierbar, neue Läufe sind
davon nicht betroffen.

### Wichtig: die Falsch-Positive sind weg, die echten Funde nicht

Die Lockerung in `unmet_requirements()` hätte leicht zu einem stumpfen Gate werden können.
Gegenprobe an echten Projektdaten: beide verbleibenden Funde sind nachweislich korrekt –
`POST /api/v1/dlq/replay` ist in `workspace/aegisflow` nirgends deklariert, und
`HMAC_SECRET_KEY` kommt in `workspace/eventforge_core` nur als Zeichenkette in einem
`getattr(settings, 'HMAC_SECRET_KEY', ...)` vor, ist also tatsächlich kein Settings-Feld.
Vier Tests sichern beide Richtungen ab.

### Erwartete Wirkung auf die Erfolgsquote

Von den sechs analysierten Läufen wären **`aegisflow`** (nur durch das Falsch-Positiv rot, Tests
grün) und **`cachegrid_proxy`** (nur durch das veraltete `pre_flight`-Ergebnis rot) grün
gewesen. `sentinedge` und `eventforge_core` verlieren ihr unberechtigtes Zweit-Veto, bleiben
aber wegen echter Testfehler rot – die gehen Sprint 2 (`P1-2`, Eskalations-Strategien) an.

> ⚠️ Das ist eine Rückrechnung auf archivierten Laufdaten, keine Messung. Der belastbare
> Nachweis ist ein erneuter Lauf dieser Projekte – siehe Messpunkt in Abschnitt 8.

---

## 0. 📊 Harte Ist-Zahlen (das Problem in einem Bild)

| Kennzahl | Wert | Quelle |
| :--- | :--- | :--- |
| Läufe mit `verification_ok = true` (gesamt) | **20 von 152 = 13 %** | `memory/run_history.json` |
| Läufe mit `verification_ok = true` (letzte 25) | **5 von 25 = 20 %** | dito |
| Projekte im Workspace mit Status `ok` | 17 von 39 | `core.team_health.build_team_health_rollup()` |
| Projekte in `budget_aborted` (weder rot noch grün, von keiner Reparaturschleife erfasst) | **9** | dito |
| Rote Projekte, die die Fehler-Kategorisierung als „Sonstiger Fehler" abtut | **8 von 12** | dito |
| Ø Tokenverbrauch pro Lauf (letzte 10) | **~870.000** (Cap: 1.000.000) | `run_history.json` |
| Cache-Trefferquote im letzten Lauf | **28,6 %** | `logs/runs/20260919_012548_cachegrid_proxy.jsonl` |
| Modell-Downgrades im letzten Lauf | **7 von 9 Agenten-Aufrufen** | dito |
| Aktiv genutzte Rollen (letzte 20 Läufe) | **20 von 33**, davon 5 Rollen ≥ 14× — 13 Rollen **0×** | `run_history.json` |
| Offene Tickets im Backlog | 17 `blocked` (cli) + 11 `blocked` (orchestrator) + 5 `todo` (root_cause) + 4 `review` | `core.backlog_store` |

**Kernbefund:** Das Team *produziert* gute Software – in den letzten 6 Läufen liefen Tests,
Smoke-Test, pip-audit, bandit, Testtiefe und Completeness überwiegend grün. Es *scheitert*
an der eigenen Qualitätsmechanik: teils an echten Bugs im Verifikations-Code, teils daran,
dass Befunde gemeldet, aber nie wirksam nachgezogen werden.

### Was die letzten 6 Läufe wirklich blockiert hat

| Projekt | `failed` Checks | Echter Grund |
| :--- | :--- | :--- |
| `aegisflow` | `lint`, `security_handoff` | **Falsch-Positiv** (P0-1). Testsuite war grün. |
| `aetherqueue` | `completeness`, `lint` | Tester erfand Route `GET /api/dlq`; 3 Fixversuche ohne Änderung |
| `nexus_mesh` | `lint` | **grün** (Lint ist informativ) |
| `sentinedge` | `lint`, `security_handoff`, `tests` | **Falsch-Positiv** (P0-1) + 3 echte Testfehler |
| `eventforge_core` | `sast`, `security_handoff`, `tests` | **Falsch-Positiv** (P0-1) + 1 echter Testfehler |
| `cachegrid_proxy` | `lint`, `pre_flight` | Pre-Flight-Fix ging an `architect` (schreibt keinen Code) |

---

## 1. 🔴 P0 – Bugs, die Läufe ohne Sachgrund rot färben

### P0-1 · `unmet_requirements()` hält Agenten-Rollennamen für Code-Symbole → permanentes Veto
**Status:** ✅ **erledigt 2026-09-20** (Commit folgt unten) · **Wirkung:** sehr hoch

`core/team_board.py:279` definiert
``_SYMBOL_REF_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]{2,})`")``. Damit gilt **jedes in
Backticks gesetzte Wort** als Code-Symbol, das im Projekt als `def X` / `class X` / `X =`
definiert sein muss. Der `security`-Agent formuliert seine Übergaben aber praktisch immer als
„\`backend\` muss …" – und `def backend` wird es nie geben.

Live reproduziert (`from core.team_board import unmet_requirements`):

| Projekt | Als „fehlend" gemeldete Symbole |
| :--- | :--- |
| `sentinedge` | `tester`, `run_sync`, **`backend`** |
| `eventforge_core` | `api_integration`, `database`, **`backend`**, `ALLOWED_HOSTS`, `CORS_ORIGINS`, `HMAC_SECRET_KEY` |
| `aegisflow` | **`backend`** (2×, in zwei getrennten Handoffs) |

Folge: `agents/orchestrator/verification.py:401` schreibt
`outcome.record("security_handoff", False, ...)`. `security_handoff` steht **nicht** in
`INFORMATIONAL_CHECK_KEYS` (`agents/orchestrator/verification_checks.py:152`), blockiert also
`verification_ok` hart. Der eine Fix-Versuch in
`agents/orchestrator/integration.py:315` (`security_handoff_fix`) kann die Bedingung
prinzipiell nicht erfüllen → `recurring-failure-<slug>`-Ticket → `queue_red_projects()` queued
das Projekt erneut → dieselbe Schleife. **`aegisflow` war fachlich grün und wurde allein
dadurch rot.**

Zwei weitere Fehlerklassen derselben Funktion:

* **Annotierte Zuweisungen werden nicht erkannt.** `workspace/eventforge_core/app/core/config.py:13`
  enthält `ALLOWED_HOSTS: list[str] = ["*"]`; der Regex `\bALLOWED_HOSTS\s*=` greift wegen des
  `: list[str]` dazwischen nicht. Die idiomatische pydantic-Settings-Form ist damit systematisch
  „fehlend".
* **Benutzung ≠ Definition.** `run_sync` wird in `workspace/sentinedge/tests/conftest.py:27` als
  `await conn.run_sync(...)` benutzt – die Anforderung ist erfüllt, die Prüfung verlangt aber
  eine Definition.

**Lösung (`core/team_board.py.unmet_requirements`):**

1. Bekannte Agenten-/Rollen-IDs ausschließen (Quelle: `DEPARTMENT_DEFINITIONS` bzw. die
   registrierten `agent_id`s), bevor ein Backtick-Wort als Symbol gewertet wird.
2. Symbolprüfung per AST statt Regex, inkl. `ast.AnnAssign` (annotierte Zuweisung),
   Klassenattributen und Modul-Konstanten – und zusätzlich „Symbol wird irgendwo aufgerufen"
   als Erfüllung akzeptieren.
3. Regex-Fallback nur noch als Notnagel, mit `\w+\s*(?::[^=]+)?=` statt `\w+\s*=`.

**Akzeptanzkriterium:** `unmet_requirements('workspace/aegisflow')` liefert `[]`.
Neue Tests in `tests/test_team_board.py`: Rollenname in Backticks erzeugt keinen Befund;
`X: list[str] = [...]` gilt als definiert; benutztes, nicht definiertes Symbol gilt als erfüllt.

---

### P0-2 · `security_handoff` bekommt nur EINEN Fixversuch und wird nie neu bewertet
**Status:** ✅ **erledigt 2026-09-20** · **Wirkung:** hoch

`IntegrationMixin._run_security_requirements_checkpoint()` (`agents/orchestrator/integration.py:280-338`)
beauftragt genau einen Agenten, prüft einmal nach und schreibt das Ergebnis auf
`self._security_unmet_requirements`. `verification.py:398` liest dieses Feld **am Anfang** der
Verifikationsschleife und trägt das Veto ein. Danach wird es nie mehr überprüft – selbst wenn
spätere Fix-Runden (Tests, Completeness, Integrations-Checkpoint) den Code längst repariert haben.

**Lösung:** `security_handoff` am Ende der Verifikation – direkt vor `reconcile_verification_ok()`
(`verification.py:1794`) – erneut auswerten und `outcome.record()` überschreiben. Dieselbe
Re-Evaluierung fehlt auch bei `pre_flight` (siehe P0-3), deshalb als gemeinsamer Schritt
„Re-Check blockierender Prüfungen vor der Rekonziliation" umsetzen.

**Akzeptanzkriterium:** Regressionstest, der ein anfangs unerfülltes Handoff nach einer
simulierten Fix-Runde als erfüllt neu aufzeichnet und `verification_ok=True` erreicht.

---

### P0-3 · `pre_flight`-Ergebnis ist veraltet und blockiert nach bereits erfolgtem Fix
**Status:** ✅ **erledigt 2026-09-20** · **Wirkung:** hoch

`cachegrid_proxy` endete mit `failed: ["lint", "pre_flight"]`. Heute gilt:

```
python -c "from core.pre_flight_check import run_pre_flight_check; print(run_pre_flight_check('workspace/cachegrid_proxy').passed)"
→ True
```

Der Pre-Flight-Check lief nur in der Schleife **vor** der Testausführung
(`verification.py:454`), brach nach dem Circuit-Breaker ab (`verification.py:479`) und wurde bei
`verification.py:578` mit dem letzten – inzwischen veralteten – Report aufgezeichnet. Die
nachfolgenden Fix-Runden reparierten die Ursache, aber niemand maß nach. Das Projekt ist de
facto fertig und steht dauerhaft als rot in der Historie.

**Lösung:** `pre_flight` nach der letzten Fix-Runde neu ausführen und aufzeichnen (gemeinsam mit
P0-2).

**Akzeptanzkriterium:** Test, der einen fehlgeschlagenen Pre-Flight nach einer erfolgreichen
Reparatur als `passed` neu aufzeichnet.

> ⚠️ Bereits gestaged, aber **noch nicht committet** (`git diff --cached`): die Zuweisung von
> Pre-Flight-Fixes an nicht-codeschreibende Rollen (`_NON_CODE_WRITING_ROLES`,
> `verification.py:530`) und die F841-Regel in `agents/backend_agent.py`. → **Zuerst committen**,
> mit `Closes: root-cause-cachegrid_proxy-pre-flight-fixversuche-scheitern-durch-ineffektive-agentenzu,
> root-cause-cachegrid_proxy-unbenutzte-variablenzuweisung-in-fastapi-applikation-verletz`.

---

### P0-4 · ~~`budget_aborted`-Projekte fallen aus jeder Reparaturschleife~~
**Status:** ✅ **verifiziert am 2026-09-20 – kein Bug, keine Änderung nötig**

> **Korrektur der ursprünglichen Analyse.** Die Annahme war falsch. Gegen den echten Code geprüft:
>
> 1. **`queue_red_projects()` greift diese Projekte bereits auf.** Die Überspring-Bedingung
>    lautet `if last.get("verification_ok") and not dod_blocking: continue` – sie kennt
>    `budget_aborted` gar nicht. Alle neun genannten Projekte tragen `verification_ok=False`
>    und werden damit regulär eingeplant. Der einzige Fall, der durchfällt, ist
>    `verification_ok=True` **und** `budget_aborted=True` **ohne** DoD-Blocker: im gesamten
>    Workspace trifft das auf genau ein Projekt zu (`hyperionsentinel`, 2026-09-13) – und auch
>    das nur, weil der Lauf älter ist als der Fix in `verification.py`, der seither
>    `budget_aborted` zurücksetzt, sobald die Kern-Testsuite bestanden hat. Für neue Läufe kann
>    die Kombination nicht mehr entstehen.
> 2. **Die fehlende Fehlerkategorie ist Absicht, nicht Versehen.** `core/team_health.py:119-123`
>    begründet es ausdrücklich: „ein Budget-Abbruch oder manueller Abbruch ist kein inhaltlicher
>    Fehler und hat oft gar kein `failure_detail`, würde sonst fälschlich mit anderen Projekten
>    unter ‚Sonstiger Fehler' zusammengelegt."
>
> Was bleibt, ist kein Fehler dieses Mechanismus, sondern das Budget-Problem selbst – behandelt
> in **P5-3** (Verifikations-Reserve) und **P5-2** (Token-Effizienz).

---

### P0-5 · Fehler-Kategorisierung kennt die häufigsten Fehlerarten nicht
**Status:** ✅ **erledigt 2026-09-20** · **Wirkung:** mittel (Voraussetzung für bessere Fehleranalyse)

`core/team_health.py._CATEGORY_MARKERS` (Zeile 22-32) kennt Frontend, Smoke, Lasttest, Docker,
Dependency-Audit, Coverage, Lint, Testsuite. Es fehlen genau die Marker, die die Verifikation
heute am häufigsten erzeugt:

| Fehlender Marker | Bedeutung | Vorkommen letzte 6 Läufe |
| :--- | :--- | :--- |
| `🛡️ ❌` | Sicherheits-Übergabe offen | 3× |
| `🧩` / `Verifikations-Veto durch Completeness-Check` | Vollständigkeits-Veto | 1× |
| `🔍 🛑` / `Pre-Flight` | Pre-Flight-Circuit-Breaker | 1× |
| `🚫 Lauf-Budget` | Budget-Abbruch | 2× |

Folge: 8 von 12 roten Projekten landen im Sammeltopf „Sonstiger Fehler" – die
projektübergreifende Mustererkennung, also genau die gewünschte bessere Fehleranalyse, ist für
die dominanten Fehlerklassen blind.

**Akzeptanzkriterium:** `build_team_health_rollup('workspace').shared_patterns` zeigt
`Sicherheits-Übergabe` mit ≥ 3 Projekten; „Sonstiger Fehler" enthält ≤ 3 Projekte.

---

### P0-6 · `lint` erscheint als `failed`, obwohl es laut Definition of Done irrelevant ist
**Status:** ✅ **erledigt 2026-09-20** (Teil 2, `--unsafe-fixes`, bleibt offen) · **Wirkung:** niedrig (Kosmetik), verwirrt aber jede Analyse

In **5 von 6** letzten Läufen steht `lint` in `failed`, obwohl es in `INFORMATIONAL_CHECK_KEYS`
steht und `lint_clean` in der DoD `required: false` ist. Jede spätere Analyse (auch die des
`root_cause_analyst`) liest das als echten Fehlschlag – das Ticket
`root-cause-cachegrid_proxy-unbenutzte-variablenzuweisung-…` (ruff `F841`) ist genau daraus
entstanden und hat eine LLM-Tiefenanalyse für eine ungenutzte Variable verbrannt.

**Lösung:** `VerificationOutcome.to_dict()` (`core/verification_outcome.py:85`) um
`failed_blocking` / `failed_informational` erweitern; Berichte und der Root-Cause-Prompt nutzen
nur `failed_blocking`.

**Ergänzend:** `ruff check --fix` läuft bereits (`core/verifier/lint.py:108`), aber bewusst ohne
`--unsafe-fixes`. Die real übrig bleibenden Regeln der letzten Läufe (`SIM102`, `SIM103`,
`RUF013`, `RUF059`, `F841`) sind fast alle unsafe-fixbar. Vorschlag: ein zweiter, **separat
protokollierter** Durchlauf mit `--unsafe-fixes`, gefolgt von einem erneuten Testlauf – Änderung
nur übernehmen, wenn die Tests danach weiterhin grün sind.

---

## 2. 🟠 P1 – Autonomie: Befunde in Arbeit verwandeln

### P1-1 · Root-Cause-Tickets werden erzeugt, aber nie bearbeitet
**Status:** ✅ erledigt 2026-09-21 · **Aufwand:** L · **Wirkung:** sehr hoch

`core/root_cause_analyst.py` (`TICKET_SOURCE = "root_cause_analysis"`) legt bewusst Tickets an,
die **nicht** in `core/backlog_worker.py._AUTONOMOUS_SOURCES` stehen – „Framework-Änderungen
verdienen ein menschliches Review". Ergebnis nach ~3 Wochen: 5 `todo` + 1 `blocked`
Root-Cause-Tickets liegen unbearbeitet. Von den 15 als `done` markierten wurden laut
CHANGELOG-Eintrag „Backlog-Reconciliation 2026-09-19" mehrere nur deshalb geschlossen, weil sie
in einer manuellen Sitzung nachträglich verifiziert wurden.

**Lösung – neuer Modus `python main.py --work-framework-backlog`:**

1. Greift `root_cause_analysis`-Tickets mit `[framework]`-Präfix auf.
2. Arbeitet **immer** in einem isolierten Branch (`core/git_isolation.py` existiert bereits).
3. Pflichtschritte pro Ticket: Reproduktionstest schreiben (der ohne Fix rot ist) → Fix →
   `ruff check` + `pytest` → Commit mit `Closes: <ticket-id>` → **Draft-PR**, kein Merge.
4. Das menschliche Review bleibt damit erhalten, weil nur ein Draft-PR entsteht – die Arbeit
   selbst passiert autonom.

**Akzeptanzkriterium:** Ein Lauf gegen ein vorhandenes `root-cause-*`-Ticket erzeugt einen
Branch mit mindestens einem neuen, vorher fehlschlagenden Test und einem Draft-PR.

> **Umsetzung:** `python main.py --work-framework-backlog [--limit N]` (Standard N=1), neues
> Modul `core/framework_backlog_worker.py`. `find_framework_tickets()` greift offene/blockierte
> `root_cause_analysis`-Tickets mit `[framework]`-Präfix im `detail`-Feld auf (genau der Marker,
> den `core/root_cause_analyst.py.record_findings_as_tickets()` für `category == "framework"`
> bereits schreibt). Jeder Versuch läuft IMMER in einem frischen, per `core/git_isolation.py`
> isolierten Git-Worktree - das echte Arbeitsverzeichnis des Nutzers wird während des gesamten
> Laufs nicht berührt. Der `refactoring`-Agent bekommt das Ticket als echten Tool-Aufrag
> (`allow_tools=True`, `project_dir=<Worktree>`) mit der verpflichtenden Anweisung, zuerst einen
> neuen Regressionstest zu schreiben, dann den Fix.
>
> Statt dem Agenten-Bericht zu vertrauen, erzwingt `_verify_regression_test_proves_the_bug()`
> einen MECHANISCHEN Beweis: alle geänderten NICHT-Test-Dateien werden kurzzeitig auf ihren
> `HEAD`-Vorher-Stand zurückgesetzt (neue Dateien gelöscht), der neue Test MUSS dann
> fehlschlagen ("rot ohne Fix") - schlägt er stattdessen schon ohne Fix nicht fehl, ist das kein
> echter Beweis und der Versuch wird verworfen. Danach wird der volle Endstand des Agenten IMMER
> wiederhergestellt (auch bei Fehlschlag, im `finally`) und derselbe Test muss GRÜN sein. Erst
> danach `ruff check` auf allen geänderten `.py`-Dateien, dann `git commit` mit
> `Closes: <ticket-id>` (schließt das Ticket automatisch via `--backlog-hygiene`, siehe
> CLAUDE.md), Push und `gh pr create --draft` (`agents/github_agent.py`, bereits vorhanden) -
> **niemals** ein automatischer Merge. Ein `git push` vom Framework-Root aus funktioniert für
> den Worktree-Branch, weil Worktrees denselben `.git`-Objektspeicher/dieselben Refs teilen
> (kein Checkout des Branches im echten Arbeitsverzeichnis nötig). Jeder Fehlschlag (kein neuer
> Test, Test bleibt rot, ruff unsauber, Push/PR schlägt fehl) lässt den Worktree für
> menschliche Inspektion stehen statt aufzuräumen, und der Lauf macht mit dem nächsten Ticket
> weiter. 8 neue Tests in `tests/test_framework_backlog_worker.py` (u.a. mit einem echten
> temporären Git-Repo und einem echten Off-by-one-Bug für die Rot/Grün-Probe, gemockter
> Agenten-Aufruf/GitHub-Push). Aktuell 0 offene `[framework]`-Tickets im echten Backlog - kein
> Live-Testlauf gegen ein reales Ticket in dieser Sitzung, aber `python main.py
> --work-framework-backlog` gegen den echten Backlog-Zustand geprüft (meldet korrekt "keine
> offenen Tickets").

---

### P1-2 · `recurring-failure-*`-Sackgasse: 8 Tickets, kein Weg heraus
**Status:** ✅ **erledigt 2026-09-20** (Stufe „Zweitmeinung") · **Wirkung:** hoch

Offen: `recurring-failure-{eventforge_core, sentinedge, hyperion_metrics, chronoflow,
entwickle_das_projekt_sentinel, devpulse, aegis_mesh, chronos_ledger}`. Fast alle tragen dieselbe
Diagnose: „Fixversuch änderte nichts an N Testfehler(n) – vermutlich falscher/unzureichend
instruierter Agent." `_governance_retry_pool()` in `core/backlog_worker.py` greift sie zwar
wieder auf, aber mit **derselben Strategie**, die schon dreimal gescheitert ist.

**Lösung – Eskalations-Strategien statt Wiederholung** (echtes Team-Verhalten: wer dreimal nicht
weiterkommt, wechselt die Methode, nicht die Lautstärke):

1. **Stufe 1 (heute):** derselbe Agent, gezielter Auftrag.
2. **Stufe 2 (neu):** *Zweitmeinung* – ein anderer Agent (z. B. `code_reviewer` oder
   `refactoring`) analysiert read-only und schreibt eine Diagnose ins Team-Board; erst dann fixt
   der Eigentümer mit dieser Diagnose im Kontext.
3. **Stufe 3 (neu):** *Reduktion* – den fehlschlagenden Test auf ein Minimalbeispiel reduzieren
   lassen (`pytest <test> -x` plus gezielter Prompt) statt den ganzen Traceback zu reichen.
4. **Stufe 4:** Ticket mit klarer, menschenlesbarer Blockade-Begründung schließen statt endlos
   neu aufzugreifen.

**Akzeptanzkriterium:** `agents/orchestrator/failure_diagnosis.py` kennt eine
`escalation_strategy`-Stufe pro Versuch; Test deckt ab, dass Versuch 2 einen *anderen* Agenten
beauftragt als Versuch 1.

---

### P1-3 · 17 `cli`-Tickets auf `blocked` – davon 9 nur wegen Hygiene-Timeout
**Status:** ✅ **erledigt 2026-09-20** · **Aufwand:** S · **Wirkung:** mittel

Detail bei 9 Tickets: „[Hygiene] Seit über 3 h ohne Fortschritt – Status auf 'blocked' gesetzt."
Das ist eine Zeitüberschreitung, keine inhaltliche Blockade – die Tickets wurden schlicht nie
aufgegriffen, weil kein Poll-Zyklus lief. Drei weitere (`cli-c1f46a6e`, `cli-d93dccc6`,
`cli-3972afbe`) tragen denselben Traceback:
`sequence item 0: expected str instance, NoneType found` in `_run_tests_logged`
(`verification.py:1213/1305`) – ein Framework-Crash, der noch nicht gegen den heutigen Code
verifiziert ist.

**Aufgaben:**

1. Zuerst prüfen, ob der `NoneType`-Crash im heutigen Code noch reproduzierbar ist; falls ja:
   `_run_tests_logged` gegen `None`-Einträge härten plus Regressionstest.

   > **Root Cause gefunden (nicht in `verification.py`, sondern eine Ebene tiefer),
   > 2026-09-20:** Der eigentliche Absturz liegt in `core/verifier/testrunner.py:203`:
   > `"\n".join(stderr_chunks)` erhielt mindestens ein `None`-Element, weil
   > `exec_result.stderr` (als `str` typisiert, aber zur Laufzeit nicht erzwungen) roh
   > angehängt wurde – anders als `exec_result.stdout`, das über ein f-String lief und ein
   > `None` unbemerkt in den Text `"None"` verwandelt hätte. Alle vier Aufrufstellen (Python/
   > npm/cargo/go) jetzt über `or ""`/`or ''` abgesichert. Regressionstest in
   > `tests/test_verifier.py` reproduziert exakt diesen Fall (gemockter Subprozess mit
   > `stderr=None`).
2. Hygiene: `blocked`-Grund maschinenlesbar trennen (`blocked_reason: "stale" | "error"`), damit
   „nur abgelaufen" automatisch wieder aufgegriffen wird und „echter Fehler" liegen bleibt.

   > **Umgesetzt:** neues Feld `Ticket.blocked_reason` (`core/backlog_store.py`, derselbe
   > None-Sentinel wie `priority`/`estimate`/`epic`, zusätzlich IMMER auf `""` zurückgesetzt,
   > sobald `status != "blocked"`). `core/backlog_hygiene.py.recover_stale_in_progress()` setzt
   > `blocked_reason="stale"` nur für reine `cli`-Tickets (NICHT für
   > `_GOVERNANCE_RETRY_PREFIXES`-Tickets, deren Eskalationslogik über `_governance_retry_pool()`
   > unverändert bleibt). `core/backlog_worker.py`s `ready_todo`-Filter greift jetzt zusätzlich
   > `status=="blocked" and blocked_reason=="stale"` auf und behandelt es wie ein frisches
   > `"todo"` – das bestehende Sicherheitsnetz für bewusst blockierte Tickets
   > (`test_manually_blocked_non_governance_ticket_is_not_touched`) bleibt unverändert grün, da
   > ein manuell/inhaltlich blockiertes Ticket nie `blocked_reason` gesetzt bekommt.
3. `cli-034e08e5` bezieht sich auf einen Merge-Konflikt-Marker (`<<<<<<< Updated upstream`) in
   `core/verifier/runtime.py` – heute nicht mehr vorhanden, Ticket schließen.

   > **Erledigt:** geprüft (kein Marker mehr, Datei parst fehlerfrei), Ticket auf `cancelled`
   > gesetzt mit Begründung im Detail-Text.

---

### P1-4 · Orchestrator-Absturz (`CancelledError`) ohne Wiederaufnahme
**Status:** ✅ **erledigt 2026-09-20** · **Wirkung:** mittel

Ticket `orchestrator-crash-CancelledError-entwickle_eventforge_ein_webhook`, Stelle:
`agents/base_agent.py:427` in `_run_agentic_loop` → `generate_with_tools`. Ein `CancelledError`
in einem einzelnen Agenten-Aufruf reißt den ganzen Lauf mit. `core/checkpoint.py` speichert
bereits Phasen-Checkpoints – ein Absturz nutzt sie aber nicht zur Wiederaufnahme.

**Lösung:** `CancelledError` pro Agenten-Aufruf abfangen, als
`AgentResult(success=False, failure_class="cancelled")` zurückgeben und den Lauf mit dem nächsten
Agenten fortsetzen; nur ein echtes Nutzer-Cancel (`cancel_requested`) bricht global ab.

---

### P1-5 · „Hard Delivery Gate" hat keine eigene `failure_class` – der Fix-Loop wiederholt denselben Ansatz blind
**Status:** 🟡 **failure_class erledigt 2026-09-20**, Fix-Loop-Kurzschluss zurückgestellt · **Aufwand:** S · **Wirkung:** mittel

Neuer Fund aus den Läufen `synapsegate` und `chronosvault` (2026-09-20), gegengeprüft über alle
`workspace/*/.ai_team_runs/*_trace.jsonl`: in **7 von ~20** ausgewerteten Projekten
(`aetherqueue` 2×, `chronoflow`, `chronosvault`, `entwickle_das_projekt_sentinel`,
`entwickle_eventforge_ein_webhook`, `logstream_sentinel`, `synapsegate`) schlägt ein
Agenten-Aufruf mit exakt derselben Meldung fehl:

> „Hard Delivery Gate: Agent hat trotz Korrektur-Hinweis keine einzige Datei über
> write_file/edit_file gespeichert – der Tokenverbrauch ist verpufft."

Betroffen ausschließlich Rollen, die einen **Fix auf Basis einer Fehlerdiagnose** liefern sollen
(`tester` 4×, `backend` 2×, `security` 2×) – nicht das Erstschreiben. Bei `chronosvault` war das
der Fehlschlag, der den ganzen Lauf rot färbte (`git log`-Stand vor Sprint 2). Der Mechanismus
selbst (`agents/base_agent.py:608-641`) ist bereits mehrfach nachgeschärft worden (siehe
`agents/team_directives.py:241`/`277`), verhindert False Positives also gut – das Problem liegt
eine Ebene höher: `AgentResult` bekommt dabei `failure_class="agent_error"` wie jeder andere
inhaltliche Fehler (bestätigt im `chronosvault`-Trace). Der Fix-Loop in
`agents/orchestrator/verification.py` kann diesen Fall damit nicht von „Agent hat geliefert, aber
falsch" unterscheiden und schickt beim nächsten Versuch **dieselbe Rolle mit demselben Prompt**
erneut los – obwohl der Agent beim letzten Mal nachweislich gar nichts geliefert hat und ein
identischer Anlauf strukturell dasselbe Ergebnis erwarten lässt.

**Lösung:** Eigene `FAILURE_CLASS_NO_DELIVERY` in `core/provider_exhaustion.py` (analog zu
`FAILURE_CLASS_CANCELLED` aus P1-4). Der Fix-Loop überspringt bei dieser Klasse die normale
Wiederholung und geht direkt zur nächsten Eskalationsstufe (P1-2 Zweitmeinung, oder bei
erreichbarem HEAVY_MODEL sofort die Modell-Eskalation aus P5-1) – ein Wiederholungsversuch mit
identischem Prompt hat hier keine Grundlage, auf der er anders ausfallen könnte.

> **Umsetzung 2026-09-20, bewusst in zwei Schritten getrennt:** `FAILURE_CLASS_NO_DELIVERY`
> existiert jetzt (`core/provider_exhaustion.py`, gesetzt in `agents/base_agent.py`), inklusive
> Test, dass der Fall weiterhin NICHT als Infrastruktur-Fehler zählt (`is_infrastructure_failure`
> unverändert – dem Agenten zurechenbar, er wurde befragt). Die zweite Hälfte – den Fix-Loop in
> `agents/orchestrator/verification.py` bei dieser Klasse aktiv zur nächsten Eskalationsstufe
> springen zu lassen, statt auf den bereits vorhandenen `_no_progress`-Kreisunterbrecher zu warten
> – wurde bewusst **zurückgestellt**: die 2000+ Zeilen lange, vielfach getestete Fix-Loop-Funktion
> ist ein zu hohes Risiko für eine ungeprüfte Kontrollfluss-Änderung in dieser Sitzung. Der
> `_no_progress`-Signaturvergleich fängt den Fall bereits **eine Runde später** ab (ohne Dateien
> ist die nächste Testfehler-Signatur zwangsläufig identisch) – die neue `failure_class` liefert
> das Signal jetzt schon sofort und macht diesen zweiten Schritt zu einer risikoarmen, punktuellen
> Ergänzung für eine künftige Sitzung, statt selbst blockierend zu sein.

---

## 3. 🟡 P2 – Selbstoptimierung der Agenten (wirksam statt gut gemeint)

### P2-1 · Learnings haben keine Wirksamkeitsmessung – die Verdrängung rät
**Status:** ✅ erledigt 2026-09-21 · **Aufwand:** L · **Wirkung:** sehr hoch

`memory/agent_knowledge_base.py` sagt es im eigenen Kommentar (Zeile 74 ff.): *„Eine echte
Wirksamkeitsmessung … würde ein anderes Speicherformat erfordern – `memory/agent_learnings.json`
ist eine schlichte `dict[str, list[str]]`-Struktur ohne Metadaten."* Als Ersatz dient
`_specificity_score()`, eine Heuristik. Real stehen 7 der 22 Agenten am Limit
`MAX_RULES_PER_AGENT = 10`; dort verdrängt jede neue Regel eine alte nach Wortmuster statt nach
Nutzen.

Die Folge sieht man in der Datei: neben sehr wertvollen, spezifischen Regeln
(„Bei In-Memory-SQLite `poolclass=StaticPool` setzen") stehen inhaltsleere Ermahnungen
(„Priorisiere bei API-Engpässen die Identifikation von Showstoppern gegenüber
Stil-Optimierungen.", „Nutze `<summary_state>` zur Vermeidung redundanter Anweisungen im
Kontext.").

**Lösung – Schema-Migration mit Wirksamkeits-Tracking:**

```jsonc
{"backend": [{
  "rule": "…",
  "created_at": "2026-09-19T…",
  "source_project": "cachegrid_proxy",
  "trigger_signature": "F841",   // an welchen Befund die Regel gekoppelt ist
  "injections": 42,              // wie oft in einen Prompt eingefügt
  "violations_before": 11,
  "violations_after": 3
}]}
```

* `trigger_signature` kommt aus dem auslösenden Befund (ruff-Code, Check-Key, Lesson-Signature).
* Nach jedem Lauf prüft ein deterministischer Schritt, ob die Signatur wieder auftrat, und zählt
  hoch – kein zusätzlicher LLM-Aufruf.
* Verdrängt wird die Regel mit der **schlechtesten** Wirksamkeit
  (`violations_after / injections`), nicht die generischste.
* Eine Regel mit `injections > 20` und unveränderter Verletzungsrate wird automatisch als
  „Prompt-Regel wirkungslos → deterministischer Check nötig" gemeldet – genau die Grenze, die der
  `agent_trainer`-Prompt bereits beschreibt (`agents/agent_trainer_agent.py`, Abschnitt
  „WICHTIGE Grenze von Punkt 1").

**Migration:** Abwärtskompatibler Loader (String ⇒ Objekt mit Defaults), damit die vorhandenen
22 Agenten × bis zu 10 Regeln nicht verloren gehen.

**Akzeptanzkriterium:** `/agent-learnings` (CLI) zeigt pro Regel Wirksamkeit und Alter;
`_evict_least_valuable()` nutzt die gemessene Rate, wenn ≥ 5 Injektionen vorliegen, sonst den
bestehenden Spezifitäts-Fallback.

> **Umsetzung (2026-09-21):** `memory/agent_knowledge_base.py` speichert jede Regel jetzt als
> Metadaten-Objekt (`rule`, `created_at`, `source_project`, `trigger_signature`, `injections`,
> `violations_before`, `violations_after`) statt als reinen String. Ein alter String-Eintrag wird
> beim Laden transparent in dieses Schema migriert (`_normalize_entry`) – keine Regel geht
> verloren, `get_learnings()`/`get_all_learnings()` liefern für bestehende Aufrufer unverändert
> reine Regeltexte, neu ist `get_learning_details()` für die Metadaten.
>
> `add_learning()` bekommt optional `trigger_signature` (z. B. `import_name_error:<modul>`,
> `instance_attribute_error:<klasse>` – bereits verdrahtet in
> `agents/orchestrator/failure_diagnosis.py`). Tritt dieselbe Signatur erneut auf, während für
> sie bereits eine Regel existiert, wird KEINE Dublette angelegt, sondern `violations_after` der
> bestehenden Regel hochgezählt – das ist die deterministische, LLM-freie Wirksamkeitsmessung aus
> der Akzeptanzkriterium-Formel (`violations_after / injections`). `get_augmented_prompt()` zählt
> bei jeder Verwendung eine Injektion je enthaltener Regel.
>
> Neue Eviction-Funktion `_evict_least_valuable_entry()`: Liegen für mindestens eine Regel ≥ 5
> Injektionen vor (`MIN_INJECTIONS_FOR_EFFECTIVENESS`), fliegt darunter die mit der schlechtesten
> (höchsten) Verletzungsrate; ohne ausreichend vermessene Regeln fällt sie auf die bestehende
> `_specificity_score`-Heuristik zurück – exakt die im Akzeptanzkriterium geforderte Reihenfolge.
> Eine Regel mit > 20 Injektionen (`INEFFECTIVE_INJECTION_THRESHOLD`) und weiterhin auftretender
> Verletzung wird einmalig als `learning_ineffective`-Team-Lektion gemeldet (Flag im Eintrag
> verhindert Mehrfachmeldung) – dieselbe Grenze, die der `agent_trainer`-Prompt bereits beschreibt.
>
> `/learnings` (CLI, `interface/cli.py._show_learnings`) zeigt zwei neue Spalten: **Wirksamkeit**
> (grün/gelb/rot je nach `1 - effectiveness`, oder `— (n/5)` unterhalb der Mindest-Injektionszahl)
> und **Alter** in Tagen aus `created_at`. `violations_before` bleibt im Schema als Platzhalter für
> eine künftige, dedizierte Vor-Regel-Historie reserviert – die Verdrängungs-/Meldeformel des
> Akzeptanzkriteriums benötigt nur `violations_after`/`injections`.
>
> 11 neue Tests in `tests/test_learning_effectiveness.py` (Migration, Signatur-Dedup/-Zählung,
> Injektionszählung, Wirksamkeitsberechnung, Verdrängungspriorität, einmalige Meldung) plus alle
> 73 bestehenden Learnings-/Prompt-Cache-Tests unverändert grün.

---

### P2-2 · Das Modell-Auto-Tuning optimiert die falsche Zielgröße (Selbst-Degradierungs-Spirale)
**Status:** ✅ erledigt 2026-09-21 · **Aufwand:** M · **Wirkung:** sehr hoch

`memory/auto_tuned_models.json` hat `performance`, `content_lead`, `api_integration`,
`design_lead`, `frontend`, `qa_lead` u. a. von `gemini-3.8-flash` auf `gemini-3.1-flash-lite`
heruntergestuft – begründet mit „Empirisch bessere Erfolgsquote (100 % vs. 72,3 %)".

Diese „Erfolgsquote" kommt aus `memory/run_history.py.get_agent_success_rates()` und bedeutet
**ausschließlich**: der Agenten-Aufruf hat keine Exception geworfen
(`entry["successes"] += 1 if res.get("success")`). Sie sagt nichts über die Qualität des
gelieferten Codes. Parallel liegt die Projekt-Erfolgsquote bei 13 %.

Das schwächere Modell „gewinnt" damit strukturell: es antwortet schneller, macht weniger
Tool-Calls, läuft seltener in Timeouts – und liefert schlechteren Code, den erst die Verifikation
Phasen später bestraft, ohne dass diese Strafe je auf den Agenten zurückgerechnet wird.

**Lösung:**

1. Neue Metrik `agent_quality_score` aus:
   (a) Anteil Läufe mit `verification_ok=True`, an denen der Agent beteiligt war,
   (b) Anzahl Fix-Runden, die auf Dateien dieses Agenten entfielen (`file_owners` liegt vor),
   (c) Anteil Läufe ohne Watchdog-Intervention.
2. `core/optimization_advisor.py`: Downgrade nur vorschlagen, wenn Erfolgsquote **und**
   Qualitäts-Score nicht schlechter werden. Upgrade-Vorschläge symmetrisch erlauben.
3. Die bestehenden Auto-Downgrades einmalig gegen die neue Metrik nachprüfen und dokumentiert
   zurücknehmen, wo sie nicht standhalten.

**Akzeptanzkriterium:** Test, der belegt, dass ein Agent mit 100 % Aufruf-Erfolg, aber
unterdurchschnittlichem Qualitäts-Score **kein** Downgrade vorgeschlagen bekommt.

> **Umsetzung (2026-09-21):** `memory/run_history.py.get_agent_model_performance()` liefert je
> (Agent, Modell) jetzt zusätzlich `quality_rate`: der Anteil der LÄUFE (nicht Aufrufe - ein
> Agent kann mehrfach je Lauf aufgerufen werden, `verification_ok` ist aber eine Eigenschaft des
> gesamten Laufs), in denen diese Kombination vorkam UND die mit `verification_ok=True` endeten.
> Unter `MIN_QUALITY_SAMPLE_RUNS` (3) Läufen bleibt sie `None` (zu wenig Daten für ein Urteil).
> `core/optimization_advisor.py.analyze()` verlangt jetzt für JEDEN Modell-Vorschlag `quality_rate`
> auf BEIDEN Seiten und blockt, wenn das vorgeschlagene Modell dabei nicht mindestens
> gleichauf ist (`MIN_QUALITY_SCORE_GAP_TO_BLOCK`) - ohne Daten lieber kein Vorschlag als ein
> unbelegter Downgrade. Punkt (b)/(c) der ursprünglichen Lösungsskizze (Fix-Runden je
> Datei-Owner, Watchdog-Interventionsquote) sind bewusst NICHT umgesetzt: `memory/run_history.json`
> speichert bisher weder `file_owners` noch Watchdog-Ereignisse je Lauf - das würde eine eigene
> Erweiterung von `record_run()`/den Aufrufstellen in `agents/orchestrator/` erfordern und bleibt
> als Folgearbeit offen; `verification_ok` allein ist bereits ein deutlich robusteres Qualitätssignal
> als die reine Aufruf-Erfolgsquote und reicht für die im Akzeptanzkriterium geforderte Absicherung.
>
> **Punkt 3 (bestehende Auto-Downgrades nachgeprüft):** Reale Messung gegen `memory/run_history.json`
> (200 Läufe) zeigte für 6 der 7 in `memory/auto_tuned_models.json` auf `gemini-3.1-flash-lite`
> heruntergestuften Agenten eine drastisch schlechtere `quality_rate` als beim zuvor
> konfigurierten `gemini-3.8-flash` (z. B. `frontend`: 4,3 % vs. 26,9 %; `design_lead`: 0,0 % vs.
> 40,0 %; `api_integration`: 0,0 % vs. 16,7 %; außerdem `content_lead`, `qa_lead`, `tester`) -
> exakt die im Befund beschriebene Spirale: 100 % Aufruf-Erfolg bei tatsächlich kaum
> verifizierenden Läufen. Diese 6 Einträge wurden manuell auf `gemini-3.8-flash` zurückgenommen
> (mit dokumentierter Begründung + Zeitstempel im jeweiligen Eintrag). `performance` blieb
> unverändert auf `gemini-3.1-flash-lite` (23,5 % vs. 23,1 % `quality_rate` - kein echter
> Unterschied). `memory/auto_tuned_models.json` ist git-ignoriert (lokaler Zustand, kein
> Repo-Commit nötig).
>
> Neue Tests: 2 in `tests/test_optimization_advisor.py` (Vorschlag wird bei schlechter
> Verifikationsqualität trotz besserer Aufruf-Erfolgsquote geblockt; kein Vorschlag ohne
> ausreichende Qualitäts-Stichprobe) und 3 in `tests/test_run_history.py`
> (`quality_rate`-Berechnung: unterhalb der Mindest-Stichprobe `None`, spiegelt `verification_ok`
> statt Aufruf-Erfolg wider, zählt einen Lauf mit mehreren Aufrufen nur einmal).

---

### P2-3 · 13 von 33 Rollen wurden in 20 Läufen kein einziges Mal eingesetzt
**Status:** 🟡 teilweise 2026-09-21 · **Aufwand:** M · **Wirkung:** mittel-hoch

Einsatz in den letzten 20 Läufen: `tester` 48×, `backend` 45×, `dev_lead` 32×, `security` 20×,
`architect` 19×, `frontend` 15×, `qa_lead` 14× — dann fällt es steil ab: `code_reviewer` 6×,
`database` **3×**, `readme`/`finops`/`mobile`/`ml`/`performance`/`api_integration` je 1×.
**Nie eingesetzt:** `devops`, `documentation`, `product_owner`, `refactoring`, `project_cleaner`,
`github`, `compliance`, `ui_ux`, `business_analyst`, `copywriter`, `i18n`, `image_generator`,
`prompt_engineer`, `web_research`.

`memory/team_lessons.jsonl` meldet das seit dem 2026-09-06 als `unused_agent` (12 Einträge) – es
folgte nie eine Konsequenz. Besonders auffällig: der `database`-Agent läuft praktisch nie, obwohl
SQLAlchemy-Fehler zu den häufigsten echten Testfehlern gehören (`aetherqueue`: zwei
konkurrierende `Base`-Definitionen; `devpulse`: `TypeError` in drei Modell-Tests).

**Lösung – Entscheidung statt Dauer-Meldung.** Je Rolle eine der drei Optionen wählen und
umsetzen:

1. **Pflicht-Rolle machen:** `database` und `code_reviewer` als feste Phasen-Teilnehmer, wenn das
   Projekt ein ORM/Schema enthält (deterministisch erkennbar: `sqlalchemy` in `requirements.txt`).
2. **Planer-Beschreibung schärfen:** `core/task_manager.py._relevant_agent_ids()` und der
   Planer-Prompt beschreiben die Rolle offenbar nicht so, dass sie je gewählt wird.
3. **Streichen:** Rollen ohne realistischen Bedarf (`image_generator`, `copywriter`, `i18n` für
   backendlastige Projekte) aus dem Standard-Katalog nehmen – 33 Rollen, von denen 13 Dekoration
   sind, verwässern jeden Planer-Prompt und kosten in jedem Lauf Tokens.

**Akzeptanzkriterium:** `unused_agent`-Lektionen führen automatisch zu einem Backlog-Ticket mit
genau diesen drei Optionen; nach der Abarbeitung liegen ≤ 3 nie genutzte Rollen vor.

> **Umsetzung (2026-09-21, teilweise):** Von den 14 nie eingesetzten Rollen waren 5
> (`copywriter`, `i18n`, `image_generator`, `prompt_engineer`, `web_research`) bereits hinter
> `core/task_manager.py._NICHE_AGENT_TRIGGERS` versteckt - sie erscheinen nur, wenn die Anfrage
> ein passendes Stichwort enthält, und ihr Nicht-Erscheinen in den letzten 20 Läufen ist damit
> kein Fund, sondern der Filter funktioniert wie vorgesehen (keine Aktion nötig). `compliance`
> und `project_cleaner` hatten bereits ein explizites "einbeziehen wenn..."-Kriterium im
> `DECOMPOSE_SYSTEM_PROMPT` - ihre Seltenheit ist plausibel echt (nicht jedes Projekt betrifft
> personenbezogene Daten oder braucht Aufräumarbeiten), daher ebenfalls keine Änderung.
>
> Die verbleibenden 7 Rollen (`product_owner`, `business_analyst`, `ui_ux`, `devops`,
> `documentation`, `refactoring`, `github`) standen dagegen IMMER sichtbar im Zerlegungs-Prompt
> und hatten trotzdem nur eine reine Fähigkeitsbeschreibung ohne WANN-Kriterium - dieselbe
> Ursache, die bei `accessibility`/`finops`/`web_research`/`performance`/`image_generator`/
> `copywriter`/`mobile`/`ml`/`prompt_engineer`/`data_engineer`/`i18n`/`team_lead` bereits per
> "Option 2: Planer-Beschreibung schärfen" behoben wurde (siehe deren Kommentare in
> `core/task_manager.py`). Alle 7 bekamen jetzt dasselbe Muster: eine `AVAILABLE_AGENTS`-
> Beschreibung mit konkretem "Einsetzen bei: (1)/(2)/(3)..."-Kriterium (inkl. Abgrenzung zu
> überlappenden Rollen, z. B. `documentation` vs. `readme`, `refactoring` vs. `code_reviewer`)
> PLUS eine explizite Regel im `DECOMPOSE_SYSTEM_PROMPT`.
>
> `record_unused_agent_tickets()` (`core/optimization_advisor.py`) nennt in der Ticket-Detail
> jetzt wörtlich alle drei Lösungsoptionen aus diesem Roadmap-Eintrag (Pflicht-Rolle machen /
> Planer-Beschreibung schärfen / Streichen) statt nur allgemein auf eine Prüfung zu verweisen.
>
> **Bewusst NICHT umgesetzt:** Option 1 (Pflicht-Rolle für `database`/`code_reviewer` bei
> SQLAlchemy-Projekten) und Option 3 (Rollen streichen) - eine Rolle aus `AVAILABLE_AGENTS` zu
> entfernen hat Blast-Radius über `agents/__init__.py`, `agents/department_lead_agent.py`,
> `agents/orchestrator/__init__.py`, `config.py` und `core/team_board.py` hinweg und braucht
> eine eigene, sorgfältig verifizierte Änderung statt einer Prompt-Schärfung; eine erzwungene
> Pflicht-Teilnahme ändert das Phasen-Routing selbst. Ob ≤ 3 Rollen tatsächlich unused bleiben,
> lässt sich erst nach künftigen echten Läufen messen (`record_unused_agent_tickets()` schließt
> ein Ticket automatisch, sobald die Rolle wieder gewählt wird - siehe
> `close_resolved_unused_agent_tickets()`) - deshalb 🟡 statt ✅.
>
> Neue Tests: `tests/test_unused_agent_prompt_guidance.py` (alle 7 Rollen behalten ein
> "Einsetzen bei"-Kriterium + eine explizite Prompt-Regel) und 1 neuer Test in
> `tests/test_optimization_advisor.py` (Ticket nennt alle drei Optionen wörtlich).

---

### P2-4 · Der Retrospektiv-Schritt arbeitet blind
**Status:** ✅ erledigt 2026-09-21 · **Aufwand:** S · **Wirkung:** mittel

Im Lauf `cachegrid_proxy`: `retrospective` = 1.325 Prompt-Tokens, **0 Tool-Calls**, 0 Dateien.
`agent_trainer` = zwei Aufrufe, 0 Dateien, davon einer mit 88.428 Tokens und 68 s Laufzeit. Der
`root_cause_analyst`-Docstring beschreibt das Problem bereits: der Retrospektiv-Agent bekommt nur
einen auf ~1500-2000 Zeichen gekappten Prosa-Auszug ohne `project_dir`/`allow_tools`.

**Lösung – zwei Varianten, Empfehlung: Variante B.**

* **A:** Dem Retrospektiv-Schritt dieselbe read-only Werkzeugbasis geben wie dem
  Root-Cause-Analysten (`project_dir=BASE_DIR`, `tools_read_only=True`).
* **B (empfohlen):** Ihn auf einen rein deterministischen Schritt reduzieren (Kennzahlen aus
  `outcome`, `run_trace` und `file_owners` zusammenfassen, kein LLM) und die LLM-Analyse allein
  dem Root-Cause-Analysten überlassen. Zwei LLM-Analysen desselben Laufs mit unterschiedlicher
  Evidenztiefe erzeugen widersprüchliche Lektionen – und Variante B spart pro Lauf ~90k Tokens.

> **Umsetzung (2026-09-21, Variante B):** `agents/orchestrator/retrospective.py._run_retrospective()`
> macht KEINEN LLM-Aufruf mehr. Statt eines auf ~250 Zeichen je Agent gekürzten Prosa-Auszugs an
> den `retrospective`-Agenten liefert die Funktion jetzt direkt eine deterministische
> Kennzahlen-Zusammenfassung aus der bereits vorliegenden `results`-Liste (Gesamtdauer,
> Erfolgsquote, Gesamt-Tokens, fehlgeschlagene Agenten mit Fehlermeldung, die drei
> token-intensivsten Agenten) - `total_tokens=0`, keine LLM-Latenz. Die eigentliche LLM-
> Tiefenanalyse bleibt vollständig beim `root_cause_analyst`
> (`_maybe_run_root_cause_analysis()`), der im Gegensatz zum bisherigen Retrospektiv-Schritt
> echten `project_dir`/Werkzeug-Zugriff hat - keine zwei widersprüchlichen LLM-Analysen mehr auf
> unterschiedlicher Evidenztiefe. Der Rückgabewert speist `_run_agent_trainer_self_optimization()`
> unverändert über `retro_content` weiter.
>
> Der `retrospective`-Agent selbst (`agents/retrospective_agent.py`) bleibt registriert/
> instanziiert (kein Umbau der Agenten-Registrierung, dieselbe Vorsicht wie bei P2-3 - kleinerer,
> sicherer Blast-Radius) - er wird nur in diesem Aufruf nicht mehr für eine LLM-Anfrage genutzt.
>
> 3 neue Tests in `tests/test_deterministic_retrospective.py`: kein LLM-Aufruf mehr (ein
> absichtlich fehlschlagender Mock beweist das), Zusammenfassung auch ohne Fehlschläge, `None`
> ohne registrierten `retrospective`-Agenten.

---

## 4. 🟢 P3 – Bessere Fehleranalyse nach Projektende

### P3-1 · Es gibt keinen Projekt-Abschlussbericht als Artefakt
**Status:** ✅ erledigt 2026-09-21 · **Aufwand:** M · **Wirkung:** hoch

Heute entstehen pro Lauf: `.ai_team_runs/<ts>_verification.md` (Prüfprotokoll),
`.ai_team_dod.json` (Kriterien), `.ai_team_status.json` (Historie), `logs/runs/*.jsonl` (Trace).
Was fehlt, ist die Zusammenführung: **ein Post-Mortem pro Lauf**, das die Frage beantwortet
„Warum ist dieses Projekt nicht fertig geworden und was kostet uns das beim nächsten Mal?"

**Lösung – `workspace/<projekt>/.ai_team_runs/<ts>_postmortem.md`, deterministisch erzeugt:**

* **Ergebnis:** DoD-Blocker, blockierende vs. informative Checks (P0-6), Dauer, Tokenverbrauch.
* **Zeitachse:** Phasen, Agenten, Tokens, Tool-Calls, Watchdog-Eingriffe, Modell-Downgrades –
  alles bereits im Trace vorhanden.
* **Fix-Ökonomie:** Wie viele Tokens gingen in *Produktion* vs. in *Reparatur*? (Task-IDs mit
  Präfix `verify_fix_*` sind eindeutig markiert.) In `sentinedge` waren das 3 von 3
  Verifikations-Runden – diese Kennzahl gibt es bisher nirgends.
* **Rollen-Bilanz:** geplant vs. tatsächlich eingesetzt vs. Dateien geschrieben.
* **Verweis** auf die Root-Cause-Tickets, die aus diesem Lauf entstanden sind.

**Akzeptanzkriterium:** Neues Modul `core/run_postmortem.py` plus Test; der Bericht entsteht ohne
zusätzlichen LLM-Aufruf für **jeden** Lauf, auch für grüne.

> **Umsetzung:** Neues Modul `core/run_postmortem.py.generate_postmortem()` – rein
> deterministisch (kein LLM-Aufruf, wie die Retrospektive aus P2-4), aus `agents/orchestrator/
> __init__.py.process()` nach Retrospektive/Trainer/Root-Cause-Analyse aufgerufen (damit auch
> in diesem Lauf neu angelegte Root-Cause-Tickets schon sichtbar sind) und additiv in
> `try/except` eingebettet, damit ein Fehler hier nie einen sonst erfolgreichen Lauf kippt.
> Läuft für JEDEN Lauf, auch bei Budget-Abbruch/manuellem Abbruch, damit auch dort
> nachvollziehbar bleibt, wie weit der Lauf kam. Schreibt
> `workspace/<projekt>/.ai_team_runs/<ts>_postmortem.md` mit: Ergebnis (Verifikation, Dauer,
> Tokens, Dateien, blockierende vs. informative fehlgeschlagene Checks aus P0-6s
> `VerificationOutcome`), Fix-Ökonomie (Produktion vs. Reparatur-Tokens – ein Aufruf gilt als
> Reparatur, wenn seine `task_id` eines der Muster `fix`/`recheck`/`escalation`/`governance_`/
> `verify_`/`autofix` aus dem Verifikations-/Governance-Fixloop enthält), Rollen-Bilanz
> (geplant aus `agent_tasks` vs. tatsächlich eingesetzt vs. Dateien je Rolle), Zeitachse (aus
> dem bereits vorhandenen `core/run_trace.py`-Projekt-Trace) und offene Root-Cause-Tickets
> desselben Projekts (`core/backlog_store.py`, `source == "root_cause_analysis"`). 4 neue Tests
> in `tests/test_run_postmortem.py`; Wiring zusätzlich gegen 4 bestehende End-to-End-
> Integrationstests verifiziert (`test_governance_fix_loop.py`,
> `test_completeness_measured_despite_budget.py`, u.a., 19 Tests grün), um sicherzustellen,
> dass der neue Aufruf in `process()` echte Läufe nicht bricht.

---

### P3-2 · Kein Trendbericht über Läufe hinweg
**Status:** ✅ erledigt 2026-09-21 · **Aufwand:** M · **Wirkung:** hoch

`--team-retro` und `--weekly-digest` existieren, aber die wichtigste Frage – *„Werden wir
besser?"* – beantwortet nichts. Die Zahl „13 % grün über 152 Läufe" musste für diese Roadmap von
Hand ausgerechnet werden.

**Lösung – `python main.py --team-trend [--days N]`:**

* Erfolgsquote pro Woche (rollierend), Ø Tokens/Lauf, Ø Fix-Runden/Lauf.
* Top-5-Blocker nach Häufigkeit über alle Läufe (setzt P0-5 voraus).
* Wirksamkeit der Learnings (setzt P2-1 voraus): welche Regeln haben ihren Befund verschwinden
  lassen, welche nicht.
* Regressions-Warnung: Kennzahl über die letzten 10 Läufe schlechter als über die 10 davor.

> **Umsetzung:** Neues Modul `core/team_trend.py.build_team_trend()`, `python main.py
> --team-trend [--days N]` (Standard 30 Tage). Rein deterministisch, komplett aus bereits
> bestehenden Datenquellen zusammengesetzt: rollierende Wochen-Erfolgsquote und Ø Tokens/Lauf
> aus `memory/run_history.json`; Top-5-Blocker über ALLE (nicht nur die jeweils neuesten)
> Läufe je Projekt aus `workspace/*/.ai_team_status.json` mittels `core/team_health.py.
> categorize_failure()` (P0-5); Wirksamkeit der Learnings aus `memory/agent_learnings.json`
> über die in P2-1 eingeführten `effectiveness`-Werte (Vorzeichen für die Anzeige umgedreht:
> `_effectiveness_rate()` liefert `violations_after / injections`, niedriger = besser - der
> Bericht zeigt wie `interface/cli.py._show_learnings()` "% wirksam", höher = besser);
> Regressions-Warnung durch Vergleich der letzten 10 mit den 10 Läufen davor. Ø
> Reparatur-Aufrufe/Lauf liest die `Reparatur (...): N Tokens (M Aufruf(e))`-Zeile aus den in
> P3-1 neu eingeführten `workspace/*/.ai_team_runs/*_postmortem.md`-Berichten - liegen (noch)
> keine vor, weist der Bericht das offen als "keine Post-Mortem-Berichte gefunden" aus statt
> stillschweigend 0 anzuzeigen. Gegen echte Produktivdaten geprüft (`--team-trend --days 30`
> über 155 reale Läufe). 8 neue Tests in `tests/test_team_trend.py`.

---

### P3-3 · Root-Cause-Analyse verbrennt Aufrufe für Trivialbefunde
**Status:** ✅ erledigt 2026-09-21 · **Aufwand:** S · **Wirkung:** mittel

`root-cause-cachegrid_proxy-unbenutzte-variablenzuweisung-…`: eine vollständige, werkzeugbasierte
LLM-Tiefenanalyse mit Repository-Zugriff für **eine ungenutzte Variable** (ruff `F841`), die
`ruff --fix --unsafe-fixes` in Millisekunden behebt.

**Lösung:** `should_trigger()` (`core/root_cause_analyst.py:244`) zusätzlich an `failed_blocking`
koppeln (P0-6) und eine Ausschlussliste für rein informative bzw. deterministisch behebbare
Befundklassen einführen.

> **Umsetzung (2026-09-21):** `should_trigger()` bekommt ein neues Argument
> `has_blocking_failure` (Default `True` - bestehende Aufrufer ohne dieses Argument behalten ihr
> bisheriges Verhalten). Der `not verification_ok and files_written > 0`-Zweig löst nur noch
> aus, wenn zusätzlich `has_blocking_failure=True` ist.
> `agents/orchestrator/retrospective.py._maybe_run_root_cause_analysis()` liest dafür
> `self.last_verification_outcome` (bereits seit P0-6 vorhanden) aus und reicht
> `bool(outcome.blocking_failed_checks)` durch - ein rein informativer Befund wie `lint`
> (F841 & co., `INFORMATIONAL_CHECK_KEYS`) landet damit nicht mehr in `blocking_failed_checks`
> und löst folglich keine kostenpflichtige Tiefenanalyse mehr aus. Fällt `last_verification_
> outcome` aus irgendeinem Grund nicht auf eine echte `VerificationOutcome`-Instanz zurück
> (z. B. in Alt-Tests), greift sicherheitshalber das bisherige, gröbere `not verification_ok`
> als Ersatzsignal, statt stillschweigend nie mehr auszulösen.
>
> Eine SEPARATE Ausschlussliste für "deterministisch behebbare Befundklassen" (zweiter Teil der
> ursprünglichen Lösungsskizze) wurde bewusst NICHT zusätzlich eingeführt: `INFORMATIONAL_CHECK_
> KEYS` deckt den beschriebenen Fall (lint/F841) bereits vollständig über die `has_blocking_
> failure`-Kopplung ab, ohne einen zweiten, separat zu pflegenden Mechanismus mit potenziell
> abweichender Klassifikation zu benötigen.
>
> 5 neue Tests in `tests/test_root_cause_analyst.py`: `should_trigger()` mit/ohne
> `has_blocking_failure`, Rückwärtskompatibilität ohne das neue Argument, sowie zwei
> Orchestrator-Integrationstests (`TestMaybeRunRootCauseAnalysisWiring`), die belegen, dass ein
> reiner `lint`-Fehlschlag `run_analysis()` NICHT aufruft, ein echter `tests`-Fehlschlag dagegen
> schon.

---

### P3-4 · `team_lessons.jsonl` ist uneinheitlich und teilweise unlesbar
**Status:** ✅ erledigt 2026-09-21 · **Aufwand:** S · **Wirkung:** mittel

> **Umsetzung:** Nachprüfung ergab, dass core/team_memory.py die 21 vermeintlich „category-losen"
> Einträge bereits absichtlich als eigene Ereigniszeilen führt (`event: lesson_recurrence` /
> `event: lesson_status`, siehe `_append_event()`) und `read_team_lessons()` diese sauber von den
> 81 echten Lektionen (`category`/`detail`/`project_slug`/`timestamp`) trennt – die ursprüngliche
> Analyse stammte aus der Zeit vor dieser Trennung. Die reale Datei war beim erneuten Prüfen
> bereits vollständig valide (0 kaputte/unvollständige Zeilen). Offen war nur, dass diese
> Schema-Erwartung nirgends **erzwungen** wurde und `python main.py --clean-telemetry` – anders
> als für `run_history.json`/`eval_history.json` – keine Normalisierung für Altbestände in
> `team_lessons.jsonl` anbot. Neu: `core/telemetry_hygiene.py.clean_team_lessons()` validiert
> jede Zeile gegen das Zwei-Formen-Schema (Lektion: `category`/`detail`/`project_slug`/
> `timestamp` nicht-leer, `signature` optional – wird bei Bedarf aus category+detail
> nachberechnet wie in `_entry_signature()`; Ereignis: `event` ∈
> `{lesson_recurrence, lesson_status}` mit `signature`/`timestamp`) und entfernt schema-widrige
> Zeilen (kaputtes JSON, leere Pflichtfelder, unbekannter Ereignistyp) mit Sicherungskopie,
> genau wie die bestehenden `clean_run_history()`/`clean_eval_history()`. `--clean-telemetry`
> ruft das jetzt als dritten Schritt mit auf. Bewusst NICHT umgesetzt: die im Roadmap-Entwurf
> vorgeschlagene Umbenennung von `lesson_recurrence` zu einem `category`-Wert – das bestehende
> `event`-Feld-Design trennt Lektionen und Buchführungs-Ereignisse bereits eindeutiger als eine
> gemeinsame `category`-Spalte es würde, eine Migration hätte hier ohne echten Zusatznutzen nur
> Risiko für den funktionierenden Lifecycle (`read_lesson_index()`, `update_lesson_status()`)
> erzeugt. 4 neue Tests in `tests/test_team_lessons_schema.py`, u.a. ein Regressionstest, der die
> echte `memory/team_lessons.jsonl` gegen das Schema prüft.

---

## 5. 🔵 P4 – „Wie ein echtes Entwicklerteam" arbeiten

### P4-1 · Code-Review ist optional statt Standard
**Status:** ✅ erledigt 2026-09-21 · **Aufwand:** M · **Wirkung:** hoch

`code_reviewer` lief in 6 von 20 Läufen; in `cachegrid_proxy` mit 2 Tool-Calls, 0 geschriebenen
Dateien und 20.360 Tokens – also ein Kommentar ins Leere. In einem echten Team geht kein Code
ohne Review in den Merge.

**Lösung:** Die `governance_lead`-Phase verbindlich machen, wenn Code geschrieben wurde, und den
Review in einen **Befund-mit-Pflicht-Antwort-Zyklus** überführen: jeder Review-Befund wird
entweder behoben oder mit Begründung als `wontfix` im Team-Board quittiert. `core/review_gate.py`
(438 Zeilen) existiert bereits – zuerst prüfen, warum es nicht greift.

> **Umsetzung:** Root Cause geklärt: `core/review_gate.py` selbst funktioniert (Fund-Erkennung,
> Fix-Schleife, Re-Review, Eskalation zu einem `unresolved-governance-critical-*`-Backlog-Ticket
> via `agents/orchestrator/governance.py` - das ist bereits der faktische
> "Befund-mit-Pflicht-Antwort-Zyklus", ein Fund verschwindet nie stillschweigend, sondern landet
> entweder als behoben oder als offenes Ticket zur menschlichen Entscheidung). Es griff nur nie,
> weil `agents/orchestrator/__init__.py` `code_reviewer`/`refactoring`/`compliance`/… bei
> `ENABLE_REVIEW_AFTER_VERIFICATION` komplett aus der Ausführung ausklammert
> (`deferred_review_tasks`), wenn der LLM-Planer (`core/task_manager.py`) sie nicht von sich aus
> einplant - `agents/orchestrator/integration.py._run_review_after_verification()` beendete sich
> dann mit `if review_tasks:` sofort, ohne je zu prüfen, ob überhaupt Code entstanden ist. Neu:
> direkt vor diesem Check wird `code_reviewer` zusätzlich eingeplant, wenn `review_tasks` leer
> ist, `code_reviewer` als Rolle verfügbar ist UND mindestens ein Agent in diesem Lauf
> tatsächlich Dateien geschrieben hat - dieselbe deterministische "Pflicht-Einplanung"-Logik wie
> der bereits bestehende `architect`-Zwang nach wiederholtem Scheitern
> (`agents/orchestrator/__init__.py`). Ein bestehender Test
> (`tests/test_governance_fix_loop.py.test_review_only_agent_absent_adds_no_section`) prüfte
> exakt das alte, jetzt bewusst geänderte Verhalten ("kein Reviewer geplant → keine Sektion") -
> umbenannt/umgedreht zu `test_review_only_agent_absent_but_code_written_forces_review_section`.
> 2 neue Tests in `tests/test_p1_team_workflow.py.TestMandatoryCodeReview` (erzwungen bei
> geschriebenem Code, NICHT erzwungen ohne jede Dateiänderung). Gegen 48 bestehende
> End-to-End-Integrationstests verifiziert (u.a. `test_governance_fix_loop.py`,
> `test_frontend_build_integration.py`, `test_run_cancellation.py`), keine Regression.

---

### P4-2 · Keine Abnahme gegen die ursprüngliche Anforderung
**Status:** ✅ erledigt 2026-09-21 · **Aufwand:** M · **Wirkung:** hoch

Die Definition of Done prüft technische Eigenschaften (Tests laufen, App startet, keine Secrets).
Niemand prüft: *Haben wir gebaut, was bestellt war?* Beispiel `cachegrid_proxy` – bestellt waren
u. a. „Write-Behind-Strategie", „Key-Tagging und selektive Invalidierung", „vollständige
pytest-Suite für Race Conditions und Cache-Eviction". Geliefert wurden **3 Testfunktionen**, die
die Testtiefen-Prüfung mit „1/1 API-Routen (100 %)" passieren – weil das Projekt nur eine Route
deklariert. Die Kennzahl war grün, die Anforderung nicht erfüllt.

**Lösung:** Der `product_owner`-Agent (existiert, wird nie eingesetzt – siehe P2-3) bekommt einen
festen Abnahme-Schritt: Anforderungsliste aus dem Auftragstext extrahieren (einmal, in Phase 1,
als `.ai_team_acceptance.json` persistiert), am Ende gegen den echten Code prüfen und als
DoD-Kriterium `requirements_met` aufzeichnen.

**Akzeptanzkriterium:** Ein Lauf mit 6 bestellten Features, von denen 3 fehlen, endet mit
`is_done: false` und benennt die 3 fehlenden Features namentlich.

> **Umsetzung:** Neues Modul `core/acceptance_check.py`, zwei zusätzliche `product_owner`-
> LLM-Aufrufe je Lauf (nur wenn `ENABLE_ACCEPTANCE_CHECK`, Standard an): Phase 1
> (`extract_requirements()`, ohne Tool-Zugriff) destilliert den Auftragstext direkt nach
> Projekt-Anlage, VOR jeder Fachbereichs-Phase, in eine nummerierte Anforderungsliste und
> persistiert sie als `.ai_team_acceptance.json`. Phase 2 (`verify_acceptance()`, mit
> Lese-Tool-Zugriff `tools_read_only=True` - derselbe Modus wie `core/roadmap_advisor.py`) läuft
> nach Entwicklung/Verifikation, nur wenn tatsächlich Code geschrieben wurde, und prüft jede
> Anforderung `list_files`/`read_file`/`search_code` GEGEN DEN ECHTEN CODE. Beide Antworten
> werden strikt über die Zeilennummer geparst (nicht per Textähnlichkeit, robuster gegen
> Umformulierung) - lässt sich eine Antwort nicht sauber im geforderten Format auswerten
> (Zeilenzahl passt nicht zur Anforderungszahl), blockiert das bewusst NICHT (`parsed=False` →
> `requirements_met=None`), damit ein Formatfehler im LLM-Text nie fälschlich ein sonst fertiges
> Projekt blockiert. `core/definition_of_done.py` bekommt das neue, verpflichtende Kriterium
> `requirements_met` (nur `applicable`, wenn die Prüfung überhaupt lief), das die fehlenden
> Anforderungen im `detail`-Feld namentlich benennt. 20 neue Tests (`tests/test_acceptance_
> check.py`, `tests/test_definition_of_done.py`). Ergänzt, nicht ersetzt, die bereits bestehende
> `ACCEPTANCE_CRITERIA_CHECK_INSTRUCTION` in `core/result_aggregator.py` (dort nur eine
> Prompt-Anweisung an den ohnehin laufenden Synthese-Aufruf ohne echten Code-Zugriff - genau die
> Schwäche, die der reale `cachegrid_proxy`-Fund zeigte). Gegen 70 bestehende End-to-End-
> Integrationstests verifiziert, keine Regression.

---

### P4-3 · Testtiefe misst Routen, nicht Fachlichkeit
**Status:** 🟡 teilweise 2026-09-21 · **Aufwand:** M · **Wirkung:** mittel-hoch

`core/test_depth.py` misst „Anteil der API-Routen, die im Test aufgerufen werden". Bei
`cachegrid_proxy` (1 Route) und `nexus_mesh` (2 Routen) ergibt das trivial 100 %, obwohl die
eigentliche Fachlogik (LRU-Eviction, TTL-Verfall, Thundering-Herd-Mutex,
Circuit-Breaker-Zustände) ungetestet blieb.

**Lösung:** Zusätzliches, deterministisches Signal: Anteil der öffentlichen Funktionen/Klassen in
`app/core/`, `app/services/`, `app/domain/`, die in mindestens einem Test importiert **und**
aufgerufen werden. `core/code_graph.py` (495 Zeilen) liefert die Grundlage dafür bereits.

> **Umsetzung:** `core/test_depth.py.analyze_domain_logic_depth()` (neu) baut auf
> `core/code_graph.py.CodebaseGraph` auf: identifiziert öffentliche Funktionen/Klassen/Methoden
> in Verzeichnissen namens `core`/`services`/`domain`/`logic` und prüft je Symbol, ob sein Name
> in mindestens einer Testdatei sowohl IMPORTIERT als auch AUFGERUFEN wird (reiner Import ohne
> Aufruf zählt nicht). Neues, eigenständiges `VerificationOutcome`-Check `domain_logic_depth`,
> in `agents/orchestrator/verification.py` einmalig am Ende der Verifikations-Pipeline erfasst
> (`ENABLE_DOMAIN_LOGIC_DEPTH_SIGNAL`, Standard an; Schwelle `MIN_DOMAIN_LOGIC_TEST_RATIO`,
> Standard 0.5). Bewusst **rein informativ** (`INFORMATIONAL_CHECK_KEYS`, `required=False` wie
> `coverage`/`lint`) statt blockierend, deshalb "teilweise": ein AST-Aufruf-Abgleich hat reale
> blinde Flecken (Decorator-Aufrufe, Dependency-Injection-Container, dynamischer Dispatch) - ein
> KI-generiertes Symbol kann trotz echtem Test fälschlich als ungetestet erscheinen. Ohne
> Kalibrierung an echten Läufen wäre ein blockierendes Gate hier ein Risiko für viele
> falsch-positive Blockaden bisher grüner Projekte (anders als beim bereits bestehenden,
> route-basierten `test_depth`, der über mehrere Läufe hinweg beobachtet werden konnte, bevor er
> blockierend wurde). Auch bewusst kein eigener Fix-Loop (anders als bei `test_depth`) - das
> Signal ist zunächst nur sichtbar, keine automatische Nachbesserungs-Runde. Sobald echte
> Lauf-Daten die Falsch-Positiv-Rate belegen, kann das Kriterium regulär auf blockierend
> umgestellt werden (Analog zu P0-6/P3-3s Blocking-vs-Informational-Unterscheidung). 5 neue
> Tests in `tests/test_test_depth.py`. Gegen 160 bestehende Tests (u.a. `test_p0_structured_
> verification.py`, `test_governance_fix_loop.py`) verifiziert, keine Regression.

---

### P4-4 · Kein geteiltes Kurzzeitgedächtnis während der Entwicklungsphase
**Status:** 🟡 **früher Abfang + zuverlässige Vertragsdatei erledigt 2026-09-21**, echte Prompt-Injektion vor dem ersten Schreiben weiterhin offen · **Aufwand:** M · **Wirkung:** mittel

`core/message_bus.py` sagt im eigenen Docstring, dass die echte Publish/Subscribe-Klasse entfernt
wurde, weil sie nie genutzt wurde. Die Koordination läuft über `core/team_board.py` – ein
Datei-Zustand, den Agenten nur lesen, wenn sie explizit dazu aufgefordert werden. Folge: der
Tester erfindet die Route `GET /api/dlq` (`aetherqueue`), obwohl das Backend sie nie deklariert
hat – und drei Fix-Runden scheitern daran.

**Lösung:** Vor jedem codeschreibenden Agentenaufruf einen **deterministisch erzeugten
Projekt-Steckbrief** in den Prompt injizieren (kein LLM): tatsächlich vorhandene Routen,
Modul-Symbole und Modelle, direkt aus `core/code_graph.py` / `core/contract_verifier.py`.
Ein Tester, der die echte Routenliste im Kontext hat, erfindet keine.

> **Präzisierung 2026-09-20, Fund in `synapsegate`:** Dieselbe Fehlerklasse trat erneut auf –
> `tests/test_events_api.py` ruft `POST /api/v1/events/` und `GET /api/v1/events/dlq` auf, beide
> existieren im Backend nicht (Completeness-Check deckte es auf, nach bereits verbrauchten
> Tokens für die falschen Tests). Die genaue Lücke ist jetzt lokalisiert: `contract_review`
> (Trace-Event `contract_review`, `endpoints=3, calls=0` bei diesem Backend-only-Projekt) prüft
> **ausschließlich** Frontend↔Backend-Feldabgleich – zwischen `tester` und `backend` gibt es
> **keinen** äquivalenten Abgleich, weder vorher (Prompt-Injektion) noch güterschützend danach
> (der Vergleich läuft erst spät im AST-Completeness-Check mit). `interface_contract.json` wird
> für Backend-only-Projekte offenbar gar nicht erst angelegt (bei `synapsegate` fehlt die Datei
> komplett, bei `chronosvault` mit Frontend existiert sie) – die Lösung oben darf sich also nicht
> auf `contract_review` stützen, sondern muss unabhängig von einem vorhandenen Frontend laufen.

> **Umsetzung 2026-09-20, Analyse und bewusste Entscheidung:** Die ursprünglich vorgeschlagene
> Prompt-Injektion (echte Routen VOR dem Schreiben in den Kontext geben) griffe hier NICHT: im
> Test-First-Modus (`ENABLE_TEST_FIRST`, Standard aktiv) arbeitet `tester` laut
> `agents/orchestrator/department.py._TEST_FIRST_NOTE` bewusst **parallel** zu `backend` in
> derselben Phase, gegen `interface_contract.json`/die Akzeptanzkriterien statt gegen fertigen
> Code – bei ≥3 Mitgliedern der dev_lead-Phase laufen beide Rollen sogar echt gleichzeitig
> (`asyncio.gather`, siehe `effective_run_mode`). Zum Zeitpunkt der Prompt-Erstellung existieren
> die realen Backend-Routen oft schlicht noch nicht - es gäbe nichts zu injizieren. Die
> eigentliche Ursache liegt eine Ebene höher (verlässt sich `interface_contract.json`,
> geschrieben vom Architekten, das aber für Backend-only-Projekte laut Fund oben nicht
> zuverlässig entsteht) und wäre ein eigener, größerer Eingriff in die Planungsphase.
>
> **Stattdessen umgesetzt: ein deterministischer, verzögerter Abfang statt einer Vermeidung.**
> `_run_test_route_mismatch_preflight()` (`agents/orchestrator/department.py`) läuft direkt nach
> der Test-First-Entwicklungsphase – am selben Punkt wie der bereits vorhandene
> Einstiegspunkt-Pre-Flight, nur EINMAL, BEVOR performance/readme/qa_lead/security/
> resilience_guard (bei `synapsegate` fünf weitere Phasen) auf dem fehlerhaften Stand
> weiterarbeiten. Nutzt die bereits vorhandenen, rein statischen Detektoren
> `_test_requests_undeclared_routes()` und `_unwired_api_routers()`
> (`core/verifier/completeness.py`, kein LLM-Aufruf, keine Testausführung) und dispatcht bei
> einem Fund GENAU EINEN gezielten Fix-Task – an `tester` bei erfundenen Testrouten, an den
> bekannten Datei-Eigentümer (Fallback `backend`) bei einem nie verbundenen Router. Abgesichert
> mit demselben `is_safe_project_dir()`-Framework-Root-Schutz wie der bestehende
> Integrations-Checkpoint. Läuft NUR, wenn `test_first_active` UND `tester` tatsächlich an der
> Phase beteiligt war – ohne Test-First liest `tester` beim Schreiben in der QA-Phase ohnehin
> schon den echten Code. Abgedeckt durch `tests/test_route_mismatch_preflight.py` (6 Tests,
> inkl. Reproduktion des synapsegate- UND des hyperion_metrics-Funds) sowie zwei neue Tests in
> `tests/test_p1_team_workflow.py`, die den Aufruf nur unter Test-First erwarten. **Offen bleibt**
> die eigentliche Prompt-Injektions-Lösung als Vermeidung statt Nach-Korrektur – dafür müsste
> zuerst sichergestellt werden, dass `interface_contract.json` auch für Backend-only-Projekte
> zuverlässig entsteht.

> **Umsetzung 2026-09-21, die genannte Voraussetzung geschlossen:** Neues Modul
> `core/interface_contract.py.ensure_interface_contract()` - rein additiv, überschreibt NIE eine
> bereits vom architect geschriebene Datei, trägt `interface_contract.json` aber deterministisch
> (kein LLM-Aufruf, `core/code_graph.py`) nach, wenn sie nach der Entwicklungsphase noch fehlt:
> alle Top-Level-Klassen/-Funktionen (keine Methoden, keine privaten Namen, keine Testdateien)
> aus dem tatsächlich geschriebenen Code. Läuft in `agents/orchestrator/department.py` am selben
> Checkpoint wie der bereits bestehende `_run_test_route_mismatch_preflight()` (nach `dev_lead`),
> damit `qa_lead`/`governance_lead`/spätere Fix-Runden ab hier wenigstens einen echten Vertrag
> vorfinden statt gar keinen - schließt die vorherige Analyse-Lücke ("bei `synapsegate` fehlt die
> Datei komplett"). Deckt bewusst nur `class`/`function` ab, nicht `instance`/`constant` (aus
> reiner AST-Analyse nicht zuverlässig von einer beliebigen Modulvariable unterscheidbar) - ein
> gröberer, aber immerhin vorhandener Vertrag statt keinem. Abgesichert mit demselben
> `is_safe_project_dir()`-Framework-Root-Schutz wie `core/project_scaffold.py` - ein erster
> Entwurf ohne diese Schranke schrieb bei einem Test mit `project_dir="."` (Framework-Root)
> tatsächlich eine `interface_contract.json` mit dem gesamten Framework-Quellcode ins Repo-Root;
> beim Verifizieren aufgefallen, vor dem Commit korrigiert und mit einem eigenen Regressionstest
> abgesichert. 8 neue Tests in `tests/test_interface_contract.py`. **Weiterhin offen:** die eigentliche Vermeidung (echte
> Routen VOR dem ersten Schreiben in den Prompt injizieren) bleibt architektonisch schwierig,
> solange `tester` im Test-First-Modus PARALLEL zu `backend` arbeitet und die Routen zu diesem
> Zeitpunkt schlicht noch nicht existieren (siehe Analyse 2026-09-20 oben) - dafür bräuchte es
> einen größeren Eingriff in die Phasen-Reihenfolge selbst, kein reines Kontext-Problem mehr.

---

### P4-5 · Foreign-Changes: Agenten überschreiben fremden Code
**Status:** ✅ erledigt (bereits vor dieser Sitzung behoben, hier nur nachgeprüft) · **Aufwand:** S · **Wirkung:** mittel

Aus `logs/FEHLERANALYSE_KI_TEAM_20260916.md`, Problem 4: der `security`-Agent überschrieb
`app/main.py` und `app/api/endpoints.py` (Eigentümer: `backend`); der Security-Report konnte
deshalb nicht sauber geschrieben werden. `core/write_guard.py` existiert – prüfen, ob es diesen
Fall abdeckt, und ggf. auf „Fremddatei nur per `edit_file` mit Begründung im Team-Board"
verschärfen.

> **Nachprüfung 2026-09-21:** `config.py.AGENT_WRITE_SCOPES["security"]` deckt genau diesen
> Fund bereits ab (Kommentar dort datiert auf den cloudpulse-Lauf vom 16.09., derselbe Vorfall)
> - `security` darf seither nur noch eigene Dateien (`*security*`, `*auth*`,
> `.env.example`, Abhängigkeits-/Tooling-Manifeste, `*__init__.py`) schreiben, `app/main.py`/
> `app/api/endpoints.py` sind für die Rolle über `check_write_scope()`
> (`core/write_guard.py`, in `core/agent_toolbox.py` an allen vier Schreib-Werkzeugen verankert)
> blockiert - Änderungen an fremden Backend-Dateien beschreibt `security` seitdem im eigenen
> Bericht statt sie selbst zu schreiben (noch strenger als die vorgeschlagene "edit_file mit
> Begründung", die einen Fremdzugriff mit Begründung weiterhin erlaubt hätte). Belegt durch
> `tests/test_cloudpulse_regressions.py` (u.a. `foreign_changes`-Fall) und
> `tests/test_write_guard.py`, beide grün (29 Tests). Kein Code-Fund mehr offen - lediglich der
> Roadmap-Status war seit der Umsetzung nicht aktualisiert worden.

---

## 6. 🟣 P5 – Kosten, Kapazität & Modell-Realität

### P5-1 · Alle Premium-Modelle liegen auf Cooldown – das Team läuft dauerhaft im Notbetrieb
**Status:** ✅ **alle drei Punkte erledigt 2026-09-21** · **Wirkung:** sehr hoch

`memory/provider_cooldowns.json` – aktueller Stand:

| Modell | Grund | Cooldown |
| :--- | :--- | :--- |
| `claude-opus-5` | „Claude Nutzungslimit erschöpft" | 24 h |
| `claude-sonnet-5` | „Claude Nutzungslimit erschöpft" | 24 h |
| `deepseek:deepseek-chat` | „Insufficient Balance" | 24 h |
| `openrouter:openrouter/auto` | „requires more credits" | 24 h |
| `gemini-pro-latest` | „429 Quota Exceeded (alle Gemini-Keys erschöpft)" | 12 h |

Im Lauf `cachegrid_proxy` wurden **7 von 9** Agenten-Aufrufen heruntergestuft
(`gemini-pro-latest` → `gemini-3.8-flash`). Die HEAVY_MODEL-Eskalation, auf die sich die
Fix-Schleifen als letzte Rettung verlassen, erreicht ihre Zielstufe nicht – im Lauf
`eventforge_core` steht das wörtlich im Protokoll: „HEAVY_MODEL-Eskalation für tester griff nicht
tatsächlich (Kontingent-Erschöpfung o. ä.)". Das Ticket `recurring-failure-eventforge_core`
bezeichnet sich selbst als „eher ein Infrastruktur-/Kontingent- als ein Agenten-Problem".

**Aufgaben:**

1. **Ehrlicher Degraded-Mode:** Ist die HEAVY-Stufe beim Lauf-Start nicht erreichbar
   (`core/model_preflight.py` misst das bereits), den Lauf **sichtbar als „degradiert"**
   kennzeichnen – im Trace, im Abschlussbericht und in `run_history`. Läufe im Degraded-Mode
   dürfen die Modell-Auto-Tuning-Statistik (P2-2) **nicht** speisen.
2. **Eskalation ohne Zielstufe unterlassen:** Ist `HEAVY_MODEL` nachweislich nicht erreichbar,
   den „letzten Versuch mit HEAVY_MODEL" überspringen statt ihn wirkungslos zu verbrennen (real
   beobachtet in `aetherqueue` und `eventforge_core`).
3. **Kapazitäts-Gate schärfen:** `core/capacity_gate.py` blockiert nur, wenn eine kritische Rolle
   *gar kein* Modell über ihrer Mindeststufe hat. Zusätzlich warnen, wenn ≥ 50 % der geplanten
   Rollen herabgestuft starten müssten – und nachfragen, ob der Lauf trotzdem starten soll.

> **Umsetzung Punkt 1 (2026-09-21):** `agents/orchestrator/__init__.py.process()` prüft direkt
> nach der Plan-Freigabe `core/capacity_gate.py.model_unreachable_reason(HEAVY_MODEL)` (kein
> zusätzlicher Netzwerk-Ping - derselbe deterministische Key-/Kontingent-Check, den P5-1 Punkt 2
> bereits nutzt) und hält das Ergebnis als `self.last_run_degraded_reason`. Ist HEAVY_MODEL nicht
> erreichbar: sofortige Notification, ein `run_degraded_mode`-Trace-Event, ein eigener Absatz im
> Abschlussbericht, und `memory/run_history.py.record_run()` bekommt ein neues `degraded`-Feld.
> `get_agent_model_performance()` (P2-2) zählt degradierte Läufe NICHT mehr in `quality_runs`/
> `quality_ok_runs` mit (weiterhin aber in `calls`/`successes` - die reine Aufruf-Erfolgsquote
> ist von der Modellstärke unabhängig), damit ein reiner Kontingent-Engpass nie als
> Qualitätsmangel eines Modells fehlinterpretiert wird.
>
> **Umsetzung Punkt 3 (2026-09-21):** `CapacityAssessment` bekommt `downgraded_agent_ids`/
> `downgraded_ratio`/`mostly_downgraded` (Schwelle `MOSTLY_DOWNGRADED_THRESHOLD = 0.5`) -
> berechnet über ALLE eingeplanten Rollen (nicht nur die kritischen wie beim Blockade-Check
> oben), da ein Qualitätsrisiko durch Herabstufung für den GESAMTEN Lauf gilt. Ab der Schwelle
> erscheint zusätzlich zur Warnung eine aktive Rückfrage - wiederverwendet dasselbe
> `plan_confirmation_callback`-Bestätigungs-Gate wie die reguläre Plan-Freigabe (kein neues UI
> nötig); ohne Callback (unbeaufsichtigte Läufe wie `--work-backlog`) bleibt es bei der
> Warnung, der Lauf startet wie bisher. 5 neue Tests in `tests/test_capacity_gate.py`
> (`TestMostlyDowngradedWarning`), 2 in `tests/test_run_history.py`, 5 in
> `tests/test_degraded_mode_and_capacity_confirmation.py`. Gegen 147 bestehende Tests
> verifiziert (u.a. `test_plan_confirmation_gate.py`, `test_governance_fix_loop.py`,
> `test_p1_team_workflow.py`), keine Regression. Punkt 2 bereits 2026-09-20 erledigt (siehe
> `core/capacity_gate.py.model_unreachable_reason()`-Docstring).

---

### P5-2 · Ein Lauf kostet ~870k Tokens, davon der Großteil wiederholter Prompt-Kontext
**Status:** 🟡 **Aufgabe 1 (Gemini-Caching) erledigt 2026-09-20**, Aufgaben 2+3 offen · **Aufwand:** M · **Wirkung:** hoch

Aus dem `cachegrid_proxy`-Trace: `prompt_tokens` 638.581 bei `cache_read_tokens` 182.588 →
**Cache-Trefferquote 28,6 %**. Ein einzelner `backend`-Aufruf: 237.401 Prompt-Tokens bei 13
Tool-Calls und nur 10.706 Completion-Tokens – der Kontext wird bei jedem Tool-Call praktisch
vollständig neu gesendet. Zwei Läufe (`sentinedge`, `eventforge_core`) erreichten das
1-Mio-Budget mitten in der Verifikation und brachen den Completeness-Check ab.

Aus `logs/FEHLERANALYSE_KI_TEAM_20260916.md`: im Lauf `cloudpulse` schlug der
`read_without_write`-Watchdog in **9 von 15** Agentenaufrufen an; im `cachegrid_proxy`-Lauf immer
noch 2×.

**Aufgaben:**

1. **Explizites Caching für Gemini.** `core/llm_factory.py` setzt `cache_control: ephemeral` nur
   auf dem Anthropic-Pfad (Zeilen 1641/1721/1736). Da faktisch alles über Gemini läuft (P5-1),
   hängt die Trefferquote am impliziten Caching. Gemini-Context-Caching für den stabilen
   Prompt-Anteil (System-Prompt + Learnings + Projekt-Steckbrief) explizit setzen.

   > **Root Cause bestätigt, 2026-09-20:** Zeile 1168/1243 **liest** zwar
   > `cached_content_token_count` aus der Gemini-Antwort, aber nirgends im Modul wird ein
   > `CachedContent`-Objekt via `client.caches.create(...)` angelegt oder `cached_content=` an
   > `generate_content()`/`generate_with_tools()` übergeben – die Lese-Seite existiert, die
   > Schreib-Seite (Cache überhaupt erst anlegen) fehlt komplett. Direkter Scan aller
   > `workspace/*/.ai_team_runs/*_trace.jsonl` (264 `agent_call`-Events, alle Projekte,
   > nicht nur `cachegrid_proxy`): **kein einziger** Aufruf hat einen `cache_read_tokens`-Wert
   > größer 0 – das Feld fehlt im Event durchgängig ganz (`None`, nicht `0`). Bei 19,56 Mio.
   > Prompt-Tokens in Summe macht das den größten bezifferbaren Hebel in P5-2. Die zuvor für
   > `cachegrid_proxy` notierte Trefferquote von 28,6 % ließ sich aus dem aktuellen Trace nicht
   > reproduzieren (das Feld ist dort `None`) – vermutlich aus einer anderen Quelle berechnet;
   > als verbindliche Zahl gilt die durchgängige 0 %-Messung.
   >
   > **Umgesetzt 2026-09-20:** `core/llm_factory.py._gemini_cached_content_name()` legt bei
   > System-Prompts ab 6.000 Zeichen ein `CachedContent`-Objekt an (`client.caches.create(...)`,
   > TTL 15 min) und cached es prozesslokal über `(API-Key, Modell, sha256(Prompt))`, sodass
   > wiederholte Iterationen desselben Agentic-Loops UND spätere Aufrufe derselben Rolle mit
   > identischem System-Prompt (z.B. über mehrere Verifikations-Fixrunden) sich einen einzigen
   > Cache teilen, statt jedes Mal neu zu bezahlen. Bewusst maximal defensiv: jede
   > Cache-Erstellung ist reiner Best-Effort mit vollständigem Try/Except (`_gemini_config_with_cache`)
   > – scheitert sie (Modell ohne Unterstützung, Prompt zu kurz, API-Fehler), verhält sich der
   > Aufruf exakt wie zuvor (inline `system_instruction`, kein `cached_content`); ein
   > fehlschlagender Cache-Versuch darf den eigentlichen `generate_content`-Aufruf nie gefährden.
   > Ein Modell, bei dem die Erstellung fehlschlägt, wird für eine Stunde übersprungen statt bei
   > jedem Aufruf erneut zu scheitern. Abgedeckt durch `tests/test_gemini_context_caching.py`
   > (11 Tests, inkl. End-to-End-Nachweis, dass `cached_content` tatsächlich bei
   > `models.generate_content()` ankommt, und dass eine scheiternde Cache-Erstellung den
   > eigentlichen Aufruf unverändert durchlässt).
   >
   > **Live verifiziert 2026-09-20, Referenzlauf `notecatcher`, UND dabei ein echter Bug
   > gefunden und behoben:** Der erste Live-Versuch schlug in JEDEM Werkzeug-Aufruf
   > (backend/security/tester) mit `400 INVALID_ARGUMENT` fehl – die Gemini-API lehnt
   > `cached_content` zusammen mit gleichzeitig gesetztem `system_instruction`, `tools` ODER
   > `tool_config` im selben Request kategorisch ab ("Proposed fix: move those values to
   > CachedContent from GenerateContent request"). Die ursprüngliche Unit-Test-Abdeckung prüfte
   > nur den Fall `tools=[]` und deckte das nicht auf. Behoben: `tools`/`tool_config` werden jetzt
   > mit ins Cache-Objekt gelegt (`CreateCachedContentConfig(tools=..., tool_config=...)`) und im
   > `GenerateContentConfig` weggelassen, sobald ein Cache greift; der Registry-Schlüssel enthält
   > jetzt zusätzlich einen Hash von `tools`/`tool_config`, damit unterschiedliche Rollen (andere
   > Werkzeugkataloge) keinen fremden Cache treffen. Neuer Regressionstest
   > `test_real_tools_are_never_set_alongside_cached_content` deckt genau diesen Fall ab. Nach dem
   > Fix lief `notecatcher` fehlerfrei durch, Abschlussbericht: **63 % Cache-Trefferquote bei
   > 470.809 Prompt-Tokens**; isolierter Zweitaufruf mit identischem Prompt bestätigt
   > `cache_read_tokens=3336` bei Aufruf 1 UND 2 (Wiederverwendung greift).
   >
   > **Dabei zusätzlich gefunden (kleinere, eigenständige Lücke):** Die 63 % stammen aus
   > `token_guard`s Aggregat-Zähler (korrekt gespeist über `record_usage(...,
   > cache_read_tokens=...)`), NICHT aus den einzelnen `agent_call`-Trace-Events – dort steht
   > weiterhin `cache_read_tokens=0` bei jedem Aufruf. Ursache: `core/message_bus.py.AgentResult`
   > hat gar kein `cache_read_tokens`-Feld, und `core/run_logger.py.log_agent_result()` liest nur
   > `prompt_tokens`/`completion_tokens`/`total_tokens` vom `AgentResult`. Der ursprüngliche
   > „0 % über alle 264 Traces"-Befund oben war also selbst teilweise ein Artefakt dieser
   > Beobachtungslücke, nicht nur fehlenden Cachings – zum Zeitpunkt der Messung stimmte aber
   > wahrscheinlich beides gleichzeitig (kein Cache UND keine Sichtbarkeit).
   >
   > **Ebenfalls behoben, 2026-09-20:** `cache_read_tokens`/`cache_write_tokens` sind jetzt
   > Felder auf `core/message_bus.py.AgentResult`, werden in `agents/base_agent.py._run_agentic_loop()`
   > über alle Iterationen summiert (nicht nur aus der letzten Antwort übernommen) und landen
   > via `core/run_logger.py.log_agent_result()` in jeder `agent_call`-Trace-Zeile. Künftige
   > Cache-Analysen können sich damit auf strukturierte Trace-Daten stützen statt auf den
   > Freitext des Abschlussberichts. Abgedeckt durch zwei neue Tests in
   > `tests/test_agentic_loop_resilience.py` (Einzel-Iteration und Summierung über mehrere
   > Iterationen hinweg).
2. **Kontext-Kompaktierung früher greifen lassen.** `context_chars_compacted` lag im letzten Lauf
   bei nur 24.839 Zeichen über den *ganzen* Lauf. Die Empfehlung aus der Fehleranalyse
   (> 15 Tool-Calls oder > 100k Tokens ⇒ Zwischenergebnis erzwingen) ist noch nicht umgesetzt.
3. **Werkzeug-Ergebnisse deduplizieren:** dieselbe Datei zweimal gelesen ⇒ nur das letzte
   Ergebnis im Kontext behalten, frühere durch einen Verweis ersetzen.

**Akzeptanzkriterium:** Ein Referenzlauf (`ping_service`, minimal) und ein mittlerer Lauf
(`nexus_mesh`) vorher/nachher gemessen: ≥ 25 % weniger Prompt-Tokens bei gleichem Ergebnis.

---

### P5-3 · Budget-Abbruch trifft die Verifikation statt der Produktion
**Status:** ✅ **erledigt 2026-09-20 – aber anders als ursprünglich gedacht**

> **Teil-Korrektur.** Die vorgeschlagene Lösung („eine feste Reserve von z. B. 15 %
> zurückhalten") **existiert bereits**: `VERIFICATION_TOKEN_RESERVE_RATIO = 0.15`,
> `_generation_budget_exceeded()` und `_generation_reserve_is_hard_abort()` in
> `agents/orchestrator/budget.py` (der „Verification Reserve Paradox"-Fix). Sie hat auch
> funktioniert – `eventforge_core` stoppte die Generierung bei 855.372 von 850.000 zulässigen
> Tokens.

**Der tatsächliche Fund, gemessen über die letzten neun Läufe:**

| | Verifikations-Anteil am Gesamtverbrauch |
| :--- | :--- |
| Läufe **ohne** Budget-Abbruch | 6,9 % · 9,7 % · 14,2 % · 15,6 % · 16,0 % |
| Läufe **mit** Budget-Abbruch | 19,5 % · 30,4 % · 31,8 % · 35,0 % |
| Konfigurierte Reserve | **15,0 %** |

Die Trennung ist vollständig: Läufe, die grün durchlaufen, sind in der Verifikation billig –
Läufe, die **Reparatur** brauchen, kosten dort das Doppelte bis Dreifache der Reserve. Die
Reserve ist also genau für den Fall zu klein bemessen, für den sie existiert. Sie einfach
hochzusetzen hilft nicht: die Generierungsphase (`dev_lead` allein: 500.000–750.000 Tokens)
würde dann abgeschnitten und unfertigen Code liefern.

**Was stattdessen behoben wurde:** Das Budget-Gate der Vollständigkeits-Schleife stand **vor**
dem Aufruf von `verifier.check_completeness()`. Dieser Check ist rein deterministisch
(AST/Dateisystem) und kostet **keine Tokens** – gegated wurde also nichts gespart, aber bei
leerem Budget gar nicht erst gemessen. `completeness_report` blieb `None`, die Aufzeichnung
fiel aus, und der Check galt als „nicht gemessen" statt bestanden oder gerissen (real:
„🚫 Lauf-Budget erreicht – Vollständigkeits-Check nach Versuch 0 abgebrochen"). Jetzt läuft die
Messung immer; budgetpflichtig ist nur noch der **Fix-Versuch**, der einen echten
Agenten-Aufruf kostet.

**Offen bleibt** die eigentliche Ursache – ein Lauf kostet zu viel: siehe **P5-2**.

---

## 7. ⚪ P6 – Aufräumen & Hygiene

| # | Aufgabe | Aufwand |
| :--- | :--- | :--- |
| P6-1 | Gestagte, nicht committete Fixes einchecken (siehe P0-3) – mit `Closes:`-Zeilen | XS |
| P6-2 | ~~`workspace/cachegrid_proxy/` gehört nicht in Framework-Commits~~ – **Korrektur 2026-09-20: Fehlannahme.** `workspace/` ist bewusst versioniert (1068 getrackte Dateien, eigene `feat:`-Commits je Projekt). Richtig ist nur, generierte Projekte **getrennt** vom Framework-Fix zu committen. | – |
| P6-3 | `memory/history_default.json` ist **1,99 MB** – Rotation/Archivierung einführen | S |
| P6-4 | `memory/backlog.json` 143 KB / 200 Tickets, davon 19 `cancelled` + 96 `done` – abgeschlossene Tickets nach `memory/backlog_archive.json` auslagern | S |
| P6-5 | `interface/cli.py` 2.378 Zeilen, `core/llm_factory.py` 1.848, `agents/orchestrator/verification.py` 1.816 – die drei größten Module nach Verantwortlichkeiten aufteilen | L |
| P6-6 | `core/message_bus.py` enthält nur noch zwei Dataclasses – in `core/agent_contracts.py` umbenennen (60+ Importe, daher mit Alias-Übergang) | S |
| P6-7 | `run_closed` meldete `agent_calls: 6` bei 9 `agent_call`-Events im selben Trace – Zählweise vereinheitlichen | XS |
| P6-8 | Test-Rauschen in der Historie: `*_test_proj`-Läufe stehen in `run_history.json` und verfälschen jede Statistik (`--clean-telemetry` existiert, wird offenbar nicht regelmäßig ausgeführt) | XS |

---

## 8. 🎯 Empfohlene Reihenfolge

**Sprint 1 – „Läufe werden wieder grün" (höchster Hebel, ~3 Tage)**
`P6-1` → `P0-1` → `P0-2` → `P0-3` → `P0-4` → `P0-5`
*Erwartete Wirkung:* Von den letzten 6 Läufen wären `aegisflow` und `cachegrid_proxy` grün
gewesen, `nexus_mesh` sauber grün statt mit Scheinbefund. Erfolgsquote 20 % → ~50 %.
**Messpunkt:** Nach Sprint 1 dieselben 6 Projekte erneut laufen lassen und die Quote vergleichen.

**Sprint 2 – „Das Team bleibt nicht stecken" (~4 Tage)**
`P1-2` (Eskalations-Strategien) → `P1-4` (Crash-Resilienz) → `P5-1` (Degraded-Mode ehrlich
machen) → `P5-3` (Verifikations-Reserve)

**Sprint 3 – „Das Team lernt wirklich" (~5 Tage)**
`P2-1` (Learnings mit Wirksamkeit) → `P2-2` (Qualitäts-Metrik statt Aufruf-Erfolg) →
`P2-4` (Retrospektive deterministisch) → `P3-3` (Root-Cause nur bei echten Blockern)

**Sprint 4 – „Das Team arbeitet autonom" (~5 Tage)**
`P1-1` (`--work-framework-backlog`) → `P1-3` (Ticket-Hygiene) → `P3-1` (Post-Mortem-Artefakt) →
`P3-2` (Trendbericht) → `P3-4` (Lesson-Schema)

**Sprint 5 – „Das Team verhält sich wie ein echtes Team" (~6 Tage)**
`P4-1` (Review verbindlich) → `P4-2` (Abnahme gegen Anforderung) → `P4-4` (Projekt-Steckbrief) →
`P4-3` (Testtiefe fachlich) → `P2-3` (Rollen-Portfolio bereinigen) → `P4-5` (Write-Guard)

**Laufend:** `P5-2` (Token-Effizienz) und `P6-*` (Hygiene) parallel einstreuen.

---

## 9. 🔧 Nützliche Prüfbefehle für die Abarbeitung

```bash
# Erfolgsquote der letzten N Läufe
python -c "import json;r=json.load(open('memory/run_history.json',encoding='utf-8'));l=r[-25:];print(sum(1 for x in l if x.get('verification_ok')),'/',len(l))"

# Offene Root-Cause-Tickets
python -c "from core.backlog_store import list_tickets;[print(t.id,t.status) for t in list_tickets() if t.source=='root_cause_analysis' and t.status!='done']"

# Falsch-Positive der Handoff-Prüfung (P0-1) live gegenprüfen
python -c "from core.team_board import unmet_requirements;[print(p,unmet_requirements('workspace/'+p)) for p in ('aegisflow','sentinedge','eventforge_core')]"

# Pre-Flight-Status eines angeblich roten Projekts (P0-3)
python -c "from core.pre_flight_check import run_pre_flight_check;print(run_pre_flight_check('workspace/cachegrid_proxy').passed)"

# Projektübergreifender Health-Rollup (P0-5)
python -c "from core.team_health import build_team_health_rollup;print(build_team_health_rollup('workspace').shared_patterns)"

# Rollen-Einsatz über die letzten 20 Läufe (P2-3)
python -c "import json,collections;r=json.load(open('memory/run_history.json',encoding='utf-8'));print(collections.Counter(a['agent_id'] for x in r[-20:] for a in x.get('agent_results',[])).most_common())"

# Nach jeder Änderung Pflicht:
ruff check && python -m pytest -q
```

> Hinweis für Windows: Bei Python-Einzeilern mit Umlauten in der Ausgabe
> `PYTHONIOENCODING=utf-8` voranstellen, sonst bricht die Ausgabe mit
> `UnicodeEncodeError: 'charmap' codec` ab.

---

## 10. ✅ Fortschritts-Tracker

| ID | Titel | Prio | Status |
| :--- | :--- | :--- | :--- |
| P0-1 | Rollennamen als Code-Symbole in `unmet_requirements()` | P0 | ☑ erledigt |
| P0-2 | `security_handoff` wird nie neu bewertet | P0 | ☑ erledigt |
| P0-3 | `pre_flight`-Ergebnis veraltet | P0 | ☑ erledigt |
| P0-4 | ~~`budget_aborted` fällt aus der Reparaturschleife~~ | P0 | ☑ verifiziert – kein Bug |
| P0-5 | Fehler-Kategorisierung kennt Hauptfehlerarten nicht | P0 | ☑ erledigt |
| P0-6 | `lint` erscheint fälschlich als Fehlschlag | P0 | ☑ erledigt (Teil 2 offen) |
| P1-1 | `--work-framework-backlog` (autonome Framework-Fixes) | P1 | ☑ erledigt |
| P1-2 | Eskalations-Strategien statt Wiederholung | P1 | ☑ erledigt |
| P1-3 | Ticket-Hygiene: `stale` vs. `error` trennen | P1 | ☑ erledigt |
| P1-4 | `CancelledError` reißt den Lauf mit | P1 | ☑ erledigt |
| P1-5 | Hard Delivery Gate ohne eigene `failure_class` | P1 | 🟡 failure_class erledigt, Fix-Loop-Kurzschluss offen |
| P2-1 | Learnings mit Wirksamkeitsmessung | P2 | ☑ erledigt |
| P2-2 | Modell-Auto-Tuning optimiert falsche Zielgröße | P2 | ☑ erledigt |
| P2-3 | 13 ungenutzte Rollen – entscheiden statt melden | P2 | 🟡 teilweise |
| P2-4 | Retrospektive arbeitet blind | P2 | ☑ erledigt |
| P3-1 | Post-Mortem-Artefakt pro Lauf | P3 | ☑ erledigt |
| P3-2 | `--team-trend` Trendbericht | P3 | ☑ erledigt |
| P3-3 | Root-Cause nur bei blockierenden Befunden | P3 | ☑ erledigt |
| P3-4 | `team_lessons.jsonl` Schema vereinheitlichen | P3 | ☑ erledigt |
| P4-1 | Code-Review verbindlich | P4 | ☑ erledigt |
| P4-2 | Abnahme gegen die Anforderung | P4 | ☑ erledigt |
| P4-3 | Testtiefe fachlich statt nur Routen | P4 | 🟡 teilweise (informativ, nicht blockierend) |
| P4-4 | Projekt-Steckbrief für jeden Agenten | P4 | 🟡 Abfang + zuverlässige Vertragsdatei erledigt, Prompt-Injektion vor 1. Schreiben offen |
| P4-5 | Write-Guard gegen Fremddatei-Überschreiben | P4 | ☑ erledigt (bereits vorhanden, nachgeprüft) |
| P5-1 | Degraded-Mode ehrlich machen | P5 | ☑ erledigt (alle 3 Punkte) |
| P5-2 | Token-Effizienz / Caching | P5 | 🟡 Gemini-Caching erledigt (Aufgabe 1), Rest offen |
| P5-3 | Verifikations-Reserve im Budget | P5 | ☑ erledigt (Reserve existierte, Gate korrigiert) |
| P6-1 | Gestagte Fixes committet | P6 | ☑ erledigt |
| P6-2 | ~~Workspace aus Framework-Commits~~ | P6 | ☑ Fehlannahme, siehe oben |
| P6-3…8 | Hygiene & Aufräumen | P6 | ☐ |
