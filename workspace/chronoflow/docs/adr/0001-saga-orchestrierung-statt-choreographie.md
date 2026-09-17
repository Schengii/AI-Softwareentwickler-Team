# Saga Orchestrierung statt Choreographie

Status: Angenommen

## Kontext

Wir benötigen eine Saga-Workflow-Engine. Zur Wahl stehen Choreographie (Event-basiert, dezentral) und Orchestrierung (zentraler Controller).

## Entscheidung

Wir nutzen Orchestrierung (Saga Orchestrator), da dies die Statusverfolgung für das Web-Dashboard stark vereinfacht und besser zu einer monolithischen FastAPI-Anwendung mit einer zentralen Datenbank passt.

## Konsequenzen

Zentraler Orchestrator ist ein Single Point of Failure, aber in einem Monolithen ohnehin gegeben. Leichteres Debugging und Status-Tracking für das Dashboard.
