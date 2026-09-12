# ==========================================
# Multi-Stage Production Dockerfile: OmniQueue
# Base Image: Python 3.11-slim (Debian Bookworm)
# ==========================================

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
RUN pip install --prefix=/install --no-warn-script-location -r requirements.txt


# --- Stage 2: Runtime Environment ---
FROM python:3.11-slim AS runner

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    APP_MODULE="app.main:app" \
    PYTHONPATH=/app

# Install runtime dependencies (curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Security: Create non-root system group and user
RUN groupadd -g 10001 omniqueue && \
    useradd -u 10001 -g omniqueue -s /bin/bash -m omniqueue

# Setup application directories and persistent storage
RUN mkdir -p /app/data /app/logs && \
    chown -R omniqueue:omniqueue /app

# Copy application source code and static assets
COPY --chown=omniqueue:omniqueue static /app/static
COPY --chown=omniqueue:omniqueue src /app/src
COPY --chown=omniqueue:omniqueue app /app/app

# Switch to non-privileged user
USER omniqueue:omniqueue

EXPOSE 8000

# Docker Healthcheck checking liveness & DB readiness via /healthz
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

# Production startup with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*"]
