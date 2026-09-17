# 🛡️ SECURITY AUDIT REPORT: Hyperion Metrics

**Audit-Datum:** 2026-09-17  
**Auditor:** Senior Security Engineer & Penetration Tester  
**Zielsystem:** hyperion_metrics (FastAPI Metrik-Ingestion & Alerting)

---

## 1. Executive Summary & Bedrohungsanalyse (Threat Model)
Das System *hyperion_metrics* nimmt Echtzeit-Metrikdaten via HTTP POST entgegen, verarbeitet diese über In-Memory-Queues und Aggregations-Pipelines und streamt Aggregationen und Alerts über WebSockets an Dashboards.

### Hauptrisikovektoren:
1. **Denial of Service (DoS) durch unbegrenzte Queue / Ingestion-Überlastung:**
   - Unbegrenzte `asyncio.Queue()` ohne Backpressure (`maxsize=0`) ermöglicht Speichererschöpfung (OOM) bei Spitzenlast.
   - Fehlendes Rate Limiting auf dem Ingestion-Endpunkt `POST /api/v1/metrics`.
2. **WebSocket Exhaustion & Slowloris Attack:**
   - Fehlende Begrenzung aktiver Verbindungen in `ConnectionManager`. Angreifer können Tausende WebSockets öffnen und Dateideskriptoren / Memory erschöpfen.
   - Fehlende Nachrichtengrößen- und Nachrichtenratenbegrenzung auf eingehende WebSocket-Frames.
3. **Payload Injection & Parameter Tampering:**
   - Fehlende Längenbeschränkungen und Zeichensatz-Sanitization für Metriknamen und Tags (XSS/Log Injection/ReDoS).
   - NaN / Infinite / extreme Float-Werte, die Rechenoperationen und JSON-Serialisierung korrumpieren können.
4. **Fehlende Security Header & CORS:**
   - Ungesicherte Standardkonfiguration ohne Security-Header (HSTS, CSP, X-Content-Type-Options, Frame-Options).

---

## 2. Findings & Schweregrad-Klassifizierung

| ID | Befund | Schweregrad | Status |
|---|---|---|---|
| **SEC-01** | Unbegrenzte Ingestion Queue & Fehlendes Backpressure Handling | **Kritisch** | Behoben |
| **SEC-02** | Fehlendes Rate Limiting & Überlastungsschutz für Ingestion-Endpunkt | **Hoch** | Behoben |
| **SEC-03** | Fehlendes Connection-Limit & DoS-Schutz auf WebSocket-Endpunkten | **Hoch** | Behoben |
| **SEC-04** | Unsanitisierte Metriknamen, Tags & Werte (Float-Anomalien, Log-Injection) | **Hoch** | Behoben |
| **SEC-05** | Fehlende HTTP Security Header & unzureichende Origin-Validierung | **Mittel** | Behoben |

---

## 3. Detaillierte Befunde & Gegenmaßnahmen

### SEC-01: Unbegrenzte Ingestion Queue & Fehlendes Backpressure (Kritisch)
- **Problem:** `ingestion_queue = asyncio.Queue()` besaß kein `maxsize`. Bei einem Ansturm an Ingestion-Anfragen lief der Prozess ungebremst mit Millionen Punkten voll, bis der Kernel den Prozess wegen OOM killt.
- **Fix:** Konfigurierbare Obergrenze (`MAX_QUEUE_SIZE`) mit `queue.put_nowait()` oder `asyncio.wait_for`. Bei voller Queue wird `503 Service Unavailable` mit `Retry-After` Header zurückgegeben (Backpressure).

### SEC-02: Rate Limiting auf Ingestion-Endpunkten (Hoch)
- **Problem:** Keine Client-seitigen Kontingente; ein einzelner fehlerhafter oder bösartiger Client konnte die gesamte Verarbeitungsbandbreite an sich reißen.
- **Fix:** Token-Bucket / Sliding-Window Rate-Limiter (`RateLimiter`) in `app/core/security.py`, basierend auf `time.monotonic()`. Schutz über IP- und Client-Tracking.

### SEC-03: WebSocket DoS & Connection Exhaustion (Hoch)
- **Problem:** `ConnectionManager` akzeptierte unbegrenzt Verbindungen. Keine Limits pro IP, kein globales Limit, unbegrenzte `receive_text()` Puffergröße.
- **Fix:** `MAX_WEBSOCKET_CONNECTIONS` und `MAX_CONNECTIONS_PER_IP` im `ConnectionManager`. Schließen mit WebSocket-Code `1008 (Policy Violation)` bzw. `1013 (Try Again Later)`.

### SEC-04: Metrik Input Sanitization & Validierung (Hoch)
- **Problem:** Metrik-Namen und Tag-Keys/Values erlaubten beliebige Zeichenketten (inkl. Control-Chars, CRLF für Log-Injection oder Script-Tags für Dashboards). Floats wurden nicht gegen `NaN`, `+Inf`, `-Inf` abgesichert.
- **Fix:** Strikte Regex-Sanitizer (`^[a-zA-Z0-9_.-]{1,128}$`), PII/Control-Char-Filterung, Float-Range-Checks und Prüfung auf finite Floats (`math.isfinite()`).

### SEC-05: HTTP Security Header & CORS (Mittel)
- **Problem:** Standard-FastAPI liefert keine Defensiv-Header (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, CSP).
- **Fix:** Integration einer `SecurityHeadersMiddleware` für alle HTTP-Responses.

---

## 4. Security Checkliste für Hyperion Metrics
- [x] In-Memory Queues mit striktem `maxsize` und 503-Backpressure versehen
- [x] In-Memory Rate-Limiter mit `time.monotonic()` implementiert
- [x] Metrik-Namen, Tags und Floating-Point-Werte strikt sanitisiert und validiert
- [x] WebSocket-Verbindungsanzahl global und pro Client begrenzt
- [x] WebSocket Message Size & Receive Timeout überwacht
- [x] Keine unsicheren `loop.time()` oder `asyncio.get_event_loop()` Aufrufe
- [x] HTTP Security Header (nosniff, frame-options, csp) aktiv
- [x] Unit- und Integrationstests für Security-Komponenten erfolgreich
