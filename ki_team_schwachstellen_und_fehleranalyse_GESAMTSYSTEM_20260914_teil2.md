# KI-Team Folgeanalyse: Schwachstellen in den neu gebauten Selbstlern-Modulen
**Datum:** 14. September 2026 (Folgeanalyse zum selben Tag)
**Umfang:** Kritische Selbstprüfung der in der vorherigen Sitzung neu gebauten Module
(`core/root_cause_analyst.py`, `core/component_library.py`, Orchestrator-/Dashboard-Anbindung)
sowie ein erneuter Sicherheits-/Muster-Sweep über den Rest des Frameworks.

---

## 1. Management Summary

Der Rest des Frameworks bleibt bei erneuter Prüfung bemerkenswert solide: kein `shell=True`,
kein bare `except:`, keine veränderlichen Default-Argumente, keine TODO/FIXME-Leichen im
Produktivcode über `agents/`, `core/`, `interface/` hinweg – die Selbstdokumentations- und
Test-Disziplin dieses Teams hält einer erneuten, gezielten Suche nach klassischen
Anti-Pattern stand.

Die wertvollsten neuen Funde liegen deshalb genau dort, wo es zu erwarten war: in den **eben
erst gebauten, noch nicht durch echte Läufe gehärteten** Selbstlern-Modulen aus der
vorherigen Sitzung. Alle vier Befunde wurden durch tatsächliche Codeausführung verifiziert,
nicht nur durch Lesen:

1. **Kritisch:** `core/root_cause_analyst.py.extract_findings()` erkennt **null Befunde**,
   sobald das Modell zwischen den Feldern Leerzeilen einfügt – ein bei LLM-Markdown-Ausgaben
   praktisch garantiertes Verhalten. Das neue Flaggschiff-Feature würde in der Praxis
   vermutlich fast nie einen Treffer liefern, obwohl Tokens für die Analyse ausgegeben wurden.
2. **Mittel-Hoch:** Kein Kostenschutz/Cooldown für `should_trigger()` – ein chronisch
   scheiterndes Projekt löst bei JEDEM einzelnen Lauf eine neue, teure Tiefenanalyse aus,
   anders als die bestehenden Schwellwert-Mechanismen in `core/optimization_advisor.py`.
3. **Mittel:** `core/component_library.py` schreibt `manifest.json` NICHT atomar (fehlender
   Temp-Datei+`os.replace()`-Schutz, den `core/backlog_store.py` nach einem echten,
   dokumentierten Datenverlust-Vorfall bereits eingeführt hat) – bei den standardmäßig 2
   parallelen Dashboard-Jobs ein reales Risiko für Korruption/verlorene Einträge.
4. **Niedrig-Mittel:** Die Erkennungs-Heuristik für wiederverwendbare Bausteine übersieht
   gängige TypeScript-Muster (`export default class`, `export abstract class`) und schneidet
   vorangehende Decorators (`@dataclass`, `@Injectable()`) beim Ernten ab.

---

## 2. Detaillierte Befunde

### Befund 1 (Kritisch): `extract_findings()` scheitert an realistischer LLM-Formatierung

**Nachweis (tatsächlich ausgeführt):**
```python
from core.root_cause_analyst import extract_findings

response_with_blank_lines = '''### Befund 1

**Kategorie:** framework

**Titel:** Budget-Reserve blockiert die Verifikation

**Root Cause:** ...

**Empfehlung:** ...
'''
extract_findings(response_with_blank_lines)  # -> [] (0 Befunde!)
```
**Ursache:** `_FINDING_BLOCK_RE` verlangt zwischen den Feldern Kategorie/Titel/Root Cause exakt
EINEN Zeilenumbruch, keinen leeren dazwischenliegenden. Sobald zwischen `**Kategorie:** ...`
und `**Titel:** ...` eine Leerzeile steht (Standard-Markdown-Stil, den praktisch jedes LLM für
"lesbare" Aufzählungen mit fetten Labels verwendet, unabhängig vom Prompt-Beispiel ohne
Leerzeilen), bricht das Pattern-Matching an genau dieser Stelle ab.

