# Security Audit Report: ChronoFlow

## 1. 🔍 Übersicht
- **Datum:** 2026-09-17
- **Auditor:** Security Engineer
- **Fokus:** API-Sicherheit, Input-Validierung, Security-Headers, Idempotenz-Schutz

## 2. 🚨 Findings & Fixes

### Finding 1: Fehlende Input-Validierung bei Saga-Erstellung
- **Schweregrad:** Hoch
- **Beschreibung:** Die Pydantic-Modelle in `app/schemas/saga.py` akzeptierten beliebige Strings für `workflow_type` und unbegrenzte Payloads, was zu DoS oder Injection-Angriffen führen könnte.
- **Fix:** Hinzufügen von `pydantic.Field` mit `min_length`, `max_length` und `pattern` (Regex) für strikte Validierung.
- **Status:** Behohen in `app/schemas/saga.py`.

### Finding 2: Fehlende Security-Headers
- **Schweregrad:** Mittel
- **Beschreibung:** Die FastAPI-Anwendung sendete keine sicherheitsrelevanten HTTP-Header (wie CSP, X-Frame-Options, X-Content-Type-Options), was XSS- und Clickjacking-Angriffe begünstigt.
- **Fix:** Implementierung einer `SecurityHeadersMiddleware` in `app/main.py`, die `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff` und `Strict-Transport-Security` setzt.
- **Status:** Behoben in `app/main.py`.

### Finding 3: Unzureichende Validierung des Idempotency-Keys
- **Schweregrad:** Hoch
- **Beschreibung:** Der `Idempotency-Key` Header wurde ohne Längen- oder Formatprüfung direkt in die Datenbankabfrage übernommen. Dies öffnet Vektoren für SQL-Injection (obwohl SQLAlchemy Parameterbindung nutzt, ist es Best Practice, Inputs zu validieren) und DoS durch extrem lange Keys.
- **Fix:** Hinzufügen von Pydantic-Constraints (`min_length`, `max_length`, `pattern`) direkt im `Header`-Parameter in `app/api/sagas.py`.
- **Status:** Behoben in `app/api/sagas.py`.

### Finding 4: Fehlende Validierung von Pfad-Parametern
- **Schweregrad:** Mittel
- **Beschreibung:** Der `saga_id` Pfad-Parameter in `GET /api/v1/sagas/{saga_id}` wurde nicht validiert.
- **Fix:** Hinzufügen von `Path`-Constraints in `app/api/sagas.py`.
- **Status:** Behoben in `app/api/sagas.py`.

## 3. ✅ Security-Checkliste
- [x] Input-Validierung (Pydantic Constraints)
- [x] Security-Headers (CSP, HSTS, X-Frame-Options)
- [x] Idempotenz-Schutz (Format-Validierung des Keys)
- [x] Keine Hardcoded Secrets (Nutzung von `.env` via `app/core/config.py`)
- [x] Sichere Datenbankabfragen (SQLAlchemy ORM)
