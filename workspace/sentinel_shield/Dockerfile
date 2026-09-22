# ==========================================
# Stage 1: Build-Umgebung (Multi-Stage)
# ==========================================
FROM python:3.11-slim AS builder

WORKDIR /build

# System-Abhängigkeiten für Build-Prozess
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Wheel-Pakete bauen, um im Runner schlank und ohne Compiler auszukommen
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ==========================================
# Stage 2: Minimales Produktions-Image
# ==========================================
FROM python:3.11-slim AS runner

WORKDIR /app

# Minimal notwendige Runtime-Tools (curl für Healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Prinzip der minimalen Rechte: Non-Root User anlegen
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /sbin/nologin -M appuser

# Python-Pakete aus Builder-Stage übernehmen
COPY --from=builder /root/.local /home/appuser/.local

# Umgebungsvariablen setzen
ENV PATH="/home/appuser/.local/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

# Anwendungscode kopieren und Berechtigungen setzen
COPY --chown=appuser:appgroup app/ ./app/

# Ownership für appuser sicherstellen
RUN chown -R appuser:appgroup /app /home/appuser

# Wechsel zu Non-Root User
USER appuser

# Exponierter Port
EXPOSE 8000

# Docker-Healthcheck gemäß Best Practice
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Produktions-Start mit Uvicorn (Einstiegspunkt app.main:app)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--no-access-log"]
