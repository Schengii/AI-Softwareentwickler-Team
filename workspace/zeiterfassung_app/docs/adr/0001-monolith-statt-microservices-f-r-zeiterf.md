# Monolith statt Microservices für Zeiterfassungs-App

Status: Angenommen

## Kontext

Die Anwendung ist eine typische SaaS‑Zeiterfassung für Selbstständige mit begrenztem Nutzer‑ und Datenvolumen. Anforderungen umfassen schnelle Entwicklung, einfache Wartung und geringe Infrastruktur‑Komplexität.

## Entscheidung

Monolithische Architektur mit FastAPI‑Backend und React‑Frontend wird gewählt.

## Konsequenzen

Einfachere CI/CD, geringere Ops‑Kosten, schnellere Feature‑Delivery. Skalierung über horizontale Replication des gesamten Services. Bei starkem Wachstum kann später zu Microservices migriert werden.
