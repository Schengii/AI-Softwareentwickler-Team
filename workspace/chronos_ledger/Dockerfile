# ==============================================================================
# ChronosLedger - Production Multi-Stage Dockerfile
# ==============================================================================

# --- Stage 1: Build & Dependencies ---
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
RUN pip install --prefix=/install -r requirements.txt

# --- Stage 2: Runtime Minimal Image ---
FROM python:3.11-slim AS runner

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    HOST=0.0.0.0 \
    PYTHONPATH=/app

# Minimal packages needed at runtime (curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Principle of Least Privilege: Non-root User
RUN groupadd -g 10001 chronos && \
    useradd -u 10001 -g chronos -s /bin/bash -m chronos

# Copy installed python dependencies from builder
COPY --from=builder /install /usr/local

# Copy application source and static assets
COPY --chown=chronos:chronos app /app/app
COPY --chown=chronos:chronos README.md /app/README.md

# Ensure data directory for SQLite / local persistence exists with proper permissions
RUN mkdir -p /app/data && chown -R chronos:chronos /app/data

USER chronos

EXPOSE 8000

# Docker native Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

# Production WSGI/ASGI invocation with Graceful Shutdown handling
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "15"]
