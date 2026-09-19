# Modularer Monolith als Architekturstil

Status: Angenommen

## Kontext

Die Anwendung muss Webhooks empfangen, verarbeiten und verwalten. Ein Microservice-Ansatz wäre für den Start zu komplex, ein unstrukturierter Monolith zu schwer wartbar.

## Entscheidung

Modularer Monolith mit Clean Architecture. Die Domänen (Ingestion, Delivery, Management) werden in separaten Modulen innerhalb einer einzigen FastAPI-Anwendung gekapselt.

## Konsequenzen

Klare Trennung von Ingestion (schnelle Annahme), Delivery (asynchrone Verarbeitung) und Management-API. Einfacheres Deployment als Microservices, aber vorbereitet für spätere Skalierung.
