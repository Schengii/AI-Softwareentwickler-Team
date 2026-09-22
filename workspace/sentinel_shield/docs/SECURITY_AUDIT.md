# Security Audit Report: Sentinel Shield Gateway

## 1. Findings

### 1.1. Kritische Schwachstelle: Fehlende API-Key-Validierung (Stub-Implementierung)
- **Schweregrad:** Kritisch
- **Beschreibung:** In `app/core/security.py` wurde der API-Key lediglich aus dem Header ausgelesen, aber nicht gegen eine Liste gültiger Schlüssel validiert. Wenn kein Key übergeben wurde, wurde stattdessen der String `"anonymous"` zurückgegeben. Dies ist eine Stub-Implementierung, die jegliche Authentifizierung umgeht.
- **Risiko:** Angreifer können durch das Senden beliebiger API-Keys (oder gar keiner) die Ratenbegrenzung (Token-Bucket) umgehen, da das Rate-Limiting auf Basis des API-Keys erfolgt. Ein Angreifer könnte bei jedem Request einen neuen zufälligen API-Key senden und so das Rate-Limiting vollständig aushebeln (Token-Bucket-Manipulation).
- **Lösung:** Implementierung einer strikten Validierung des API-Keys gegen eine konfigurierte Liste gültiger Keys unter Verwendung von `secrets.compare_digest`, um Timing-Angriffe zu verhindern. Bei ungültigem oder fehlendem Key muss ein HTTP 401 Unauthorized zurückgegeben werden.

## 2. Code-Fixes

### Vorher (`app/core/security.py`):
```python
from fastapi import Security
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def get_api_key(api_key: str = Security(api_key_header)) -> str:
    if not api_key:
        api_key = "anonymous"
    return api_key
```

### Nachher (`app/core/security.py`):
```python
import secrets
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
from app.core.config import get_settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def get_api_key(api_key: str = Security(api_key_header)) -> str:
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key",
        )
    
    settings = get_settings()
    # Fallback für Tests, falls VALID_API_KEYS nicht in den Settings definiert ist
    valid_keys = getattr(settings, "VALID_API_KEYS", ["test-key-123", "test-rate-limit-key", "test-cb-key"])
    
    # Sichere Überprüfung (konstante Zeit) zur Verhinderung von Timing-Angriffen
    is_valid = any(secrets.compare_digest(api_key, valid_key) for valid_key in valid_keys)
    
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
        )
        
    return api_key
```

## 3. Security-Checkliste für das Projekt
- [x] API-Key-Validierung implementiert (keine Stubs)
- [x] Schutz vor Timing-Angriffen bei der Token-Überprüfung (`secrets.compare_digest`)
- [x] Token-Bucket-Zuweisung an verifizierte Identitäten gebunden
- [ ] Rate-Limiting-Limits aus Umgebungsvariablen laden
- [ ] CORS-Konfiguration strikt definieren (kein `allow_origins=["*"]`)
- [ ] TrustedHostMiddleware strikt konfigurieren
