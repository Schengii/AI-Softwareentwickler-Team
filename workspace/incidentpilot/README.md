# IncidentPilot

IncidentPilot is an automated incident monitoring and response platform designed to streamline system reliability and alert management.

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.12+

### Local Development (Python)
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Start the application:
   ```bash
   uvicorn app.main:app --reload
   ```

### Containerized Deployment
Start the full stack using Docker Compose:
```bash
docker-compose up --build
```

## 🧪 Testing
Run the test suite to verify the application integrity:
```bash
pytest
```

## 🏗️ Architecture
The project follows a modular architecture:
- **Backend**: FastAPI-based service with asynchronous database support.
- **Frontend**: React SPA with Vite.
- **Documentation**: Detailed guides and ADRs are located in the `docs/` and `architecture/` directories.

## 📚 Documentation
- [Developer Guide](docs/DEVELOPER_GUIDE.md)
- [Architecture Overview](architecture/README.md)
- [API Specification](architecture/openapi.yaml)
