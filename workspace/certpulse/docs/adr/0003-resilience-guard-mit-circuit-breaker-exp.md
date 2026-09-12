# Resilience Guard mit Circuit Breaker & Exponential Backoff für Webhooks

Status: Angenommen

## Kontext

CertPulse sendet Webhook-Benachrichtigungen an Slack, Discord oder Custom HTTP-Endpunkte bei kritischem Zertifikatsstatus. Wenn Empfänger nicht erreichbar sind oder drosseln, dürfen Hintergrundprüfungen nicht blockieren.

## Entscheidung

Implementierung eines eigenständigen Resilience Guards mit In-Memory Circuit Breaker, Exponential Backoff und Jitter auf HTTPX-Basis.

## Konsequenzen

Externe Webhook-Ausfälle blockieren weder den Prüflauf noch überlasten sie gescheiterte Endpunkte. Bei wiederholten Fehlern schützt der Circuit Breaker das System.
