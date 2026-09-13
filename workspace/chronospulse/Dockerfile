# Multi-Stage Dockerfile fuer ChronosPulse API
# Stage 1: Build-Umgebung fuer Dependencies und Wheels
FROM python:3.11-slim AS builder

WORKDIR /build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt


# Stage 2: Minimales Produktions-Image
FROM python:3.11-slim AS runner

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/home/chronos/.local/bin:${PATH}" \
    PORT=8000 \
    HOST=0.0.0.0

# Installiere curl fuer Healthchecks und minimiere Angriffsflaeche
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-Root Benutzer 'chronos' anlegen (Principle of Least Privilege)
RUN groupadd -g 1001 chronos && \
    useradd -u 1001 -g chronos -m -s /bin/bash chronos

# Kopiere installierte Python-Pakete aus Builder
COPY --from=builder --chown=chronos:chronos /root/.local /home/chronos/.local

# Kopiere Anwendungsquellcode und erstelle Datenverzeichnis
COPY --chown=chronos:chronos app /app/app
RUN mkdir -p /app/data && chown -R chronos:chronos /app/data

# Wechsel zu Non-Root User
USER chronos

# Exponiere Service-Port
EXPOSE 8000

# Docker Healthcheck gemaess Vorgaben
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Produktions-Entrypoint mit Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers"]
