# Resilience Guard mit Async Circuit Breaker Pattern

Status: Angenommen

## Kontext

Incident-Automation erfordert den Aufruf externer KI-Modelle und Third-Party Integrations. Wenn diese ausfallen oder laggen, darf das opspilot-System nicht blockieren.

## Entscheidung

Implementierung eines dedizierten Resilience Guards mit Async Circuit Breaker Pattern für alle ausgehenden KI- und Incident-Workflow-Aufrufe.

## Konsequenzen

Verhindert Cascading Failures bei Fehlern externer AI-APIs (OpenAI/Anthropic) oder Webhook-Zielen. Automatische Zustandsübergänge (CLOSED, OPEN, HALF-OPEN) mit konfigurierbarem Timeout und Failure Threshold. Steuerung via Environment-Variablen.
