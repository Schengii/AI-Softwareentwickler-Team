# Multi-Stage Containerisierung mit Non-Root User und Resource Limits

Status: Angenommen

## Kontext

Die OmniMetric-Engine muss als containerisierter Dienst hochverfügbar, sicher und performant in einer Cloud-/On-Premise-Umgebung betrieben werden können. Es wurde nach der optimalen Packaging-Strategie gesucht.

## Entscheidung

Es wird ein Multi-Stage Docker Build basierend auf python:3.11-slim verwendet. Unnötige Compilertools verbleiben in der Builder-Stage. Der Runtime-Container läuft mit einem isolierten Non-Root-User ('appuser', UID 10001) und verfügt über definierte Docker-Healthchecks sowie Resource Limits in docker-compose.yml.

## Konsequenzen

Vorteile:
- Erhöhte Sicherheit durch Ausführung als non-root User (UID 10001) und minimales Base-Image.
- Optimierte Image-Größe und schnelles Deployment durch Multi-Stage Build.
- Verhindert Resource Starvation im Cluster/Host durch strikte Limits (2 CPUs, 1GB RAM).
- Integrierte Healthchecks zur automatischen Wiederherstellung bei Ausfällen.

Einschränkungen:
- Erweiterungen mit C-Extensions erfordern vorübergehende Build-Abhängigkeiten in Stage 1.
