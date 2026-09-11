# KeyGate Service

A production-ready FastAPI microservice for API Key management and token-bucket rate limiting.

## 🚀 Features
- **API Key Management:** Secure creation, listing, and revocation of API keys.
- **Security:** SHA-256 hashing with salt; keys are only displayed once in plaintext.
- **Rate Limiting:** In-memory Token-Bucket algorithm for high-performance request throttling.
- **Resilience:** Health checks, input validation, and OWASP-compliant security headers.
- **Deployment:** Docker-ready with `docker-compose` support.

## 📋 Project Structure
```text
keygate_service/
├── app/                # Application source code
├── tests/              # Unit and integration tests
│   └── load/           # Locust load testing scripts
├── docs/               # Architecture Decision Records (ADRs)
├── docker-compose.yml  # Deployment configuration
├── Dockerfile          # Container definition
└── requirements.txt    # Project dependencies
```

## ⚡ Quickstart

### Local Development
1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Run the service:**
   ```bash
   uvicorn app.main:app --reload
   ```

### Docker
```bash
docker-compose up --build
```

## ⚙️ Environment Variables
| Variable | Description | Default |
| :--- | :--- | :--- |
| `DATABASE_URL` | SQLite path | `sqlite:///./keygate.db` |
| `ALLOWED_ORIGINS` | CORS allowed origins | `["http://localhost:3000"]` |

## 📡 API Examples

### 1. Create API Key
```bash
curl -X POST http://localhost:8000/api/v1/keys \
     -H "Content-Type: application/json" \
     -d '{"name": "my-service", "roles": ["admin"], "quota": 100}'
```

### 2. Verify API Key
```bash
curl -X POST http://localhost:8000/api/v1/verify \
     -H "X-API-Key: kg_..."
```
*Returns `200 OK` (success) or `401 Unauthorized` / `429 Too Many Requests`.*

### 3. List Keys
```bash
curl -X GET http://localhost:8000/api/v1/keys
```

### 4. Revoke Key
```bash
curl -X DELETE http://localhost:8000/api/v1/keys/{key_id}
```

### 5. Health Check
```bash
curl -X GET http://localhost:8000/health
```

## 🧪 Testing
Run unit and integration tests:
```bash
pytest
```

Run load tests (requires `locust`):
```bash
locust -f tests/load/locustfile.py --host http://localhost:8000
```

## 📜 Changelog
All notable changes to this project will be documented in this file.

### [0.1.0] - 2024-05-22
- Initial release of KeyGate Service.
- Implemented API Key management and Token-Bucket rate limiting.
- Added Docker support and load testing scripts.
