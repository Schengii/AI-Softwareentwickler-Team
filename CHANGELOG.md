# 📜 Änderungsprotokoll

Chronologische Historie realer Funde und Fixes am KI-Softwareentwickler-Team, neueste
zuerst. Jeder Eintrag entstand aus einem konkreten, beobachteten Problem – meist aus
einem echten Lauf gegen ein echtes Projekt –, nicht aus spekulativen Verbesserungen.
Für die aktuelle Funktionsübersicht siehe [README.md](README.md).

---

## 🔴 Masterplan Stufe 0-3: Modell-Tiering, Telemetrie und Benchmark waren wirkungslos

Umsetzung des `/goal`-Auftrags zum Masterplan (`KI_TEAM_MASTERPLAN_OPTIMIERUNG.md`). Die Analyse
von 200 Laeufen, 5.368 LLM-Calls und 50 Benchmark-Laeufen foerderte drei sich gegenseitig
verstaerkende Defekte zutage, die zusammen die Luecke zwischen einer gruenen Testsuite und einer
Verifikationsrate von ~20% erklaeren.

**Stufe 0 - Ehrliche Messung**
- `agents/base_agent.py` protokollierte im Fehlerpfad das KONFIGURIERTE statt des tatsaechlich
  kontaktierten Modells. Folge: 160 Fehlschlaege unter `claude-sonnet-5` - fuer ein Modell, das
  laut `memory/cost_history.json` nie einen einzigen Call gemacht hat (`ANTHROPIC_API_KEY` war
  leer). `core/provider_exhaustion.py.classify_failure()` trennt jetzt echte Agentenfehler von
  Infrastruktur-Ausfaellen; `memory/run_history.py` rechnet Letztere aus allen Erfolgsquoten
  heraus. Zuvor lernte die Selbstoptimierung aus Rate-Limits statt aus Qualitaetsmaengeln.
- `evals/runner.py` bestimmte `verification_ok` per Substring-Match auf dem Report-TEXT - der
  gepruefte Marker "Verifikations-Protokoll" steht aber in JEDEM Bericht, auch in gescheiterten.
  Der Benchmark konnte strukturell nicht durchfallen (50 von 50 "bestanden", jeweils mit
  `total_tokens: 0`, weil die Kennzahl nie zugewiesen wurde). Liest jetzt das strukturierte
  Orchestrator-Ergebnis, summiert die echten Tokens und archiviert ein vorhandenes
  Projektverzeichnis, damit Dateien frueherer Laeufe keinen gescheiterten Lauf bestehen lassen.
- `core/run_logger.py` (neu): `logs/` war vollstaendig leer, es existierte kein einziges
  `logging.basicConfig` und kein `FileHandler`. Ein im Hintergrund gescheiterter Lauf war
  hinterher nicht untersuchbar. Schreibt jetzt ein JSONL je Lauf (mit angefordertem UND
  effektivem Modell je Agenten-Call) plus die rohen Verifikationsausgaben.

**Stufe 1 - Funktionierende Modelle**
- `HEAVY_MODEL` und `ORCHESTRATOR_MODEL` zeigten bedingungslos auf Claude - ohne
  `ANTHROPIC_API_KEY` hatten damit 13 Rollen und der Orchestrator kein funktionierendes
  Primaermodell. Live reproduziert: Alle drei Komplexitaetsstufen wurden von ein und demselben
  Modell beantwortet. `config._first_available_model()` waehlt pro Stufe jetzt das staerkste
  Modell, dessen Provider tatsaechlich einen Schluessel hat.
- `_allow_self_fallback=False` steuerte im `GeminiClient` nur den Groq-Hop, nicht die
  Fallback-Kette - das Provider-Pinning aus `base_agent.py` war fuer Gemini wirkungslos. Jede
  echte Abwertung wird jetzt zusaetzlich ueber `set_model_downgrade_listener()` sichtbar.
- `main.py --check-models` (neu, `core/model_preflight.py`) beantwortet die Frage, die sich das
  Framework nie gestellt hat: Mit welchen Modellen arbeitet das Team wirklich?
- Circuit Breaker: Im Lauf `event_ticket_api` scheiterten 19 von 21 Agenten an erschoepften
  Kontingenten, 0 Dateien wurden geschrieben - und der Lauf startete trotzdem die Verifikation,
  dispatchte einen Fix-Auftrag fuer "keine Tests gefunden" und schrieb einen irrefuehrenden
  Projektstatus. `PROVIDER_EXHAUSTION_ABORT_RATIO` beendet solche Laeufe jetzt sauber.

**Stufe 2 - Qualitaet**
- Smoke-Test-Gate VOR der Testschleife: Startet die App nicht, scheitert jeder Test an derselben
  Ursache und die Fix-Schleife arbeitet an Symptomen (opspilot: 1.038.910 Tokens ohne bestandene
  Verifikation). Der Startfehler wird jetzt zuerst und isoliert behoben.
- `core/definition_of_done.py` (neu): `PROJECT_STATE.md` meldete "In Entwicklung" auch bei null
  geschriebenen Dateien. `.ai_team_dod.json` ersetzt den Prosa-Status durch harte Kriterien und
  unterscheidet "nicht geprueft" von "geprueft und durchgefallen".

**Stufe 3 - Effizienz**
- Learning-Verdraengung war FIFO: Bei den 7 Agenten am Limit verdraengte jede neue - auch jede
  belanglose - Regel die aelteste und oft konkreteste. Verdraengt wird jetzt die generischste.
- Cache-stabile Prompt-Reihenfolge: Der volatile Learnings-Block stand zwischen Basis-Prompt und
  Werkzeugkatalog und warf bei jeder neuen Lernregel den unveraenderten Katalog aus dem Cache
  (21,08 Mio. Prompt- gegen 0,84 Mio. Completion-Tokens bei 12% Cache-Trefferquote).
- Nischen-Rollen (`mobile` 0 Aufrufe, `i18n`/`finops` je 1) werden nur noch bei inhaltlich
  passender Anfrage in den Zerlegungs-Prompt aufgenommen - 22 statt 33 Rollen bei einer
  Standard-Backend-Aufgabe.
- Env-Namen-Mapping: Bei 7 Rollen (`PO_MODEL` statt `PRODUCT_OWNER_MODEL` etc.) pruefte
  `get_model_for_agent()` den falschen Variablennamen, wodurch ein Rollen-Override still vom
  Fachbereichs-Override ueberstimmt wurde - die Vorrang-Regel kehrte sich um.

**Dabei aufgedeckte latente Bugs:** Die Provider-Wrapper entfernen ihr Praefix beim Anlegen
(`groq:openai/gpt-oss-120b` -> `openai/gpt-oss-120b`). Vergleiche der Form
`agent._llm.model_name == HEAVY_MODEL` waren dadurch strukturell falsch -
`_escalate_agent_models()` haette jeden Agenten fuer nicht hochgestuft gehalten, sobald HEAVY ein
praefixbehaftetes Modell ist. `core/llm_factory.normalize_model_name()`/`is_same_model()` loesen
das an allen betroffenen Stellen.

Verifiziert: `ruff check` sauber, vollstaendige pytest-Suite **1683 passed** (von zuvor 1504;
179 neue Tests in 9 neuen Testdateien). `main.py --check-models` bestaetigt live, dass jetzt alle
vier Stufen mit dem konfigurierten Modell antworten - zuvor kollabierten alle drei auf dasselbe.

---

## ⚡ Sync/Async-SQLAlchemy-Konflikt jetzt schon im schnellen Pre-Flight-Check erkannt

Fortsetzung des `/goal`-Auftrags (Database Architecture Drift): `core/verifier/completeness.
_conflicting_sqlalchemy_config()` erkannte einen Mix aus synchronem `create_engine()` und
asynchronem `create_async_engine()` im selben Projekt bereits zuverlässig - aber erst als Teil
der vollen, teuren Verifikation nach dem echten Testlauf. `core/pre_flight_check.py`, der
schnelle deterministische Check VOR der Testsuite, kannte diese Fehlerklasse bisher nicht.

`_check_conflicting_sqlalchemy_engines()` ergänzt denselben Check (inkl. derselben Alembic-
Ausnahme für idiomatisch synchrone Migrationsskripte) als neuen blockierenden Issue-Typ
`conflicting_sqlalchemy_engines` - ein Projekt mit dieser Architektur-Drift wird jetzt schon
vor dem ersten, unnötigen pytest-Lauf markiert statt erst danach.

Verifiziert: `ruff check` sowie die vollständige pytest-Suite (1492 passed) laufen fehlerfrei
durch (ein unabhängiger `ConnectionResetError`-Flake in `test_dashboard_cancel.py` lief isoliert
erneut grün und stammt nicht aus dieser Änderung).

---

## 🛠️ Agenten-Prompts für Contract-/Typ- und DB-Architektur-Konsistenz geschärft

Nutzeranfrage (`/goal`): gezieltes Framework- & Agenten-Refactoring gegen fünf konkrete
Schwachstellen aus den letzten Läufen (Contract-/Typ-Inkonsistenzen, Import-Drift/Phantom-
Symbole, sync/async-DB-Architektur-Drift, schwache `tester`/`accessibility`-Agenten,
Wissens-Transfer aus `memory/team_lessons.jsonl`). Bestandsaufnahme ergab: der Symbol-
Existenz-Check (AST) und die Sync/Async-SQLAlchemy-Konflikt-Erkennung waren in
`core/verifier/completeness.py` bereits vollständig implementiert und getestet (siehe
`tests/test_verifier_completeness.py`), ebenso die geschärften `AVAILABLE_AGENTS`-Trigger-
Beschreibungen für `accessibility`/`data_engineer`/`performance` in `core/task_manager.py` -
diese Punkte waren aus früheren Retrospektiven bereits erledigt.

Ergänzt wurden die noch offenen Lücken direkt in den Agenten-Systemprompts, die diese
Fehlerklassen überhaupt erst vermeiden sollen: `tester_agent` prüft jetzt explizit
`isinstance(result, <PydanticKlasse>)` statt eines bloßen `isinstance(res, dict)`, benennt
`app.dependency_overrides[get_async_session]` vs. `[get_db]` korrekt je nach Projekt-Typ und
verlangt eigene Testfälle für Resilience-/Fallback-Rückgaben mit identischem Datentyp wie der
Regelfall. `database_agent` und `backend_agent` tragen jetzt beide ein striktes
"Single-DB-Paradigm" (keine Mischung aus `create_engine`/`create_async_engine`, genau eine
zentrale `Base`-Definition, Fallback-Werte als typisierte Pydantic-Instanzen statt roher
Dicts). `accessibility_agent` liefert jetzt verbindlich datei- und zeilenbezogene Korrekturen
am tatsächlichen Projekt-Code (inkl. `onKeyDown`-Handlern bei `role="button"`) statt eines
generischen WCAG-Checklisten-Berichts.

Verifiziert: `ruff check` (agents/, core/, interface/, memory/) sowie die vollständige
pytest-Suite (1490 passed) laufen fehlerfrei durch.

---

## 🛑 Deutliche Eskalation, wenn ein Governance-Ticket seine automatischen Retries ausschöpft

