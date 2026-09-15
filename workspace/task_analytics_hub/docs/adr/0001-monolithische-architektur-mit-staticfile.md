# Monolithische Architektur mit StaticFiles-Mount für Frontend

Status: Angenommen

## Kontext

Das System erfordert ein Backend (FastAPI) und ein Frontend (Dashboard). Es soll als Docker-Container deployt werden.

## Entscheidung

Wahl einer monolithischen Architektur, bei der das FastAPI-Backend das Frontend über StaticFiles ausliefert.

## Konsequenzen

Einfacheres Deployment (ein Docker-Container), geringere Latenz bei der Auslieferung, aber begrenzte unabhängige Skalierbarkeit von Frontend und Backend.
