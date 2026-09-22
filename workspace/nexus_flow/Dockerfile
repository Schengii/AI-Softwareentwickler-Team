# Multi-Stage Dockerfile für nexus_flow (FastAPI & SQLite Event Service)
# Stage 1: Build-Umgebung für Wheels & Abhängigkeiten
FROM python:3.11-slim AS builder

WORKDIR /build

# Systemabhängigkeiten für den Build-Prozess
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# Stage 2: Produktions-Laufzeitumgebung
FROM python:3.11-slim AS runner

LABEL maintainer="Nexus Flow DevOps Team"
LABEL description="Produktions-Container für Nexus Flow Event-Ingestion und Webhook-Service"

WORKDIR /app

# Basis-Tools für Healthcheck & curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-Root Benutzer und Gruppe anlegen (Sicherheit: Principle of Least Privilege)
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup --no-create-home appuser

# Kopiere installierte Python-Pakete aus Builder-Stage
COPY --from=builder /root/.local /home/appuser/.local

# Persistenzverzeichnis für SQLite erstellen und Berechtigungen vergeben
RUN mkdir -p /data && chown -R appuser:appgroup /data && chmod 770 /data

# Applikationscode kopieren und Eigentümerschaft setzen
COPY --chown=appuser:appgroup app/ /app/app/

# PATH für Python User-Packages anpassen
ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    HOST=0.0.0.0

# Non-Root Benutzer aktivieren
USER appuser

# Exponiere Service-Port
EXPOSE 8000

# Docker-Healthcheck auf /health
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Startkommando mit Signalweiterleitung (Graceful Shutdown)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
