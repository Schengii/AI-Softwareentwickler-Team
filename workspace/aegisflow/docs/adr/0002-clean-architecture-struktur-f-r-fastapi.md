# Clean Architecture Struktur für FastAPI

Status: Angenommen

## Kontext

Das Projekt erfordert eine klare Trennung nach Fachbereichen und Schichten, um die Komplexität des Event-Brokers beherrschbar zu machen und parallele Entwicklung zu ermöglichen.

## Entscheidung

Wir strukturieren das Projekt strikt nach Clean Architecture in die Schichten `routers/` (API), `services/` (Business Logic), `models/` (Pydantic/SQLAlchemy) und `storage/` (Datenbankzugriff).

## Konsequenzen

Hohe Testbarkeit und Wartbarkeit durch Entkopplung. Erfordert strikte Disziplin bei den Importen, um Zirkelbezüge zu vermeiden. Die `interface_contract.json` dient als verbindliche Schnittstelle zwischen den Schichten.
