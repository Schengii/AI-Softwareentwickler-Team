"""
agents/team_directives.py – Verbindliche, rollenübergreifende Direktiven für die Kernrollen
(architect, backend, tester, refactoring).

Systemische Fehlerbilder aus realen Läufen, die diese Direktiven adressieren:
- Interface-Drift: architect/backend definierten `class EncryptionService`, tester importierte
  eine freie Funktion `encrypt` -> Abbruch schon bei der Test-Collection.
- Settings ohne Dev-Defaults -> ValidationError bei jedem Import ohne `.env`.
- Fix-Loops änderten requirements.txt bei Import-/Syntaxfehlern.

Die Blöcke hängen als STATISCHE Suffixe an den System-Prompts (bytegleich über alle Läufe, damit
das Caching-Präfix aus agents/base_agent.py stabil bleibt). Die deterministische Gegenseite ist
core/failure_triage.py: liest interface_contract.json, routet Strukturfehler an den abweichenden
Agenten und setzt Manifest-Änderungen bei Strukturfehlern zurück.
"""

from core.failure_triage import INTERFACE_CONTRACT_FILE

_SETTINGS_RULE = """- Pydantic-Settings (`BaseSettings`): JEDES Feld hat einen lauffähigen Dev-Default (z. B.
  `DATABASE_URL: str = "sqlite:///./dev.db"`, `SECRET_KEY: str = Field(default_factory=lambda:
  secrets.token_urlsafe(32))`, `DEBUG: bool = False`) und `model_config = SettingsConfigDict(
  env_file=".env", extra="ignore")`; Zugriff über eine gecachte `get_settings()`. `import app.main`
  und die Testsuite müssen OHNE `.env` und ohne gesetzte Umgebungsvariablen starten –
  Produktionswerte kommen ausschließlich aus der Umgebung."""

# Team-Optimierung (Analysebericht `ki_team_schwachstellen_und_fehleranalyse_aethermesh_
# 20260913.md`, Schwachstelle 4): das Framework installiert `pytest-asyncio` inzwischen selbst
# und aktiviert `asyncio_mode=auto` als CLI-Default (core/verifier/environment.py,
# core/verifier/testrunner.py) - eine vom Team selbst angelegte pytest.ini bleibt trotzdem
# sinnvoll, weil sie die Konfiguration auch außerhalb der Verifikations-Sandbox (z. B. bei einem
# manuellen `pytest`-Aufruf im ausgelieferten Projekt) reproduzierbar macht und `pythonpath = .`
# lokale Importe (`from app... import ...`) ohne zusätzliches `PYTHONPATH`-Setup absichert.
_PYTEST_ASYNCIO_CONFIG_RULE = """- Nutzt das Projekt `asyncio`, FastAPI oder asynchrone Tests (`async def test_...`), legst du
  IMMER eine `pytest.ini` im Projekt-Root mit genau diesem Inhalt an (per write_file):
  ```ini
  [pytest]
  asyncio_mode = auto
  pythonpath = .
  ```
  Ohne `asyncio_mode = auto` überspringt pytest jede asynchrone Testfunktion stillschweigend
  ("async def functions are not natively supported") - der generierte Code bleibt dann komplett
  ungeprüft, selbst wenn er fehlerfrei ist."""

ARCHITECT_CONTRACT_DIRECTIVE = f"""
## 📜 Contract First – verbindlicher Modul-Schnittstellen-Vertrag
Bevor implementiert wird, legst du die öffentliche Python-Schnittstelle JEDES Moduls fest, das von
mehr als einer Datei oder mehr als einem Agenten genutzt wird:
1. Schreibe den Vertrag per write_file als `{INTERFACE_CONTRACT_FILE}` ins Projekt-Root (ohne
   Werkzeuge: als ```json-Block in Abschnitt 4). Format:
   `{{"modules": {{"app/core/encryption.py": {{"EncryptionService": "class", "encryption_service": "instance"}}}}}}`
   Erlaubte Arten: class | function | instance | constant.
2. Lege pro Fähigkeit GENAU EINE Form fest – Klasse ODER freie Funktion, nie beides offen. Sollen
   andere Module eine Klasse direkt nutzen, vereinbare zusätzlich eine benannte Modul-Instanz.
3. Nenne in „Anweisungen für das Team" für jede vereinbarte Datei den exakten Import
   (`from app.core.encryption import EncryptionService`). Niemand importiert Symbole außerhalb
   des Vertrags.
4. Plane genau eine zentrale Settings-Klasse ein:
{_SETTINGS_RULE}
5. Änderst du eine Schnittstelle, aktualisierst du `{INTERFACE_CONTRACT_FILE}` im selben Schritt.
6. Tooling-Konfiguration für Tests:
{_PYTEST_ASYNCIO_CONFIG_RULE}
"""

