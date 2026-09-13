# SQLite (Async) statt PostgreSQL

Status: Angenommen

## Kontext

Eine relationale Datenbank für Incidents wird benötigt. Zur Auswahl standen PostgreSQL (leistungsstark, extern) und SQLite (eingebettet).

## Entscheidung

Wir entscheiden uns für SQLite in Kombination mit SQLAlchemys Async-Erweiterung (aiosqlite).

## Konsequenzen

Einfaches Setup ohne externen Datenbankserver, ideal für eine in sich geschlossene Anwendung. Die Nebenläufigkeit (Concurrency) bei Schreibzugriffen ist im Vergleich zu PostgreSQL eingeschränkt, aber für ein Dashboard mit moderater Schreiblast ausreichend.
