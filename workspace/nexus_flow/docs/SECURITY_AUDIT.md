# Sicherheits-Audit-Bericht: nexus_flow

**Projekt:** nexus_flow (FastAPI Event-Ingestion & Webhook-Stream-Service)  
**Datum:** September 2026  
**Auditor:** Senior Security Engineer & Penetration Tester  
**Status:** Findings identifiziert & Härtungsmaßnahmen implementiert  

---

## 1. Management Summary & Bedrohungsmodell (Threat Modeling)

nexus_flow ist ein asynchroner Event-Ingestion- und Webhook-Dispatching-Dienst. Die primären Angriffsvektoren umfassen:
1. **SSRF (Server-Side Request Forgery) via Webhook Subscriptions:** Angreifer registrieren Webhook-URLs, die auf interne Cloud-Metadaten (z. B. `169.254.169.254`), Loopback (`127.0.0.1`, `localhost`) oder interne private Netzwerke (RFC 1918) verweisen, um vertrauliche Daten abzugreifen oder interne Dienste zu kompromittieren.
2. **Denial of Service (DoS) via Unbounded Payloads:** Fehlen von Größenbeschränkungen bei Ingestion-Payloads kann zu Memory Exhaustion und Datenbank-Überlastung führen.
3. **CORS & Host Injection:** Ungeschützte Wildcard-CORS- und Host-Konfigurationen in Multi-Tenant- oder Unternehmensumgebungen.
4. **Fehlende Security HTTP-Header:** Ermöglicht Clickjacking, MIME-Sniffing und Information Disclosure.
5. **Kryptographische Härtung:** Sicherstellung von zeitkonstantem HMAC-Vergleich (`hmac.compare_digest`) und robuster Secret-Generierung.

---

## 2. Zusammenfassung der Findings

| ID | Schweregrad | Kategorie | Beschreibung | Status |
|---|---|---|---|---|
| **SEC-01** | **Kritisch** | SSRF (CWE-918) | Keine URL-Validierung / IP-Filterung beim Webhook-Dispatching. Private IPs, Loopback und Cloud-Metadaten erreichbar. | **Behoben** |
| **SEC-02** | **Hoch** | API / DoS (CWE-400) | Keine Begrenzung der Ingestion-Payload-Größe und fehlende URL-Validierung in Schemas. | **Behoben** |
| **SEC-03** | **Mittel** | Konfiguration (CWE-942) | CORS `allow_origins=["*"]` statisch konfiguriert; keine Trusted-Host-Beschränkung. | **Behoben** |
| **SEC-04** | **Mittel** | HTTP-Sicherheit (CWE-693) | Fehlende Sicherheits-Header (X-Content-Type-Options, X-Frame-Options, HSTS). | **Behoben** |
| **SEC-05** | **Niedrig** | Information Disclosure | Server-Versions-Header und unmaskierte Fehlerdetails in HTTP-Antworten. | **Behoben** |

---

## 3. Detaillierte Findings & Code-Fixes

### SEC-01: Server-Side Request Forgery (SSRF) im Webhook-Dispatcher
- **Schweregrad:** **Kritisch** (CVSS: 9.1)
- **Beschreibung:**  
  In `app/services/webhook_dispatcher.py` sendete `WebhookDispatcher._send_http_request` Anfragen an beliebige Ziel-URLs aus `SubscriptionModel.url`, ohne das Schema (`http`/`https`) einzuschränken oder die IP-Adresse nach DNS-Auflösung gegen private IP-Bereiche (RFC 1918, RFC 3927, RFC 6890, Loopback, Link-Local) abzusichern.
- **Risiko:**  
  Ein Angreifer kann über Subscription-Registrierungen AWS/GCP-Instanz-Metadaten (`http://169.254.169.254/latest/meta-data/`) oder lokale Admin-Ports (`http://127.0.0.1:8000`, `http://localhost:6379`) ansteuern und exfiltrieren.
