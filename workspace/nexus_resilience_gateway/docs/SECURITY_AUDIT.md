# Security Audit Report: Nexus Resilience Gateway

**Projekt:** Nexus Resilience Gateway  
**Datum:** 2025-05-18  
**Auditor:** Senior Security Engineer & Penetration Tester  
**Fokus:** OWASP Top 10, Replay-Schutz, Payload-Sanitization, Pydantic v2 Validierung, API-Sicherheit  

---

## 1. Executive Summary

Das **Nexus Resilience Gateway** fungiert als sicherheitskritisches Eintrittstor (Ingress Proxy & Webhook Gateway) für mandantenfähige Microservice-Architekturen. Eine umfassende Überprüfung des bestehenden Codes deckte mehrere kritische bis mittlere Sicherheitsrisiken auf:
1. **Kritisch:** CORS-Fehlkonfiguration (`allow_origins=["*"]` kombiniert mit `allow_credentials=True`).
2. **Hoch:** Replay-Angriffe durch fehlende Nonce-Validierung (nur Timestamp-Fenster vorhanden).
3. **Hoch:** Fehlen von Pydantic v2 Payload-Validierung & Input-Sanitization für Ingress-Proxies (Gefahr von ReDoS, Payload-Injection und unkontrollierter Speicherauslastung).
4. **Hoch:** Fehlende Beschränkung der maximalen Request-Body-Größe (DoS durch Unbounded Memory Consumption).
5. **Mittel:** Unmaskierte PII / vertrauliche Daten in Logging und Fehlermeldungen.

Durch die Einführung von `app/core/security.py` und der Absicherung von `app/main.py` wurden alle Schwachstellen behoben.

---

## 2. Findings & Schweregrad-Klassifizierung

| ID | Schwachstelle | OWASP Top 10 | Schweregrad | Status |
|---|---|---|---|---|
| **SEC-01** | CORS Wildcard mit Credentials | A05:2021 - Security Misconfiguration | **Kritisch** | Behoben |
| **SEC-02** | Replay-Attacken via fehlende Nonce-Prüfung | A07:2021 - Identification & Authentication Failures | **Hoch** | Behoben |
| **SEC-03** | Fehlende Pydantic v2 Validierung & Payload Sanitization | A03:2021 - Injection / A04:2021 - Insecure Design | **Hoch** | Behoben |
| **SEC-04** | Unbegrenzte Request-Payload-Größe (DoS) | A05:2021 - Security Misconfiguration | **Hoch** | Behoben |
| **SEC-05** | Sensitive Exception-Leaks & Unmaskierte Identifier | A09:2021 - Security Logging and Monitoring Failures | **Mittel** | Behoben |

---

## 3. Detaillierte Befundanalyse & Threat Modeling

### SEC-01: CORS Wildcard mit Credentials (Kritisch)
- **Beschreibung:** Die Konfiguration `allow_origins=["*"]` mit `allow_credentials=True` verstößt gegen die W3C/Fetch-Spezifikation und erlaubt potenziell Cross-Origin Read Exploits, wenn Browser strikte Regeln nicht erzwingen oder Proxies die Header unbedacht spiegeln.
- **Bedrohung:** Ein bösartiger Angreifer kann über eine fremde Webseite authentifizierte Anfragen im Kontext des Opfers an das Gateway leiten.
- **Fix:** Explizite Whitelist aus Konfiguration (`ALLOWED_ORIGINS`) und Deaktivierung von Wildcards.

### SEC-02: Replay-Attacken via fehlende Nonce-Prüfung (Hoch)
- **Beschreibung:** Die bisherige Implementierung prüfte ausschließlich `abs(now - x_timestamp) > 300`. Innerhalb dieses 5-Minuten-Zeitfensters konnte ein abgefangener Request mit gültiger Signatur beliebig oft erneut gesendet werden (Replay-Angriff, z. B. doppelte Zahlungs-Webhooks).
- **Bedrohung:** Duplizierung von Transaktionen und Manipulation von Zielsystemen durch Netzwerk-Lauscher.
- **Fix:** Einführung eines In-Memory Nonce-Speichers mit TTL (`NonceReplayCache`), der Nonces an Tenant-IDs bindet und jeden Request innerhalb des Gültigkeitsfensters idempotenz-geprüft serialisiert.

