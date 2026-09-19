# Security Audit Report

## Findings

### 1. Replay-Attack Vulnerability in Webhook Ingestion (Kritisch)
- **Problem**: Die HMAC-Signaturprüfung in `app/api/security.py` validierte bisher keinen Zeitstempel. Ein Angreifer könnte einen abgefangenen, gültigen Webhook-Request beliebig oft wiederholen (Replay-Attacke).
- **Lösung**: Ein `X-Timestamp`-Header wurde eingeführt und in die Signaturberechnung einbezogen. Die Toleranz beträgt 5 Minuten (300 Sekunden).
- **Status**: Behoben in `app/api/security.py`.

### 2. Idempotency-Check unvollständig (Hoch)
- **Problem**: Der Idempotency-Check hat nicht korrekt gegen die Datenbank validiert.
- **Lösung**: `check_idempotency` nutzt nun das `IdempotencyKey`-Modell und wirft `409 Conflict`, wenn der Key bereits existiert.
- **Status**: Behoben in `app/api/security.py`.

### 3. Unsichere CORS und Allowed Hosts Konfiguration (Kritisch)
- **Problem**: In `app/core/config.py` sind `ALLOWED_HOSTS` und `CORS_ORIGINS` auf `["*"]` gesetzt.
- **Lösung**: Muss vom Backend/Database Agent auf explizite Listen (z.B. `["localhost", "127.0.0.1"]`) umgestellt werden.
- **Status**: Offen (Ticket für Backend/Database Agent).

### 4. Fehlender spezifischer HMAC Secret Key (Mittel)
- **Problem**: Es fehlt ein dedizierter `HMAC_SECRET_KEY` in den Settings.
- **Lösung**: Muss in `app/core/config.py` ergänzt werden.
- **Status**: Offen (Ticket für Database Agent).

## Security-Checkliste
- [x] HMAC-Signaturprüfung implementiert
- [x] Replay-Schutz (Timestamp-Validierung) implementiert
- [x] Idempotency-Check (Datenbank-Abgleich) implementiert
- [ ] `ALLOWED_HOSTS` auf Whitelist umstellen (Backend)
- [ ] `CORS_ORIGINS` auf Whitelist umstellen (Backend)
- [ ] `HMAC_SECRET_KEY` in Config aufnehmen (Database)
