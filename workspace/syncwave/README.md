# Syncwave

Syncwave ist eine moderne, hochperformante Event- & Log-Monitoring-Plattform für Microservices. Sie bietet Echtzeit-Einblicke durch WebSocket-Streaming und eine persistente Historie via SQLite.

## 🚀 Features

- **Live-Monitoring**: WebSocket-basierter Log-Stream mit geringer Latenz.
- **Persistenz**: Historische Log-Daten werden in einer SQLite-Datenbank gespeichert.
- **Statistiken**: Echtzeit-KPIs (Events/Sekunde, Fehlerquote).
- **Barrierefreiheit**: WCAG 2.2 Level AA konformes Dashboard.

## 🛠️ Installation

```bash
# Repository klonen
git clone <repository-url>
cd syncwave

# Virtuelle Umgebung erstellen und aktivieren
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Abhängigkeiten installieren
pip install -r requirements.txt
```

## 🏃‍♂️ Starten

```bash
# Anwendung starten
uvicorn app.main:app --reload
```

Das Dashboard ist unter `http://localhost:8000` erreichbar.

## 🔌 API-Dokumentation

### REST-API
- `POST /api/v1/logs`: Erfasst ein neues Log-Event.
  - Payload: `{"level": "INFO|WARN|ERROR", "service_name": "string", "payload": "string"}`
- `GET /api/v1/logs`: Ruft historische Logs ab (Filter: `service_name`, `level`).
- `GET /api/v1/stats`: Liefert aktuelle Statistiken (Events/Sekunde, Error-Rate).

### WebSocket
- `WS /ws/logs`: Live-Stream aller eingehenden Log-Events.

## 🧪 Tests

```bash
pytest
```

## 📝 Changelog

### [0.1.0] - 2024-05-22
- Initiales Release
- Grundlegende REST-API & WebSocket-Integration
- SQLite-Persistenz mit SQLAlchemy 2.0
- WCAG-konformes Dashboard-Grundgerüst
