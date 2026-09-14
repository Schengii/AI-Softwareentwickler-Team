# KI-Team Gesamtsystem-Analyse: Reifegrad, offene Schwachstellen & Weiterentwicklungs-Roadmap
**Datum:** 14. September 2026
**Umfang:** Gesamte Codebasis (agents/, core/, interface/, memory/) sowie die letzten Workspace-Läufe
(devpulse, aethermesh, chronospulse, hyperionsentinel, pulseflow_gateway, ecochef, eventstream_zero)
**Methode:** Statische Code-Analyse + Abgleich mit `logs/runs/*.jsonl`, `logs/verification/*.log` und den
vier bereits vorhandenen Einzel-Projekt-Analysen (`ki_team_schwachstellen_und_fehleranalyse_{devpulse,
aethermesh,chronospulse,hyperionsentinel}_202609*.md`)

---

## 1. Management Summary

Das Framework ist **deutlich reifer als der typische "AI-Agent-Demo"-Zuschnitt**: 33 Fachrollen, echtes
Function-Calling gegen reale Werkzeuge, eine isolierte venv-Verifikation mit echter Testausführung,
Pre-Flight-/Completeness-/Contract-Checks, Budget-Governance, Produktions-Monitoring nach echtem Deploy,
eine daten­getriebene Modell-Optimierung (`core/optimization_advisor.py`) und ein teamweites
Lessons-Learned-Gedächtnis (`core/team_memory.py`). Auffällig: **fast jede nicht-triviale Codezeile trägt
einen Kommentar der Form "Realer Fund am Lauf X, Datum Y"** – das Team dokumentiert seine eigene
Fehlerhistorie bereits ungewöhnlich diszipliniert.

Die vier vorhandenen Einzel-Analysen (devpulse/aethermesh/chronospulse/hyperionsentinel) wurden geprüft:
**alle darin beschriebenen Bugs sind im aktuellen Code bereits behoben** (verifiziert per Grep gegen
`_SQLA_DSN_DRIVER_RE`, `owners.discard("tester")`, `_generation_budget_reached_this_run`,
`pytest-asyncio`-Auto-Install, `SECURITY_AUDIT.md`-Pflicht-Write). Das bestätigt: **der Lern-Mechanismus
funktioniert – aber aktuell nur als manueller Workflow** (jemand liest Logs, schreibt eine Analyse,
jemand implementiert den Fix). Genau das ist die größte strukturelle Lücke, um dem Ziel "lernt
automatisch aus jedem Fehler" näherzukommen – siehe Abschnitt 2.1.

Zusätzlich wurden bei dieser Analyse **zwei bisher nicht dokumentierte, noch offene Probleme** gefunden
(Abschnitt 2), sowie vier strukturelle Weiterentwicklungsfelder für mehr Autonomie/Professionalität
(Abschnitt 3).

---

## 2. Neu gefundene, noch offene Schwachstellen

### 2.1 Der eigentliche Lern-Kreislauf ist manuell, nicht automatisch — größte Lücke zum Nutzerziel

**Befund:** Die vier existierenden Tiefenanalysen, die zu den wichtigsten Framework-Fixes der letzten
Woche geführt haben (DSN-Regex, Budget-Reserve-Paradox, Tester/Owner-Routing, pytest-asyncio), sind
selbst nirgends im Code als automatisierter Schritt verankert. Das bestätigt der Code selbst:

- `agents/orchestrator/retrospective.py._run_retrospective()` übergibt dem `retrospective`-Agenten pro
  Ergebnis nur einen **auf 250 Zeichen gekappten Auszug** (`r.content[:250]`) – kein Zugriff auf die
  echten Log-Dateien, keine Tools, kein `read_file`. Das reicht für oberflächliches Feedback, aber nicht
  für die Art von Fund, die z.B. die "Ghost-Frontend"-Schwachstelle (fehlendes `<script>`-Tag) oder das
  "Verification Reserve Paradox" aufgedeckt hat – beides erforderte, echte Logdateien UND echten
  Projekt-Code nebeneinander zu lesen.
