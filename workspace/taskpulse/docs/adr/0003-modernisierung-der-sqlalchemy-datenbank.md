# Modernisierung der SQLAlchemy-Datenbank-Initialisierung

Status: Angenommen

## Kontext

Die bisherige `declarative_base()`-Funktion ist veraltet (MovedIn20Warning). Zudem fehlte eine saubere Initialisierungslogik für die Datenbanktabellen.

## Entscheidung

Umstellung auf `DeclarativeBase` und explizite `init_db()`-Funktion, die im FastAPI-Startup-Event aufgerufen wird.

## Konsequenzen

Die Verwendung von DeclarativeBase ist der moderne Standard in SQLAlchemy 2.0 und vermeidet Deprecation-Warnungen. Die Initialisierung im Startup-Event stellt sicher, dass die Datenbank bereit ist, bevor die App Anfragen entgegennimmt.
