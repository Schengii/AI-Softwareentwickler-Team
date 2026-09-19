# Append-Only Audit-Trail mit SQLite-Triggern

Status: Angenommen

## Kontext

Ein unveränderlicher Audit-Trail aller Zugriffe (Zero-Trust) wird gefordert, um Nachvollziehbarkeit bei Security-Incidents zu garantieren.

## Entscheidung

Implementierung des Audit-Trails als Append-Only-Tabelle in SQLite, abgesichert durch SQLite-Trigger, die UPDATE und DELETE Operationen auf dieser Tabelle blockieren.

## Konsequenzen

Audit-Tabellen wachsen kontinuierlich. Es dürfen keine DELETE/UPDATE-Operationen auf Audit-Tabellen in der Applikation existieren. Bei SQLite kann dies durch Trigger (Prevent Update/Delete) auf Datenbankebene erzwungen werden.
