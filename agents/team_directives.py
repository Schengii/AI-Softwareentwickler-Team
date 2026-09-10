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
{_SETTINGS_RULE}
"""

TESTER_CONTRACT_DIRECTIVE = f"""
## 📜 Contract First – Tests gegen die echte Schnittstelle
- Vor jedem Import aus Produktivcode liest du `{INTERFACE_CONTRACT_FILE}` UND die Zieldatei selbst
  (read_file/search_code). Du importierst NUR Symbole, die dort auf Modulebene existieren.
- Nimm nie an, dass eine Methode als freie Funktion existiert: Definiert das Modul
  `class EncryptionService` mit `encrypt()`, testest du `EncryptionService(...).encrypt(...)` bzw. die
  vereinbarte Instanz – nicht `from app.core.encryption import encrypt`.
- Weicht der Produktivcode vom Vertrag ab, passt du den Test NICHT an den Fehler an, sondern nennst
  die Abweichung (Datei + Symbol) in deiner Antwort.
- Tests setzen benötigte Settings über `monkeypatch.setenv(...)` bzw. `app.dependency_overrides`
  und verlassen sich nie auf eine vorhandene `.env`.
- Direkt nach dem Schreiben führst du `run_tests` aus; Collection-Fehler (ImportError/SyntaxError)
  behebst du vor allem anderen.
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
