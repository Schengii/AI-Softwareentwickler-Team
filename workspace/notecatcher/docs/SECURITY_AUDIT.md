# Security Audit Report

## Übersicht
Dieses Dokument enthält die Ergebnisse der Sicherheitsüberprüfung für den `notecatcher`-Microservice.

## Findings

### 1. Fehlende Längenbegrenzung bei der Input-Validierung (Hoch)
**Beschreibung:** Die Pydantic-Modelle für die Eingabevalidierung (`NoteCreate`) in `app/main.py` definieren keine maximale Länge (`max_length`) für die Felder `text` und `tag`. Dies ermöglicht es Angreifern, extrem große Payloads zu senden, was zu Speichererschöpfung (Denial of Service) führen kann, insbesondere da die Daten im In-Memory-Speicher gehalten werden.
**Betroffene Datei:** `app/main.py`
**Symbol:** `NoteCreate`
**Lösungsvorschlag:** Füge `max_length` zu den Feldern hinzu.
```python
class NoteCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)
    tag: str | None = Field(None, max_length=50)
```
**Aktion für Backend-Agent:** Bitte die Klasse `NoteCreate` in `app/main.py` entsprechend anpassen.

### 2. Fehlende sichere HTTP-Header (Mittel)
**Beschreibung:** Der Anwendung fehlen grundlegende Sicherheits-Header (wie HSTS, X-Content-Type-Options, X-Frame-Options), die vor gängigen Angriffen wie Clickjacking oder MIME-Sniffing schützen.
**Betroffene Datei:** `app/main.py`
**Lösungsvorschlag:** Implementierung einer Security-Middleware, die diese Header setzt. Die Middleware wurde in `app/core/security.py` bereitgestellt.
**Aktion für Backend-Agent:** Bitte die Middleware in `app/main.py` einbinden:
```python
from app.core.security import SecurityHeadersMiddleware

app.add_middleware(SecurityHeadersMiddleware)
```

## Security-Checkliste
- [ ] Input Validation: Längenbegrenzungen für Pydantic-Modelle definiert (Fix durch Backend ausstehend)
- [ ] Security Headers: Middleware implementiert und bereitgestellt (Einbindung durch Backend ausstehend)
- [x] Authentifizierung: Nicht gefordert laut Spezifikation
- [x] Datenbank-Sicherheit: In-Memory, keine SQL-Injection möglich