_ASYNC_EVENT_LOOP_DIRECTIVE = """
## ⏱️ Async & Event-Loop Direktive (VERBINDLICH)
- `asyncio.get_event_loop()` ist auf Modulebene und im synchronen `__init__` VERBOTEN. In Python
  3.10+ existiert dort noch kein laufender Event-Loop – der Aufruf wirft beim Import durch pytest
  sofort `RuntimeError: There is no current event loop in thread 'MainThread'` und lässt die
  gesamte Testsuite schon in der Collection-Phase scheitern.
- Für Zeitmessungen, Cooldowns, TTLs und Timeouts (Circuit Breaker, Rate Limiter, Caches) wird
  STANDARDMÄSSIG `time.monotonic()` verwendet, NIEMALS `loop.time()`/`asyncio.get_event_loop().time()`.
- Globale Singletons (z. B. CircuitBreaker-Instanzen, HTTP-Clients wie `httpx.AsyncClient`) werden
  NIEMALS ungeschützt auf Modulebene instanziiert. Sie entstehen ausschließlich im FastAPI-Lifespan
  (`@asynccontextmanager async def lifespan(...)`) oder in einer asynchronen Factory-Methode
  (`async def get_instance(cls) -> "X"`), niemals beim Import.
"""

PYTHON_CODE_CONTRACT_DIRECTIVE = f"""
## 📜 Contract First – verbindlich für alle Python-Code schreibenden Agenten
- Prüfe IMMER ZUERST `{INTERFACE_CONTRACT_FILE}` (per read_file/search_code), bevor du neue Dateien,
  Klassen oder Schnittstellen erstellst. Existiert der Vertrag, implementierst du jedes dort
  genannte Symbol exakt mit Name, Art (class/function/instance/constant) und Modulpfad.
- Weiche NIEMALS von den dort definierten Dateipfaden und Typen ab. Brauchst du eine Abweichung,
  änderst du Vertrag UND Code im selben Schritt – nie nur den Code.
- Musst du eine neue Hilfsdatei/ein neues Modul anlegen, das NICHT im Vertrag steht, dokumentierst
  du dies explizit im Task-Output (Dateipfad + Zweck) und hältst dich an den Standardpfad
  `app/<modul>/...`.
{_SETTINGS_RULE}
{_ASYNC_EVENT_LOOP_DIRECTIVE}"""

# Team-Optimierung (`/goal`-Auftrag, Schwachstelle 1 aus den Läufen eventstream_zero/
# aethermesh/chronospulse/incident_pulse): mehrere reale Läufe lieferten ein Backend, das
# ausschließlich aus Submodulen (app/core/*.py, app/security/*.py, ...) ohne jeden zentralen
# Einstiegspunkt bestand - core/verifier/testrunner.py._find_incomplete_project_reason()
# erkennt genau dieses Muster zwar NACHTRÄGLICH (Python-Dateien + Manifest, aber kein
# main.py/app.py/...), das kommt aber erst NACH bereits verbranntem Token-Budget zum Tragen.
# Diese Pflicht wirkt VORHER, direkt im Backend-System-Prompt.
_BACKEND_ENTRYPOINT_DIRECTIVE = """
## 🚪 Pflicht-Einstiegspunkt (VERBINDLICH, keine Ausnahme)
- Sobald das Projekt ein Backend, eine API oder Serverkomponenten enthält, legst du als
  ALLERERSTE oder ZWEITE Datei zwingend den zentralen Einstiegspunkt an (bevorzugt
  `app/main.py`, ersatzweise `main.py`) – NIEMALS erst, nachdem alle Submodule fertig sind.
- Dieser Einstiegspunkt MUSS enthalten:
  1. Eine initialisierte App-Instanz auf Modulebene (`app = FastAPI(...)`).
  2. Einen Lifespan-Handler (`@asynccontextmanager async def lifespan(app: FastAPI): ...`,
     via `FastAPI(lifespan=lifespan)` eingebunden) für Startup-/Shutdown-Ressourcen
     (DB-Engine, HTTP-Clients, Singletons – siehe Async & Event-Loop Direktive unten).
  3. Einen Health-Check-Endpunkt `GET /health`, der ohne Auth erreichbar ist und mindestens
     `{"status": "ok"}` liefert.
  4. Falls statische Web-Assets existieren (`public/`, `static/`, `app/static/`): den Mount
     `app.mount("/", StaticFiles(directory=...), name=...)`.
- Ein Projekt darf NIEMALS nur aus Submodulen (app/core/, app/security/, ...) ohne diesen
  Einstiegspunkt bestehen – ein Backend ohne `app/main.py`/`main.py` gilt als unvollständig
  abgebrochen, unabhängig davon, wie vollständig die einzelnen Submodule sind.
"""

BACKEND_CONTRACT_DIRECTIVE = f"""
## 📜 Contract First – Implementierung gegen den Vertrag
- Lies vor dem ersten Schreiben `{INTERFACE_CONTRACT_FILE}` (falls vorhanden) und implementiere JEDES
  dort genannte Symbol exakt mit Name, Art (class/function/instance/constant) und Modulpfad auf
  Modulebene.
- Brauchst du eine Abweichung, änderst du Vertrag UND Code im selben Schritt – nie nur den Code.
  Fehlt der Vertrag, legst du ihn für jedes modulübergreifend genutzte Symbol selbst an.
- Importierst du aus dem Modul eines anderen Agenten, prüfst du das Symbol vorher per
  read_file/search_code, statt eine Signatur anzunehmen.
{_BACKEND_ENTRYPOINT_DIRECTIVE}
{_SETTINGS_RULE}
{_ASYNC_EVENT_LOOP_DIRECTIVE}"""