**Auswirkung:** In der Praxis würde `run_analysis()` reihenweise mit
`"Antwort enthielt keine im erwarteten Format erkennbaren Befunde"` scheitern – der teure
Werkzeug-Loop mit vollem Repository-Zugriff lief durch, das Ergebnis landet aber nirgends als
Ticket oder Team-Lektion. Das komplette Feature aus Punkt 3 der letzten Sitzung wäre dadurch
in der Praxis wahrscheinlich fast wirkungslos, obwohl alle Unit-Tests grün sind (sie testen nur
mit dem exakten, blockfreien Beispieltext).

**Der bereits im selben Projekt vorhandene, robustere Ansatz:** `core/roadmap_advisor.py.
_PROPOSAL_RE` verarbeitet `content.splitlines()` **zeilenweise** statt über einen
mehrzeiligen Block-Regex – jede Leerzeile wird dabei einfach ignoriert (kein Treffer für diese
eine Zeile), statt den gesamten Folge-Block zu zerstören. Genau dieses Muster (oder ein
`re.split()` auf `### Befund \d+` gefolgt von toleranter Feld-für-Feld-Extraktion mit
`re.search()` statt eines einzigen durchgehenden Block-Patterns) sollte `extract_findings()`
übernehmen.

---

### Befund 2 (Mittel-Hoch): Kein Cooldown für wiederholte Root-Cause-Analysen

**Beobachtung:** `should_trigger()` liefert `True`, sobald `not verification_ok and
files_written > 0` – bei JEDEM einzelnen Lauf, unabhängig davon, ob genau derselbe Fehler
bereits im vorherigen Lauf analysiert wurde. Im Unterschied dazu verlangt z.B.
`core/optimization_advisor.py` (`MIN_SAMPLE_SIZE`, `MIN_VERIFICATION_SAMPLE_SIZE`) eine
statistisch tragfähige Mindest-Anzahl an Beobachtungen, bevor überhaupt etwas ausgelöst wird –
dieselbe Kosten-Disziplin fehlt hier.

**Auswirkung:** Ein Projekt, das z.B. wegen eines hartnäckigen Umgebungsproblems dreimal
hintereinander scheitert (wie real bei `ecochef` beobachtet), löst DREIMAL die volle,
werkzeugbasierte Tiefenanalyse aus – auch wenn Befund 1 gefixt ist und jedes Mal ein Ticket
entsteht, wird bei identischer Ursache zwar dasselbe Ticket nur aktualisiert (Dedup wirkt
korrekt), aber der TEURE LLM-Aufruf mit vollem Tool-Zugriff läuft trotzdem jedes Mal erneut.

**Empfehlung:** Vor dem Aufruf prüfen, ob für dasselbe `project_slug` bereits kürzlich
(z.B. innerhalb der letzten N Minuten oder für denselben `verification_summary`-Fingerprint)
eine Root-Cause-Analyse durchgeführt wurde (analog zu `core/team_memory.py`s
`_DEDUP_LOOKBACK`-Prinzip), und in diesem Fall überspringen.

---

### Befund 3 (Mittel): `component_library.py` schreibt `manifest.json` nicht atomar

**Nachweis:** `core/backlog_store.py._save_raw()` trägt einen ausführlichen Kommentar über
einen ECHTEN, reproduzierten Datenverlust-Vorfall: ein gleichzeitiger Leser traf einen
gleichzeitigen `upsert_ticket()`-Schreibvorgang mitten im `write_text()`, bekam kaputtes JSON,
und der nächste Schreibvorgang überschrieb dadurch das GESAMTE Backlog. Die Lösung dort:
Schreiben in eine Temp-Datei im selben Verzeichnis + `os.replace()` (atomar unter POSIX UND
Windows).

`core/component_library.py._save_manifest()` verwendet dagegen weiterhin direktes
`MANIFEST_FILE.write_text(...)` – exakt das Muster, das im Backlog-Store bereits zu echtem
Datenverlust geführt hat. Da `interface/web_dashboard.py` standardmäßig
`DASHBOARD_MAX_CONCURRENT_JOBS=2` parallele Läufe unterstützt (durch
`tests/test_dashboard_concurrency.py` aktiv abgedeckt) und `harvest_from_project()` nach JEDEM
erfolgreich verifizierten Lauf aufgerufen wird, ist das Szenario "zwei Projekte werden
gleichzeitig fertig und ernten gleichzeitig" real erreichbar, nicht nur theoretisch.

