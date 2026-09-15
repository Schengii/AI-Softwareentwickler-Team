# Dev Snippet Vault

Eine moderne, performante Code-Snippet- und Wissensdatenbank für Entwickler.

## 🚀 Features
- **Volltextsuche:** Dank SQLite FTS5-Integration.
- **Syntax-Highlighting:** Integriert im Dashboard.
- **Dark-Mode UI:** Optimiert für Entwickler-Workflows.
- **REST API:** FastAPI-basiert mit Pydantic v2 Validierung.

## 🛠 Tech Stack
- **Backend:** FastAPI, SQLAlchemy, SQLite (FTS5)
- **Frontend:** HTML5, CSS (Dark Mode), JS
- **Validierung:** Pydantic v2

## 📦 Installation & Start

### Lokal
1. **Abhängigkeiten:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Start:**
   ```bash
   uvicorn app.main:app --reload
   ```

### Docker
```bash
docker build -t dev-snippet-vault .
docker run -p 8000:8000 dev-snippet-vault
```

## 📚 API Dokumentation
Nach dem Start ist die interaktive API-Dokumentation unter `/docs` (Swagger UI) verfügbar.

## ⚖️ Architektur-Entscheidungen (ADRs)
- [ADR 0001: SQLite FTS5 für Volltextsuche](docs/adr/0001-sqlite-fts5-f-r-volltextsuche-statt-exte.md)

## 📝 Changelog

### [0.1.0] - 2025-05-15
- Initiales Release: Grundgerüst mit FastAPI, SQLite FTS5 und Basis-Dashboard.
