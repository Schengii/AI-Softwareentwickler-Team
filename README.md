# 🤖 KI-Softwareentwickler-Team (v4.3)

<div align="center">

[![CI](https://github.com/Schengii/AI-Softwareentwickler-Team/actions/workflows/ci.yml/badge.svg)](https://github.com/Schengii/AI-Softwareentwickler-Team/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Hierarchy](https://img.shields.io/badge/Fachbereichs--Hierarchie-5_Teamleiter-blue?style=for-the-badge)
![Specialists](https://img.shields.io/badge/KI--Spezialisten-33_Agenten-success?style=for-the-badge)
![Resilience-Guard](https://img.shields.io/badge/Resilience--Guard-Fault--Tolerance_&_CircuitBreaker-orange?style=for-the-badge)
![RAG](https://img.shields.io/badge/Codebase_RAG-Gemini_Embeddings_%2B_BM25--Fallback-orange?style=for-the-badge)
![MCP](https://img.shields.io/badge/MCP_Server-IDE_Ready-6941C6?style=for-the-badge)
![Web-UI](https://img.shields.io/badge/Web--Dashboard-Dark_Mode-2ea043?style=for-the-badge)
![Persistent-Learning](https://img.shields.io/badge/Persistente_Selbstoptimierung-Aktiv-success?style=for-the-badge)
![Sandbox-Validation](https://img.shields.io/badge/Sandbox_Auto--Validierung-Aktiv-blueviolet?style=for-the-badge)

**Ein autonomes, hierarchisch strukturiertes KI-Team für vollständige, token-optimierte Softwareentwicklung.**  
33 hochspezialisierte KI-Experten – aufgeteilt in **5 Fachbereiche mit jeweils eigenem Teamleiter**, **Resilience-Guard (Circuit Breakers, Backoff, Graceful Degradation & Chaos Tests)**, **persistentem Langzeit-Gedächtnis & automatischer Selbstoptimierung**, **Prompt-Engineering**, **WCAG 2.2 Barrierefreiheit (a11y)**, **integriertem RAG-Vektorindex**, **Model Context Protocol (MCP)**, **Web-Dashboard**, **Sandbox-Code-Validierung**, **Tavily Live-Web-Recherche**, **DeepSeek Reasoning**, **Groq Turbo Inferenz** und Workspace-Dateisystem.

</div>

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

## 📖 Inhaltsverzeichnis

- [Hierarchische Team- & Fachbereichsstruktur (Grafik)](#teamstruktur)
- [Kommunikations- & Delegations-Workflow](#kommunikations-workflow)
- [🛡️ Neuer Spezialist: Resilience-Guard (QA & Fault-Tolerance)](#resilience-guard)
- [🌐 Modernes Web-Dashboard & Visualisierung](#web-dashboard)
- [🔌 MCP-Server: Einbindung in Cursor, Windsurf & Antigravity](#mcp-server)
- [🔍 Lokales Codebase-RAG & Semantische Suche](#codebase-rag)
- [🧪 Sandbox-Code-Validierung & Automatische Test-Execution](#sandbox-validierung)
- [🪙 Hartes Lauf-Budget (MAX_RUN_TOKENS)](#lauf-budget)
- [🧠 Persistente KI-Selbstoptimierung & Langzeitgedächtnis](#persistente-selbstoptimierung)
- [🎯 Die 33 Spezialisten & Fachbereiche](#die-33-spezialisten)
- [🚀 Alle CLI-Befehle im Überblick](#cli-befehle)
- [🧪 Automatisierte Tests](#tests)

---

<a id="teamstruktur"></a>
## 🏢 Hierarchische Team- & Fachbereichsstruktur

```
                                  Du (Nutzer)
                                       │
                                       │ 1. Aufgabe & Anforderungen
                                       ▼
                   ┌───────────────────────────────────────┐
                   │       🤖 HAUPTAGENT (Orchestrator)    │
                   │   Koordiniert Gesamtablauf & Synthese │
                   └───────────────────┬───────────────────┘
                                       │
                       2. Teilt auf in 5 Fachbereiche
                                       │
       ┌───────────────────────────────┼───────────────────────────────┬───────────────────────────────┬───────────────────────────────┐
       ▼                               ▼                               ▼                               ▼                               ▼
 ┌───────────┐                   ┌───────────┐                   ┌───────────┐                   ┌───────────┐                   ┌───────────┐
 │ 👔 Team-  │                   │ ⚡ Team-  │                   │ 🎨 Team-  │                   │ 🛡️ Team-  │                   │ 🔍 Team-  │
 │  leiter   │                   │  leiter   │                   │  leiter   │                   │  leiter   │                   │  leiter   │
 │  Planung  │                   │ Dev-Team  │                   │  Design   │                   │ QA/DevOps │                   │Governance │
 └─────┬─────┘                   └─────┬─────┘                   └─────┬─────┘                   └─────┬─────┘                   └─────┬─────┘
       │                               │                               │                               │                               │
       │ 3. Delegiert an Fachteam      │ 3. Delegiert an Fachteam      │ 3. Delegiert an Fachteam      │ 3. Delegiert an Fachteam      │ 3. Delegiert an Fachteam
       ▼                               ▼                               ▼                               ▼                               ▼
 ┌───────────┐                   ┌───────────┐                   ┌───────────┐                   ┌───────────┐                   ┌───────────┐
 │  FACHTEAM │                   │  FACHTEAM │                   │  FACHTEAM │                   │  FACHTEAM │                   │  FACHTEAM │
 │ • Product │                   │ • Backend │                   │ • Image/  │                   │ • DevOps  │                   │ • Code-   │
 │   Owner   │                   │ • Frontend│                   │   SVG     │                   │ • Tester  │                   │   Reviewer│
 │ • Business│                   │ • Database│                   │ • Copy-   │                   │ • Security│                   │ • Refact- │
 │   Analyst │                   │ • API/Int.│                   │   writer  │                   │ • Resil-  │                   │   oring   │
 │ • Web-Res.│                   │ • DataEng.│                   │ • UI/UX   │                   │   ience   │                   │ • Compli- │
 │ • Architekt                   │ • Mobile  │                   │ • a11y    │                   │   Guard   │                   │    ance   │
 │ • FinOps  │                   │ • ML / AI │                   │ • i18n    │                   │ • GitHub  │                   │ • Cleaner │
 └─────┬─────┘                   │ • Prompt- │                   │ • Docs    │                   └─────┬─────┘                   │ • Trainer │
       │                         │   Engineer│                   │ • Readme  │                         │                         └─────┬─────┘
       │ 4. Meldet Ergebnis      │ • Perform.│                   └─────┬─────┘                         │ 4. Meldet Ergebnis            │
       ▼                         └─────┬─────┘                         │                               ▼                               │ 4. Meldet Ergebnis
 ┌───────────┐                         │                               │ 4. Meldet Ergebnis      ┌───────────┐                         ▼
 │ 👔 Team-  │                         │ 4. Meldet Ergebnis            ▼                         │ 🛡️ Team-  │                   ┌───────────┐
 │  leiter   │                         ▼                         ┌───────────┐                   │  leiter   │                   │ 🔍 Team-  │
 │  Planung  │                   ┌───────────┐                   │ 🎨 Team-  │                   │ QA/DevOps │                   │  leiter   │
 └─────┬─────┘                   │ ⚡ Team-  │                   │  leiter   │                   └─────┬─────┘                   │Governance │
       │                         │  leiter   │                   │  Design   │                         │                         └─────┬─────┘
       │                         └─────┬─────┘                   └─────┬─────┘                         │                               │
       └───────────────────────────────┴───────────────┬───────────────┴───────────────────────────────┴───────────────────────────────┘
                                                       │
                                                       │ 5. Alle Teamleiter liefern geprüfte Teilberichte
                                                       ▼
                                       ┌───────────────────────────────┐
                                       │   🤖 HAUPTAGENT (Synthese)    │
                                       │ • Führt alle Teile zusammen   │
                                       │ • Schreibt Projekt-Dateien    │
                                       │ • Führt finale Sandbox-Tests  │
                                       └───────────────┬───────────────┘
                                                       │
                                                       │ 6. Fertiges Gesamtergebnis & Projektdateien
                                                       ▼
                                                  Du (Nutzer)
```

---

<a id="kommunikations-workflow"></a>
## 🔄 Kommunikations- & Delegations-Workflow

Was die Grafik oben zeigt, läuft technisch über zwei einfache Datenstrukturen
(`core/message_bus.py`) und einen festen 5-Phasen-Ablauf (`agents/orchestrator.py`):

1. **Zerlegung:** `TaskManager.decompose()` lässt den Hauptagenten die Nutzeranfrage in eine
   Liste von `AgentTask`-Objekten (Agent-ID + präzise Teilaufgabe) aufteilen – nur die
   Spezialisten, die für die Aufgabe wirklich gebraucht werden.
2. **Phasen-Durchlauf:** Die 5 Fachbereiche laufen in fester Reihenfolge (`PHASE_ORDER`):
   Planung → Entwicklung → Design/Content → QA/Security → Governance. Planung und
   Governance laufen sequenziell, die anderen drei parallel (`asyncio.gather`).
3. **Echte Delegation:** Vor jeder Phase bekommt der zuständige Teamleiter einen echten
   LLM-Aufruf mit der Aufgabenliste seines Fachteams und liefert priorisierte
   Arbeitsanweisungen zurück, die den Mitgliedern als Zusatzkontext mitgegeben werden.
4. **Ausführung mit echtem Werkzeugzugriff:** Jedes Fachteam-Mitglied arbeitet über den
   agentischen Werkzeug-Loop (siehe oben) direkt im Projektverzeichnis und liefert ein
   `AgentResult` (Erfolg/Fehler, Inhalt, Tokens, geschriebene Dateien) zurück.
5. **Echte Konsolidierung:** Nach jeder Phase prüft derselbe Teamleiter per weiterem
   LLM-Aufruf die Ergebnisse seines Teams und erstellt den offiziellen Fachbereichsbericht.
   Eine `file_owners`-Map merkt sich dabei, welcher Agent welche Datei geschrieben hat –
   die Grundlage für die gezielte Fehlerbehebung in der Verifikationsphase (siehe unten).
6. **Synthese:** Der Hauptagent fasst alle Fachbereichsberichte über `ResultAggregator`
   zu einem einheitlichen Gesamtergebnis zusammen und liefert es an den Nutzer zurück.

---

<a id="resilience-guard"></a>
## 🛡️ Neuer Spezialist: Resilience-Guard (QA & Fault-Tolerance)

Der [ResilienceGuardAgent](agents/resilience_guard_agent.py) sichert Software gegen Ausfälle ab:
- **Circuit Breaker:** Unterbricht Anfragen an ausgefallene Fremddienste, bevor der eigene Server überlastet.
- **Smart Retries:** Exponentielles Backoff mit Jitter gegen Thundering-Herd-Probleme.
- **Graceful Degradation:** Fällt nahtlos auf Caches oder Fallbacks zurück.
- **Chaos Tests:** Schreibt gezielte Unit-Tests zur Simulation von Netzwerk-Timeouts und Verbindungsabbrüchen.

---

<a id="web-dashboard"></a>
## 🌐 Modernes Web-Dashboard & Visualisierung

```bash
python main.py --dashboard [--port N] [--host ADRESSE]   # Standard: Port 8080, nur localhost
```

Ein echter, funktionsfähiger HTTP-Server (`interface/web_dashboard.py`, stdlib
`ThreadingHTTPServer`, keine zusätzliche Web-Framework-Abhängigkeit):

- **Startseite:** Dark-Mode-UI mit Eingabefeld für neue Aufgaben und Live-Übersicht aller
  5 Fachbereiche mit ihren echten Mitgliederlisten (aus `DEPARTMENT_DEFINITIONS`, nicht
  hart codiert).
- **`POST /api/run`:** Nimmt eine Aufgabe entgegen und reiht sie in eine Job-Queue ein.
  Jobs laufen **seriell** in einem einzigen Hintergrund-Worker – bewusst kein paralleler
  Mehrfach-Betrieb, weil sich mehrere gleichzeitige Läufe sonst denselben
  Gesprächsverlauf (`ConversationHistory`) teilen und gegenseitig verfälschen würden.
- **`GET /api/status/<job_id>`:** Wird vom Frontend alle 2 Sekunden abgefragt und liefert
  denselben Live-Fortschritt (Status-Zeilen je Fachbereich/Agent), den auch die CLI zeigt,
  plus das fertige Ergebnis, sobald der Lauf abgeschlossen ist.
- **`GET /api/status`:** Echte Team-Metadaten (Agentenanzahl, Fachbereiche, Mitglieder) aus
  der laufenden `Orchestrator`-Instanz statt fest verdrahteter Werte.

**🔒 Sicherheit standardmäßig aktiv:** Der Server bindet per Default nur auf `127.0.0.1`
(`config.DASHBOARD_HOST`) – aus dem Netzwerk nicht erreichbar. Wer das Dashboard bewusst im
Netzwerk freigeben will (`--host 0.0.0.0` oder `DASHBOARD_HOST` in der `.env`), MUSS
zusätzlich `DASHBOARD_AUTH_TOKEN` setzen; ohne Token verweigert `run_dashboard()` den Start
mit einer klaren Fehlermeldung, statt unauthentifiziert im Netzwerk zu lauschen. Ist ein
Token gesetzt, verlangt jeder Request (auch `GET /`) entweder den Header
`Authorization: Bearer <token>` oder `?token=<token>` in der URL – sonst `401 Unauthorized`.

---

<a id="mcp-server"></a>
## 🔌 MCP-Server: Einbindung in Cursor, Windsurf & Antigravity

`interface/mcp_server.py` ist ein Model-Context-Protocol-Server über stdio (JSON-RPC 2.0),
mit dem jede MCP-fähige IDE das gesamte Team als Werkzeug ansprechen kann.

**Start:** `python -m interface.mcp_server`

**Einbindung** (Beispiel für die MCP-Client-Konfiguration, z. B. Cursor `mcp.json` oder
Claude Desktop `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "ki-softwareentwickler-team": {
      "command": "python",
      "args": ["-m", "interface.mcp_server"],
      "cwd": "/pfad/zu/AI-Softwareentwickler-Team"
    }
  }
}
```

**Bereitgestellte Werkzeuge:**

| Tool | Beschreibung |
|---|---|
| `ai_team_develop` | Führt das komplette Team für eine beliebige Aufgabe aus (`prompt`) und liefert das fertige, geprüfte Ergebnis. |
| `ai_team_list_projects` | Listet alle vorhandenen Projekte im `workspace/`-Verzeichnis auf. |
| `ai_team_rag_search` | Durchsucht ein konkretes Projekt (`project` + `query`) semantisch – dieselbe Gemini-Embedding-Suche wie `/rag` in der CLI. |

---

<a id="sandbox-validierung"></a>
## 🧪 Sandbox-Code-Validierung & Automatische Test-Execution

Zwei unabhängige Prüfebenen, die sich ergänzen:

1. **Statische Validierung** (`core/code_sandbox.py`): Prüft Python-Code per `ast.parse()`
   auf Syntaxfehler, JSON per `json.loads()`, YAML auf grobe Formatierungsfehler (z. B. Tabs
   statt Leerzeichen) – schnell, ohne Ausführung, ohne Abhängigkeiten.
2. **Echte dynamische Verifikation** (`core/verifier.py`, `ProjectVerifier`): Legt bei
   vorhandener `requirements.txt` eine isolierte venv im Projekt an, installiert die
   Abhängigkeiten wirklich per `pip`, und führt die tatsächliche Testsuite aus (`pytest`,
   falls installiert, sonst `unittest discover`). Schlägt ein Test fehl, wird der reale
   Traceback geparst (beide Formate: klassischer Python-Traceback und pytest-Kurzformat)
   und der betroffene Agent anhand der `file_owners`-Map gezielt zur Korrektur beauftragt –
   bis zu `MAX_VERIFICATION_ITERATIONS` Runden (Standard: 2).

Beide Ebenen laufen automatisch als Teil jedes Orchestrator-Laufs, ohne dass der Nutzer sie
manuell anstoßen muss. Manuell erreichbar über `/run-tests [projekt]` in der CLI.

**🔒 Secrets bleiben vor Subprozessen verborgen:** `run_command`/`run_tests` (und damit jede
von einem Agenten ausgelöste `pip install`/`npm install`) starten den Kindprozess NICHT mit
der vollen Prozessumgebung dieses Frameworks – `core/code_sandbox.py` filtert vorher alles
heraus, dessen Variablenname nach einem Secret aussieht (`*_API_KEY`, `*_TOKEN`, …). Ein
bösartiges oder kompromittiertes Paket, das per Install-Skript Umgebungsvariablen ausliest,
bekommt so keine echten API-Keys zu sehen.

---

<a id="lauf-budget"></a>
## 🪙 Hartes Lauf-Budget (MAX_RUN_TOKENS)

`core/quota_estimator.py` zeigt den Tokenverbrauch live an – vorher aber nur als Anzeige,
ohne dass ein außer Kontrolle geratener Lauf (z. B. durch mehrere Verifikations-Fixversuche
mit kostenpflichtigen Heavy-Modellen wie Claude) je automatisch gestoppt wurde. `agents/orchestrator.py`
bricht Läufe jetzt tatsächlich ab, sobald das per `.env` konfigurierte `MAX_RUN_TOKENS`
(Standard: `0` = deaktiviert, bestehende Läufe bleiben unangetastet) erreicht wird:

- Die Prüfung erfolgt vor jeder der 5 Fachbereichs-Phasen sowie vor jedem Verifikations-Fixversuch
  (`_run_budget_exceeded()`), nicht mitten in einer laufenden Phase – bereits begonnene Arbeit
  wird also nicht abgewürgt.
- Bei Überschreitung werden verbleibende Fachbereiche, weitere Verifikations-Fixversuche sowie
  Retrospektive & Selbstoptimierung übersprungen – die bis dahin erarbeiteten Ergebnisse werden
  trotzdem synthetisiert und ausgeliefert, nicht verworfen (Graceful Degradation statt Abbruch
  ohne Ergebnis).
- Die `### 📈 Projekt-Kennzahlen`-Tabelle zeigt bei aktivem Budget zusätzlich `Lauf-Budget: X / Y
  Tokens` an, sodass der Verbrauch schon während des Laufs sichtbar ist (nicht erst danach).

---

<a id="persistente-selbstoptimierung"></a>
## 🧠 Persistente KI-Selbstoptimierung & Langzeitgedächtnis

- **Gesprächsverlauf** (`memory/conversation_history.py`): Jede Nutzer-/Assistenten-Nachricht
  wird als JSON unter `memory/history_<session>.json` persistiert und bei künftigen Anfragen
  als Kontext (gekürzt auf die letzten Nachrichten) mitgegeben – Konversationen überleben
  also einen Neustart des Programms.
- **Agenten-Wissensbasis** (`memory/agent_knowledge_base.py`): Nach jedem Lauf analysiert der
  `agent_trainer`-Agent per LLM-Aufruf Fehler und Ineffizienzen und schlägt konkrete
  Prompt-Schärfungen vor. `Orchestrator._extract_and_store_learnings()` liest primär einen
  maschinenlesbaren ```json```-Block (`{"learnings": [{"agent_id": ..., "rule": ...}]}`) aus
  dem Trainer-Bericht – dabei explizit NICHT nur den ersten gefundenen Block, sondern den
  ersten, der wirklich einen `"learnings"`-Schlüssel enthält (der Bericht selbst zeigt in
  seinen Prompt-Diff-Beispielen oft schon ein illustratives ```json```-Snippet davor). Liefert
  das Modell keinen gültigen JSON-Block, greift ein Text-Fallback
  (`"Betroffener Agent:"` gefolgt von Aufzählungspunkten). Jede `agent_id` wird gegen die
  echten Agenten-/Leiter-IDs validiert. Regeln werden pro Agent als Liste in
  `memory/agent_learnings.json` gespeichert (max. 5 pro Agent – älteste fällt raus, jede
  einzelne Regel zusätzlich auf `MAX_RULE_LENGTH=300` Zeichen gedeckelt, da sie bei JEDEM
  künftigen Aufruf des Agenten erneut in dessen System-Prompt landet) und bei jedem künftigen
  Aufruf automatisch angehängt (`get_augmented_prompt()`).

---

<a id="codebase-rag"></a>
## 🔍 Lokales Codebase-RAG & Semantische Suche

Agenten (über das `search_code`-Werkzeug), `/load` bestehender Projekte, der `/rag`-CLI-Befehl
und der MCP-Server (`ai_team_rag_search`) durchsuchen den Code semantisch über echte
Gemini-Embeddings (`core/embedding_index.py`, Modell `gemini-embedding-001`, 768 Dimensionen)
– findet auch Treffer ohne Wortüberschneidung, z. B. liefert *"Wie wird ein Nutzer
eingeloggt?"* die passende `auth.py`, obwohl dort nirgends "einloggen" steht.

- **Persistenter Cache pro Projekt** (`workspace/<projekt>/.ai_team_rag/index.json`): Nur
  neue oder per SHA-256-Hash erkannte geänderte Dateien werden neu eingebettet – nicht das
  gesamte Projekt bei jedem Aufruf.
- **Automatischer Fallback:** Ohne `GEMINI_API_KEY` oder bei einem fehlgeschlagenen
  Embedding-Aufruf springt das System auf die eingebaute BM25-Keyword-Suche
  (`core/vector_store.py`) zurück – die Suche funktioniert also immer, nur mit
  unterschiedlicher Qualität.

---

<a id="die-33-spezialisten"></a>
## 🎯 Die 33 Spezialisten & Fachbereiche

| Fachbereich | Teamleiter | Spezialisten im Team |
|---|---|---|
| 🔵 **Planung, Analyse & Architektur** | `planning_lead` | `product_owner`, `business_analyst`, `web_research`, `architect`, `finops`, `team_lead` |
| 🟢 **Software-Entwicklung** | `dev_lead` | `backend`, `frontend`, `database`, `api_integration`, `data_engineer`, `mobile`, `ml`, `prompt_engineer`, `performance` |
| 🎨 **Design, Media & Content** | `creative_lead` | `image_generator`, `copywriter`, `ui_ux`, `accessibility`, `i18n`, `documentation`, `readme` |
| 🟡 **Qualität, DevOps & Security** | `qa_lead` | `devops`, `tester`, `security`, `resilience_guard`, `github` |
| 🔴 **Excellence & Governance** | `governance_lead` | `code_reviewer`, `refactoring`, `compliance`, `project_cleaner`, `agent_trainer`, `retrospective` |

---

<a id="cli-befehle"></a>
## 🚀 Alle CLI-Befehle im Überblick

```bash
python main.py                          # Interaktive CLI (Standard)
python main.py --dashboard [--port N]   # Web-Dashboard unter http://localhost:8080
```

Details zum Web-Dashboard: [🌐 Modernes Web-Dashboard & Visualisierung](#web-dashboard).

| Befehl | Beschreibung |
|---|---|
| `/projekte` | Listet alle bestehenden Projekte im Workspace auf |
| `/load <pfad/name>` | Lädt ein bestehendes Projekt (Workspace oder externer Pfad) zur Weiterentwicklung |
| `/rag <begriff>` | Führt eine semantische Code-Recherche im geladenen Projekt durch |
| `/team` | Zeigt alle 5 Fachbereiche, Teamleiter und 33 Spezialisten an |
| `/workspace [projekt]` | Listet alle generierten Dateien im Projektordner auf |
| `/export [projekt]` | Packt das Projektverzeichnis in ein ZIP-Archiv |
| `/run-tests [projekt]` | Führt automatische Unit-Tests im Projekt aus |
| `/push` | Führt manuell einen Git-Commit & Push aus |
| `/verlauf` | Zeigt den bisherigen Gesprächsverlauf |
| `/neu` | Startet eine neue Konversation (löscht Verlauf) |
| `/hilfe` | Zeigt die Befehlsübersicht an |
| `/beenden` | Beendet das Programm |

---

<a id="tests"></a>
## 🧪 Tests ausführen

```bash
python -m unittest discover -s tests -p "test_*.py"
```

Die komplette Testsuite ist vollständig gemockt und läuft **ohne jeden API-Key/echten
LLM-Aufruf** durch (verifiziert). `.github/workflows/ci.yml` führt sie bei jedem Push/PR
gegen `main` automatisch aus (Python 3.11 & 3.12) – kostenlos, ohne Secrets nötig, plus
ein Syntax-Check aller Quelldateien. Echte End-to-End-Läufe mit echten LLM-Aufrufen
bleiben bewusst ein manueller, gezielter Schritt und sind nicht Teil der CI.

## 🧹 Lint (ruff)

```bash
pip install -r requirements-dev.txt
ruff check .
```

Konfiguration in `ruff.toml` (bewusst auf den Framework-Code beschränkt, `workspace/`
mit den vom Team selbst generierten Beispielprojekten ist ausgeschlossen). Läuft als
eigener, paralleler `lint`-Job in `.github/workflows/ci.yml` bei jedem Push/PR.