TESTER_CONTRACT_DIRECTIVE = f"""
## 📜 Contract First – Tests gegen die echte Schnittstelle
- Speichere JEDE Testdatei SOFORT per `write_file("tests/test_<name>.py", ...)`/`edit_file` –
  NIEMALS nur als Codeblock im Antworttext. Realer Fund (OmniQueue-Lauf): eine vollständige
  Testsuite (8.167 Completion-Tokens) wurde nur im Fließtext ausgegeben statt gespeichert – das
  Hard Delivery Gate wertete das als kompletten Fehlschlag, 46.643 Tokens verpufften wirkungslos,
  und die eigentlich geplanten Tests fehlten am Ende ganz im Projekt.
- Vor jedem Import aus Produktivcode liest du `{INTERFACE_CONTRACT_FILE}` UND die Zieldatei selbst
  (read_file/search_code). Du importierst NUR Symbole, die dort auf Modulebene existieren.
- Nimm nie an, dass eine Methode als freie Funktion existiert: Definiert das Modul
  `class EncryptionService` mit `encrypt()`, testest du `EncryptionService(...).encrypt(...)` bzw. die
  vereinbarte Instanz – nicht `from app.core.encryption import encrypt`.
- Raten von Keyword-Argumenten oder Methodensignaturen ist VERBOTEN. Bevor du eine Methode einer
  neu erstellten Klasse aufrufst oder assertierst, MUSST du die Methodendefinition via `read_file`
  oder `find_symbol_definition` prüfen, um TypeErrors durch falsch geratene Parameter zu verhindern.
- Weicht der Produktivcode vom Vertrag ab, passt du den Test NICHT an den Fehler an, sondern nennst
  die Abweichung (Datei + Symbol) in deiner Antwort.
- Tests setzen benötigte Settings über `monkeypatch.setenv(...)` bzw. `app.dependency_overrides`
  und verlassen sich nie auf eine vorhandene `.env`.
- Direkt nach dem Schreiben führst du `run_tests` aus; Collection-Fehler (ImportError/SyntaxError)
  behebst du vor allem anderen.
{_PYTEST_ASYNCIO_CONFIG_RULE}
"""

FRONTEND_CONTRACT_DIRECTIVE = """
## 📜 Contract First – Web-Assets sofort physisch speichern
- Speichere JEDES Web-Asset (HTML, CSS, JS) SOFORT als erste Aktion per `write_file("static/<datei>", ...)`
  – gib niemals riesige Codeblöcke im Antworttext aus, um das 8.192-Token-Ausgabelimit von Gemini
  Flash nicht zu überschreiten. Realer Fund (OmniQueue-Lauf, siehe TESTER_CONTRACT_DIRECTIVE): eine
  komplette Datei, nur im Fließtext statt per Werkzeug gespeichert, wertete das Hard Delivery Gate
  als kompletten Fehlschlag – die eigentlich fertige Arbeit fehlte danach ganz im Projekt.
- Erst NACH dem `write_file`-Aufruf erklärst du wichtige Entscheidungen kurz in Prosa, nie als
  Ersatz für die physische Datei.
"""

FIX_LOOP_DIRECTIVE = f"""
## 🧭 Fix-Loop-Disziplin: Ursache vor Symptom
Klassifiziere einen Testfehler, BEVOR du etwas änderst:
| Fehlerbild | Richtige Korrektur | Tabu |
|---|---|---|
| SyntaxError / IndentationError | genau die genannte Datei und Zeile reparieren | Manifeste, andere Dateien |
| ImportError: cannot import name 'X' from '<Projektmodul>' | Schnittstelle angleichen: Konsument an `{INTERFACE_CONTRACT_FILE}`/den realen Code ODER fehlendes Symbol beim Anbieter ergänzen | requirements.txt |
| ModuleNotFoundError für ein Projektmodul (app, src, …) | Datei/Paket anlegen bzw. `pythonpath = .` in pytest.ini | requirements.txt |
| ValidationError einer Settings-Klasse | Dev-Defaults ergänzen | `.env`-Pflicht einführen |
| ModuleNotFoundError für ein Drittanbieter-Paket | Paket in requirements.txt ergänzen | Code umbauen |
- Dependency-Manifeste änderst du NUR im letzten Fall. Bei Strukturfehlern setzt die Verifikation
  Manifest-Änderungen automatisch zurück.
- Minimal-invasiv: nur die Dateien ändern, die Fehlermeldung bzw. „KONKRETE URSACHE" nennen; kein
  Umbau, solange die Testsuite rot ist. Prüfe jede Korrektur sofort mit `run_tests`.
"""
