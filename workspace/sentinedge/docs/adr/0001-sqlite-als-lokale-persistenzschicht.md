# SQLite als lokale Persistenzschicht

Status: Angenommen

## Kontext

Der Server soll als 'lokaler' Zero-Trust Secrets- und Feature-Flag-Server fungieren. Eine externe Datenbank würde die Komplexität und den Setup-Aufwand erhöhen.

## Entscheidung

Verwendung von SQLite (via SQLAlchemy) als primäre Datenbank für Secrets, Feature-Flags, RBAC und Audit-Logs.

## Konsequenzen

Einfache Installation ohne externe Abhängigkeiten (kein Docker/PostgreSQL nötig). Gleichzeitige Schreibzugriffe sind limitiert, was für einen lokalen Server akzeptabel ist. Backups sind einfache Dateikopien.
