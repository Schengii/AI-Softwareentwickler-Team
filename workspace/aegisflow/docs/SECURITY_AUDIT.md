# Security Audit Report - AegisFlow

## Findings

### 1. SSRF Vulnerability in Webhook Dispatching (Kritisch)
**Beschreibung:** Webhook-URLs werden ohne Validierung aufgerufen. Ein Angreifer könnte interne IPs (z.B. `127.0.0.1`, `169.254.169.254` für AWS Metadata) angeben, um interne Systeme zu scannen oder anzugreifen.
**Lösung:** Implementierung einer Whitelist/Blacklist-Validierung für URLs in `app/core/security.py` (`is_safe_url`), die private IP-Bereiche (RFC 1918) und interne Hostnamen blockiert.
**Aktion für Backend:** Nutze `is_safe_url` aus `app.core.security` in `app/services/event_service.py` vor dem Dispatching.

### 2. Fehlende Payload-Validierung (Hoch)
**Beschreibung:** Das Event-Payload in `app/models/event.py` hat keine Größenbeschränkung. Dies kann zu DoS-Angriffen führen, wenn riesige Payloads gesendet werden.
**Lösung:** Füge in `app/models/event.py` einen Pydantic-Validator hinzu, der die Payload-Größe (z.B. auf 64KB) beschränkt.
**Aktion für Backend:** Ergänze `EventCreate` in `app/models/event.py` um einen `@field_validator("payload")`, der die Größe via `len(json.dumps(v))` prüft.

### 3. Unsichere FastAPI Defaults (Mittel)
**Beschreibung:** Es fehlen sichere HTTP-Header (HSTS, X-Content-Type-Options) und eine strikte CORS-Konfiguration.
**Lösung:** Implementierung von `SecurityHeadersMiddleware` und striktem CORS in `app/core/security.py`.
**Aktion für Backend:** Rufe `setup_security(app)` aus `app.core.security` in `app/main.py` auf.

## Checkliste
- [x] SSRF-Präventions-Logik implementiert (`app/core/security.py`)
- [x] Security Middleware für sichere Header und CORS implementiert (`app/core/security.py`)
- [ ] Backend: Payload-Validierung in `app/models/event.py` einbauen
- [ ] Backend: `setup_security(app)` in `app/main.py` einbinden
- [ ] Backend: `is_safe_url` in `app/services/event_service.py` nutzen