- Der eigene Docstring von `agents/orchestrator/retrospective.py` (Zeile 13–25) gibt das offen zu: der
  "Deterministischer Check-Vorschlag" eines Trainer-Reports blieb bis 2026-09-07 folgenlos liegen, weil
  er "nur einmalig im Trainer-Bericht dieses einen Laufs stand und danach spurlos verloren ging" – die
  Lücke wurde laut Kommentar **"erst nach einer vollständigen manuellen Analysesitzung (statt
  automatisch aus dem Trainer-Report heraus)"** geschlossen.
- Es gibt keinen Trigger, der bei `verification_ok: false`, `budget_aborted: true` oder einem
  wiederholten Fehlersignatur-Ticket automatisch eine **forensische Tiefenanalyse mit echtem
  Tool-Zugriff** (auf `logs/runs/*.jsonl`, `logs/verification/*.log`, den generierten Projekt-Code UND
  den Framework-Code selbst) auslöst und deren konkrete Fix-Vorschläge strukturiert in ein Ticket
  überführt.

**Auswirkung:** Das Team lernt zuverlässig aus Fehlern – aber nur, solange ein Mensch periodisch genau
diese Analyse-Sitzung anstößt (wie in diesem Chat). Ohne diesen manuellen Trigger bleiben tiefsitzende,
mehrere Dateien/Logs übergreifende Bugs unentdeckt, auch wenn alle Rohdaten dafür bereits vorliegen.

**Empfehlung:** Siehe 3.1 ("Automatisierter Root-Cause-Analyst").

---

### 2.2 Verlorene Tracebacks bei Top-Level-Crashes des Orchestrators (verifiziert am `ecochef`-Lauf)

**Befund:** `workspace/ecochef` hat am 13.09.2026 **fünf** Läufe hintereinander produziert
(`logs/runs/20260913_{124114,140359,163546,171154,171721}_ecochef.jsonl`). Die ersten drei brechen mit
exakt demselben Signal ab:
```json
{"event": "run_closed", "verification_ok": false, "aborted": true, "abort_reason": "exception:TypeError"}
```
In `agents/orchestrator/__init__.py` (Zeile 386–388) steht der zuständige Handler:
```python
except BaseException as exc:
    self._close_unfinished_run_log(f"exception:{type(exc).__name__}")
    raise
```
Es wird **nur der Exception-Klassenname**, nicht die Nachricht und kein Traceback persistiert. Der
tatsächliche Stack-Trace geht nur an die Konsole (falls interaktiv beobachtet) bzw. verpufft in
Dashboard-/Hintergrund-Läufen vollständig. Bemerkenswert: An anderer Stelle im selben Repo
(`interface/cli.py:510-520`) wurde exakt dieses Muster bereits einmal als Fehler erkannt und behoben –
dort steht wörtlich der Kommentar *"Ohne den [Traceback] ist nachträglich nicht mehr rekonstruierbar,
WELCHE Zeile den Fehler auslöste – der Fund war praktisch unbehebbar, sobald die Sitzung vorbei war"* –
aber die Lehre wurde nicht auf den strukturell selben Handler im Orchestrator selbst übertragen.

**Auswirkung:** Genau der ecochef-Fall zeigt die Konsequenz: derselbe `TypeError` trat 3x hintereinander
auf, konnte aber **nicht diagnostiziert und dauerhaft gefixt werden**, weil aus den Logs nur "TypeError"
hervorgeht – keine Zeile, kein Modul, keine Nachricht. Das Projekt wurde erst im 4./5. Versuch (nach
vermutlich zufälliger Umgehung des Auslösers) überhaupt bis zur Verifikation geführt, blieb dort aber
mit `blocking: ["tests_pass", "missing_entrypoint"]` unfertig liegen – für `ecochef` existiert bis heute
kein `.ai_team_status_full.log`, das Projekt wurde nie erfolgreich abgeschlossen.

**Empfehlung:**
1. In `Orchestrator.process()` (Zeile 386–388) `traceback.format_exc()` (gekappt, analog
   `interface/cli.py`s `MAX_FAILURE_DETAIL_CHARS`-Konvention) mit in `_close_unfinished_run_log()`
   übergeben und im Run-Log persistieren, nicht nur den Klassennamen.
