# PulseFlow Gateway

A high-performance, real-time event and webhook gateway designed for reliability, idempotency, and observability.

## 🚀 Features
- **Webhook Ingestion:** Secure HMAC-SHA256 signature validation.
- **Idempotency:** Built-in protection against duplicate events.
- **Async Pipeline:** SQLite-backed worker queue with retry logic and DLQ.
- **Observability:** Real-time metrics and WebSocket live feed.
- **Dashboard:** Vanilla JS/CSS dashboard (WCAG 2.2 AA compliant).

## 🏗️ Architecture
The system uses an embedded SQLite database with WAL mode for high-concurrency event processing, avoiding external dependencies like Redis for initial deployments.

![Architecture](docs/architecture.png) *(Placeholder)*

## 🛠️ Quickstart

### Local Development
1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Run the application:**
   ```bash
   python -m pulseflow_gateway.main
   ```

### Docker
```bash
docker build -t pulseflow-gateway .
docker run -p 8000:8000 pulseflow-gateway
```

## 📡 API Reference

### Webhook Ingestion
`POST /api/v1/webhooks/{source_id}`

**Headers:**
- `X-Pulse-Signature`: HMAC-SHA256 signature.

**Example (cURL):**
```bash
curl -X POST http://localhost:8000/api/v1/webhooks/github \
  -H "X-Pulse-Signature: sha256=..." \
  -d '{"event": "push", "ref": "refs/heads/main"}'
```

## 🧪 Testing
Run unit tests:
```bash
pytest tests/unit
```

Run load tests (using Locust):
```bash
locust -f tests/load/locustfile.py
```

## 📝 Changelog
All notable changes to this project will be documented in this file.

### [0.1.0] - 2023-10-27
- Initial project structure setup.
- ADR 0001: Embedded SQLite + Asyncio Worker Queue.
- ADR 0002: Standalone Vanilla JS/CSS Dashboard.
- Added base requirements and load testing suite.
