# 📖 API- & Systemdokumentation: FastAPI Health-Monitor

## 📐 Architektur-Überblick

Der Health-Monitor basiert auf einer asynchronen ASGI-Architektur mit FastAPI, SQLite (via `aiosqlite` & `SQLAlchemy`) und einem WebSocket-Event-Bus zur Übertragung von Metriken an das React-Frontend.

---

## 🔌 API-Endpunkte

### 1. System Health Status
- **URL:** `/health`
- **Methode:** `GET`
- **Beschreibung:** Liefert den Eigenstatus des Monitor-Dienstes.
- **Response (200 OK):**
  