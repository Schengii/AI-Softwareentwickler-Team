# syntax=docker/dockerfile:1.7
##############################################
# Stage 1: builder - Dependencies kompilieren #
##############################################
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Build-Tools nur temporaer fuer Wheels mit nativen Extensions (z.B. sqlmodel-Deps)
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc build-essential \
    && rm -rf /var/lib/apt/lists/*

# In eigenes venv installieren, damit final-Stage nur den venv-Ordner kopiert
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

##############################################
# Stage 2: final - schlankes Runtime-Image    #
##############################################
FROM python:3.12-slim AS final

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    DATABASE_URL="sqlite:////app/data/keygate.db" \
    ALLOWED_ORIGINS="[]"

WORKDIR /app

# curl fuer HEALTHCHECK, danach apt-Cache entfernen
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root User nach Prinzip der minimalen Berechtigungen
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

COPY --from=builder /opt/venv /opt/venv
COPY --chown=appuser:appuser app ./app

# Datenverzeichnis fuer SQLite-Datei (per Volume gemountet), Owner appuser
RUN mkdir -p /app/data && chown -R appuser:appuser /app/data

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl --fail http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
