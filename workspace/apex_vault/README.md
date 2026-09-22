# Apex Vault

Apex Vault ist ein hochsicherer, produktionsreifer Secrets- und Key-Management-Dienst, entwickelt mit FastAPI, SQLAlchemy und SQLite. Er bietet eine robuste Architektur zur sicheren Speicherung und Verwaltung von Geheimnissen unter Verwendung von AES-256-GCM Verschlüsselung.

## 🚀 Features

- **Sichere Speicherung:** Secrets werden niemals im Klartext in der Datenbank gespeichert.
- **AES-256-GCM Verschlüsselung:** Integrierte Krypto-Engine für maximale Datensicherheit.
- **Audit-Logging:** Vollständige Nachverfolgbarkeit aller Zugriffe und Aktionen.
- **TTL-Unterstützung:** Automatische Ablaufsteuerung für Secrets.
- **Master-API-Key:** Authentifizierung über dedizierten Master-Key.

## 🛠️ Installation

1. Repository klonen:
   ```bash
   git clone <repo-url>
   cd apex_vault
   ```

2. Abhängigkeiten installieren:
   ```bash
   pip install -r requirements.txt
   ```

3. Umgebungsvariablen konfigurieren (`.env` erstellen):
   ```bash
   cp .env.example .env
   # MASTER_KEY und DATABASE_URL anpassen
   ```

4. Server starten:
   ```bash
   uvicorn app.main:app --reload
   ```

## 🔐 Envelope Encryption Konzept

Apex Vault nutzt ein Envelope-Encryption-Modell:
1. **Master Key:** Ein vom Administrator definierter Schlüssel dient als Root-of-Trust.
2. **Datenverschlüsselung:** Jeder Secret-Wert wird mit einem eindeutigen, zufällig generierten Data Encryption Key (DEK) verschlüsselt.
3. **Key Wrapping:** Der DEK selbst wird mit dem Master Key verschlüsselt und zusammen mit dem verschlüsselten Secret gespeichert.

## 📡 API-Endpunkte

Alle Endpunkte befinden sich unter `/api/v1`.

### Secrets verwalten
- `POST /api/v1/secrets`: Neues Secret erstellen.
- `GET /api/v1/secrets/{name}`: Secret abrufen.
- `POST /api/v1/secrets/{name}/revoke`: Secret widerrufen.

### Audit
- `GET /api/v1/audit`: Audit-Logs abrufen.

### System
- `GET /health`: Status-Check.

## 📝 Changelog

### [0.1.0] - 2026-09-22
- Initiales Release des Apex Vault Dienstes.
- Implementierung der Krypto-Engine (AES-256-GCM).
- Basis-API-Struktur mit FastAPI.
- Audit-Logging und TTL-Unterstützung.
