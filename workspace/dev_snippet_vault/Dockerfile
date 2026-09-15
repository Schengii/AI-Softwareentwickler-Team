# Multi-Stage / Hardened Production Dockerfile für dev_snippet_vault
FROM python:3.11-slim

# Umgebungsvariablen setzen: Python-Pufferung deaktivieren, Bytecode minimieren
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# Arbeitsverzeichnis definieren
WORKDIR /app

# Nicht-privilegierten Systembenutzer anlegen (Principle of Least Privilege)
RUN groupadd --system --gid 10001 appgroup && \
    useradd --system --uid 10001 --gid 10001 --no-create-home appuser

# Abhängigkeiten installieren (ohne Cache zur Image-Optimierung)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Anwendungs- und Frontend-Dateien kopieren
COPY app/ ./app/
COPY public/ ./public/

# Eigentumsrechte an Nicht-Root-Benutzer übertragen
RUN chown -R appuser:appgroup /app

# Auf unprivilegierten Benutzer umschalten
USER appuser

# API-Port exponieren
EXPOSE 8000

# Container Healthcheck (nutzt native Python urllib, kein externes curl nötig)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

# Startbefehl für FastAPI mit Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
