# Security Audit Report - EventStream-Zero

## 1. Übersicht
Dieses Dokument enthält die Sicherheitsrichtlinien und Findings für das EventStream-Zero Projekt.

## 2. Findings & Implementierungen

### [Kritisch] Fehlende Authentifizierung & Autorisierung
- **Risiko:** Jeder kann auf die API zugreifen, Topics erstellen und Nachrichten lesen/schreiben.
- **Fix:** Implementierung von JWT-basierter Authentifizierung mit RBAC (Role-Based Access Control) in `app/security/auth.py`.

### [Kritisch] Unverschlüsselte Speicherung von Payloads
- **Risiko:** Sensible Daten im WAL können bei Kompromittierung des Dateisystems im Klartext gelesen werden.
- **Fix:** Implementierung von AES-256-GCM Authenticated Encryption in `app/security/crypto.py`.

### [Hoch] Fehlendes Audit-Logging
- **Risiko:** Sicherheitsrelevante Ereignisse (Logins, abgelehnte Zugriffe) sind nicht nachvollziehbar.
- **Fix:** Strukturiertes JSON-Logging in `app/security/audit.py` implementiert.

## 3. Security Checkliste
- [x] JWT-Authentifizierung (HS256) implementiert
- [x] RBAC (admin, producer, consumer) integriert
- [x] AES-256-GCM Payload-Verschlüsselung mit Nonce/Tag
- [x] Strukturiertes JSON Audit-Logging
- [ ] Rate-Limiting für API-Endpunkte (ausstehend)
- [ ] TLS/HTTPS Konfiguration für Produktion (ausstehend)
- [x] Pre-Flight-Checks: `__init__.py` Dateien in Modulpfaden hinzugefügt.
