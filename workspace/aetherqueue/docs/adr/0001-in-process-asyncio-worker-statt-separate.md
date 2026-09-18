# In-Process Asyncio Worker statt separatem Worker-Prozess

Status: Angenommen

## Kontext

Das System soll als In-Memory/SQLite Event- und Job-Orchestrator mit FastAPI fungieren. Es stellt sich die Frage, ob der Worker als separater Prozess (z.B. Celery) oder als In-Process Background-Task (asyncio) implementiert wird.

## Entscheidung

Wir implementieren den Worker als In-Process asyncio Background-Task innerhalb der FastAPI-Anwendung.

## Konsequenzen

Einfache Bereitstellung als Single-Node-Applikation. Skaliert nicht über mehrere Maschinen hinweg ohne externe Datenbank. Bei Absturz des Prozesses werden laufende Jobs beim Neustart als FAILED/DLQ oder PENDING markiert (benötigt Recovery-Logik).
