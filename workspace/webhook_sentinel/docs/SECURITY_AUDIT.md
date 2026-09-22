# Security Audit Report: Webhook Sentinel

## 1. Management Summary
Das Projekt wurde auf Sicherheitslücken im Bereich SSRF (Server-Side Request Forgery), Kryptographie (HMAC) und allgemeine API-Sicherheit geprüft. Die Kernanforderungen an die Sicherheit wurden analysiert und entsprechende Härtungsmaßnahmen implementiert.

## 2. Findings

### 2.1. Fehlende CORS-Konfiguration (Hoch)
**Beschreibung:** Wie aus früheren Projekten gelernt, fehlt standardmäßig oft eine strikte CORS-Konfiguration. Ohne explizite CORS-Richtlinien ist die API anfällig für unautorisierte Cross-Origin-Anfragen aus dem Browser.
**Lösung:** Implementierung einer strikten CORS-Middleware in `app/core/security.py`. `allow_origins=["*"]` in Kombination mit `allow_credentials=True` wird strikt vermieden.

### 2.2. SSRF-Schutz (Mittel)
**Beschreibung:** Der Backend-Entwickler hat bei der Subscription-Anlage nur einen grundlegenden SSRF-Schutz (Blockieren von `localhost` und `127.0.0.1`) implementiert. Im `WebhookDispatcher` (`app/services/dispatcher.py`) existiert jedoch bereits die Funktion `is_ssrf_safe_url`, die eine vollständige DNS-Auflösung durchführt und private/lokale Netze (`is_private`, `is_loopback`, etc.) blockiert.
**Lösung:** Die Funktion `is_ssrf_safe_url` wird vor jedem HTTP-Aufruf im Dispatcher verwendet. Dies schützt vor SSRF. 
**Hinweis zu DNS-Rebinding:** Da die URL im Dispatcher validiert, aber danach vom `httpx.AsyncClient` erneut aufgelöst wird, besteht ein theoretisches Restrisiko für DNS-Rebinding. Für den aktuellen Scope ist der Schutz jedoch adäquat.

### 2.3. HMAC-Signierung (Info)
**Beschreibung:** Die HMAC-SHA256 Signierung in `generate_hmac_signature` (`app/services/dispatcher.py`) ist korrekt implementiert. Sie nutzt `hmac.new` mit `hashlib.sha256` und ist resistent gegen Timing-Angriffe, da sie nur generiert und nicht verglichen wird (der Empfänger muss `hmac.compare_digest` nutzen).

## 3. Security Checkliste
- [x] SSRF-Schutz für Webhook-URLs (Private IPs & Loopback blockiert via DNS-Auflösung)
- [x] HMAC-SHA256 Signatur für ausgehende Webhooks
- [x] CORS-Konfiguration implementiert (kein Wildcard mit Credentials)
- [x] Keine sensiblen Daten im Klartext in Logs (Exception-Handling geprüft)
- [ ] DNS-Rebinding-Schutz auf Netzwerkebene (Empfehlung für DevOps/Infrastruktur)
