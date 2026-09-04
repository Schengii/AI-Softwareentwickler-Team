# Microservices statt Monolith für CloudVault

Status: Angenommen

## Kontext

Anforderung an eine sichere, skalierbare File-Sharing-Plattform. Alternative: Monolith. Entscheidung für Microservices aufgrund der Sicherheitsanforderungen (Isolation) und Skalierbarkeit.

## Entscheidung

Microservices-Architektur mit API-Gateway.

## Konsequenzen

Ermöglicht klare Trennung von Verantwortlichkeiten, Skalierbarkeit der Services und einfache Wartbarkeit. Erhöht jedoch die Komplexität durch Netzwerk-Overhead und Service-Discovery.
