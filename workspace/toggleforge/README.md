# ToggleForge

ToggleForge is a production-ready, fault-tolerant Feature Flag and Dynamic Configuration Gateway. It provides high-performance flag evaluation using consistent hashing for deterministic canary rollouts and comprehensive audit logging.

## 🚀 Features

- **Boolean Flags**: Simple on/off toggles.
- **Percentage Rollouts**: Deterministic canary releases using SHA256 consistent hashing.
- **User Targeting**: Rule-based evaluation (user_id, email domain, roles).
- **Audit Logging**: Track all configuration changes.
- **Accessibility**: Web dashboard compliant with WCAG 2.2 AA.

## 🏗️ Architecture

ToggleForge uses a stateless evaluation engine. By hashing `(flag_key + entity_id)`, the system ensures that the same user consistently falls into the same rollout bucket without requiring global state or session stickiness.

See [ADR-0001: SHA256 Consistent Hashing](docs/adr/0001-sha256-consistent-hashing-f-r-percentage.md) for details.

## 🛠️ Quick Start

### Prerequisites
- Python 3.10+
- `pip install -r requirements.txt`

### Running the Application
```bash
uvicorn app.main:app --reload
```

The dashboard will be available at `http://localhost:8000`.

## 📡 API Documentation

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/v1/flags` | Create a new feature flag |
| `GET` | `/api/v1/flags` | List all flags |
| `GET` | `/api/v1/flags/{key}` | Get flag details |
| `PUT` | `/api/v1/flags/{key}` | Update/Toggle flag |
| `POST` | `/api/v1/evaluate` | Evaluate flag for an entity |
| `GET` | `/api/v1/audit` | Retrieve audit trail |

## 📝 Changelog

### [0.1.0] - 2025-05-22
- Initial release of ToggleForge.
- Implemented core evaluation engine with SHA256 consistent hashing.
- Added REST API for flag management and evaluation.
- Added WCAG 2.2 AA compliant dashboard skeleton.