2. Bei einem Crash automatisch ein Backlog-Ticket mit `source="orchestrator_crash"` und dem vollen
   (gekappten) Traceback anlegen – dieselbe Ticket-Infrastruktur, die bereits für wiederkehrende
   Verifikations-/Lint-Funde existiert (`agents/orchestrator/__init__.py` Zeile ~1050).
3. `workspace/ecochef` erneut laufen lassen bzw. gezielt debuggen, sobald der Traceback sichtbar ist –
   aktuell ist es das einzige Projekt im Workspace ohne abgeschlossenen Status.

---

## 3. Strukturelle Weiterentwicklung für mehr Professionalität, Intelligenz, Autonomie & Selbstoptimierung

### 3.1 Automatisierter Root-Cause-Analyst (schließt die Lücke aus 2.1)

Ergänze einen neuen, automatisch getriggerten Schritt (kein neuer "Agent" im Sinne einer 34. Fachrolle,
sondern ein Orchestrator-Mechanismus analog zu `core/production_monitor.py`), der **nach jedem Lauf
mit `verification_ok=false`, `budget_aborted=true` oder einem neu eröffneten
"wiederkehrender Fehler"-Ticket** automatisch:
1. mit echtem `read_file`/`search_code`-Zugriff auf `logs/runs/<lauf>.jsonl`,
   `logs/verification/<lauf>.log`, den generierten Projekt-Code UND (read-only) den relevanten
   Framework-Code selbst zugreift (Rechte-Modell wie die bestehenden read-only Re-Review-Tasks in
   `agents/orchestrator/verification.py`),
2. nach demselben Format wie die vier vorhandenen Analysen einen kurzen Root-Cause-Bericht erzeugt,
3. daraus **strukturierte** (nicht nur Prosa-)Vorschläge extrahiert – dieselbe Regex-Idee wie
   `_DETERMINISTIC_CHECK_SUGGESTION_RE`, aber direkt in ein Ticket mit `source="root_cause_analysis"`
   statt nur im Bericht dieses einen Laufs zu verbleiben,
4. NICHT automatisch Code ändert (bewusst wie `roadmap_advisor.py`/`optimization_advisor.py` – ein
   Mensch reviewt Framework-Änderungen), aber das Ticket priorisiert und beim nächsten
   `agent_trainer`-Lauf verpflichtend vorlegt.

Das würde den Workflow, der diese Session gerade manuell ausgeführt hat, zu einem Selbstläufer machen –
exakt das, was der Nutzer mit "lernt mit jedem gemachten Fehler dazu" meint.

### 3.2 Cross-Projekt Komponenten-/Pattern-Bibliothek ("Wiederverwendung statt Neuerfindung")

**Befund:** `core/embedding_index.py`/`core/vector_store.py` indizieren ausschließlich **innerhalb**
eines einzelnen Projekts (`workspace/<projekt>/.ai_team_rag/`). Es gibt keine projektübergreifende
Bibliothek verifizierter, bereits getesteter Implementierungen wiederkehrender Infrastruktur-Bausteine
(CircuitBreaker, Rate-Limiter, JWT-Auth-Middleware, Repository-Base-Klassen, SSE-Hubs, Retry/Backoff).
Die Konsequenz ist im Lauf konkret sichtbar: `chronospulse` lieferte einen 5-zeiligen
Kommentar-Stub statt eines echten `CircuitBreaker` (Schwachstelle 4 der Chronospulse-Analyse) – exakt
die Art Baustein, die in einem reifen Team beim zweiten oder dritten Projekt nicht mehr neu geschrieben,
sondern aus einer geprüften internen Bibliothek gezogen würde.

**Empfehlung:** Ein `memory/component_library/` (oder `core/component_library.py`), das:
- nach jedem erfolgreich verifizierten Lauf (`verification_ok=true`) automatisch prüft, ob generischer,
  wiederverwendbarer Code entstanden ist (Heuristik: Klassen-/Modulnamen aus einer kuratierten Liste wie
  `CircuitBreaker`, `RateLimiter`, `RetryPolicy`, `JWTAuth`, Repository-Basisklassen),
  und diesen (mit Provenienz: Quellprojekt, Datum, bestandene Tests) in die Bibliothek übernimmt,
