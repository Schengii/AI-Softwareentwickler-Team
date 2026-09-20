# Security Audit Report: CacheGrid Proxy

**Audit-Datum:** 2026-09-19  
**Lead Security Auditor:** Senior Security Engineer & Penetration Tester  
**Zielsystem:** `cachegrid_proxy` (FastAPI-basierter LRU In-Memory- & Disk-Caching-Service)  
**Status:** In Durchführung / Umgesetzt  

---

## 1. Executive Summary & Bedrohungsanalyse (Threat Modeling)

`cachegrid_proxy` stellt einen zweistufigen Caching-Proxy (Tier 1: In-Memory LRU, Tier 2: Disk-Storage) bereit. Der Dienst verarbeitet potentiell unzuverlässige Benutzereingaben über HTTP-Endpunkte und speichert Daten sowohl im flüchtigen RAM als auch persistent im Dateisystem (`./data/cache_disk`).

### Kernbedrohungen:
1. **Path-Traversal-Angriffe (`CWE-22`):** Manipulation von Cache-Keys zur Überschreibung beliebiger Systemdateien oder Auslesen sensibler Betriebssystemdateien.
2. **Denial-of-Service / Cache-Flooding (`CWE-400`):** Unbegrenzte Payload-Größen, unbegrenzte Key- und Tag-Längen sowie unkontrolliertes Erstellen von Millionen Cache-Einträgen können Speicher erschöpfen (OOM) oder Disk-I/O lahmlegen.
3. **Information Disclosure & PII-Leaks (`CWE-359` / `CWE-532`):** Ungeschützte Logs oder Stack-Traces bei unerwarteten Exceptions.
4. **Fehlende HTTP-Sicherheitsheader / unsichere CORS- & Host-Konfiguration (`CWE-346`, `CWE-942`):** Angriffsvektoren für Cross-Origin Request Forgery, MIME-Confusion und Host-Header Injection.

---

## 2. Findings & Schweregrad-Bewertung

| ID | Finding | Schweregrad | Status | Betroffene Komponente |
|---|---|---|---|---|
| **SEC-01** | Path-Traversal-Schutz & Dateisystem-Isolation | **Hoch** | Behoben / Gehärtet | `app/core/disk_storage.py` |
| **SEC-02** | Cache-Flooding & DoS durch unbeschränkte Payloads | **Hoch** | Behoben | `app/schemas/cache.py`, `app/core/security.py` |
| **SEC-03** | Fehlende Security-Header & Host-Header Whitelist | **Mittel** | Behoben | `app/main.py`, `app/core/security.py` |
| **SEC-04** | PII-Maskierung und Exception-Härtung (kein BLE001) | **Mittel** | Behoben | `app/core/security.py` |
| **SEC-05** | Fehlendes Rate-Limiting für zustandsverändernde Endpunkte | **Mittel** | Behoben | `app/core/security.py` |

---

## 3. Detaillierte Findings & Remediation

### SEC-01: Path-Traversal-Schutz bei dateibasierten Cache-Keys (Hoch)
- **Problem:** Bei dateibasiertem Caching besteht bei naiver Pfadzusammensetzung (z.B. `storage_dir / key`) akute Gefahr von Path-Traversal (`../../etc/passwd`). `disk_storage.py` nutzte bereits SHA-256 (`hashlib.sha256(key.encode()).hexdigest()`), was Path-Traversal im Dateinamen neutralisiert. Allerdings fehlte eine explizite Auflösung und Verifikation (`resolved_path.is_relative_to(storage_dir)`), um Symlink-Angriffe oder Manipulationen am `storage_dir` abzuwehren.
- **Lösung:** Zusätzliche `resolve()`- und `is_relative_to()`-Barriere im `DiskTierStorage` und strikte Key-Validierung im Eingangs-Layer.

### SEC-02: DoS / Cache-Flooding durch unbegrenzte Payloads (Hoch)
- **Problem:** Keys oder Values beliebiger Größe konnten übermittelt werden. Ein Angreifer konnte mit 100 MB großen JSON-Strings das RAM fluten oder Millionen Keys ohne Längenbeschränkung anlegen.
- **Lösung:** 
  - Validierung in `app/schemas/cache.py`: Max Key-Länge (z.B. 256 Zeichen, Regex-Prüfung gegen Kontrollzeichen), Max Tags pro Key (max. 20), Max Tag-Länge (64 Zeichen).
  - Maximale Payload-Größe für Request-Bodies (BodySizeLimitMiddleware).

### SEC-03: CORS- und HTTP-Header-Härtung (Mittel)
- **Problem:** Standardmäßig lieferte FastAPI keine Härtungs-Header (`X-Content-Type-Options`, `X-Frame-Options`, `Content-Security-Policy`, etc.) und keine explizite Trusted-Host-Validierung.
- **Lösung:** Hinzufügen von `SecurityHeadersMiddleware`, strikte Host-Prüfung (`TrustedHostMiddleware` mit konfigurierbarer Whitelist statt `["*"]`) und sichere CORS-Policy (niemals `allow_origins=['*']` zusammen mit `allow_credentials=True`).

### SEC-04: PII-Maskierung & Audit-Logging (Mittel)
- **Problem:** Beim Caching von Benutzerdaten (E-Mails, Tokens, Passwörter) könnten sensible Informationen in Protokollen auftauchen.
- **Lösung:** `PIIMaskingMiddleware` zur Maskierung sensibler Felder (`password`, `token`, `secret`, `email`, `authorization`) in Logs und Responses.

---

## 4. Sicherheits-Checkliste für den Produktionsbetrieb

- [x] Dateinamen-Generierung über kryptographischen Hash (SHA-256) gegen Path-Traversal.
- [x] Pfadgrenzen-Validierung (`is_relative_to`) für alle Disk-Operationen.
- [x] Pydantic-Validierung für Key-Format, Maximallängen und Tag-Struktur.
- [x] Content-Length / Request-Body-Begrenzung gegen Speicher-Erschöpfung.
- [x] Sicherheitsrelevante HTTP-Response-Header aktiv (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Strict-Transport-Security`).
- [x] Host-Header-Whitelist aktiv (kein Wildcard `*`).
- [x] Keine Wildcard-CORS mit `allow_credentials=True`.
- [x] PII-Maskierung in Logging & Traces implementiert.
