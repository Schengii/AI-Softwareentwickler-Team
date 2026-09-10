# AuditLog Sentinel

AuditLog Sentinel is a production-ready, high-performance audit logging and monitoring system designed for centralized log management, real-time analysis, and secure storage.

## 🚀 Features

- **Centralized Logging:** Aggregate logs from multiple services.
- **Real-time Monitoring:** Dashboard with filtering and search capabilities.
- **Secure Storage:** PostgreSQL-backed storage with strict data integrity.
- **Accessibility-First:** Built with WCAG 2.2 AA standards in mind.
- **Scalable API:** FastAPI-based backend with OpenAPI documentation.

## 🛠️ Tech Stack

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy, PostgreSQL, Pydantic
- **Frontend:** React, TypeScript, Tailwind CSS, Vite, Chart.js
- **Infrastructure:** Docker, Alembic (Migrations)

## 📋 Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 15+

## ⚙️ Local Setup

### Backend
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
# Configure environment variables in .env
alembic upgrade head
uvicorn app.main:app --reload
```

### Frontend
```bash
npm install
npm run dev
```

## 📚 API Documentation
Once the backend is running, access the interactive API documentation at:
`http://localhost:8000/docs`

## 🚀 Deployment
The project is container-ready. Use the provided `Dockerfile` and `docker-compose.yml` (if applicable) to deploy to your production environment. Ensure `SECRET_KEY` and database credentials are set via environment variables.

## 📝 Changelog
All notable changes to this project will be documented in this file.

### [0.1.0] - 2023-10-27
- Initial project structure setup.
- Backend foundation (FastAPI, SQLAlchemy, Pydantic).
- Frontend foundation (React, Tailwind, Vite).
- ADRs for technology choices established.