**Empfehlung:** `_save_manifest()` auf dasselbe Temp-Datei+`os.replace()`-Muster wie
`core/backlog_store.py._save_raw()` umstellen (inkl. des dortigen `PermissionError`-Retry für
Windows).

---

### Befund 4 (Niedrig-Mittel): Lücken in der Baustein-Erkennungsheuristik

**Nachweis (tatsächlich ausgeführt):**
```python
from core.component_library import _PATTERNS
any(p.search('export default class CircuitBreaker {') for p in _PATTERNS.values())  # False
any(p.search('export abstract class RateLimiter {') for p in _PATTERNS.values())    # False
```
Beide sind gängige, seriöse TypeScript-Konventionen (Default-Export einer einzelnen
Haupt-Klasse pro Datei; abstrakte Basisklassen) – werden von den aktuellen Regex-Mustern in
`_PATTERNS` aber nicht erkannt, weil dort nur `(?:export\s+)?class` vorgesehen ist.

Zusätzlich schneidet `_extract_block()` einen vorangehenden Decorator ab: Eine mit `@dataclass`
annotierte `CircuitBreaker`-Klasse wird ohne den Decorator geerntet – wird dieser Baustein
später unverändert übernommen, fehlt ihm ein möglicherweise verhaltensrelevanter Decorator
(bei `@dataclass` z.B. die automatisch generierten `__init__`/`__eq__`-Methoden).

**Empfehlung:**
1. Muster um `export\s+(?:default\s+|abstract\s+)*class` erweitern.
2. `_extract_block()`: vor `match.start()` rückwärts über zusammenhängende
   Decorator-/Annotations-Zeilen (`^\s*@\w+`) scannen und diese mit in den geernteten Block
   aufnehmen.

---

## 3. Erneuter Sweep über den Rest des Frameworks (keine neuen Befunde)

Gezielt geprüft und unauffällig:
- Keine `shell=True`-Aufrufe in `agents/`/`core/`/`interface/` (kein Shell-Injection-Vektor).
- Keine bare `except:`-Klauseln, keine veränderlichen Default-Argumente.
- `core/dependency_updater.py` öffnet bewusst nur einen PR zum menschlichen Review, merged
  nie automatisch – Muster bleibt konsistent mit der übrigen Autonomie-Zurückhaltung des Teams.

---

## 4. Priorisierte Maßnahmenliste

| # | Befund | Aufwand | Wirkung | Status |
|---|---|---|---|---|
| 1 | `extract_findings()` auf zeilen-/blockweise tolerante Extraktion umstellen (analog `roadmap_advisor.py`) | Klein–Mittel | Sehr hoch (das gesamte Feature aus der letzten Sitzung hängt daran) | ✅ Umgesetzt (`_BEFUND_HEADER_RE`/`_FIELD_LABEL_RE`/`_parse_fields()`) |
| 2 | Cooldown/Dedup gegen wiederholte Root-Cause-Analysen derselben Ursache | Klein | Mittel (Tokenersparnis bei chronisch scheiternden Projekten) | ✅ Umgesetzt (`ROOT_CAUSE_ANALYSIS_COOLDOWN_SECONDS`, 6h, pro Projekt) |
| 3 | `component_library._save_manifest()` atomar schreiben (Temp-Datei + `os.replace()`) | Klein | Mittel (verhindert Korruption/Datenverlust unter Nebenläufigkeit) | ✅ Umgesetzt + per Stresstest gegen die alte Implementierung verifiziert |
| 4 | `_PATTERNS` um `export default/abstract class` erweitern + Decorators beim Ernten mitnehmen | Klein | Niedrig–Mittel (bessere Trefferquote der Bibliothek) | ✅ Umgesetzt (`_EXPORT_PREFIX`, `_leading_decorators()`) |

Details siehe `CHANGELOG.md` (neuester Eintrag) und die erweiterten Testdateien
`tests/test_root_cause_analyst.py`/`tests/test_component_library.py`.
