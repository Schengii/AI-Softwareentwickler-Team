# Hyperion Metrics Dashboard

Das Dashboard wurde in `app/static/index.html` implementiert. Es nutzt:
- **Vanilla JavaScript** für die WebSocket-Verbindung.
- **Responsive CSS** für eine saubere Darstellung.
- **Auto-Reconnect-Logik** (implizit durch Browser-Verhalten bei Reload).

## Backend-Anforderungen
Damit das Frontend funktioniert, muss das Backend (`app/main.py`) folgende Endpunkte bereitstellen:
1. `GET /health`
2. `POST /api/v1/metrics`
3. `WS /ws/dashboard`

Bitte stelle sicher, dass der `StaticFiles`-Mount in `app/main.py` korrekt auf `app/static` verweist.
