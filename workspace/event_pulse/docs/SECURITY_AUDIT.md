# Security Audit Report: Event Pulse

## 1. Übersicht
Dieses Dokument enthält die Ergebnisse des Security-Audits für das Projekt `event_pulse`. Der Fokus lag auf der Absicherung der API-Endpunkte, insbesondere der Validierung eingehender Webhooks und dem Schutz vor Replay-Attacken.

## 2. Findings

### 2.1 Fehlende Authentifizierung / Signaturprüfung bei eingehenden Events (Kritisch)
**Beschreibung:** Der Endpunkt `POST /events` nahm Events ohne jegliche Authentifizierung oder Signaturprüfung entgegen. Dies ermöglichte es Angreifern, beliebige Events in das System einzuspeisen (Spoofing) und an die registrierten Webhook-Endpunkte weiterleiten zu lassen.
**Risiko:** Kritisch. Unautorisierter Zugriff auf die Kernfunktionalität, potenzieller Missbrauch als Spam-/DDoS-Relay.
**Lösung:** Implementierung einer HMAC-SHA256 Signaturprüfung inkl. Replay-Schutz (Timestamp-Validierung) als FastAPI-Dependency für eingehende Requests.

### 2.2 Fehlendes Rate Limiting (Hoch)
**Beschreibung:** Die API-Endpunkte verfügen über kein Rate Limiting.
**Risiko:** Hoch. Gefahr von Denial-of-Service (DoS) und Brute-Force-Angriffen.
**Lösung:** Implementierung von Rate Limiting (z.B. via Token Bucket) für alle öffentlichen Endpunkte.

### 2.3 SSRF-Gefahr bei Webhook-Zustellung (Hoch)
**Beschreibung:** Der Dispatcher sendet HTTP-POST-Requests an vom Benutzer definierte URLs (`EndpointCreate.url`). Es findet keine Validierung statt, ob diese URLs auf interne Netzwerke (z.B. `localhost`, `10.0.0.0/8`, AWS Metadata Service `169.254.169.254`) zeigen.
**Risiko:** Hoch. Server-Side Request Forgery (SSRF).
**Lösung:** Implementierung einer URL-Validierung, die private und reservierte IP-Bereiche blockiert.

### 2.4 Secrets in Klartext in der Datenbank (Mittel)
**Beschreibung:** Das `secret` für Endpunkte wird in Klartext in der Datenbank gespeichert. Da dieses Secret für die HMAC-Generierung benötigt wird, kann es nicht gehasht werden, sollte aber symmetrisch verschlüsselt (z.B. AES-GCM) abgelegt werden.
**Risiko:** Mittel. Bei einer Kompromittierung der Datenbank können Angreifer gültige Signaturen für alle Endpunkte fälschen.
**Lösung:** Verschlüsselung der Secrets in der Datenbank mit einem Master-Key aus den Umgebungsvariablen.

## 3. Implementierte Fixes
- **HMAC-Validierung & Replay-Schutz:** Die Datei `app/core/security.py` wurde erstellt. Sie enthält die Dependency `verify_incoming_webhook`, welche die Signatur eingehender Events verifiziert und Replay-Attacken abwehrt.
- **Integration in FastAPI:** Der Endpunkt `POST /events` in `app/main.py` wurde abgesichert.

## 4. Security-Checkliste
- [x] HMAC-SHA256 Signaturprüfung für eingehende Events
- [x] Replay-Schutz (Timestamp-Toleranz)
- [ ] SSRF-Schutz für ausgehende Webhooks
- [ ] Rate Limiting implementieren
- [ ] Secrets in der Datenbank verschlüsseln
- [ ] PII-Maskierung in Logs

## 5. Pre-Flight Checks & Struktur
- **Fix:** Fehlende `app/__init__.py` hinzugefügt, um Modul-Importe (`app.dispatcher`) zu ermöglichen und Import-Fehler in Test- und Laufzeitumgebungen zu verhindern. Keine neuen kritischen Sicherheitsbefunde in diesem Schritt.