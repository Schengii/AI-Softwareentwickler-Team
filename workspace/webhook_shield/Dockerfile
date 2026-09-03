# Use multi-stage build for smaller image size
FROM python:3.11-slim AS builder

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc python3-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --user -r requirements.txt

FROM python:3.11-slim

WORKDIR /app
# Create non-root user
RUN groupadd -g 999 appuser && \
    useradd -r -u 999 -g appuser appuser && \
    chown -R appuser:appuser /app

COPY --from=builder /root/.local /home/appuser/.local
COPY . .
RUN chown -R appuser:appuser /app

ENV PATH=/home/appuser/.local/bin:$PATH
USER appuser

EXPOSE 8000

# Use gunicorn with uvicorn workers for production
CMD ["gunicorn", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "app.main:app", "--bind", "0.0.0.0:8000"]
