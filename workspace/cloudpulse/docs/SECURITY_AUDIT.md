# Security Audit Report - CloudPulse

## 1. Findings & Schweregrade

### 1.1 Kritisch: Unsichere CORS-Konfiguration
- **Beschreibung**: In `app/main.py` wurde `allow_origins=["*"]` in Kombination mit `allow_credentials=True` konfiguriert. Dies ist ein erhebliches Sicherheitsrisiko und wird von FastAPI standardmäßig blockiert (bzw. führt zu Fehlern), da es Cross-Origin-Angriffe ermöglicht.
- **Lösung**: Explizite Whitelist über `pydantic-settings` implementiert.

### 1.2 Hoch: Fehlender SSRF-Schutz (Server-Side Request Forgery)
- **Beschreibung**: Der Endpunkt zum Erstellen von Monitoren akzeptiert beliebige URLs. Ein Angreifer könnte interne IPs (z.B. `127.0.0.1`, `192.168.x.x`) oder Cloud-Metadaten-Dienste (z.B. AWS `169.254.169.254`) anpingen und so das interne Netzwerk ausspähen.
- **Lösung**: Implementierung der Funktion `validate_ssrf_safe_url` in `app/core/security.py`, die Hostnamen auflöst und private/lokale IPs blockiert.

### 1.3 Mittel: Hardcodierte Konfiguration
- **Beschreibung**: CORS-Origins und andere Einstellungen sollten nicht hardcodiert sein.
- **Lösung**: Einführung von `BaseSettings` für umgebungsbasierte Konfiguration.

## 2. Code-Fixes

- **`app/core/security.py`**: Neue Datei mit SSRF-Validierung und Settings-Management.
- **`app/main.py`**: CORS-Middleware auf `settings.CORS_ORIGINS` umgestellt.
- **`app/api/endpoints.py`**: SSRF-Validierung vor dem Speichern der Monitor-URL integriert.

## 3. Security-Checkliste für das Projekt
- [x] CORS restriktiv konfiguriert
- [x] SSRF-Schutz für ausgehende Requests (Monitor-URLs)
- [x] Keine Secrets im Code (Nutzung von `.env` / `BaseSettings`)
- [ ] Rate-Limiting für API-Endpunkte (Empfehlung für die Zukunft)
- [ ] Authentifizierung/Autorisierung für das Dashboard (Empfehlung für die Zukunft)