### SEC-03: Fehlende Pydantic v2 Payload Validierung & Sanitization (Hoch)
- **Beschreibung:** Eingehende Body-Bytes wurden ungeprüft und unvalidiert weitergeleitet (`len(raw_body)`). JSON-Payloads wurden weder typisiert noch auf schädliche Muster (XSS-Tags, Steuerzeichen, Tiefenrekursion) hin validiert.
- **Bedrohung:** XSS in Downstream-Dashboards, SQL-/NoSQL-Injection in nachgelagerten Services sowie Speicherüberlauf durch tief verschachtelte JSON-Objekte.
- **Fix:** Definition von Pydantic v2 Schemata (`GatewayProxyPayload`, `WebhookPayloadModel`) mit rekursiver String-Bereinigung (`sanitize_text`), Längenbeschränkungen und Strip-Whitespace.

### SEC-04: Unbegrenzte Request-Payload-Größe (Hoch)
- **Beschreibung:** `await request.body()` las den gesamten Body ohne Vorab-Prüfung von `Content-Length` oder Stream-Limitierung in den Arbeitsspeicher.
- **Bedrohung:** Denial of Service durch gezieltes Senden gigantischer Payloads (z.B. Gigabyte-Streams).
- **Fix:** Durchsetzung eines Limits (Standard: 2 MB pro Request) vor dem Puffern im Speicher mit `HTTP 413 Payload Too Large`.

---

## 4. Vorher / Nachher Code-Vergleiche

### SEC-01: CORS Konfiguration
```python
# VORHER: Unsichere Wildcards
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# NACHHER: Whitelist & explizite Methoden
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in ALLOWED_ORIGINS if origin.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["X-Tenant-ID", "X-Signature", "X-Timestamp", "X-Nonce", "Content-Type", "Authorization"],
)
```

### SEC-02 & SEC-03: Replay-Schutz & Pydantic v2 Sanitization
```python
# VORHER: Reines Timestamp-Delta ohne Nonce, kein Schema
if abs(now - req_time) > 300:
    raise HTTPException(...)
raw_body = await request.body()

# NACHHER: Pydantic v2 Schema + Sanitization + Nonce-Prüfung
payload = validate_and_sanitize_payload(raw_body)
nonce_cache.verify_and_store(tenant_id=x_tenant_id, nonce=x_nonce, timestamp=req_time)
```

---

## 5. Security-Checkliste für den Produktivbetrieb

- [x] **HMAC-SHA256 Signaturprüfung:** Kryptografisch sicherer Vergleich mit `hmac.compare_digest` gegen Timing-Angriffe.
- [x] **Replay-Schutz:** Timestamp-Toleranz (±300s) kombiniert mit kryptografisch eindeutigem `X-Nonce`-Cache.
- [x] **Pydantic v2 Validierung:** Vollständige Schemavalidierung und Feldbeschränkung für alle Ingress-Payloads.
- [x] **Input-Sanitization:** Automatische Entfernung gefährlicher HTML/Script-Artefakte und Null-Bytes.
- [x] **CORS & Host-Whitelisting:** Keine Wildcards mehr bei aktivierten Credentials.
- [x] **DoS-Schutz:** Maximale Payload-Größe (2 MB) hart durchgesetzt.
- [x] **PII-Maskierung:** Anonymisierung von Mandanten- und Header-Informationen in Logfiles.
- [x] **Sichere Zufallswerte:** Verwendung von `secrets`-Modul für Session- und Fallback-Tokens.