- **Behebung:**  
  Implementierung eines dedizierten SSRF-Validators `validate_webhook_url` in `app/core/security.py`, der:
  1. Nur `http` und `https` erlaubt (standardmäßig HTTPS empfohlen).
  2. DNS auflöst und gegen IPv4/IPv6 Private-, Loopback-, Link-Local- und Reserved-Subnetze prüft.
  3. Integration des Prüfschritts direkt im `WebhookDispatcher` vor jedem Dispatch-Versuch.

#### Vorher:
```python
async def _send_http_request(self, url: str, payload_bytes: bytes, headers: Dict[str, str]):
    async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
        return await client.post(url, content=payload_bytes, headers=headers)
```

#### Nachher:
```python
is_safe, error_msg = validate_webhook_url(subscription.url, allow_private=settings.ALLOW_PRIVATE_WEBHOOKS)
if not is_safe:
    attempt.status = DeliveryStatus.FAILED.value
    attempt.error_message = f"SSRF Guard: {error_msg}"
    await session.commit()
    return attempt
```

---

### SEC-02: Input-Validierung & DoS-Prävention (Payload Size & URLs)
- **Schweregrad:** **Hoch** (CVSS: 7.5)
- **Beschreibung:**  
  Fehlende Längenbegrenzung für Ingestion-Payloads, Event-Typen und Idempotency-Keys sowie fehlende Pydantic-Validierung für Webhook-Zieladressen.
- **Risiko:**  
  Speicherüberlastung, DB-Bloat und Denial-of-Service durch Riesenpayloads (>100MB).
- **Behebung:**  
  - Bereitstellung von Konstanten und Validatoren in `app/core/security.py` (`MAX_PAYLOAD_BYTES = 1_048_576` = 1MB).
  - Validierung von Idempotency-Keys auf sichere Zeichensätze (keine Steuerzeichen, Längenbeschränkung max 128 Zeichen).

---

### SEC-03: CORS & Host-Härtung
- **Schweregrad:** **Mittel** (CVSS: 5.3)
- **Beschreibung:**  
  `allow_origins=["*"]` war in `app/main.py` ungeschützt hardcodiert.
- **Behebung:**  
  Konfigurierbare CORS-Origins über `Settings.ALLOWED_CORS_ORIGINS` und Unterstützung von Trusted-Host-Middleware.

---

### SEC-04: Fehlende Security Response Header
- **Schweregrad:** **Mittel** (CVSS: 5.0)
- **Beschreibung:**  
  API-Antworten enthielten keine standardmäßigen Browser- und API-Sicherheitsheader.
- **Behebung:**  
  Bereitstellung der `SecurityHeadersMiddleware` in `app/core/security.py`:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `X-XSS-Protection: 0` (Moderne Deaktivierung fehleranfälliger Filter)
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Content-Security-Policy: default-src 'none'; frame-ancestors 'none';`

---

## 4. Security Checkliste für nexus_flow

- [x] **SSRF-Schutz:** Validierung aller Webhook-URLs vor Dispatch & Auflösung gegen private/loopback/metadata Subnetze.
- [x] **Timing-Attack Resilience:** HMAC-Verifizierung nutzt `hmac.compare_digest`.
- [x] **Input-Validation:** Begrenzung von Event-Payload-Größen (1MB) und Idempotency-Keys.
- [x] **Security-Header:** Integration von Security Headers Middleware.
- [x] **CORS:** Keine Kombination von Wildcard Origins mit Credentials; konfigurierbare Whitelist.
- [x] **SQL-Injection:** Vollständige Nutzung von SQLAlchemy 2.0 ORM / parametrisierten Statements (kein raw SQL string formatting).
- [x] **Secret-Management:** Keine fest verdrahteten Secrets; HMAC-Secrets werden pro Subscription generiert/gespeichert.
- [x] **Exception Hygiene:** Spezifisches Abfangen von Exceptions ohne Maskierung unerwarteter Systemfehler (Einhaltung BLE001-Regel).

---

## 5. Fazit

Mit den implementierten Härtungen in `app/core/security.py` und der Absicherung des `WebhookDispatcher` ist `nexus_flow` gegen SSRF-Angriffe, Injection-Vektoren und unkontrollierte Payload-Exhaustion wirksam geschützt.
