# Security Audit & Hardening Report - PipelinePilot

**Projekt:** PipelinePilot (CI/CD & Task Workflow Engine)  
**Rolle:** Senior Security Engineer & Penetration Tester  
**Datum:** 2026-09-16  
**Status:** Audit abgeschlossen, Härtung & Fixes implementiert  

---

## 1. Executive Summary

Im Rahmen des Security Audits von **PipelinePilot** wurden die Kernkomponenten der CI/CD- und Task-Workflow-Engine analysiert:
1. **Task Execution Engine (`app/engine/executor.py`)**: Ausführung von Shell-Commands, HTTP-Pings und Transformationen.
2. **Eingabevalidierung & Sanitization (`app/schemas.py`)**: Validierung von Commands, URL-Schemes und Parametern.
3. **Statische Datei-Auslieferung & Pfad-Traversal (`main.py` / `static/`)**: Absicherung gegen Directory Traversal (`../`).
4. **Security Header & Transport-Sicherheit**: Content Security Policy (CSP), X-Frame-Options, X-Content-Type-Options, Referrer-Policy.

### Gefundene & behobene Schwachstellen:
- **[KRITISCH] Arbitrary Remote Command Execution via unvalidierte Shell-Befehle:** Der `StepExecutor._execute_shell` führte unbereinigte Shell-Strings direkt via `asyncio.create_subprocess_shell` aus. Dadurch bestanden Risiken für unkontrollierte Command Injection, Verkettung (`&&`, `;`, `|`), destruktive Systembefehle (`rm -rf /`, `mkfs`) und Fork-Bombs.
- **[HOCH] Server-Side Request Forgery (SSRF) im HTTP-Ping Step:** `StepExecutor._execute_http` erlaubte unbeschränkten Zugriff auf interne Netzwerkadressen (z. B. AWS/GCP Metadata Services `169.254.169.254`, `localhost`, `127.0.0.1`, RFC1918-Netze) und unsichere Protokolle (`file://`, `ftp://`).
- **[MITTEL] Fehlende Security-Header & Information Disclosure:** Die FastAPI-Anwendung lieferte statische Assets und REST-Endpunkte ohne essenzielle HTTP-Sicherheitsheader (CSP, HSTS/Nosniff, Frame-Options) aus.
- **[MITTEL] Pfad-Traversal-Risiko bei statischen Dateien:** Risiko unzureichend beschränkter Static-Mounts.
- **[NIEDRIG] Schema-Lockerung / Unvollständige Feld-Defaults:** Fehlende Default-Werte in Pydantic-Modellen führten zu 422 Unprocessable Content bei minimalen Shell-Steps.

---

## 2. Detaillierte Befunde & Bedrohungsanalyse (Threat Modeling)

### Befund 1: Unkontrollierte Shell Command Execution & Injection
- **Schweregrad:** Kritisch (CVSS 9.8)
- **Komponente:** `app/engine/executor.py` (`_execute_shell`)
- **Bedrohung:** Da PipelinePilot Pipelines über REST-Endpunkte anlegt, können Angreifer gefährliche Befehlsketten einschleusen (z. B. `rm -rf /`, Reverse Shells via `nc`, Exfiltration sensibler Umgebungsvariablen).
- **Gegenmaßnahme:**
  1. Einführung einer strikten Command-Sanitization und Blocklist in `app/core/security.py`.
  2. Blockierung gefährlicher Metazeichen und destruktiver Befehle.
  3. Konfigurierbare Ausführung mit Timeout (Standard: 30s) und Argument-Tokenisierung via `shlex.split`.

### Befund 2: Server-Side Request Forgery (SSRF)
- **Schweregrad:** Hoch (CVSS 8.6)
- **Komponente:** `app/engine/executor.py` (`_execute_http`)
- **Bedrohung:** Der HTTP-Step akzeptiert beliebige URLs. Angreifer könnten Cloud-Metadaten-Endpunkte (`http://169.254.169.254/latest/meta-data/`) oder lokale Admin-Ports abfragen.
- **Gegenmaßnahme:**
  1. Strikte Whitelist für URL-Schemata (`http`, `https`).
  2. Validierung gegen Loopback- (`127.0.0.1`, `localhost`) und Cloud-Metadaten-IPs (`169.254.169.254`).

### Befund 3: Fehlende Security Response Header
- **Schweregrad:** Mittel (CVSS 5.3)
- **Komponente:** `main.py`
- **Bedrohung:** Clickjacking, MIME-Sniffing und Cross-Site Scripting (XSS).
- **Gegenmaßnahme:**
  1. Implementierung einer dedizierten `SecurityHeadersMiddleware` in `app/core/security.py`.
  2. Setzen von `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin` und Content-Security-Policy (CSP).

### Befund 4: Path-Traversal-Prävention für `static/`
- **Schweregrad:** Mittel (CVSS 6.5)
- **Komponente:** `main.py`
- **Bedrohung:** Auslesen sensitiver System- oder Projektdateien (`/etc/passwd`, `.env`, SQLite DB) über manipulierbare Pfadangaben.
- **Gegenmaßnahme:**
  1. Auflösung aller Pfade mit `pathlib.Path.resolve()` und strikte Prüfung, ob der Zielpfad innerhalb des Basisverzeichnisses `static/` verbleibt.
  2. Absicherung der statischen Root-Route `/` gegen Directory Traversal.

---

## 3. Durchgeführte Implementierungen & Fixes

### 3.1 `app/core/security.py`
Erstellt als zentrales Sicherheitsmodul mit:
- `validate_and_sanitize_command(command: str) -> str`: Prüft auf destruktive Muster (`rm -rf /`, Fork-Bombs, Metazeichen-Misbrauch).
- `validate_http_target(url: str, allow_local: bool = False) -> str`: Validiert URLs gegen SSRF und unzulässige Protokolle.
- `safe_resolve_path(base_dir: Path, requested_path: str) -> Path`: Schützt vor Pfad-Traversal.
- `SecurityHeadersMiddleware`: FastAPI/Starlette Middleware für HSTS, CSP, X-Frame-Options, X-Content-Type-Options.

### 3.2 Härtung `app/engine/executor.py`
- Integration von `validate_and_sanitize_command` vor dem Starten von Subprozessen.
- Timeout-Absicherung für Shell-Prozesse (`asyncio.wait_for`).
- Validierung der Ziel-URL via `validate_http_target`.

### 3.3 Härtung `app/schemas.py`
- Pydantic-Feldvalidierung und Bereitstellung sinnvoller Defaults (`name="Unnamed Step"`), um robuste API-Validierung ohne unnötige 422-Blockaden zu gewährleisten.

### 3.4 Integration in `main.py`
- Registrierung der `SecurityHeadersMiddleware`.
- Traversal-sichere Routenabwicklung.

---

## 4. Security Checkliste für das Projekt

- [x] Command-Injection-Prüfung & Sanitization für alle Shell-Steps aktiv.
- [x] SSRF-Schutz für HTTP-Ping Steps implementiert.
- [x] Pfad-Traversal-Schutz für `/` und statische Ressourcen verifiziert.
- [x] Security-Header (X-Content-Type-Options, X-Frame-Options, CSP) aktiv.
- [x] Keine hartcodierten Secrets im Quellcode.
- [x] Async Timeout-Schutz gegen Denial of Service (Hanging Subprocesses).
- [x] Sichere Pydantic Schema-Validierung aktiv.
