CREATE TABLE IF NOT EXISTS webhooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint_path TEXT NOT NULL UNIQUE,
    hmac_secret TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS delivery_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    webhook_id INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    headers_json TEXT NOT NULL,
    status TEXT NOT NULL,
    retry_count INTEGER DEFAULT 0,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (webhook_id) REFERENCES webhooks(id)
);

CREATE INDEX IF NOT EXISTS idx_delivery_logs_webhook_id ON delivery_logs(webhook_id);
CREATE INDEX IF NOT EXISTS idx_delivery_logs_timestamp ON delivery_logs(timestamp);
