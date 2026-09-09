# Microservices Architecture statt Monolith

Status: Angenommen

## Kontext

Die Plattform muss skalierbar, hochverfügbar und modulare Governance‑Features (User‑Management, Policy‑Engine, Dashboard, SAST‑Job‑Runner) unterstützen.

## Entscheidung

Microservices-Architektur mit unabhängigen Services (Auth, User, Policy, Dashboard, SAST‑Runner) gewählt.

## Konsequenzen

Erhöhte Komplexität beim Deployment, erfordert Service‑Discovery und Orchestrierung (Kubernetes). Vorteile: unabhängige Skalierung, klare Verantwortlichkeiten, leichteres Team‑Ownership.