- den bestehenden `core/embedding_index.py`-Mechanismus wiederverwendet, aber projektübergreifend
  indiziert,
- Agenten mit einem neuen, schreibgeschützten Tool (`search_component_library`) zugänglich gemacht wird,
  mit einer klaren Prompt-Regel: "Prüfe zuerst die Komponenten-Bibliothek, bevor du Standard-
  Infrastruktur wie Circuit-Breaker/Rate-Limiter/Auth komplett neu implementierst."

Das reduziert nicht nur Tokenverbrauch (kein wiederholtes Neuerfinden), sondern auch die
Fehlerwiederholungsrate bei genau den Bausteinen, die laut den vorliegenden Analysen am häufigsten als
Stub/fehlerhaft auffallen.

### 3.3 Beobachtbarkeit: Konsistenz von Status-Flags reparieren

Die Hyperionsentinel-Analyse (Schwachstelle 2, bereits dokumentiert, Status unklar ob vollständig
gefixt) zeigt ein Muster, das über den Einzelfall hinaus relevant bleibt: nachgelagerte optionale Checks
können `budget_aborted=true` setzen, obwohl die Kern-Verifikation bereits erfolgreich war
(`verification_ok=true`). Empfehlung: Ein klar getrenntes drittes Flag `optional_checks_skipped` statt
der Überladung von `budget_aborted` – wichtig für die Aussagekraft von `memory/run_history.py` und
`core/team_health.py`, die daraus Erfolgsquoten berechnen. Eine falsch klassifizierte "Niederlage" senkt
künstlich die gemessene Team-Erfolgsquote und kann `core/optimization_advisor.py` zu falschen
Modell-/Agenten-Bewertungen verleiten (Daten-Rauschen in einem System, das explizit datenbasiert
optimieren will).

### 3.4 Autonomie behutsam ausbauen statt pauschal erweitern

Das Framework trifft bereits eine sehr bewusste, gut begründete Grenze: `core/backlog_worker.py`
arbeitet nur Tickets mit bestimmten `source`-Werten autonom ab (`_AUTONOMOUS_SOURCES`), Vorschläge von
`roadmap_advisor.py`/`optimization_advisor.py`/`production_monitor.py` landen bewusst NICHT automatisch
in der Umsetzung. Das ist richtig und sollte **nicht** pauschal aufgeweicht werden. Sinnvoller
nächster Schritt statt genereller Autonomie-Erhöhung:
- Der neue `root_cause_analysis`-Ticket-Typ aus 3.1 sollte ebenfalls bewusst NICHT autonom sein
  (Framework-Änderungen verdienen Review), aber im Dashboard prominent als "wartet auf Freigabe"
  gebündelt statt zwischen normalen Feature-Tickets zu verschwinden.
- `ENABLE_AUTO_MODEL_TUNING` ist aktuell (korrekterweise) per Default deaktiviert (`config.py` Zeile
  889, opt-in per `.env`). Da `core/optimization_advisor.py` bereits eine belastbare, mehrfach
  abgesicherte Kosten-Nutzen-Abwägung eingebaut hat (Toleranzschwellen für Tokenmehrkosten,
  Mindeststichprobengröße), lohnt sich eine Überprüfung, ob genug Lauf-Historie vorliegt, um es
  probeweise für einzelne, unkritische Agentenrollen zu aktivieren – mit Monitoring über
  `memory/cost_history.json`.

---

## 4. Priorisierte Maßnahmenliste

| # | Maßnahme | Aufwand | Wirkung | Referenz |
|---|---|---|---|---|
| 1 | Traceback statt nur Exception-Klassenname im Orchestrator-Crash-Handler persistieren + Ticket | Klein | Hoch (macht jeden künftigen Crash überhaupt erst diagnostizierbar) | 2.2 |
| 2 | `workspace/ecochef` mit sichtbarem Traceback erneut debuggen/fertigstellen | Klein–Mittel | Mittel (einziges unfertiges Projekt im Workspace) | 2.2 |
| 3 | Automatisierter Root-Cause-Analyst nach fehlgeschlagenen/abgebrochenen Läufen | Mittel–Groß | Sehr hoch (automatisiert genau den Lern-Kreislauf, den der Nutzer will) | 2.1, 3.1 |
| 4 | Cross-Projekt Komponenten-Bibliothek für Standard-Infrastruktur | Groß | Hoch (weniger Tokenverbrauch, weniger wiederholte Bugklassen) | 3.2 |
| 5 | `budget_aborted` von optionalen Nachprüfungen entkoppeln (drittes Flag) | Klein | Mittel (verhindert verfälschte Erfolgsquoten-Statistik) | 3.3 |
| 6 | Dashboard-Bündelung für "wartet auf Freigabe"-Vorschlagstickets (root_cause/roadmap/optimization) | Klein–Mittel | Mittel (Sichtbarkeit statt Verlust im Ticket-Rauschen) | 3.4 |

