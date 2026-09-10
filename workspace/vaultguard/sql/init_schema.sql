-- VaultGuard PostgreSQL Schema
-- Datenbank-Initialisierungsskript für Secrets Management & Leak Prevention

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Tabelle: Users (Nutzerverwaltung & RBAC)
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) NOT NULL UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index für schnelles Nutzer-Lookup bei Authentifizierung
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);


-- 2. Tabelle: Secrets (Verschlüsselte Secrets & Key-Value-Store)
CREATE TABLE IF NOT EXISTS secrets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    key VARCHAR(255) NOT NULL,
    encrypted_value TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    environment VARCHAR(50) NOT NULL DEFAULT 'production',
    tags TEXT NULL DEFAULT NULL,
    expires_at TIMESTAMPTZ NULL DEFAULT NULL,
    is_revoked BOOLEAN NOT NULL DEFAULT FALSE,
    hmac_signature VARCHAR(255) NULL DEFAULT NULL,
    owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_secret_key_env_owner UNIQUE (key, environment, owner_id)
);

-- Indizes für Performanz bei Filtern & Lookups
CREATE INDEX IF NOT EXISTS idx_secrets_owner_id ON secrets(owner_id);
CREATE INDEX IF NOT EXISTS idx_secrets_key_env ON secrets(key, environment);
CREATE INDEX IF NOT EXISTS idx_secrets_is_revoked ON secrets(is_revoked);


-- 3. Tabelle: Secret Versions (Historie zur Secret-Rotation)
CREATE TABLE IF NOT EXISTS secret_versions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    secret_id UUID NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    encrypted_value TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_secret_version UNIQUE (secret_id, version)
);

CREATE INDEX IF NOT EXISTS idx_secret_versions_secret_id ON secret_versions(secret_id);


-- 4. Tabelle: Audit Logs (Unveränderliches Audit-Log für Governance)
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_type VARCHAR(100) NOT NULL,
    actor_id UUID NULL DEFAULT NULL REFERENCES users(id) ON DELETE SET NULL,
    secret_id UUID NULL DEFAULT NULL REFERENCES secrets(id) ON DELETE SET NULL,
    ip_address VARCHAR(45) NULL DEFAULT NULL,
    user_agent VARCHAR(512) NULL DEFAULT NULL,
    details JSONB NULL DEFAULT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indizes für Sicherheits-Analysen, Zeitreihen-Queries und Event-Filtering
CREATE INDEX IF NOT EXISTS idx_audit_logs_event_type ON audit_logs(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_logs_actor_id ON audit_logs(actor_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_secret_id ON audit_logs(secret_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at DESC);


-- 5. Tabelle: Leak Scans (Ergebnisse der Leak-Prevention-Scans)
CREATE TABLE IF NOT EXISTS leak_scans (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'PASSED',
    findings_count INTEGER NOT NULL DEFAULT 0,
    details JSONB NULL DEFAULT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_leak_scans_status ON leak_scans(status);
CREATE INDEX IF NOT EXISTS idx_leak_scans_created_at ON leak_scans(created_at DESC);