Nutzeranfrage: Fortsetzung der Framework-Optimierungen. Realer Fund im aktuellen Backlog
(`memory/backlog.json`): `recurring-failure-sentinelproxy`/`recurring-lint-sentinelproxy` stehen
seit `retries: 2` (== `MAX_GOVERNANCE_TICKET_RETRIES`) dauerhaft auf "blocked" -
`core/backlog_worker.py._governance_retry_pool()` greift sie absichtlich nie wieder auf
(dokumentierte Design-Entscheidung: "bleibt bewusst blocked liegen, sichtbar für eine
menschliche Prüfung"). Die dabei gesendete Benachrichtigung war aber bei JEDEM erfolglosen
Versuch identisch ("Backlog-Ticket benötigt Aufmerksamkeit") - beim letzten erlaubten Versuch
genauso wie beim ersten. Ohne `MAX_GOVERNANCE_TICKET_RETRIES` im Kopf zu haben, wirkte ein
dauerhaft "blocked" liegendes Ticket wie "wird noch automatisch behoben", nicht wie "braucht
JETZT einen Menschen, kein weiterer automatischer Versuch folgt".

`run_backlog_poll_cycle()` erkennt jetzt den Moment, in dem ein Governance-Retry-Ticket seinen
LETZTEN erlaubten automatischen Versuch verbraucht (`ticket.retries + 1 >= MAX_GOVERNANCE_
TICKET_RETRIES`) UND weiterhin nicht "pr_opened" erreicht: sendet eine deutlich anders
formulierte Benachrichtigung ("🛑 Automatische Wiederholungsversuche ausgeschöpft") statt der
generischen, und trägt die Ticket-ID zusätzlich in `BacklogPollReport.retries_exhausted_ticket_
ids` ein. `python main.py --work-backlog` hebt das jetzt auch in der Konsolenausgabe separat
hervor, statt es in der generischen Ergebnisliste untergehen zu lassen.

Neue Tests: `tests/test_backlog_worker.py` (3 neue Fälle: letzter Versuch scheitert → als
ausgeschöpft gemeldet, nicht-letzter Versuch scheitert → nicht gemeldet, letzter Versuch
gelingt → nicht gemeldet). Volle Suite (1490 Tests) grün, `ruff check` clean.

---

## 🧠 Proaktive Import-Namen-Prüfung, ehrliche Kennzeichnung von Kontingent-Erschöpfung in Tickets

Nutzerauftrag: Analyse der letzten realen KI-Team-Läufe (`workspace/agent_governance`,
`memory/history_default.json`, `memory/team_lessons.jsonl`) und Umsetzung sinnvoller
Verbesserungen AM FRAMEWORK selbst (nicht an einzelnen Workspace-Projekten). Zwei konkrete,
echte Lücken gefunden und behoben:

1. **`ImportError: cannot import name 'X' from 'Y'` trat wiederholt identisch auf, bevor je ein
   Testlauf lief:** `memory/history_default.json` zeigte denselben
   `ImportError: cannot import name 'RateLimitMiddleware' from 'app.middleware.rate_limit'` an
   mehreren, verschiedenen Läufen - die importierte Klasse existierte im Zielmodul tatsächlich
   unter einem anderen Namen. `core/pre_flight_check.py` prüfte bisher nur, ob das MODUL
   existiert (`_is_local_module`/`_check_missing_init`), nie, ob der konkret importierte NAME
   darin auch wirklich definiert ist - eine bereits vorhandene, aber rein REAKTIVE
   Selbstlern-Logik (`agents/orchestrator/verification.py._import_name_error_target()`,
   `tests/test_import_name_error_learning.py`) griff erst NACH einem echten pytest-Fehlschlag.
   Neue `_check_imported_names_exist()` (neuer Befund-Typ `unresolved_import_name`, blockierend
   wie `missing_init`/`syntax_error`) erkennt dieselbe Fehlerklasse jetzt per `ast.parse()` -
   ohne LLM-Aufruf, Millisekunden statt eines vollen Testlaufs. Bewusst konservativ, um keine
   falschen Befunde zu erzeugen: überspringt jedes Zielmodul mit `from x import *`
   (Namen dann statisch nicht mehr bestimmbar) und behandelt `from <package> import <submodul>`
   immer als gültig, wenn `<submodul>.py`/`<submodul>/` existiert - unabhängig davon, ob
   `__init__.py` den Namen explizit re-exportiert (Python löst Submodul-Importe so auf).
2. **Ein durch API-Kontingent-Erschöpfung verursachter Laufabbruch sah in einem
   `unresolved-governance-critical-`/`recurring-failure-`-Ticket identisch aus wie ein echter,
   ungelöster Code-Defekt:** derselbe Lauf an `agent_governance` endete mit 11 von 32
   Agenten-Aufrufen, die in Folge mit `total_tokens: 0` scheiterten, weil alle konfigurierten
   Provider gleichzeitig ihr Tages-Kontingent ausgeschöpft hatten (`429 RESOURCE_EXHAUSTED`) -
   das eröffnete Ticket enthielt keinen Hinweis darauf, war für eine spätere Prüfung nicht von
   einem echten Bug zu unterscheiden. `core/backlog_worker.py._is_provider_exhaustion_error()`/
   `_all_agents_failed_on_provider_exhaustion()` erkannten dieses Muster bereits, aber nur für
   den autonomen `--work-backlog`-Ticket-Pfad. Diese Erkennung lebt jetzt in
   `core/provider_exhaustion.py` (von `core/backlog_worker.py` weiterhin per Alias genutzt) und
   ist zusätzlich in `agents/orchestrator/dispatch.py._run_agents_parallel()` verdrahtet: scheitert
   eine ganze Welle von Agenten-Aufrufen ausschließlich an einer Kontingent-Erschöpfung, setzt das
   `self._provider_exhausted_this_run` für den Rest des Laufs - jedes danach eröffnete
   `unresolved-governance-critical-`/`unresolved-permission-blocked-`/`recurring-failure-`-Ticket
   trägt jetzt einen expliziten Hinweis, dass die Ursache (auch) ein Kontingent-Engpass statt
   zwingend ein echter Defekt gewesen sein könnte.

3. **`SASTAdapter` gibt ein `Dict` zurück statt des annotierten Pydantic-Modells - dasselbe
   Fehlerbild wie der bereits behobene opspilot-Fund, aber OHNE Resilience-/Circuit-Breaker-
   Kontext:** `core/verifier/completeness.py._resilience_fallback_type_mismatch()` (Retrospektive
   2026-09-08) erkennt "Dict-Literal statt Pydantic-Modell" bisher NUR innerhalb eines
   `except CircuitBreakerError`-artigen Fallback-Zweigs - der `agent_governance`-Fund
   (`unresolved-governance-critical-agent_governance`-Ticket, 2026-09-09) war aber die normale
   Implementierung einer Methode, kein Resilience-Fallback, und blieb deshalb unerkannt. Neue,
   allgemeinere `_direct_dict_return_type_mismatch()` (AST-basiert statt zeilenbasiert): prüft
   JEDE Funktion/Methode mit einer "modellartigen" Rückgabetyp-Annotation (einfacher, groß
   geschriebener `ast.Name`, nicht in der neuen `core/verifier/models.py._GENERIC_RETURN_TYPE_
   NAMES`-Liste) gegen jede eigene `return`-Stelle - verschachtelte innere Funktionen mit
   eigener Signatur werden dabei bewusst nicht mitgeprüft (`_own_return_statements()`).

Bewusst NICHT umgesetzt, weil es eine bereits bestehende, dokumentierte Design-Entscheidung
gebrochen hätte (kein offener Punkt, sondern eine geprüfte und verworfene Idee): Governance-/
Recurring-Tickets künstlich vor reguläre "todo"-Tickets zu priorisieren -
`core/backlog_worker.py.run_backlog_poll_cycle()` sortiert automatische Wiederholungsversuche
bewusst HINTER frischen, vom Nutzer/Dashboard eingereichten Tickets gleicher Priorität ("ein
bewusst eingereichtes Ticket soll nicht hinter einem automatischen Retry zurückstehen müssen").
Ein `priority=1`-Versuch wurde umgesetzt, beim Test gegen diese Dokumentation als Regression
erkannt und wieder vollständig zurückgenommen (kein Diff in `agents/orchestrator/__init__.py`,
`agents/orchestrator/verification.py`, `core/workspace_audit.py` gegenüber dem Ausgangsstand).

Neue Tests: `tests/test_pre_flight_check.py` (6 neue Fälle: RateLimitMiddleware-Reproduktion
absolut/relativ, korrekter Import, gültiger Submodul-Import, Wildcard-Re-Export,
Drittanbieter-Import unberührt), `tests/test_provider_exhaustion.py` (13 Fälle für
`core/provider_exhaustion.py` und die neue Verdrahtung in `DispatchMixin._run_agents_parallel()`),
`tests/test_verifier_completeness.py` (4 neue Fälle für `_direct_dict_return_type_mismatch()`).
Volle Suite (1487 Tests) grün, `ruff check` clean.

---

## 🔐 Dependency-Audit über alle requirements-Dateien, Bandit-B101-False-Positives, Fehlerbehandlungs-Disziplin

Nutzerauftrag: Analyse von vier vermuteten System-/Workflow-Hürden (Sandbox-Dependency-
Desync, fehlende Erst-Tests, wiederkehrende Lint-/SAST-False-Positives, Traceback-Injection
im Fix-Loop). Ergebnis der Analyse: Punkte 1 (requirements-dev.txt-Installation in der Sandbox),
2 (automatische Testsuite-Nachbeauftragung des Testers) und 4 (voller Traceback im Fix-Prompt,
Eskalationskette mit stärkerem Modell) waren bereits robust implementiert
(`core/verifier/environment.py`, `agents/orchestrator/verification.py`). Zwei konkrete, echte
Lücken daneben wurden gefunden und behoben:

1. **`core/verifier/security.py`: `check_dependency_vulnerabilities()` prüfte nur die ERSTE
   gefundene Requirements-Datei gegen die CVE-Datenbank**, obwohl `_requirements_files()`
   längst mehrere Dateien liefert (requirements.txt + requirements-dev.txt) – Testabhängigkeiten
   wie `httpx`/`pytest-asyncio` in requirements-dev.txt blieben dadurch unbemerkt von jedem
   Sicherheits-Scan ausgeschlossen. `_audit_python_dependencies()` übergibt `pip-audit` jetzt
   ein wiederholtes `-r` pro gefundener Datei statt nur der ersten.
2. **`core/verifier/environment.py`: `_requirements_files()` kannte nur requirements.txt/
   -dev.txt**, obwohl `core/manifest_guard.py._PYTHON_REQUIREMENTS_MANIFESTS` bereits
   requirements-test.txt/requirements-prod.txt als gültige Manifeste anerkennt – eine so
   benannte Datei wäre in der Sandbox nie installiert/gescannt worden. Beide Namen ergänzt.
3. **`core/verifier/security.py`: bandit meldete B101 ("Use of assert detected") bei JEDER
   generierten Testdatei**, weil pytest-Tests idiomatisch auf `assert` setzen
   (`agents/tester_agent.py` schreibt das explizit vor) – kein echter Sicherheitsfund, nur
   Dauer-Rauschen. `_sast_python()` schließt jetzt zusätzlich zu den Build-/Umgebungs-
   Verzeichnissen erkannte Testverzeichnisse (`tests/`, `test/`, `__tests__/`) vom Scan aus UND
   überspringt B101 projektweit (`-s B101`) als zweite, robustere Verteidigungslinie – echte
   Regeln (SQL-Injection, hartcodierte Secrets, `shell=True`, …) bleiben unberührt.
4. **`agents/base_agent.py`: neue `exception_handling_note`** in
   `_augment_with_tool_instructions()` (nur für `CODE_WRITING_AGENT_IDS`) – konkrete Regel
   gegen den wiederkehrenden ruff-Fund BLE001 ("Do not catch blind exception"): spezifischere
   Exception verwenden, wo möglich, sonst einen bewusst breiten `except Exception:`-Fallback
   mit kurzem Begründungskommentar kennzeichnen. Setzt VOR dem Fund an, statt ihn erst über das
   nie automatisch schließende `recurring-lint-`-Ticket (`core/project_status.py.
   has_repeated_lint_finding()`) für menschliche Prüfung zu melden.

Neue Tests: `tests/test_verifier_dev_dependency_sync.py` (7 Fälle: Manifest-Namen-Erkennung,
Multi-Datei-Audit, Bandit-Ausschluss/-s B101), 3 in `tests/test_adr_adoption.py`
(Prompt-Regressionstests für die neue Fehlerbehandlungs-Regel). Volle Suite grün, `ruff check`
clean.

---

## 🧹 Mocking-Pflicht für den Tester-Agenten & automatisches Pruning verwaister Tickets

Nutzerauftrag: zwei konkrete, vom Nutzer benannte Verbesserungen.

1. **`agents/tester_agent.py`: Mocking-Richtlinie für externe Netzwerkverbindungen.** Neue,
   konkrete Regel im System-Prompt: JEDER Aufruf an einen echten externen Dienst (Drittanbieter-
   APIs, Zahlungsanbieter, E-Mail/SMS, Cloud-Storage, andere Microservices, externe LLM-APIs)
   MUSS gemockt werden (`unittest.mock`/`AsyncMock`, `respx`/`responses`/`pytest-httpx` für
   Python, `jest.mock()`/`vi.mock()`/`msw` für Jest/Vitest) - Tests laufen automatisiert in einer
   isolierten Umgebung ohne garantierten Internetzugriff und ohne echte Drittanbieter-
   Zugangsdaten, ein ungemockter Aufruf schlägt dort unabhängig von der Anwendungslogik fehl.
   Eine projekteigene Datenbank (SQLite/In-Memory) zählt bewusst NICHT als "extern".
2. **`core/backlog_store.py`: neue `prune_orphaned_tickets()`.** Ein Ticket mit gesetztem
   `project_slug` verweist auf ein konkretes `workspace/<slug>`-Projekt - wird dieses gelöscht,
   blieb das Ticket bisher für IMMER im Backlog liegen (kein Verzeichnis mehr, das ein
   Fix-Auftrag betreffen könnte). Tickets OHNE `project_slug` (teamweite Meta-Tickets wie
   `unused-agent-<id>`/`team-verification-trend`) gelten bewusst NIE als verwaist. Verdrahtet in
   `core/workspace_audit.py.run_workspace_audit_cycle()` (nutzt die dort ohnehin schon ermittelte
   Liste vorhandener Projekte, kein zusätzlicher Dateisystem-Scan), läuft VOR der Pro-Projekt-
   Schleife, damit ein gerade gelöschtes Projekt nicht erst fälschlich als frischer
   Verifikations-Fehlschlag auffällt.

Neue Tests: 5 für `prune_orphaned_tickets()` (inkl. Kein-Schreiben-bei-leerem-Ergebnis und
Standard-Auflösung über `WorkspaceManager`), 2 für die Verdrahtung im Audit-Zyklus. Volle Suite
grün, `ruff check` clean.

---

## 🎫 Dieselbe Detail-Löschung beim Aufgreifen auch im Issue-Watcher geschlossen

Nutzeranfrage: Fortsetzung derselben Analyse - derselbe, bereits in `core/backlog_worker.py`
behobene Fehler (siehe Eintrag weiter unten) trat identisch auch in `core/issue_watcher.py`
auf: `_process_single_issue()` markierte ein Issue-Ticket beim Aufgreifen per
`upsert_ticket(..., status="in_progress")` ohne `detail=...` - da `detail` in
`core/backlog_store.py.upsert_ticket()` kein Sentinel-Parameter ist (fester Default `""`),
hätte ein erneutes Aufgreifen desselben Issues (z.B. nach einer vorherigen offenen Rückfrage)
den bereits bekannten Kontext sofort gelöscht. Rein durch Code-Lektüre nachgewiesen (dieselbe,
bereits bestätigte Fehlerklasse), nicht durch einen weiteren Live-Vorfall.

- **`core/issue_watcher.py`:** liest das bestehende Ticket-Detail per `get_ticket()` vor dem
  Aufgreifen und gibt es explizit weiter, statt es stillschweigend zu überschreiben.
- **`tests/test_issue_watcher.py`:** neuer Test bestätigt den Detail-Erhalt.

Bei dieser Gelegenheit auch geprüft, ob core/issue_watcher.py/core/backlog_worker.py NACH dem
Öffnen eines PRs zum Hauptbranch zurückwechseln sollten (das hätte den Git-Vorfall aus dem
vorigen Eintrag verhindert) - bewusst NICHT geändert: der Code dokumentiert das explizit als
gewollte Design-Entscheidung (Zeile bei `create_pull_request()`), da ein Zurückwechseln jede nur
auf dem Feature-Branch committete Datei aus dem Arbeitsverzeichnis entfernen würde, bis der PR
gemerged ist. Das eigentliche Risiko (siehe voriger Eintrag) ist `GitHubAgent.commit()`s
`git add -A`, das bei GLEICHZEITIG offenen, unrelated Änderungen im Arbeitsverzeichnis
sweep-artig mit eingesammelt wird - eine Betriebsregel (nicht parallel zu `--work-backlog`/
`--check-issues` von Hand am Framework arbeiten), keine Code-Änderung.

Volle Suite grün, `ruff check` clean.

---

## ⏳ Tages-Kontingent vs. Minutenlimit: erschöpfte Modelle bekamen alle denselben kurzen Cooldown

Nutzeranfrage: Fortsetzung derselben Analyse, ausgelöst durch zwei echte `--work-backlog`-Läufe
in dieser Session. Google meldete dabei strukturiert: `quotaId:
"GenerateRequestsPerDayPerProjectPerModel-FreeTier", quotaValue: "20"` - ein TAGES-Kontingent
von 20 Anfragen, kein kurzes Minutenlimit. `core/token_guard.py.mark_model_exhausted()` vergibt
aber für JEDES 429 denselben generischen `default_cooldown_seconds` (60s) - jeder weitere Agent
im selben Lauf (und jeder spätere `--work-backlog`-Retry) versuchte das für Stunden erkennbar
erschöpfte Modell trotzdem sofort wieder, statt es zuverlässig zu überspringen. Live beobachtet:
in einem einzigen Lauf scheiterten dadurch nacheinander Backend-Entwickler, QA-Tester,
GitHub-Agent und Code-Reviewer jeweils erneut an derselben, bereits bekannten Erschöpfung.

- **`core/llm_factory.py`:** neue `_exhaustion_cooldown_seconds()` erkennt das `"PerDay"`-Signal
  im rohen Fehlertext (kein zusätzlicher API-Zugriff/Parsing nötig) und vergibt dafür
  `DAILY_QUOTA_COOLDOWN_SECONDS` (4h) statt des kurzen Standard-Cooldowns - an beiden Stellen,
  die ein Gemini-429 behandeln (`generate_with_tools()`, `_call_with_retry_and_usage()`).
- **`tests/test_llm_routing.py`:** neuer Test mit dem ECHTEN, real beobachteten Fehlertext
  bestätigt den langen Cooldown; bestehende Tests (kurzes Limit) bleiben unverändert grün.

Volle Suite grün, `ruff check` clean.

---

## 🧪 Testisolations-Lücke: `token_guard`-Erschöpfungszustand sickerte zwischen Tests durch

Nutzeranfrage: Fortsetzung derselben Analyse. Ein voller Suite-Lauf (nicht der isolierte
Einzeltest) zeigte `tests/test_llm_routing.py::
test_claude_candidate_is_skipped_entirely_without_anthropic_api_key` als einzigen Fehlschlag
(`1 failed, 1343 passed`). Root Cause: `core/token_guard.py` hält mit dem Modul-Singleton
`token_guard` einen EINZIGEN, prozessweiten Erschöpfungszustand (`_exhausted_models`) - mehrere
Tests markieren darüber gezielt Modelle als "erschöpft" (teils mit `cooldown_seconds=999.0`,
fast 17 Minuten). Einzelne Testklassen räumen das bereits in ihrer eigenen `tearDown()` auf,
aber jeweils nur für eine fest verdrahtete, eigene Liste bekannter Modellnamen - ein Test in
einer anderen Klasse ohne solche Aufräum-Logik lässt den Zustand trotzdem in später laufende,
komplett unabhängige Tests durchsickern. Dieselbe Fehlerklasse wie der bereits dokumentierte
`_gemini_rate_limiter`-Fund (siehe `tests/conftest.py`).

- **`tests/conftest.py`:** neue autouse-Fixture `_reset_token_guard_exhaustion` - leert
  `token_guard._exhausted_models` zentral vor UND nach jedem Test, unabhängig davon, welcher
  konkrete Test den Zustand hinterlässt (deckt auch künftige, noch ungeschriebene Tests ab,
  dieselbe Linie wie die bereits bestehende Rate-Limiter-Fixture).

Volle Suite grün, `ruff check` clean.

---

## 🔁 Verwaiste "in_progress"-Tickets: doppelte Ursache für dauerhaft unsichtbare Backlog-Einträge

Nutzeranfrage: Fortsetzung derselben Analyse, diesmal ausgelöst durch einen echten
`--work-backlog`-Lauf während dieser Session. `memory/backlog.json` zeigte ein reales Ticket
(`audit-service_bookmark_monitor`) seit über 15 Stunden unverändert bei `status="in_progress"`
UND `detail=""`. Zwei zusammenhängende Ursachen gefunden:

1. **`core/backlog_worker.py._process_single_ticket()`** markierte ein Ticket beim Aufgreifen
   bisher per `upsert_ticket(..., status="in_progress")` OHNE `detail=...` - anders als
   `project_slug`/`priority`/`estimate`/`epic`/`retries` ist `detail` in
   `core/backlog_store.py.upsert_ticket()` KEIN Sentinel-Parameter (fester Default `""`, kein
   "unverändert lassen"), das löschte den bereits bekannten Befund also sofort beim Aufgreifen -
   lange bevor überhaupt ein Ergebnis vorliegt. Behoben: `detail=ticket.detail` wird jetzt
   explizit mitgegeben.
2. Stürzt der Prozess DANACH ab (Rechner-Neustart, harter Abbruch - echt beobachtet), bleibt das
   Ticket für IMMER bei `status="in_progress"` hängen: weder `ready_todo` (nur `"todo"`) noch
   `_governance_retry_pool()` (nur `"blocked"`) picken diesen Status je wieder auf. Neue
   `_recover_stale_in_progress_tickets()` setzt ein seit `STALE_IN_PROGRESS_HOURS` (3h)
   unverändertes `"in_progress"`-Ticket auf seinen vermutlichen Vorher-Status zurück
   (Governance-/Audit-Retry-Tickets → `"blocked"`, respektiert damit weiterhin
   `MAX_GOVERNANCE_TICKET_RETRIES`; alle anderen → `"todo"`) - läuft VOR dem WIP-Limit-Check,
   damit ein längst abgestürzter Prozess nicht auf unbestimmte Zeit echte neue Arbeit blockiert.

`tests/test_backlog_worker.py`: 3 neue Tests (Detail-Erhalt beim Aufgreifen, verwaistes Ticket
wird wieder aufgreifbar, ein GERADE ERST aufgegriffenes Ticket bleibt unangetastet). Volle Suite
grün, `ruff check` clean.

---

## 🔍 Workspace-Audit-Tickets trugen nur einen Zähler statt der bereits bekannten Testfehler-Details

Nutzeranfrage: Fortsetzung derselben Analyse. Dieselbe Fehlerklasse wie beim vorigen
Backlog-Detail-Fix, an einer zweiten Stelle: `core/workspace_audit.py` (`--audit-workspace`,
Tickets `audit-<slug>`) schrieb bei einem echten Testfehlschlag bisher nur
`"{len(result.failures)} echte(r) Testfehler"` als Ticket-Detail - ein reiner Zähler, obwohl
`ProjectVerifier.run_tests()` bereits Test-ID, Fehlermeldung und betroffene Dateien kannte.
Da `audit-`-Tickets über `core/backlog_worker.py._GOVERNANCE_RETRY_PREFIXES` selbst retry-fähig
sind und `ticket.detail` der einzige Kontext ist, den `_process_single_ticket()` in den
Fix-Auftrag mischt, hatte ein automatischer Retry dadurch strukturell weniger Information zur
Verfügung, als längst berechnet vorlag.

- **`core/workspace_audit.py`:** baut das Ticket-Detail bei einem echten Testfehlschlag jetzt
  aus den tatsächlichen `TestFailure`-Objekten (Test-ID/Fehlermeldung/Dateien, dieselben Felder
  wie im regulären Fix-Loop) statt aus einem bloßen Zähler - `reason_skipped` (z.B.
  "Unvollständiges Projekt erkannt") bleibt unverändert die bevorzugte Quelle, wenn vorhanden.
- **`tests/test_workspace_audit.py`:** neuer Test bestätigt, dass das Ticket-Detail Test-ID,
  Fehlermeldung und Dateien enthält statt nur eines Zählers.

Volle Suite grün, `ruff check` clean.

---

## 🎫 Backlog-Retry überschrieb den ursprünglichen Befund mit einer kontextlosen Ausgangs-Zeile

Nutzeranfrage: Fortsetzung der Team-Analyse ("bis alle Fehler behoben sind"). Zwei reale,
dauerhaft "blocked" hängende Tickets (`recurring-lint-sentinelproxy`,
`recurring-failure-sentinelproxy`, beide `retries: 2`) trugen exakt denselben, komplett
kontextlosen Detail-Text: "Ticket bearbeitet, dabei aber keine Datei geändert - vermutlich war
der Titel nicht eindeutig genug." Ursache: `core/backlog_worker.py.run_backlog_poll_cycle()`
überschrieb `ticket.detail` nach JEDEM Retry-Versuch bedingungslos mit der knappen
Ausgangs-Zeile des Versuchs - für Governance-/Recurring-*-Tickets ist `detail` aber der EINZIGE
Träger des ursprünglich erkannten Befunds, den `_process_single_ticket()` extra in den
Fix-Auftrag mischt. Nach GENAU EINEM Fehlschlag ohne neue Information war dieser Kontext für
jeden weiteren automatischen Retry unwiderbringlich weg - jeder folgende Versuch hatte dadurch
WENIGER Information als der erste, garantiert kein besseres Ergebnis, bis
`MAX_GOVERNANCE_TICKET_RETRIES` erreicht war und das Ticket für immer blockiert liegen blieb.

- **`core/backlog_worker.py`:** ein Ausgang OHNE neue, verwertbare Information (`no_changes`,
  `error`) behält `ticket.detail` nach einem Retry jetzt unverändert bei; ein Ausgang mit echtem
  Erkenntnisgewinn (PR eröffnet, CI-Fehler, Rückfrage, gefundene Secrets) überschreibt ihn
  weiterhin wie bisher.
- **`tests/test_backlog_worker.py`:** zwei neue Tests - Detail bleibt nach einem kontextlosen
  Fehlschlag erhalten bzw. wird bei echtem PR-Erfolg weiterhin aktualisiert.

Volle Suite grün, `ruff check` clean.

---

## 🧪 "Ran 0 tests" / "NO TESTS RAN": fehlendes `pytest` in der Umgebung war die stille Ursache

Nutzeranfrage: Fortsetzung derselben Analyse. Zwei weitere reale, dauerhaft "blocked" Tickets
(`recurring-failure-event_relay`, `recurring-failure-service_bookmark_monitor`) zeigten
identisch: "Fixversuch änderte nichts an 1 Testfehler(n) – vermutlich falscher/unzureichend
instruierter Agent" mit der Fehlermeldung "Ran 0 tests in 0.000s / NO TESTS RAN" und
"Betroffene Dateien: unbekannt". Root Cause gefunden: `core/verifier/testrunner.py._run_
pytest_or_unittest()` prüft `import pytest` und fällt bei Fehlschlag STILLSCHWEIGEND auf
`python -m unittest discover` zurück - das erkennt generierten, im pytest-Stil geschriebenen
Testcode (einfache `def test_...()`-Funktionen ohne `unittest.TestCase`) aber gar nicht als
Tests. Ohne Traceback (reine Testlauf-Diagnostik, kein Stacktrace) hatte der Fix-Loop keinen
Datei-Bezug und beauftragte blind den `tester` - der konnte die tatsächliche, umgebungsbedingte
Ursache (fehlendes `pytest` in requirements.txt/requirements-dev.txt) strukturell nie beheben.

- **`core/verifier/environment.py`:** neue `_ensure_pytest_available()` - stellt `pytest` VOR
  jedem Testlauf sicher, unabhängig davon, ob der jeweilige Agent daran gedacht hat, es als
  Abhängigkeit in requirements.txt aufzunehmen (es ist das vom FRAMEWORK selbst gewählte
  Test-Werkzeug, keine Produktabhängigkeit des generierten Projekts). Läuft nur, wenn überhaupt
  eine venv angelegt wurde UND echte Python-Testdateien existieren, sonst unnötiger Zusatzaufruf.
- **`agents/orchestrator/verification.py`:** zweite Verteidigungslinie für den Fall, dass die
  Nachinstallation selbst fehlschlägt (z.B. kein Netzwerkzugriff) - neue `_diagnose_no_tests_ran()`
  erkennt das "Ran 0 tests"/"NO TESTS RAN"/"collected 0 items"-Muster und liefert dem Fix-Agenten
  eine konkrete Diagnose statt eines kontextlosen Tracebacks. Die Routing-Logik bevorzugt für
  GENAU dieses Fehlerbild jetzt den Owner von requirements.txt (meist backend/database) vor dem
  bisherigen blinden `tester`-Fallback.
- **`tests/test_verifier.py`, `tests/test_no_tests_ran_diagnosis.py` (neu):** 5+4 Tests - Diagnose-
  Erkennung, Nachinstallation (fehlend/bereits vorhanden), Routing-Präferenz, volle
  `_run_verification_loop()`-Integration bis `verification_ok=True`.

Volle Suite grün, `ruff check` clean.

---

## 🔀 Governance-Fix-Schleife eskaliert jetzt auch bei wechselnder Symptomatik derselben Ursache

Nutzeranfrage: Fortsetzung der Team-Analyse, konkret Punkt 2 - der reale `event_relay`-Lauf vom
06.09. zeigte denselben ungelösten Governance-Befund zweimal innerhalb von 23 Minuten
(`.ai_team_decisions.jsonl`: 12:29 "ResilienceManager nicht in main.py verdrahtet" → nach einem
Fixversuch, 12:49 "ImportError: `resilience` keine globale Instanz mehr in app/kafka_client.py").
Derselbe Ursache-Bereich, aber ZWEI TEXTLICH UNTERSCHIEDLICHE kritische Befunde - der bereits
bestehende Zirkuit-Breaker (`_no_progress()` in `agents/orchestrator/verification.py`) vergleicht
Fund-Signaturen aber nur auf EXAKTE Wiederholung und griff deshalb nie. Der verpflichtende
Re-Review nach dem letzten Fixversuch eröffnete dadurch direkt ein Backlog-Ticket, OHNE - anders
als beim Zirkuit-Breaker-Pfad - je den zuständigen Fachbereichsleiter mit einer geänderten
Strategie zu versuchen.

- **`agents/orchestrator/verification.py`:** der verpflichtende finale Re-Review
  (`attempt == MAX_REVIEW_ITERATIONS`) eskaliert bei weiterhin kritischem Befund jetzt EINMAL an
  den zuständigen Fachbereichsleiter (dieselbe `escalation_attempted`-Sperre wie beim
  `_no_progress()`-Pfad, verhindert eine doppelte Eskalation innerhalb desselben Laufs), bevor das
  Ticket eröffnet wird. Bewusst OHNE die zusätzliche Modell-Eskalation (`_escalate_agent_models()`)
  an dieser Stelle - die bräuchte einen echten Provider-Client
  (`core/llm_factory.py.LLMFactory.create_for_model()`), den bestehende Tests für "unterschiedliche
  Befunde" (`tests/test_governance_no_progress_breaker.py::test_different_critical_findings_do_not_trigger_breaker`)
  bewusst NICHT mocken; die Modell-Eskalation bleibt dem bereits bestehenden `_no_progress()`-Pfad
  vorbehalten.
- **`tests/test_governance_final_reverification.py`:** zwei neue Tests - Eskalation löst das
  Problem (kein Ticket) bzw. Eskalation löst es NICHT (Ticket wird wie bisher eröffnet, die
  menschliche Prüfung bleibt das letzte Netz).

Volle Suite (1328 Tests) grün, `ruff check` clean. Alle bereits bestehenden Governance-/
Eskalations-Tests (inkl. der bewusst ungemockten `create_for_model`-Gegenprobe) unverändert grün.

---

## 💤 Ungenutzte Agentenrollen: von der stillen Lektion zum sichtbaren Backlog-Ticket

Nutzeranfrage: Analyse des gesamten Agenten-Teams auf sinnvolle Verbesserungen, dann konkrete
Umsetzung des priorisierten ersten Punkts. `memory/team_lessons.jsonl` zeigte am 06.09. einen
über mehrere Sessions hinweg wiederkehrenden Fund: 11 von 33 Planer-wählbaren Rollen wurden
über die letzten 100 Läufe kein einziges Mal ausgewählt (`unused_agent`-Kategorie aus
`core/optimization_advisor.py`) - eine frühere Session hatte davon bereits `web_research`,
`finops`, `performance` und `accessibility` durch konkretere "Einsetzen bei"-Trigger in ihrer
Planer-Beschreibung behoben, aber (a) die verbleibenden 7 Rollen unbehandelt gelassen und (b)
der Fund selbst blieb eine stille Zeile in einer JSONL-Datei, die niemand routinemäßig liest.

1. **`core/task_manager.py`: dieselbe Beschreibungs-Schärfung für die verbleibenden 7 Rollen**
   (`copywriter`, `image_generator`, `data_engineer`, `mobile`, `ml`, `prompt_engineer`,
   `i18n`) - jede bisherige Beschreibung nannte nur WAS die Rolle kann, nie WANN man sie
   gegenüber einer verwandten Rolle wählt (`ml` vs. `prompt_engineer`, `data_engineer` vs.
   `backend`/`database`, `mobile` vs. `frontend`). Jetzt mit expliziten "Einsetzen bei"-Triggern
   UND einer Abgrenzung zur nächstliegenden Rolle.
2. **`core/optimization_advisor.py`: neue `record_unused_agent_tickets()`.** Öffnet/aktualisiert
   pro betroffener Rolle ein stabiles Backlog-Ticket (`unused-agent-<id>`, `status="todo"`,
   `source="optimization_advisor"`) - sichtbar und verfolgbar im Kanban-Board statt nur in
   `team_lessons.jsonl`. `source="optimization_advisor"` ist bewusst NICHT in
   `core/backlog_worker.py._AUTONOMOUS_SOURCES` enthalten: ob eine Rolle wirklich überflüssig
   ist oder nur unklar beschrieben war, ist eine menschliche Abwägung, kein Fix, den
   `--work-backlog` selbstständig übernehmen soll.
3. **`agents/orchestrator/__init__.py`:** ruft `record_unused_agent_tickets()` direkt neben dem
   bereits bestehenden `record_suggestions_as_lessons()`-Aufruf auf - derselbe Fund landet jetzt
   an BEIDEN Stellen (Lektion fürs Agenten-Prompt-Gedächtnis UND Ticket fürs Board).
4. **`tests/conftest.py`:** die bestehende `_no_real_team_lesson_writes`-Fixture patcht jetzt
   zusätzlich `record_unused_agent_tickets` als No-Op - ohne diesen Patch hätte ein Testlauf mit
   einem echten `unused_agent`-Befund in der Historie ein echtes Ticket in die VERSIONIERTE
   `memory/backlog.json` geschrieben (dieselbe Fehlerklasse wie der bereits dokumentierte reale
   Vorfall mit `team_lessons.jsonl`, nur eine Datei weiter).
5. **`evals/tasks.py`: neue Referenzaufgabe `faq_rag_chatbot`.** Keine der bisherigen 5
   Aufgaben verlangte RAG/Embeddings oder LLM-Prompting - `ml` und `prompt_engineer` hatten
   dadurch strukturell nie eine passende Aufgabe, unabhängig von ihrer Beschreibung. Die neue
   Aufgabe (FAQ-Chatbot mit lokaler Vektordatenbank + Prompt-Injection-Guardrails) braucht
   beide Rollen fachlich echt, statt sie nur per Stichwort zu erzwingen.

Volle Suite grün, `ruff check` clean.

---

## 🏗️ Fünf Framework-Lücken aus der event_relay-Retrospektive vollständig geschlossen

Nutzeranfrage: die im vorigen Retrospektive-Eintrag identifizierten fünf Verbesserungen
vollständig umsetzen und dabei ausschließlich das FRAMEWORK selbst (nicht die generierten
Testprojekte) härten - Ziel: professioneller, autonomer, selbstoptimierend, mit einem
Agenten-Loop, der bis zum Projektziel führt, statt bei der ersten Stagnation aufzugeben.

1. **`core/optimization_advisor.py`: cross-projekt wiederkehrende Kategorien.**
   `_find_recurring_lesson_categories()` gruppiert nach (project_slug, category) und sah daher
   NIE das dominanteste real beobachtete Muster: `unresolved_governance_critical` trat in 9 von
   15 Lektionen auf, aber an 9 VERSCHIEDENEN Projekten - kaum ein Slug kam zweimal vor. Neue
   `_find_recurring_teamwide_categories()`/`RecurringTeamWideCategory` aggregieren zusätzlich
   NUR nach `category` (projektübergreifend, `MIN_TEAMWIDE_LESSON_RECURRENCE = 5`) und schließen
   `project_slug="_team"`-Meta-Funde aus - macht strukturelle FRAMEWORK-Lücken sichtbar, die
   jedes neue Projekt gleichermaßen treffen, statt sie in fünfzehn Einzelfällen zu verstecken.
2. **`core/team_memory.py`: Schweregrad-gewichtete Lektionen-Auswahl.**
   `format_team_lessons_for_agents()` wählte bisher rein nach Rezenz aus `MAX_LESSONS_SHOWN=5`
   Plätzen - ein einzelner Optimierungslauf schrieb real 11 `unused_agent`-Lektionen in
   derselben Sekunde und hätte damit eine kurz zuvor aufgezeichnete
   `unresolved_governance_critical`-Lektion aus dem Agenten-Kontext verdrängt. Neue
   `_select_with_severity_reservation()` reserviert `_RESERVED_HIGH_SEVERITY_SLOTS = 2` Plätze
   für nicht-niedrigschwellige Kategorien (`_LOW_SEVERITY_CATEGORIES`), unabhängig von ihrem Alter.
3. **`core/verifier/models.py`/`completeness.py`: `CompletenessIssue.kind` ersetzt fragile
   Substring-Filter.** `agents/orchestrator/verification.py` filterte "lokaler Import schlägt
   fehl"-Funde bisher per `"existierendes lokales" in message` - `_check_symbols_in_module_file()`
   formuliert einen fehlenden SYMBOL-Import (z.B. `from app.resilience import resilience`, wenn
   `resilience` dort nicht mehr definiert ist) aber bewusst OHNE diese Zeichenfolge. Genau diese
   Fehlerklasse (real: `RateLimitMiddleware`/`SimpleRateLimiter` bei zeiterfassung_app UND
   `resilience` bei event_relay) fiel dadurch durch BEIDE Filter (Vorab-Import-Check UND
   Governance-Fix-Prompt-Anreicherung), obwohl `check_completeness()` sie längst korrekt erkannte.
   Ein neues `kind="missing_local_import"`-Tag ersetzt beide Substring-Filter durch einen
   stabilen, maschinenlesbaren Vergleich.
4. **`agents/orchestrator/verification.py`: harte strukturelle Gegenprobe im finalen
   Governance-Re-Review.** Der verpflichtende Re-Review nach dem letzten Fix-Versuch verließ
   sich bisher AUSSCHLIESSLICH auf die Einschätzung des LLM-Reviewers - real akzeptierte er
   einen Fix als erledigt, der einen frischen `ImportError` einführte (die globale
   `resilience`-Instanz wurde im selben Fix entfernt, der Import blieb). `check_completeness()`
   läuft jetzt zusätzlich als deterministische Gegenprobe: ein struktureller Neu-Bruch gilt als
   weiterhin kritisch, unabhängig vom LLM-Urteil.
5. **`agents/orchestrator/verification.py`: Eskalationsleiter für die Governance-Fix-Schleife.**
   `_run_verification_loop` eskaliert bei Stagnation bereits an den Fachbereichsleiter UND an
   HEAVY_MODEL, bevor sie aufgibt - `_run_governance_fix_loop` brach bei "kein Fortschritt"
   bisher nach GENAU EINEM Fixversuch direkt zum Ticket ab. Durchläuft jetzt dieselbe
   Eskalationsleiter (Fachbereichsleiter mit geänderter Strategie, dann ein letzter Versuch mit
   HEAVY_MODEL), bevor ein Backlog-Ticket eröffnet wird - der spätere `--work-backlog`-Retry
   eskaliert zwar ebenfalls das Modell, aber erst im nächsten Scheduler-Zyklus.

Nebenbefund beim Testen von Punkt 5: `tests/test_governance_no_progress_breaker.py` patchte
`core.llm_factory.LLMFactory.create_for_model` bisher NICHT (anders als das Pendant
`tests/test_verification_no_progress_breaker.py`) - ohne den Patch hätte die neue
Modell-Eskalation einen ECHTEN Provider-Client konstruiert. Ergänzt, bevor es zu echten
API-Aufrufen in der Testsuite kommen konnte.

Volle Suite grün, `ruff check` clean.

---

## 🧪 Echter Team-Lauf gegen `event_relay` deckt Testisolations-Lücke im Optimization-Advisor auf

Nutzeranfrage: volle Testsuite prüfen und die Session abschließen. Das Team baute im Rahmen
dieser Session `workspace/event_relay` (Kafka-Event-Relay mit Resilience-Layer) neu auf - ein
echter Lauf, kein synthetischer Test. `core/optimization_advisor.py` erkannte dabei über die
`unused_agent`-Kategorie (siehe letzter Eintrag unten) 11 seit mindestens 20 Läufen nie vom
Planer gewählte Rollen und schrieb sie als 11 Lektionen mit identischem `project_slug` ("_team")
in `memory/team_lessons.jsonl` - genug, um `MIN_LESSON_RECURRENCE` in
`_find_recurring_lesson_categories()` zu überschreiten.

- **`tests/test_optimization_advisor.py`:** Die Basisklasse `TestOptimizationAdvisor` isolierte
  bisher nur `memory/run_history.py` per temporärer Datei, nicht aber
  `core/team_memory.TEAM_MEMORY_FILE` - andere Testklassen in derselben Datei patchen es
  bereits korrekt. Dadurch las `_find_recurring_lesson_categories()` in Tests wie
  `test_empty_history_yields_empty_report` und
  `test_verification_trend_not_flagged_below_min_sample` ungefiltert die ECHTE,
  repo-weite `team_lessons.jsonl` mit - sobald genug reale Team-Läufe wiederkehrende
  Kategorien zum selben Projekt anhäuften (wie oben durch den `event_relay`-Lauf geschehen),
  schlugen `report.is_empty()`-Erwartungen fehl, obwohl der jeweilige Test selbst keine
  Lektion aufzeichnete. `setUp()` patcht `TEAM_MEMORY_FILE` jetzt zusätzlich auf eine
  temporäre Datei, konsistent mit dem bereits etablierten Muster der anderen Testklassen.

Volle Suite (1275 Tests) grün, `ruff check` clean. Der `event_relay`-Lauf selbst hinterließ
außerdem einen kritischen Governance-Fund (`unresolved_governance_critical`, siehe
`memory/team_lessons.jsonl`): der neue `ResilienceManager` aus `app/resilience.py` ist noch
nicht in `app/main.py`s `create_event` verdrahtet - offen für einen Folgelauf.

---

## 🌱 Team-Wachstums-Retrospektive: Scaffold-Werkzeug, Unterauslastungs-Erkennung & Fallback-Absicherung

Nutzeranfrage: das Framework selbst (nicht die generierten Testprojekte) auf Verbesserungen
für das weitere Wachsen des Agenten-Teams prüfen und die Modellzuweisungen gegen die
tatsächlichen Aufgabenbereiche der Agenten abgleichen.

- **`scripts/new_agent.py` (neu):** automatisiert alle vier bisher von Hand gepflegten
  Registrierungsstellen einer neuen Fachrolle (`agents/orchestrator/__init__.py`-Instanziierung,
  `core.task_manager.AVAILABLE_AGENTS`, `config.AGENT_MODELS`, genau eine
  `config.DEPARTMENT_*_AGENTS`-Menge) in einem CLI-Aufruf, legt das Agenten-Klassen-Gerüst an
  und lässt `ruff check --fix` laufen. Die reinen String-Transformationen sind isoliert testbar
  (`tests/test_new_agent_scaffold.py`, inkl. eines End-to-End-Tests gegen Kopien der echten
  Zieldateien). Siehe ARCHITECTURE.md Abschnitt 1.1.
- **`core/task_manager.py`:** die im Planer-System-Prompt gesendete Liste "Verfügbare
  Agenten-IDs" war ein von Hand gepflegter, zweiter String, unabhängig von der
  programmatisch aus `AVAILABLE_AGENTS` gebauten Beschreibungsliste - beide waren bereits real
  auseinandergelaufen (`agent_trainer` stand als wählbar in der ID-Liste, obwohl bewusst ohne
  Beschreibung ausgeschlossen). `_DECOMPOSE_EXCLUDED_AGENT_IDS` ist jetzt die eine Quelle für
  beide.
- **`tests/test_agent_registry_consistency.py` (neu):** 5 Tests gleichen die vier Register
  gegeneinander ab - verhindert künftiges Auseinanderlaufen beim Wachsen des Teams, statt es
  nur einmalig richtigzustellen.
- **`core/optimization_advisor.py`:** neue `UnusedAgent`-Kategorie meldet Rollen, die über
  mindestens `MIN_TOTAL_RUNS_FOR_UNUSED_CHECK` (20) Läufe kein einziges Mal vom Planer
  ausgewählt wurden - bisher erkannte `analyze()` nur AUFGERUFENE Agenten mit schlechter
  Erfolgsquote, nicht Rollen, die dem Team faktisch nie Nutzen bringen, aber weiterhin
  Wartungsaufwand binden.
- **`tests/test_agent_model_fallback_coverage.py` (neu):** stellt sicher, dass JEDER
  konfigurierte Agent (inkl. `ORCHESTRATOR_MODEL`) mindestens zwei erreichbare Modelle hat,
  falls eines ausfällt - prüft `config.AGENT_MODELS`/`ORCHESTRATOR_MODEL` strukturell gegen
  `core.llm_factory.MODEL_FALLBACKS` bzw. die fest einprogrammierten Fallback-Hops der
  Nicht-Gemini-Clients. Ergebnis: bereits vollständig abgedeckt, jetzt regressionssicher.
- **`config.py`:** `compliance` von STANDARD auf HEAVY hochgestuft - dieselbe Kategorie echter,
  konsequenzenreicher Trade-off-Entscheidungen (DSGVO/GDPR-Audits, Lizenzprüfung GPL vs. MIT)
  wie die direkt daneben bereits bei HEAVY eingestuften `security`/`code_reviewer`-Rollen. Der
  Hauptagent (`ORCHESTRATOR_MODEL = CLAUDE_HEAVY_MODEL`) bleibt die einzige Rolle mit der
  stärksten Modellstufe - alle übrigen Zuordnungen wurden geprüft und als bereits sinnvoll
  nach Aufgabenkomplexität gestaffelt bestätigt.

Volle Suite (1275 Tests) grün, `ruff check` clean.

---

## 🔧 Team-Retrospektive: 5 Selbstoptimierungs-Lücken im Goal-Loop & Optimization-Advisor geschlossen

Nutzeranfrage: Analyse der jüngsten Team-Arbeit auf sinnvolle Optimierungen für Tokennutzung,
Agenteneinsatz und den Selbstoptimierungs-Loop. Fünf konkrete Lücken identifiziert und behoben:

1. **Stagnationserkennung im Goal-Loop war zu strikt** (`core/goal_loop.py`): verlangte exakte
   String-Gleichheit von `failure_detail` zwischen zwei Iterationen. Ein Traceback mit leicht
   verschobener Zeilennummer (beim iterativen Fixen derselben Ursache real häufig) umging das
   komplett – der Loop drehte sich bis `max_iterations` weiter und verbrannte nur Tokens.
   `_normalize_failure_detail()` vergleicht jetzt normalisiert (Groß-/Kleinschreibung,
   Interpunktion UND Zahlen ignoriert).
2. **Optimierungsvorschläge blieben unsichtbar ohne `ENABLE_AUTO_MODEL_TUNING`**
   (`core/optimization_advisor.py.record_suggestions_as_lessons()`): schreibt Modell- und
   Underperformer-Funde jetzt zusätzlich ins teamweite Lektionen-Gedächtnis
   (`core/team_memory.py`), damit sie auch bei autonomen `--work-backlog`/Cron-Läufen ohne
   menschlichen Betrachter sichtbar bleiben. Wird direkt im Orchestrator-Lauf aufgerufen.
3. **Goal-Loop ignorierte bereits erkannte teamweite Verifikations-Trends**: neue
   `get_recent_verification_trend_warning()` fließt jetzt in den Eval-Prompt jeder Iteration
   ein – der Loop plant vorsichtiger, statt erst am eigenen Scheitern zu erkennen, dass das Team
   gerade häufig scheitert.
4. **Kein Mittelweg zwischen Vorschlag ignorieren und globalem Auto-Tuning-Schalter**: neuer
   CLI-Befehl `/apply-tuning <agent_id>` (`core/optimization_advisor.py.apply_single_suggestion()`)
   übernimmt GEZIELT genau einen Modell-Vorschlag, unabhängig von `ENABLE_AUTO_MODEL_TUNING` –
   dafür markiert ein neues `manual`-Feld in `memory/auto_tuned_models.json`, dass
   `config.get_model_for_agent()` diesen Eintrag auch bei deaktiviertem globalem Schalter
   anwendet (automatisch geschriebene Einträge bleiben wie bisher daran gebunden).
5. **Wiederkehrende Lektionen-Kategorien am selben Projekt wurden nie ausgewertet**: neue
   `RecurringLessonCategory`-Auswertung in `analyze()` meldet, wenn dieselbe
   `team_lessons.jsonl`-Kategorie (z.B. `unresolved_governance_critical`) 3+ mal am selben
   Projekt auftritt – ein Hinweis auf eine Ursache, die der reguläre Fix-/Governance-Loop dort
   nicht dauerhaft behebt.

24 neue/erweiterte Tests (`tests/test_goal_loop.py`, `tests/test_optimization_advisor.py`,
`tests/test_cli_optimize_command.py`); volle Test-Suite (1243 Tests) grün, `ruff check` clean.

**Zwei echte Bugs bei der Verifikation gefunden und behoben:**
- Punkt 2 machte `record_suggestions_as_lessons()` unbedingt bei JEDEM `Orchestrator.process()`-
  Lauf scharf – Dutzende bestehender Tests lassen `process()` ohne Mock von
  `optimization_advisor` durchlaufen und schrieben dadurch einen echten, aus der tatsächlichen
  `memory/run_history.json` gelesenen Befund in die VERSIONIERTE `memory/team_lessons.jsonl`.
  Neue `tests/conftest.py` patcht `record_suggestions_as_lessons` zentral als No-Op für die
  gesamte Testsuite (reine Testisolation, kein Produktionsverhalten geändert).
- `tests/test_dashboard_concurrency.py.test_independent_orchestrator_instances_dont_mix_
  conversation_history` verglich `id()` zweier `ConversationHistory`-Objekte, ohne beide
  gleichzeitig am Leben zu halten – nach GC des ersten Objekts konnte CPython dessen Adresse
  für das zweite wiederverwenden, was den Test einmal real (abhängig von Timing/Testreihenfolge)
  fälschlich fehlschlagen ließ. Sammelt jetzt die Objekte selbst statt ihrer `id()` und
  vergleicht mit `assertIsNot()` – unabhängig vom GC-Timing korrekt.

---

## 🛠️ CI-Fehlschläge auf GitHub Actions behoben (Groq-Fallback-Tests & Workspace-Checks)

Realer Fund bei GitHub Actions PR-Checks (#35): die CI schlug mit 3 fehlerhaften Jobs fehl:
- `tests/test_llm_routing.py`: Tests für Fallback auf Groq mockten zwar `create_for_model`, aber nicht `GROQ_API_KEY`. Durch die kürzlich eingeführte `_provider_available()`-Prüfung sortierte der Client Groq in Umgebungen ohne Secrets (GitHub Actions CI-Runner) vorab aus. Mit `@patch("core.llm_factory.GROQ_API_KEY", "gsk_dummy_test_key")` laufen die Tests nun unabhängig von lokalen `.env`-Keys stabil in CI.
- `Workspace-Python-Check`: Ungenutzte Imports in `cloudvault` (`HTTPException`, `Depends`, `pytest`), ungenutzte Zuweisung `as websocket` in `omnichat` und fehlender `TestClient`-Import in `taskpulse` bereinigt (`ruff check --isolated --select F,E9` clean).
- `Workspace-TypeScript-Check`: Escapte Quotes `\"` in `omnichat/ChatWindow.tsx` korrigiert, `incidentpilot/vite.config.ts` typisiert und JSX-haltige Hooks `useWebSocket.ts`/`useWebSocket.test.ts` sauber auf `.tsx` umbenannt (`tsc --noEmit` clean).

---

## 🚦 `/tokens` zeigt jetzt Agent→Modell-Zuordnung & Wanduhr-ETA erschöpfter Modelle

Nutzeranfrage: eine Übersicht des Token-Status pro AGENT und Modell – welche Modelle gerade
verfügbar sind, welche das Kontingent aufgebraucht haben und WANN sie wieder verfügbar sind.
Der bisherige `/tokens`-Report (`core/quota_estimator.py`) zeigte Verbrauch nur pro Provider/
Modell, mit einem binären "🚨 Cooldown / Limit"-Badge ohne Zeitangabe – und keinen Bezug
dazu, welche der 38 Agenten-Rollen (`config.AGENT_MODELS`) davon überhaupt betroffen sind.

- `core/token_guard.py.get_exhausted_details()`: neue Methode, die für jedes aktuell
  erschöpfte Modell Grund, verbleibende Sekunden UND einen für Menschen lesbaren
  Wanduhr-Zeitpunkt (`HH:MM:SS`) liefert, ab dem es voraussichtlich wieder verfügbar ist –
  der interne Cooldown-Zähler läuft über `time.monotonic()` (nicht direkt mit einer Uhrzeit
  vergleichbar).
- `core/quota_estimator.py.get_agent_availability()`: ordnet jeden konfigurierten Agenten
  seinem aktuellen Modell (inkl. Fachbereichs-/Env-Overrides über `get_model_for_agent()`)
  und dessen Live-Verfügbarkeit zu.
- `format_markdown_table()` (angezeigt über `/tokens`) ergänzt zwei neue Abschnitte: eine
  Tabelle erschöpfter Modelle mit Grund + ETA + verbleibender Zeit, und eine
  Agent→Modell→Status-Tabelle (🟢 Verfügbar / 🚨 Cooldown bis HH:MM:SS Uhr).
- 3 neue Tests in `tests/test_quota_estimator.py`.

---

## ⚡ Fallback-Kette überspringt Provider ohne konfigurierten API-Key statt sie erfolglos zu versuchen

Wiederkehrender Fund aus mehreren echten Läufen (`ZWISCHENSTAND_KI_TEAM_PROJEKT.md`): `MODEL_
FALLBACKS` listet `claude-sonnet-5`/`claude-opus-5`/`claude-haiku-4-5` als ERSTEN Fallback-
Kandidaten für jede Gemini-Stufe – in Setups ohne `ANTHROPIC_API_KEY` scheiterte dieser Hop
jedes Mal mit `Claude innerhalb einer Fallback-Kette nicht verfügbar (kein ANTHROPIC_API_KEY)`,
bevor die Kette beim tatsächlich funktionierenden nächsten Kandidaten (kleinere Gemini-Stufe
oder Groq) ankam. Der Lauf scheiterte dadurch nicht final, aber jeder betroffene Agenten-Aufruf
verschwendete einen kompletten Hop (Client instanziieren, Anfrage starten, Fehler fangen) UND
erzeugte im Report eine irreführende ❌-Zeile, die wie ein echter Ausfall aussah statt wie eine
von vornherein bekannte Konfigurationslücke.

- `core/llm_factory.py._provider_available()`: neue, zentrale Prüfung, ob für einen
  Fallback-Kandidaten überhaupt ein API-Key konfiguriert ist (Claude → `ANTHROPIC_API_KEY`,
  Groq → `GROQ_API_KEY`, DeepSeek/OpenRouter/HuggingFace analog). Beide `models_to_try`-
  Konstruktionen (`generate_with_tools()` und `_call_with_retry_and_usage()`, inkl. der
  Cooldown-Wartelogik bei komplett erschöpfter Kette) filtern Kandidaten ohne Key jetzt VOR
  dem Versuch heraus, statt sie zu versuchen und den Fehler abzufangen.
- Neuer Test in `tests/test_llm_routing.py`
  (`test_claude_candidate_is_skipped_entirely_without_anthropic_api_key`): stellt sicher, dass
  `LLMFactory.create_for_model()` für Claude ohne `ANTHROPIC_API_KEY` gar nicht erst
  aufgerufen wird und die Kette direkt zur nächsten Gemini-Stufe springt.

---

## 🎨 Automatischer Safe-Fix für Lint-Funde statt liegenbleibender Warnungen

Zweiter Fund derselben cloudvault-Bestandsaufnahme: 13 ruff-Lint-Funde standen im
Verifikations-Protokoll ("⚠️ ruff: 13 Lint-Fund(e)"), wurden aber nie behoben – Lint ist
bewusst rein informativ (kein Blocker wie ein Testfehler, siehe `LintReport`-Docstring), aber
bisher war auch niemand je beauftragt, sie zu FIXEN, selbst wenn es triviale, syntaktisch
zweifelsfreie Autofixes gewesen wären (unsortierte/ungenutzte Importe, veraltete
Typannotationen, …).

- `core/verifier/lint.py._lint_python()` führt vor dem eigentlichen Check-Lauf jetzt
  `ruff check --fix` aus – NUR sichere Autofixes, bewusst OHNE `--unsafe-fixes` (das kann
  Verhalten ändern). Dieselbe Idee wie `black`/`prettier` im Pre-Commit-Hook eines echten
  Teams: trivialer Aufräumschritt ohne Agenten-Auftrag, bevor überhaupt berichtet wird.
  Opt-out über `ENABLE_AUTO_LINT_FIX=false` (Standard: an).
- 2 neue Tests in `tests/test_verifier_lint.py` (Fix-Aufruf vor Check-Aufruf, Opt-out-Flag).

---

## 🧩 Vollständigkeits-Check: "Tests grün" ≠ "Feature fertig" (cloudvault-Bestandsaufnahme)

Analyse des zuletzt generierten Projekts (`workspace/cloudvault`, sichere File-Sharing-
Plattform) zeigte einen Lauf, der als "✅ Vollständig verifiziert & einsatzbereit" markiert
wurde (`verification_ok: true`), obwohl:
- der Upload-Endpunkt nur den Kommentar `# Hier würde die AES-256-GCM Verschlüsselung ... und
  S3-Speicherung erfolgen` enthielt statt echter Verschlüsselung – die Tests prüften denselben
  Stub, den der Code tatsächlich lieferte, also bestanden sie trivial;
- das README `pip install -r requirements.txt` vorschrieb, obwohl diese Datei nie erzeugt wurde;
- 13 ruff-Lint-Funde im Protokoll standen, aber nie behoben wurden.

Keiner der bisherigen Checks (Testsuite, Lint, SAST, Coverage, Runtime-Smoke) erkennt einen
absichtlich unfertig gelassenen Codepfad, nur einen tatsächlich FALSCHEN – "Tests grün" wurde
bisher mit "Anforderung erfüllt" gleichgesetzt.

- Neuer Check `core/verifier/completeness.py.check_completeness()`: durchsucht generierten
  Code nach Platzhalter-/Stub-Markern (deutsch/englisch: "Hier würde ... erfolgen",
  `NotImplementedError`, "placeholder implementation", …) und prüft, ob im README per
  Installationsbefehl referenzierte Dateien (`pip install -r X`, `psql -f X.sql`, …)
  tatsächlich existieren.
- Anders als Lint/SAST (rein informativ) blockiert ein Fund hier `verification_ok` wie ein
  echter Testfehler – ein Stub-Kommentar ist eine nicht erfüllte fachliche Anforderung, keine
  Stil-Frage. `agents/orchestrator/verification.py` löst bei einem Fund dieselbe gezielte
  Fix-Schleife aus wie bei einem echten Testfehler (Owner per Dateipfad ermittelt, Auftrag "die
  Funktionalität WIRKLICH implementieren, nicht nur den Kommentar entfernen").
  Opt-out über `ENABLE_COMPLETENESS_CHECK=false` (Standard: an).
- `agents/security_agent.py`: der Systemprompt weist den Security-Agenten jetzt explizit an,
  einen Sicherheits-Stub (simulierte Verschlüsselung, ein Auth-Check, der immer `True`
  zurückgibt, …) immer als **Kritisch** einzustufen statt als Hinweis – ein solcher Stub sieht
  in Reports wie ein erledigtes Feature aus, bietet aber keinerlei Schutz.
- 7 neue Tests in `tests/test_verifier_completeness.py`.

---

## 🩹 Echter Praxistest des Ziel-Loops deckt Kosten-Historie-Bug auf: `KeyError('cache_read_tokens')`

Erster echter Live-Lauf von `/goal` (echte LLM-Aufrufe, kein Mock) nach der Kill-Switch-Runde:
Ziel wurde korrekt erreicht und verifiziert, aber jeder Lauf zeigte still
`⚠️ Kosten-Historie (record_run_usage) konnte nicht aktualisiert werden: 'cache_read_tokens'`.
Ein früherer Kommentar hatte das als "vermutlich eine Versions-Eigenheit der
google-genai/anthropic-SDK-Antwortobjekte" abgetan – tatsächlich ein simples,
reproduzierbares Schema-Migrations-Loch, das JEDEN echten Lauf seit Einführung von
`cache_read_tokens`/`cache_write_tokens` betraf (bestätigt: alle drei Modelle in der echten
`memory/cost_history.json` fehlten beide Spalten).

- `memory/cost_history.py.record_run_usage()`: `totals.setdefault(model_name, ...)` füllt
  Standardwerte nur bei einem komplett NEUEN Modell-Eintrag – ein bereits vorhandener
  Eintrag aus der Zeit VOR diesen beiden Spalten hatte sie schlicht nicht, `entry[key] += ...`
  scheiterte dann mit `KeyError`. `entry.setdefault(key, 0)` backfillt fehlende Schlüssel
  jetzt auch an bestehenden Einträgen – selbstheilend ab dem nächsten Lauf.
- `agents/orchestrator/budget.py._model_usage_deltas()`: ein zweiter, unabhängiger Bug –
  `cache_read_tokens`/`cache_write_tokens` fehlten im berechneten Delta-Dict komplett, das
  Feld blieb dadurch strukturell IMMER bei 0, selbst wenn `core/token_guard.py` echte
  Cache-Treffer korrekt mitgezählt hatte.
- 3 neue Tests (Backfill eines Legacy-Eintrags ohne Cache-Spalten, echte Delta-Berechnung mit
  Cache-Werten). Volle Suite (943 Tests) grün, ruff sauber.

---

## 🩹 Leerer Konsolidierungs-Block ließ Teamleiter unnötig Rückfragen stellen

Realer Fund aus einer echten, offen gebliebenen Rückfrage eines `governance_lead`-
Konsolidierungslaufs (PR #21, "Ergebnisse wurden im Prompt nicht mitgeliefert"):
`agents/orchestrator/reporting.py._format_results_for_review()` nahm bisher nur Ergebnisse
mit `success=True and content` in den Ergebnis-Block auf, den ein Fachbereichsleiter zur
Konsolidierung bekommt. Schlugen ALLE Mitglieder einer Phase fehl, oder lieferte ein
Mitglied `success=True` mit leerem `content` (z.B. ein reiner Tool-Aufruf ohne
abschließenden Text – typisch für `project_cleaner`), war der Block komplett LEER. Der
Teamleiter bekam wörtlich "... haben folgende Ergebnisse geliefert:\n\n\nPrüfe sie ..." und
stellte folgerichtig eine Rückfrage, statt einen Bericht zu schreiben.

- Fehlgeschlagene Mitglieder werden jetzt mit ihrem Fehlertext aufgeführt (statt zu
  verschwinden), erfolgreiche-aber-leere Mitglieder mit einem expliziten Hinweis – der
  Block ist nie mehr komplett leer.
- 4 neue, isolierte Tests (`tests/test_department_consolidation_review_formatting.py`),
  inkl. exakter Reproduktion des gemeldeten Szenarios (alle Mitglieder scheitern/liefern
  nichts). Volle Suite (941 Tests) grün, ruff sauber.

---

## 🏷️ Echtes Release-Management fürs Framework selbst: `/release`

Realer Fund bei einer Bestandsaufnahme des eigenen Teams: `CHANGELOG.md` wird bei jedem PR
manuell um einen neuen Eintrag ergänzt, aber es gab über die gesamte Projekthistorie keine
einzige Versionsnummer, keinen Git-Tag, keine GitHub-Release – das README zeigte "v4.3" nur
als hart einprogrammierte Zeichenkette ohne jeden Bezug zu echten Commits oder Tags.

- `core/framework_release.py` (neu): leitet den nächsten SemVer-Bump aus den ECHTEN
  Commit-Messages seit dem letzten Tag ab (nutzt die bereits etablierte
  feat:/fix:/BREAKING-CHANGE-Konvention). Release-Notes sind die echten kategorisierten
  Commit-Subjects, kein LLM-Text. Bewusst **nicht** `core/release_manager.py` genannt – das
  benennt bereits ein anderes, unabhängiges Feature (automatisches Release-Tagging
  generierter `workspace/`-PROJEKTE beim Mergen ihres Tickets, siehe
  [📋 Backlog/Kanban](README.md#backlog-kanban)); beide Module lösen ähnlich klingende, aber
  fachlich getrennte Aufgaben und sollen nicht kollidieren.
- `interface/cli.py`: neuer Befehl `/release` mit Vorschau + Bestätigungs-Gate.
- 25 neue Tests, u.a. echte Tag-/Log-Operationen gegen ein lokales Git-Repo mit Bare-Remote.

Volle Suite grün, ruff sauber.

---

## 🏷️ TypeScript-CI-Check, GitHub-Labels für Verifikationsstatus & Eskalation bei Wiederholungsfehlern

Direkte Fortsetzung der drei Vorschläge aus dem vorherigen Eintrag unten, alle vollständig
umgesetzt:

- **`workspace-typescript-check` (neuer CI-Job):** Pendant zu `workspace-python-check` für
  `.ts`/`.tsx`-Dateien – `workspace-frontend-tests` läuft nur, wenn ein Projekt bereits ein
  `test`-Skript in `package.json` hat; ein generiertes `.tsx`-Fragment ganz ohne
  `package.json` (real beobachtet: `TaskList.tsx`/`useTaskWebSocket.ts`) durchlief bisher
  keinen einzigen CI-Check. `tsc --noEmit` über alle per `git ls-files` gefundenen
  `workspace/*.ts(x)`-Dateien, TS2307 ("Cannot find module" – workspace/-Projekte werden
  bewusst ohne `node_modules` committet) wird gezielt ausgefiltert, jeder andere
  Diagnose-Code (Syntaxfehler, kaputtes JSX, falsch referenzierte Namen) lässt den Job
  fehlschlagen.
- **GitHub-Labels statt nur Titel-Präfix:** `agents/github_agent.py.label_pr()` legt
  `verification-failed`/`budget-aborted`/`needs-clarification` idempotent an und wendet sie
  auf den PR an – sichtbar in der PR-LISTE, nicht erst beim Öffnen des einzelnen PRs. Neues
  `Orchestrator.last_budget_aborted`, damit `interface/cli.py` diesen Grund unabhängig von
  `last_verification_ok` erkennen kann.
- **`core/project_status.count_consecutive_failed_runs()`:** Ab zwei aufeinanderfolgenden
  Läufen ohne bestandene Verifikation ersetzt eine deutlichere Warnung MIT konkreter
  Handlungsempfehlung die bisher rein informative Duplikat-Warnung – ein manueller
  Abbruch (`cancelled=True`) zählt bewusst nicht als Fehlschlag und unterbricht die Zählung.

---

## 🩹 CI-Lücke bei generiertem `workspace/`-Code + Verifikationsstatus in Duplikat-Warnung

Retrospektive zu vier separaten, aufeinanderfolgenden Läufen an praktisch derselben
Aufgabe (`fastapi-task-mgmt`, `fastapi_task_websocket`, `kanban_board`,
`kanban_task_manager`), die alle vier mit `verification_ok=false` endeten und trotzdem
in einem gemeinsamen Commit mit erfolgsklingender Nachricht zusammengeführt wurden.

- **CI prüfte `workspace/`-Python-Code bisher gar nicht:** `ruff.toml` schließt
  `workspace/` bewusst aus (eigener Stil generierter Projekte), der Syntax-Check im
  `test`-Job filtert `workspace/` ebenfalls komplett heraus. Der interne Verifier
  (`core/verifier.py._lint_python`, läuft während eines echten Agentenlaufs) hatte reale
  Bugs korrekt erkannt (u.a. `json.loads()` ohne Import, `app`/`Depends` ohne Import) –
  dieses Ergebnis wurde aber nie durch eine zweite, unabhängige CI-Prüfung nach dem Lauf
  abgesichert. Neuer Job `workspace-python-check`: `py_compile` +
  `ruff check --isolated --select F,E9` (umgeht den `ruff.toml`-Exclude bewusst) über
  alle `workspace/*.py`-Dateien. Alle 25 dadurch aufgedeckten Altfunde in bereits
  gemergtem Workspace-Code sind mitbehoben.
- **Duplikat-Warnung ohne Verifikationsstatus:** Die Warnung vor dem Anlegen eines neuen
  Projekts (siehe [PR-Workflow](README.md#pr-workflow)) zeigte bisher nur Namen bereits vorhandener Projekte, nicht deren zuletzt
  protokollierten Verifikationsstatus – ein fehlgeschlagener Vorversuch wirkte dadurch
  nicht dringlicher als ein sauber abgeschlossenes Projekt. Zeigt jetzt zusätzlich
  ✅/⚠️/🚫/⏹️ je Projekt an, weiterhin ohne Ähnlichkeits-Matching/Heuristik/LLM-Aufruf.

---

## ↩️ Echter Rollback-Workflow: `/rollback <PR-Nummer>`

Realer Fund bei einer Bestandsaufnahme des eigenen Teams: bricht ein gemergter PR `main`
(z.B. ein CI-Fehlschlag, der erst NACH dem Merge bemerkt wird), gab es keinerlei Mechanismus,
das rückgängig zu machen – nur der manuelle Weg direkt über GitHub. Ein echtes Team hat einen
bekannten, schnellen Rollback-Pfad.

- `agents/github_agent.py`: zwei neue Methoden – `get_merged_pr_info()` liest Merge-Commit-SHA
  und Titel eines PRs per `gh pr view` (lehnt nicht-gemergte PRs mit klarem Grund ab, statt
  einen falschen Erfolg vorzutäuschen); `revert_commit()` führt einen echten
  `git revert --no-edit` aus – ein Merge-Konflikt dabei ist kein Absturz, nur ein sauberer
  Fehlschlag.
- `interface/cli.py`: neuer Befehl `/rollback <PR-Nummer>` – legt einen eigenen Revert-Branch
  vom Hauptbranch an, revertiert den Merge-Commit darauf, pusht und öffnet einen ganz normalen
  Revert-Pull-Request. KEIN Direct-Commit auf den Hauptbranch, derselbe PR-Workflow (CI/Review)
  wie jede andere Änderung. Vorschau + Bestätigungs-Gate wie bei `/delete-project`.
- 10 neue Tests (`test_rollback_workflow.py`): `get_merged_pr_info()` gegen gemergte/offene/
  nicht gefundene PRs; `revert_commit()` gegen ein ECHTES lokales Git-Repo (inkl. eines echten
  Revert-Konflikts); der volle CLI-Ablauf (Branch→Revert→Push→PR), Abbruch bei fehlender
  Bestätigung, fehlendem `gh`, nicht-gemergtem PR und einem Revert-Konflikt (checkt dabei
  sauber zum ursprünglichen Branch zurück). Volle Suite grün, ruff sauber.

---

## 🎯 Autonomer Ziel-Loop, Runde 2: Rand- & Fehlerfälle, Ticket-Status, `pytest` ohne Pfadangabe

Zweite Prüfrunde am Ziel-Loop (`core/goal_loop.py`) nach der ersten Kill-Switch-Runde
darunter – diesmal auf Rand- und Fehlerfälle statt der Kernlogik, plus ein reales
Test-Tooling-Problem, das beim vollständigen Verifizieren der Suite auffiel:

- **Nutzerabbruch/Absturz landeten irreführend als "review" im Backlog:** `upsert_ticket()`
  setzte bei JEDEM nicht-erfolgreichen Ausgang denselben Status `"review"` – ein per Strg+C
  abgebrochener Loop sah damit im Board wie ein fertig zur Prüfung anstehender PR aus, obwohl
  nichts zu prüfen ist. Jetzt: `"cancelled"` bei Nutzerabbruch, `"blocked"` bei einer echten
  Exception, `"review"` nur noch beim tatsächlichen "Ziel nach max. Iterationen offen"-Fall.
- **Exceptions verschwanden in einer irreführenden Standardmeldung:** Warf
  `orchestrator.process()` mitten in einer Iteration eine Exception (z.B. komplett erschöpfte
  Provider-Kette), landete das zwar korrekt als Fehlschlag in `iterations_history`, der
  `final_message` des Abschlussberichts sagte aber trotzdem nur "Ziel nach maximalen
  Iterationen noch nicht vollständig abgeschlossen" – als wäre einfach das Budget an
  Iterationen ausgegangen. `final_message` nennt jetzt explizit Iteration und Fehlertext der
  Exception.
- **Kein Schutz vor leerem Ziel oder `max_iterations < 1`:** Ein leeres/nur-Whitespace-`goal`
  hätte einen sinnlosen Orchestrator-Lauf mit leerer Aufgabe gestartet (Tokenverbrauch ohne
  jeden Nutzen); `max_iterations=0` (oder negativ, z.B. durch einen Tippfehler in
  `/goal -1 ...`) ließ den Loop bisher still und ohne jede Rückmeldung zu einem kompletten
  No-Op werden. Beide Fälle werden jetzt VOR dem ersten Orchestrator-Aufruf abgefangen – ein
  leeres Ziel bricht sofort mit klarer Meldung ab, ein zu kleines `max_iterations` wird sichtbar
  auf 1 angehoben statt schweigend zu nichts zu führen.
- **`pytest`/`python -m pytest` ohne Pfadangabe crashte mit einem internen Capture-Fehler:**
  Realer Fund beim vollständigen Verifizieren dieser Änderungsrunde – ohne `testpaths` sammelte
  ein blankes `pytest` im Projekt-Root auch jeden Test aus generierten
  `workspace/<projekt>/tests/`-Verzeichnissen ein, deren Abhängigkeiten hier nicht installiert
  sind (`ModuleNotFoundError: No module named 'app'` etc.) – genug betroffene Module ließen
  pytest sogar mit `ValueError: I/O operation on closed file` beim Teardown abstürzen, statt nur
  die eigene, tatsächlich grüne Framework-Suite zu melden. Neues `pytest.ini` (`testpaths =
  tests`) behebt das: `pytest` ohne jede Pfadangabe läuft jetzt zuverlässig nur gegen die 888
  Tests der eigenen Suite.

5 neue Tests (leeres Ziel, `max_iterations`-Clamping, Exception-Reporting im Abschlussbericht);
volle Suite (888 Tests) grün, ruff sauber.

---

## 🎯 Autonomer Ziel-Loop (`core/goal_loop.py`): Kill-Switches gegen Endlosschleifen & echter Provider-Fallback

Neuer Baustein: der autonome Ziel-Loop (`/goal`, `python main.py --goal`) lässt das Team nicht
mehr nur einen einzelnen `Orchestrator.process()`-Durchlauf abarbeiten, sondern iteriert
selbstständig weiter – nach jeder Runde bewertet ein LLM-Judge (`GOAL_LOOP_EVAL_MODEL`) anhand
von Zwischenstand, Dateiliste und Verifikations-Status, ob das Ziel erreicht ist, und erzeugt
andernfalls automatisch den präzisen Folge-Prompt für die nächste Runde. Bei der Analyse des
Erstentwurfs (noch vor dem ersten Commit) fielen drei konkrete Lücken auf, die jetzt behoben
sind:

- **Echter Bug: `LLMFactory.create_llm` existiert gar nicht.** Der Bewertungsschritt rief eine
  nicht existierende Factory-Methode auf, die JEDES Mal eine `AttributeError` warf – durch das
  breite `except Exception` fiel die Bewertung dadurch bei jedem einzelnen Lauf sofort auf die
  simple Heuristik zurück, ohne dass das je sichtbar wurde (alle Tests mockten
  `_evaluate_and_synthesize_next_step` direkt und liefen daher am Bug vorbei). Zusätzlich wurde
  die bereits asynchrone `generate()`-Coroutine fälschlich über `asyncio.to_thread()`
  aufgerufen, was ein unawaited Coroutine-Objekt statt eines Strings zurückgegeben hätte.
  Ersetzt durch `LLMFactory.create_for_model(...)` + `await llm.generate(...)` – dieselbe
  zentrale Provider-Erkennung, die auch jeder Agent nutzt, inklusive der in
  `GeminiClient._call_with_retry_and_usage()` eingebauten `MODEL_FALLBACKS`-Kette (echter
  Cross-Provider-Fallback bei Erschöpfung/Fehler des primären Eval-Modells statt eines starren
  Single-Shot-Aufrufs).
- **Kein kumulatives Token-Budget über Iterationen hinweg:** `MAX_RUN_TOKENS` begrenzt nur
  EINEN einzelnen `orchestrator.process()`-Aufruf – ein Ziel-Loop mit mehreren Iterationen
  konnte dieses Budget bis zu `max_iterations`-mal hintereinander ausschöpfen, ohne dass der
  Loop selbst je abgebrochen wäre. Neues `GOAL_LOOP_MAX_TOTAL_TOKENS` (Standard `0` = aus)
  summiert den Tokenverbrauch aller Iterationen dieses Loops über `token_guard.get_summary()`
  und bricht den Loop ab, sobald das Budget erreicht ist – die bis dahin erarbeiteten
  Ergebnisse bleiben erhalten (Graceful Degradation statt Abbruch ohne Ergebnis).
- **Kein Stagnations-Abbruch:** Liefert die Verifikation zwei Iterationen in Folge exakt
  denselben Fehler, dreht sich der Loop erkennbar im Kreis (ein Bug, den das Team offenbar
  nicht selbst löst) – bisher liefen trotzdem alle `max_iterations` Runden durch und
  verbrannten dabei unnötig Tokens. Der Loop erkennt identische `failure_detail`-Werte
  aufeinanderfolgender Iterationen jetzt und bricht sofort mit klarer Begründung ab.

6 neue/erweiterte Tests (`tests/test_goal_loop.py`): Stagnations-Abbruch, kumulatives
Token-Budget (per gemocktem `token_guard.get_summary()`), plus die bestehenden 4 Tests für
Erfolg-bei-erster-Iteration, Mehrrunden-Recovery, Abschlussbericht-Formatierung und
kooperativen Abbruch – alle grün, ruff sauber.

---

## 🔍 Workspace-Audit: unvollständige Projekte & Nahezu-Duplikate erkennen

Realer Fund bei einer manuellen Bestandsaufnahme aller `workspace/`-Projekte: mehrere Läufe
wurden vom Orchestrator als abgeschlossen protokolliert, obwohl das Ergebnis erkennbar
unvollständig war. `workspace/api_health_monitor` importierte in `main.py` ein Objekt, das in
`checker.py` nur durch einen Platzhalterkommentar ("... beibehalten") ersetzt worden war –
der allererste Testlauf brach schon beim Import ab (jetzt gefixt). `workspace/api-health-monitor`
(Nahezu-Duplikat desselben Namens, nur mit Bindestrich statt Unterstrich) hatte gar keinen
Einstiegspunkt, `workspace/realtime_polling_platform` bestand nur aus zwei Modulen ohne
Tests/Manifest – beide liefen bisher unter dem harmlosen "keine Tests gefunden" durch.

- `core/verifier.py`: neue `ProjectVerifier._find_incomplete_project_reason()` erkennt zwei
  konkret beobachtete Muster als echten Fehlschlag statt als Skip: ein mehrteiliges
  Backend-Projekt mit `requirements.txt`/`pyproject.toml`, aber ohne jeden Einstiegspunkt
  (`main.py`/`app.py`/`manage.py`/…), sowie ein `tests/`-Ordner mit `conftest.py`, aber ohne
  eine einzige echte Testdatei. Ein einzelnes Skript ohne Manifest (der bereits bestehende
  legitime Fall) bleibt unverändert ein harmloser Skip.
- `agents/orchestrator.py`: zeigt diesen neuen Fall im Verifikations-Protokoll als ❌ statt als
  ⚠️ an. Zusätzlich neue `_find_near_duplicate_slug()`-Prüfung: warnt gezielt, wenn ein neuer
  `project_slug` sich von einem bereits vorhandenen Workspace-Projekt nur durch Schreibweise
  (`_`/`-`/Groß-Kleinschreibung) unterscheidet, statt nur generisch "bereits vorhanden: ..."
  aufzulisten.
- `agents/frontend_agent.py`, `mobile_agent.py`, `database_agent.py`: dieselbe Regel gegen
  "... (X beibehalten)"-Platzhalterkommentare in frisch generiertem Code wie beim
  `backend`-Agenten ergänzt – ein generisches LLM-Fehlerbild, nicht backend-spezifisch.
- `core/workspace_audit.py` (neu) + `python main.py --audit-workspace`: periodischer
  Poll-Zyklus (analog `core/dependency_watch.py`), der `ProjectVerifier.run_tests()` erneut
  gegen JEDES Workspace-Projekt ausführt – unabhängig von aktiver Entwicklung – und bei einem
  echten Fehlschlag ein Backlog-Ticket öffnet. Schließt die Lücke, dass ein Projekt, das seit
  seinem letzten Lauf nie wieder angefasst wurde, sonst nie von selbst erneut geprüft würde.
- 15 neue Tests (`core/verifier.py`, `agents/orchestrator.py`, `core/workspace_audit.py`);
  volle Suite (855 Tests) grün, ruff sauber.

---

## ⌨️ Mehrzeilige Eingabe im interaktiven CLI-Prompt

Realer Fund (Nutzeranfrage): `interface/cli.py._main_loop()` las die Nutzereingabe über
`console.input()` (dünner Wrapper um Pythons `input()`) - das liest immer nur bis zum ersten
Zeilenumbruch. Eine mehrzeilige Aufgabenbeschreibung, oder ein ins Terminal eingefügter
mehrzeiliger Text, wurde dadurch NICHT als eine Eingabe erkannt, sondern jede Zeile einzeln
als eigener, meist unsinniger Prompt verarbeitet. Neue Methode
`CLIInterface._read_user_input()`: endet eine Zeile auf ein einzelnes `\` (dieselbe
Fortsetzungs-Konvention wie in der Shell/in Python selbst), wird die nächste Zeile
angehängt statt die Eingabe abzuschließen. Eine normale, einzeilige Aufgabe bleibt dadurch
unverändert genauso schnell wie bisher (ein `console.input()`-Aufruf, kein Overhead).

---

## 🧪 CI-Testrunner von `unittest discover` auf `pytest` umgestellt

Realer Fund bei der Prüfung der `core/llm_factory.py`-Fallback-Ketten: der CI-„Tests"-Job
(`.github/workflows/ci.yml`) lief bisher über `python -m unittest discover`. Dessen
`TestLoader` sammelt ausschließlich `unittest.TestCase`-Subklassen ein - drei bereits
existierende, reine Pytest-Fixture-/`@pytest.mark.anyio`-Testdateien
(`test_dashboard_sse.py`, `test_mcp_server_extended.py`, `test_prompt_caching.py`, keine
`TestCase`-Klassen) wurden dadurch zwar importiert, ihre Tests aber **nie tatsächlich
ausgeführt** - ein grüner CI-Lauf bedeutete für diese drei Dateien seit ihrer Einführung nur
"importierbar", nicht "getestet". `python -m pytest tests/` sammelt beide Testarten
gleichwertig ein und läuft unittest.TestCase-basierte Tests unverändert mit; `tests/` bleibt
bewusst als Argument (nicht `.`) nötig, damit pytest über die vorhandene
`tests/__init__.py`-Package-Erkennung dieselbe `RUN_HISTORY_FILE`-Umleitung wie zuvor
`unittest discover -t .` sicherstellt.

`pytest>=8.0.0,<9.0.0` zu `requirements.txt` ergänzt (vorher nur transitiv über
`pytest-cov` in `requirements-dev.txt` vorhanden) - der CI-„Tests"-Job installiert bewusst nur
`requirements.txt`, nicht `requirements-dev.txt`.

---

## 🤖 Vier Schritte Richtung "echtes Team": Selbstgesteuertes Backlog, Mid-Task-Eskalation, Epics & Produktions-Monitoring

Nutzerwunsch: das Team soll "noch eigenständiger, autonomer, voll funktionsfähiger und
professioneller genau wie ein echtes Softwareentwickler-Team aus Menschen arbeiten". Vier
konkrete, verifizierte Lücken gegenüber echtem Team-Verhalten geschlossen:

- **`core/backlog_worker.py`** (`python main.py --work-backlog`): ein "todo"-Ticket aus
  `/backlog-add` wurde laut eigenem CLI-Hinweistext bisher NIE automatisch angegangen ("Führt
  selbst nichts aus... wird erst zu echter Arbeit, wenn du die Aufgabe regulär in den Chat
  schreibst") - core/issue_watcher.py reagiert nur auf NEU gelabelte GitHub-Issues, nicht auf
  bereits wartende Backlog-Punkte. Greift jetzt eigenständig das höchstpriorisierte,
  abhängigkeitsfreie Ticket auf, über denselben PR-Workflow/dasselbe Sicherheitsmodell wie
  der Issue-Watcher. Bewusst NICHT in `.github/workflows/ai-team-scheduler.yml` verdrahtet
  (eigene `scripts/run_backlog_worker.ps1` für den lokalen Taskplaner) - `memory/backlog.json`
  ist gitignored, ein GitHub-Actions-Runner mit frischem Checkout hätte hier immer leeren
  Zustand und würde scheinbar erfolgreich, aber wirkungslos durchlaufen.
- **`core/backlog_store.py`**: Tickets tragen jetzt `epic`/`depends_on` -
  `is_ticket_ready()` prüft echte Abhängigkeiten (unbekannte IDs gelten bewusst als NICHT
  erfüllt, nie stillschweigend ignoriert), `/backlog` markiert blockierte Tickets sichtbar
  (`🔗 ... wartet auf: ...`). Ein größeres Vorhaben lässt sich jetzt als zusammenhängende,
  sinnvoll sortierte Ticket-Kette planen statt jede Anfrage isoliert zu bearbeiten.
- **`ask_human_for_clarification`** (`core/agent_toolbox.py`): Rückfragen passierten bisher
  nur VOR dem Start einer Aufgabe (core/task_manager.py needs_clarification) - sobald Agenten
  liefen, gab es kein Mittel mehr, eine echte, entscheidende Unklarheit zu melden, nur
  Weiterarbeiten mit einer geratenen Annahme. Jeder toolbox-fähige Agent kann jetzt mitten in
  der Aufgabe eskalieren; sichtbar im Ergebnis, im Git-Push-Gate der CLI, und als eigener,
  als Draft markierter PR-Zustand in `--check-issues`/`--work-backlog` (core/message_bus.py.
  AgentResult.needs_human_input/clarification_questions, agents/orchestrator.py.
  last_needs_human_input).
- **`core/production_monitor.py`** (`python main.py --check-deployments`) + **`/deploy-cloud`**
  (interface/cli.py): realer Fund beim Umsetzen - `core/cloud_deployment.py` (Fly.io/Vercel/
  Render/Railway) existierte bereits vollständig fertig implementiert, war aber NIRGENDS in
  CLI/Dashboard verdrahtet, obwohl das README das Gegenteil behauptete. Jetzt per
  `/deploy-cloud <provider> [projekt] [--real]` erreichbar (Standard: sicherer Dry-Run).
  Dabei zwei weitere echte Bugs in `core/cloud_deployment.py.deploy()` gefunden und behoben:
  ein "echter" Deploy-Versuch für render/railway behauptete UNGEPRÜFT Erfolg, ohne je einen
  Deploy-Befehl auszuführen (beide haben kein lokales CLI-Deploy-Kommando - jetzt ehrlich als
  "nicht möglich" statt fälschlich "erfolgreich" gemeldet); ein "echter" Vercel-Deploy prüfte
  nur, ob die CLI installiert ist, rief sie aber NIE tatsächlich auf (jetzt ein echter
  `vercel --prod`-Aufruf). Ein erfolgreicher ECHTER Deploy wird über `core/deployment_status.py`
  persistiert (gitignored, reiner Laufzeit-Zustand) und von `--check-deployments` periodisch
  per echtem HTTP-Request auf Erreichbarkeit geprüft - ein Ausfall eröffnet automatisch ein
  hochpriorisiertes Backlog-Ticket + externe Benachrichtigung, eine Wiederherstellung schließt
  es automatisch. Dieselbe lokale-Zustand-Begründung wie beim Backlog-Worker: eigene
  `scripts/run_production_monitor.ps1`, bewusst nicht im GitHub-Actions-Scheduler.

51 neue/angepasste Tests (815 gesamt), `ruff check .` sauber.

---

## 🕳️ Fünf zusammenhängende Verifikations-Lücken am Pong-Projekt (Frontend "geprüft und ok", aber funktional tot)

Realer Fund: das generierte Pong-Spiel (`workspace/pong-game`) hatte einen grünen PR (#20,
CI grün, Backlog-Status "review") und trug trotzdem KEINEN einzigen funktionierenden
Bootstrap-/Render-Code (`game.js` besaß keine `draw()`-Methode, keinen Game-Loop, `index.html`
lud das ES-Modul ohne `type="module"` - die Seite crashte beim Öffnen sofort mit einem
JS-Syntaxfehler). `npm test` schlug sogar komplett fehl (0 von 2 Tests liefen je), bevor
dieser Fund überhaupt gemacht wurde. Fünf unabhängige, sich gegenseitig verstärkende Lücken
im Verifikations-Pfad ließen das durchrutschen:

- **`interface/cli.py._ask_for_git_push()`**: der PR-Body enthielt bisher NIE den
  Verifikationsstatus - nur das Terminal warnte (`verification_note`), aber genau das sieht
  ein GitHub-Reviewer nie. Ein PR, dessen echte Testsuite nicht bestätigt bestanden hat,
  bekommt jetzt einen `⚠️ [UNVERIFIZIERT]`-Titel-Präfix, das vollständige
  Verifikations-Protokoll im Body (`Orchestrator.last_verification_summary`, neu) und wird per
  `github_agent.create_pull_request(draft=True)` als Draft angelegt statt als normaler,
  mergebarer PR.
- **`requirements.txt`**: Playwright war nur Dev-Abhängigkeit - ohne installiertes Playwright
  fällt `core/browser_verifier.py` STILL auf eine rein statische Datei-Existenz-Prüfung
  zurück, die kein JavaScript ausführt. Jetzt Laufzeit-Abhängigkeit; ein `static_dom`-Pass
  wird im Verifikations-Protokoll außerdem explizit als "nur eingeschränkt geprüft" markiert
  statt optisch identisch zu einem echten Playwright-Lauf zu erscheinen.
- **`core/browser_verifier.py`**: neue Blank-Canvas-Heuristik (`blank_canvases`) - ein
  `<canvas>`-Element, dessen Pixelinhalt nach dem Laden byte-identisch mit einem frisch
  erzeugten LEEREN Canvas ist, wurde nachweislich nie gezeichnet (kein Fehler wird dabei
  geworfen, es fehlt schlicht jeder Render-Aufruf) - genau das Pong-Muster.
- **`agents/orchestrator.py._run_verification_loop()`**: ein Fehlschlag des Frontend/UI-Checks
  (Konsolenfehler, fehlendes Asset, jetzt auch Blank-Canvas) war bisher rein informativ und
  beeinflusste `verification_ok` NICHT - für ein Frontend-Projekt ist dieser Check aber oft die
  einzige Instanz, die überhaupt echten Browser-Code ausführt. Zählt jetzt wie ein
  fehlgeschlagener Lastentest/Runtime-Smoke-Test als echte Anforderungsverletzung.
- **`core/verifier.py._parse_node_failures()`**: zwei Bugs zugleich. (1) `message` blieb für
  per "FAIL <datei>"-Header erkannte Jest-Fehlschläge IMMER `""` - der Fix-Agent im
  Verifikations-Fix-Loop bekam nie die tatsächliche Fehlermeldung zu sehen. (2) ein
  Jest-Konfigurationsfehler ("Cannot use import statement outside a module" u.ä.) wurde
  ausschließlich der Testdatei zugeschrieben und landete deshalb beim `tester`-Agenten, obwohl
  die Ursache in der Node-Projekt-Konfiguration liegt - `package.json` wird bei erkannter
  Fehlersignatur jetzt zusätzlich implizierter Owner.
- **`.github/workflows/ci.yml`**: neuer Job `workspace-frontend-tests` führt echtes
  `npm test` in jedem `workspace/*`-Projekt mit Test-Skript aus - CI testete bisher
  AUSSCHLIESSLICH den Python-Code des Orchestrators selbst (`ruff.toml` schließt `workspace/`
  bewusst aus), ein grüner PR-Check bedeutete nie "das generierte Frontend funktioniert".

`workspace/pong-game` selbst wurde im selben Zug repariert (`draw()`/Game-Loop/Event-Handling
ergänzt, `type="module"`, Jest-ESM-Konfiguration) - sonst hätte der neue CI-Job und der neue
Blank-Canvas-Check sofort auf diesem PR angeschlagen.

---

## 🔧 Datenbasierte Selbstoptimierungs-Vorschläge über mehrere Läufe hinweg

Nutzerwunsch: "Loops einbauen, damit das Team eigenständiger arbeiten und sich weiter
optimieren kann". Nach Rückfrage (drei mögliche Lesarten: eingebauter Daemon-Modus im
Framework, Claude-Code-`/schedule` für wiederkehrende Läufe, oder eine tiefere
Selbstoptimierungs-Schleife) fiel die Wahl bewusst auf Letzteres – als reiner VORSCHLAG, keine
automatische Änderung, dieselbe Linie wie die bereits weiter unten dokumentierte Entscheidung,
Phasenreihenfolge-Änderungen nicht automatisch, sondern nur nach Rücksprache umzusetzen.

- **`memory/run_history.py.get_agent_model_performance()`**: `agent_results`-Einträge trugen
  bisher `agent_id`/`success`/`total_tokens`, aber NICHT, welches Modell tatsächlich genutzt
  wurde (`AgentResult.model_used` existierte bereits, wurde aber nie mit aufgezeichnet) – es
  gab dadurch keine Möglichkeit zu sehen, ob die aktuell konfigurierte Modellzuweisung eines
  Agenten (z. B. nach einem manuellen `.env`-Wechsel) empirisch tatsächlich die beste ist.
  Gruppiert Erfolgsquote/Tokenverbrauch je (Agent, Modell)-Kombination; ältere Historien-
  Einträge ohne `model_used` landen unter "unbekannt" statt zu crashen.
- **`core/optimization_advisor.py`** (`analyze()`, `format_report_for_humans()`): rein
  deterministische Auswertung (keine LLM-Interpretation nötig – Erfolgsquoten sind bereits
  harte Zahlen) erkennt zwei Muster: (1) ein Agent lief bereits mit mehreren Modellen in der
  Historie, eines davon deutlich besser (Mindest-Stichprobengröße `MIN_SAMPLE_SIZE=5` je
  Modell UND Mindest-Lücke `MIN_SUCCESS_RATE_GAP=15` Prozentpunkte, sonst gilt es als
  Rauschen); (2) ein Agent scheitert auffällig oft gegenüber dem Team-Durchschnitt. Beides
  bewusst NUR als Empfehlung formatiert, ändert `config.py` nie automatisch.
- Erscheint automatisch als eigener Abschnitt im Abschlussbericht JEDES Laufs (`agents/
  orchestrator.py`), aber NUR wenn ein aussagekräftiger Befund vorliegt – kein unnötiger
  Abschnitt für die Mehrheit der Läufe. Zusätzlich jederzeit ohne neuen Lauf über den neuen
  CLI-Befehl `/optimize` abrufbar.

23 neue Tests (`test_optimization_advisor.py`, `test_optimization_advisor_integration.py`,
`test_cli_optimize_command.py`, Erweiterung von `test_run_history.py`). Volle Suite
(752 Tests) grün, ruff sauber.

---

## ♿ Echter axe-core-Accessibility-Scan statt LLM-Freitext-Checkliste

Letzter offener Punkt aus der Bestandsaufnahme gegen ein professionelles Team: Nach SAST
(`bandit`) und Lizenz-Audit (`pip-licenses`) blieb der `accessibility`-Agent als dritter Agent
übrig, dessen Report reine LLM-Einschätzung ohne echten Fundort war – ausgerechnet, obwohl
`core/browser_verifier.py` bereits per Playwright echt gerenderte Seiten für den UI-Check
zur Verfügung hatte.

- **`core/browser_verifier.py.verify_accessibility()`** (`AccessibilityReport`,
  `AccessibilityViolation`): führt `axe-core-python` (WCAG 2.x, dieselbe Engine, die auch
  `@axe-core/playwright`, `cypress-axe`, `jest-axe` nutzen) gegen den ersten gefundenen
  HTML-Einstiegspunkt aus – eigener, unabhängiger Playwright-Lauf statt Wiederverwendung des
  bestehenden UI-Checks, damit ein Fehlschlag hier den Konsolen-/Asset-Check nicht beeinflusst
  und umgekehrt. `core/verifier.py.check_accessibility()` delegiert dünn daran, exakt wie
  `check_browser_ui()`. Braucht zwingend eine echt gerenderte Seite (Playwright UND
  `axe-core-python`) – ohne beides `attempted=False`, NIEMALS fälschlich "keine Verstöße".
  Rein informativ im Abschlussbericht wie der bestehende Frontend/UI-Check direkt darüber,
  beeinflusst `verification_ok` nicht.
- Parsing bewusst defensiv (`.get()`-Ketten statt direkter Zugriffe) gegen axe-core-Versions-
  Drift, dasselbe Prinzip wie beim k6-Summary-Parser: fehlende/abweichende Felder degradieren
  konservativ, statt mit `KeyError` zu crashen.

14 neue Tests (`test_accessibility_verifier.py`, `test_accessibility_integration.py`). Neue
optionale Dev-Abhängigkeit `axe-core-python` in `requirements-dev.txt`. Volle Suite
(737 Tests) grün, ruff sauber.

Damit sind jetzt alle drei Agenten mechanisiert, die zuvor reine LLM-Einschätzungen ohne
echten Fundort abgaben: `security` (SAST), `compliance` (Lizenz-Audit) und `accessibility`
(axe-core) – durchgängig dasselbe Muster wie beim ursprünglichen Dependency-Audit.

---

## 📜 CHANGELOG.md für generierte Projekte & echtes Slack-Block-Kit-Format

Letzte zwei kleinere Punkte aus derselben Bestandsaufnahme:

- **`core/release_manager.py.update_project_changelog()`:** `tag_release()` erstellte bisher
  nur ein GitHub-Release (Tag + Notes) – nur das Framework-Repo hatte eine im Projekt selbst
  lesbare Versionshistorie, generierte Projekte in `workspace/` nicht. Nach jedem erfolgreichen
  Release schreibt derselbe Aufruf jetzt zusätzlich eine echte `CHANGELOG.md` **im generierten
  Projekt** (`workspace/<projekt>/CHANGELOG.md`, neueste Einträge zuerst) – über die
  GitHub-Contents-API (`gh api --method PUT`) direkt gegen den Default-Branch, ohne den
  lokalen Checkout in `BASE_DIR` anzufassen (derselbe Grund wie bei `gh release create`
  selbst: der lokale Checkout könnte gerade auf einem völlig anderen Branch stehen, z. B.
  mitten in einem parallelen Lauf). Sicher gegen versehentliches Überschreiben: ohne das
  korrekte `sha` einer bereits existierenden Datei lehnt GitHubs eigene Contents-API den
  Schreibvorgang ab, statt ihn stillschweigend zu ersetzen – `_fetch_existing_changelog()`
  startet deshalb im Fehlerfall bewusst konservativ mit einer frischen Datei, statt zu raten.
  Erkennt einen fremden/von Hand abweichenden Header, wird der neue Eintrag nur oben angefügt,
  statt bestehenden Inhalt zu überschreiben. Best effort wie das Release-Tagging selbst: ein
  fehlgeschlagenes CHANGELOG-Update lässt das bereits erfolgreiche Release NIE nachträglich
  als Fehlschlag gelten.
- **`core/notifier.py`:** Das Slack-Webhook-Payload war bisher ein einziger flacher
  `{"text": "..."}`-String – in Slack kam das unformatiert an, obwohl Slack für genau diesen
  Zweck ein eigenes Nachrichtenformat (Block Kit) mit fett/Struktur/Farbe anbietet.
  `_build_slack_payload()` nutzt jetzt echtes Block Kit: fett hervorgehobenes Event-Label,
  farbiger Rand je nach grob an Schlagworten erkanntem Schweregrad ("fehlgeschlagen"/
  "blockiert"/"Budget erreicht" → Rot, "Warnung"/"Achtung" → Orange, sonst Blau) und ein
  Kontext-Footer mit Zeitstempel. Das oberste `"text"`-Feld bleibt zusätzlich gesetzt – Slacks
  eigene Fallback-Konvention für Push-Vorschauen/Clients ohne Block-Kit-Rendering, zugleich
  Rückwärtskompatibilität für Fremd-Webhooks, die nur ein einfaches `"text"`-Feld auswerten.
  Bewusst NICHT umgesetzt: Threads/Mentions – beides bräuchte die `chat.postMessage`-API mit
  einem echten Bot-Token statt der aktuellen, einfachen Webhook-URL, ein anderes Auth-Modell.

29 neue Tests (`test_release_manager.py` erweitert, `test_notifier.py` erweitert). Volle Suite
(723 Tests) grün, ruff sauber.

---

## 🏋️ Echte Ausführung der Lastentest-Skripte statt ungeprüfter Ablage

Direkte Fortsetzung der Bestandsaufnahme unten: der `performance`-Agent schrieb bereits
vollständige k6-/Locust-Lastentest-Skripte, aber – anders als `run_tests()` für die normale
Testsuite – wurden sie NIE tatsächlich ausgeführt. Ein Skript, das nie läuft, ist praktisch
wertlos: niemand (Mensch oder Team) weiß, ob es syntaktisch überhaupt funktioniert oder was
es unter Last ergäbe.

- **`core/verifier.py.check_load_test()`** (`PerfCheckReport`): startet einen gefundenen
  Python-Web-Einstiegspunkt (dieselbe Erkennung wie im `http_api`-Zweig von
  `check_runtime_smoke()`) auf einem freien Port und führt einen kurzen SMOKE-Lasttest
  dagegen aus – wenige Sekunden, wenige virtuelle Nutzer. Bewusst KEIN vollständiger
  Lasttest/Benchmark (würde Minuten dauern und echte Ressourcen binden), nur eine Prüfung,
  ob die App unter minimaler gleichzeitiger Last überhaupt fehlerfrei antwortet. Sucht
  ausschließlich unter der neuen Konvention `tests/load/` (`locustfile.py` hat Vorrang vor
  `*.js`-k6-Skripten) – `agents/performance_agent.py` wurde entsprechend angepasst, inkl. der
  Vorgabe, die Ziel-URL NIEMALS hart zu codieren (Locust: `--host` zur Laufzeit; k6:
  `__ENV.BASE_URL`), da der automatische Testlauf den freien Port erst zur Laufzeit kennt.
  `locust`-CSV-Ergebnisse werden per `csv.DictReader` geparst (robust gegen Spalten-
  Reihenfolge-Unterschiede zwischen Locust-Versionen), `k6`-JSON-Summaries defensiv gegen
  bekannte Format-Abweichungen zwischen Versionen. Wie bei jedem anderen Check: fehlendes
  Skript/Tool oder ein technischer Fehlschlag (App startet nicht) ist KEIN Fehler, nur nicht
  prüfbar (`attempted=False`) – in der Praxis für die meisten Projekte ein No-Op. Neuer
  Opt-out `ENABLE_LOAD_TEST_CHECK=false`, Dauer über `LOAD_TEST_DURATION_SECONDS` (Standard 5s)
  konfigurierbar. Ein fehlgeschlagener Request zählt wie beim Runtime-Smoke-Test als echte
  Anforderungsverletzung (`verification_ok = False`), nicht als reiner Stil-Hinweis.
- **Nebenfund beim Bau des Checks:** `check_runtime_smoke()`s `http_api`-Zweig rief
  `CodeSandbox.safe_environment()` auf – eine Methode, die nie existiert hat (korrekt ist
  `_restricted_env()`). Jeder erkannte FastAPI-/Flask-/uvicorn-Einstiegspunkt wäre dadurch mit
  `AttributeError` gecrasht. Blieb unbemerkt, weil `tests/test_verifier_smoke.py` nur die
  `cli_script`-/`node_server`-Zweige mit einem echten Aufruf testet, nie den `http_api`-Zweig
  (der lief bisher ausschließlich über gemockte `check_runtime_smoke()`-Rückgabewerte in
  Integrationstests) – derselbe Musterfund wie schon beim `browser_verifier.py`-`NameError` im
  CHANGELOG-Eintrag weiter unten: reine Mocks sehen strukturell nicht jeden echten,
  dynamischen Codepfad. Direkt mitgefixt.

24 neue Tests (`test_verifier_load_test.py`, `test_load_test_integration.py`), 8 bestehende
Verifikations-Integrationstests um `check_load_test.return_value.attempted = False` ergänzt
(dasselbe Musterproblem wie bei `check_docker_build`/`check_browser_ui`: ein komplett
gemockter `ProjectVerifier` liefert für einen neuen, nicht explizit gemockten Single-Report-
Check sonst ein truthy `MagicMock` statt `attempted=False`). `agents/orchestrator.py` formatiert
`p95_ms` zusätzlich per `isinstance()`-Prüfung statt `is not None`, damit ein unvollständig
gemockter Verifier in künftigen Tests nicht erneut an derselben Stelle crasht. Volle Suite
(711 Tests) grün, ruff sauber. Neue optionale Dev-Abhängigkeit `locust` in
`requirements-dev.txt` (`k6` ist kein pip-Paket und muss separat installiert werden, wie
`docker` bei `check_docker_build()`).

---

## 🕵️ Mechanisierte Security-/Lizenz-Prüfung statt LLM-Raten & persistentes Design-System

Bestandsaufnahme auf explizite Nutzeranfrage ("welche Verbesserungen fehlen für ein
vollständiges, professionelles Team?"): Der Dependency-Audit (`pip-audit`/`npm audit`) und
der Lint-Check (`ruff`/`eslint`/`tsc`) hatten die rein LLM-basierte Einschätzung von
`security`/Code-Qualität bereits durch echte Tool-Läufe ersetzt – zwei weitere Agenten-Reports
hingen aber noch im alten Zustand fest: reines, ungeprüftes Freitext-Raten des Modells, ohne
Datei/Zeile oder echte Paket-Metadaten.

- **SAST für generierten Python-Code** (`core/verifier.py.check_sast()`, `SastReport`): Neuer
  echter statischer Scan (`bandit`) gegen bekannte Schwachstellenmuster (hartcodierte
  Secrets, unsichere Deserialisierung, SQL-Injection-Vektoren, unsichere Zufallszahlen,
  `eval`/`exec`, …) – ersetzt die bisherige Freitext-Einschätzung des `security`-Agenten
  (der Schwachstellen nur "plausibel" vermuten konnte) durch einen geparsten Fund mit
  exakter Datei/Zeile/Regel/Schweregrad. Dasselbe Graceful-Degradation-Prinzip wie beim
  Dependency-Audit: fehlendes `bandit` oder ein technischer Fehlschlag ist NIE ein Fehler,
  nur nicht prüfbar (`attempted=False`), niemals fälschlich als "keine Funde" gemeldet. Rein
  informativ im Abschlussbericht (wie Lint), kein automatischer Blocker – ein SAST-Fund kann
  ein False Positive sein und braucht menschliche Einschätzung, anders als ein roter Test.
  Aktuell nur Python; Node/Rust/Go (z. B. via `semgrep`) sind eine naheliegende spätere
  Erweiterung, analog dazu, wie auch der Dependency-Audit schrittweise über mehrere Runden
  auf Node/Rust/Go ausgeweitet wurde.
- **Echter Lizenz-/SBOM-Scan** (`core/verifier.py.check_licenses()`, `LicenseAuditReport`):
  `pip-licenses` liest die Lizenzen der TATSÄCHLICH installierten Python-Abhängigkeiten aus
  der isolierten Projekt-venv (`--python <venv-interpreter>`) und markiert bekannte
  Copyleft-Lizenzen (GPL/AGPL/LGPL/MPL/CDDL/EUPL/SSPL per Namens-Heuristik) – ersetzt die
  bisherige, vom `compliance`-Agenten GERATENE Lizenz-Tabelle ("MIT/AGPL 🔴") durch echte
  Paket-Metadaten. Rechtlich relevant: eine geratene Lizenzangabe bei einem echten
  Copyleft-Paket ist eine falsche Sicherheit, kein bloßer Stil-Hinweis wie ein Lint-Fund.
- **Persistentes Projekt-Design-System** (`core/design_system.py`, `/design-system [projekt]`):
  Die bereits bestehende Projekt-Konstitution (`core/project_constitution.py`) hält feste
  Tech-Stack-Präferenzen über mehrere Läufe hinweg fest – seit der Design-vor-Dev-
  Phasenaufteilung (`design_lead` läuft VOR `dev_lead`) fehlte ausgerechnet dem VISUELLEN
  Design (Farbpalette, Typografie, Spacing-Skala, Komponenten-Namenskonvention, Tonalität für
  `copywriter`) ein Pendant: ein zweiter Lauf am selben Projekt hätte eine andere
  Primärfarbe/Schriftart wählen können als der erste, ohne dass die Nutzeranfrage das je
  erwähnt hätte. Neue Datei `.ai-team-design.toml` im Projektverzeichnis (bewusst NICHT
  gitignored, wie `.ai-team.toml`), nach demselben Muster gelesen/geschrieben und bei JEDEM
  künftigen Lauf in den Kontext aller Teilaufgaben injiziert.

50 neue Tests (`test_verifier_sast.py`, `test_sast_integration.py`, `test_verifier_license.py`,
`test_license_audit_integration.py`, `test_design_system.py`, `test_cli_design_system_command.py`,
`test_design_system_integration.py`). Volle Suite (692 Tests) grün, ruff sauber. Neue optionale
Dev-Abhängigkeiten `bandit`/`pip-licenses` in `requirements-dev.txt` (dieselbe Graceful-Skip-
Philosophie wie `pip-audit`: fehlt das Tool lokal, wird der jeweilige Scan übersprungen statt
zu crashen oder fälschlich "sauber" zu melden).

**Bewusst zurückgestellt: mechanisierte Ausführung der vom `performance`-Agenten geschriebenen
k6-/Locust-Lastentests.** Anders als SAST/Lizenz-Scan (einmaliger, kurzer Tool-Aufruf) würde
ein echter Lasttest die generierte Anwendung tatsächlich unter Last hochfahren müssen – ein
deutlich größerer Eingriff (Ports, Laufzeit, Ressourcenverbrauch) als die übrigen
Verifikationsschritte. Als nächster Schritt vorgemerkt, aber nicht Teil dieser Runde.

---

## 🎨 Design-vor-Dev-Phasenaufteilung: Vorab-Design & Post-Dev-Content/Dokumentation

Strukturelle Weiterentwicklung der Fachbereichs-Hierarchie basierend auf dem von Claude
gekennzeichneten Architektur-Diskussionspunkt:

- **Aufspaltung der Design- und Content-Phasen:** Bisher lief `dev_lead` vor `creative_lead`
  – `creative_lead` enthielt jedoch sowohl vorlaufende Rollen (`ui_ux`, `image_generator`, `copywriter`),
  die Entwürfe und Assets vor dem Coden liefern sollten, als auch nachlaufende Rollen
  (`accessibility`, `i18n`, `documentation`, `readme`), die zwingend auf fertigen Code angewiesen sind.
- **6-Phasen-Ablauf:**
  1. `planning_lead`: Anforderungsanalyse, Scope & Architektur-Blueprint.
  2. `design_lead`: Wireframes, Design-Tokens, SVG-Icons/Logos & Copywriting vorab.
  3. `dev_lead`: Fullstack-, Backend- und Frontend-Entwicklung basierend auf den Design-Spezifikationen.
  4. `content_lead`: Barrierefreiheit (a11y), Mehrsprachigkeit (i18n), Dokumentation & README auf dem erzeugten Code.
  5. `qa_lead`: Echte Testsuite, Security-Audits & Resilience-Prüfung.
  6. `governance_lead`: Code-Review, Refactoring, DSGVO/Compliance & Hygiene.
- **Rückwärtskompatibilität:** `config.py` unterstützt weiterhin `CREATIVE_LEAD_MODEL` und
  `DEPARTMENT_CREATIVE_MODEL` als Fallbacks für `design_lead` und `content_lead`.
- **Neue Tests:** `tests/test_department_phase_order.py` validiert die strikte Phasenfolge und den
  Kontextfluss zwischen Design, Dev und Content/Doku.

---

## 🤖 Drei weitere Lücken gegenüber einem echten Profi-Team: Pro-Projekt-Budget, Release-Tagging, Sprint-Priorisierung

Zweite Runde derselben Nutzeranfrage-getriebenen Bestandsaufnahme (siehe Eintrag unten):

- **Pro-Projekt-Kostenbudget über ALLE Läufe hinweg:** `MAX_RUN_TOKENS` begrenzt nur EINEN
  einzelnen Lauf – ein Projekt mit vielen aufeinanderfolgenden Läufen (z.B. für einen externen
  Auftraggeber mit festem Kostenrahmen) hatte kein Limit über die gesamte Projekt-Lebenszeit.
  `/constitution` (neues Feld `max_project_tokens`) + `memory/run_history.get_total_tokens_for_project()`
  (bereits vorhandene, project_slug-gefilterte Lauf-Historie, nur neu summiert) schließen die
  Lücke, unabhängig vom globalen Lauf-Budget geprüft: ist das Projekt-Budget bereits VOR
  Laufbeginn erschöpft, bricht `agents/orchestrator.py.process()` ab, ohne auch nur einen
  Agenten zu starten; während des Laufs wird es an denselben drei Prüfpunkten wie
  `MAX_RUN_TOKENS` mitgeprüft (`_project_budget_exceeded()`). `_budget_exceeded_label()` nennt
  in jeder Abbruch-Meldung korrekt, WELCHES der beiden unabhängigen Budgets tatsächlich bindend
  war, statt pauschal auf `MAX_RUN_TOKENS` zu verweisen. `max_project_tokens` ist bewusst NICHT
  Teil des in den Agenten-Kontext injizierten Konstitutions-Texts (operative Kennzahl, keine
  inhaltliche Vorgabe).
- **Generierte Projekte bekommen jetzt eine eigene Versionshistorie:** Der PR-Workflow deckte
  Feature-Branch → Pull Request → Merge vollständig ab, aber danach passierte nichts mehr – nur
  das Framework selbst hatte ein gepflegtes CHANGELOG.md. `core/release_manager.py` (neu)
  taggt automatisch ein neues GitHub-Release (`<projekt>-vX.Y.Z`, fortlaufende Patch-Version je
  Projekt – workspace/-Projekte liegen im selben Repo wie das Framework, daher das
  Projekt-Präfix) MIT Release-Notes (Ticket-Titel + PR-Link), sobald `core/merge_watcher.py`
  einen echten Merge erkennt UND das Ticket ein `project_slug` trägt. Nächste freie Version wird
  über `gh release list` ermittelt (bewusst NICHT lokale `git tag`-Einträge, die ohne
  `git fetch --tags` veraltet sein könnten und denselben Tag doppelt vergeben würden). Best
  effort: ein fehlgeschlagenes Tagging lässt das Ticket trotzdem korrekt auf `done` stehen.
  Nebenbefund beim Verdrahten: `check_merged_tickets()` hätte für jeden Test versehentlich eine
  ECHTE, intern neu angelegte `GitHubAgent()`-Instanz für das Tagging verwendet statt der
  gemockten übergebenen Instanz – gefixt, bevor es zu echten `gh`-Aufrufen während der Tests
  kommen konnte.
- **Sprint-/Kapazitäts-Grundlagen im Backlog:** Bisher entstand JEDES Ticket erst, wenn eine
  Aufgabe bereits lief – keine Möglichkeit, mehrere geplante Aufgaben vorab zu priorisieren, und
  kein Kapazitätsbegriff über mehrere gleichzeitig laufende Tickets hinweg. `core/backlog_store.py`:
  `Ticket` bekommt `priority` (1=hoch/2=mittel/3=niedrig, dieselbe Konvention wie
  `AgentTask.priority`) und `estimate` (freier Text). `upsert_ticket()` behandelt beide als
  Sentinel (`None` = unverändert übernehmen) statt als echten Default – ein echter Default hätte
  eine beim Anlegen gesetzte Priorität bei jedem der zahlreichen bestehenden Status-Update-Aufrufe
  (z.B. `core/issue_watcher.py`, die priority/estimate nie mitgeben) stillschweigend auf
  "mittel" zurückgesetzt. Neuer CLI-Befehl `/backlog-add [priorität] <titel>` legt ein noch
  nicht begonnenes, priorisiertes `todo`-Ticket an (führt selbst nichts aus – wird erst zu
  echter Arbeit, wenn die Aufgabe regulär in den Chat geschrieben wird, genau wie die bereits
  bestehenden `todo`-Tickets aus `core/pr_review_watcher.py`). `/backlog` sortiert jede Spalte
  nach Priorität und zeigt eine rein informative WIP-Limit-Warnung (`BACKLOG_WIP_LIMIT_IN_PROGRESS`,
  Standard `0` = aus) – bewusst kein Hard-Block, ein Kanban-WIP-Limit ist Team-Disziplin, keine
  technische Zwangsbeschränkung.
- **Geprüft, aber bewusst NICHT geändert: Design-vor-Dev-Reihenfolge.** Vermutung aus der
  vorherigen Runde war, Design/Content liefe parallel zu oder nach der Entwicklung. Tatsächliche
  Prüfung von `_run_department_hierarchy()`: die 5 Fachbereichs-Phasen laufen strikt
  SEQUENZIELL (eine einfache `for`-Schleife über `PHASE_ORDER`) – nur die Mitglieder INNERHALB
  eines Fachbereichs können parallel laufen (`run_mode`). Entwicklung (`dev_lead`) läuft also
  bereits vollständig VOR Design/Content (`creative_lead`) ab, nicht parallel dazu. Eine
  Umkehrung (Design vor Dev) wäre für `ui_ux`/`image_generator` plausibel wertvoll, aber
  `creative_lead` enthält auch `accessibility`/`i18n`/`documentation`/`readme` – Rollen, die
  zwingend AUF bereits existierenden Code angewiesen sind (sie prüfen/beschreiben, was gebaut
  wurde). Eine pauschale Verschiebung des gesamten Fachbereichs würde diese vier Rollen ohne
  Not verschlechtern; eine gezielte Aufspaltung (nur `ui_ux`/`image_generator` vor `dev_lead`)
  wäre eine grössere Strukturänderung mit Auswirkung auf JEDEN künftigen Lauf – bewusst nicht
  ohne weitere Rücksprache umgesetzt.

42 neue Tests (`test_project_token_budget.py`, `test_release_manager.py`, Erweiterungen an
`test_project_constitution.py`/`test_run_history.py`/`test_merge_watcher.py`/
`test_backlog_store.py`, neues `test_cli_backlog_commands.py`). Volle Suite (656 Tests) grün,
ruff sauber.

---

## 🤖 Drei Lücken gegenüber einem echten Profi-Team: stille Datei-Kollisionen, passiver Dependency-Scan, fehlende Branch-Protection

Gezielte Bestandsaufnahme auf Nutzeranfrage ("was fehlt noch, damit das Team wie ein echtes
Entwicklerteam arbeitet?"), keine aus einem einzelnen Lauf beobachteten Symptome, sondern drei
strukturelle Lücken beim Durchsehen des Orchestrierungs-Codes selbst:

- **Datei-Kollisionen zwischen parallel arbeitenden Fachteam-Mitgliedern blieben stumm:**
  `agents/orchestrator.py._run_department_hierarchy()` lässt Fachbereiche mit 3+ Mitgliedern
  echt parallel per `asyncio.gather` laufen (der bestehende Kommentar dort dokumentiert
  bereits, dass sich Agenten dabei NIE gegenseitig sehen – Grundlage für die schon vorhandene
  Zwei-Mitglieder-Ausnahme). `core/agent_toolbox.py._tool_write_file()` überschreibt eine
  Datei dabei blind (kein Lock/Merge) – schreiben zwei Agenten dieselbe Datei (z.B.
  `requirements.txt`), gewann bisher stillschweigend nur der laut Ergebnis-Reihenfolge letzte
  Schreiber als `file_owners`-Eintrag, ohne dass irgendjemand vom Verlust der zuerst
  geschriebenen Version erfuhr. `_detect_file_write_collisions()` (neu) erkennt Kollisionen
  direkt nach jedem parallelen Ausführungs-Batch, meldet sie live UND sammelt sie für einen
  neuen, deterministischen `### ⚠️ Datei-Kollisionen`-Abschnitt im Abschlussbericht
  (`_build_file_collision_section()`) – automatisch entscheidbar, welche Version richtig ist,
  ist es nicht, deshalb "melden statt raten", dieselbe Philosophie wie bei fehlgeschlagener
  Verifikation. Rein additiv über den neuen, optionalen `collision_sink`-Parameter durchgereicht
  – bestehende Aufrufer/Tests ohne Interesse daran bleiben unverändert.
- **`--check-dependencies` warnte nur, statt wie ein echter Dependabot/Renovate zu handeln:**
  `core/dependency_watch.py` fand bekannte CVEs, legte aber nur ein `blocked`-Ticket an – ein
  Mensch musste die Abhängigkeit danach manuell selbst anheben. `core/dependency_updater.py`
  (neu) hebt jedes Paket mit bekannter Schwachstelle UND mindestens einer von `pip-audit`
  gelieferten `fix_versions`-Angabe in `requirements.txt` automatisch auf die erste (niedrigste
  sichere) Version an – bewusst NUR für Python: `pip-audit` liefert eine einfache, verlässliche
  "eine sichere Version"-Angabe direkt aus der Advisory-Datenbank, `npm audit` dagegen nicht
  (oft ein ganzer Abhängigkeitsbaum-Umbau mit möglichen Breaking Changes) – Node/Rust/Go
  bleiben deshalb bei der reinen Meldung. Der Update-PR läuft über denselben
  `agents/github_agent.py`-Mechanismus wie der Issue-Watcher, ohne menschliche Bestätigung
  (unbeaufsichtigter Poll-Zyklus – ein Mensch reviewt/merged den PR anschließend ganz normal
  über GitHub). Nebenbefund beim Verdrahten: `core/merge_watcher.py` erkannte eine PR-URL im
  Ticket-`detail`-Feld bisher nur per striktem `startswith("http")` – die neuen
  Dependency-Update-Tickets hängen die URL aber hinter einen beschreibenden Text (damit die
  Schwachstellen-Beschreibung im Board sichtbar bleibt), wären also NIE automatisch von
  "review" auf "done" gezogen worden. Auf einen Substring-Regex-Match umgestellt (deckt beide
  Fälle ab, keine Verhaltensänderung für die bestehenden PR-Workflow-/Issue-Tickets).
  `ENABLE_DEPENDENCY_AUTO_UPDATE=true` (Standard) schaltet es ab.
- **Der PR-Workflow verhinderte nur eigene Direct-Pushes, nicht die eines Menschen:**
  `agents/github_agent.py.create_branch()`/`create_pull_request()` sorgen dafür, dass DIESES
  Tool nicht direkt auf `main` committet – GitHub selbst kannte davon nichts, ein `git push
  origin main` von Hand (oder einem anderen Tool) wäre weiterhin klaglos durchgegangen. Neue
  Methoden `get_repo_slug()`/`set_branch_protection()` aktivieren echte Branch-Protection über
  `gh api --method PUT ... --input -` (Pflicht-Freigaben vor dem Merge, kein
  Force-Push/Löschen, gilt auch für Repo-Admins). Neuer CLI-Befehl `/protect-branch [branch]`
  mit Vorschau + Bestätigung (`BRANCH_PROTECTION_REQUIRED_REVIEWS`, Standard `1`) – bewusst nur
  ein expliziter, einmaliger Befehl statt eines automatischen Laufs, da eine Änderung an den
  Repo-Einstellungen selbst Admin-Rechte voraussetzt und ein bewusster Schritt sein soll, kein
  Seiteneffekt eines normalen Team-Laufs.

46 neue Tests (`test_file_write_collisions.py`, `test_dependency_updater.py`, Erweiterungen an
`test_dependency_watch.py`/`test_merge_watcher.py`/`test_github_agent_issue_methods.py`, neues
`test_protect_branch_command.py`). Volle Suite (614 Tests) grün, ruff sauber.

---

## 🔍 Code-Review-Runde: drei stille Verifikations-Lücken, Lint-Gate & Test-Isolation

Eine gezielte Bestandsaufnahme des gesamten Frameworks (nicht aus einem einzelnen Lauf,
sondern aus systematischem Code-Review + echtem Ausführen von `ruff`/der vollen Testsuite)
förderte drei echte Bugs zutage, die ausgerechnet die eigenen Verifikations-Features
betrafen – also genau die Stellen, denen ein autonomer Lauf am meisten vertraut:

- **`core/browser_verifier.py`:** `sys.executable` wurde verwendet, obwohl `import sys` im
  Modul fehlte. Der resultierende `NameError` wurde vom umgebenden `except Exception: return
  None` lautlos verschluckt – der dynamische Playwright-Check lief dadurch **nie**, selbst
  wenn Playwright installiert war, und das System fiel bei JEDEM Lauf unbemerkt auf die
  statische DOM-Prüfung zurück (`engine` blieb fälschlich `"static_dom"`).
- **`agents/orchestrator.py`:** Der `else`-Zweig für einen fehlgeschlagenen Runtime-Smoke-Test
  (App startet nachweislich nicht) baute nur eine ungenutzte `err`-Variable (von `ruff` als
  `F841` markiert) – ohne `notify()`, ohne Eintrag in `summary_lines`, ohne `verification_ok`
  zurückzusetzen. Ein echter Startfehler blieb dadurch komplett unsichtbar UND unblockiert,
  obwohl genau das der Zweck dieses Checks ist ("Tests grün != App startet", siehe Eintrag
  weiter unten). Jetzt analog zur Testabdeckungs-Schwelle behandelt: sichtbar gemeldet UND
  `verification_ok = False`.
- **`interface/web_dashboard.py`:** `DashboardServer.shutdown()` stoppte den Event-Loop, ohne
  den dauerhaft laufenden `_dispatch_loop()`-Task vorher zu canceln – sichtbar als `Task was
  destroyed but it is pending!`/`RuntimeError: Event loop is closed`-Rauschen am Ende der
  Testsuite. Rein kosmetisch (keine Tests schlugen dadurch fehl), aber ein sauberer Shutdown
  sollte keine offenen Tasks lautlos zurücklassen.

**Nebenbefund beim Verifizieren der Fixes:** `tests/test_commit_message_summary.py` war nicht
workspace-isoliert (fehlende `self.orchestrator._workspace = WorkspaceManager(tempdir)`,
anders als `test_coverage_integration.py` & Co.) und schrieb bei JEDEM Testlauf über
`core/project_status.py.record_run()` eine echte `.ai_team_status.json` in einen neuen, nie
committeten `workspace/fastapi_health_check/`-Ordner im echten Framework-Workspace – die
volle Testsuite hat also bei jedem Durchlauf den eigenen Workspace vollgemüllt. Jetzt isoliert.

`ruff check .` fand darüber hinaus 36 Lint-Fehler auf `main` (u.a. genau der `NameError` oben
als `F821`) – der CI-Lint-Job war zum Zeitpunkt dieser Bestandsaufnahme also tatsächlich rot,
nur bemerkte es niemand, weil `ruff` nirgends lokal vor dem Commit lief:

- **Neues lokales Pre-Commit-Lint-Gate** (`scripts/git-hooks/pre-commit` +
  `scripts/install-git-hooks.ps1`/`.sh`, einmalig zu installieren): bricht `git commit` ab,
  wenn `ruff check .` Funde meldet (umgehbar mit `--no-verify`). `.gitattributes` (neu, gab es
  bisher gar nicht) erzwingt LF für diese Shell-Skripte, da `core.autocrlf=true` (Windows-
  Standard) sie sonst beim nächsten Checkout auf CRLF umgestellt und damit an der
  Shebang-Zeile gebrochen hätte.
- **README-Empfehlung statt automatisiertem Workflow:** ein regelmäßiger `--eval`-Lauf mit
  echten Provider-Keys vor größeren Releases wurde bewusst NUR als dokumentierter manueller
  Schritt ergänzt (README, Abschnitt "Tests ausführen"), nicht als automatisierter
  GitHub-Actions-Workflow – das würde wiederkehrende, echte API-Kosten verursachen und eigene
  Secrets-Freigaben voraussetzen, eine Entscheidung, die bewusst beim Repo-Betreiber bleibt.

4 neue Regressionstests (Playwright-`sys.executable`-Aufruf, Smoke-Test-Sichtbarkeit im
Erfolgs- UND Fehlerfall, Dashboard-Shutdown-Task-Cleanup); volle Suite (568 Tests) grün, ruff
sauber.

---

## 🔔 Externe Benachrichtigung bei Vorfällen, die menschliche Aufmerksamkeit brauchen

Dritter Fund derselben Bestandsaufnahme (siehe die beiden Einträge unten): Blockaden waren
bisher nur sichtbar, wenn jemand aktiv ins Dashboard/Log/Issue schaute – core/issue_watcher.py
(Cron-Poll-Zyklus) und interface/web_dashboard.py (Hintergrund-Jobs) laufen aber gerade
UNBEAUFSICHTIGT, anders als interface/cli.py.

- `core/notifier.py` (neu): `notify_external(event, message)` – No-op ohne konfiguriertes
  `NOTIFY_WEBHOOK_URL` (Standard), sonst ein einfacher JSON-POST (`{"text": "..."}`,
  Slack-Incoming-Webhook-kompatibel) über die bereits vorhandene `httpx`-Abhängigkeit. Ein
  Fehlschlag beim Senden wird verschluckt – darf nie einen sonst erfolgreichen Lauf zum
  Scheitern bringen, dieselbe Best-Effort-Philosophie wie `memory/run_history.py.record_run()`.
- Vier Integrationsstellen, bewusst an bereits bestehenden "das braucht Aufmerksamkeit"-Punkten
  statt neuer verstreuter Logik: `agents/orchestrator.py` (ein zentraler Aufruf dort, wo das
  erreichte Lauf-Budget bereits in die Statistik einfließt – deckt alle drei Stellen ab, an
  denen `budget_aborted` gesetzt werden kann), `core/issue_watcher.py` (EIN Aufruf direkt neben
  dem bestehenden `upsert_ticket()`-Mapping-Ort in `run_issue_poll_cycle()`, feuert für jeden
  Outcome außer dem echten Erfolgsfall `pr_opened`), `interface/web_dashboard.py`
  (`_execute_job()` bei `ticket_status == "blocked"`), `interface/cli.py._report_ci_status()`
  (siehe CI-Feedback-Loop-Eintrag unten).
- 3 neue Tests (`tests/test_notifier.py`) plus je ein Test an den vier Integrationsstellen
  (`tests/test_governance_fix_loop.py`, `tests/test_issue_watcher.py`,
  `tests/test_web_dashboard.py`, `tests/test_cli_push_gate.py`).

---

## 🔀 CI-Feedback-Loop geschlossen: rote CI zieht den Backlog-Status jetzt nach

Zweiter Fund derselben Bestandsaufnahme: `agents/github_agent.py.wait_for_ci_status()` wurde
nach einem Push zwar aufgerufen, das Ergebnis aber nur angezeigt/geloggt – der
Backlog-Ticket-Status (`core/backlog_store.py`) blieb "review"/"done" stehen, selbst wenn die
echte CI-Pipeline danach tatsächlich rot wurde. `core/issue_watcher.py` prüfte CI nach einem PR
bisher gar nicht.

- `interface/cli.py._report_ci_status()` gibt jetzt `(status, detail)` statt `None` zurück.
  `_ask_for_git_push()` zieht den Ticket-Status bei `"failed"` auf `"blocked"` (statt bei
  "review"/"done" stehen zu bleiben) und ergänzt die CI-Fehlermeldung im Ticket-Detail –
  `"passed"`/`"timeout"`/`"no_run"` ändern nichts am bisherigen Verhalten.
- `core/issue_watcher.py`: nach erfolgreicher PR-Erstellung wird jetzt zusätzlich
  `wait_for_ci_status()` abgefragt. Neuer Ausgang `"pr_opened_ci_failed"` (Label bleibt
  `ai-team-done` – ein PR WURDE eröffnet, das beschreibt das Label bereits korrekt; die
  CI-Info steht stattdessen im Issue-Kommentar), gemappt auf Backlog-Status `"blocked"` – über
  denselben bereits bestehenden EIN-Mapping-Ort (`_OUTCOME_TO_TICKET_STATUS` in
  `run_issue_poll_cycle()`), kein neuer Sonderfall an einer zweiten Stelle.
- 4 neue Tests in `tests/test_cli_push_gate.py`, 4 neue Tests in `tests/test_issue_watcher.py`.
  `tests/test_ci_feedback_loop.py` (reine `wait_for_ci_status()`-Unit-Tests) unverändert.

---

## 🛡️ Governance-Fix-Loop: kritische Review-Befunde lösen jetzt einen Korrekturauftrag aus

Erster Fund einer Bestandsaufnahme des eigenen Teams (kein einzelner End-to-End-Testlauf
diesmal, sondern eine gezielte Durchsicht, ob das Team wie ein echtes Entwicklerteam
funktioniert): `code_reviewer`/`security`/`compliance` (`REVIEW_ONLY_AGENT_IDS`)
kategorisieren Befunde in ihren Reports selbst nach Schweregrad ("Kritisch") – das löste aber
NIE einen Korrekturauftrag aus, nur ein echter Testfehler tat das
(`agents/orchestrator.py._run_verification_loop()`). Ein "Kritisch" im Code-Review ist bei
einem echten Team ein Blocker, kein FYI im Abschlussbericht.

- `core/review_gate.py` (neu): `find_critical_findings()` erkennt kritisch markierte
  Abschnitte per Text-Heuristik (🔴-Emoji und/oder das Wort "Kritisch", mit Negativ-Filter gegen
  "keine kritischen Befunde"-Bestätigungen) – bewusst KEIN vollständiger Markdown-Parser,
  sondern gezielt auf die drei tatsächlich in den System-Prompts vorgeschriebenen Formate
  getestet (analog zu `_ADR_TEXT_MARKERS`/`_is_rate_limit_error()` an anderer Stelle im
  Projekt). `route_findings_to_owners()` gleicht Backtick-Dateipfade in jedem Fund gegen
  `file_owners` ab und ordnet ihn dem zuständigen Agenten zu; nicht zuordenbare Funde landen
  transparent im Protokoll statt still zu verschwinden.
- `agents/orchestrator.py._run_governance_fix_loop()`: neue Methode, strukturell ein
  Geschwister von `_run_verification_loop()` (gleiche Budget-/Abbruch-Prüfpunkte, gleiches
  Fix-Dispatch-Muster über `file_owners`). Läuft NACH der Fachbereichs-Hierarchie und VOR der
  echten Testverifikation. `MAX_REVIEW_ITERATIONS` (bisher ein toter, nie verdrahteter Rest aus
  einer früheren Version unter "Sprache & Verhalten" – ebenfalls ein realer Fund dieser
  Bestandsaufnahme) steuert jetzt tatsächlich, ob nach einem Fix-Versuch die ursprünglich
  meldenden Review-Rollen frisch erneut geprüft werden (Standard `1` = genau ein Fix-Dispatch
  ohne erneute Prüfung). Neuer Flag `ENABLE_GOVERNANCE_FIX_LOOP` (Standard an).
- 12 neue Tests (`tests/test_review_gate.py`), 6 neue Tests
  (`tests/test_governance_fix_loop.py`, voller `Orchestrator.process()`-Lauf mit gemocktem LLM).
- Volle Suite (506 Tests) grün, ruff sauber.

---

## ⚡ Team-Komplexitäts-Skalierung: kein Teamleiter-Overhead mehr bei trivialen Aufgaben

Realer Fund aus Probelauf 3 (FastAPI-Ping-API, ein einziger Endpunkt + ein Test): 66.000
Tokens verbraucht, obwohl am Ende nur 2 Dateien entstanden – der Lauf selbst diagnostizierte
sich in seiner eigenen Retrospektive als "Token-Inflation" und "Over-Engineering". Ursache:
jeder der 3 beteiligten Fachbereiche (dev/qa/governance) hatte jeweils nur EIN einziges
Mitglied (backend, tester, code_reviewer), durchlief aber trotzdem die volle
Teamleiter-Delegation UND -Konsolidierung – macht 6 zusätzliche LLM-Aufrufe für 3 tatsächliche
Arbeitsergebnisse. Ein Teamleiter, der mit sich selbst über die Aufgabenverteilung an EIN
Mitglied "abstimmt", stiftet keinen echten Nutzen.

- `core/task_manager.py`: neue Funktion `is_micro_task()` – rein deterministisch aus dem
  bereits erstellten Aufgabenplan berechnet (KEIN zusätzlicher LLM-Aufruf, keine neue
  Schätzung). Eine Aufgabe gilt als klein, wenn höchstens 4 Spezialisten eingeplant wurden UND
  keiner davon zu `_COMPLEXITY_SIGNAL_AGENT_IDS` gehört (architect, security, compliance,
  finops, performance, data_engineer, ml, mobile, product_owner, business_analyst,
  web_research – Rollen, die laut den bestehenden `DECOMPOSE_SYSTEM_PROMPT`-Regeln ohnehin nur
  bei echter Komplexität eingeplant werden).
- `agents/orchestrator.py._run_department_hierarchy()`: neues Flag `ENABLE_TASK_COMPLEXITY_SCALING`
  (Standard an). Hat ein Fachbereich bei einer kleinen Aufgabe nur EIN Mitglied, entfallen
  Delegation UND Konsolidierung durch den Teamleiter – das Mitglied bekommt seine bereits
  präzise Aufgabenbeschreibung aus `decompose()` direkt. Fachbereiche mit MEHREREN Mitgliedern
  behalten die Teamleiter-Koordination immer (echter Abstimmungsbedarf, z.B. um doppelte
  Parallel-Implementierungen zu vermeiden).
- 9 neue Tests (`test_task_complexity_scaling.py`): `is_micro_task()`-Klassifikation inkl. des
  real beobachteten backend+tester+code_reviewer-Plans; Einzelmitglied-Fachbereiche überspringen
  Delegation/Konsolidierung bei kleiner Aufgabe; Mehrmitglied-Fachbereiche behalten sie immer;
  abgeschaltetes Flag stellt exakt das alte Verhalten wieder her. Volle Suite (458 Tests) grün,
  ruff sauber.

---

## 🪙 Klare Fehlermeldung statt rohem Provider-JSON beim gepinnten Groq-/Claude-Scheitern

Fund aus Probelauf 3 (gezielte Nachverifikation von Fix #1 direkt gegen `main`): der Trial
löste dabei unprovoziert das real vertagte "Groq-Tageslimit"-Szenario aus –
`governance_lead` (HEAVY-Tier, kein `ANTHROPIC_API_KEY`) war innerhalb einer Aufgabe bereits
erfolgreich auf Groq gepinnt (siehe `agents/base_agent.py` `active_llm`), verbrauchte über
mehrere Iterationen genug Tokens, um Groqs echtes Tageskontingent zu kippen ("tokens per day
(TPD)") – und die Aufgabe scheiterte mit dem **rohen Groq-JSON-Fehlertext** als
`AgentResult.error`, statt einer verständlichen Meldung. Zwei gezielte Probes an den echten
Klassen aus `core/llm_factory.py` bestätigten den Mechanismus: **vor** dem Pinning wird ein
Groq-Ausfall transparent zu Gemini gerettet, **nach** dem Pinning (`_allow_self_fallback=False`)
wird die Exception bewusst ungefiltert durchgereicht – ein weiterer Hop dort würde exakt die
Provider-Historie-Korruption zurückbringen, die das Pinning verhindert (siehe
`_run_agentic_loop`-Docstring). Dieses Verhalten bleibt **unverändert** – nur die Meldung war
unnötig kryptisch.

- `core/llm_factory.py`: neue Helfer `_is_rate_limit_error()` / `_pinned_provider_failure()`.
  Erkennt eine Exception als Kontingent-/Rate-Limit-Fehler (429/rate_limit/resource_exhausted/
  quota), ersetzt sie beim gepinnten Scheitern (`GroqClient`/`ClaudeClient`, jeweils
  `generate_with_usage()` UND `generate_with_tools()`) durch eine verständliche deutsche
  Meldung ("bereits fest eingeplant und gerade nicht verfügbar ... kurz warten oder API-Key
  ergänzen"), die die rohe Provider-Meldung zur Diagnose weiterhin enthält (`raise ... from e`).
  Andere Fehlerarten (z.B. Netzwerkfehler) bleiben bewusst unverändert roh durchgereicht, da
  dort eine andere Diagnose nötig ist.
- 4 neue Tests (`test_pinned_provider_failure_message.py`): gepinnter Groq-/Claude-Rate-Limit-
  Fehler bekommt die klare Meldung; ein NICHT-Rate-Limit-Fehler bleibt unverändert; der
  bestehende automatische Rettungs-Hop zu Gemini VOR dem Pinning funktioniert weiterhin
  unverändert (Regressionsschutz). Volle Suite (453 Tests) grün, ruff sauber.

---

## 📐 ADR-Adoption Teil 2: architect ruft das Werkzeug jetzt auch wirklich auf

Fund aus einem ZWEITEN echten End-to-End-Testlauf, der gezielt prüfte, ob die vorherige
ADR-Adoption-Runde (siehe Eintrag unten) wirklich greift: Sie greift – teilweise. `architect`
wurde diesmal korrekt eingeplant und explizit mit "erstelle ADR" beauftragt
(`DECOMPOSE_SYSTEM_PROMPT`-Regel funktioniert live nachweislich), rief aber trotz eigener
System-Prompt-Anweisung (`agents/architect_agent.py`) NIE `record_architecture_decision` auf –
die Entscheidung stand nur im Fließtext. Der bestehende Code-Fence-Retry
(`CODE_WRITING_AGENT_IDS`) greift hier nicht: `architect` gehört nicht zu dieser Gruppe und
liefert legitim Code-Fences für Mermaid-Diagramme, ohne dass "kein write_file aufgerufen"
dort ein Problem wäre.

- `agents/base_agent.py`: eigene, gezielte Heuristik für `architect` – NICHT der
  Code-Fence-Check von oben, sondern `_ADR_TEXT_MARKERS` (deckt den vom
  `architect`-Ausgabeformat selbst vorgeschriebenen Abschnitt "Technologie-Entscheidungen
  (ADRs)" ab). Erwähnt die finale Antwort eine Technologie-/Architektur-Entscheidung, OHNE
  dass während der GESAMTEN Aufgabe auch nur eine Datei (nicht mal ein ADR) geschrieben
  wurde, wird GENAU EIN gezielter Korrektur-Hinweis nachgeschoben – dasselbe
  Ein-Retry-Muster wie die beiden bestehenden Fixes.
- 6 neue Tests (`test_agentic_loop_resilience.py`): Retry-Pfad inkl. echtem
  `record_architecture_decision`-Aufruf danach; kein Retry ohne Entscheidungs-Marker; kein
  Retry, wenn schon eine Datei geschrieben wurde; kein Retry für Agenten außerhalb von
  `architect` (auch nicht für `backend` mit demselben Marker im Text); nur EIN Retry; kein
  Retry ohne verbleibende Iteration. Volle Suite (446 Tests) grün, ruff sauber.

---

## 📐 ADR-Adoption: architect wird jetzt zuverlässiger eingeplant

Vierter und letzter Fund aus demselben echten End-to-End-Testlauf (siehe die Einträge
unten): obwohl die Aufgabe explizit eine Technologie-Abwägung mit echter Alternative
verlangte ("wäge zwischen In-Memory-Liste und SQLite ab und begründe die Entscheidung"),
plante der Hauptagent den `architect`-Agenten gar nicht erst ein – `backend`/`database`
trafen die Entscheidung dann selbst, ohne sie je über `record_architecture_decision` zu
dokumentieren. Zwei unabhängige Gegenmaßnahmen, da keine allein zuverlässig genug ist:

- `core/task_manager.py`: `DECOMPOSE_SYSTEM_PROMPT` bekommt eine explizite,
  NICHT-optionale Einbeziehungs-Regel für `architect`, analog zu den bestehenden Regeln für
  `security`/`compliance`/`tester` – sobald eine echte Technologie-/Architektur-Entscheidung
  mit mehreren vertretbaren Alternativen ansteht (Datenpersistenz, Monolith vs.
  Microservices, REST vs. GraphQL, Datenbanksystem, Auth-Strategie), nicht nur bei
  offensichtlich komplexen Aufgaben.
- `agents/base_agent.py`: zweite Verteidigungslinie – Code-schreibende Agenten
  (`CODE_WRITING_AGENT_IDS`) bekommen in ihrem Werkzeug-Anweisungsblock zusätzlich einen
  expliziten Hinweis auf `record_architecture_decision`, falls `architect` trotzdem nicht
  eingeplant wird. Gezielt NUR für diese Rollen (nicht z.B. `copywriter`/`i18n`, die legitim
  keine Architektur-Entscheidungen treffen) – kein unnötiger Prompt-Text für Rollen, die ihn
  nie brauchen.
- 3 neue Tests (`test_adr_adoption.py`): die neue `architect`-Regel steht wirklich (und als
  "NICHT optional") im Prompt – bewusst nur ein Text-Regressionstest, kein Beweis, dass ein
  echtes LLM ihr folgt, das kann nur ein weiterer echter Lauf zeigen; ein Code-schreibender
  Agent sieht den ADR-Hinweis, ein reiner Text-Agent (`copywriter`) nicht. Volle Suite
  (440 Tests) grün, ruff sauber.

---

## 🛠️ Code-schreibende Agenten liefern Code nicht mehr unbemerkt nur im Antworttext

Dritter Fund aus demselben echten End-to-End-Testlauf (siehe die beiden Einträge unten):
Backend (×2), Datenbank- und README-Agent meldeten `success=True` und verbrauchten
zusammen ~48.000 Tokens, schrieben dabei aber laut Report "0 Dateien" – der Code steckte
vermutlich nur im Antworttext statt über `write_file`/`edit_file`, trotz expliziter
Anweisung dazu (`_augment_with_tool_instructions()`). Der bestehende Regex-Text-Fallback
(`core/workspace.py.parse_and_save_files()`) fing das NICHT auf – im Log erschien kein
einziges "💾 Workspace: … Text-Fallback"; die Regex verlangt einen erkennbaren
Dateipfad-Marker (Fence mit Doppelpunkt, Überschrift mit Backtick-Dateiname, "Datei:"/
"File:"-Zeile), den freier Fließtext ohne solche Marker nicht liefert.

- `agents/base_agent.py`: `CODE_WRITING_AGENT_IDS` (bisher in `agents/orchestrator.py`, das
  es nur noch importiert) lebt jetzt hier, da `_run_agentic_loop()` es direkt braucht.
  Liefert ein Code-schreibender Agent eine finale Textantwort mit einem Code-Fence
  (`` ``` ``), OHNE dass während der GESAMTEN Aufgabe auch nur eine Datei über
  `write_file`/`edit_file` gespeichert wurde, UND ist noch mindestens eine Iteration übrig,
  wird GENAU EIN gezielter Korrektur-Hinweis nachgeschoben ("rufe jetzt write_file/edit_file
  auf") statt die Antwort unkorrigiert zu akzeptieren – dasselbe Ein-Retry-Muster wie beim
  bestehenden `tool_use_failed`-Fix.
- 7 neue Tests (`test_agentic_loop_resilience.py`): der Retry-Pfad inkl. echtem
  `write_file`-Aufruf danach; kein Retry ohne Code-Fence; kein Retry, wenn schon vorher eine
  Datei geschrieben wurde (verhindert Fehlalarme bei legitimen Kurz-Zitaten in der
  Zusammenfassung); kein Retry für Agenten außerhalb von `CODE_WRITING_AGENT_IDS`; nur EIN
  Retry auch bei wiederholtem Fehlverhalten; kein Retry ohne verbleibende Iteration. Volle
  Suite (437 Tests) grün, ruff sauber.

---

## 🔀 PR-Workflow ließ generierte Projekte lokal verschwinden (echter End-to-End-Testlauf)

Erster echter End-to-End-Testlauf seit Einführung des PR-Workflows (reale FastAPI-Notiz-API,
echte LLM-Aufrufe über alle Fachbereiche, echter Push gegen GitHub) deckte einen schweren
Bug auf: `_ask_for_git_push()` wechselte nach Commit+Push+PR-Erstellung per `git checkout
<hauptbranch>` zurück – da das neu generierte Projekt NUR auf dem Feature-Branch committet
war (nicht auf `main`), entfernte dieser Checkout es **komplett aus dem
Arbeitsverzeichnis**. Der Code war nicht weg (sicher im Commit, gepusht, im offenen PR
sichtbar), aber lokal bis zum Merge unsichtbar – `/load <projekt>` und jeder Folgeauftrag am
selben Projekt hätten es fälschlich als neu angelegt interpretiert, weil
`WorkspaceManager.list_projects()` es nicht mehr fand. Bricht damit die bestehende
Projekt-Kontinuität über Sitzungen hinweg. Kein Unit-Test hat das gefangen: alle
PR-Workflow-Tests liefen entweder komplett gemockt oder in einem isolierten Test-Repo, nie im
echten Arbeitsverzeichnis mit echten, weiterzuentwickelnden Projekten daneben.

- `agents/github_agent.py`: `create_branch()` akzeptiert jetzt ein optionales `base` –
  branch explizit von einem bestimmten Branch abzweigen statt vom aktuellen HEAD, das nach
  diesem Fix nicht mehr zuverlässig der Hauptbranch ist.
- `interface/cli.py._ask_for_git_push()` / `core/issue_watcher.py._process_single_issue()`:
  Kein `git checkout <hauptbranch>` mehr NACH Push+PR – das Arbeitsverzeichnis bleibt bewusst
  auf dem Feature-Branch stehen, damit gerade erst generierte Dateien sichtbar bleiben. Damit
  der NÄCHSTE Lauf trotzdem korrekt vom echten Hauptbranch abzweigt (nicht vom
  Leftover-Feature-Branch dieses Laufs): `original_branch` wird jetzt zusätzlich als
  "Leftover-Zustand" erkannt, wenn er mit `feat/` beginnt und kein konfigurierter
  Hauptbranch ist (die eigene Namenskonvention, siehe `build_feature_branch_name()`) – dann
  wird trotzdem der PR-Workflow genutzt, aber explizit vom ersten konfigurierten
  Hauptbranch (`GIT_PROTECTED_BRANCHES[0]`) abgezweigt statt vom Leftover-Branch selbst.
- 2 neue Tests gegen ein echtes lokales Git-Repo (`test_pr_workflow.py`): beweisen, dass die
  gerade committete Datei nach einem Lauf lokal sichtbar BLEIBT, und dass ein zweiter Lauf
  direkt danach trotzdem korrekt vom Hauptbranch (nicht vom Leftover-Branch des ersten Laufs)
  abzweigt – der Beweis erfolgt über einen echten `git diff`, der zeigt, dass Branch 2 NICHT
  die Datei aus Lauf 1 enthält. Bestehende Tests, die den (jetzt entfernten) Rückwechsel
  erwarteten, entsprechend korrigiert. Volle Suite (433 Tests) grün, ruff sauber.

---

## 🪙 Groq-Backstop für die STANDARD/LITE-Gemini-Fallback-Kette (echter Testlauf)

Derselbe echte End-to-End-Testlauf wie beim PR-Workflow-Fund (siehe unten): der QA-Tester
scheiterte komplett – "Gemini Function-Calling Fehler nach allen Fallback-Modellen
(gemini-3.1-flash-lite): Claude innerhalb einer Fallback-Kette nicht verfügbar (kein
ANTHROPIC_API_KEY)" –, obwohl Groq im SELBEN Lauf für andere Rollen (Backend, Datenbank,
Code-Reviewer, …) einwandfrei funktionierte. Ursache: `core/llm_factory.py.MODEL_FALLBACKS`
hatte einen Groq-Backstop bisher nur für die HEAVY-Stufe (`GROQ_HEAVY_MODEL` in `config.py`),
nicht für die STANDARD/LITE-Gemini-Ketten – ein Agent mit einer echten Gemini-Störung (nicht
nur Quota-Erschöpfung) hatte dort keine weitere Rettung mehr.

- `core/llm_factory.py`: `groq:openai/gpt-oss-120b` als letzte Stufe zu den
  `gemini-3.6-flash`-, `gemini-3.1-flash-lite`- und `gemini-3.5-flash`-Fallback-Ketten
  ergänzt. Kein Endlosloop möglich (`_allow_self_fallback=False` verhindert, dass Groq bei
  eigenem Scheitern zurück zu Gemini zurückspringt).
- 1 neuer Test (`test_llm_routing.py`): beweist, dass ein Aufruf tatsächlich bei Groq landet,
  wenn sowohl Gemini als auch Claude scheitern. Dabei einen zweiten, echten Fund gemacht:
  ein BESTEHENDER Test (`test_waits_briefly_when_entire_fallback_chain_is_exhausted`) markierte
  absichtlich die GESAMTE Kette als erschöpft, um die Cooldown-Wartelogik zu prüfen – ohne
  den neuen Groq-Kandidaten mit zu markieren, wäre die Kette durch den Fix nie mehr
  vollständig erschöpft gewesen, und der Test hätte im echten `GROQ_API_KEY`-Environment
  unbemerkt einen ECHTEN Netzwerkaufruf an die Groq-API ausgelöst statt wie vorgesehen
  komplett gemockt zu bleiben. Test entsprechend korrigiert. Volle Suite (432 Tests) grün,
  ruff sauber.

---

## 📐 Architecture Decision Records (ADRs)

Realer struktureller Fund: `agents/architect_agent.py`s eigener Ausgabe-Prompt sprach schon
immer von "ADRs" (Abschnitt "6. Technologie-Entscheidungen (ADRs)") – aber nichts schrieb sie
je als echte, persistente Datei. Jede Entscheidung stand nur im Antworttext EINES Laufs und
war beim nächsten Lauf bereits wieder vergessen. `core/project_constitution.py` hält das WAS
fest (Tech-Stack), nie das WARUM – ohne das konnten spätere Läufe unbemerkt gegen frühere,
bewusst getroffene Entscheidungen arbeiten.

- `core/adr.py` (neu): `write_adr()` legt eine nummerierte `docs/adr/NNNN-slug.md` im
  Projekt an (Nygard-Format: Titel, Status, Kontext, Entscheidung, Konsequenzen) – die
  Nummer wird deterministisch in Python vergeben statt vom Modell geraten, schließt
  Kollisionen/Lücken aus. Bewusst NICHT gitignored (anders als `memory/backlog.json`) – ADRs
  sind Projekt-Dokumentation und sollen mit dem Code versioniert werden.
  `format_adr_summary_for_context()` liefert einen token-gedeckelten Digest (max. 12 ADRs,
  älteste fallen zuerst raus) für die Kontext-Injektion.
- `core/agent_toolbox.py`: neues Werkzeug `record_architecture_decision` – JEDER Agent im
  Werkzeug-Loop kann es aufrufen (dieselbe flache Toolset-Verfügbarkeit wie `write_file`),
  primär gedacht für Entscheidungen mit echter Alternative ("PostgreSQL statt MongoDB", "REST
  statt GraphQL"). Trackt die geschriebene Datei in `toolbox.files_written` wie jedes andere
  Datei-Werkzeug (relevant für die bestehende `file_owners`-Zuordnung).
- `agents/architect_agent.py`: System-Prompt weist jetzt explizit an, Entscheidungen mit
  echter Alternative ZUSÄTZLICH über das neue Werkzeug festzuhalten statt nur im Fließtext,
  und bereits im Kontext mitgegebene frühere Entscheidungen nicht unbemerkt zu widersprechen.
- `agents/orchestrator.py`: injiziert `format_adr_summary_for_context()` in den Kontext JEDER
  Teilaufgabe – dieselbe "einmal festgelegt, künftig immer mitgegeben"-Philosophie wie die
  bestehende Projekt-Konstitution und Lauf-Historie. Leer für Projekte ohne bisherige ADRs
  (kein unnötiger Prompt-Text für die Mehrheit der Läufe).
- `interface/cli.py`: neues `/adr [projekt]` zeigt alle dokumentierten Entscheidungen eines
  Projekts als Tabelle.
- `core/verifier.py`: veralteten Docstring-Hinweis bei `check_docker_build()` weiter
  präzisiert (verweist jetzt korrekt auf `core/deployment.py`/`/deploy`).
- 27 neue Tests (`test_adr.py`: Schreiben/Nummerierung/Listing inkl. kaputter Dateien und
  Kontext-Kürzung; `test_agent_toolbox.py`: neues Werkzeug inkl. Nur-Lese-Sperre und leerem
  Titel; `test_adr_integration.py`: echte Kontext-Injektion in JEDE Teilaufgabe über einen
  echten Orchestrator-Lauf, analog zu `test_constitution_integration.py`; `test_adr_command.py`:
  `/adr`-Anzeige). Volle Suite (431 Tests) grün, ruff sauber.

---

## 🔀 Merge-Erkennung fürs Backlog

Direkte Lücke aus dem Backlog/Kanban-Eintrag unten: Tickets landeten bei einem geöffneten PR
auf "review" – aber NIE automatisch weiter auf "done", selbst wenn der PR längst gemerged
wurde. Das Board driftete dadurch zwangsläufig vom echten GitHub-Zustand auseinander.

- `agents/github_agent.py`: neue `get_pr_status(pr_url)` – `gh pr view <url> --json
  state,mergedAt`, liefert `("merged"|"closed"|"open", Detail)` oder `("unknown", ...)` bei
  JEDEM Problem (kein Fehler-Raise – der Aufrufer lässt das Ticket dann unverändert, statt
  einen falschen Status zu erzwingen).
- `core/merge_watcher.py` (neu): `check_merged_tickets()` – prüft jedes Backlog-Ticket im
  Status "review" (die PR-URL steckt bereits im `detail`-Feld, siehe PR-Workflow) gegen den
  echten PR-Status: gemerged → `done`, ohne Merge geschlossen → `blocked` (abgelehnt, braucht
  menschliche Aufmerksamkeit), weiterhin offen → unverändert.
- `core/issue_watcher.py`: `run_issue_poll_cycle()` ruft `check_merged_tickets()` jetzt bei
  JEDEM Zyklus mit auf – kein zusätzlicher Cron-Eintrag nötig, der bereits eingerichtete
  `--check-issues`-Taskplaner-Job (siehe Eintrag unten) übernimmt die Merge-Erkennung gleich
  mit. `main.py` gibt aktualisierte Ticket-IDs in der `--check-issues`-Ausgabe aus.
- `interface/cli.py`: `/backlog` ist jetzt async und zieht Merges per
  `asyncio.to_thread(check_merged_tickets)` VOR der Anzeige nach – für alle, die (noch) keinen
  wiederkehrenden `--check-issues`-Lauf eingerichtet haben, sonst die einzige Stelle, an der
  ein "review"-Ticket je auf "done" gezogen worden wäre.
- `core/verifier.py`: veralteten Docstring-Hinweis bei `check_docker_build()` korrigiert
  ("das würde eine konkrete Ziel-Infrastruktur voraussetzen, die dieses Framework nicht
  kennt" – seit `core/deployment.py` nicht mehr richtig).
- 28 neue Tests (`test_github_agent_issue_methods.py::TestGetPrStatus`: alle
  `gh pr view`-Antwortfälle inkl. Timeout/kaputtes JSON; `test_merge_watcher.py`:
  Status-Übersetzung inkl. "nur review-Tickets werden geprüft"/"kein PR-Link -> übersprungen"/
  "gh nicht bereit -> nichts geprüft"; ein Integrationstest in `test_issue_watcher.py`, dass
  der Poll-Zyklus ein vorbestehendes "review"-Ticket wirklich auf "done" zieht). Volle Suite
  (411 Tests) grün, ruff sauber.

---

## 🚀 Echtes lokales Deployment (Docker Compose, `/deploy`)

Letzter offener Punkt aus der ursprünglichen Gap-Analyse gegen ein echtes Team (siehe
PR-Workflow-Eintrag unten): `core/verifier.py.check_docker_build()` prüfte bislang NUR, ob
ein generiertes Dockerfile überhaupt baut – "das würde eine konkrete Ziel-Infrastruktur
voraussetzen, die dieses Framework nicht kennt" (ursprünglicher Docstring dort). Jetzt kennt
es eine: Docker Compose lokal/self-hosted, der ohne Cloud-Account/API-Token funktionierende
Standardfall (bewusste Nutzerentscheidung gegen ein PaaS-Ziel wie Fly.io/Railway).

- `core/deployment.py` (neu): `deploy_project()` – bevorzugt eine Compose-Datei
  (`docker compose up -d --build`, liest die tatsächlich veröffentlichten Ports danach ECHT
  aus `docker compose ps --format json`, nicht aus der Compose-Datei geraten, da Docker Ports
  dynamisch zuweisen kann), sonst `docker build` + `docker run` mit Port aus einem
  gefundenen `EXPOSE` im Dockerfile. `stop_deployment()` fährt es wieder herunter. Kein
  automatischer Deploy nach Push/Merge – echte Container-Ausführung startet einen laufenden
  Prozess und belegt Ports, verdient dieselbe Bestätigungs-Gate-Philosophie wie `/push`.
- `interface/cli.py`: neue Befehle `/deploy [projekt]` (Vorschau + Bestätigung) und
  `/deploy-stop [projekt]`, fallen ohne Namen auf das per `/load` geladene Projekt zurück.
- `interface/web_dashboard.py`: neuer Deploy-Bereich (Projekt-Dropdown, Deploy/Stoppen), drei
  neue Endpunkte (`GET /api/projects`, `POST /api/deploy(-stop)`, `GET
  /api/deploy-status/<projekt>`) – läuft über denselben Hintergrund-Event-Loop wie die Jobs
  (`asyncio.to_thread`), blockiert den Server also nicht während eines Docker-Builds.
- `config.py`: `DEPLOY_TIMEOUT_SECONDS` (Standard 300s).
- 25 neue Tests (`test_deployment.py`: Compose vs. Dockerfile-Fallback vs. nichts gefunden,
  Port-Ermittlung aus echtem `docker compose ps`/`EXPOSE`, Namens-Sanitisierung;
  `test_deploy_command.py`: CLI-Bestätigungs-Gate; `test_dashboard_deploy.py`: echter
  HTTP-Server-Zyklus bis "done"/"stopped"). Volle Suite (397 Tests) grün, ruff sauber.

---

## 📋 Backlog/Kanban-Board über CLI, Dashboard & Issue-Watcher hinweg

Direkte Folge-Baustelle aus derselben Roadmap: PR-Workflow und Issue-Watcher gaben jeder
Trigger-Quelle einen eigenen, ISOLIERTEN Fortschritts-Begriff – das Web-Dashboard hielt Jobs
nur im Speicher (weg nach Neustart), der Issue-Watcher trackte Fortschritt nur über
GitHub-Labels (nur dort sichtbar), die CLI gar nicht. Kein einziger Befehl zeigte, woran das
Team gerade/zuletzt gearbeitet hat.

- `core/backlog_store.py` (neu): persistente `memory/backlog.json` mit flacher Ticket-Liste
  (`upsert_ticket()`/`list_tickets()`). Realer Fund beim Bauen: `_save_raw()` sortierte
  zunächst nach `updated_at` (Sekundenauflösung) für die Kürzung auf `MAX_TICKETS_KEPT` –
  mehrere Aktualisierungen in derselben Sekunde ließen sich damit nicht mehr eindeutig
  ordnen, ein Test bewies das konkret (das älteste statt das neueste Ticket wurde verdrängt).
  Gefixt: `upsert_ticket()` entfernt ein aktualisiertes Ticket aus seiner alten Position und
  hängt es ans Listenende – Listenreihenfolge IST damit Aktualisierungsreihenfolge, keine
  erneute Zeitstempel-Sortierung nötig.
- `core/issue_watcher.py`: schreibt "in_progress" SOFORT beim Aufgreifen eines Issues (nicht
  erst nach Abschluss – sonst wäre ein noch laufendes Issue auf dem Board unsichtbar) und
  danach den Ausgang (`pr_opened` → "review", alles andere → "blocked").
- `interface/web_dashboard.py`: `enqueue()`/`_execute_job()` spiegeln den Job-Lebenszyklus
  (queued/running/done/error/cancelled) ins Backlog; neuer `GET /api/backlog`-Endpunkt plus
  ein Kanban-Board-Bereich auf der Dashboard-Startseite (Auto-Refresh alle 5s), inkl.
  HTML-Escaping der Ticket-Titel/Details (aus Nutzereingaben/Issue-Titeln, daher potenziell
  fremdgesteuerter Text im `innerHTML`-Rendering).
- `interface/cli.py`: `/backlog` zeigt das Board als Tabelle; `_process_task()` legt beim
  Start ein `in_progress`-Ticket an, `_ask_for_git_push()` finalisiert es beim Abschluss
  (review/done/blocked) – derselbe Mechanismus, den auch der manuelle `/push`-Befehl nutzt.
- 8 neue Tests (`test_backlog_store.py`: 7 Store-Grundfunktionen inkl. der Sortier-Regression;
  `test_issue_watcher.py`: 1 neuer Beweis, dass ein Ticket schon WÄHREND der Bearbeitung als
  "in_progress" sichtbar ist). Zusätzlich Ticket-Status-Assertions in bestehende Tests
  (`test_issue_watcher.py`, `test_web_dashboard.py`) ergänzt. Alle Tests, die
  `_process_task()`/`_ask_for_git_push()` bzw. echte Dashboard-Jobs ausführen, patchen jetzt
  `core.backlog_store.BACKLOG_FILE` gegen ein temporäres Verzeichnis (dasselbe Prinzip wie
  `COST_HISTORY_FILE` in `test_cost_history_integration.py`) – ansonsten hätte JEDER
  Testlauf die echte `memory/backlog.json` mit Test-Tickets verunreinigt (real beim Bauen
  beobachtet: zwei Nachzügler-Testklassen ohne eigenes `setUp` hatten den Patch zunächst
  verpasst). Volle Suite (372 Tests) grün, ruff sauber.

---

## 🎫 Autonome, getriggerte Arbeit: GitHub-Issues als Backlog (`--check-issues`)

Ebenfalls keine Bugfix, sondern die konsequente Fortsetzung der PR-Workflow-Strukturent-
scheidung direkt darüber: der neue PR-Workflow hatte bis hierhin nur EINEN Konsumenten – einen
Menschen an der CLI, der `Confirm.ask()` bestätigt. Ohne getriggerte Arbeit entsteht nie ein
PR, wenn gerade niemand das Tool bedient, genau der Fall, für den ein echtes Team PRs eigentlich
öffnet (auf ein Issue reagieren, ohne dass jemand zusehen muss).

- `agents/github_agent.py`: sechs neue Primitiven für Issue-Interaktion – `list_actionable_issues()`
  (client­seitiger Ausschluss-Filter, da `gh issue list --label` nur UND-Verknüpfung kennt, kein
  NOT; liefert bei JEDEM Fehler eine leere Liste statt zu werfen, ein Poll-Zyklus soll bei einem
  vorübergehenden Problem einfach beim nächsten Mal erneut versuchen), `ensure_label_exists()`
  (best effort, schluckt jeden Fehler bewusst), `add_issue_label()`/`remove_issue_label()`,
  `comment_on_issue()`.
- `core/issue_watcher.py` (neu): `run_issue_poll_cycle()` – EIN Poll-Durchlauf (keine eigene
  Schleife/Sleep, das übernimmt ein externer Cron/Taskplaner/GitHub-Actions-Schedule
  zuverlässiger als ein selbstgebauter Dauer-Scheduler). Sicherheitsmodell bewusst
  konservativer als der interaktive CLI-Pfad, da kein Mensch zur Bestätigung verfügbar ist:
  nur Issues mit explizitem Opt-in-Label (`ISSUE_TRIGGER_LABEL`, Standard `ai-team`) werden
  aufgegriffen; `ISSUE_IN_PROGRESS_LABEL` wird VOR dem Lauf gesetzt (nicht danach), damit ein
  überlappender zweiter Poll-Zyklus dasselbe Issue nicht doppelt aufgreift; ein Secret-Fund
  blockiert HART (kein Push, kein PR – anders als im interaktiven Pfad, wo ein Mensch bewusst
  übersteuern kann); fehlgeschlagene Verifikation blockiert dagegen NICHT hart, sondern öffnet
  den PR trotzdem mit `⚠️ Verifikation nicht bestanden`-Kennzeichnung in Titel/Body, damit ein
  Mensch das beim Review sieht statt bereits geleistete Arbeit stillschweigend zu verwerfen;
  IMMER über einen frischen Feature-Branch + PR (`Closes #<issue-nummer>`), NIE der
  Direct-Push-Fallback des interaktiven Pfads. PR-Link/Blockade-Grund/Fehler landen als
  Issue-Kommentar – die einzige Rückmeldung ohne CLI/Dashboard-Ansicht.
- `config.py`: `ISSUE_TRIGGER_LABEL`/`ISSUE_IN_PROGRESS_LABEL`/`ISSUE_DONE_LABEL`/
  `ISSUE_BLOCKED_LABEL` sowie `ISSUE_POLL_MAX_PER_CYCLE` (Standard `1` – ein einzelner
  Cron-Tick nach längerer Pause soll nicht gleich eine ganze Batch teurer Läufe lostreten).
- `main.py`: neuer `--check-issues`-Einstiegspunkt, läuft EINEN Poll-Zyklus und beendet sich
  wieder (kein Dauerbetrieb).
- 21 neue Tests (`test_github_agent_issue_methods.py`: die sechs neuen Primitiven inkl. aller
  Fehlerpfade; `test_issue_watcher.py`: vollständige Orchestrierung – Happy Path inkl.
  Label-Reihenfolge, keine Dateiänderung, Secret-Blockade, fehlgeschlagene Verifikation
  öffnet trotzdem den PR, PR-Erstellung schlägt fehl, Orchestrator wirft eine Exception,
  `max_issues`-Limit). Volle Suite (364 Tests) grün, ruff sauber.
- `scripts/run_issue_watcher.ps1` (neu) + Windows-Taskplaner-Eintrag: ruft `--check-issues`
  wiederkehrend auf (Standard alle 15 Min) und protokolliert nach `logs/issue_watcher.log`
  (nicht versioniert). Realer Fund beim Einrichten: PowerShell 5.1s Redirect-Operatoren
  (`*>>`) schreiben Konsolenausgaben standardmäßig als UTF-16LE, was main.py's UTF-8-Fix
  (Emojis/Umlaute) im Log unlesbar gemacht hätte – behoben über `[Console]::OutputEncoding`
  VOR dem Python-Aufruf plus `Out-File -Encoding utf8` beim Schreiben. Bewusst als lokaler
  Taskplaner-Eintrag statt einer Cloud-Routine (z.B. Claude Codes `/schedule`) gelöst: eine
  Cloud-Session hat keinen Zugriff auf lokale `.env`-Secrets/die lokale `gh`-Anmeldung und
  müsste entweder eigene API-Keys in der Cloud-Umgebung hinterlegen oder die Arbeit mit
  cloud-eigenen Tools statt dem eigenen Multi-Agent-Team erledigen.

---

## 🔀 PR-Workflow: Feature-Branch + Pull Request statt Direct-Push auf den Hauptbranch

Kein Bugfix aus einem Testlauf, sondern eine bewusste Strukturentscheidung aus einer
Gap-Analyse gegen ein echtes, professionelles Team: `github_agent.commit()`/`push()`
schrieben bisher IMMER direkt auf den gerade ausgecheckten Branch – bei einem
frischen/geladenen Projekt i.d.R. `main`. Ein echtes Team committet nicht direkt auf den
Hauptbranch, sondern legt pro Aufgabe einen Feature-Branch an, öffnet einen Pull Request
und lässt Merge erst nach grüner CI/Freigabe zu.

- `agents/github_agent.py`: vier neue Methoden – `build_feature_branch_name()` (Slug der
  Aufgabe + kurzes UUID-Suffix, dieselbe Namenskonvention wie die isolierten
  Selbstverbesserungs-Worktrees in `core/git_isolation.py`, dort dafür jetzt als
  `slugify()` public statt `_slugify()` – ein zweites Mal dieselbe Logik zu duplizieren
  hätte dem Token-Effizienz-Grundsatz widersprochen), `create_branch()`, `checkout()`
  (zurück auf einen bestehenden Branch) und `gh_ready()`/`create_pull_request()` (reine
  `gh`-CLI-Fähigkeitsprüfung bzw. `gh pr create`-Aufruf, wirft nie eine Exception – ein
  fehlgeschlagener PR-Aufruf soll den bereits gepushten Branch nicht verwerfen).
- `interface/cli.py._ask_for_git_push()`: entscheidet vor dem Bestätigungs-Dialog, ob der
  PR-Workflow greift – NUR wenn der aktuelle Branch einer der neuen
  `config.GIT_PROTECTED_BRANCHES` (Standard: `main,master`) ist UND `gh_ready()` True
  liefert. Ist bereits ein Feature-/Worktree-Branch aktiv, fehlt die `gh`-CLI, fehlt ein
  GitHub-Remote, oder schlägt `create_branch()` fehl, fällt der Ablauf automatisch auf den
  bisherigen Direct-Push zurück (Graceful Degradation statt Blockade) – der
  Vorschau-Dialog zeigt die gewählte Strategie vorab an, kein blindes Ja/Nein. Nach
  erfolgreicher PR-Erstellung wechselt der Agent lokal wieder auf den ursprünglichen
  Hauptbranch zurück, damit die nächste Aufgabe wieder von einem sauberen Stand aus einen
  neuen Feature-Branch anlegt statt unbemerkt auf demselben Feature-Branch weiterzuarbeiten.
  `ENABLE_PR_WORKFLOW=false` stellt das alte Verhalten vollständig wieder her.
- 14 neue Tests (`tests/test_pr_workflow.py`): Branch-Operationen gegen ein echtes lokales
  Git-Repo (kein Mock, wie schon bei `push()` in `test_github_agent_push.py`), `gh pr
  create` über `subprocess.run` gemockt (in der CI-Umgebung nicht installiert), die
  CLI-Entscheidungslogik (Hauptbranch+gh-ready -> PR-Workflow, Feature-Branch bereits aktiv
  -> Direct-Push, `gh` nicht bereit -> Direct-Push, Branch-Anlage schlägt fehl ->
  Direct-Push-Fallback) sowie ein voller End-to-End-Beweis gegen ein echtes Repo (Branch
  wird wirklich auf den Remote gepusht, PR bekommt den echten Branch-Namen als `head`,
  danach echter Rückwechsel auf `main`). Vier bestehende Push-Gate-Tests
  (`test_cli_push_gate.py`, `test_push_gate_verification_warning.py`,
  `test_commit_message_summary.py`, `test_secret_scan_before_push.py`) fixieren
  `gh_ready.return_value = False`, da sie den Direct-Push-Pfad testen, nicht den neuen
  PR-Workflow. Volle Suite (347 Tests) grün, ruff sauber.

---

## 🛠️ Zwei Resilienz-Fixes im agentischen Werkzeug-Loop (aus demselben Testlauf)

Derselbe echte End-to-End-Testlauf (siehe Eintrag unten) deckte zwei weitere, unabhängige
Probleme im Werkzeug-Loop auf, die beide den `dev_lead`/`qa_lead` in genau diesem Lauf trafen:

1. **Halluzinierter, nicht deklarierter Werkzeug-Aufruf:** Groq (der Fallback für
   HEAVY-Rollen ohne `ANTHROPIC_API_KEY`) lehnte einen rein lesenden Konsolidierungs-Aufruf
   (`tools_read_only=True`, also KEIN `write_file` im deklarierten Tool-Set) hart mit `400`
   ab, weil das Modell selbst trotzdem versuchte, `write_file` aufzurufen – der Request war
   korrekt, nur die Modell-Ausgabe nicht. Der komplette Fachbereichsbericht ging verloren.
   `agents/base_agent.py`: `_run_agentic_loop()` erkennt diese konkrete Fehler-Signatur jetzt
   (`tool_use_failed` / `which was not in request.tools`) und unternimmt GENAU EINEN Retry
   mit explizitem Korrektur-Hinweis, statt die ganze Aufgabe zu verwerfen. Bewusst NICHT
   jede Exception abgefangen – echte Rate-Limit-/Auth-Fehler haben bereits eigene,
   spezifischere Behandlung in `core/llm_factory.py` und sollen dort bleiben.
2. **Letzte Iteration verschwendet:** Auf der letzten erlaubten Iteration durfte das Modell
   bisher weiterhin frei zwischen Werkzeug-Aufruf und Text wählen – entschied es sich
   nochmal für ein Werkzeug (real beobachtet bei ZWEI Fachbereichs-Teamleiter-Aufrufen in
   einem einzigen Lauf), wurde dieser Aufruf VERWORFEN (die Schleife bricht ab, bevor er
   ausgeführt wird) und der Nutzer sah nur "Maximale Werkzeug-Iterationen erreicht" statt
   einer echten Zusammenfassung. `_run_agentic_loop()` fügt vor der letzten Iteration jetzt
   eine explizite "Dies ist deine letzte Gelegenheit"-Aufforderung ein. Zusätzlich:
   `agents/orchestrator.py` hebt die Iterations-Caps für Fachbereichs-Delegation (3→4) und
   -Konsolidierung (4→5) moderat an – weiterhin deutlich unter dem vollen
   Entwickler-Budget, da es sich um rein lesende Aufrufe handelt.
3. 7 neue Tests (Retry-Mechanik inkl. Ausschluss unbekannter Exceptions und der
   Randbedingung "kein Retry auf der letzten Iteration"; explizite Stop-Aufforderung inkl.
   Randfall `max_tool_iterations=1`); volle Suite (337 Tests) grün, ruff sauber.

---

## 🪞 Finale Antwort zeigt jetzt echten statt vom LLM erfundenen Code

Erster echter End-to-End-Testlauf dieser Session (reale FastAPI-Notizen-API, echte
LLM-Aufrufe, keinerlei Mocking) deckte einen konkreten Vertrauensbruch auf: `app/main.py`
auf der Platte nutzte UUID-Strings als Notiz-IDs – die finale, dem Nutzer angezeigte
LLM-Synthese zeigte zwei UNTERSCHIEDLICHE Code-Versionen, beide mit Integer-IDs, keine davon
identisch mit der echten Datei. Die echte Datei und die echten Tests waren selbst korrekt
(alle 5 Tests bestanden) – nur die Anzeige log. Wer nur den Chat-Output liest statt die
Dateien zu prüfen, hätte einen falschen Eindruck vom tatsächlich gebauten Code bekommen.

- `core/result_aggregator.py`: `SYNTHESIZE_SYSTEM_PROMPT` weist das Modell jetzt explizit an,
  KEINEN vollständigen Quellcode mehr zu reproduzieren – nur Architektur, Entscheidungen und
  Zusammenspiel der Komponenten zu beschreiben, Dateien nur beim Namen zu referenzieren.
- `agents/orchestrator.py`: neue `_build_real_files_section()` – liest die tatsächlich
  geschriebenen Dateien (aus `file_owners`, bereits vorhandene Datei-Besitzer-Zuordnung)
  DIREKT von der Platte (kein LLM-Aufruf, daher immer exakt korrekt) und hängt sie als
  eigenen, deterministischen Abschnitt an die finale Antwort an – Ground Truth statt
  LLM-Erinnerung. Gedeckelt wie die bestehende Ergebnis-Formatierung (pro Datei und
  insgesamt), damit große Projekte die Antwort nicht unbegrenzt aufblähen.
- Nebeneffekt: reduziert auch den Tokenverbrauch der Synthese, da das Modell keinen
  potenziell großen Code mehr aus dem Gedächtnis regenerieren muss.
- 9 neue Tests (`_build_real_files_section()` inkl. Kürzung/Binärdateien/fehlender Dateien;
  ein echter End-to-End-Beweis, dass eine bewusst ERFUNDENE Synthese-Behauptung den echten
  Code trotzdem nicht verdrängt); volle Suite (330 Tests) grün, ruff sauber.

---

## 🔀 Echte parallele Dashboard-Jobs

Jobs liefen im Dashboard bisher SERIELL in einem einzigen Hintergrund-Worker – ein zweiter
Job musste komplett warten, selbst wenn beide unabhängige Projekte betrafen und nichts
miteinander zu tun hatten.

- `interface/web_dashboard.py`: `DashboardServer` läuft jetzt in EINEM persistenten
  asyncio-Event-Loop (ein Hintergrund-Thread), in dem bis zu
  `config.DASHBOARD_MAX_CONCURRENT_JOBS` (Standard: `2`, konservativ gegen kostenlose
  Provider-Rate-Limits) Jobs gleichzeitig laufen können. Bewusst NICHT über mehrere echte
  OS-Threads – das hätte eine echte Thread-Sicherheits-Absicherung aller geteilten globalen
  Zustände erfordert (`token_guard`, `agent_knowledge_base`,
  `memory/cost_history.json`, …). Ein einzelner Event-Loop garantiert dagegen, dass jede
  synchrone Operation (z. B. ein Dict-Update) ungestört zu Ende läuft, bevor die nächste
  Coroutine an die Reihe kommt.
- Jeder Job bekommt eine FRISCHE, isolierte `Orchestrator`-Instanz statt der bisher einen
  geteilten – das war der eigentliche Grund für die frühere Serialisierung (eine geteilte
  `ConversationHistory` hätte sich bei gleichzeitigen Jobs sonst vermischt). Alle Jobs teilen
  sich weiterhin denselben `workspace/`-Ordner.
- Cross-Thread-Zustellung neuer Jobs vom HTTP-Handler-Thread in den Event-Loop-Thread über
  `loop.call_soon_threadsafe()` (Standardmuster für genau diesen Fall – `asyncio.Queue` ist
  selbst nicht thread-safe).
- 20 neue Tests, davon 3 als echter, deterministischer Beweis (kein Timing-Raten): zwei Jobs
  werden nachweislich GLEICHZEITIG "running", ein dritter Job wartet nachweislich bei
  erreichtem Limit, und zwei parallele Jobs bekommen nachweislich zwei verschiedene
  `ConversationHistory`-Objekte. Bestehende Dashboard-Tests wurden auf klassen- statt
  instanzweites Mocking von `Orchestrator.process()` umgestellt (patcht dadurch JEDE frisch
  erzeugte Instanz). Volle Suite (321 Tests) grün, ruff sauber; ein echter
  (nicht gemockter) Server-Start im Anschluss zusätzlich manuell verifiziert.

---

## 🗓️ Kumulierte Kosten-Historie über ALLE Sitzungen hinweg

`core/token_guard.py` ist eine reine In-Memory-Instanz – bei jedem Neustart (neues
CLI-Terminal, neuer Dashboard-Prozess) beginnt der von `/tokens` gezeigte Tokenverbrauch
wieder bei Null. Es gab keinen Weg zu sehen, wie viele Tokens das Team INSGESAMT seit Beginn
der Nutzung verbraucht hat – der eigentlich relevante Wert für die Kosteneinschätzung eines
wiederkehrend genutzten Teams.

- `memory/cost_history.py` (neu): schreibt/liest eine persistente `memory/cost_history.json`
  – Pro-Modell-Aufschlüsselung (Aufrufe, Prompt-/Completion-/Gesamt-Tokens) über die gesamte
  Nutzungsgeschichte. Bewusst NUR echte Tokenzahlen, kein geschätzter $-Betrag: echte Preise
  unterscheiden sich pro Modell/Provider und ändern sich laufend – ein erfundener $-Wert ohne
  verlässliche, aktuelle Preistabelle wäre eine Falschaussage (dieselbe "echt statt
  geraten"-Philosophie wie beim Dependency-Audit/Docker-Build).
- **Kritischer Fund währenddessen:** `core/token_guard.py.get_summary()["models"]` lieferte
  über `vars(v)` eine LIVE-Referenz auf den internen Zustand statt einer Kopie – ein
  Aufrufer, der sich einen frühen Stand für eine spätere Differenzberechnung merkt (genau der
  neue Anwendungsfall hier), sah durch nachfolgende `record_usage()`-Aufrufe unbemerkt den
  SPÄTEREN Stand, weil beide Referenzen auf dasselbe Dict zeigten – jede berechnete Differenz
  wäre fälschlich `0` gewesen. Gefixt mit einer echten flachen Kopie (`dict(vars(v))`).
- `agents/orchestrator.py`: `process()` berechnet am Laufende den Pro-Modell-DELTA seit
  Laufbeginn (`_model_usage_deltas()`, dasselbe Prinzip wie das bestehende
  `_tokens_used_since()` fürs Budget) und schreibt ihn additiv in die Historie – ein zweiter
  Lauf in derselben Sitzung zählt den ersten dadurch nicht erneut mit.
- `core/quota_estimator.py`: `/tokens` zeigt jetzt zusätzlich zur aktuellen Sitzung einen
  "Kumulierter Verbrauch"-Abschnitt mit dem Gesamtwert über alle bisher aufgezeichneten
  Läufe, sortiert nach Modell.
- 19 neue Tests (Kosten-Historie: Aufzeichnen/Akkumulieren/Persistenz/Edge-Cases; die
  Live-Referenz-Regression direkt an `TokenGuard`; Orchestrator-Integration inkl. echtem
  Zwei-Läufe-Beweis, dass NICHT doppelt gezählt wird; `/tokens`-Anzeige); volle Suite
  (318 Tests) grün, ruff sauber.

---

## 📜 Projekt-Konstitution: feste Tech-Stack-Präferenzen über Sitzungen hinweg

`project_slug`/Architektur/Tech-Stack werden pro Lauf frisch vom Modell geraten – selbst am
selben Projekt kann Lauf 2 eine andere Sprache/Framework wählen als Lauf 1, wenn die
Nutzeranfrage das nicht jedes Mal explizit wiederholt. `core/project_status.py` gab dem Team
bereits Kontinuität über die LAUF-HISTORIE; jetzt gibt `core/project_constitution.py` dem
NUTZER die Kontrolle über feste Präferenzen.

- `core/project_constitution.py` (neu): schreibt/liest eine einfache, von Hand
  lesbare/editierbare `.ai-team.toml`-Datei direkt im Projektverzeichnis (bewusst NICHT
  gitignored, wie `.ai_team_status.json`) mit sechs Feldern (Sprache, Framework,
  Test-Framework, Code-Stil, Deployment-Ziel, weitere Hinweise). Nutzt stdlib `tomllib` zum
  Lesen (Python 3.11+, ohnehin Mindestversion); ein minimaler Hand-Writer fürs Schreiben
  spart eine zusätzliche Abhängigkeit, da das Schema aus flachen String-Feldern besteht.
- `interface/cli.py`: neues `/constitution [projekt]` – zeigt die aktuellen Werte, fragt ob
  bearbeitet werden soll, geht dann Feld für Feld durch (Enter = behalten, `-` = löschen).
  Ohne Projektangabe wird das per `/load` geladene Projekt verwendet.
- `agents/orchestrator.py`: `process()` injiziert die Konstitution (falls vorhanden) in den
  Kontext JEDER Teilaufgabe, genau wie die bereits bestehende Lauf-Historie – leer für
  Projekte ohne Konstitution, kein unnötiger Prompt-Text für die Mehrheit der Projekte.
- 17 neue Tests (Schreiben/Lesen inkl. Escaping von Anführungszeichen/Backslashes,
  beschädigte Datei crasht nicht, CLI-Bearbeitungsfluss inkl. Feld-Löschen via `-`,
  Orchestrator-Integration bis in den tatsächlichen Agenten-Kontext); volle Suite
  (302 Tests) grün, ruff sauber.

---

## 🧠 Editierbare Agent-Learnings: `/learnings` & `/delete-learning`

`memory/agent_learnings.json` war bisher eine reine Black Box – jede vom `agent_trainer`
per LLM-Aufruf automatisch gelernte Regel floss ab sofort bei JEDEM künftigen Aufruf des
betroffenen Agenten in dessen System-Prompt ein (siehe `get_augmented_prompt()`), ohne dass
der Mensch je einsehen oder eine falsche/überholte Regel gezielt entfernen konnte – sie wäre
erst nach 5 neueren Regeln automatisch verdrängt worden.

- `memory/agent_knowledge_base.py`: neue `get_all_learnings()` (Kopie aller Regeln aller
  Agenten, für Anzeigezwecke) und `remove_learning(agent_id, index)` (entfernt eine
  einzelne Regel anhand ihres 1-basierten Index, räumt den Agenten-Eintrag komplett auf,
  wenn keine Regel mehr übrig ist).
- `interface/cli.py`: `/learnings` zeigt alle gelernten Regeln aller Agenten nummeriert in
  einer Tabelle; `/delete-learning <agent> <nr>` entfernt eine einzelne Regel – IRREVERSIBEL,
  mit derselben Vorschau-+Bestätigungs-Logik wie `/delete-project` und das Git-Push-Gate.
  Ungültige Eingaben (unbekannter Agent, Nummer außerhalb des Bereichs, keine Zahl) geben
  eine klare Fehlermeldung statt eines Absturzes.
- 18 neue Tests (Wissensbasis-Seite: Hinzufügen/Entfernen/Persistenz/Edge-Cases; CLI-Seite:
  Anzeige, Bestätigung annehmen/ablehnen, alle ungültigen Eingaben); volle Suite
  (285 Tests) grün, ruff sauber.

---

## ⏹️ Abbruch/Pause eines laufenden Runs (Strg+C in der CLI, Cancel-Button im Dashboard)

Bisher gab es keinen Weg, einen sichtbar falsch laufenden Lauf gezielt zu stoppen – nur das
komplette Programm zu killen (CLI: Strg+C während eines laufenden Teams stürzte mit einem
rohen `KeyboardInterrupt`-Traceback ab, da `interface/cli.py` das nur am Eingabe-Prompt
abfing) bzw. die Browser-Seite wegzuklicken, während der Dashboard-Job im Hintergrund-Worker
unbeeinflusst weiterlief.

- `agents/orchestrator.py`: `process()` akzeptiert jetzt einen optionalen
  `cancel_requested`-Callback – wird an DENSELBEN Prüfpunkten wie das bestehende
  `MAX_RUN_TOKENS`-Budget abgefragt (vor jeder Fachbereichs-Phase, vor jedem Verifikations-/
  Fixversuch): dieselbe Graceful-Degradation (verbleibende Arbeit überspringen, bereits
  Erarbeitetes trotzdem synthetisieren und ausliefern), nur mit einem manuellen statt einem
  Budget-Grund im finalen Status/Protokoll und in der persistenten Lauf-Historie
  (`core/project_status.py`, neues `cancelled`-Feld – eigenes Icon `⏹️`, nicht mit `🚫`
  Budget-Abbruch verwechselbar).
- `interface/cli.py`: **Erstes Strg+C** setzt nur ein Flag (kooperativer Abbruch – der
  laufende Werkzeug-Loop/Subprozess wird nicht mitten in einer Datei-Operation abgewürgt).
  **Zweites Strg+C** während desselben, bereits abbrechenden Laufs erzwingt den echten
  Programm-Abbruch als Sicherheitsventil für einen wirklich hängenden Lauf – sauber
  abgefangen (kein roher Traceback), zurück zum Prompt statt Programmabsturz. Der
  ursprüngliche SIGINT-Handler wird danach in JEDEM Fall wiederhergestellt.
- `interface/web_dashboard.py`: neuer `POST /api/cancel/<job_id>`-Endpunkt + "⏹️ Lauf
  abbrechen"-Button im UI – markiert einen Job zum Abbruch; ein noch wartender Job wird
  direkt als abgebrochen markiert, ohne je zu starten (serieller Worker, siehe bestehende
  Design-Entscheidung).
- Bekannte Grenze, bewusst dokumentiert statt verschwiegen: ein bereits per
  `asyncio.to_thread()` gestarteter Subprozess (pip/npm install, Testlauf) lässt sich nicht
  sofort beenden – er läuft im Hintergrund zu Ende, während der sichtbare Lauf bereits als
  abgebrochen gilt (gilt grundsätzlich für jedes Python-CLI-Tool, das Subprozesse startet).
- 17 neue Tests (Orchestrator-Prüfpunkte inkl. "begonnene Phase läuft noch fertig, erst die
  nächste wird übersprungen", CLI-Signal-Handler-Mechanik inkl. Wiederherstellung nach
  Erfolg/Fehler, echter Dashboard-HTTP-Zyklus für alle drei Fälle queued/running/bereits
  fertig); volle Suite (270 Tests) grün, ruff sauber.

---

## 📋 Plan-Freigabe-Gate: den Aufgaben-Umfang VOR Tokenverbrauch sehen & bestätigen

Bisher sah der Nutzer den von `TaskManager.decompose()` erstellten Plan (welche Spezialisten,
welche Teilaufgabe) erst im FERTIGEN Ergebnis – bei einer größeren, vom Modell großzügig
interpretierten Anfrage gab es keine Möglichkeit, vor dem eigentlichen, kostenpflichtigen
Lauf gegenzusteuern. Dieselbe Rückfrage-Philosophie wie bei unklaren Anforderungen (siehe
oben), jetzt für den Fall "Anforderung ist klar, aber der abgeleitete Umfang könnte größer
sein, als beabsichtigt".

- `agents/orchestrator.py`: `process()` akzeptiert jetzt einen optionalen
  `plan_confirmation_callback` – wird NACH der Zerlegung, aber VOR jeder Ausführung
  aufgerufen (kein Agent hat zu diesem Zeitpunkt auch nur einen Token verbraucht), NUR wenn
  der Plan mindestens `PLAN_CONFIRMATION_MIN_TASKS` Teilaufgaben umfasst (Standard: `3`) –
  kleine, klar umrissene Aufgaben (z. B. "aktualisiere die README") laufen weiterhin ohne
  Rückfrage durch. Lehnt der Callback ab, bricht der Lauf sauber ab, exakt wie bei der
  bestehenden "leere agent_tasks"-Behandlung.
- `interface/cli.py`: zeigt bei Bedarf eine nach Fachbereich gruppierte Vorschau (genau die
  Spezialisten/Teilaufgaben, die gleich wirklich beauftragt würden – keine Schätzung) und
  lässt sie bestätigen. `Confirm.ask()` ist ein blockierender Terminal-Prompt – während die
  Live-Statusanzeige aktiv rendert, würde sich das mit deren Auto-Refresh-Thread beißen;
  `live.stop()`/`live.start()` pausiert die Anzeige exakt für die Dauer der Abfrage.
- Bewusst NUR CLI-seitig verdrahtet (`config.ENABLE_PLAN_CONFIRMATION`, Standard aktiv):
  Dashboard/MCP-Aufrufe reichen keinen Callback durch und bleiben dadurch unverändert
  nicht-interaktiv (kein Caller-Bruch für nicht-interaktive Integrationen).
- 12 neue Tests (Gate-Schwelle inkl. Callback wird bei kleinen Plänen NIE gefragt, Ablehnung
  stoppt nachweislich VOR jeder Fachbereichs-Ausführung, Zustimmung läuft normal weiter, CLI-
  Gruppierung nach Fachbereich, `ENABLE_PLAN_CONFIRMATION`-Umschaltung); volle Suite
  (251 Tests) grün, ruff sauber.

---

## 🎨 Echtes Lint-/Type-Check-Gate für generierten Code

`ruff.toml` lief bisher AUSSCHLIESSLICH gegen den Framework-Code selbst – `workspace/` ist
dort bewusst ausgeschlossen (richtig für den eigenen Lint-Job). Dadurch gab es für den vom
Team tatsächlich AUSGELIEFERTEN Code aber gar keine automatische Stil-/Fehlerprüfung.

- `core/verifier.py`: neue `check_lint()` – Python wird IMMER geprüft (`ruff check
  --isolated`), wenn `.py`-Dateien existieren; braucht keine Projekt-Konfiguration und läuft
  bewusst isoliert von der eigenen `ruff.toml` des Frameworks (die für den Framework-Code
  kuratierten Regeln, z. B. die E501-Ausnahme für deutschsprachige Docstrings, sollen einem
  beliebigen generierten Projekt nicht aufgezwungen werden). ESLint/`tsc` laufen dagegen NUR,
  wenn das jeweilige Node-Projekt sie selbst bereits als Dev-Abhängigkeit UND Konfiguration
  mitbringt (`.eslintrc*`/`eslint.config.*` bzw. `tsconfig.json` + lokal in `node_modules/
  .bin` installiert) – keine ungefragte Meinungsänderung an einem Projekt, das sich nie für
  diese Tools entschieden hat. Bei ESLint zählen nur echte Fehler (severity 2), keine
  Warnungen, als "nicht bestanden".
- Wie bei Docker-Build/Dependency-Audit gilt: fehlendes Tool oder ein technischer
  Fehlschlag des Lint-Laufs selbst sind KEIN Fehler, nur nicht prüfbar (`attempted=False`)
  und werden NIEMALS fälschlich als "keine Probleme" gemeldet.
- `agents/orchestrator.py`: `_run_verification_loop()` ruft den Scan nach dem Dependency-
  Audit auf (übersprungen bei Budget-Abbruch) und zeigt Funde (Datei, Zeile, Regel) im
  Verifikations-Protokoll – rein informativ, beeinflusst `verification_ok` nicht.
- 17 neue Tests (Parser gegen wortgetreue echte `ruff`-/ESLint-JSON- bzw. `tsc`-Text-
  Ausschnitte inkl. der Pfad-Relativierung, alle Skip-Fälle, Orchestrator-Integration);
  zusätzlich ein echter, ungemockter End-to-End-Nachweis gegen echten fehlerhaften und
  sauberen Python-Code während der Entwicklung. Volle Suite (239 Tests) grün, ruff sauber.

---

## 🔓 Echter Dependency-Vulnerability-Scan statt LLM-Einschätzung

Der `security`-Agent konnte Abhängigkeits-Risiken bisher nur "plausibel" per LLM einschätzen
– ohne echten Abgleich, ob eine gepinnte Paketversion in `requirements.txt`/`package.json`
tatsächlich bekannte CVEs hat. Dieselbe "echt prüfen statt raten"-Philosophie wie bei der
Docker-Build-Prüfung, jetzt für Sicherheits-Advisories.

- `core/verifier.py`: neue `check_dependency_vulnerabilities()` – führt `pip-audit -r
  requirements.txt` (braucht keine lokale Paket-Installation, löst Versionen direkt aus der
  Datei auf) bzw. `npm audit` (für dieselben Node-Projekte wie die npm-Verifikation, inkl.
  der dort bereits angelegten `package-lock.json`) gegen die öffentliche PyPI-/OSV- bzw.
  npm-Advisory-Datenbank aus. Ein Projekt kann mehrere Stacks/Node-Unterprojekte haben,
  daher eine Liste von Berichten.
- **Technischer Fehlschlag ≠ "sauber":** fehlt das Scan-Tool, fehlt eine `package-lock.json`,
  oder schlägt der Scan selbst fehl (z. B. keine Netzwerkverbindung zur Advisory-Datenbank),
  ist das wie beim Docker-Build KEIN Fehler, nur nicht prüfbar (`attempted=False`) – und
  wird NIEMALS fälschlich als "keine Schwachstellen gefunden" ausgegeben. `npm audit`s
  `{"error": {...}}`-Antwort (z. B. bei nicht erreichbarer Registry) wird dafür explizit
  erkannt statt als leeres, sauberes Ergebnis fehlinterpretiert zu werden.
- `agents/orchestrator.py`: `_run_verification_loop()` ruft den Scan nach der Docker-Build-
  Prüfung auf (übersprungen bei Budget-Abbruch) und macht Funde (Paket, Version, Advisory-ID)
  im Verifikations-Protokoll sichtbar – rein informativ, beeinflusst `verification_ok` nicht
  (ein Fund hat oft keine unmittelbare Ein-Zeilen-Lösung, anders als ein Testfehler).
- `requirements-dev.txt`: `pip-audit` als neue Dev-Abhängigkeit (wie `ruff`) – ohne
  installiertes `pip-audit` wird der Python-Scan pro Projekt übersprungen, kein Fehler.
- 14 neue Tests (Parser gegen wortgetreue echte `pip-audit`-/`npm audit`-JSON-Ausschnitte,
  alle "nicht prüfbar statt falsch sauber"-Fälle, Orchestrator-Integration); zusätzlich ein
  echter, ungemockter End-to-End-Nachweis gegen ein absichtlich verwundbares Paket
  (`urllib3==1.24.1`, 14 echte gefundene CVEs) während der Entwicklung. Volle Suite
  (222 Tests) grün, ruff sauber.

---

## 🧪 Echte npm-Verifikation für Frontend/Node-Projekte

`core/verifier.py` verifizierte bisher AUSSCHLIESSLICH Python-Code (`test_*.py`) – ein vom
`frontend`/`mobile`-Agenten erzeugtes JS/TS-Projekt lief nie durch einen echten `npm test`.
"Keine Tests gefunden" tauchte selbst dann auf, wenn eine vollständige, echt ausführbare
npm-Testsuite existierte – generierter Frontend-Code wurde also faktisch nie verifiziert.

- `core/verifier.py`: `ensure_environment()`/`run_tests()` erkennen jetzt zusätzlich jedes
  `package.json` mit einem `"test"`-Skript (node_modules ausgeschlossen) und installieren
  per `npm ci` (bei vorhandener `package-lock.json`, deterministisch) bzw. `npm install`,
  dann echtes `npm test`. Ein Projekt gilt insgesamt nur als bestanden, wenn ALLE gefundenen
  Stacks (Python UND/ODER Node) bestehen – ein grüner Backend-Test darf ein rotes Frontend
  nicht überdecken. Fehlschläge werden best-effort geparst (Jest/Vitest-`FAIL <datei>` +
  Stack-Trace-Pfade), mit demselben generischen Fallback wie bei unparsbarer Python-Ausgabe,
  falls kein bekanntes Muster erkannt wird – kein Anspruch, jedes Node-Test-Framework exakt
  zu parsen.
- **Kritischer Fund währenddessen:** `core/code_sandbox.py.run_command()` scheiterte unter
  Windows für JEDEN echten `npm`-Aufruf mit `WinError 2` ("Datei nicht gefunden") – `npm`
  (wie `npx`/`yarn`/`pnpm`) ist dort ein `.cmd`-Batch-Wrapper statt einer echten `.exe`, und
  `subprocess.run([...], shell=False)` kann `.cmd`/`.bat`-Dateien nicht direkt starten, auch
  wenn der Befehl im PATH steht. `run_command()` löst `command[0]` jetzt vorab über
  `shutil.which()` auf den tatsächlich ausführbaren Pfad auf (unter Linux/macOS ein No-op,
  da dort bereits reguläre Binärpfade zurückkommen) – betrifft nicht nur die neue
  npm-Verifikation, sondern jeden künftigen `.cmd`/`.bat`-basierten Kommandoaufruf über
  diesen Pfad.
- 21 neue Tests (echte, abhängigkeitsfreie `npm install`/`npm test`-Läufe – offline-sicher,
  kein Netzwerkzugriff nötig; `npm ci`-Kommandowahl gemockt analog zu den bestehenden
  Docker-Build-Tests; ein echter `npm --version`-Regressionstest für den Windows-`.cmd`-Fund);
  volle Suite (208 Tests) grün, ruff sauber.

---

## 🔑 Secret-Scan vor Commit & Push

`agents/github_agent.py.commit()`/`push()` prüften den zu committenden Inhalt bisher nie –
ein Agent, der versehentlich einen echten API-Key, ein Passwort oder einen Private Key in
eine generierte Datei schreibt (z. B. eine Beispiel-`.env`, eine Konfigurationsdatei), hätte
diesen Secret unbemerkt auf ein – möglicherweise öffentliches – GitHub-Repo gepusht.
Dieselbe Prüf-Philosophie wie der bereits bestehende Umgebungsvariablen-Filter für
Subprozesse (`core/code_sandbox.py`), nur für den umgekehrten Fall.

- `core/secret_scanner.py` (neu): regelbasierter, rein lokaler Scan (kein Netzwerk, kein
  LLM-Aufruf) über `scan_diff()` – erkennt bekannte Provider-Key-Formate (AWS, Google,
  GitHub, Slack, Stripe, Anthropic, private PEM-Keys) sowie generische
  `key/secret/token/password = "..."`-Zuweisungen in neu HINZUGEFÜGTEN Diff-Zeilen.
  Offensichtliche Platzhalter (`"changeme"`, `"your-api-key-here"`, Doku-Beispielwerte wie
  AWS' eigenes `AKIAIOSFODNN7EXAMPLE`) werden bewusst nicht gemeldet, um bei einem echten
  Fund ernst genommen zu werden. Gefundene Werte werden vor der Anzeige geschwärzt
  (`***REDACTED***`) – nie der volle Secret-Wert im Terminal/Log.
- `agents/github_agent.py`: neue `scan_for_secrets()` – staged (git add -A) und durchsucht
  den vollständigen `git diff --cached` (inkl. neuer, noch nicht getrackter Dateien).
- `interface/cli.py`: `_ask_for_git_push()` zeigt bei einem Fund eine deutliche
  rot umrandete Warnung mit Datei:Zeile, Regel und geschwärztem Ausschnitt sowie eine
  eigene Bestätigungsfrage – blockiert nichts hart (der Mensch kann bewusst trotzdem
  committen/pushen), analog zur bestehenden Verifikations-Warnung.
- 13 neue Tests (Erkennung aller bekannten Muster, Platzhalter-Ausschluss, echtes
  temporäres Git-Repo für `scan_for_secrets()`, CLI-Warn-Gate); volle Suite (195 Tests)
  grün, ruff sauber.

---

## 🐳 Echte Docker-Build-Prüfung (ein Schritt Richtung echtem Deployment)

"Echtes Deployment" im vollen Sinn (Push zu einer konkreten Cloud/einem Server) setzt eine
Ziel-Infrastruktur voraus, die dieses Framework nicht kennt und nicht raten sollte – das
bleibt bewusst außerhalb seines Bereichs. Was sich aber ehrlich prüfen lässt, ohne
irgendeine Zielumgebung anzunehmen: **baut das generierte Dockerfile überhaupt?** Ein
Dockerfile, das nie tatsächlich baut, bringt niemanden näher an ein echtes Ausrollen.

- `core/verifier.py`: neue `ProjectVerifier.check_docker_build()` – führt einen echten
  `docker build -t ... .` aus, WENN ein Dockerfile existiert UND `docker` lokal verfügbar
  ist. Baut niemals `docker run` oder einen echten Push/Deploy aus. Fehlendes Dockerfile
  oder fehlendes Docker sind dabei ausdrücklich KEIN Fehler, nur nicht prüfbar (dasselbe
  Prinzip wie bei "keine Tests gefunden").
- `agents/orchestrator.py`: `_run_verification_loop()` ruft das nach der Testverifikation
  auf und macht Erfolg/Fehlschlag im Verifikations-Protokoll sichtbar – übersprungen bei
  Budget-Abbruch, keine Zusatzzeile, wenn schlicht kein Dockerfile vorhanden ist.
- 7 neue Tests (gemockte `docker`-Aufrufe für `core/verifier.py` + Orchestrator-Integration);
  volle Suite (180 Tests) grün, ruff sauber.

---

## 📜 Projekt-Kontinuität über mehrere Sitzungen hinweg

`memory/conversation_history.py` ist sitzungsgebunden – startet der Nutzer eine neue
Sitzung (neues Terminal), war jeglicher Kontext über ein Projekt bisher weg, selbst bei
erneutem `/load` desselben Projekts. Ein Mensch, der ein Projekt nach Tagen wieder aufmacht,
hat wenigstens ein Commit-Log; das Team hatte bisher nur die rohen Quelldateien, ohne jeden
Hinweis auf offene Punkte (z.B. "Lauf-Budget während der Verifikation erreicht").

- `core/project_status.py` (neu): schreibt eine kompakte, gedeckelte JSON-Historie
  (`.ai_team_status.json`, max. 10 Einträge – dieselbe Deckelungslogik wie
  `memory/agent_knowledge_base.py`) direkt im Projektverzeichnis. Bewusst NICHT gitignored,
  im Unterschied zu `.ai_team_venv`/`.ai_team_rag` – das ist echte, wertvolle
  Projekt-Historie, kein Build-Artefakt, und soll mitversioniert werden.
- `agents/orchestrator.py`: injiziert die letzten 3 Läufe (mit Status-Icon ✅/⚠️/🚫) in den
  Kontext jeder Teilaufgabe – das Team sieht damit sofort, dass der letzte Lauf z.B. am
  Budget abgebrochen wurde, statt das nur aus den Quelldateien zu erraten. Protokolliert am
  Ende jedes Laufs den eigenen Ausgang (Aufgabe, Verifikation, Budget-Abbruch, Dateizahl).
- 9 neue Tests, davon einer als echter End-to-End-Nachweis: zwei GETRENNTE
  Orchestrator-Instanzen (= zwei Sitzungen) arbeiten nacheinander am selben Projekt – die
  zweite sieht die Historie der ersten. Volle Suite (173 Tests) grün, ruff sauber.

---

## 🌳 Worktree-Isolation gilt jetzt für ALLE Läufe, nicht nur Selbstverbesserung

Die bisherige Git-Worktree-Isolation griff nur, wenn das Team am Framework selbst arbeitete.
Dieselbe Gefahr besteht aber bei JEDEM Lauf gegen bereits vorhandenen Inhalt – z.B. ein per
`/load` geladenes bestehendes Projekt.

- `agents/orchestrator.py`: neue `_resolve_project_isolation()` entscheidet einheitlich für
  BEIDE Fälle (per `/load` geladen ODER frisch geratener `project_slug`): isoliert wird
  IMMER, wenn am Zielort bereits echter Inhalt existiert (Framework-Root zählt immer dazu).
  Ein **brandneues, leeres Projekt** hat nichts zu verlieren und wird bewusst weiter direkt
  geschrieben – kein Worktree-Overhead im Alltagsfall "neues Projekt erstellen".
- `core/git_isolation.py`: neue `find_git_root()` (funktioniert auch für noch nicht
  existierende Zielpfade, z.B. ein brandneues Workspace-Projekt, das erst beim nächsten
  existierenden Elternordner ansetzt) und `has_uncommitted_changes()`.
- **Unkommittete Änderungen am Zielort → keine Isolation.** Ein frischer Worktree basiert
  auf dem letzten Commit und würde unkommittete Änderungen unsichtbar machen – in diesem
  Fall wird stattdessen direkt geschrieben, mit klarer Warnung.
- Nur beim Framework-Root selbst führt ein genereller Isolations-Fehlschlag (kein Git-Repo,
  `git` fehlt) weiterhin zum Abbruch statt zu einem Fallback auf direktes Schreiben – dort
  ist das Risiko am größten.
- 9 neue Tests (echte temporäre Git-Repos); volle Suite (164 Tests) grün, ruff sauber.

---

## ❓ Rückfragen bei unklaren Anforderungen statt Raten

Realer Fund: vage Nutzeranfragen ("Ich möchte, dass ihr das Projekt weiter verbessert")
führten bisher dazu, dass der Planer einfach ein thematisch beliebiges Demo-Projekt erfand,
statt nachzufragen – ein erfahrener Senior-Entwickler würde bei einer derart unklaren
Aufgabe zuerst präzisierende Fragen stellen.

- `core/task_manager.py`: `DECOMPOSE_SYSTEM_PROMPT` kennt jetzt `needs_clarification` +
  `clarifying_questions` im JSON-Schema – NUR wenn unterschiedliche vertretbare
  Interpretationen zu grundverschiedenen Ergebnissen führen würden oder eine zwingende
  Angabe komplett fehlt (nicht bei gewöhnlicher Unterspezifikation, die ein erfahrener
  Entwickler selbst sinnvoll entscheiden würde).
- `Orchestrator.process()` zeigt die Rückfragen direkt an, **ohne auch nur einen einzigen
  Agenten zu starten** – kein Tokenverbrauch für einen möglicherweise falschen, geratenen
  Plan. Nutzt dieselbe bereits vorhandene "leere agent_tasks"-Behandlung wie ein
  Provider-Totalausfall, nur mit `❓` statt `⚠️` als Präfix.
- Gleichzeitig: `compliance` ist jetzt ebenso verpflichtend wie `security` bei
  personenbezogenen Daten, unklaren Drittanbieter-Lizenzen oder regulierten Bereichen.
- 4 neue Tests; volle Suite (155 Tests) grün, ruff sauber.

---

## 🚦 Proaktive Rate-Begrenzung gegen Gemini

Die vorherige Runde ließ die Provider-Kette bei Totalerschöpfung kurz warten (REAKTIV,
nachdem das Limit bereits erreicht war). Der eigentliche Auslöser blieb aber unadressiert:
3+-Mitglieder-Fachbereiche schicken über `asyncio.gather` ihre erste Anfrage praktisch
zeitgleich los – ohne Entzerrung stürmen mehrere Agenten gleichzeitig denselben Provider an
und lösen dessen Minutenlimit dadurch erst aus, statt es organisch über die Zeit verteilt zu
erreichen (genau das Muster, das zur Totalerschöpfung in einem echten Lauf führte).

- `core/rate_limiter.py` (neu): einfacher Sliding-Window-Rate-Limiter (`RateLimiter.acquire()`)
  – reines In-Process-Pacing, kein externer State.
- `core/llm_factory.py`: EINE geteilte `_gemini_rate_limiter`-Instanz (alle Gemini-Aufrufe
  dieses Prozesses teilen sich dasselbe Kontingent) vor jedem echten Gemini-API-Aufruf in
  beiden Haupt-Codepfaden (`generate_with_tools`, `generate_with_usage`/`generate_json`).
  Konfigurierbar über `GEMINI_MAX_CALLS_PER_MINUTE` (Standard: `12`, bewusst konservativ
  unter typischen kostenlosen RPM-Limits).
- 4 neue Tests (Pacing innerhalb des Limits ohne Wartezeit, Warten bei Überschreitung, echte
  Entzerrung bei vielen gleichzeitigen `asyncio.gather`-Aufrufern, Nachweis dass der echte
  Gemini-Aufruf tatsächlich durch den Limiter geht); volle Suite (151 Tests) grün, ruff sauber.

---

## 🛡️ Security-Review nicht mehr optional bei Auth/Nutzerdaten (P2)

`security` lief bisher nur mit, wenn der Planer ihn im Einzelfall auswählte – bei einer
Aufgabe mit Login, Zahlungsdaten oder einem öffentlich erreichbaren Endpunkt war das reiner
Zufall. `DECOMPOSE_SYSTEM_PROMPT` (`core/task_manager.py`) verlangt jetzt explizit, `security`
einzubeziehen, sobald Authentifizierung/Autorisierung, Nutzer-/Personendaten, Zahlungsdaten,
Datei-Uploads oder ein nach außen erreichbarer Netzwerk-Endpunkt entstehen – gleichrangig mit
der bereits bestehenden Pflicht-Regel für `code_reviewer`.

---

## 🔀 Push pusht den echten Branch + echter CI-Feedback-Loop (P2)

Zwei zusammenhängende Funde beim Review von `agents/github_agent.py`:

1. **`push()` hatte den Ziel-Branch fest auf `"main"` verdrahtet.** Jeder Aufruf (immer ohne
   explizites `branch=...`) pushte damit IMMER den lokalen `main`-Branch zum Remote –
   unabhängig davon, welcher Branch tatsächlich ausgecheckt war. Besonders relevant nach der
   Einführung isolierter Worktree-Branches für Selbstverbesserungsläufe (siehe oben).
   `push()` ermittelt den Ziel-Branch jetzt automatisch (`get_current_branch()`) und setzt
   bei Bedarf das Upstream-Tracking (`-u`, wichtig für neue/noch nie gepushte Branches).
2. **Kein CI-Feedback-Loop.** `push()` war bisher "fire and forget" – ob die echte
   CI-Pipeline (`.github/workflows/ci.yml`, läuft bei jedem Push) tatsächlich grün wird, hat
   das Team nie erfahren. Neue `wait_for_ci_status()` pollt den echten `gh run list`-Status
   (max. 90s) und meldet ehrlich `passed`/`failed`/`timeout`/`no_run` (kein `gh`/kein
   GitHub-Remote ist dabei kein Fehler, nur nicht prüfbar) – `interface/cli.py` zeigt das
   Ergebnis direkt nach einem erfolgreichen Push.

8 neue Tests (echtes lokales Bare-Repo für den Branch-Fix, gemockte `gh`-Aufrufe für den
Polling-Loop inkl. Timeout); volle Suite (146 Tests) grün, ruff sauber.

---

## 👥 Kleine Fachbereiche laufen jetzt sequenziell statt blind parallel

Realer Fund: Für eine triviale Aufgabe entstanden zwei parallele Implementierungen derselben
Sache (`app.py`/`test_app.py` UND separat `main.py`/`test_main.py` für denselben
Health-Check-Endpoint), weil zwei Agenten desselben "parallelen" Fachbereichs fast zeitgleich
starteten – die Dateibaum-Vorschau (siehe weiter unten) zeigt zwar immer den aktuellen Stand,
aber eben nur den zum jeweils EIGENEN Startzeitpunkt.

- `agents/orchestrator.py`: Fachbereiche mit **1–2 Mitgliedern** laufen jetzt IMMER
  sequenziell, unabhängig von der für den Fachbereich generell hinterlegten Präferenz – der
  Latenzgewinn durch Parallelität ist bei so wenigen Mitgliedern gering, der
  Sichtbarkeitsgewinn durch echte Sequenzialität groß. Ab 3 Mitgliedern bleibt es bei echter
  Parallelität (`asyncio.gather`), wo der Geschwindigkeitsvorteil überwiegt.
- 2 neue Tests: Nachweis, dass der zweite Agent eines 2er-Fachbereichs die vom ersten
  geschriebene Datei tatsächlich sieht, plus Gegenprobe, dass 3+-Mitglieder-Fachbereiche
  weiterhin `asyncio.gather` nutzen; volle Suite (138 Tests) grün, ruff sauber.

---

## ✅❓ Ehrlicher Abschluss-Status: "Fertig!" bedeutet jetzt wirklich verifiziert

Bisher endete JEDER Lauf mit demselben uneingeschränkten "✅ Fertig! Alle Fachbereiche haben
ihre Aufgaben erfolgreich abgeschlossen." – egal ob die echte Testsuite tatsächlich bestanden
hatte, nie gefunden wurde, oder nach mehreren Fixversuchen weiter fehlschlug. Wer nur die
letzte Statuszeile oder die Push-Bestätigung sah, hatte keinen Hinweis darauf, dass der zu
committende Code nie verifiziert wurde.

- `agents/orchestrator.py`: `_run_verification_loop()` gibt jetzt zusätzlich
  `verification_ok: bool` zurück – `True` NUR, wenn die echte Testsuite tatsächlich gelaufen
  UND bestanden ist (nicht bei "keine Tests gefunden", nicht bei ungelösten Testfehlern,
  nicht bei Budget-Abbruch während der Fixversuche). `Orchestrator.last_verification_ok`
  hält das Ergebnis für den Aufrufer fest; der allerletzte Status meldet entsprechend
  "✅ Fertig!" oder unmissverständlich "⚠️ Fertig, aber NICHT verifiziert!".
- `interface/cli.py`: Die Push-Bestätigung zeigt jetzt eine deutliche Warnung und eine
  andere Bestätigungsfrage, wenn `last_verification_ok` False ist – blockiert nichts hart
  (der Mensch kann bewusst trotzdem committen/pushen), macht das Risiko aber unübersehbar
  statt es im Kleingedruckten des Verifikations-Protokolls zu verstecken.
- 6 neue Tests (alle drei Ausgänge: bestanden / keine Tests / fehlgeschlagen, plus die
  Push-Gate-Warnung selbst); volle Suite (136 Tests) grün, ruff sauber.

---

## 🌳 Selbstverbesserungsläufe arbeiten jetzt in einem isolierten Git-Worktree

Bisher schrieb ein Selbstverbesserungslauf (Team arbeitet am Framework selbst,
`Orchestrator.process(forced_project_dir=<Framework-Root>)`) DIREKT im echten
Arbeitsverzeichnis des Nutzers – genau das ließ den `backend`-Agenten `main.py` UND
`interface/cli.py` mit kaputtem Inhalt überschreiben (siehe Syntax-Gate-Fund oben), während
das reale Arbeitsverzeichnis offen dalag.

- `core/git_isolation.py` (neu): legt für jeden Selbstverbesserungslauf einen komplett
  separaten Git-Worktree an – eigenes Verzeichnis (`../​.ai-team-worktrees/<slug>-<id>`),
  eigener Branch (`ai-team/<slug>-<id>`) vom aktuellen HEAD abgezweigt.
- `agents/orchestrator.py`: erkennt automatisch, wenn `forced_project_dir` auf das
  Framework-Root selbst zeigt, und leitet den Lauf transparent in den isolierten Worktree
  um. Schlägt die Isolation fehl (kein Git-Repo, `git` fehlt), bricht der Lauf bewusst ab,
  statt unsicher direkt im echten Verzeichnis zu schreiben.
- Nach dem Lauf entscheidet der Mensch selbst per `git diff`/`git merge` (oder Löschen des
  Worktrees), ob die Änderungen übernommen werden – analog zum bestehenden
  Git-Push-Bestätigungs-Gate.
- 9 neue Tests (echte temporäre Git-Repos, kein Mock, inkl. Nachweis dass Schreiben im
  Worktree das reale Arbeitsverzeichnis nachweislich nie berührt); volle Suite (130 Tests)
  grün, ruff sauber.

---

## ⏳ Kurzes Warten statt Sofort-Scheitern bei komplett erschöpfter Provider-Kette

Realer Fund aus einem echten Lauf: als an einem Tag alle Gemini-Kontingente gleichzeitig an
ihrem Minutenlimit hingen (ohne konfigurierten `ANTHROPIC_API_KEY` als Backstop), scheiterten
praktisch alle Agenten sofort – jeder einzelne Aufruf kassierte denselben `429`-Fehler erneut,
ohne je den (oft nur Sekunden entfernten) Cooldown des jeweiligen Modells abzuwarten.

- `core/token_guard.py`: neue `seconds_until_available()` – gibt zurück, wie lange mindestens
  gewartet werden muss, bis wenigstens ein Kandidat einer Fallback-Kette wieder verfügbar ist.
- `core/llm_factory.py`: `GeminiClient.generate_with_tools()`/`generate_with_usage()` warten
  jetzt kurz (gedeckelt auf `MAX_EXHAUSTION_WAIT_SECONDS = 20s`) auf den kürzesten bekannten
  Cooldown, WENN die komplette Fallback-Kette eines Aufrufs aktuell als erschöpft markiert ist –
  statt sofort denselben Fehler erneut zu kassieren. Erhöht die reale Erfolgsquote bei kurzen,
  minutenbasierten Rate-Limits spürbar, ohne einen Lauf durch unbegrenztes Warten zu blockieren.
- 3 neue Tests (Cooldown-Berechnung inkl. "kürzester gewinnt", End-to-End-Nachweis der
  Wartelogik mit gemocktem `asyncio.sleep`); volle Suite (121 Tests) grün, ruff sauber.

**Weiterhin offen (nicht durch Code lösbar):** ohne mindestens einen zweiten, tatsächlich
bezahlten Provider-Schlüssel (z.B. `ANTHROPIC_API_KEY`) als echtes Backstop bleibt das System
nur so verlässlich wie die Großzügigkeit der kostenlosen Kontingente – bei echter
Totalerschöpfung ALLER konfigurierten Provider (nicht nur eines kurzen Minutenlimits) gibt es
weiterhin keinen Ausweg außer Warten oder einen Schlüssel hinzuzufügen.

---

## 🛡️ Syntax-Gate für write_file/edit_file (kritischer Fund)

Ein echter Team-Lauf hat `main.py` **und** `interface/cli.py` unbemerkt mit syntaktisch
komplett kaputtem Inhalt überschrieben (Zeilenumbrüche/Anführungszeichen landeten als
literale `\n`/`\"` statt echter Escape-Sequenzen im Dateiinhalt – vermutlich doppelt
JSON-serialisiert) – danach war `python main.py` überhaupt nicht mehr startbar. Der Agent
meldete `success=True`, die echte Testverifikation lief zwar an und schlug fehl, aber die
Fix-Versuche scheiterten selbst wieder an einer zeitgleichen Provider-Erschöpfung (alle
Gemini-Kontingente + kein `ANTHROPIC_API_KEY`), sodass der kaputte Stand am Ende trotzdem
übernommen wurde. Nichts war committet, der Schaden blieb also lokal reparabel – aber die
eigentliche Lücke lag tiefer: **write_file/edit_file prüften den Inhalt vorher gar nicht.**

- `core/agent_toolbox.py`: `write_file`/`edit_file` lehnen jetzt jeden `.py`-Inhalt ab, der
  nicht durch `ast.parse()` (dieselbe Prüfung wie `core/code_sandbox.py`) valide ist –
  SOFORT beim Werkzeug-Aufruf selbst, nicht erst Minuten später über die teure
  Testverifikation. Der Agent bekommt eine klare Fehlermeldung zurück und kann selbst
  korrigieren, statt dass kaputter Code unbemerkt auf der Platte landet.
- `core/workspace.py`: derselbe Schutz für den Regex-basierten Text-Fallback
  (`parse_and_save_files`) – fehleranfälliger, da aus freiem Antworttext extrahiert.
- 5 neue Tests (Reproduktion des exakten Fund-Musters + Positiv-/Negativ-Fälle für beide
  Speicherpfade); volle Suite (119 Tests) grün, ruff sauber.

---

## 🪙 Commit-Message-Fallback & Test-Pflicht (Runde 2)

Ein echter Team-Lauf zeigte trotz des vorherigen Fixes erneut eine Commit-Message wie *"Ich
möchte das ihr ein neues Projekt erstellt. Es"* – diesmal, weil das Modell den (bereits
präzisierten) Zusammenfassungs-Auftrag im `DECOMPOSE_SYSTEM_PROMPT` selbst nicht befolgte,
nicht wegen eines Verdrahtungsfehlers. Zwei Gegenmaßnahmen:

- `core/task_manager.py`: `task_summary` im JSON-Schema jetzt explizit als "3-8 Wörter,
  technischer Imperativ … NIEMALS die Nutzeranfrage wörtlich wiederholen" spezifiziert.
- `interface/cli.py`: erkennt deterministisch (ohne weiteren LLM-Aufruf) typische
  Anrede-/Bitte-Formeln ("Ich möchte …", "Könnt ihr …", "Bitte …") am Anfang von
  `task_summary` und nutzt in diesem Fall `Orchestrator.last_project_slug` (immer kurz,
  bereits sanitiert) als Commit-Betreff statt eines weiteren rohen `[:50]`-Schnitts.

Derselbe Lauf lieferte außerdem ein Taschenrechner-Projekt **ohne einen einzigen Test** aus –
dessen `+`-Button beim ersten Klick mit `TypeError` abgestürzt wäre. `DECOMPOSE_SYSTEM_PROMPT`
weist das Modell jetzt an, den `tester`-Agenten bei echter Programmlogik einzubeziehen, und
die "keine Tests gefunden"-Zeile im Verifikations-Report ist von ℹ️ auf ⚠️ hochgestuft, damit
ungeprüft ausgelieferter Code sichtbar auffällt statt wie ein normaler Status durchzurutschen.

---

## 🔗 `/load` arbeitet jetzt wirklich am geladenen Projekt weiter

Der Hilfetext versprach schon immer: *"Lade das Projekt mit `/load <name>`, gib dem Team dann
deine Anweisung."* Real hatte `/load` aber NUR Auswirkung auf `/rag` – jede normale
Chat-Nachricht ließ `agents/orchestrator.py` trotzdem einen frischen `project_slug` raten und
in einem NEUEN `workspace/`-Ordner arbeiten. Das ist die eigentliche Ursache der Duplikate im
Abschnitt darunter (`calculator_service`/`simple_calculator` etc. entstanden vermutlich genau
so). `Orchestrator.process()` akzeptiert jetzt `forced_project_dir`; `interface/cli.py` reicht
`_loaded_project_dir` dorthin durch, sobald zuvor `/load` aufgerufen wurde – inklusive der
Text-Fallback-Dateispeicherung und der "Projektverzeichnis"-Anzeige in den Lauf-Kennzahlen, die
beide vorher noch am geratenen Slug statt am tatsächlichen Zielordner hingen.

---

## 🪙 Commit-Message-Fix & Duplikat-Vermeidung (Token-Effizienz-Runde)

Beim Durchsehen echter Läufe fielen zwei konkrete Verschwendungsmuster auf, die jetzt behoben sind:

- **Commit-Message nutzte die rohe Nutzereingabe statt der Aufgaben-Zusammenfassung:** `/push`
  baute den Commit-Betreff bisher aus der unveränderten, oft konversationellen Nutzereingabe
  (z.B. *"Okay ich möchte, dass ihr das Projekt weiter verbessert…"*), hart bei 50 Zeichen
  MITTEN im Wort abgeschnitten. `agents/orchestrator.py` legt die echte, vom `TaskManager`
  erzeugte Kurzfassung jetzt in `Orchestrator.last_task_summary` ab, `interface/cli.py` nutzt
  diese für die Commit-Message und schneidet nur noch an Wortgrenzen ab (`_truncate_at_word`).
- **Parallele Teammitglieder implementierten dieselbe Sache doppelt:** Bei einer trivialen
  Aufgabe entstanden real `app.py`/`test_app.py` UND separat `main.py`/`test_main.py` für
  denselben Health-Check-Endpoint, weil ein Agent nicht von sich aus `list_files` aufrief,
  bevor er zu schreiben begann. `agents/base_agent.py` stellt den aktuellen Dateibaum jetzt
  IMMER automatisch (ohne LLM-Aufruf, ohne extra Loop-Iteration) dem ersten Prompt voran und
  weist das Modell explizit an, bestehenden Code zu erweitern statt doppelt zu implementieren.
- **Neue Projekte verschleierten bereits vorhandene, inhaltlich identische Projekte:**
  `project_slug` wird pro Lauf neu vom Modell geraten und unterscheidet sich oft selbst bei
  gleicher Aufgabe (real beobachtet: `calculator_service`/`simple_calculator` und
  `notes_tasks_api`/`personal_notes_tasks` – je zwei komplette, separat bezahlte Läufe für
  praktisch dieselbe Anwendung). `Orchestrator.process()` zeigt jetzt beim Anlegen eines neuen
  Projektordners an, welche Projekte bereits im Workspace existieren, mit dem Hinweis, `/load
  <name>` zu nutzen, falls eigentlich an einem davon weitergearbeitet werden sollte.

---

## 🛠️ Echter agentischer Werkzeug-Loop, echte Verifikation & aktive Teamleiter

Seit dem letzten Umbau ist das Team kein reiner Ein-Schuss-Textgenerator mehr, sondern nutzt echtes,
providerübergreifendes Function-Calling:

- **Echte Werkzeuge statt nur Text:** Jeder Agent mit Projektzugriff bekommt `read_file`, `write_file`,
  `edit_file` (präziser Patch statt Volltext-Neuerstellung), `list_files`, `search_code`, `run_command`
  und `run_tests` – und ruft sie über natives Function-Calling von Gemini/DeepSeek/Groq/Claude/OpenRouter
  wirklich auf, bevor er eine Aufgabe als erledigt meldet (`agents/base_agent.py`, `core/agent_toolbox.py`).
- **Echte Verifikation statt Keyword-Raten:** Nach der QA-Phase installiert der Hauptagent Abhängigkeiten
  in einer isolierten venv und führt die tatsächliche Testsuite aus (`core/verifier.py`). Schlägt ein Test
  fehl, wird der reale Traceback geparst und der Korrekturauftrag GEZIELT an genau den Agenten geschickt,
  der die betroffene Datei geschrieben hat – nicht mehr blind an alle Dev-Agenten.
- **Aktive Fachbereichs-Teamleiter:** Jeder der 5 Teamleiter delegiert und konsolidiert jetzt über einen
  echten LLM-Aufruf (nicht mehr nur simulierte Statusmeldungen) und erscheint mit eigenem, geprüftem
  Ergebnis in der finalen Kennzahlen-Tabelle.

