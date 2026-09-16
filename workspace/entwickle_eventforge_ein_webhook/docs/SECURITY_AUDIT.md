# Security Audit & Pentest Report: EventForge Webhook Gateway

**Projekt:** EventForge - Webhook-Testing- und Relay-Gateway  
**Auditor:** Senior Security Engineer & Penetration Tester  
**Datum:** 2026-09-16  
**Status:** Audit abgeschlossen & Schutzmaßnahmen implementiert  

---

## 1. Management Summary & Bedrohungsmodell (Threat Modeling)

EventForge verarbeitet als Webhook-Testing- und Relay-Gateway unauthentifizierte eingehende HTTP-Anfragen aus dem Internet und leitet diese optional an vom Benutzer konfigurierte Relay-URLs weiter. Diese Architektur exponiert typischerweise hochkritische Angriffsvektoren:

1. **Server-Side Request Forgery (SSRF) im Relay-Worker (Kritisch):**
   - Angreifer konfigurieren Buckets mit `http://127.0.0.1:8000`, `http://169.254.169.254` (Cloud Instance Metadata Service / AWS IMDS / GCP / Azure) oder RFC1918-IPs (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`).
   - Folge: Remote-Angreifer können interne Microservices scannen, Cloud-Credentials extrahieren und interne Admin-Schnittstellen ansprechen.

2. **Denial of Service (DoS) durch unbegrenzte Payload-Größen (Hoch):**
   - Unbegrenzte Body-Größen bei Ingestion (`/hook/{bucket_id}`) führen zu Memory Exhaustion und SQLite/Disk Flooding.

3. **Unsichere CORS- & Host-Konfiguration (Hoch):**
   - `allow_origins=["*"]` in Kombination mit `allow_credentials=True` verstößt gegen W3C CORS Spec und Best Practices; Hosts waren nicht restriktiv validiert.

4. **Fehlende HTTP-Sicherheitsheader (Mittel):**
   - Mangel an `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Strict-Transport-Security`, `Content-Security-Policy` ermöglicht Clickjacking und MIME-Sniffing im ausgelieferten SPA-Dashboard.

5. **PII-Exposition & sensible Daten im Log (Mittel):**
   - Authorization-Tokens, Passwörter und Tokens in Query-Strings oder Body-Payloads dürfen nicht unmaskiert im Log landen.

---

## 2. Strukturierte Findings & Schweregrad-Klassifizierung

| ID | Befund | Komponente | Schweregrad | Status |
|---|---|---|---|---|
| **SEC-01** | Server-Side Request Forgery (SSRF) via Forwarding-URL | `app/core/security.py`, `app/main.py` | **Kritisch** | Behoben |
| **SEC-02** | DoS via unbeschränkte Payload-Größe (Memory/Disk Exhaustion) | `app/main.py`, Ingestion-Endpoint | **Hoch** | Behoben |
| **SEC-03** | CORS Misconfiguration (`allow_origins=['*']` mit `credentials`) | `app/main.py` | **Hoch** | Behoben |
| **SEC-04** | Fehlende HTTP Security Header (CSP, HSTS, X-Frame-Options, etc.) | `app/core/security.py` | **Mittel** | Behoben |
| **SEC-05** | PII & Secret Leakage in Logs | `app/core/security.py` | **Mittel** | Behoben |
| **SEC-06** | Fehlen von DNS-Rebinding-Schutz bei Relay-Auflösung | `app/core/security.py` | **Hoch** | Behoben |

---

## 3. Detaillierte Schwachstellenanalyse & Code-Fixes

### SEC-01: Server-Side Request Forgery (SSRF) im Relay-Worker
- **Risiko:** Angreifer registrieren Buckets mit internen Zielen (`localhost`, `127.0.0.1`, `10.0.0.0/8`, `169.254.169.254`, `[::1]`).
- **Fix:** Strenge URL-Validierung mittels `ipaddress`-Modul und DNS-Resolution Check. Verbot von Loopback, RFC1918, RFC6598 (Carrier-Grade NAT), Link-Local (`169.254.0.0/16`), IPv6 Multicast/Site-Local sowie reservierten Bereichen. Erlaubt sind ausschließlich `http` und `https` auf öffentlichen IPv4/IPv6-Adressen.
- **Implementierung:** `validate_relay_url()` in `app/core/security.py`.

### SEC-02: DoS & Ingestion Payload Limit
- **Risiko:** Riesige POST-Bodies (z. B. 1 GB) bringen die Anwendung durch Memory Allocations oder Disk Full zum Stillstand.
- **Fix:** Konfigurierbares Payload-Limit (Standard: 1 MB für Webhooks). Prüft `Content-Length` im Header vor dem Lesen und bricht bei Überschreitung mit HTTP 413 (Payload Too Large) ab; zusätzlich Stream-Limitierung.

### SEC-03: CORS Hardening
- **Risiko:** `allow_origins=["*"]` zusammen mit `allow_credentials=True` öffnet Cross-Origin-Schwachstellen.
- **Fix:** Entfernung von Wildcard-Credentials-Kombination. Konfigurierbare Ursprünge; falls Wildcard aktiv, ist `allow_credentials=False`.

### SEC-04: Security Header Middleware
- **Fix:** Middleware setzt folgende Header für jede HTTP-Antwort:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `X-XSS-Protection: 1; mode=block`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self';`
  - `Permissions-Policy: geolocation=(), camera=(), microphone=()`

---

## 4. Security Checkliste für EventForge

- [x] SSRF-Schutz für alle Forwarding-/Relay-URLs (RFC1918, Loopback, Link-Local, Cloud-Metadata blockiert).
- [x] Schema-Validierung: Ausschließlich `http` und `https`.
- [x] Ingestion Payload Size Enforcement (HTTP 413 bei > 1 MB).
- [x] Security-Header-Middleware aktiv (`Content-Security-Policy`, `X-Frame-Options`, etc.).
- [x] CORS bereinigt (`allow_credentials=False` bei Wildcard).
- [x] PII-Maskierung für Logging (Tokens, Authorization-Header, Passwörter).
- [x] Sichere Fehlerbehandlung (keine Stacktrace-Leaks an Clients).
