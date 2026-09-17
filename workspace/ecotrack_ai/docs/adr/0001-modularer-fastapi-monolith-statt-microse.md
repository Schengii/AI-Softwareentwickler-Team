# Modularer FastAPI-Monolith statt Microservices für EcoTrack Gateway

Status: Angenommen

## Kontext

EcoTrack AI benötigt ein Fleet Gateway mit ML-Prognose, FinOps-Kalkulation und PWA-Serving. Zur Wahl standen Microservices-Architektur vs. Modularer FastAPI-Monolith.

## Entscheidung

Modularer Monolith auf Basis von FastAPI, SQLite/SQLAlchemy 2.0 und Pydantic V2. Alle Domänen (Fleet, Telemetry, Emissions, FinOps, ML-Analytics) werden als entkoppelte Router und Services in einem zentralen Gateway orchestriert.

## Konsequenzen

Vorteile: Geringe Latenz, einfache lokale und CI/CD-Ausführung, keine verteilten Transaktionen, einfache PWA-Integration. Nachteile: Bei massiver horizontaler Skalierung muss später in Microservices refaktoriert werden. Spätere Änderungen müssen Modulgrenzen in app/ sauber halten.
