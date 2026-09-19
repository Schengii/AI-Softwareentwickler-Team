# Security Audit Report: Sentinedge

## Executive Summary
Das Security-Audit der Anwendung `sentinedge` hat mehrere Schwachstellen aufgedeckt, die umgehend behoben wurden. Die kritischsten Probleme betrafen die blockierende Ausführung von rechenintensiven Krypto-Operationen im asynchronen Event-Loop sowie fehlende CORS-Konfigurationen.

## Findings

### 1. CPU-bound Hashing im Async-Kontext (Kritisch)
**Beschreibung:** Die Funktionen `hash_api_key` und `verify_api_key` nutzten `bcrypt` direkt im asynchronen Event-Loop. Da `bcrypt` CPU-intensiv ist, blockiert dies den gesamten FastAPI-Prozess für andere Anfragen und führt zu Denial of Service (DoS) bei hoher Last.
**Lösung:** Auslagerung der `bcrypt`-Aufrufe in separate Worker-Threads mittels `fastapi.concurrency.run_in_threadpool`.

### 2. Fehlende CORS-Konfiguration (Kritisch)
**Beschreibung:** Die FastAPI-Anwendung hatte keine explizite CORS-Konfiguration. Dies kann zu unerwünschtem Zugriff aus dem Browser führen oder legitime Frontends blockieren.
**Lösung:** Implementierung der `CORSMiddleware` mit einer expliziten Whitelist (`allow_origins`), anstelle von Wildcards (`*`).

### 3. Timing-Attacken bei API-Key-Verifizierung (Hoch)
**Beschreibung:** Wenn eine ungültige Key-ID übergeben wurde, brach die Funktion `get_current_api_key` sofort ab. Dies ermöglichte Angreifern, durch Zeitmessung gültige Key-IDs zu erraten (User Enumeration).
**Lösung:** Implementierung eines Dummy-Hash-Vergleichs, falls der Schlüssel nicht in der Datenbank gefunden wird, um die Antwortzeit anzugleichen.

### 4. Fehlende PII-Maskierung im Audit-Log (Mittel)
**Beschreibung:** Die Funktion `log_audit` speicherte die übergebenen `details` unmaskiert in der Datenbank. Dies könnte dazu führen, dass sensible Daten (wie Secrets oder Passwörter) im Klartext im Audit-Log landen.
**Lösung:** Einführung einer rekursiven `mask_pii`-Funktion, die sensible Schlüssel (z.B. "secret", "password") vor dem Speichern maskiert.

## Security Checkliste
- [x] CPU-bound Krypto-Operationen in Threadpools ausgelagert
- [x] CORS-Middleware mit expliziter Whitelist konfiguriert
- [x] Timing-Attacken bei der Authentifizierung mitigiert
- [x] PII-Maskierung für Audit-Logs implementiert
- [x] API-Key Hashing mit sicherem Salt (bcrypt)
- [x] Granulares RBAC-System aktiv
- [x] AES-256-GCM für Secret-Verschlüsselung aktiv
