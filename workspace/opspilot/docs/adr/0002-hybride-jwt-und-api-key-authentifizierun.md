# Hybride JWT und API-Key Authentifizierung

Status: Angenommen

## Kontext

Das SaaS-MVP unterstützt sowohl ein Web-Dashboard (menschliche Benutzer) als auch API-Zugriffe (Monitoring-Tools, Webhooks, CI/CD-Pipelines).

## Entscheidung

Hybride Authentifizierungs-Strategie: Stateless JWT Tokens (HS256) für Dashboard-Nutzer und gehashte API-Keys für maschinelle System-Schnittstellen.

## Konsequenzen

Ermöglicht unkomplizierten Browser-Zugriff via Bearer Tokens für das Dashboard und maschinellen API-Zugriff über X-API-Key für Automations-Webhooks und CLI-Tools. Endpunkte werden durch flexibel kombinationsfähige FastAPI Security Dependencies geschützt.
