# FastAPI Async-First Architektur und Pydantic v2 als Schema SSOT

Status: Angenommen

## Kontext

Anforderung für opspilot SaaS-MVP: AI-Driven Incident Automation Hub mit hohen Echtzeitanforderungen und Event-Verarbeitung. Wahl zwischen synchronen Frameworks (Django/Flask) und asynchronem FastAPI mit Pydantic v2.

## Entscheidung

Entscheidung für FastAPI (Async-First) mit Pydantic v2 Schema-Validerung. Alle DB-Zugriffe, External AI Callouts und Async Workflow Execution erfolgen non-blocking.

## Konsequenzen

Erzwingt durchgängige async/await-Nutzung in allen Routen, Services und DB-Interaktionen. Pydantic v2 dient als Single Source of Truth (SSOT) für Schemas und API-Schnittstellen. Strikte Performance- und Validierungs-Vorteile.