---

## 5. Was bereits vorbildlich funktioniert (zur Einordnung)

- Echtes, providerübergreifendes Function-Calling mit realer venv-Verifikation statt Keyword-Heuristik.
- Fehler-Routing an den tatsächlichen Datei-/Klassen-Owner statt pauschal an den Tester
  (`_class_definition_owner`, bereits aus realen Funden gehärtet).
- Team-weites Lessons-Learned-Gedächtnis mit Dedup- und Prioritäts-Logik (`core/team_memory.py`).
- Datenbasierte, kostenbewusste Modell-Optimierung mit expliziten statistischen Mindestschwellen
  (`core/optimization_advisor.py`).
- Produktions-Monitoring nach echtem Deploy mit Auto-Ticket bei Ausfall/Wiederherstellung
  (`core/production_monitor.py`) – ein Schritt, den viele vergleichbare Frameworks komplett auslassen.
- Durchgängige, disziplinierte Selbstdokumentation ("Realer Fund am Lauf X") – diese Kultur ist die
  Voraussetzung dafür, dass Maßnahme 3 (automatisierter Root-Cause-Analyst) überhaupt zuverlässig
  funktionieren kann, sobald sie existiert.

---

## 6. Umsetzungsstatus (Stand: 14. September 2026, direkt im Anschluss an diese Analyse)

Alle sechs Maßnahmen aus Abschnitt 4 wurden umgesetzt und getestet:

| # | Maßnahme | Status |
|---|---|---|
| 1 | Traceback statt nur Exception-Klassenname im Crash-Handler | ✅ Umgesetzt (`agents/orchestrator/__init__.py`, `tests/test_orchestrator_crash_traceback.py`) |
| 2 | `workspace/ecochef` Absturzursache beheben | ⚠️ Teilweise: der konkrete `TypeError` in `_run_verification_loop_impl()` war bereits VOR dieser Analyse-Sitzung durch eine robuste Außenhülle (`_run_verification_loop()`, inkl. `tests/test_governance_resilience.py::test_verification_loop_resilience_on_type_error`) abgefangen worden – der eigentliche Programmierfehler ist damit gehärtet, das generierte `ecochef`-Projekt selbst wurde in dieser Sitzung NICHT erneut durchlaufen (kostenpflichtiger echter Agenten-Lauf, absichtlich nicht ungefragt ausgelöst) |
| 3 | Automatisierter Root-Cause-Analyst | ✅ Umgesetzt (`core/root_cause_analyst.py`, `tests/test_root_cause_analyst.py`) |
| 4 | Cross-Projekt Komponenten-Bibliothek | ✅ Umgesetzt (`core/component_library.py`, neues Werkzeug `search_component_library`, `tests/test_component_library.py`, `tests/test_agent_toolbox_component_library.py`) |
| 5 | `budget_aborted` von optionalen Nachprüfungen entkoppeln | ✅ War bereits VOR dieser Analyse-Sitzung umgesetzt (`agents/orchestrator/verification.py`, Zeile ~2716, `tests/test_budget_aborted_after_verification_ok.py`) – hier verifiziert statt erneut implementiert |
| 6 | Dashboard-Bündelung für freigabepflichtige Vorschlagstickets | ✅ Umgesetzt (`interface/web_dashboard.py`, neuer Bereich "Vorschläge, die auf Freigabe warten", `tests/test_dashboard_proposal_board.py`) |

Details siehe `CHANGELOG.md` (neuester Eintrag) und die jeweils referenzierten Testdateien.
